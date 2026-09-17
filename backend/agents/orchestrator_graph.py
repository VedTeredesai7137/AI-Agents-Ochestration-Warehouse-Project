"""Per-simulation LangGraph worker, validated actions, bounded repair and FIFO crises."""
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
import json
import threading
import time
from typing import TypedDict

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from backend.agents.action_executor import ActionExecutor, ExecutionError
from backend.agents.llm_client import OllamaClient
from backend.agents.plans import CrisisPlan, PlanError, parse_plan, generation_schema
from backend.agents.plan_validator import PlanValidator, WorldSnapshot
from backend.core.events import logger


class OrchestratorState(TypedDict, total=False):
    run_id: str
    crisis_kind: str
    crisis_id: str
    plan_id: str | None
    crisis_location: list
    affected_robots: list
    proposed_plan: dict | None
    validation_score: float | None
    validation_status: str
    validation_issues: list
    validation_report: dict | None
    human_approved: bool | None
    approval_source: str | None
    active_node: str
    error: str | None
    error_code: str | None
    regeneration_count: int
    rejection_count: int
    attempts: int
    fallback_used: bool
    fallback_reason: str | None
    executed_actions: int
    rejected_strategies: list


class CrisisKind(str, Enum):
    DEADLOCK = "DEADLOCK"
    STRUCTURAL_COLLAPSE = "STRUCTURAL_COLLAPSE"


@dataclass
class CrisisRequest:
    crisis_id: str
    coords: list
    affected: list
    step: int
    kind: CrisisKind = CrisisKind.STRUCTURAL_COLLAPSE
    pair: tuple[int, int] | None = None
    episode_id: int | None = None


@dataclass
class Session:
    request: CrisisRequest
    state: dict
    graph: object = None
    config: dict = field(default_factory=dict)
    expected_ownership: dict = field(default_factory=dict)
    waiting: bool = False
    started: float = field(default_factory=time.monotonic)
    timer: object = None


def should_execute_or_regenerate(state):
    # Explicit rejection feedback edge is retained, including at the checkpoint.
    if state.get("human_approved") is False:
        return "generate_plan"
    if state.get("validation_status") != "VALID":
        return "generate_plan"  # The graph edge applies the configured retry budget.
    return "execute"


class OrchestratorRunner:
    def __init__(self, engine, client=None):
        self.engine = engine
        self.client = client or OllamaClient()
        self.executor = ActionExecutor(engine)
        self.validator = PlanValidator(engine.settings)
        self._lock = threading.RLock()
        self._queue = deque()
        self._current = None
        self._last_state = {}
        self._sequence = 0

    @property
    def is_active(self):
        with self._lock:
            return self._current is not None

    @property
    def is_waiting_human(self):
        with self._lock:
            return bool(self._current and self._current.waiting)

    def get_state(self):
        with self._lock:
            session = self._current
            state = deepcopy(session.state if session else self._last_state)
            return {"run_id": self.engine.run_id, "active": session is not None,
                    "active_node": None, "crisis_id": None, "crisis_kind": None, "plan_id": None,
                    "crisis_location": [], "affected_robots": [], "proposed_plan": None,
                    "validation_score": None, "validation_status": "PENDING", "validation_issues": [],
                    "human_approved": None, "regeneration_count": 0, "rejection_count": 0,
                    "fallback_used": False, "fallback_reason": None, "error": None,
                    **state, "waiting_for_human": bool(session and session.waiting),
                    "queued_crises": len(self._queue),
                    "max_pending_crisis": self.engine.settings.max_pending_crisis,
                    "queued_crisis_ids": [r.crisis_id for r in self._queue],
                    "auto_execute_threshold": self.engine.settings.auto_execute_threshold}

    def scheduling_state(self):
        """Small state read for engine backpressure/health; no copied plan payload."""
        with self._lock:
            requests = ([self._current.request] if self._current else []) + list(self._queue)
            return dict(active=self._current is not None,
                        active_crisis_id=self._current.request.crisis_id if self._current else None,
                        queued_crises=len(self._queue),
                        structural_pending=any(r.kind == CrisisKind.STRUCTURAL_COLLAPSE for r in requests),
                        queue_full=len(self._queue) >= self.engine.settings.max_pending_crisis)

    def _is_stale(self, request):
        return (request.kind == CrisisKind.DEADLOCK and
                not self.engine.deadlock_is_current(request.pair, request.episode_id))

    def _prune_stale_locked(self):
        pending = deque()
        for request in self._queue:
            if self._is_stale(request):
                self._event("STALE_DROPPED", request, tag="CRISIS_QUEUE",
                            reason="DEADLOCK_ALREADY_RESOLVED")
            else:
                pending.append(request)
        self._queue = pending

    def invoke_async(self, crisis_coords, affected_robot_ids, kind=CrisisKind.STRUCTURAL_COLLAPSE,
                     episode_id=None):
        # All queue admission/activation uses simulation -> runner lock order.
        # Queued requests are metadata only: they NEVER pin robots.
        kind = {"deadlock": CrisisKind.DEADLOCK, "aisle_collapse": CrisisKind.STRUCTURAL_COLLAPSE}.get(kind, kind)
        kind = CrisisKind(kind)
        with self.engine.lock:
            if self.engine.closed:
                return None
            with self._lock:
                affected = sorted(set(affected_robot_ids))
                pair = tuple(affected) if kind == CrisisKind.DEADLOCK and len(affected) == 2 else None
                if kind == CrisisKind.DEADLOCK and pair is None:
                    raise ValueError("Deadlock crises require two distinct robot IDs")
                self._prune_stale_locked()
                requests = ([self._current.request] if self._current else []) + list(self._queue)
                existing = next((r for r in requests if pair is not None and r.pair == pair), None)
                if existing:
                    self._event("DEDUPED", existing, tag="CRISIS_QUEUE", pair=pair,
                                existing_crisis_id=existing.crisis_id)
                    return existing.crisis_id
                self._sequence += 1
                request = CrisisRequest(f"{self.engine.run_id}:crisis_{self._sequence:04d}",
                                        sorted(set(map(tuple, crisis_coords))), affected,
                                        self.engine.current_step, kind, pair, episode_id)
                if self._is_stale(request):
                    self._event("STALE_DROPPED", request, tag="CRISIS_QUEUE",
                                reason="DEADLOCK_ALREADY_RESOLVED")
                    return None
                if self._current:
                    if len(self._queue) >= self.engine.settings.max_pending_crisis:
                        self._event("BACKPRESSURE", request, tag="CRISIS_QUEUE",
                                    depth=len(self._queue), limit=self.engine.settings.max_pending_crisis)
                        return None
                    self._queue.append(request)
                    self._event("CRISIS_QUEUED", request, tag="CRISIS_QUEUE", depth=len(self._queue))
                else:
                    self._start_locked(request)
                return request.crisis_id

    def _start_locked(self, request):
        # Revalidate at the head, under the same lock that installs active holds.
        if self._is_stale(request):
            self._event("STALE_DROPPED", request, tag="CRISIS_QUEUE", reason="DEADLOCK_ALREADY_RESOLVED")
            return False
        state = dict(run_id=self.engine.run_id, crisis_id=request.crisis_id, crisis_kind=request.kind.value,
                     plan_id=None, crisis_location=request.coords, affected_robots=request.affected,
                     proposed_plan=None, validation_score=None, validation_status="PENDING",
                     validation_issues=[], human_approved=None, active_node="starting", error=None,
                     error_code=None, attempts=0, regeneration_count=0, rejection_count=0,
                     fallback_used=False, fallback_reason=None, executed_actions=0, rejected_strategies=[])
        session = Session(request=request, state=state)
        session.config = {"configurable": {"thread_id": request.crisis_id}, "recursion_limit": 100}
        self._current = session
        try:
            session.graph = self._build_graph(session)
            for rid in request.affected:
                robot = self.engine.robot_manager.get_robot(rid)
                if robot:
                    robot.orchestration_holds.add(request.crisis_id)
            self._event("ORCH_START", request, affected=request.affected, crisis_kind=request.kind.value)
            self._spawn(session, state)
        except Exception:
            logger.exception("[ERROR] Orchestrator startup failed crisis_id=%s", request.crisis_id)
            session.state.update(fallback_used=True, fallback_reason="ORCHESTRATOR_START_FAILED")
            try:
                self.executor.fallback(request.affected, "ORCHESTRATOR_START_FAILED", crisis_id=request.crisis_id)
            except Exception:
                logger.exception("[ERROR] Startup fallback failed crisis_id=%s", request.crisis_id)
                self._emergency_hold(session)
            finally:
                self._finish(session)
        return True

    def _spawn(self, session, initial=None):
        threading.Thread(target=self._drive, args=(session, initial), daemon=True,
                         name=f"orchestrator-{session.request.crisis_id}").start()

    def _event(self, event, request, tag="ORCH", **context):
        return self.engine.events.emit(event, tag=tag, step=self.engine.current_step,
                                       crisis_id=request.crisis_id, **context)

    def _publish(self, session, **updates):
        with self._lock:
            if self._current is session:
                session.state.update(deepcopy(updates))

    def _snapshot(self, session):
        with self.engine.lock:
            with self._lock:
                if self.engine.closed or self._current is not session:
                    raise ExecutionError("RUN_CANCELLED", "Simulation or crisis session was reset")
            return WorldSnapshot.capture(self.engine)

    def _plan_prompt(self, request, world, state):
        robots = []
        for rid in request.affected:
            r = world.robots.get(rid)
            if r is None:
                continue
            task = world.tasks.get(r.current_task)
            robots.append(dict(robot_id=rid, position=[r.position.x,r.position.y], battery=r.battery,
                carrying=r.carrying_item, task_id=r.current_task, destination=world.destination(r),
                delivery=[task.delivery_x,task.delivery_y] if task else None,
                next_cells=r.path[1:4],
                adjacent_walkable=world.warehouse.get_neighbors(r.position.x,r.position.y)))
        feedback = [{"robot_id":i.get("robot_id"),"code":i["code"]} for i in state.get("validation_issues",[])][:12]
        context = dict(kind=request.kind.value,crisis_cells=request.coords,robots=robots,
                       feedback=feedback or {"code":state.get("error_code"),"message":(state.get("error") or "")[:200]},
                       rejected_strategies=state.get("rejected_strategies",[]))
        return ("Warehouse emergency. Return JSON only: {\"actions\":[{\"robot_id\":1,\"action\":\"HOLD\","
                "\"hold_steps\":2,\"reason\":\"brief reason\"}],\"rationale\":\"brief\"}. "
                "Exactly one action per affected robot below. Allowed actions and ONLY their parameters: "
                f"HOLD hold_steps=1..{self.engine.settings.max_hold_steps}; YIELD yield_to_robot_id; "
                "REROUTE waypoint={x:int,y:int}; REASSIGN_TASK task_id (must own it); GO_TO_CHARGER no parameter. "
                "Every action needs robot_id and reason. Coordinates are x,y. Never enter crisis cells. "
                "A reroute must still reach destination with enough battery. YIELD stays stationary; "
                "do not block the winner. Use short HOLD when a safe detour is unknown. "
                "Do not repeat a rejected strategy. " + json.dumps(context,separators=(",",":")))

    def _build_graph(self, session):
        request = session.request

        def diagnose(state):
            self._publish(session, active_node="diagnose")
            self._event("DIAGNOSE", request, graph_node="diagnose", affected=request.affected)
            return {"active_node": "diagnose"}

        def generate(state):
            attempts = state.get("attempts", 0)
            if attempts >= 1 + self.engine.settings.max_regenerations:
                return {"error_code": state.get("error_code") or "MAX_REGENERATIONS",
                        "active_node": "regenerating", "validation_status": "INVALID", "proposed_plan": None}
            if attempts:
                self._event("PLAN_REGENERATED", request, reason=state.get("error_code") or "HUMAN_REJECTED",
                            attempt=attempts, maximum=self.engine.settings.max_regenerations)
            plan_id = f"{request.crisis_id}:plan_{attempts + 1:03d}"
            updates = {"attempts": attempts + 1, "regeneration_count": attempts,
                       "plan_id": plan_id, "proposed_plan": None, "human_approved": None, "approval_source": None,
                       "validation_status": "PENDING", "validation_score": None, "validation_issues": [],
                       "error": None, "error_code": None, "active_node": "generate_plan"}
            self._publish(session, **updates)
            with self.engine.lock:
                world = self._snapshot(session)
                if (request.kind == CrisisKind.DEADLOCK and not self.engine.deadlock_is_current(
                        request.pair, request.episode_id, active_crisis=request.crisis_id)):
                    self._event("STALE_DROPPED", request, tag="CRISIS_QUEUE", reason="DEADLOCK_ALREADY_RESOLVED")
                    return {**updates, "error_code": "STALE_CRISIS", "error": "Deadlock already resolved"}
            session.expected_ownership = world.ownership_key(request.affected)
            prompt = self._plan_prompt(request, world, state)
            started = time.monotonic()
            self._event("LLM_REQUEST", request, tag="LLM", plan_id=plan_id, model=self.client.model,
                        attempt=attempts + 1, graph_node="generate_plan", prompt_chars=len(prompt))
            try:
                raw = self.client.generate(prompt, generation_schema())
                plan = parse_plan(raw)
                session.expected_ownership = world.ownership_key([a.robot_id for a in plan.actions])
                self._event("LLM_SUCCESS", request, tag="LLM", plan_id=plan_id, model=self.client.model,
                            latency_ms=round((time.monotonic()-started)*1000, 2), actions=len(plan.actions))
                if plan.strategy_key() in state.get("rejected_strategies", []):
                    self._event("INVALID_PLAN", request, tag="VALIDATOR", plan_id=plan_id, codes=["REJECTED_STRATEGY"])
                    updates.update(error_code="REJECTED_STRATEGY", error="Model repeated a rejected strategy",
                                   validation_status="INVALID")
                else:
                    updates["proposed_plan"] = plan.model_dump(mode="json")
                    self._event("PLAN_PARSED", request, tag="PLAN", plan_id=plan_id, actions=len(plan.actions))
            except PlanError as error:
                updates.update(error_code=error.code, error=str(error), validation_status="INVALID")
                if error.code in ("LLM_INVALID_JSON", "LLM_SCHEMA_ERROR"):
                    self._event("INVALID_PLAN", request, tag="VALIDATOR", plan_id=plan_id,
                                codes=[error.code], reason=str(error))
                self._event("LLM_FAILURE", request, tag="LLM", plan_id=plan_id, model=self.client.model,
                            error_code=error.code, reason=str(error),
                            latency_ms=round((time.monotonic()-started)*1000, 2))
            except Exception:
                logger.exception("[LLM][ERROR] Unexpected inference failure crisis_id=%s", request.crisis_id)
                updates.update(error_code="LLM_INTERNAL_ERROR", error="Unexpected inference failure", validation_status="INVALID")
                self._event("LLM_FAILURE", request, tag="LLM", plan_id=plan_id, model=self.client.model,
                            error_code="LLM_INTERNAL_ERROR", latency_ms=round((time.monotonic()-started)*1000, 2))
            self._publish(session, **updates)
            return updates

        def after_generate(state):
            if state.get("error_code") == "STALE_CRISIS":
                return END
            if state.get("proposed_plan"):
                return "validate"
            if state.get("error_code") in ("LLM_TIMEOUT", "LLM_UNAVAILABLE", "LLM_INTERNAL_ERROR"):
                return "fallback"
            if state.get("attempts", 0) >= 1 + self.engine.settings.max_regenerations:
                return "fallback"
            return "generate_plan"

        def validate(state):
            self._publish(session, active_node="validate")
            plan = CrisisPlan.model_validate(state["proposed_plan"])
            report = self.validator.validate(plan, self._snapshot(session), request.coords, request.affected)
            auto = (report.valid and not report.requires_human and
                    report.validation_score >= self.engine.settings.auto_execute_threshold)
            updates = dict(active_node="validate", validation_status="VALID" if report.valid else "INVALID",
                           validation_score=report.validation_score, validation_issues=[i.model_dump() for i in report.issues],
                           validation_report=report.model_dump(mode="json"), human_approved=True if auto else None,
                           approval_source="policy" if auto else None,
                           error_code=None if report.valid else "PLAN_VALIDATION_FAILED")
            self._event("VALIDATOR_PASS" if report.valid else "INVALID_PLAN", request, tag="VALIDATOR",
                        plan_id=state["plan_id"], validation_score=report.validation_score,
                        errors=report.metrics["errors"], warnings=report.metrics["warnings"],
                        codes=[i.code for i in report.issues], graph_node="validate")
            self._publish(session, **updates)
            return updates

        def after_validate(state):
            if state.get("human_approved") is False:
                return "generate_plan"
            if state.get("validation_status") != "VALID":
                return "fallback" if state["attempts"] >= 1 + self.engine.settings.max_regenerations else "generate_plan"
            return should_execute_or_regenerate(state)

        def execute(state):
            self._publish(session, active_node="execute")
            try:
                plan = CrisisPlan.model_validate(state["proposed_plan"])
                with self.engine.lock:
                    self._snapshot(session)
                    self.executor.execute(plan, request.coords, request.affected,
                                          human_approved=state.get("approval_source") == "human" and state.get("human_approved") is True,
                                          expected_ownership=session.expected_ownership,
                                          expected_issues=state.get("validation_issues"),
                                          crisis_id=request.crisis_id, plan_id=state["plan_id"])
                return {"active_node": "execute", "executed_actions": len(plan.actions)}
            except ExecutionError as error:
                self._event("ACTION_FAILED", request, tag="EXECUTOR", plan_id=state["plan_id"], error_code=error.code,
                            reason=str(error))
                return {"error_code": error.code, "error": str(error), "executed_actions": 0}

        def fallback(state):
            reason = state.get("error_code") or "MAX_REGENERATIONS"
            self._publish(session, active_node="fallback", fallback_used=True, fallback_reason=reason)
            self._recover_session(session, reason, plan_id=state.get("plan_id"))
            return {"active_node": "fallback", "fallback_used": True, "fallback_reason": reason}

        graph = StateGraph(OrchestratorState)
        for name, node in (("diagnose", diagnose), ("generate_plan", generate), ("validate", validate),
                           ("execute", execute), ("fallback", fallback)):
            graph.add_node(name, node)
        graph.set_entry_point("diagnose")
        graph.add_edge("diagnose", "generate_plan")
        graph.add_conditional_edges("generate_plan", after_generate,
                                    {n: n for n in ("validate", "generate_plan", "fallback", END)})
        graph.add_conditional_edges("validate", after_validate,
                                    {n: n for n in ("execute", "generate_plan", "fallback")})
        graph.add_conditional_edges("execute", lambda s: "fallback" if s.get("error_code") else END,
                                    {"fallback": "fallback", END: END})
        graph.add_edge("fallback", END)
        # Per-session checkpointer is discarded at completion, bounding graph history.
        return graph.compile(checkpointer=MemorySaver(), interrupt_before=["execute"])

    def _drive(self, session, initial=None):
        try:
            with self._lock:
                if self._current is not session:
                    return
            result = session.graph.invoke(initial, session.config)
            self._publish(session, **result)
            snapshot = session.graph.get_state(session.config)
            if snapshot.next:
                with self._lock:
                    if self._current is not session:
                        return
                    if result.get("human_approved") is True:
                        self._spawn(session)
                    else:
                        session.waiting = True
                        session.state["active_node"] = "waiting_for_human"
                        self._event("HITL_REQUESTED", session.request, tag="HITL", plan_id=result.get("plan_id"),
                                    validation_score=result.get("validation_score"))
                        session.timer = threading.Timer(self.engine.settings.hitl_timeout_seconds,
                                                        self._expire, args=(session, result.get("plan_id")))
                        session.timer.daemon = True
                        session.timer.start()
                return
            self._finish(session)
        except Exception:
            logger.exception("[ERROR] Background orchestrator failed crisis_id=%s", session.request.crisis_id)
            with self._lock:
                if self._current is not session:
                    return
            self._publish(session, error="Background orchestration failed; safe recovery applied",
                          error_code="ACTION_EXECUTION_FAILED", fallback_used=True,
                          fallback_reason="ACTION_EXECUTION_FAILED")
            try:
                self._recover_session(session, "ACTION_EXECUTION_FAILED")
            except Exception:
                logger.exception("[ERROR] Fallback failed crisis_id=%s", session.request.crisis_id)
                self._emergency_hold(session)
            finally:
                self._finish(session)

    def _recover_session(self, session, reason, **trace):
        with self.engine.lock:
            with self._lock:
                if self.engine.closed or self._current is not session:
                    return
            self.executor.fallback(session.request.affected, reason,
                                   crisis_id=session.request.crisis_id, **trace)

    def _emergency_hold(self, session):
        with self.engine.lock:
            with self._lock:
                if self.engine.closed or self._current is not session:
                    return
            for rid in session.request.affected:
                robot = self.engine.robot_manager.get_robot(rid)
                if robot:
                    robot.path = []
                    robot.hold_steps_remaining = self.engine.settings.max_hold_steps
            self._event("FALLBACK_HELD", session.request, tag="FALLBACK", reason="RECOVERY_SERVICE_FAILED", fallback=True)

    def human_override(self, approved, plan_id=None):
        with self._lock:
            session = self._current
            if not session or not session.waiting:
                return {"success": False, "message": "Orchestrator is not waiting for human input."}
            if plan_id != session.state.get("plan_id"):
                return {"success": False, "message": "Plan changed. Review the current plan and submit its plan_id."}
            updates = {"human_approved": approved, "approval_source": "human"}
            if not approved:
                plan = CrisisPlan.model_validate(session.state["proposed_plan"])
                updates.update(rejection_count=session.state["rejection_count"] + 1,
                               rejected_strategies=session.state["rejected_strategies"] + [plan.strategy_key()],
                               error_code="HUMAN_REJECTED")
            session.graph.update_state(session.config, updates, as_node="validate")
            session.state.update(updates)
            session.state["active_node"] = "executing" if approved else "regenerating"
            session.waiting = False
            if session.timer:
                session.timer.cancel()
            self._event("HITL_APPROVED" if approved else "HITL_REJECTED", session.request, tag="HITL", plan_id=plan_id)
            self._spawn(session)
            return {"success": True, "message": "Decision accepted. Graph resuming."}

    def _expire(self, session, plan_id):
        with self._lock:
            if self._current is not session or not session.waiting or session.state.get("plan_id") != plan_id:
                return
            session.waiting = False
            session.state.update(fallback_used=True, fallback_reason="HITL_TIMEOUT", error_code="HITL_TIMEOUT")
        try:
            self._recover_session(session, "HITL_TIMEOUT")
        except Exception:
            logger.exception("[ERROR] HITL timeout recovery failed")
            self._emergency_hold(session)
        finally:
            self._finish(session)

    def _finish(self, session):
        with self.engine.lock:
            with self._lock:
                # Always release this ID, including late cancelled-worker exits.
                for robot in self.engine.robot_manager.robots:
                    robot.orchestration_holds.discard(session.request.crisis_id)
                if self._current is not session:
                    return
                try:
                    if session.timer:
                        session.timer.cancel()
                    if session.state.get("fallback_used"):
                        self.engine.measurements["orchestrator_fallback_count"] += 1
                    session.state["active_node"] = "complete"
                    session.waiting = False
                    self._last_state = deepcopy(session.state)
                    self._event("ORCH_COMPLETE", session.request,
                                duration_ms=round((time.monotonic()-session.started)*1000, 2),
                                executed_actions=session.state.get("executed_actions", 0),
                                fallback=session.state.get("fallback_used", False))
                    if self.engine.negotiation_service:
                        self.engine.negotiation_service.record("Orchestrator Crisis Resolution",
                            session.state.get("fallback_reason") or session.state.get("error") or "Validated structured actions applied",
                            "Fallback" if session.state.get("fallback_used") else "Plan finished")
                finally:
                    self._current = None
                    while self._queue and not self.engine.closed:
                        request = self._queue.popleft()
                        self._event("CRISIS_DEQUEUED", request, tag="CRISIS_QUEUE", remaining=len(self._queue))
                        if self._start_locked(request):
                            break

    def reset(self):
        with self.engine.lock:
            with self._lock:
                if self._current and self._current.timer:
                    self._current.timer.cancel()
                if self._current or self._queue:
                    self.engine.events.emit("ORCH_CANCELLED", reason="SIMULATION_RESET",
                                            cancelled_crises=len(self._queue) + int(self._current is not None))
                self._current = None
                self._queue.clear()
                self.engine._deadlock_pairs.clear()
                self.engine._contention.clear()
                self.engine._last_contention.clear()
                self.engine._contention_cells.clear()
                self.engine._recoveries.clear()
                self._last_state = {}
                for robot in self.engine.robot_manager.robots:
                    robot.orchestration_holds.clear()

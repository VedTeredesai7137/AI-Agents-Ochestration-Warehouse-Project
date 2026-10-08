"""
SimulationEngine — Orchestration infrastructure for the warehouse simulation.

The engine coordinates execution but does NOT make task assignment decisions.
Task allocation is handled by TaskAgents via the Contract Net Protocol.
Robot behavior is handled by RobotAgents via the perceive-decide-act cycle.

Responsibilities:
  - Advance simulation step counter.
  - Reset collision reservations each step.
  - Tick TaskAgentManager (CNP lifecycle).
  - Tick AgentManager (robot perceive-decide-act).
  - Detect simulation completion.
"""

from backend.core.models import RobotStatus
from collections import Counter
from copy import deepcopy
from random import Random
import time
import threading
import uuid

from backend.core.events import EventRecorder, logger
from backend.core.settings import Settings
from backend.agents.orchestrator_graph import CrisisKind, CrisisRequest, OrchestratorRunner
from backend.simulation.pathfinder import AStarPathfinder
from backend.simulation.charging import ChargingManager


class SimulationEngine:

    def __init__(
        self,
        robot_manager,
        collision_manager,
        task_manager,
        charging_manager,
        pathfinder,
        agent_manager=None,
        task_agent_manager=None,
        negotiation_service=None,
        settings=None,
        seed=None,
        rng=None,
        lock=None,
        llm_client=None,
    ):
        self.robot_manager = robot_manager
        self.collision_manager = collision_manager
        self.task_manager = task_manager
        self.charging_manager = charging_manager
        self.pathfinder = pathfinder
        self.agent_manager = agent_manager
        self.task_agent_manager = task_agent_manager
        self.negotiation_service = negotiation_service
        self.current_step = 0
        self.settings = settings or Settings.from_env()
        self.seed = self.settings.simulation_seed if seed is None else seed
        self.rng = rng if rng is not None else Random(self.seed)
        self.run_id = uuid.uuid4().hex[:12]
        self.lock = lock or threading.RLock()
        self.closed = False
        self.events = EventRecorder(self.run_id, self.settings.event_history_limit)
        self.task_manager.events = self.events
        self.task_manager.negotiation_service = self.negotiation_service
        self.orchestrator_runner = OrchestratorRunner(self, llm_client)
        self.measurements = Counter()
        self.started_at = None
        self.completion_seconds = None
        self.charging_manager.robots = self.robot_manager.robots
        self.task_manager.charging_manager = self.charging_manager
        self._deadlocks = {}
        self._crises = {}
        self._contention = {}  # Actual failed movement attempts in this tick.
        self._last_contention = {}  # Last completed tick, for queue admission between ticks.
        self._contention_cells = {}
        self._recoveries = set()
        self._deadlock_pairs = {}
        self._episode_sequence = 0
        self._incidents = {}  # Bounded by the configured run budget, not tick count.
        self._next_crisis_step = self.settings.crisis_interval
        self._automatic_sequence_index = 0

    # ------------------------------------------------------------------
    # Orchestrator observability
    # ------------------------------------------------------------------

    @property
    def orchestrator_active(self):
        """True when the LangGraph crisis orchestrator is running."""
        return self.orchestrator_runner.is_active

    # ------------------------------------------------------------------
    # Legacy assign_new_tasks — kept for backward compatibility when
    # no task_agent_manager is present.
    # ------------------------------------------------------------------

    def assign_new_tasks(self):
        """Centralized auction fallback (used only if no task_agent_manager)."""
        for task in self.task_manager.get_unassigned_tasks():
            bids = []
            for robot in self.robot_manager.robots:
                if robot.current_task is not None:
                    continue
                if robot.battery < 30:
                    continue
                distance = (
                    abs(robot.position.x - task.pickup_x)
                    + abs(robot.position.y - task.pickup_y)
                )
                battery_penalty = (100 - robot.battery) * 0.1
                bid = distance + battery_penalty
                bids.append((bid, robot.id))

            if not bids:
                continue

            bids.sort()
            winner = bids[0][1]

            try:
                if self.negotiation_service is not None:
                    bids_str = ", ".join([f"R{r_id}: {b:.1f}" for b, r_id in bids])
                    self.negotiation_service.explain_auction_winner(task.id, winner, bids_str)
            except Exception:
                logger.exception("[ERROR] Legacy auction explanation failed task_id=%s", task.id)

            robot = self.robot_manager.get_robot(winner)

            pickup_path = self.pathfinder.find_path(
                (robot.position.x, robot.position.y),
                (task.pickup_x, task.pickup_y)
            )

            delivery_path = self.pathfinder.find_path(
                (task.pickup_x, task.pickup_y),
                (task.delivery_x, task.delivery_y)
            )

            if not pickup_path:
                continue

            if not delivery_path:
                continue

            path = pickup_path

            if not path:
                continue

            self.task_manager.assign_task(
                task.id,
                winner
            )

            self.robot_manager.assign_task(
                winner,
                task.id,
                path
            )
            robot.delivery_path = delivery_path

            logger.debug("[CNP] task_id=%s robot_id=%s legacy assignment", task.id, winner)

    # ------------------------------------------------------------------
    # Legacy handle_battery — kept for backward compatibility when
    # no agent_manager is present.
    # ------------------------------------------------------------------

    def handle_battery(self, robot):

        if robot.battery > 20:
            return

        if robot.status == RobotStatus.CHARGING:
            return

        if robot.current_task is not None:

            self.task_manager.unassign_task(
                robot.current_task
            )

            logger.info("[CNP] robot_id=%s released task_id=%s for charging", robot.id, robot.current_task)

        robot.path = self.charging_manager.get_charge_path(robot, self.pathfinder)
        robot.carrying_item = False
        robot.delivery_path = []
        if not robot.path or len(robot.path) - 1 > robot.battery:
            robot.path = []
            robot.current_task = None
            robot.status = RobotStatus.NEEDS_CHARGE
            logger.error("[CHARGE ERROR] robot_id=%s cannot reach a charger", robot.id)
            return

        robot.current_task = None
        robot.status = RobotStatus.CHARGING

        logger.info("[CHARGING] robot_id=%s heading to charger", robot.id)

    # ------------------------------------------------------------------
    # STEP — main simulation tick
    # ------------------------------------------------------------------

    def context(self):
        return dict(current_step=self.current_step, robot_manager=self.robot_manager,
                    task_manager=self.task_manager, charging_manager=self.charging_manager,
                    pathfinder=self.pathfinder, collision_manager=self.collision_manager,
                    negotiation_service=self.negotiation_service, warehouse=self.pathfinder.warehouse,
                    engine=self)

    def step(self):
        with self.lock:
            if self.closed:
                return
            if self.started_at is None:
                self.started_at = time.monotonic()
            self.task_manager.current_step = self.current_step + 1
            self._contention.clear()
            self._contention_cells.clear()
            self._recoveries.clear()
            self._step()
            self._last_contention = dict(self._contention)
            self._update_deadlock_pairs()
            charging = sum(r.status == RobotStatus.CHARGING for r in self.robot_manager.robots)
            self.measurements["charging_robot_ticks"] += charging
            self.measurements["max_charging_robots"] = max(self.measurements["max_charging_robots"], charging)
            if self.is_complete() and self.completion_seconds is None:
                self.completion_seconds = time.monotonic() - self.started_at
                self.events.emit("ALL_TASKS_COMPLETED", tag="SIM", step=self.current_step,
                    tasks=len(self.task_manager.tasks), wall_clock_seconds=round(self.completion_seconds,3),
                    charging_events=self.measurements["charging_events"],
                    reauction_count=sum(t.reauction_count for t in self.task_manager.tasks),
                    crises=self.measurements["crisis_count"], llm_calls=self.events.totals()[0].get("LLM_REQUEST",0),
                    fallbacks=self.measurements["orchestrator_fallback_count"])
            if self.current_step % 100 == 0:
                self.events.emit("HEALTH", tag="SIM", **self.health_snapshot())

    def close(self):
        with self.lock:
            self.closed = True
            self.orchestrator_runner.reset()

    def _step(self):

        self.current_step += 1

        logger.debug("[SIM] step=%s run_id=%s", self.current_step, self.run_id)
        if self._next_crisis_step <= 0:
            self._next_crisis_step = self.settings.crisis_interval
        
        if (self.settings.crisis_interval and self.current_step >= self._next_crisis_step
                and self.measurements["crisis_count"] < self.settings.effective_crisis_budget and not self.is_complete()):
            self._next_crisis_step = self.current_step + self.settings.crisis_interval
            sequence = (CrisisKind.STRUCTURAL_COLLAPSE, CrisisKind.ROBOT_IMMOBILIZED,
                        CrisisKind.CHARGER_OUTAGE, CrisisKind.CRITICAL_TASK)
            kind = sequence[self._automatic_sequence_index % len(sequence)]
            self._automatic_sequence_index += 1
            try:
                self.trigger_crisis(kind, periodic=True)
            except ValueError as error:
                self.events.emit("PERIODIC_SKIPPED", tag="CRISIS", step=self.current_step,
                                 reason="NO_ELIGIBLE_INCIDENT", detail=str(error))

        self.collision_manager.reset_step(self.robot_manager.robots)

        # ----- Multi-Agent path (new: CNP + agents) -----
        if self.task_agent_manager is not None and self.agent_manager is not None:
            # 1. Tick task agents (issue CFPs, collect proposals, award contracts)
            self.task_agent_manager.tick_all(
                robot_manager=self.robot_manager,
                pathfinder=self.pathfinder,
            )

            # 2. Tick robot agents (process messages, perceive, decide, act)
            self.agent_manager.tick_all(
                engine=self,
                current_step=self.current_step,
                robot_manager=self.robot_manager,
                task_manager=self.task_manager,
                charging_manager=self.charging_manager,
                pathfinder=self.pathfinder,
                collision_manager=self.collision_manager,
                negotiation_service=self.negotiation_service,
                warehouse=self.pathfinder.warehouse,
            )
            return

        # ----- Agent-only path (agents without CNP) -----
        if self.agent_manager is not None:
            self.assign_new_tasks()
            self.agent_manager.tick_all(
                engine=self,
                current_step=self.current_step,
                robot_manager=self.robot_manager,
                task_manager=self.task_manager,
                charging_manager=self.charging_manager,
                pathfinder=self.pathfinder,
                collision_manager=self.collision_manager,
                negotiation_service=self.negotiation_service,
                warehouse=self.pathfinder.warehouse,
            )
            return

        # ----- Legacy path (no agents at all) -----
        self.assign_new_tasks()

        for robot in self.robot_manager.robots:

            self.handle_battery(robot)

            if len(robot.path) <= 1:

                if robot.status == RobotStatus.CHARGING and self.charging_manager.at_station(robot, self.pathfinder.warehouse):

                    robot.battery += 10

                    if robot.battery >= 100:

                        robot.battery = 100
                        robot.status = RobotStatus.IDLE

                        logger.info("[CHARGING] robot_id=%s fully charged", robot.id)

                continue

            if robot.battery < 1:
                robot.battery = max(0, robot.battery)
                robot.status = RobotStatus.NEEDS_CHARGE
                continue
            next_x, next_y = robot.path[1]

            success, _ = self.collision_manager.reserve_cell(
                next_x,
                next_y,
                robot.id
            )
            if not success:
                continue

            robot.position.x = next_x
            robot.position.y = next_y

            robot.path.pop(0)

            robot.battery = max(0, robot.battery - 1)

            logger.debug("[ROBOT][MOVE] robot_id=%s position=(%s,%s) battery=%.0f status=%s",
                        robot.id, next_x, next_y, robot.battery, robot.status.value)

            if len(robot.path) == 1:

                if robot.status == RobotStatus.CHARGING:

                    logger.info("[CHARGING] robot_id=%s arrived at charger", robot.id)

                elif robot.current_task is not None:

                    task = self.task_manager.get_task(
                        robot.current_task
                    )

                    if not robot.carrying_item:

                        robot.carrying_item = True

                        robot.path = (
                            robot.delivery_path
                        )

                        robot.status = (
                            RobotStatus.DELIVERING
                        )

                        logger.info("[TASK] robot_id=%s picked task_id=%s", robot.id, robot.current_task)

                    else:

                        logger.info("[TASK] robot_id=%s delivered task_id=%s", robot.id, robot.current_task)

                        self.task_manager.complete_task(
                            robot.current_task
                        )

                        robot.current_task = None

                        robot.carrying_item = False

                        robot.delivery_path = []

                        robot.status = (
                            RobotStatus.IDLE
                        )

    def is_complete(self):

        unfinished_tasks = [
            task
            for task in self.task_manager.tasks
            if not task.completed
        ]

        active_robots = [
            robot
            for robot in self.robot_manager.robots
            if robot.current_task is not None
        ]

        return (
            len(unfinished_tasks) == 0
            and len(active_robots) == 0
        )

    def request_deadlock(self, robot_id, other_id, cell):
        """Record contention; three strikes ONLY request deterministic recovery.

        Called for every failed reservation. Pair escalation happens after all
        robots tick, so old counters and partial tick order cannot imply reciprocity.
        """
        if other_id is None:
            return
        self._contention[robot_id] = other_id
        self._contention_cells[robot_id] = tuple(cell)
        agent = self.agent_manager.get_agent(robot_id)
        if agent.blocked_counter != 3:
            return
        if robot_id not in self._deadlocks:
            self._deadlocks[robot_id] = self.current_step
            self.measurements["deadlock_count"] += 1
            self.events.emit("DEADLOCK_DETECTED", tag="SIM", step=self.current_step,
                             robot_id=robot_id, other_robot_id=other_id, cell=cell)
        self._recoveries.add(robot_id)
        self.orchestrator_runner.executor.fallback([robot_id], "DETERMINISTIC_DEADLOCK")
        agent.blocked_counter = 0

    def _reciprocal_pair(self, pair, active_crisis=None, observations=None):
        observations = self._contention if observations is None else observations
        robots = [self.robot_manager.get_robot(rid) for rid in pair]
        for robot, other in zip(robots, reversed(robots)):
            if (robot is None or other is None or robot.current_task is None
                    or robot.status not in (RobotStatus.MOVING, RobotStatus.DELIVERING)
                    or robot.hold_steps_remaining or robot.yield_steps_remaining
                    or robot.orchestration_holds - {active_crisis}
                    or len(robot.path) < 2
                    or (active_crisis is None and observations.get(robot.id) != other.id)
                    or tuple(robot.path[1]) != (other.position.x, other.position.y)):
                return False
        return True

    def deadlock_is_current(self, pair, episode_id, active_crisis=None):
        """Caller holds engine.lock. A moved/resolved/replaced incident is stale."""
        episode = self._deadlock_pairs.get(pair)
        return bool(episode and episode["id"] == episode_id
                    and episode["positions"] == self._pair_positions(pair)
                    and self._pair_tasks(pair) == episode["tasks"]
                    and self._reciprocal_pair(pair, active_crisis, self._last_contention))

    def _pair_tasks(self, pair):
        return tuple(r.current_task if (r := self.robot_manager.get_robot(rid)) else None for rid in pair)

    def _pair_positions(self, pair):
        return tuple((r.position.x, r.position.y) if (r := self.robot_manager.get_robot(rid)) else None
                     for rid in pair)

    def _update_deadlock_pairs(self):
        pairs = {tuple(sorted((rid, other))) for rid, other in self._contention.items() if rid != other}
        # Observe actual failed moves BEFORE fallback changed a path or added HOLD.
        # Intentional waits never publish failed attempts and never increment this.
        observed = {pair for pair in pairs if all(
            self._contention.get(rid) == other
            and self._contention_cells.get(rid) == self._pair_positions((other,))[0]
            and (r := self.robot_manager.get_robot(rid)) is not None
            and r.current_task is not None
            and r.status in (RobotStatus.MOVING, RobotStatus.DELIVERING)
            for rid, other in (pair, tuple(reversed(pair))))}
        for pair, episode in list(self._deadlock_pairs.items()):
            changed_blocker = any(rid in self._contention and self._contention[rid] != other
                                  for rid, other in (pair, tuple(reversed(pair))))
            if (episode["positions"] != self._pair_positions(pair) or episode["tasks"] != self._pair_tasks(pair)
                    or (changed_blocker and not episode["submitted"])):
                del self._deadlock_pairs[pair]
            else:
                # Each robot can reach its third strike on a different tick.
                # Remember recovery even while its peer is intentionally waiting.
                episode["recovered"].update(rid for rid, other in (pair, tuple(reversed(pair)))
                    if rid in self._recoveries and self._contention.get(rid) == other)
                if len(episode["recovered"]) == 2:
                    episode.setdefault("recovery_ready_step", self.current_step)
        for pair in sorted(observed):
            episode = self._deadlock_pairs.get(pair)
            if episode is None:
                self._episode_sequence += 1
                episode = dict(id=self._episode_sequence, positions=self._pair_positions(pair),
                               tasks=self._pair_tasks(pair), recovered=set(), persistent_ticks=0, submitted=False)
                self._deadlock_pairs[pair] = episode
            episode["recovered"].update(set(pair) & self._recoveries)
            if len(episode["recovered"]) == 2:
                episode.setdefault("recovery_ready_step", self.current_step)
            if episode["submitted"]:
                continue
            if episode.get("recovery_ready_step", self.current_step) < self.current_step:
                episode["persistent_ticks"] += 1
            # Failed recovery may itself insert a short HOLD/replan. Preserve the
            # episode across that pause, but only count reciprocal failed moves.
            if (episode["persistent_ticks"] >= self.settings.deadlock_persistence_steps
                    and self._reciprocal_pair(pair)):
                episode["submitted"] = True
                if self.settings.orchestrator_enabled:
                    self.events.emit("DEADLOCK_PERSISTENT", tag="SIM", step=self.current_step,
                                     pair=pair, persistent_ticks=episode["persistent_ticks"])
                    self.trigger_crisis(CrisisKind.DEADLOCK, robot_ids=list(pair),
                                        episode_id=episode["id"], source="natural")

    def health_snapshot(self):
        with self.lock:
            scheduling = self.orchestrator_runner.scheduling_state()
            active_id = scheduling["active_crisis_id"]
            robots = self.robot_manager.robots
            return dict(step=self.current_step,
                completed_tasks=sum(t.completed for t in self.task_manager.tasks),
                remaining=sum(not t.completed for t in self.task_manager.tasks),
                idle=sum(r.status == RobotStatus.IDLE for r in robots),
                reauctioned=sum(t.reauction_count for t in self.task_manager.tasks),
                moving=sum(r.status in (RobotStatus.MOVING, RobotStatus.DELIVERING) and len(r.path) > 1
                           and not r.orchestration_holds and not r.hold_steps_remaining and not r.yield_steps_remaining
                           for r in robots),
                charging=sum(r.status == RobotStatus.CHARGING for r in robots),
                intentional_hold=sum(bool(r.hold_steps_remaining or r.yield_steps_remaining) for r in robots),
                orchestration_pinned=sum(bool(r.orchestration_holds) for r in robots),
                queue_depth=scheduling["queued_crises"], active_crisis=active_id is not None,
                active_crisis_id=active_id,
                orphaned_holds=sum(len(r.orchestration_holds - {active_id}) for r in robots),
                successful_moves=self.measurements["successful_moves"])

    def record_movement(self, robot_id):
        self.measurements["successful_moves"] += 1
        self._contention.pop(robot_id, None)
        self._last_contention.pop(robot_id, None)
        for pair in list(self._deadlock_pairs):
            if robot_id in pair:
                del self._deadlock_pairs[pair]
        started = self._deadlocks.pop(robot_id, None)
        if started is not None:
            duration = self.current_step - started
            self.measurements["deadlocks_resolved"] += 1
            self.measurements["deadlock_resolution_steps"] += duration
            self.events.emit("DEADLOCK_RESOLVED", tag="SIM", step=self.current_step,
                             robot_id=robot_id, resolution_steps=duration)
        for crisis_id, info in list(self._crises.items()):
            info["remaining"].discard(robot_id)
            if not info["remaining"]:
                duration = self.current_step - info["step"]
                self.measurements["crises_recovered"] += 1
                self.measurements["crisis_recovery_steps"] += duration
                self.events.emit("CRISIS_RECOVERED", step=self.current_step, crisis_id=crisis_id,
                                 recovery_steps=duration)
                del self._crises[crisis_id]

    def _collapse_preserves_access(self, cells, protected):
        # Read-only flood fill for connectivity, not a second movement pathfinder.
        warehouse = self.pathfinder.warehouse
        blocked = set(cells)
        root = next(iter(protected), (0,0))
        seen, pending = {root}, [root]
        while pending:
            for cell in warehouse.get_neighbors(*pending.pop()):
                if cell not in blocked and cell not in seen:
                    seen.add(cell)
                    pending.append(cell)
        return protected <= seen and all(c in seen for c in self.charging_manager.stations(self.pathfinder))

    def crisis_summary(self):
        with self.lock:
            used = self.measurements["crisis_count"]
            return dict(crisis_budget=self.settings.effective_crisis_budget, crises_submitted=used,
                        crises_completed=self.measurements["crises_completed"],
                        crises_remaining=max(0, self.settings.effective_crisis_budget-used),
                        next_automatic_crisis_step=self._next_crisis_step if self.settings.crisis_interval else None,
                        crisis_types=[kind.value for kind in CrisisKind],
                        incidents=[dict(record) for record in self._incidents.values()])

    def trigger_warehouse_crisis(self, coords=None, *, periodic=False):
        """Compatibility entry point; all injected crises share one run budget."""
        return self.trigger_crisis(CrisisKind.STRUCTURAL_COLLAPSE, coords=coords, periodic=periodic)

    def trigger_crisis(self, kind=CrisisKind.STRUCTURAL_COLLAPSE, *, coords=None, robot_ids=None,
                       task_id=None, periodic=False, episode_id=None, source=None):
        with self.lock:
            kind = CrisisKind(kind)
            if self.closed:
                return None
            if coords is not None and kind != CrisisKind.STRUCTURAL_COLLAPSE:
                raise ValueError("Coordinates are supported only for structural collapse")
            if task_id is not None and kind != CrisisKind.CRITICAL_TASK:
                raise ValueError("task_id is supported only for urgent-order disruption")
            source = source or ("automatic" if periodic else "manual")
            scheduling = self.orchestrator_runner.scheduling_state()
            if self.measurements["crisis_count"] >= self.settings.effective_crisis_budget:
                self.events.emit("CRISIS_BUDGET_EXHAUSTED", tag="CRISIS", step=self.current_step,
                                 budget=self.settings.effective_crisis_budget)
                return None
            if (periodic and (scheduling["active"] or scheduling["queued_crises"])) or scheduling["queue_full"]:
                self.events.emit("PERIODIC_SKIPPED" if periodic else "BACKPRESSURE", tag="CRISIS",
                                 step=self.current_step, reason="ORCHESTRATOR_BACKPRESSURE",
                                 active=scheduling["active"], queued=scheduling["queued_crises"])
                return None
            warehouse = self.pathfinder.warehouse
            affected = sorted(set(robot_ids or []))
            if any(self.robot_manager.get_robot(rid) is None for rid in affected):
                raise ValueError("Affected robot does not exist")
            details = dict(managed=True, source=source)
            if kind == CrisisKind.DEADLOCK:
                episode = self._deadlock_pairs.get(tuple(affected), {})
                if (len(affected) != 2 or not self.deadlock_is_current(tuple(affected), episode_id)
                        or episode.get("persistent_ticks", 0) < self.settings.deadlock_persistence_steps):
                    return None
                coords = []
            elif kind == CrisisKind.STRUCTURAL_COLLAPSE:
                # Explicit operator input is checked before consuming a budget slot.
                if coords is not None:
                    self._validate_collapse(set(map(tuple, coords)))
                coords = coords or []
            elif kind == CrisisKind.CHARGER_OUTAGE:
                if len(self.charging_manager.stations(self.pathfinder)) < 2:
                    raise ValueError("Charger outage requires at least two charging bays")
                if self._outage_bay() is None:
                    self.events.emit("PERIODIC_SKIPPED" if periodic else "CRISIS_NOT_ELIGIBLE", tag="CRISIS",
                                     step=self.current_step, reason="NO_ENERGY_SAFE_CHARGER_OUTAGE")
                    return None
                coords = []
            else:
                candidates = [r for r in self.robot_manager.robots if not r.fault_reason]
                if kind == CrisisKind.CRITICAL_TASK:
                    task = self.task_manager.get_task(task_id) if task_id else next(
                        (t for t in self.task_manager.tasks if not t.completed and t.assigned_robot is not None), None)
                    if task is None or task.completed or task.assigned_robot is None:
                        raise ValueError("Urgent disruption requires an owned unfinished task")
                    affected = [task.assigned_robot]
                    details["task_id"] = task.id
                elif not affected:
                    candidates.sort(key=lambda r: (r.current_task is None, r.id))
                    affected = [candidates[0].id] if candidates else []
                if not affected:
                    return None
                if len(affected) != 1:
                    raise ValueError("This incident requires exactly one robot")
                details["robot_id"] = affected[0]
                r = self.robot_manager.get_robot(affected[0])
                coords = [(r.position.x, r.position.y)]
            if self.settings.orchestrator_enabled:
                known_ids = set(self._incidents)
                crisis_id = self.orchestrator_runner.invoke_async(coords, affected, kind=kind,
                                        episode_id=episode_id, details=details)
                if crisis_id is None:
                    return None
                if crisis_id in known_ids:
                    return crisis_id  # Pair deduplication never consumes another budget slot.
            else:
                crisis_id = f"{self.run_id}:baseline_crisis_{self.measurements['crisis_count']+1:04d}"
                request = CrisisRequest(crisis_id, coords, affected, self.current_step, kind,
                                        tuple(affected) if kind == CrisisKind.DEADLOCK else None, episode_id, details)
                if not self.activate_crisis(request):
                    return None
                self.orchestrator_runner.executor.fallback(request.affected, "ORCHESTRATOR_DISABLED",
                                                         crisis_id=crisis_id, crisis_kind=kind.value)
                self.finish_crisis(request)
            self.measurements["crisis_count"] += 1
            self.measurements["automatic_crises" if periodic else "manual_crises" if source == "manual" else "natural_crises"] += 1
            if source != "natural":
                self._next_crisis_step = self.current_step + self.settings.crisis_interval
            record = self._incidents.setdefault(crisis_id, {})
            record.update(crisis_id=crisis_id, crisis_kind=kind.value, source=source, detected_step=self.current_step)
            record.setdefault("status", "QUEUED")
            self.events.emit("CRISIS_CREATED", tag="CRISIS", step=self.current_step, crisis_id=crisis_id,
                             crisis_kind=kind.value, source=source, crisis_location=record.get("crisis_location", coords),
                             affected=record.get("affected", affected), remaining=self.crisis_summary()["crises_remaining"])
            return crisis_id

    def _validate_collapse(self, cells):
        warehouse = self.pathfinder.warehouse
        occupied = {(r.position.x, r.position.y) for r in self.robot_manager.robots}
        protected = {(t.pickup_x, t.pickup_y) for t in self.task_manager.tasks if not t.completed}
        protected |= {(t.delivery_x, t.delivery_y) for t in self.task_manager.tasks if not t.completed}
        if not cells or any(not warehouse.is_walkable(x,y) or (x,y) in occupied | protected or warehouse.grid[y][x] == "C"
                            for x,y in cells) or not self._collapse_preserves_access(cells, occupied | protected):
            raise ValueError("Collapse must preserve task/charger access and avoid occupied/protected cells")
        if not self._change_preserves_energy({cell:"S" for cell in cells}):
            raise ValueError("Collapse would invalidate an owned task's charging-energy itinerary")

    def _change_preserves_energy(self, changes):
        """Non-mutating admission preflight using the existing charging itinerary planner."""
        warehouse = deepcopy(self.pathfinder.warehouse)
        for (x,y),cell in changes.items():
            warehouse.grid[y][x] = cell
        warehouse.revision += 1
        after_pf, after_charge = AStarPathfinder(warehouse), ChargingManager()
        for robot in self.robot_manager.robots:
            task = self.task_manager.get_task(robot.current_task)
            if not task or task.completed:
                continue
            start = (robot.position.x,robot.position.y)
            goal = (task.delivery_x,task.delivery_y) if robot.carrying_item else (task.pickup_x,task.pickup_y)
            if robot.carrying_item:
                before = self.charging_manager.journey(start,goal,robot.battery,self.pathfinder,loaded=True,build_route=False)
                after = after_charge.journey(start,goal,robot.battery,after_pf,loaded=True,build_route=False)
            else:
                before = self.charging_manager.task_offer(robot,task,self.pathfinder)
                after = after_charge.task_offer(robot,task,after_pf)
            if before is not None and after is None:
                return False
        return True

    def _outage_bay(self):
        occupied = {(r.position.x,r.position.y) for r in self.robot_manager.robots}
        stations = self.charging_manager.stations(self.pathfinder)
        if len(stations) < 2:
            return None
        choices = [bay for bay in stations if bay not in occupied]
        choices.sort(key=lambda c: (-sum(r.status == RobotStatus.CHARGING and bool(r.path) and tuple(r.path[-1]) == c
                                        for r in self.robot_manager.robots), c))
        for bay in choices:
            if all(min(self.charging_manager.distance((r.position.x,r.position.y), c, self.pathfinder)
                       for c in stations if c != bay) * (2 if r.carrying_item else 1) <= r.battery
                   for r in self.robot_manager.robots) and self._change_preserves_energy({bay:"."}):
                return bay
        return None

    def activate_crisis(self, request):
        """Called under engine.lock only when queued work reaches the front."""
        details, kind = request.details, request.kind
        warehouse = self.pathfinder.warehouse
        try:
            if kind == CrisisKind.STRUCTURAL_COLLAPSE:
                result = self._activate_collapse(request.coords or None)
                if not result:
                    return False
                request.coords, request.affected = result
            elif kind == CrisisKind.ROBOT_IMMOBILIZED:
                robot = self.robot_manager.get_robot(details["robot_id"])
                if not robot or robot.fault_reason:
                    return False
                robot.fault_reason = "TEMPORARY_IMMOBILIZATION"
                request.coords = [(robot.position.x, robot.position.y)]
            elif kind == CrisisKind.CRITICAL_TASK:
                task = self.task_manager.get_task(details["task_id"])
                if not task or task.completed or task.assigned_robot is None:
                    return False
                task.priority = "CRITICAL"
                request.affected = [task.assigned_robot]
            elif kind == CrisisKind.CHARGER_OUTAGE:
                bay = self._outage_bay()
                if bay is None:
                    return False
                request.coords = [bay]
                details["charger"] = bay
                request.affected = [r.id for r in self.robot_manager.robots
                                    if r.status == RobotStatus.CHARGING and r.path and tuple(r.path[-1]) == bay]
                if not request.affected:
                    request.affected = [min(self.robot_manager.robots, key=lambda r:(r.battery,r.id)).id]
                warehouse.grid[bay[1]][bay[0]] = "."
                warehouse.revision += 1
                for rid in request.affected:
                    robot = self.robot_manager.get_robot(rid)
                    if robot.status == RobotStatus.CHARGING:
                        robot.path = self.charging_manager.get_charge_path(robot, self.pathfinder,
                                             congestion=True, loaded=robot.carrying_item)
            elif kind == CrisisKind.DEADLOCK and not self.deadlock_is_current(request.pair, request.episode_id):
                return False
        except ValueError:
            return False  # Conditions changed while queued: no partial physical effect.
        self._incidents.setdefault(request.crisis_id, {}).update(status="ACTIVE", crisis_kind=kind.value,
                           affected=list(request.affected), crisis_location=list(request.coords))
        self.events.emit("CRISIS_ACTIVATED", tag="CRISIS", step=self.current_step, crisis_id=request.crisis_id,
                         crisis_kind=kind.value, affected=request.affected, crisis_location=request.coords)
        if request.affected:
            self._crises[request.crisis_id] = {"step": self.current_step, "remaining": set(request.affected)}
        return True

    def finish_crisis(self, request, dropped=False):
        if not request.details.get("managed"):
            return
        record = self._incidents.setdefault(request.crisis_id, {})
        if record.get("status") in ("COMPLETE", "STALE_DROPPED"):
            return
        if request.kind == CrisisKind.ROBOT_IMMOBILIZED:
            robot = self.robot_manager.get_robot(request.details.get("robot_id"))
            if robot:
                robot.fault_reason = None
        if request.kind == CrisisKind.CHARGER_OUTAGE and "charger" in request.details:
            x,y = request.details["charger"]
            self.pathfinder.warehouse.grid[y][x] = "C"
            self.pathfinder.warehouse.revision += 1
        record["status"] = "STALE_DROPPED" if dropped else "COMPLETE"
        self.measurements["crises_completed"] += 1
        self.events.emit("CRISIS_HANDLING_COMPLETE", tag="CRISIS", step=self.current_step,
                         crisis_id=request.crisis_id, crisis_kind=request.kind.value, dropped=dropped,
                         temporary_effects_restored=request.kind in (CrisisKind.ROBOT_IMMOBILIZED, CrisisKind.CHARGER_OUTAGE))

    def _activate_collapse(self, coords=None):
        with self.lock:
            warehouse = self.pathfinder.warehouse
            occupied = {(r.position.x, r.position.y) for r in self.robot_manager.robots}
            if coords is None:
                protected = {(t.pickup_x,t.pickup_y) for t in self.task_manager.tasks if not t.completed}
                protected |= {(t.delivery_x,t.delivery_y) for t in self.task_manager.tasks if not t.completed}
                candidates = []
                for y in range(1, warehouse.height - 1):
                    for x in range(1, warehouse.width - 3):
                        cells = [(x+i, y) for i in range(3)]
                        if all(warehouse.grid[cy][cx] == "." and (cx, cy) not in occupied | protected for cx, cy in cells):
                            candidates.append(cells)
                central = [c for c in candidates if 10 <= c[0][1] <= 20 and 5 <= c[0][0] < warehouse.width - 7]
                if not candidates:
                    return None
                self.rng.shuffle(candidates)
                paths = [set(map(tuple, r.path + r.delivery_path)) for r in self.robot_manager.robots]
                candidates.sort(key=lambda c: (-sum(bool(set(c) & p) for p in paths), c not in central))
                coords = next((c for c in candidates if self._collapse_preserves_access(c, occupied | protected)
                               and self._change_preserves_energy({cell:"S" for cell in c})), None)
                if coords is None:
                    return None
            cells = set(map(tuple, coords))
            self._validate_collapse(cells)
            affected = [r.id for r in self.robot_manager.robots
                        if any(tuple(p) in cells for p in r.path + r.delivery_path)]
            for x, y in cells:
                warehouse.grid[y][x] = "S"
            warehouse.revision += 1
            if self.agent_manager and self.agent_manager.message_bus:
                from backend.agents.message_bus import MessageType
                bus = self.agent_manager.message_bus
                bus.broadcast(bus.create_message(sender="System", recipient="ALL", message_type=MessageType.CRISIS_ALERT,
                                                 payload={"coords": sorted(cells)}))
            if self.negotiation_service:
                first, last = min(cells), max(cells)
                self.negotiation_service.generate_crisis_report(*first, *last)
            # Path safety/replanning is immediate, including for queued robots.
            # This runs under the simulation lock and does not wait for inference.
            for rid in affected:
                robot = self.robot_manager.get_robot(rid)
                agent = self.agent_manager.get_agent(rid)
                if any(tuple(p) in cells for p in robot.path):
                    agent._recover_route(self.context())
                if any(tuple(p) in cells for p in robot.delivery_path):
                    task = self.task_manager.get_task(robot.current_task)
                    robot.delivery_path = self.pathfinder.find_path(
                        (task.pickup_x, task.pickup_y), (task.delivery_x, task.delivery_y)) if task else []
            return sorted(cells), affected

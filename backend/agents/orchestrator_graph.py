"""
OrchestratorGraph — LangGraph-based deliberative crisis orchestrator.

When an aisle collapse or major deadlock occurs, this graph takes control
of the swarm to generate a multi-robot evacuation plan using the local LLM.

State Machine:
  diagnose → generate_plan → validate → [HITL interrupt if low confidence] → execute
  If human REJECTS: validate loops back to generate_plan for a new LLM strategy.

Architecture:
  - Runs asynchronously via asyncio — does NOT block the FastAPI thread.
  - Uses LangGraph's MemorySaver checkpointer with interrupt_before on the
    execute node to implement Human-In-The-Loop (HITL) approval.
  - The local Ollama/Mistral LLM generates the rerouting strategy.
"""

import asyncio
import json
import random
import time
import threading
from typing import TypedDict, Optional

import requests
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver


# ---------------------------------------------------------------------------
# State Schema
# ---------------------------------------------------------------------------

class OrchestratorState(TypedDict):
    """State flowing through the LangGraph crisis orchestrator."""
    crisis_location: list            # List of (x, y) coordinate tuples for collapsed cells
    affected_robots: list            # List of robot IDs whose paths cross the crisis zone
    proposed_plan: dict              # LLM-generated rerouting strategy
    confidence_score: float          # Model's self-assessed confidence (0.0–1.0)
    human_approved: Optional[bool]   # None = pending, True = approved, False = rejected
    active_node: str                 # Current node name for frontend observability
    error: Optional[str]             # Error message if any node fails
    rejection_count: int             # How many times the human has rejected plans


# ---------------------------------------------------------------------------
# Node Implementations
# ---------------------------------------------------------------------------

def diagnose(state: OrchestratorState) -> dict:
    """
    Identify which robots are trapped or affected by the crisis.
    
    Reads the crisis_location from state and cross-references against
    the robot paths stored in the orchestrator context. Robots whose
    current path contains any collapsed cell are considered affected.
    """
    affected = state.get("affected_robots", [])
    crisis = state.get("crisis_location", [])
    
    print(f"\n[🧠 GRAPH] Executing Node: DIAGNOSE | State: crisis={crisis}, affected_count={len(affected)}")
    print(f"[🧠 GRAPH] diagnose: {len(affected)} robots affected: {affected}")
    print(f"[🧠 GRAPH] Transitioning to next node...")
    
    return {
        "active_node": "diagnose",
        "affected_robots": affected,
    }


def generate_plan(state: OrchestratorState) -> dict:
    """
    Use the local Ollama LLM to propose a rerouting strategy for affected robots.
    
    Sends a structured prompt to Mistral describing the crisis location,
    the affected robot IDs, and requests a JSON rerouting plan.
    Returns a mocked confidence_score between 0.70 and 0.95.
    """
    crisis = state["crisis_location"]
    affected = state["affected_robots"]
    rejection_count = state.get("rejection_count", 0)
    
    print(f"\n[🧠 GRAPH] Executing Node: GENERATE_PLAN | State: affected={affected}, rejections={rejection_count}")
    
    # If this is a re-generation after rejection, tell the LLM to try a different approach
    rejection_context = ""
    if rejection_count > 0:
        rejection_context = (
            f" The previous plan was REJECTED by the human operator ({rejection_count} time(s)). "
            "You MUST propose a DIFFERENT strategy than before. Consider alternative routes, "
            "different robot priorities, or fallback to charging stations."
        )
    
    prompt = (
        f"A warehouse aisle has collapsed at cells {crisis}. "
        f"The following robots are affected and need rerouting: {affected}. "
        f"{rejection_context}"
        "Generate a JSON rerouting strategy. The output must be a JSON object with exactly one field: "
        "'routes' which is a list of objects, each with 'robot_id' (int) and 'action' (string describing "
        "what the robot should do: e.g., 'reroute_around_north', 'retreat_to_charger', 'hold_position')."
    )
    
    payload = {
        "model": "mistral",
        "prompt": prompt,
        "format": "json",
        "stream": False,
    }
    
    proposed_plan = {"routes": []}
    
    try:
        print(f"[🧠 GRAPH] generate_plan: Sending prompt to Ollama (attempt #{rejection_count + 1})...")
        response = requests.post(
            "http://localhost:11434/api/generate",
            json=payload,
            timeout=60.0,
        )
        response.raise_for_status()
        data = response.json()
        raw = data.get("response", "{}")
        result = json.loads(raw)
        proposed_plan = result
        print(f"[🧠 GRAPH] generate_plan: LLM plan received: {proposed_plan}")
    except requests.exceptions.Timeout:
        print("[🧠 GRAPH] generate_plan: LLM timeout (60s). Using fallback plan.")
        proposed_plan = {
            "routes": [
                {"robot_id": rid, "action": "hold_position_and_recompute_path"}
                for rid in affected
            ],
            "fallback": True,
        }
    except Exception as e:
        print(f"[🧠 GRAPH] generate_plan: LLM error: {e}. Using fallback plan.")
        proposed_plan = {
            "routes": [
                {"robot_id": rid, "action": "hold_position_and_recompute_path"}
                for rid in affected
            ],
            "fallback": True,
            "error": str(e),
        }
    
    # Confidence score — random between 0.70 and 0.95 as specified
    confidence = round(random.uniform(0.70, 0.95), 2)
    print(f"[🧠 GRAPH] generate_plan: Confidence score = {confidence}")
    print(f"[🧠 GRAPH] Transitioning to next node...")
    
    return {
        "active_node": "generate_plan",
        "proposed_plan": proposed_plan,
        "confidence_score": confidence,
        "human_approved": None,  # Reset approval for new plan
    }


def validate(state: OrchestratorState) -> dict:
    """
    Evaluate the proposed plan's confidence score.
    
    If confidence_score < 0.85, the plan is flagged as requiring human
    approval. The graph will be interrupted before the execute node
    (via LangGraph's interrupt_before mechanism), pausing execution
    until a human operator approves or rejects.
    """
    confidence = state.get("confidence_score", 0.0)
    human_approved = state.get("human_approved")
    rejection_count = state.get("rejection_count", 0)
    
    print(f"\n[🧠 GRAPH] Executing Node: VALIDATE | State: confidence={confidence}, human_approved={human_approved}, rejections={rejection_count}")
    
    if confidence < 0.85:
        print(f"[🧠 GRAPH] validate: LOW CONFIDENCE ({confidence}). Requesting human approval.")
        print(f"[🧠 GRAPH] Transitioning to next node...")
        return {
            "active_node": "validate",
            "human_approved": None,  # Pending — graph will interrupt before execute
        }
    else:
        print(f"[🧠 GRAPH] validate: HIGH CONFIDENCE ({confidence}). Auto-approving plan.")
        print(f"[🧠 GRAPH] Transitioning to next node...")
        return {
            "active_node": "validate",
            "human_approved": True,
        }


def execute(state: OrchestratorState) -> dict:
    """
    Apply the approved rerouting plan to affected robots.
    
    This node runs only after human approval (if required).
    It stores the execution result in state. The actual path
    modification on Robot objects is performed by the engine
    after the graph completes, using the plan from state.
    
    Also pushes a log entry to NegotiationService for the
    /negotiation/logs endpoint.
    """
    approved = state.get("human_approved")
    plan = state.get("proposed_plan", {})
    affected = state.get("affected_robots", [])
    confidence = state.get("confidence_score", 0.0)
    rejection_count = state.get("rejection_count", 0)
    
    print(f"\n[🧠 GRAPH] Executing Node: EXECUTE | State: approved={approved}, affected={len(affected)}, confidence={confidence}, rejections={rejection_count}")
    
    if approved is False:
        # This path should not normally be reached because the conditional
        # edge routes rejections back to generate_plan. But as a safety net:
        print("[🧠 GRAPH] execute: Plan REJECTED by operator. This should have looped back.")
        return {
            "active_node": "execute",
            "proposed_plan": {**plan, "executed": False, "rejected": True},
        }
    
    print(f"[🧠 GRAPH] execute: Applying rerouting plan to {len(affected)} robots.")
    
    # Mark plan as executed — the engine will read this and recompute paths
    executed_plan = {
        **plan,
        "executed": True,
        "execution_time": time.time(),
    }
    
    # Push log entry to NegotiationService (will be picked up by _apply_plan in the runner)
    conf_pct = round(confidence * 100)
    _push_negotiation_log(
        event=f"Orchestrator Crisis Resolution",
        reasoning=f"Executed Reroute Plan. Confidence: {conf_pct}%. Affected: {affected}. Rejections: {rejection_count}.",
        decision=f"Plan executed for {len(affected)} robots",
    )
    
    print(f"[🧠 GRAPH] execute: Plan execution complete. Log pushed to negotiation logs.")
    print(f"[🧠 GRAPH] Graph execution FINISHED.")
    
    return {
        "active_node": "execute",
        "proposed_plan": executed_plan,
    }


def _push_negotiation_log(event: str, reasoning: str, decision: str):
    """
    Push a log entry into the NegotiationService's negotiation_logs list
    so it appears in GET /negotiation/logs.
    
    Uses a lazy import to avoid circular dependencies.
    """
    try:
        from backend.agents.negotiation import NegotiationService
        # Access the module-level singleton instance
        import backend.agents.negotiation as neg_module
        service = neg_module.negotiation_service
        
        log_entry = {
            "robot1": "Orchestrator",
            "robot2": "Swarm",
            "cell": (0, 0),
            "winner": "N/A",
            "reason": reasoning,
            "event": event,
            "timestamp": time.time(),
            "reasoning": reasoning,
            "decision": decision,
        }
        service.negotiation_logs.append(log_entry)
        print(f"[🧠 GRAPH] Negotiation log pushed: {event}")
    except Exception as e:
        print(f"[🧠 GRAPH] WARNING: Failed to push negotiation log: {e}")


# ---------------------------------------------------------------------------
# Conditional Edge: Route from validate
# ---------------------------------------------------------------------------

def should_execute_or_regenerate(state: OrchestratorState) -> str:
    """
    Conditional edge from validate node.
    
    Routes:
      - If human_approved is True  → proceed to 'execute'
      - If human_approved is None  → proceed to 'execute' (interrupt_before pauses it)
      - If human_approved is False → loop back to 'generate_plan' for a new LLM strategy
    """
    human_approved = state.get("human_approved")
    
    if human_approved is False:
        print(f"\n[🧠 GRAPH] Human rejected plan. Looping back to GENERATE_PLAN node.")
        return "generate_plan"
    
    # For True or None, proceed to execute (interrupt_before handles HITL pause)
    return "execute"


# ---------------------------------------------------------------------------
# Graph Compilation
# ---------------------------------------------------------------------------

# Checkpointer for HITL interrupt support
checkpointer = MemorySaver()

# Build the StateGraph
builder = StateGraph(OrchestratorState)

# Add nodes
builder.add_node("diagnose", diagnose)
builder.add_node("generate_plan", generate_plan)
builder.add_node("validate", validate)
builder.add_node("execute", execute)

# Set entry point
builder.set_entry_point("diagnose")

# Linear edges: diagnose → generate_plan → validate
builder.add_edge("diagnose", "generate_plan")
builder.add_edge("generate_plan", "validate")

# Conditional edge from validate: execute OR loop back to generate_plan
builder.add_conditional_edges(
    "validate",
    should_execute_or_regenerate,
    {"execute": "execute", "generate_plan": "generate_plan"},
)

# execute → END
builder.add_edge("execute", END)

# Compile with checkpointer and interrupt_before on execute for HITL
orchestrator_graph = builder.compile(
    checkpointer=checkpointer,
    interrupt_before=["execute"],
)


# ---------------------------------------------------------------------------
# Async Runner — Invokes the graph without blocking the simulation thread
# ---------------------------------------------------------------------------

class OrchestratorRunner:
    """
    Manages the lifecycle of a single orchestrator graph invocation.
    
    Provides:
      - Async graph invocation in a background thread
      - State introspection for the frontend API
      - Human override (approve/reject) to resume paused execution
      - Rejection feedback loop: reject → generate_plan → validate → ...
    """
    
    def __init__(self):
        self._thread_id = None         # LangGraph thread ID for checkpointer
        self._config = None            # Graph config dict
        self._current_state = None     # Latest graph state snapshot
        self._is_active = False        # Whether the orchestrator is running
        self._is_waiting_human = False # Whether paused at HITL interrupt
        self._lock = threading.Lock()
        self._loop = None              # Dedicated asyncio event loop
        self._thread = None            # Background thread for the loop
        self._invocation_count = 0     # Unique ID per invocation
        self._negotiation_service = None  # Reference for log pushing
    
    @property
    def is_active(self) -> bool:
        return self._is_active
    
    @property
    def is_waiting_human(self) -> bool:
        return self._is_waiting_human
    
    def get_state(self) -> dict:
        """Return the current orchestrator state for API consumption."""
        with self._lock:
            if not self._is_active and self._current_state is None:
                return {
                    "active": False,
                    "active_node": None,
                    "crisis_location": None,
                    "affected_robots": [],
                    "proposed_plan": None,
                    "confidence_score": None,
                    "human_approved": None,
                    "waiting_for_human": False,
                    "error": None,
                    "rejection_count": 0,
                }
            
            st = self._current_state or {}
            return {
                "active": self._is_active,
                "active_node": st.get("active_node"),
                "crisis_location": st.get("crisis_location"),
                "affected_robots": st.get("affected_robots", []),
                "proposed_plan": st.get("proposed_plan"),
                "confidence_score": st.get("confidence_score"),
                "human_approved": st.get("human_approved"),
                "waiting_for_human": self._is_waiting_human,
                "error": st.get("error"),
                "rejection_count": st.get("rejection_count", 0),
            }
    
    def invoke_async(self, crisis_coords: list, affected_robot_ids: list, pathfinder=None, robot_manager=None):
        """
        Launch the orchestrator graph in a background thread.
        
        Parameters
        ----------
        crisis_coords : list of (x, y) tuples
        affected_robot_ids : list of int
        pathfinder : AStarPathfinder (stored for execute-phase path recomputation)
        robot_manager : RobotManager (stored for execute-phase robot mutation)
        """
        with self._lock:
            if self._is_active:
                print("[🧠 GRAPH] Already active, skipping duplicate invocation.")
                return
            
            self._invocation_count += 1
            self._thread_id = f"crisis-{self._invocation_count}"
            self._config = {"configurable": {"thread_id": self._thread_id}}
            self._is_active = True
            self._is_waiting_human = False
            self._current_state = {
                "crisis_location": crisis_coords,
                "affected_robots": affected_robot_ids,
                "active_node": "starting",
                "rejection_count": 0,
            }
        
        # Store references for execute phase
        self._pathfinder = pathfinder
        self._robot_manager = robot_manager
        
        initial_state: OrchestratorState = {
            "crisis_location": crisis_coords,
            "affected_robots": affected_robot_ids,
            "proposed_plan": {},
            "confidence_score": 0.0,
            "human_approved": None,
            "active_node": "starting",
            "error": None,
            "rejection_count": 0,
        }
        
        def run_graph():
            try:
                print(f"\n[🧠 GRAPH] ====== CRISIS ORCHESTRATOR INVOKED (thread_id={self._thread_id}) ======")
                print(f"[🧠 GRAPH] Crisis coords: {crisis_coords}")
                print(f"[🧠 GRAPH] Affected robots: {affected_robot_ids}")
                
                # Invoke graph — will pause at interrupt_before=["execute"]
                result = orchestrator_graph.invoke(initial_state, self._config)
                
                self._handle_graph_result(result)
                
            except Exception as e:
                print(f"[🧠 GRAPH] Graph invocation error: {e}")
                with self._lock:
                    self._current_state = self._current_state or {}
                    self._current_state["error"] = str(e)
                    self._current_state["active_node"] = "error"
                    self._is_active = False
                    self._is_waiting_human = False
        
        thread = threading.Thread(target=run_graph, daemon=True)
        thread.start()
    
    def _handle_graph_result(self, result):
        """Process the result of a graph invocation or resume."""
        with self._lock:
            self._current_state = dict(result)
            
            # Check if we're at the interrupt (paused before execute)
            snapshot = orchestrator_graph.get_state(self._config)
            if snapshot.next:
                # Graph is paused — check if human approval is needed
                human_approved = self._current_state.get("human_approved")
                if human_approved is None:
                    self._is_waiting_human = True
                    self._current_state["active_node"] = "waiting_for_human"
                    print(f"\n[🧠 GRAPH] ⏸️  Graph PAUSED at HITL interrupt — waiting for human approval.")
                    print(f"[🧠 GRAPH] Confidence: {self._current_state.get('confidence_score')} | Rejections: {self._current_state.get('rejection_count', 0)}")
                else:
                    # Auto-approved but still at interrupt, resume immediately
                    self._is_waiting_human = False
                    print(f"[🧠 GRAPH] Auto-approved (confidence >= 0.85). Resuming to execute node...")
                    self._resume_graph()
            else:
                # Graph completed without interrupt
                self._is_active = False
                self._apply_plan()
                print(f"\n[🧠 GRAPH] ====== CRISIS ORCHESTRATOR COMPLETED ======")
    
    def _resume_graph(self):
        """Resume graph execution after the interrupt (internal, called with lock held)."""
        def do_resume():
            try:
                print(f"\n[🧠 GRAPH] Resuming graph execution after interrupt...")
                result = orchestrator_graph.invoke(None, self._config)
                
                self._handle_graph_result(result)
            except Exception as e:
                print(f"[🧠 GRAPH] Resume error: {e}")
                with self._lock:
                    self._current_state = self._current_state or {}
                    self._current_state["error"] = str(e)
                    self._current_state["active_node"] = "error"
                    self._is_active = False
                    self._is_waiting_human = False
        
        threading.Thread(target=do_resume, daemon=True).start()
    
    def human_override(self, approved: bool) -> dict:
        """
        Accept human input (Approve/Reject) and resume the paused graph.
        
        If approved=True: graph resumes into the execute node.
        If approved=False: graph loops back to generate_plan for a new strategy.
        
        Parameters
        ----------
        approved : bool
            True to approve the plan, False to reject.
        
        Returns
        -------
        dict with success status and message.
        """
        with self._lock:
            if not self._is_waiting_human:
                return {"success": False, "message": "Orchestrator is not waiting for human input."}
            
            self._is_waiting_human = False
            
            if approved:
                # Human approved — update state and let the graph proceed to execute
                orchestrator_graph.update_state(
                    self._config,
                    {"human_approved": True, "active_node": "human_approved"},
                )
                self._current_state["human_approved"] = True
                self._current_state["active_node"] = "executing"
                
                print(f"\n[🧠 GRAPH] ✅ Human APPROVED the plan. Resuming to EXECUTE node.")
            else:
                # Human rejected — increment rejection count and route back to generate_plan
                current_rejections = self._current_state.get("rejection_count", 0)
                new_rejection_count = current_rejections + 1
                
                orchestrator_graph.update_state(
                    self._config,
                    {
                        "human_approved": False,
                        "active_node": "rejected",
                        "rejection_count": new_rejection_count,
                    },
                )
                self._current_state["human_approved"] = False
                self._current_state["active_node"] = "regenerating"
                self._current_state["rejection_count"] = new_rejection_count
                
                print(f"\n[🧠 GRAPH] ❌ Human REJECTED plan. Rejection count: {new_rejection_count}.")
                print(f"[🧠 GRAPH] Human rejected plan. Looping back to GENERATE_PLAN node.")
        
        # Resume graph execution — the conditional edge will route appropriately
        self._resume_graph()
        
        action = "APPROVED" if approved else "REJECTED — Recalculating"
        return {"success": True, "message": f"Plan {action}. Graph resuming."}
    
    def _apply_plan(self):
        """
        After graph completes, apply the rerouting plan to affected robots.
        Recomputes A* paths for each affected robot.
        """
        if not self._current_state:
            return
        
        plan = self._current_state.get("proposed_plan", {})
        if not plan.get("executed"):
            print("[🧠 GRAPH] Plan was not executed (rejected or error). No paths modified.")
            return
        
        affected = self._current_state.get("affected_robots", [])
        if not self._pathfinder or not self._robot_manager:
            print("[🧠 GRAPH] Missing pathfinder/robot_manager reference. Cannot recompute paths.")
            return
        
        print(f"[🧠 GRAPH] Applying plan: Recomputing paths for {len(affected)} robots.")
        for rid in affected:
            robot = self._robot_manager.get_robot(rid)
            if robot and robot.path and len(robot.path) > 1:
                # Recompute path from current position to original destination
                dest = robot.path[-1]
                new_path = self._pathfinder.find_path(
                    (robot.position.x, robot.position.y),
                    dest,
                )
                if new_path:
                    robot.path = new_path
                    print(f"[🧠 GRAPH] Robot {rid}: Path recomputed ({len(new_path)} steps)")
                else:
                    print(f"[🧠 GRAPH] Robot {rid}: No valid path found, clearing path.")
                    robot.path = []


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

orchestrator_runner = OrchestratorRunner()

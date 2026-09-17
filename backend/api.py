import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import JSONResponse
from copy import deepcopy
from functools import wraps
from typing import Literal
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, StrictBool, Field

from backend.simulation.warehouse import Warehouse
from backend.state.robot_state import RobotManager
from backend.simulation.pathfinder import AStarPathfinder
from backend.state.task_state import TaskManager
from backend.simulation.collision import CollisionManager
from backend.simulation.charging import ChargingManager
from backend.simulation.engine import SimulationEngine
from backend.agents.robot_orchestrator import AgentManager
from backend.agents.message_bus import MessageBus
from backend.agents.task_orchestrator import TaskAgentManager
from backend.agents.negotiation import NegotiationService
from backend.simulation.factory import create_simulation
from backend.core.settings import Settings
import logging

class HealthLogFilter(logging.Filter):
    def __init__(self):
        super().__init__()
        self.last_log_time = 0.0

    def filter(self, record: logging.LogRecord) -> bool:
        msg = record.getMessage()
        health_paths = [
            "/warehouse/grid",
            "/agents/status",
            "/simulation/status",
            "/tasks",
            "/auction/logs",
            "/negotiation/logs",
            "/orchestrator/state",
            "/robots",
            "/agents/messages",
            "/tasks/agents"
        ]
        if any(path in msg for path in health_paths):
            now = time.time()
            if now - self.last_log_time >= 20.0:
                self.last_log_time = now
                return True
            return False
        return True

# Apply filter to uvicorn.access logger
logging.getLogger("uvicorn.access").addFilter(HealthLogFilter())



# --- Pydantic Request Models ---

class TaskCreateRequest(BaseModel):
    pickup_x: int
    pickup_y: int
    delivery_x: int
    delivery_y: int
    priority: Literal["NORMAL", "CRITICAL"] = "NORMAL"


# --- Simulation Factory ---

simulation_lock = threading.RLock()
control_lock = threading.RLock()
loop_stop = threading.Event()


def initialize_simulation(seed=None, settings=None):
    engine = create_simulation(seed=seed, settings=settings, lock=simulation_lock)
    return (engine.pathfinder.warehouse, engine.robot_manager, engine.task_manager,
            engine.pathfinder, engine.collision_manager, engine.charging_manager,
            engine.agent_manager, engine.agent_manager.message_bus, engine.task_agent_manager,
            engine.negotiation_service, engine)


def snapshot_response(function):
    """Serialize detached data; response serialization never races with a tick."""
    @wraps(function)
    def wrapped(*args, **kwargs):
        with simulation_lock:
            return deepcopy(function(*args, **kwargs))
    return wrapped


# --- Simulation Initialization ---

(
    warehouse,
    robot_manager,
    task_manager,
    pathfinder,
    collision_manager,
    charging_manager,
    agent_manager,
    message_bus,
    task_agent_manager,
    negotiation_service,
    simulation
) = initialize_simulation()


# --- Thread State ---

simulation_running = False
simulation_thread = None


# --- Background Loop ---

def simulation_loop(stop_event, engine):
    global simulation_running
    try:
        while not stop_event.is_set():
            with simulation_lock:
                if stop_event.is_set() or engine is not simulation:
                    break
                engine.step()
            stop_event.wait(0.2)
    except Exception:
        logging.getLogger("warehouse").exception("[ERROR] Simulation worker failed run_id=%s", engine.run_id)
        engine.events.emit("SIMULATION_FAILED", tag="ERROR", step=engine.current_step,
                           reason="Simulation paused after an internal error")
    finally:
        with simulation_lock:
            if engine is simulation:
                simulation_running = False


# --- FastAPI App ---

app = FastAPI(
    title="Warehouse Swarm API",
    description="Multi-Agent Warehouse Swarm Robotics Simulation API",
    version="3.0.0"
)

app.mount("/static", StaticFiles(directory=str(PROJECT_ROOT / "frontend")), name="static")

templates = Jinja2Templates(
    directory=str(PROJECT_ROOT / "frontend")
)


# ===========================
# DAY 15 — VISUALIZATION
# ===========================

@app.get("/dashboard")
def dashboard(request: Request):
    """Serve the warehouse visualization dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html"
    )

@app.get("/OperationCentre")
def operation_centre(request: Request):
    """Serve the advanced AI Operations Centre dashboard."""
    return templates.TemplateResponse(
        request=request,
        name="OperationCentre.html"
    )


@app.get("/warehouse/grid")
@snapshot_response
def get_warehouse_grid():
    """Return the warehouse grid layout."""
    return {
        "width": warehouse.width,
        "height": warehouse.height,
        "grid": warehouse.grid
    }


# ===========================
# CORE ENDPOINTS
# ===========================

@app.get("/")
def root():
    return {
        "message": "Warehouse Swarm API"
    }


@app.get("/robots")
@snapshot_response
def get_robots():
    return [
        {
            "id": robot.id,
            "position": {
                "x": robot.position.x,
                "y": robot.position.y
            },
            "battery": robot.battery,
            "status": robot.status.value,
            "current_task": robot.current_task,
            "hold_steps_remaining": robot.hold_steps_remaining,
            "yield_to_robot_id": robot.yield_to_robot_id,
            "orchestration_held": bool(robot.orchestration_holds),
            "path": [[p[0], p[1]] for p in robot.path] if robot.path else []
        }
        for robot in robot_manager.robots
    ]


@app.get("/tasks")
@snapshot_response
def get_tasks():
    return [
        {
            "id": task.id,
            "assigned_robot": task.assigned_robot,
            "completed": task.completed,
            "pickup_x": task.pickup_x,
            "pickup_y": task.pickup_y,
            "delivery_x": task.delivery_x,
            "delivery_y": task.delivery_y,
            "priority": task.priority
        }
        for task in task_manager.tasks
    ]


@app.get("/auction/logs")
@snapshot_response
def get_auction_logs():
    """Return the raw bids from the most recent task CNP auctions."""
    return list(task_agent_manager.latest_logs)

@app.get("/negotiation/logs")
@snapshot_response
def get_negotiation_logs():
    """Return the last 5 deadlock negotiation or auction explanation logs from the local LLM."""
    return negotiation_service.recent(5)


# ============================
# SIMULATION CONTROL
# ============================

@app.post("/simulation/step")
def post_simulation_step():
    """Execute exactly one simulation step."""

    with simulation_lock:
        simulation.step()

    return {
        "success": True,
        "current_step": simulation.current_step
    }


@app.post("/tasks/create")
def post_create_task(request: TaskCreateRequest):
    """Create a new task dynamically via API. Automatically creates a TaskAgent."""

    with simulation_lock:
        if not warehouse.is_walkable(request.pickup_x, request.pickup_y) or not warehouse.is_walkable(request.delivery_x, request.delivery_y):
            raise HTTPException(400, "Task coordinates must be inside walkable warehouse cells")
        if not pathfinder.find_path((request.pickup_x, request.pickup_y), (request.delivery_x, request.delivery_y)):
            raise HTTPException(400, "Task pickup and delivery must be connected")
        task_manager.create_task(
            request.pickup_x,
            request.pickup_y,
            request.delivery_x,
            request.delivery_y,
            request.priority
        )

        new_task_id = task_manager.next_task_id - 1

        # Create a TaskAgent for the new task
        task_agent_manager.create_agent_for_task(new_task_id)

    return {
        "success": True,
        "task_id": new_task_id
    }


class ResetRequest(BaseModel):
    seed: int | None = None
    orchestrator_enabled: bool | None = None


@app.post("/simulation/reset")
def post_simulation_reset(request: ResetRequest | None = None):
    """Reset the entire simulation to initial state."""

    global warehouse
    global robot_manager
    global task_manager
    global pathfinder
    global collision_manager
    global charging_manager
    global agent_manager
    global message_bus
    global task_agent_manager
    global negotiation_service
    global simulation
    global simulation_running
    global simulation_thread

    global loop_stop
    with control_lock:
        loop_stop.set()
        with simulation_lock:
            simulation_running = False
            old = simulation
            old.close()
            selected_seed = request.seed if request and request.seed is not None else old.seed
            settings = old.settings
            if request and request.orchestrator_enabled is not None:
                settings = settings.model_copy(update={"orchestrator_enabled": request.orchestrator_enabled})
            (warehouse, robot_manager, task_manager, pathfinder, collision_manager,
             charging_manager, agent_manager, message_bus, task_agent_manager,
             negotiation_service, simulation) = initialize_simulation(selected_seed, settings)
        if simulation_thread is not None:
            simulation_thread.join(timeout=2.0)
            simulation_thread = None

    return {
        "success": True,
        "message": "Simulation reset"
    }


# ===============================
# AUTONOMOUS LOOP
# ===============================

@app.post("/simulation/start")
def post_simulation_start():
    """Start the autonomous simulation loop in a background thread."""

    global simulation_running
    global simulation_thread

    global loop_stop
    with control_lock:
        with simulation_lock:
            if simulation_running:
                raise HTTPException(409, "Simulation already running")
            loop_stop = threading.Event()
            simulation_running = True
            simulation_thread = threading.Thread(target=simulation_loop, args=(loop_stop, simulation), daemon=True)
            simulation_thread.start()
    return {"success": True, "message": "Simulation started"}


@app.post("/simulation/pause")
def post_simulation_pause():
    """Pause the autonomous simulation loop."""

    global simulation_running
    global simulation_thread

    with control_lock:
        loop_stop.set()
        with simulation_lock:
            simulation_running = False
        if simulation_thread is not None:
            simulation_thread.join(timeout=2.0)
            simulation_thread = None
    return {"success": True, "message": "Simulation paused"}


# ============================
# SIMULATION STATUS
# ============================

@app.get("/simulation/status")
@snapshot_response
def get_simulation_status():
    """Return comprehensive simulation status."""

    active_robots = [
        robot
        for robot in robot_manager.robots
        if robot.current_task is not None
    ]

    unfinished_tasks = [
        task
        for task in task_manager.tasks
        if not task.completed
    ]

    total_strikes = sum(agent.blocked_counter for agent in agent_manager.agents) if agent_manager else 0

    return {
        "run_id": simulation.run_id,
        "seed": simulation.seed,
        "grid_revision": warehouse.revision,
        "orchestrator_enabled": simulation.settings.orchestrator_enabled,
        "current_step": simulation.current_step,
        "active_robots": len(active_robots),
        "unfinished_tasks": len(unfinished_tasks),
        "total_robots": len(robot_manager.robots),
        "total_tasks": len(task_manager.tasks),
        "simulation_complete": simulation.is_complete(),
        "running": simulation_running,
        "total_strikes": total_strikes,
        "orchestrator_active": simulation.orchestrator_active
    }


# ============================
# AGENT INTROSPECTION
# ============================

@app.get("/agents/status")
@snapshot_response
def get_agents_status():
    """Return the current goal, beliefs, memory size, and pending messages for every robot agent."""
    return {
        "agents": [
            {
                "robot_id": agent.robot.id,
                "goal": agent.goal,
                "beliefs": agent.beliefs,
                "memory_size": len(agent.memory),
                "pending_messages": message_bus.pending_count(agent.agent_id),
            }
            for agent in agent_manager.agents
        ]
    }


@app.get("/agents/message-history")
@snapshot_response
def get_message_history():
    return message_bus.history()


@app.get("/agents/messages")
@snapshot_response
def get_agents_messages():
    """Return pending messages for every robot agent (peek without consuming)."""
    return {
        "agents": [
            {
                "robot_id": agent.robot.id,
                "pending_messages": [
                    {
                        "id": msg.id,
                        "sender": msg.sender,
                        "type": msg.message_type.value,
                        "payload": msg.payload,
                    }
                    for msg in message_bus.peek_messages(agent.agent_id)
                ]
            }
            for agent in agent_manager.agents
        ]
    }


@app.get("/tasks/agents")
@snapshot_response
def get_task_agents_status():
    """Return the status of all task agents (CNP lifecycle)."""
    return {
        "task_agents": task_agent_manager.get_all_status()
    }


# ============================
# ORCHESTRATOR ENDPOINTS
# ============================

class OrchestratorOverrideRequest(BaseModel):
    approved: StrictBool
    plan_id: str | None = None


@app.get("/orchestrator/state")
@snapshot_response
def get_orchestrator_state():
    """Return the current LangGraph orchestrator state for frontend HUD."""
    return simulation.orchestrator_runner.get_state()


@app.post("/orchestrator/override")
def post_orchestrator_override(request: OrchestratorOverrideRequest):
    """Accept human input (Approve/Reject) and resume the paused LangGraph execution."""
    with simulation_lock:
        result = simulation.orchestrator_runner.human_override(request.approved, request.plan_id)
    if not result["success"]:
        raise HTTPException(409, result["message"])
    return result


class CrisisCreateRequest(BaseModel):
    coords: list[tuple[int, int]] | None = Field(default=None, min_length=1, max_length=10)


@app.post("/simulation/crisis")
def post_crisis(request: CrisisCreateRequest | None = None):
    with simulation_lock:
        try:
            crisis_id = simulation.trigger_warehouse_crisis(request.coords if request else None)
        except ValueError as error:
            raise HTTPException(400, str(error)) from error
        if crisis_id is None:
            raise HTTPException(409, "No eligible cells remain for collapse")
        return {"success": True, "crisis_id": crisis_id}


@app.get("/orchestrator/events")
@snapshot_response
def get_events(event_type: str | None = None, robot_id: int | None = None,
               crisis_id: str | None = None, limit: int = Query(default=100, ge=1, le=2000)):
    return {"run_id": simulation.run_id, "events": simulation.events.query(
        limit=limit, event_type=event_type, robot_id=robot_id, crisis_id=crisis_id)}


@app.exception_handler(Exception)
async def unexpected_error(request: Request, error: Exception):
    logging.getLogger("warehouse").error("[ERROR] API request failed path=%s", request.url.path,
                                        exc_info=(type(error), error, error.__traceback__))
    return JSONResponse(status_code=500, content={"detail": "Internal server error; consult backend logs"})

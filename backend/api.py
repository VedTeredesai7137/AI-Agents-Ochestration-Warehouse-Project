import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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
from backend.agents.orchestrator_graph import orchestrator_runner
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
    priority: str = "NORMAL"


# --- Simulation Factory ---

def initialize_simulation():
    """
    Creates all simulation components and returns them.
    Used at startup and by the reset endpoint.

    Architecture:
      MessageBus connects TaskAgents and RobotAgents.
      TaskAgentManager issues CFPs and awards contracts.
      AgentManager drives robot perceive-decide-act cycles.
      SimulationEngine orchestrates ticks without making decisions.
    """

    warehouse = Warehouse(width=50, height=30)
    warehouse.generate()

    robot_manager = RobotManager()
    robot_manager.spawn_from_warehouse(warehouse)

    task_manager = TaskManager()

    import random
    def get_random_walkable():
        while True:
            x = random.randint(1, warehouse.width - 2)
            y = random.randint(1, warehouse.height - 2)
            if warehouse.grid[y][x] == ".":
                return x, y

    for _ in range(120):
        px, py = get_random_walkable()
        dx, dy = get_random_walkable()
        task_manager.create_task(px, py, dx, dy)

    pathfinder = AStarPathfinder(warehouse)

    collision_manager = CollisionManager()

    charging_manager = ChargingManager()

    # --- Multi-Agent System ---
    message_bus = MessageBus()

    agent_manager = AgentManager(robot_manager, message_bus=message_bus)
    agent_manager.create_agents()

    task_agent_manager = TaskAgentManager(task_manager, message_bus)
    task_agent_manager.create_agents_for_existing_tasks()

    negotiation_service = NegotiationService()

    simulation = SimulationEngine(
        robot_manager,
        collision_manager,
        task_manager,
        charging_manager,
        pathfinder,
        agent_manager=agent_manager,
        task_agent_manager=task_agent_manager,
        negotiation_service=negotiation_service,
    )

    return (
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
    )



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

simulation_lock = threading.Lock()
simulation_running = False
simulation_thread = None


# --- Background Loop ---

def simulation_loop():
    """
    Target function for the background simulation thread.
    Runs simulation.step() in a loop with 0.2s delay.
    Lock is acquired only for the step, not during sleep.
    """
    global simulation_running

    while simulation_running:

        with simulation_lock:
            simulation.step()

        time.sleep(0.2)


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
            "path": [[p[0], p[1]] for p in robot.path] if robot.path else []
        }
        for robot in robot_manager.robots
    ]


@app.get("/tasks")
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
def get_auction_logs():
    """Return the raw bids from the most recent task CNP auctions."""
    return task_agent_manager.latest_logs

@app.get("/negotiation/logs")
def get_negotiation_logs():
    """Return the last 5 deadlock negotiation or auction explanation logs from the local LLM."""
    return negotiation_service.negotiation_logs[-5:]


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


@app.post("/simulation/reset")
def post_simulation_reset():
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

    with simulation_lock:

        # Stop background thread if running
        simulation_running = False

    if simulation_thread is not None:
        simulation_thread.join(timeout=2.0)
        simulation_thread = None

    with simulation_lock:

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

    if simulation_running:
        return {
            "success": False,
            "message": "Simulation already running"
        }

    simulation_running = True

    simulation_thread = threading.Thread(
        target=simulation_loop,
        daemon=True
    )
    simulation_thread.start()

    return {
        "success": True,
        "message": "Simulation started"
    }


@app.post("/simulation/pause")
def post_simulation_pause():
    """Pause the autonomous simulation loop."""

    global simulation_running
    global simulation_thread

    simulation_running = False

    if simulation_thread is not None:
        simulation_thread.join(timeout=2.0)
        simulation_thread = None

    return {
        "success": True,
        "message": "Simulation paused"
    }


# ============================
# SIMULATION STATUS
# ============================

@app.get("/simulation/status")
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


@app.get("/agents/messages")
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
def get_task_agents_status():
    """Return the status of all task agents (CNP lifecycle)."""
    return {
        "task_agents": task_agent_manager.get_all_status()
    }


# ============================
# ORCHESTRATOR ENDPOINTS
# ============================

class OrchestratorOverrideRequest(BaseModel):
    approved: bool


@app.get("/orchestrator/state")
def get_orchestrator_state():
    """Return the current LangGraph orchestrator state for frontend HUD."""
    return orchestrator_runner.get_state()


@app.post("/orchestrator/override")
def post_orchestrator_override(request: OrchestratorOverrideRequest):
    """Accept human input (Approve/Reject) and resume the paused LangGraph execution."""
    result = orchestrator_runner.human_override(request.approved)
    return result

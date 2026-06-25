import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from simulation.warehouse import Warehouse
from simulation.robot_manager import RobotManager
from simulation.pathfinder import AStarPathfinder
from simulation.task_manager import TaskManager
from simulation.collision_manager import CollisionManager
from simulation.auction_manager import AuctionManager
from simulation.charging_manager import ChargingManager
from simulation.simulation_engine import SimulationEngine
from simulation.agent_manager import AgentManager


# --- Pydantic Request Models ---

class TaskCreateRequest(BaseModel):
    pickup_x: int
    pickup_y: int
    delivery_x: int
    delivery_y: int


# --- Simulation Factory ---

def initialize_simulation():
    """
    Creates all simulation components and returns them.
    Used at startup and by the reset endpoint.
    """

    warehouse = Warehouse(width=30, height=20)
    warehouse.generate()

    robot_manager = RobotManager()
    robot_manager.spawn_from_warehouse(warehouse)

    task_manager = TaskManager()

    task_manager.create_task(10, 1, 1, 1)
    task_manager.create_task(15, 4, 1, 4)
    task_manager.create_task(20, 7, 1, 7)
    task_manager.create_task(25, 10, 1, 10)
    task_manager.create_task(27, 13, 1, 13)

    pathfinder = AStarPathfinder(warehouse)

    collision_manager = CollisionManager()

    charging_manager = ChargingManager()

    auction_manager = AuctionManager(robot_manager)

    agent_manager = AgentManager(robot_manager)
    agent_manager.create_agents()

    simulation = SimulationEngine(
        robot_manager,
        collision_manager,
        task_manager,
        charging_manager,
        pathfinder,
        auction_manager,
        agent_manager=agent_manager
    )

    return (
        warehouse,
        robot_manager,
        task_manager,
        pathfinder,
        collision_manager,
        charging_manager,
        auction_manager,
        agent_manager,
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
    auction_manager,
    agent_manager,
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
    description="API for the Warehouse Swarm Robotics Simulation",
    version="2.0.0"
)

templates = Jinja2Templates(
    directory=str(Path(__file__).parent / "templates")
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


@app.get("/warehouse/grid")
def get_warehouse_grid():
    """Return the warehouse grid layout."""
    return {
        "width": warehouse.width,
        "height": warehouse.height,
        "grid": warehouse.grid
    }


# ===========================
# EXISTING ENDPOINTS (Day 12)
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
            "current_task": robot.current_task
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
            "delivery_y": task.delivery_y
        }
        for task in task_manager.tasks
    ]


# ============================
# DAY 13 — SIMULATION CONTROL
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
    """Create a new task dynamically via API."""

    with simulation_lock:
        task_manager.create_task(
            request.pickup_x,
            request.pickup_y,
            request.delivery_x,
            request.delivery_y
        )

    new_task_id = task_manager.next_task_id - 1

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
    global auction_manager
    global agent_manager
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
            auction_manager,
            agent_manager,
            simulation
        ) = initialize_simulation()

    return {
        "success": True,
        "message": "Simulation reset"
    }


# ===============================
# DAY 14 — AUTONOMOUS LOOP
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
# ENHANCED STATUS (Day 14)
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

    return {
        "current_step": simulation.current_step,
        "active_robots": len(active_robots),
        "unfinished_tasks": len(unfinished_tasks),
        "total_robots": len(robot_manager.robots),
        "total_tasks": len(task_manager.tasks),
        "simulation_complete": simulation.is_complete(),
        "running": simulation_running
    }


# ============================
# AGENT INTROSPECTION
# ============================

@app.get("/agents/status")
def get_agents_status():
    """Return the current goal and beliefs for every robot agent."""
    return {
        "agents": [
            {
                "robot_id": agent.robot.id,
                "goal": agent.goal,
                "beliefs": agent.beliefs,
                "memory_size": len(agent.memory),
            }
            for agent in agent_manager.agents
        ]
    }

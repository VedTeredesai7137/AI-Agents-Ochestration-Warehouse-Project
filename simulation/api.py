import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi import FastAPI

from simulation.warehouse import Warehouse
from simulation.robot_manager import RobotManager
from simulation.pathfinder import AStarPathfinder
from simulation.task_manager import TaskManager
from simulation.collision_manager import CollisionManager
from simulation.auction_manager import AuctionManager
from simulation.charging_manager import ChargingManager
from simulation.simulation_engine import SimulationEngine


# --- Simulation Initialization ---

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

simulation = SimulationEngine(
    robot_manager,
    collision_manager,
    task_manager,
    charging_manager,
    pathfinder,
    auction_manager
)


# --- FastAPI App ---

app = FastAPI(
    title="Warehouse Swarm API",
    description="API for the Warehouse Swarm Robotics Simulation",
    version="1.0.0"
)


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


@app.get("/simulation/status")
def get_simulation_status():

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
        "unfinished_tasks": len(unfinished_tasks)
    }

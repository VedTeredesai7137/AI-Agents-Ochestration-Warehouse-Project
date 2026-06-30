import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from simulation.warehouse import Warehouse
from simulation.robot_manager import RobotManager
from simulation.pathfinder import AStarPathfinder
from simulation.task_manager import TaskManager
from simulation.collision_manager import CollisionManager
from simulation.charging_manager import ChargingManager
from simulation.simulation_engine import SimulationEngine
from simulation.agent_manager import AgentManager
from simulation.message_bus import MessageBus
from simulation.task_agent_manager import TaskAgentManager


def main():

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

    # --- Multi-Agent System ---
    message_bus = MessageBus()

    agent_manager = AgentManager(robot_manager, message_bus=message_bus)
    agent_manager.create_agents()

    task_agent_manager = TaskAgentManager(task_manager, message_bus)
    task_agent_manager.create_agents_for_existing_tasks()

    simulation = SimulationEngine(
        robot_manager,
        collision_manager,
        task_manager,
        charging_manager,
        pathfinder,
        agent_manager=agent_manager,
        task_agent_manager=task_agent_manager,
    )

    print(f"Robots: {len(robot_manager.robots)}")
    print(f"Tasks: {len(task_manager.tasks)}")
    print(f"MessageBus: {message_bus}")
    print(f"Agent Manager: {agent_manager}")
    print(f"Task Agent Manager: {task_agent_manager}")

    while not simulation.is_complete():

        simulation.step()

        if simulation.current_step == 10:
            task_manager.create_task(5, 6, 1, 6)
            task_agent_manager.create_agent_for_task(
                task_manager.next_task_id - 1
            )

        if simulation.current_step == 20:
            task_manager.create_task(18, 15, 1, 15)
            task_agent_manager.create_agent_for_task(
                task_manager.next_task_id - 1
            )

        if simulation.current_step % 50 == 0:
            print("\nDEBUG")
            for task in task_manager.tasks:
                print(task.id, task.assigned_robot, task.completed)

    print("\nSIMULATION COMPLETE")


if __name__ == "__main__":
    main()
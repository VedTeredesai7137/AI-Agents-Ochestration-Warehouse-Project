import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from simulation.warehouse import Warehouse
from simulation.robot_manager import RobotManager
from simulation.pathfinder import AStarPathfinder
from simulation.task_manager import TaskManager
from simulation.collision_manager import CollisionManager
from simulation.auction_manager import AuctionManager
from simulation.charging_manager import ChargingManager
from simulation.simulation_engine import SimulationEngine


def main():

    warehouse = Warehouse(width=30, height=20)
    warehouse.generate()

    robot_manager = RobotManager()
    robot_manager.spawn_from_warehouse(
        warehouse
    )

    task_manager = TaskManager()

    task_manager.create_task(10, 1)
    task_manager.create_task(15, 4)
    task_manager.create_task(20, 7)
    task_manager.create_task(25, 10)
    task_manager.create_task(27, 13)

    pathfinder = AStarPathfinder(
        warehouse
    )

    collision_manager = (
        CollisionManager()
    )

    charging_manager = (
        ChargingManager()
    )

    auction_manager = (
        AuctionManager(
            robot_manager
        )
    )

    simulation = (
        SimulationEngine(
            robot_manager,
            collision_manager,
            task_manager,
            charging_manager,
            pathfinder,
            auction_manager
        )
    )
    print( f"Robots: {len(robot_manager.robots)}" )
    print( f"Tasks: {len(task_manager.tasks)}" )
    print( f"Pathfinder: {pathfinder}" )
    print( f"Collision Manager: {collision_manager}" )
    print( f"Charging Manager: {charging_manager}" )
    print( f"Auction Manager: {auction_manager}" )

    while (
        not simulation.is_complete()
    ):

        simulation.step()

        if (
            simulation.current_step
            == 10
        ):

            task_manager.create_task(
                5,
                6
            )

        if (
            simulation.current_step
            == 20
        ):

            task_manager.create_task(
                18,
                15
            )
        if simulation.current_step % 50 == 0:

            print("\nDEBUG")

            for task in task_manager.tasks:

                print(
                    task.id,
            task.assigned_robot,
            task.completed
        )

    print(
        "\nSIMULATION COMPLETE"
    )


if __name__ == "__main__":
    main()
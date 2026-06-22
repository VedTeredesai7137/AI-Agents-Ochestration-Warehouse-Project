import sys
from pathlib import Path

PROJECT_ROOT = (
    Path(__file__)
    .parent
    .parent
)

sys.path.insert(
    0,
    str(PROJECT_ROOT)
)

from simulation.warehouse import (
    Warehouse
)

from simulation.robot_manager import (
    RobotManager
)

from simulation.pathfinder import (
    AStarPathfinder
)

from simulation.task_manager import (
    TaskManager
)

from simulation.collision_manager import (
    CollisionManager
)

from simulation.simulation_engine import (
    SimulationEngine
)

from simulation.auction_manager import (
    AuctionManager
)


def main():

    warehouse = Warehouse(
        width=30,
        height=20
    )

    warehouse.generate()

    robot_manager = (
        RobotManager()
    )

    robot_manager.spawn_from_warehouse(
        warehouse
    )

    task_manager = (
        TaskManager()
    )

    task_manager.create_task(
        1,
        10,
        1
    )

    task_manager.create_task(
        2,
        15,
        4
    )

    task_manager.create_task(
        3,
        20,
        7
    )

    task_manager.create_task(
        4,
        25,
        10
    )

    task_manager.create_task(
        5,
        27,
        13
    )

    pathfinder = (
        AStarPathfinder(
            warehouse
        )
    )

    auction_manager = (
        AuctionManager(
            robot_manager
        )
    )

    print(
        "\nAUCTION PHASE\n"
    )

    for task in (
        task_manager.tasks
    ):

        winner_id = (
            auction_manager
            .run_auction(
                task
            )
        )

        if winner_id is None:
            continue

        robot = (
            robot_manager
            .get_robot(
                winner_id
            )
        )

        start = (
            robot.position.x,
            robot.position.y
        )

        goal = (
            task.pickup_x,
            task.pickup_y
        )

        path = (
            pathfinder.find_path(
                start,
                goal
            )
        )

        task_manager.assign_task(
            task.id,
            winner_id
        )

        robot_manager.assign_task(
            winner_id,
            task.id,
            path
        )

    collision_manager = (
        CollisionManager()
    )

    simulation = (
        SimulationEngine(
            robot_manager,
            collision_manager,
            task_manager
        )
    )

    while (
        not simulation.is_complete()
    ):

        simulation.step()

    print(
        "\nSIMULATION COMPLETE"
    )


if __name__ == "__main__":
    main()
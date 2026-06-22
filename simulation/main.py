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

from simulation.simulation_engine import (
    SimulationEngine
)

from simulation.collision_manager import (
    CollisionManager
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

    pathfinder = (
        AStarPathfinder(
            warehouse
        )
    )

    goals = [
        (25, 1),
        (24, 4),
        (23, 7),
        (22, 10),
        (21, 13)
    ]

    for robot_id in range(
        1,
        6
    ):

        robot = (
            robot_manager
            .get_robot(
                robot_id
            )
        )

        start = (
            robot.position.x,
            robot.position.y
        )

        goal = (
            goals[
                robot_id - 1
            ]
        )

        path = (
            pathfinder.find_path(
                start,
                goal
            )
        )

        robot_manager.assign_path(
            robot_id,
            path
        )

    collision_manager = (
        CollisionManager()
    )

    simulation = (
        SimulationEngine(
            robot_manager,
            collision_manager
        )
    )

    while (
        not simulation.is_complete()
    ):

        simulation.step()

    print(
        "\nSimulation Complete"
    )


if __name__ == "__main__":
    main()
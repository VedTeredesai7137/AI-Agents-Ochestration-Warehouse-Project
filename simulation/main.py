import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

sys.path.insert(
    0,
    str(PROJECT_ROOT)
)

from simulation.warehouse import Warehouse
from simulation.robot_manager import RobotManager
from simulation.pathfinder import (
    AStarPathfinder
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

    start = (1, 18)

    goal = (25, 1)

    path = (
        pathfinder.find_path(
            start,
            goal
        )
    )

    print(
        "\nPATH FOUND:\n"
    )

    print(path)

    robot_manager.assign_path(
        1,
        path
    )

    print(
        "\nROBOT MOVEMENT:\n"
    )

    while True:

        robot = (
            robot_manager.get_robot(
                1
            )
        )

        print(robot)

        if len(robot.path) <= 1:
            break

        robot_manager.move_robot_one_step(
            1
        )


if __name__ == "__main__":
    main()
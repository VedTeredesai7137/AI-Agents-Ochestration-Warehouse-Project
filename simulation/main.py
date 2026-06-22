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

    for i in range(5):

        robot = (
            robot_manager.get_robot(
                i + 1
            )
        )

        start = (
            robot.position.x,
            robot.position.y
        )

        goal = goals[i]

        path = (
            pathfinder.find_path(
                start,
                goal
            )
        )

        robot_manager.assign_path(
            robot.id,
            path
        )

        print(
            f"\nRobot {robot.id}"
        )

        print(
            f"Start: {start}"
        )

        print(
            f"Goal : {goal}"
        )

        print(
            f"Path Length: "
            f"{len(path)}"
        )

    simulation = (
        SimulationEngine(
            robot_manager
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
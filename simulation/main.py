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

    print(
        "\nTASKS CREATED\n"
    )

    task_manager.display_tasks()

    pathfinder = (
        AStarPathfinder(
            warehouse
        )
    )

    unassigned_tasks = (
        task_manager
        .get_unassigned_tasks()
    )

    for index, task in enumerate(
        unassigned_tasks
    ):

        robot_id = index + 1

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
            robot_id
        )

        robot_manager.assign_task(
            robot_id,
            task.id,
            path
        )

        print(
            f"\nRobot {robot_id}"
            f" assigned "
            f"Task {task.id}"
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
        "\nALL TASKS REACHED"
    )


if __name__ == "__main__":
    main()
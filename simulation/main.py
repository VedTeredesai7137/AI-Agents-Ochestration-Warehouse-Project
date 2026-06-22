import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(
    0,
    str(PROJECT_ROOT)
)

from simulation.warehouse import Warehouse
from simulation.robot_manager import RobotManager


def main():

    warehouse = Warehouse(
        width=30,
        height=20
    )

    warehouse.generate()

    print(
        "\nWarehouse initialized\n"
    )

    robot_manager = RobotManager()

    robot_manager.spawn_from_warehouse(
        warehouse
    )

    print(
        "Robots Spawned:\n"
    )

    robot_manager.display_robots()

    print(
        "\nMoving Robot 1...\n"
    )

    robot_manager.move_robot_right(
        1
    )

    robot_manager.display_robots()


if __name__ == "__main__":
    main()
print("Program Started")
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from simulation.warehouse import Warehouse


def main():
    warehouse = Warehouse(
        width=30,
        height=20
    )

    warehouse.generate()
    warehouse.render()


if __name__ == "__main__":
    main()
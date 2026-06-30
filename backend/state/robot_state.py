from backend.core.models import (
    Robot,
    Position,
    RobotStatus
)


class RobotManager:

    def __init__(self):

        self.robots = []

    def create_robot(
        self,
        robot_id,
        x,
        y
    ):

        robot = Robot(
            id=robot_id,
            battery=100.0,
            position=Position(
                x=x,
                y=y
            ),
            status=RobotStatus.IDLE
        )

        self.robots.append(
            robot
        )

    def spawn_from_warehouse(
        self,
        warehouse
    ):

        robot_id = 1

        for y in range(
            warehouse.height
        ):

            for x in range(
                warehouse.width
            ):

                if (
                    warehouse.grid[y][x]
                    == "R"
                ):

                    self.create_robot(
                        robot_id,
                        x,
                        y
                    )

                    robot_id += 1

    def get_robot(
        self,
        robot_id
    ):

        for robot in self.robots:

            if robot.id == robot_id:

                return robot

        return None

    def display_robots(self):

        for robot in self.robots:

            print(robot)

    def assign_task(
        self,
        robot_id,
        task_id,
        path
    ):

        robot = self.get_robot(
            robot_id
        )

        if robot is None:
            return

        robot.current_task = (
            task_id
        )

        robot.path = path

        robot.status = (
            RobotStatus.MOVING
        )
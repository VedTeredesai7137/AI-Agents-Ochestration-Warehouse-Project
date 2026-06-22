class SimulationEngine:

    def __init__(
        self,
        robot_manager
    ):
        self.robot_manager = (
            robot_manager
        )

        self.current_step = 0

    def step(self):

        self.current_step += 1

        print(
            f"\nSTEP {self.current_step}\n"
        )

        for robot in (
            self.robot_manager.robots
        ):

            if len(robot.path) > 1:

                next_position = (
                    robot.path[1]
                )

                robot.position.x = (
                    next_position[0]
                )

                robot.position.y = (
                    next_position[1]
                )

                robot.path.pop(0)

                robot.battery -= 1

                print(
                    f"Robot {robot.id}"
                    f" -> "
                    f"({robot.position.x},"
                    f"{robot.position.y})"
                )

    def is_complete(self):

        for robot in (
            self.robot_manager.robots
        ):

            if len(robot.path) > 1:

                return False

        return True
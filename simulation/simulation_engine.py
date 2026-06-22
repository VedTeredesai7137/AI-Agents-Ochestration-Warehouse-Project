from simulation.models import (
    RobotStatus
)


class SimulationEngine:

    def __init__(
        self,
        robot_manager,
        collision_manager,
        task_manager
    ):

        self.robot_manager = (
            robot_manager
        )

        self.collision_manager = (
            collision_manager
        )

        self.task_manager = (
            task_manager
        )

        self.current_step = 0

    def step(self):

        self.current_step += 1

        print(
            f"\nSTEP "
            f"{self.current_step}\n"
        )

        self.collision_manager.reset_step()

        for robot in (
            self.robot_manager.robots
        ):

            if len(robot.path) <= 1:
                continue

            next_x = (
                robot.path[1][0]
            )

            next_y = (
                robot.path[1][1]
            )

            if not (
                self.collision_manager
                .reserve_cell(
                    next_x,
                    next_y
                )
            ):

                robot.status = (
                    RobotStatus.WAITING
                )

                continue

            robot.position.x = (
                next_x
            )

            robot.position.y = (
                next_y
            )

            robot.path.pop(0)

            robot.battery -= 1

            print(
                f"Robot {robot.id}"
                f" -> "
                f"({next_x},{next_y})"
            )

            if len(robot.path) == 1:

                robot.status = (
                    RobotStatus.PICKING
                )

                print(
                    f"Robot "
                    f"{robot.id}"
                    f" reached Task "
                    f"{robot.current_task}"
                )

    def is_complete(self):

        for robot in (
            self.robot_manager.robots
        ):

            if len(robot.path) > 1:
                return False

        return True
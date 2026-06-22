from simulation.models import (
    RobotStatus
)


class SimulationEngine:

    def __init__(
        self,
        robot_manager,
        collision_manager
    ):

        self.robot_manager = (
            robot_manager
        )

        self.collision_manager = (
            collision_manager
        )

        self.current_step = 0

    def step(self):

        self.current_step += 1

        print(
            f"\n{'=' * 40}"
        )

        print(
            f"STEP {self.current_step}"
        )

        print(
            f"{'=' * 40}\n"
        )

        self.collision_manager.reset_step()

        for robot in (
            self.robot_manager.robots
        ):

            if len(robot.path) <= 1:
                continue

            next_position = (
                robot.path[1]
            )

            next_x = next_position[0]
            next_y = next_position[1]

            can_move = (
                self.collision_manager
                .reserve_cell(
                    next_x,
                    next_y
                )
            )

            if not can_move:

                robot.status = (
                    RobotStatus.WAITING
                )

                print(
                    f"Robot {robot.id}"
                    f" WAITING"
                )

                print(
                    f"Target Cell "
                    f"({next_x},{next_y}) "
                    f"already reserved\n"
                )

                continue

            robot.position.x = next_x
            robot.position.y = next_y

            robot.path.pop(0)

            robot.battery -= 1

            robot.status = (
                RobotStatus.MOVING
            )

            print(
                f"Robot {robot.id}"
                f" -> "
                f"({next_x},{next_y})"
            )

        print()

    def is_complete(self):

        for robot in (
            self.robot_manager.robots
        ):

            if len(robot.path) > 1:
                return False

        return True
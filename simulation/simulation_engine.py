from simulation.models import (
    RobotStatus
)


class SimulationEngine:

    def __init__(
        self,
        robot_manager,
        collision_manager,
        task_manager,
        charging_manager,
        pathfinder
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

        self.charging_manager = (
            charging_manager
        )

        self.pathfinder = (
            pathfinder
        )

        self.current_step = 0

    def handle_battery(
        self,
        robot
    ):

        if (
            robot.battery
            > 20
        ):
            return

        if (
            robot.status
            == RobotStatus.CHARGING
        ):
            return

        station = (
            self.charging_manager
            .get_nearest_station(
                robot
            )
        )

        robot.path = (
            self.pathfinder
            .find_path(
                (
                    robot.position.x,
                    robot.position.y
                ),
                station
            )
        )

        robot.status = (
            RobotStatus.CHARGING
        )

        robot.current_task = (
            None
        )

        print(
            f"Robot "
            f"{robot.id}"
            f" heading to charger"
        )

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

            self.handle_battery(
                robot
            )

            if len(robot.path) <= 1:

                if (
                    robot.status
                    ==
                    RobotStatus.CHARGING
                ):

                    robot.battery += 10

                    if (
                        robot.battery
                        >= 100
                    ):

                        robot.battery = 100

                        robot.status = (
                            RobotStatus.IDLE
                        )

                        print(
                            f"Robot "
                            f"{robot.id}"
                            f" fully charged"
                        )

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
                f"Robot "
                f"{robot.id}"
                f" -> "
                f"({next_x},{next_y}) "
                f"Battery="
                f"{robot.battery:.0f}"
            )

            if (
                len(robot.path)
                == 1
            ):

                if (
                    robot.status
                    ==
                    RobotStatus.CHARGING
                ):

                    print(
                        f"Robot "
                        f"{robot.id}"
                        f" arrived at charger"
                    )

                else:

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

            if (
                len(robot.path)
                > 1
            ):
                return False

        return True
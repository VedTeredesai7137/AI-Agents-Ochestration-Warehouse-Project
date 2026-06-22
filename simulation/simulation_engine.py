from simulation.models import RobotStatus


class SimulationEngine:

    def __init__(
        self,
        robot_manager,
        collision_manager,
        task_manager,
        charging_manager,
        pathfinder,
        auction_manager
    ):
        self.robot_manager = robot_manager
        self.collision_manager = collision_manager
        self.task_manager = task_manager
        self.charging_manager = charging_manager
        self.pathfinder = pathfinder
        self.auction_manager = auction_manager
        self.current_step = 0

    def assign_new_tasks(self):

        for task in self.task_manager.get_unassigned_tasks():

            winner = self.auction_manager.run_auction(task)

            if winner is None:
                continue

            robot = self.robot_manager.get_robot(winner)

            path = self.pathfinder.find_path(
                (robot.position.x, robot.position.y),
                (task.pickup_x, task.pickup_y)
            )

            if not path:
                continue

            self.task_manager.assign_task(
                task.id,
                winner
            )

            self.robot_manager.assign_task(
                winner,
                task.id,
                path
            )

            print(
                f"Task {task.id} assigned to Robot {winner}"
            )

    def handle_battery(self, robot):

        if robot.battery > 20:
            return

        if robot.status == RobotStatus.CHARGING:
            return

        if robot.current_task is not None:

            self.task_manager.unassign_task(
                robot.current_task
            )

            print(
                f"Robot {robot.id} released Task "
                f"{robot.current_task}"
            )

        station = self.charging_manager.get_nearest_station(
            robot
        )

        robot.path = self.pathfinder.find_path(
            (robot.position.x, robot.position.y),
            station
        )

        robot.current_task = None
        robot.status = RobotStatus.CHARGING

        print(
            f"Robot {robot.id} going to charge"
        )

    def step(self):

        self.current_step += 1

        print(f"\nSTEP {self.current_step}")

        self.assign_new_tasks()

        self.collision_manager.reset_step()

        for robot in self.robot_manager.robots:

            self.handle_battery(robot)

            if len(robot.path) <= 1:

                if robot.status == RobotStatus.CHARGING:

                    robot.battery += 10

                    if robot.battery >= 100:

                        robot.battery = 100
                        robot.status = RobotStatus.IDLE

                        print(
                            f"Robot {robot.id} fully charged"
                        )

                continue

            next_x, next_y = robot.path[1]

            if not self.collision_manager.reserve_cell(
                next_x,
                next_y
            ):
                continue

            robot.position.x = next_x
            robot.position.y = next_y

            robot.path.pop(0)

            robot.battery -= 1

            print(
                f"Robot {robot.id} -> ({next_x},{next_y}) "
                f"Battery={robot.battery:.0f}"
            )

            if len(robot.path) == 1:

                if robot.status == RobotStatus.CHARGING:

                    print(
                        f"Robot {robot.id} arrived at charger"
                    )

                elif robot.current_task is not None:

                    print(
                        f"Robot {robot.id} completed Task "
                        f"{robot.current_task}"
                    )

                    self.task_manager.complete_task(
                        robot.current_task
                    )

                    robot.current_task = None
                    robot.status = RobotStatus.IDLE

    def is_complete(self):

        unfinished_tasks = [
            task
            for task in self.task_manager.tasks
            if not task.completed
        ]

        active_robots = [
            robot
            for robot in self.robot_manager.robots
            if robot.current_task is not None
        ]

        return (
            len(unfinished_tasks) == 0
            and len(active_robots) == 0
        )
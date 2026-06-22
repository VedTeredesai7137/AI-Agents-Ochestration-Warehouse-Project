class AuctionManager:

    def __init__(
        self,
        robot_manager
    ):

        self.robot_manager = (
            robot_manager
        )

    def calculate_bid(
        self,
        robot,
        task
    ):

        distance = (
            abs(
                robot.position.x
                -
                task.pickup_x
            )
            +
            abs(
                robot.position.y
                -
                task.pickup_y
            )
        )

        battery_penalty = (
            100
            -
            robot.battery
        ) * 0.1

        return (
            distance
            +
            battery_penalty
        )

    def run_auction(
        self,
        task
    ):

        bids = []

        print(
            f"\nTASK {task.id}"
        )

        for robot in (
            self.robot_manager.robots
        ):

            if (
                robot.current_task
                is not None
            ):
                continue

            if (
                robot.battery
                < 30
            ):
                continue

            bid = (
                self.calculate_bid(
                    robot,
                    task
                )
            )

            bids.append(
                (
                    bid,
                    robot.id
                )
            )

            print(
                f"Robot "
                f"{robot.id}"
                f" bid = "
                f"{bid:.2f}"
            )

        if not bids:
            return None

        bids.sort()

        winner_id = (
            bids[0][1]
        )

        print(
            f"WINNER -> "
            f"Robot "
            f"{winner_id}"
        )

        return winner_id
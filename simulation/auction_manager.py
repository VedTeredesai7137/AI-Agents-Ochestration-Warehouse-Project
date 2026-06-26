class AuctionManager:

    def __init__(
        self,
        robot_manager
    ):

        self.robot_manager = (
            robot_manager
        )
        self.latest_logs = []

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

        if not bids:
            return None

        bids.sort()
        
        self.latest_logs.append({
            "task_id": task.id,
            "bids": [{"robot_id": r_id, "bid": b} for b, r_id in bids],
            "winner": bids[0][1]
        })

        return bids[0][1]
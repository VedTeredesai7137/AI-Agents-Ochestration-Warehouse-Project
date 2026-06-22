class ChargingManager:

    def __init__(self):

        self.charging_stations = [
            (0, 0),
            (1, 0),
            (28, 0),
            (29, 0)
        ]

    def get_nearest_station(
        self,
        robot
    ):

        best_station = None

        best_distance = float(
            "inf"
        )

        for station in (
            self.charging_stations
        ):

            distance = (
                abs(
                    robot.position.x
                    - station[0]
                )
                +
                abs(
                    robot.position.y
                    - station[1]
                )
            )

            if (
                distance
                < best_distance
            ):

                best_distance = (
                    distance
                )

                best_station = (
                    station
                )

        return best_station
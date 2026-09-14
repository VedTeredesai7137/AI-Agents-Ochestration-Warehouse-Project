class ChargingManager:
    """Choose real, reachable chargers using the current warehouse grid."""

    def get_charge_path(self, robot, pathfinder):
        warehouse = pathfinder.warehouse
        start = (robot.position.x, robot.position.y)
        stations = [(x, y) for y, row in enumerate(warehouse.grid)
                    for x, cell in enumerate(row) if cell == "C"]
        paths = [pathfinder.find_path(start, station) for station in stations]
        return min((path for path in paths if path), key=len, default=[])

    @staticmethod
    def at_station(robot, warehouse):
        x, y = robot.position.x, robot.position.y
        return (0 <= y < len(warehouse.grid) and
                0 <= x < len(warehouse.grid[y]) and warehouse.grid[y][x] == "C")

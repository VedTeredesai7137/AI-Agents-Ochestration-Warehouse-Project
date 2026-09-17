"""Reachable, energy-feasible charging stops using the existing A* service."""
import heapq
from collections import OrderedDict, deque


class ChargingManager:
    RESERVE = 5
    CHARGE_RATE = 10  # Already fast: ten ticks from empty. Travel was the bottleneck.
    QUEUE_PENALTY = 12

    def __init__(self):
        self._grid_key = None
        self._paths = OrderedDict()
        self.robots = ()
        self._distances = OrderedDict()
        self._station_key = None
        self._stations = []

    def route(self, start, goal, pathfinder):
        warehouse = pathfinder.warehouse
        key = (id(warehouse), warehouse.revision)
        if self._grid_key != key:
            self._paths.clear()
            self._distances.clear()
            self._grid_key = key
        pair = (tuple(start), tuple(goal))
        if pair in self._paths:
            cached = self._paths[pair]
            if not cached or pathfinder._validate_path_integrity(cached):
                self._paths.move_to_end(pair)
                return list(cached)
        path = pathfinder.find_path(*pair)
        self._paths[pair] = tuple(path)
        if len(self._paths) > 8192:
            self._paths.popitem(last=False)
        return path

    def stations(self, pathfinder):
        key = (id(pathfinder.warehouse),pathfinder.warehouse.revision)
        if self._station_key != key:
            self._stations = [(x,y) for y,row in enumerate(pathfinder.warehouse.grid)
                              for x,cell in enumerate(row) if cell == "C"]
            self._station_key = key
        return self._stations

    def distance(self, start, goal, pathfinder):
        # Exact static distance fields for bidding/energy estimates only. Actual
        # routes still use A* with its complete integrity checks. Bounded by goals.
        key = (id(pathfinder.warehouse),pathfinder.warehouse.revision)
        if self._grid_key != key:
            self._paths.clear()
            self._distances.clear()
            self._grid_key = key
        goal = tuple(goal)
        if goal not in self._distances:
            distances = {}
            if pathfinder.warehouse.is_walkable(*goal):
                distances[goal] = 0
                pending = deque([goal])
                while pending:
                    cell = pending.popleft()
                    for neighbor in pathfinder.warehouse.get_neighbors(*cell):
                        if neighbor not in distances:
                            distances[neighbor] = distances[cell]+1
                            pending.append(neighbor)
            self._distances[goal] = distances
            if len(self._distances)>512:
                self._distances.popitem(last=False)
        self._distances.move_to_end(goal)
        return self._distances[goal].get(tuple(start),float("inf"))

    def nearest_distance(self, start, pathfinder):
        return min((self.distance(start, c, pathfinder) for c in self.stations(pathfinder)), default=float("inf"))

    def get_charge_path(self, robot, pathfinder, *, congestion=False, loaded=False):
        start = (robot.position.x, robot.position.y)
        rate = 2 if loaded else 1
        choices = []
        for station in self.stations(pathfinder):
            if congestion and station == start and robot.battery >= 100:
                continue
            path = self.route(start, station, pathfinder)
            if not path:
                continue
            demand = sum(r.id != robot.id and (r.position.x, r.position.y) == station
                         or r.id != robot.id and r.status.value == "CHARGING" and bool(r.path) and tuple(r.path[-1]) == station
                         for r in self.robots) if congestion else 0
            if congestion and ((len(path)-1)*rate > robot.battery or demand):
                continue
            choices.append((len(path)-1 + demand*self.QUEUE_PENALTY, station, path))
        return min(choices, default=(0, None, []))[2]

    def journey(self, start, goal, battery, pathfinder, *, loaded=False, pickup=False, build_route=True):
        """Feasible itinerary through real charging cells, or None.

        Each charging leg must fit the battery. A goal retains enough energy for
        the nearest charger plus reserve; after pickup that return is loaded.
        Dijkstra searches only charger stops (<=8), never warehouse movement cells.
        A* supplies every route. Returns first leg, total estimated cost, arrival energy.
        """
        start, goal = tuple(start), tuple(goal)
        rate = 2 if loaded else 1
        reserve_at_goal = self.nearest_distance(goal, pathfinder)*(2 if pickup else 1) + self.RESERVE
        stations = self.stations(pathfinder)
        heap = [(0.0, start, float(battery), None)]
        if start in stations and battery < 100:
            heap = [((100-battery)/self.CHARGE_RATE, start, 100.0, start)]
        visited = set()
        while heap:
            cost, node, energy, first = heapq.heappop(heap)
            if node in visited:
                continue
            visited.add(node)
            distance = self.distance(node, goal, pathfinder)
            if distance*rate + reserve_at_goal <= energy:
                leg = first or goal
                return (self.route(start, leg, pathfinder) if build_route else leg), cost+distance, energy-distance*rate
            for station in stations:
                if station == node or station in visited:
                    continue
                distance = self.distance(node, station, pathfinder)
                if distance*rate + self.RESERVE <= energy:
                    recharge = (100-(energy-distance*rate))/self.CHARGE_RATE
                    demand = sum(r.status.value == "CHARGING" and bool(r.path) and tuple(r.path[-1]) == station
                                 for r in self.robots)
                    recharge += demand*self.QUEUE_PENALTY
                    heapq.heappush(heap, (cost+distance+recharge, station, 100.0, first or station))
        return None

    def task_offer(self, robot, task, pathfinder):
        start = (robot.position.x, robot.position.y)
        pickup = (task.pickup_x, task.pickup_y)
        delivery = (task.delivery_x, task.delivery_y)
        first = self.journey(start, pickup, robot.battery, pathfinder, pickup=True, build_route=False)
        if first is None:
            return None
        second = self.journey(pickup, delivery, first[2], pathfinder, loaded=True, build_route=False)
        if second is None:
            return None
        # Cost is travel + charging service ticks, with a small measured energy-margin penalty.
        margin = second[2] - self.nearest_distance(delivery, pathfinder) - self.RESERVE
        return first[1] + second[1] + max(0, 20-margin)*0.1

    @staticmethod
    def at_station(robot, warehouse):
        x, y = robot.position.x, robot.position.y
        return (0 <= y < len(warehouse.grid) and
                0 <= x < len(warehouse.grid[y]) and warehouse.grid[y][x] == "C")

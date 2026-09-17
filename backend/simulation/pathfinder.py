import heapq


class AStarPathfinder:

    def __init__(self, warehouse):
        self.warehouse = warehouse

    def heuristic(
        self,
        a,
        b
    ):
        return abs(a[0] - b[0]) + abs(a[1] - b[1])

    def reconstruct_path(
        self,
        came_from,
        current
    ):
        path = [current]

        while current in came_from:
            current = came_from[current]
            path.append(current)

        path.reverse()

        return path

    def _validate_path_integrity(self, path):
        """
        Post-search safety check: verify every cell in the path is walkable
        and each consecutive step is exactly 1 orthogonal move apart.
        Returns the path if valid, empty list if any cell is invalid.
        """
        if not path:
            return []

        for i, (x, y) in enumerate(path):
            if not self.warehouse.is_walkable(x, y):
                print(
                    f"[PATHFINDER ERROR] Path integrity failed: "
                    f"cell ({x},{y}) at index {i} is NOT walkable. "
                    f"Path rejected. Full path: {path}"
                )
                return []

        # Verify orthogonal adjacency between consecutive cells
        for i in range(1, len(path)):
            px, py = path[i - 1]
            cx, cy = path[i]
            dx = abs(cx - px)
            dy = abs(cy - py)
            if (dx + dy) != 1:
                print(
                    f"[PATHFINDER ERROR] Path integrity failed: "
                    f"non-adjacent step from ({px},{py}) to ({cx},{cy}) "
                    f"at index {i}. Distance={dx+dy}. Path rejected."
                )
                return []

        return path

    def find_path(
        self,
        start,
        goal,
        blocked_cells=None
    ):
        blocked_cells = set(blocked_cells or ()) - {start}
        if goal in blocked_cells:
            return []
        # Pre-validate start and goal are walkable
        if not self.warehouse.is_walkable(start[0], start[1]):
            print(
                f"[PATHFINDER ERROR] Start cell ({start[0]},{start[1]}) "
                f"is NOT walkable. Returning empty path."
            )
            return []

        if not self.warehouse.is_walkable(goal[0], goal[1]):
            print(
                f"[PATHFINDER ERROR] Goal cell ({goal[0]},{goal[1]}) "
                f"is NOT walkable. Returning empty path."
            )
            return []

        # Trivial case: start == goal
        if start == goal:
            return [start]

        open_set = []

        heapq.heappush(
            open_set,
            (0, start)
        )

        came_from = {}

        g_score = {
            start: 0
        }

        f_score = {
            start: self.heuristic(
                start,
                goal
            )
        }

        # Closed set prevents re-expansion of already-processed nodes
        closed_set = set()

        while open_set:

            current = heapq.heappop(
                open_set
            )[1]

            # Skip if already processed (stale heap entry)
            if current in closed_set:
                continue

            if current == goal:
                raw_path = self.reconstruct_path(
                    came_from,
                    current
                )
                return self._validate_path_integrity(raw_path)

            closed_set.add(current)

            neighbors = self.warehouse.get_neighbors(
                current[0],
                current[1]
            )

            for neighbor in neighbors:

                if neighbor in closed_set or neighbor in blocked_cells:
                    continue

                tentative_g_score = (
                    g_score[current] + 1
                )

                if (
                    neighbor not in g_score
                    or
                    tentative_g_score < g_score[neighbor]
                ):

                    came_from[neighbor] = current

                    g_score[neighbor] = (
                        tentative_g_score
                    )

                    f_score[neighbor] = (
                        tentative_g_score
                        +
                        self.heuristic(
                            neighbor,
                            goal
                        )
                    )

                    heapq.heappush(
                        open_set,
                        (
                            f_score[neighbor],
                            neighbor
                        )
                    )

        print(
            f"[PATHFINDER WARNING] No path found from "
            f"{start} to {goal}."
        )
        return []
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

    def find_path(
        self,
        start,
        goal
    ):

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

        while open_set:

            current = heapq.heappop(
                open_set
            )[1]

            if current == goal:

                return self.reconstruct_path(
                    came_from,
                    current
                )

            neighbors = self.warehouse.get_neighbors(
                current[0],
                current[1]
            )

            for neighbor in neighbors:

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

        return []
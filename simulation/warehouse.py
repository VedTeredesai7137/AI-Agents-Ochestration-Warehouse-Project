# warehouse.py

class Warehouse:

    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.grid = []

    def create_empty_grid(self):
        self.grid = [
            ["." for _ in range(self.width)]
            for _ in range(self.height)
        ]

    def add_shelves(self):
        for row in range(2, self.height - 2, 3):
            for col in range(2, self.width - 2):
                self.grid[row][col] = "S"

    def add_charging_stations(self):
        self.grid[0][0] = "C"
        self.grid[0][1] = "C"
        self.grid[0][self.width - 1] = "C"
        self.grid[0][self.width - 2] = "C"

    def add_robot_spawn_area(self):
        spawn_row = self.height - 2
        for col in range(1, 6):
            self.grid[spawn_row][col] = "R"

    def generate(self):
        self.create_empty_grid()
        self.add_shelves()
        self.add_charging_stations()
        self.add_robot_spawn_area()

    def render(self):
        for row in self.grid:
            print(" ".join(row))

    def is_walkable(self, x, y):

        if x < 0:
            return False

        if y < 0:
            return False

        if x >= self.width:
            return False

        if y >= self.height:
            return False

        return self.grid[y][x] != "S"

    def get_neighbors(self, x, y):

        directions = [
            (0, 1),
            (0, -1),
            (1, 0),
            (-1, 0)
        ]

        neighbors = []

        for dx, dy in directions:

            nx = x + dx
            ny = y + dy

            if self.is_walkable(nx, ny):
                neighbors.append((nx, ny))

        return neighbors


    def get_spawn_locations(self):

        locations = []

        for y in range(self.height):

            for x in range(self.width):

                if self.grid[y][x] == "R":

                    locations.append(
                        (x, y)
                    )

        return locations

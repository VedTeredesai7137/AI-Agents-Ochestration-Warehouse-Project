class CollisionManager:

    def __init__(self):
        self.reserved_cells = {}

    def reset_step(self):
        self.reserved_cells.clear()

    def reserve_cell(
        self,
        x,
        y,
        robot_id
    ):

        cell = (x, y)

        if cell in self.reserved_cells:
            return False, self.reserved_cells[cell]

        self.reserved_cells[cell] = robot_id

        return True, None
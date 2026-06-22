class CollisionManager:

    def __init__(self):
        self.reserved_cells = set()

    def reset_step(self):
        self.reserved_cells.clear()

    def reserve_cell(
        self,
        x,
        y
    ):

        cell = (x, y)

        if cell in self.reserved_cells:
            return False

        self.reserved_cells.add(
            cell
        )

        return True
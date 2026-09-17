class CollisionManager:
    """Conservative step-local reservations including robots that stay stationary.

    A vacated cell remains reserved until the next tick. This prevents edge swaps;
    it can reduce throughput, but never permits moving through another robot.
    """
    def __init__(self):
        self.reserved_cells = {}
        self.occupied_cells = {}
        self.blocked_attempts = 0

    def reset_step(self, robots=()):
        self.reserved_cells.clear()
        self.occupied_cells = {(r.position.x, r.position.y): r.id for r in robots}

    def reserve_cell(self, x, y, robot_id):
        cell = (x, y)
        owner = self.occupied_cells.get(cell, self.reserved_cells.get(cell))
        if owner is not None and owner != robot_id:
            self.blocked_attempts += 1
            return False, owner
        self.reserved_cells[cell] = robot_id
        return True, None

    def moved(self, robot_id, old, new):
        self.occupied_cells.pop(old, None)
        self.occupied_cells[new] = robot_id
        self.reserved_cells[old] = robot_id

# Warehouse Swarm Project

## 1. Executive Summary

**Warehouse Swarm Project** is a learning project that simulates a simple swarm robotics warehouse environment in Python. It demonstrates how multiple robots can operate concurrently in a structured warehouse grid, bid for pickup tasks, navigate with A* pathfinding, avoid instant collisions, manage battery and charging behavior, and respond to dynamic task injection during runtime.

This repository exists as a technical exercise and exploratory prototype for swarm robotics coordination. It is not a production-grade warehouse management system, but it is intentionally designed to illustrate fundamental concepts such as:

- Warehouse environment modeling
- Robot state and task lifecycle management
- A* path planning on a grid
- Auction-based task allocation
- Reservation-style collision avoidance
- Battery-aware behavior and charging decisions
- Runtime task injection and reassignment

The current completion state of the project is a working simulation executed from `simulation/main.py` that:

- generates a warehouse grid,
- spawns five robots at predefined spawn points,
- creates an initial set of pickup tasks,
- assigns tasks through auctions,
- moves robots step-by-step,
- enforces simple collision checks,
- manages battery levels and charging trips,
- injects new tasks dynamically at steps 10 and 20,
- terminates when all tasks are complete and no robots are active.

This README documents the actual implemented behavior in the existing source code and serves as the authoritative technical specification for future AI agents.

## 2. System Architecture

The system is structured as a set of cooperating managers with a central simulation engine. The current architecture is intentionally modular, with separate responsibilities for environment modeling, robot control, task management, auctions, pathfinding, collision control, charging decisions, and runtime sequencing.

### Architecture Overview

The current top-level data and control flow is:

```text
Warehouse
  ├─> RobotManager
  ├─> TaskManager
  ├─> AuctionManager
  ├─> Pathfinder
  ├─> CollisionManager
  ├─> ChargingManager
  └─> SimulationEngine
```

A more detailed ASCII architecture diagram:

```text
+-----------------+      +----------------+      +-----------------+
|   Warehouse     |      |  RobotManager  |      |  TaskManager    |
|  (warehouse.py) |      | (robot_manager)|      | (task_manager)  |
+-----------------+      +----------------+      +-----------------+
          |                       |                       |
          | grid, neighbors       | robots list            | tasks list
          | walkability           | spawn robots          | create/assign
          v                       v                       v
+--------------------+   +----------------+   +-------------------------+
|  AStarPathfinder   |<--| AuctionManager |-->| SimulationEngine        |
|  (pathfinder.py)   |   | (auction_mgr)  |   | (simulation_engine.py)  |
+--------------------+   +----------------+   +-------------------------+
          ^                       ^                       |
          | path computation      | bid calculation         |
          | on warehouse grid     | using robot state       v
          |                       |                       +------------------+
          |                       |                       | CollisionManager |
          |                       |                       | (collision_mgr)  |
          |                       |                       +------------------+
          |                       |                              |
          |                       |                              | reserved cells
          |                       |                              v
          |                       |                       +------------------+
          |                       |                       | ChargingManager  |
          |                       |                       | (charging_mgr)   |
          |                       |                       +------------------+
```

### Component Responsibilities and Data Flow

- **Warehouse** provides the grid layout, walkability rules, shelf placement, charging stations, spawn locations, and neighbor discovery.
- **RobotManager** spawns robots on warehouse-defined spawn cells and stores the robot state list used by the simulation.
- **TaskManager** stores tasks, tracks assignment, and flags completion.
- **AuctionManager** computes bids for unassigned tasks and selects a winning idle robot.
- **AStarPathfinder** computes a collision-free path on the warehouse grid from a robot's current position to a target cell.
- **CollisionManager** provides per-step reservation of target cells to prevent two robots from moving into the same cell in the same simulation step.
- **ChargingManager** selects the nearest charging station for a robot that must recharge.
- **SimulationEngine** orchestrates the simulation step sequence, including task assignment, battery handling, movement, task completion, and charging.

The primary runtime loop is in `simulation/main.py`, which constructs all components and executes repeated `SimulationEngine.step()` calls until completion.

## 3. Repository Structure

This repository contains a single Python package: `simulation`. It is intentionally small but complete enough to capture the current implementation.

### `README.md`

- Purpose: authoritative technical specification for the entire repository.
- Responsibilities: document system architecture, components, current behavior, bugs, and debugging guidance.
- Key Classes/Functions: none; documentation only.
- Dependencies: none.
- Used By: users, future AI agents, maintainers.
- Future Expansion: expand with diagrams, runtime examples, or API design updates.

### `simulation/__init__.py`

- Purpose: package marker for the `simulation` module.
- Responsibilities: allow `from simulation import ...` imports.
- Key Content: empty file.
- Dependencies: none.
- Used By: `simulation/main.py` via package import.
- Future Expansion: export package-level API if needed.

### `simulation/constants.py`

- Purpose: define shared warehouse and robot constants.
- Responsibilities: store grid dimensions, tile symbols, maximum battery.
- Key Constants:
  - `WAREHOUSE_WIDTH = 30`
  - `WAREHOUSE_HEIGHT = 20`
  - `MAX_ROBOTS = 50`
  - `SHELF = "S"`
  - `AISLE = "."`
  - `CHARGER = "C"`
  - `ROBOT_SPAWN = "R"`
  - `MAX_BATTERY = 100`
- Dependencies: none.
- Used By: currently no file imports it; constants are duplicated implicitly in implementation.
- Future Expansion: integrate into warehouse generation, pathfinding, charging, and robot management for consistent configuration.

### `simulation/models.py`

- Purpose: define domain models for robot and position data.
- Responsibilities: model robot state, battery, position, current task, and status.
- Key Classes:
  - `Position(BaseModel)`
    - x: int
    - y: int
  - `RobotStatus(str, Enum)`
    - IDLE, MOVING, WAITING, PICKING, DELIVERING, CHARGING, NEEDS_CHARGE
  - `Robot(BaseModel)`
    - id: int
    - battery: float
    - position: Position
    - status: RobotStatus
    - current_task: int | None
    - path: list
- Key Functions:
  - `Robot.__str__()`: formatted debug string for robot state.
- Dependencies: `pydantic.BaseModel`, Python `enum.Enum`.
- Used By: `simulation/robot_manager.py`, `simulation/simulation_engine.py`, `simulation/auction_manager.py`, `simulation/charging_manager.py`.
- Future Expansion: add payload, capacity, destination, or richer state transitions.

### `simulation/warehouse.py`

- Purpose: build and query the warehouse grid environment.
- Responsibilities: generate the warehouse map, spawn points, charging stations, shelf layout, walkability checks, and neighbor discovery.
- Key Class:
  - `Warehouse`
    - attributes: `width`, `height`, `grid`
    - methods:
      - `create_empty_grid()`
      - `add_shelves()`
      - `add_charging_stations()`
      - `add_robot_spawn_area()`
      - `generate()`
      - `render()`
      - `is_walkable(x, y)`
      - `get_neighbors(x, y)`
      - `get_spawn_locations()`
- Dependencies: none.
- Used By: `simulation/main.py`, `simulation/pathfinder.py`, `simulation/robot_manager.py`.
- Future Expansion: support obstacles, shelves with storage locations, multi-layer grids, or dynamic warehouse reconfiguration.

### `simulation/pathfinder.py`

- Purpose: compute shortest paths on the warehouse grid using A*.
- Responsibilities: perform heuristic search, manage open and closed sets, reconstruct found paths.
- Key Class:
  - `AStarPathfinder`
    - __init__(warehouse)
    - `heuristic(a, b)`
    - `reconstruct_path(came_from, current)`
    - `find_path(start, goal)`
- Dependencies: Python `heapq`.
- Used By: `simulation/simulation_engine.py`, `simulation/charging_manager.py` indirectly through `SimulationEngine.handle_battery()`.
- Future Expansion: add tie-breaking, path smoothing, multi-agent path planning, or obstacle-aware costs.

### `simulation/task_manager.py`

- Purpose: maintain the task list and assignment state.
- Responsibilities: create new tasks, query tasks, assign/unassign, and mark completion.
- Key Class:
  - `Task`
    - id, pickup_x, pickup_y, completed, assigned_robot
  - `TaskManager`
    - methods:
      - `create_task(pickup_x, pickup_y)`
      - `get_task(task_id)`
      - `get_unassigned_tasks()`
      - `assign_task(task_id, robot_id)`
      - `unassign_task(task_id)`
      - `complete_task(task_id)`
- Dependencies: Python `dataclasses.dataclass`
- Used By: `simulation/main.py`, `simulation/simulation_engine.py`.
- Future Expansion: support task priorities, deadlines, delivery locations, and lifecycle timestamps.

### `simulation/robot_manager.py`

- Purpose: create and manage robot states.
- Responsibilities: instantiate robots, spawn from warehouse spawn points, retrieve robots, display state, and assign tasks.
- Key Class:
  - `RobotManager`
    - attributes: `robots`
    - methods:
      - `create_robot(robot_id, x, y)`
      - `spawn_from_warehouse(warehouse)`
      - `get_robot(robot_id)`
      - `display_robots()`
      - `assign_task(robot_id, task_id, path)`
- Dependencies: `simulation.models`.
- Used By: `simulation/main.py`, `simulation/auction_manager.py`, `simulation/simulation_engine.py`.
- Future Expansion: support robot removal, recharging statistics, heterogeneous robot models, and robot-to-robot communication.

### `simulation/auction_manager.py`

- Purpose: allocate tasks to robots via an auction mechanism.
- Responsibilities: compute bid scores, filter eligible robots, choose the lowest-cost bid.
- Key Class:
  - `AuctionManager`
    - attributes: `robot_manager`
    - methods:
      - `calculate_bid(robot, task)`
      - `run_auction(task)`
- Dependencies: none beyond `simulation.robot_manager` usage.
- Used By: `simulation/simulation_engine.py`.
- Future Expansion: include estimated path cost, workload balancing, or explicit reserve prices.

### `simulation/collision_manager.py`

- Purpose: prevent robots from moving into the same cell in the same step.
- Responsibilities: reserve cells for the current step and reject duplicate reservations.
- Key Class:
  - `CollisionManager`
    - `reserved_cells`
    - methods:
      - `reset_step()`
      - `reserve_cell(x, y)`
- Dependencies: none.
- Used By: `simulation/simulation_engine.py`.
- Future Expansion: maintain full reservation tables, support swapping, or detect deadlocks.

### `simulation/charging_manager.py`

- Purpose: select the nearest charging station for low-battery robots.
- Responsibilities: define charging station coordinates and compute nearest station distance.
- Key Class:
  - `ChargingManager`
    - `charging_stations`
    - method: `get_nearest_station(robot)`
- Dependencies: none.
- Used By: `simulation/simulation_engine.py`.
- Future Expansion: support charging station capacity, dynamic station placement, and reservation of charging cells.

### `simulation/simulation_engine.py`

- Purpose: coordinate the simulation step and govern robot behavior.
- Responsibilities: assign tasks, manage battery transitions, move robots, complete tasks, and determine simulation completion.
- Key Class:
  - `SimulationEngine`
    - attributes: `robot_manager`, `collision_manager`, `task_manager`, `charging_manager`, `pathfinder`, `auction_manager`, `current_step`
    - methods:
      - `assign_new_tasks()`
      - `handle_battery(robot)`
      - `step()`
      - `is_complete()`
- Dependencies: `simulation.models.RobotStatus`.
- Used By: `simulation/main.py`.
- Future Expansion: support simulation logging, multiple timesteps, event queues, and more advanced execution strategies.

### `simulation/main.py`

- Purpose: launch the simulation end-to-end.
- Responsibilities: construct objects, generate the warehouse, spawn robots, create tasks, run the simulation loop, and print progress.
- Key Functions:
  - `main()`
- Dependencies: all other simulation modules.
- Used By: direct execution as `python simulation/main.py`.
- Future Expansion: add CLI options, configuration files, or batch scenarios.

## 4. Warehouse Model

The warehouse is represented as a 2D grid with fixed width and height. `simulation/warehouse.py` constructs the grid and defines how robots can navigate it.

### Grid representation

- The grid is a list of rows: `self.grid[y][x]`.
- `width=30`, `height=20` by current instantiation in `simulation/main.py`.
- Each cell contains a character string representing one of:
  - `"S"` for shelves,
  - `"."` for open aisles,
  - `"C"` for charging stations,
  - `"R"` for robot spawn cells.

### Symbols

- `S` — shelf cell, treated as obstacle and not walkable.
- `R` — robot spawn position, treated as an open cell for pathing and initial robot placement.
- `C` — charging station, treated as an open cell for robot movement.
- `.` — free aisle cell.

### Warehouse generation rules

The warehouse generation procedure is:

1. `create_empty_grid()` fills the entire grid with `.`.
2. `add_shelves()` places shelf cells on fixed rows:
   - for `row` in `range(2, height - 2, 3)`, every third row starting at row 2,
   - for `col` in `range(2, width - 2)`, all columns from 2 through width-3.
3. `add_charging_stations()` places four chargers at fixed positions:
   - `(0, 0)`, `(1, 0)`, `(28, 0)`, `(29, 0)`.
4. `add_robot_spawn_area()` marks the row `height - 2` at columns `1` through `5` as spawn cells.

This means shelves form horizontal bands at rows 2, 5, 8, 11, 14, and 17, with open space at the leftmost two columns and rightmost two columns.

### Shelf placement logic

Shelves are placed in a repeated pattern of 3-row vertical pitch, leaving aisle rows between them. A shelf row covers columns 2 through `width-3`.

Because shelves use a fixed row pattern, the warehouse has broad walkable corridors in the first two columns, the last two columns, and any row not occupied by a shelf.

### Spawn location logic

Robot spawn locations are hard-coded in `add_robot_spawn_area()`:

- spawn row = `height - 2` = 18,
- spawn columns = 1..5,
- spawn cells: `(1, 18)`, `(2, 18)`, `(3, 18)`, `(4, 18)`, `(5, 18)`.

Robots are created at these exact coordinates by `RobotManager.spawn_from_warehouse()`.

### Charging station logic

Charging stations are placed as the first two and last two cells in the top row:

- `(0, 0)`, `(1, 0)`, `(28, 0)`, `(29, 0)`.

The charging station list in `ChargingManager` mirrors these coordinates.

### Walkability rules

The warehouse walkability rules are implemented by `Warehouse.is_walkable(x, y)`: a cell is walkable if and only if it is inside the warehouse bounds and the grid cell is not `S`.

This means that `R`, `C`, and `.` are all treated as walkable.

### Neighbor discovery

Neighbor discovery is performed by `Warehouse.get_neighbors(x, y)`. It explores four cardinal directions:

- `(0, 1)` south,
- `(0, -1)` north,
- `(1, 0)` east,
- `(-1, 0)` west.

Each neighbor is included only if `is_walkable(nx, ny)` returns `True`.

### Graph interpretation

The warehouse grid is implicitly interpreted as a grid graph where each walkable cell is a node and edges exist between orthogonally adjacent walkable cells.

This produces a graph with uniform edge cost (1 per move) and no diagonals.

### Why A* depends on this system

`AStarPathfinder.find_path()` calls `warehouse.get_neighbors()` to expand the search graph. The pathfinder uses the warehouse grid to avoid `S` cells and to constrain search to valid locations.

Without the warehouse's walkability and neighbor definitions, the pathfinder could not compute valid paths or avoid shelves.

## 5. Robot System

Robots are modeled with a lightweight state machine and path storage for future movement.

### Robot model details

The robot model is defined in `simulation/models.py`:

- `id` — unique integer identifier.
- `battery` — float battery percentage.
- `position` — `Position(x, y)` representing current coordinates.
- `status` — `RobotStatus` enum.
- `current_task` — integer task ID or `None`.
- `path` — list of coordinates representing the planned path.

### Robot statuses

The `RobotStatus` enum defines the following values:

- `IDLE`
- `MOVING`
- `WAITING`
- `PICKING`
- `DELIVERING`
- `CHARGING`
- `NEEDS_CHARGE`

In practice, the simulation uses only:

- `IDLE`
- `MOVING`
- `CHARGING`

States such as `WAITING`, `PICKING`, `DELIVERING`, and `NEEDS_CHARGE` are defined but not currently used by any engine logic.

### Robot lifecycle

- Robots start in `IDLE` after spawning at warehouse spawn cells.
- When assigned a task, robots transition to `MOVING` and store a path to the pickup cell.
- When battery is low, robots transition to `CHARGING`, release any assigned task, and store a path to the nearest charger.
- When a robot arrives at a charger and its battery reaches `100`, it transitions back to `IDLE`.

### Path storage

Each robot stores the planned path in `robot.path`. The path is a list of coordinate tuples, including the robot's current position as the first element and the goal position as the last element.

Example path form:

```python
[(3, 18), (3, 17), (3, 16), ..., (10, 1)]
```

The simulation executes movement by consuming the first element and moving to `path[1]`.

### State transition diagram

Current implemented transitions:

```text
IDLE -> MOVING -> IDLE
   ^             |
   |             v
   +--- CHARGING <-
```

More explicitly:

- `IDLE` to `MOVING`: when a task is assigned.
- `MOVING` to `IDLE`: when a task is completed and the path is exhausted.
- `IDLE` to `CHARGING`: when `battery <= 20` and the robot is not already charging.
- `CHARGING` to `IDLE`: when battery reaches 100.

### Example state flows

Example task execution flow:

1. `IDLE` robot has no task.
2. Auction assigns a task.
3. Robot enters `MOVING` with path to pickup.
4. Robot moves step-by-step.
5. When the path length is reduced to 1 after movement, the task is completed.
6. Robot sets `current_task = None` and `status = IDLE`.

Example charging flow:

1. Robot battery drops to 20 or lower.
2. `handle_battery()` releases task if present.
3. Robot finds nearest charger and sets `status = CHARGING`.
4. Robot moves toward charger.
5. Once at charger, battery increments by 10 each simulation step.
6. When battery >= 100, robot becomes `IDLE`.

## 6. Pathfinding System

The current pathfinding system is a standard A* implementation executed by `simulation/pathfinder.py`.

### A* implementation details

`AStarPathfinder.find_path(start, goal)` performs the following work:

- Uses a binary heap priority queue `open_set` with entries `(f_score, node)`.
- Initializes `g_score[start] = 0`.
- Initializes `f_score[start] = heuristic(start, goal)`.
- Repeatedly pops the lowest `f_score` node from `open_set`.
- If the popped node equals the goal, reconstructs the path and returns it.
- Otherwise, expands all valid neighbors returned by `warehouse.get_neighbors()`.
- Tentatively computes `tentative_g_score = g_score[current] + 1`
- If the neighbor is not in `g_score`, or if the tentative score is lower, updates `came_from`, `g_score`, `f_score`, and pushes the neighbor onto `open_set`.
- If no path is found, returns `[]`.

### Open set and closed set behavior

- `open_set` is stored as a heap of `(f_score, node)` tuples.
- There is no explicit closed set object. Instead, the algorithm uses the `g_score` map to avoid expanding higher-cost paths to the same node.
- Duplicate nodes with different `f_score` may appear in `open_set`.

### Heuristic

The heuristic is the Manhattan distance between points:

```python
abs(a[0] - b[0]) + abs(a[1] - b[1])
```

Because movement is restricted to cardinal directions on a grid, Manhattan distance is admissible and consistent.

### Neighbor expansion

Neighbors are generated by the warehouse's `get_neighbors()` method, which yields walkable adjacent cells.

If a neighbor is walkable and the tentative `g_score` is better than any previously known cost, the algorithm records the edge and queues the neighbor.

### Path reconstruction

When the goal is reached, `reconstruct_path(came_from, current)` builds the path by following predecessor links from goal to start and then reversing the list.

The reconstructed path includes both the start node and the goal node.

### Complexity

- Time complexity: worst-case `O(n log n)` where `n` is the number of nodes explored, due to the heap operations.
- Space complexity: `O(n)` for `g_score`, `f_score`, and `came_from` maps.

### Known limitations

- No explicit closed set increases reliance on `g_score` for pruning.
- The pathfinder does not detect or prune repeated heap entries.
- Edge costs are uniform; it does not support weighted or directional costs.
- It does not take robot path reservations into account. It assumes static obstacles only.
- It has no safeguards against impossible goals beyond returning `[]`.

### How paths are returned

Paths are returned as a Python list of coordinate tuples. Example output:

```python
[(3, 18), (3, 17), (3, 16), (4, 16), (5, 16), (6, 16), (6, 15), (6, 14), (7, 14), (8, 13), (9, 12), (10, 11), (10, 10), (10, 9), (10, 8), (10, 7), (10, 6), (10, 5), (10, 4), (10, 3), (10, 2), (10, 1)]
```

The first element is the starting position, and the final element is the target cell.

### Sample path example

If a robot begins at `(1, 18)` and the task pickup destination is `(10, 1)`, the A* path may navigate northward and eastward through aisle spaces while avoiding shelf rows. The exact path depends on the layout but will always follow cardinal moves.

## 7. Task System

The task system is intentionally minimal and focuses on pickup assignments.

### Task model

A `Task` has the following fields in `simulation/task_manager.py`:

- `id`: unique integer identifier.
- `pickup_x`: x coordinate of the pickup location.
- `pickup_y`: y coordinate of the pickup location.
- `completed`: boolean flag.
- `assigned_robot`: robot ID or `None`.

### Task lifecycle

1. **Creation**: `TaskManager.create_task(pickup_x, pickup_y)` creates a new task with `completed=False` and `assigned_robot=None`.
2. **Assignment**: `TaskManager.assign_task(task_id, robot_id)` sets the task's assigned robot.
3. **Completion**: `TaskManager.complete_task(task_id)` marks the task as complete.
4. **Unassignment**: `TaskManager.unassign_task(task_id)` clears the assigned robot for tasks whose robot is redirected to charge.

### Task creation

Initial tasks are created in `simulation/main.py`:

- `Task 1` at `(10, 1)`
- `Task 2` at `(15, 4)`
- `Task 3` at `(20, 7)`
- `Task 4` at `(25, 10)`
- `Task 5` at `(27, 13)`

Dynamic tasks are added during runtime at step 10 and step 20.

### Task assignment

Unassigned tasks are retrieved by `TaskManager.get_unassigned_tasks()`, which filters tasks where `assigned_robot is None` and `completed is False`.

`SimulationEngine.assign_new_tasks()` iterates over these tasks and uses `AuctionManager.run_auction(task)` to find an eligible robot.

When a winner is selected, the simulation assigns the task to the robot and sets its path to the pickup coordinates.

### Task completion

A task is marked complete when a robot reaches the final cell of its path and `robot.current_task` is not `None`.

The engine prints a completion message and sets the robot's status to `IDLE`.

### Task reassignment

If a robot with an assigned task drops below the battery threshold (`<= 20`), `SimulationEngine.handle_battery()` unassigns the task and prints a release message. That task becomes available again for future auctions.

### Dynamic insertion

Dynamic task injection occurs in `simulation/main.py`:

- At `simulation.current_step == 10`, a new task is created at `(5, 6)`.
- At `simulation.current_step == 20`, a new task is created at `(18, 15)`.

These tasks are inserted during run-time and enter the auction system immediately in the next simulation step.

### Task states

The system tracks the following effective task states:

- `UNASSIGNED`: `assigned_robot is None` and `completed is False`.
- `ASSIGNED`: `assigned_robot` set to a robot ID.
- `COMPLETED`: `completed is True`.

There is no explicit state enum, but the flags and fields produce this state model.

## 8. Auction Allocation System

The auction system selects the best robot for each unassigned task.

### Bid formula

`AuctionManager.calculate_bid(robot, task)` computes a bid as:

```text
bid = distance + battery_penalty
```

Where:

- `distance = abs(robot.position.x - task.pickup_x) + abs(robot.position.y - task.pickup_y)`
- `battery_penalty = (100 - robot.battery) * 0.1`

### Distance cost

The distance cost is Manhattan distance between the robot's current position and the task pickup location.

This is a rough estimate of travel cost and corresponds to a single-step-per-cell movement cost.

### Battery penalty

A battery penalty is applied as 10% of the missing battery percentage.

For example:

- Robot battery `100` => penalty `0.0`
- Robot battery `50` => penalty `5.0`
- Robot battery `20` => penalty `8.0`

This encourages robots with higher remaining battery to win auctions.

### Robot filtering

`run_auction()` filters robots using the following criteria:

- `robot.current_task is None`: the robot must not already have an assigned task.
- `robot.battery >= 30`: the robot must have at least 30 battery percent.

Robots with current tasks or low battery are excluded from bidding.

### Winner selection

The auction builds a list of `(bid, robot.id)` tuples and sorts them.

The winning robot is the one with the smallest bid.

### Tie handling

When bids are equal, Python tuple sort preserves the robot ID comparison as a tiebreaker because the entries are `(bid, robot.id)`.

This means the lower-numbered robot wins ties on equal bid values.

### Current assumptions

- All tasks require only one pickup location.
- All robots are homogeneous and can execute any task.
- The auction is run independently for each task, not as a multi-task combinatorial auction.
- The bid formula uses only current position and battery.
- Robots do not consider their existing path when bidding.

### Limitations

- No consideration of task deadlines or priorities.
- No explicit handling of charging robots or `CHARGING` status within the auction filter.
- No global optimization across all tasks.
- No penalty for task reassignment churn.

### Exact math example

Robot A at `(1, 18)` with battery `100`, Task at `(10, 1)`:

- distance = `|1-10| + |18-1| = 9 + 17 = 26`
- battery_penalty = `(100 - 100) * 0.1 = 0`
- bid = `26`

Robot B at `(5, 18)` with battery `60`, same task:

- distance = `|5-10| + |18-1| = 5 + 17 = 22`
- battery_penalty = `40 * 0.1 = 4`
- bid = `26`

Tied bids choose the lower robot ID.

## 9. Collision Avoidance System

The collision avoidance system is a reservation mechanism that prevents two robots from entering the same cell during the same simulation step.

### Reservation-based collision avoidance

`CollisionManager` maintains `reserved_cells`, a set of coordinate tuples reserved for the current step.

### Per-step reservation reset

At the start of each simulation step, `SimulationEngine.step()` calls `collision_manager.reset_step()`, clearing the reserved cells set.

This means reservation is only valid for a single step and does not persist across multiple steps.

### Cell locking

When a robot wants to move, the engine checks the next cell:

```python
if not collision_manager.reserve_cell(next_x, next_y):
    continue
```

If the cell is already reserved, the robot does not move this step.

### Conflict resolution

- If two robots attempt to move into the same next cell, the first to reserve it in iteration order succeeds.
- The other robot remains in place for that step.

No further conflict resolution is applied.

### Current limitations

- The reservation system is step-local only.
- There is no path-level planning to avoid future conflicts.
- Swapping positions between robots is not explicitly handled.
- There is no deadlock detection or avoidance.
- Because the simulation iterates robots in the same order each step, later robots are biased to yield.

### Example

Robot 1 and Robot 2 both have next step `(10, 5)`. Provided Robot 1 is iterated first, it reserves `(10, 5)` successfully. Robot 2 fails, stays in place, and retries on the next step.

## 10. Battery and Charging System

Battery management is a core part of the current simulation behavior.

### Battery drain

Every time a robot moves one step along its path, its battery is decremented by `1`.

Battery drain occurs only during movement. Idle robots do not drain battery.

### Charging threshold

A robot enters charging behavior when its battery is `<= 20` and it is not already `CHARGING`.

### Charging station selection

`ChargingManager.get_nearest_station(robot)` selects the charger with the smallest Manhattan distance from the robot's current position. It uses the same Manhattan distance calculation as the auction system.

### Charging path generation

When a robot must charge, `handle_battery()`:

1. Unassigns any current task.
2. Finds nearest charger.
3. Computes a path from current position to charger using A*.
4. Sets `robot.path` to this charger path.
5. Sets `robot.current_task = None`.
6. Sets `robot.status = RobotStatus.CHARGING`.

### Charging completion

During each simulation step, if the robot is on a path of length `<= 1` and has status `CHARGING`, the engine increments `robot.battery` by `10`.

When `robot.battery >= 100`, it clamps battery to `100` and transitions the robot back to `IDLE`.

### Task release process

If a robot with `current_task` assigned drops below the threshold, `handle_battery()` calls `task_manager.unassign_task(robot.current_task)` before sending the robot to charge.

This makes the previously assigned task available again.

### Task reassignment process

After a task is unassigned, it can be reassigned during the next `assign_new_tasks()` call if there is an available eligible robot.

The robot that was sent to charge is no longer eligible to bid until its battery recovers above 30 and it is no longer on a charging path, depending on status and battery.

### Complete state flow

```text
battery > 20 and current_task assigned -> continue MOVING
battery <= 20 and not CHARGING -> release task, compute charger path, CHARGING
CHARGING with path length <= 1 -> battery += 10
battery >= 100 -> battery = 100, status = IDLE
```

Note: The engine does not currently charge robots while they still have a movement path to a task unless they have reached the charger cell.

## 11. Simulation Engine

`SimulationEngine` in `simulation/simulation_engine.py` is the orchestrator of the runtime behavior.

### Execution order of a simulation step

Each call to `SimulationEngine.step()` executes the following sequence:

1. Increment `self.current_step`.
2. Print the current step.
3. Call `assign_new_tasks()` to assign unassigned tasks to eligible robots.
4. Reset the collision reservations for the new step.
5. Loop through every robot in `robot_manager.robots`.
   a. Call `handle_battery(robot)`.
   b. If the robot's path length is `<= 1`, handle charging bookkeeping and skip movement.
   c. Extract the next cell from `robot.path`: `robot.path[1]`.
   d. Attempt to reserve the cell via `collision_manager.reserve_cell(next_x, next_y)`.
   e. If the reservation fails, the robot does not move.
   f. If the reservation succeeds, update the robot's position and pop the first path element.
   g. Decrement `robot.battery` by `1`.
   h. If the path length is now `1` and the robot has a current task, complete the task.

### Logical flow pseudocode

```python
self.current_step += 1
print("STEP", self.current_step)
self.assign_new_tasks()
self.collision_manager.reset_step()
for robot in self.robot_manager.robots:
    self.handle_battery(robot)
    if len(robot.path) <= 1:
        if robot.status == RobotStatus.CHARGING:
            robot.battery += 10
            if robot.battery >= 100:
                robot.battery = 100
                robot.status = RobotStatus.IDLE
        continue
    next_x, next_y = robot.path[1]
    if not self.collision_manager.reserve_cell(next_x, next_y):
        continue
    robot.position.x = next_x
    robot.position.y = next_y
    robot.path.pop(0)
    robot.battery -= 1
    print("Robot moved")
    if len(robot.path) == 1:
        if robot.status == RobotStatus.CHARGING:
            print("arrived at charger")
        elif robot.current_task is not None:
            self.task_manager.complete_task(robot.current_task)
            robot.current_task = None
            robot.status = RobotStatus.IDLE
```

### Detailed breakdown

- **Task assignment** happens before robots move each step.
- **Collision state reset** happens once per step, so reservation is only one-step deep.
- **Battery handling** occurs for every robot before movement.
- **Movement** is executed only when a robot has a remaining path longer than one cell.
- **Task completion** is detected by path exhaustion, not by explicit task pickup/delivery logic.

### Simulation completion criteria

`SimulationEngine.is_complete()` returns `True` only when:

- there are no unfinished tasks (`task.completed == False`), and
- no robot has `current_task` assigned.

This means the simulation may still continue if tasks remain uncompleted or if robots are still assigned to tasks.

## 12. Dynamic Task Injection

Dynamic task injection is already implemented in `simulation/main.py`.

### Runtime insertion points

During the simulation loop:

- At simulation step `10`, the runtime creates a new task at `(5, 6)`.
- At simulation step `20`, the runtime creates a new task at `(18, 15)`.

The new tasks are appended to `task_manager.tasks` and are eligible for assignment in the next simulation step.

### How reassignment works

When a robot is forced to charge, `handle_battery()` unassigns its task and that task re-enters `get_unassigned_tasks()`.

When new tasks are inserted, they are also available to the same auction system.

### Auction rerun behavior

The auction system is run for every unassigned task every step inside `assign_new_tasks()`.

Each unassigned task receives a separate auction. If no eligible robot is found, the task remains unassigned and will be retried in the next step.

### Expected behavior

- New tasks should be discovered on the next simulation step after insertion.
- If eligible robots exist, the auction will assign them based on bid score.
- If no robot has sufficient battery or all are occupied, the task remains unassigned until conditions change.

## 13. Current Working Scenario

This section describes exactly what happens when `simulation/main.py` is executed.

### Initialization

1. `Warehouse(width=30, height=20)` is instantiated.
2. `warehouse.generate()` is called, creating the grid, shelf rows, charging stations, and spawn cells.
3. `RobotManager()` is created.
4. `robot_manager.spawn_from_warehouse(warehouse)` spawns robots for each `R` cell. With spawn row 18 and columns 1-5, there are 5 robots.
5. `TaskManager()` is created.
6. Five initial tasks are created at hard-coded pickup coordinates.
7. `AStarPathfinder(warehouse)` is created.
8. `CollisionManager()` is created.
9. `ChargingManager()` is created with fixed station coordinates.
10. `AuctionManager(robot_manager)` is created.
11. `SimulationEngine(...)` is instantiated with all managers.
12. The program prints counts for robots and tasks and object representations.

### Start of the simulation loop

`while not simulation.is_complete(): simulation.step()` begins the runtime.

Each step executes the simulation engine as described in Section 11.

### Auction phase

At every step, the simulation attempts to assign all currently unassigned tasks.

For each task:

- `AuctionManager.run_auction(task)` collects bids from all robots with `current_task is None` and `battery >= 30`.
- It selects the lowest bid and returns a robot ID.
- If a winner exists, the task is assigned and the robot receives an A* path to the pickup location.

### Path generation

A path is generated by `AStarPathfinder.find_path()` using the robot's current coordinates and the task pickup coordinates.

If no path is found, the task remains unassigned.

### Movement

Robots with assigned paths move one step per simulation step if their next target cell is free.

Movement occurs by advancing from `path[0]` to `path[1]` and removing the first element.

A robot consumes one battery unit for each movement step.

### Task completion

When a robot's path length reaches `1` after a movement and it has a current task, the task is marked complete, the robot's current task is cleared, and its status becomes `IDLE`.

### Dynamic task injection

At step 10, `task_manager.create_task(5, 6)` adds a new pickup task.

At step 20, `task_manager.create_task(18, 15)` adds another new pickup task.

These tasks enter the auction pool immediately on the next step.

### Simulation termination

The loop exits when `simulation.is_complete()` returns `True`.

This occurs only when all tasks in `task_manager.tasks` are completed and no robot has an assigned task.

Once complete, the program prints `SIMULATION COMPLETE`.

## 14. Current Limitations

These limitations are derived directly from the current implementation.

- No explicit robot physical footprint; robots occupy a single cell only.
- No task delivery or drop-off destination. Tasks are completed upon reaching a pickup cell.
- No multi-stage tasks or carrier handoffs.
- No task priorities, deadlines, or task type variations.
- No multi-agent path planning beyond single-robot A* planning.
- No advanced congestion prediction or flow management.
- No visualization UI: the project is console-only.
- No persistence of state to disk.
- Auction uses only current position and battery; it does not consider assigned path length or task sequence.
- Collision avoidance is only one-step reservation and does not prevent future collisions.
- Charging stations are unbounded; infinite robots can occupy the same charger coordinate over multiple steps.
- Robot `status` enum values are defined but not all status values are used.
- The warehouse constants file exists but is not integrated into the runtime.
- Robots can be assigned tasks while in `CHARGING` status because only task assignment and battery thresholds are checked.
- `SimulationEngine.is_complete()` does not require zero robot movement paths, only no assigned tasks, so robots may still hold stale paths if `current_task` is cleared.
- There is no timeout or maximum number of steps guard; certain failure modes can run indefinitely.

## 15. Known Bugs and Failure Modes

### Infinite Simulation Loop

- **Cause:** An unassigned task remains incomplete and there are no eligible robots to take it.
- **Symptoms:** `simulation.current_step` continues to increment endlessly.
- **Diagnosis:** Check if tasks remain with `completed == False` and `assigned_robot is None`, and whether all robots have `battery < 30` or no valid paths.
- **Fix:** Ensure `assign_new_tasks()` can eventually assign or expire tasks; add a fallback or step limit.

### Task Never Completes When Start Equals Goal

- **Cause:** A robot assigned to a task that is already at the pickup location receives a path of length `1`, but movement and completion logic only process completion after moving.
- **Symptoms:** Robot remains at the pickup position, status may be `MOVING`, task is never marked `completed`, simulation may stall.
- **Diagnosis:** Inspect `robot.path` length and `robot.status` when a robot is assigned a task at its current location.
- **Fix:** Add explicit completion when `len(robot.path) == 1` immediately after assignment or treat zero-move path as immediate completion.

### Charging Robot Can Be Reassigned a Task

- **Cause:** `AuctionManager.run_auction()` only filters on `robot.current_task is None` and `robot.battery >= 30`. It does not prevent robots with `status == CHARGING` from bidding.
- **Symptoms:** A robot already heading to a charger may be assigned a new task unexpectedly.
- **Diagnosis:** Check `robot.status` in auction eligibility.
- **Fix:** Add `robot.status == RobotStatus.IDLE` or disallow `CHARGING` robots from bidding.

### Path Reservation Starvation

- **Cause:** `CollisionManager` reserves only the next target cell for the current step. If two robots keep competing, one may repeatedly get blocked.
- **Symptoms:** A robot fails to move for several steps while another repeatedly obtains the cell.
- **Diagnosis:** Trace `collision_manager.reserved_cells` and robot order in `SimulationEngine.step()`.
- **Fix:** Introduce fairness, two-way swap handling, or a multi-step reservation table.

### Task Release on Low Battery Does Not Consider Destination Reachability

- **Cause:** A robot may release a task due low battery and then compute a charger path without verifying the charger is reachable.
- **Symptoms:** The robot may be stuck if A* returns `[]`, and the task stays unassigned.
- **Diagnosis:** Confirm `robot.path` after calling `handle_battery()` when `charging_manager.get_nearest_station()` returns a valid coordinate.
- **Fix:** Add a check for path existence and handle unreachable chargers gracefully.

### Unused Constants and Enum Values

- **Cause:** `simulation/constants.py` defines constants that are not referenced in other modules. Several `RobotStatus` values are unused.
- **Symptoms:** The codebase has redundant or misleading definitions.
- **Diagnosis:** Search for constant imports and enum value references.
- **Fix:** Remove or integrate unused constants; align the enum with actual behavior.

### No Validation of Task Coordinates

- **Cause:** Tasks can be created at any coordinate without checking walkability.
- **Symptoms:** A task may be created on a shelf or outside reachable area, causing `find_path()` to fail and task to remain unassigned.
- **Diagnosis:** Inspect `task_manager.create_task()` and the coordinates it receives.
- **Fix:** Validate pickup coordinates against `Warehouse.is_walkable()` upon task creation.

## 16. AI Debugging Guide

This section maps common problems to likely files and concrete checks.

### Problem: Robot not moving

- Likely Files:
  - `simulation/simulation_engine.py`
  - `simulation/pathfinder.py`
  - `simulation/collision_manager.py`
  - `simulation/robot_manager.py`
- Checks:
  1. Is `robot.path` length greater than 1?
  2. Is `robot.status` `CHARGING`, `MOVING`, or `IDLE`?
  3. Does `handle_battery()` reset the robot to charge unexpectedly?
  4. Does `reserve_cell(next_x, next_y)` return `False` because another robot reserved the cell?
  5. Is the path computed by `find_path()` valid and non-empty?

### Problem: Task never completes

- Likely Files:
  - `simulation/simulation_engine.py`
  - `simulation/task_manager.py`
  - `simulation/pathfinder.py`
- Checks:
  1. Is `robot.current_task` still set after reaching the final path cell?
  2. Does `robot.path` ever shrink to exactly 1 while `robot.status` is non-`CHARGING`?
  3. Was the task assigned to a robot with an immediate path length of 1?
  4. Are tasks being completed by `task_manager.complete_task()`?

### Problem: Infinite loop

- Likely Files:
  - `simulation/main.py`
  - `simulation/simulation_engine.py`
  - `simulation/task_manager.py`
  - `simulation/auction_manager.py`
- Checks:
  1. Does `simulation.is_complete()` remain `False` because there are incomplete tasks?
  2. Are there tasks that are unassigned and unreachable?
  3. Are all robots low on battery and unable to bid?
  4. Is there a maximum step count guard? (No.)

### Problem: Robot never charges

- Likely Files:
  - `simulation/simulation_engine.py`
  - `simulation/charging_manager.py`
  - `simulation/robot_manager.py`
- Checks:
  1. Is `robot.battery <= 20` when `handle_battery()` runs?
  2. Is `robot.status == RobotStatus.CHARGING` preventing the charge logic from running? (It should allow the battery increment path.)
  3. Does `robot.path` successfully target a charger?
  4. Is `charging_manager.get_nearest_station(robot)` returning a valid tuple?

### Problem: Task gets assigned to a robot but never moved

- Likely Files:
  - `simulation/simulation_engine.py`
  - `simulation/robot_manager.py`
  - `simulation/task_manager.py`
- Checks:
  1. Was the task successfully assigned in `assign_new_tasks()`?
  2. Was `robot.path` set to an empty list or a list of length 1?
  3. Is the robot being diverted to charge before movement begins?
  4. Does `AuctionManager.run_auction()` assign a robot already in `CHARGING` status?

### Problem: Auction chooses suboptimal robot

- Likely Files:
  - `simulation/auction_manager.py`
  - `simulation/robot_manager.py`
  - `simulation/simulation_engine.py`
- Checks:
  1. Are all eligible robots being considered?
  2. Is `robot.current_task` incorrectly set or cleared?
  3. Is battery penalty computed correctly?
  4. Are tasks assigned in the correct order?

### Problem: Collision manager does not prevent collisions

- Likely Files:
  - `simulation/collision_manager.py`
  - `simulation/simulation_engine.py`
- Checks:
  1. Does `reserve_cell()` add the coordinate to `reserved_cells`?
  2. Was `reset_step()` called at the beginning of the step?
  3. Do two robots report moving into the same target cell in the same step?

### Problem: Charging station unreachable

- Likely Files:
  - `simulation/charging_manager.py`
  - `simulation/pathfinder.py`
  - `simulation/warehouse.py`
- Checks:
  1. Is the charging station coordinate present in a walkable cell?
  2. Does `AStarPathfinder.find_path()` return `[]` for the charger target?
  3. Does the charger coordinate match `warehouse.grid` layout?

## 17. Day-by-Day Evolution

The current implementation reflects the following incremental evolution.

### Day 1: Project structure

- Established the `simulation` package and repository layout.
- Created placeholder files for core components.

### Day 2: Warehouse environment

- Implemented `Warehouse`.
- Added grid generation.
- Added shelf placement, charging station placement, and robot spawn area.
- Added walkability and neighbor discovery.

### Day 3: Robot models and spawning

- Implemented `Robot`, `Position`, and `RobotStatus`.
- Implemented `RobotManager` and robot spawning from warehouse spawn cells.
- Added robot creation and retrieval methods.

### Day 4: A* pathfinding

- Implemented `AStarPathfinder`.
- Added Manhattan heuristic and path reconstruction.
- Integrated path computation with warehouse walkability.

### Day 5: Task system

- Implemented `TaskManager`.
- Added task creation, assignment, unassignment, and completion.
- Introduced tasks with pickup coordinates.

### Day 6: Auction-based task allocation

- Implemented `AuctionManager`.
- Added bid calculation using distance and battery penalty.
- Added robot eligibility filtering.

### Day 7: Multi-robot simulation engine

- Implemented `SimulationEngine`.
- Added simulation step logic and task assignment.
- Connected robots, tasks, pathfinding, and auctions.

### Day 8: Collision avoidance

- Implemented `CollisionManager`.
- Added per-step cell reservation.
- Integrated collision checks into robot movement.

### Day 9: Battery management and charging

- Implemented `ChargingManager`.
- Added battery threshold logic and charging station routing.
- Added charging state and battery recharge increments.

### Day 10: Dynamic task injection and task reassignment

- Implemented dynamic task creation at steps 10 and 20.
- Added task release when robots transition to charging.
- Added repeated auction attempts for unassigned tasks.

## 18. Future Roadmap

This section describes potential future directions without claiming they already exist.

- Delivery stations and explicit drop-off destinations.
- Multi-stage tasks with pickup and delivery phases.
- Multi-Agent Path Finding (MAPF) and cooperative path planning.
- Conflict-Based Search (CBS) for collision-free multi-robot paths.
- Persistent reservation tables spanning multiple steps.
- Warehouse heatmaps for congestion analysis.
- Fleet optimization and workload balancing across the swarm.
- Reinforcement learning for adaptive auction or routing behavior.
- Swarm intelligence mechanisms such as distributed bidding or pheromone-like coordination.
- Digital twin visualization for warehouse monitoring and debugging.

## 19. Run Instructions

### Python version

- This project requires Python 3.10 or newer because it uses union types like `int | None`.

### Dependencies

- `pydantic` is required by `simulation/models.py`.

Install dependencies with:

```bash
python -m pip install pydantic
```

### Execution command

Run the simulation from the repository root:

```bash
python simulation/main.py
```

### Expected output

The program prints:

- robot and task counts,
- component object representations,
- a step-by-step log of movements,
- task assignments,
- charging behavior,
- and a final `SIMULATION COMPLETE` message.

### Common issues

- If `pydantic` is not installed, Python will raise an import error for `simulation.models`.
- If using Python older than 3.10, type syntax `int | None` will fail.
- There is no built-in runtime limit, so a stuck scenario may loop indefinitely if tasks cannot be completed.

## 20. AI Context Compression Summary

This section is the shortest single-page summary future AI assistants should read first.

### Core architecture

- `simulation/main.py` builds the system and loops until completion.
- `Warehouse` generates a fixed 30x20 grid with shelves (`S`), chargers (`C`), and spawn cells (`R`).
- `RobotManager` spawns 5 robots on `R` cells and stores them.
- `TaskManager` maintains pickup tasks with `id`, coordinates, assignment state, and completion.
- `AuctionManager` assigns tasks by minimizing Manhattan distance plus battery penalty.
- `AStarPathfinder` computes grid paths using Manhattan heuristic and warehouse walkability.
- `CollisionManager` reserves the next cell per robot per step.
- `ChargingManager` selects the nearest charger by Manhattan distance.
- `SimulationEngine` performs assignment, battery handling, movement, task completion, and step advancement.

### File purposes

- `simulation/constants.py`: static warehouse and robot constants (defined but not used).
- `simulation/models.py`: robot data models.
- `simulation/warehouse.py`: warehouse grid construction and neighbor logic.
- `simulation/pathfinder.py`: A* search implementation.
- `simulation/task_manager.py`: task CRUD and state tracking.
- `simulation/robot_manager.py`: robot spawning and task assignment.
- `simulation/auction_manager.py`: bid calculation and auction winner selection.
- `simulation/collision_manager.py`: step-local movement reservation.
- `simulation/charging_manager.py`: charger selection.
- `simulation/simulation_engine.py`: step orchestration.
- `simulation/main.py`: simulation entry point and dynamic task injection.

### Core algorithms

- **A***: 4-neighbor Manhattan grid search with open-set heap and g/f scores.
- **Auction**: each unassigned task performs a robot bid evaluation; the lowest bid wins.
- **Collision avoidance**: per-step reservation of next move targets.
- **Charging**: robots with battery <= 20 release tasks and path to nearest charger.

### Simulation lifecycle

1. Initialize environment, robots, tasks, and managers.
2. Enter loop while tasks remain incomplete.
3. Assign unassigned tasks with auctions.
4. Reset collision reservations.
5. For each robot:
   - handle battery recharge and charging logic,
   - move along path if possible,
   - decrement battery on movement,
   - complete tasks when the path ends.
6. Inject new tasks at step 10 and 20.
7. Exit once all tasks are complete and no robot has an active task.

### Debugging strategy

For a given failure mode, identify the responsible module by symptom:

- Movement issues -> `simulation_engine.py`, `collision_manager.py`, `pathfinder.py`.
- Auction issues -> `auction_manager.py`, `robot_manager.py`, `task_manager.py`.
- Task completion issues -> `simulation_engine.py`, `task_manager.py`.
- Battery/charging issues -> `simulation_engine.py`, `charging_manager.py`.
- Grid/path issues -> `warehouse.py`, `pathfinder.py`.

Start with state inspection: robot paths, battery levels, task assignment flags, and current step prints.

---

This README reflects the exact current implementation of the Warehouse Swarm Project. It should be sufficient for future AI agents to understand the system, diagnose problems, and extend the code with confidence.
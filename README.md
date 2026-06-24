# Warehouse Swarm Project

## 1. Executive Summary

**Warehouse Swarm Project** is a Python-based swarm robotics warehouse simulation with a FastAPI backend and a live browser-based visualization dashboard. It demonstrates how multiple robots operate concurrently in a structured warehouse grid, bid for pickup-and-delivery tasks via auction, navigate with A* pathfinding, avoid collisions, manage battery and charging behavior, and respond to dynamic task injection during runtime.

The system consists of:

- A **simulation core** — a step-based engine that manages warehouse generation, robot spawning, task creation, auction-based allocation, A* pathfinding, collision avoidance, battery management, and a pickup→delivery workflow.
- A **FastAPI REST API** — exposes simulation state (robots, tasks, status), provides simulation control (step, start, pause, reset), and accepts dynamic task creation.
- A **browser dashboard** — a Jinja2-rendered HTML/CSS/JS page at `/dashboard` that visualizes the warehouse grid in real-time by polling the API every 200ms.

The simulation runs in-memory. All state lives in Python objects. There is no database, no Redis, no message queue.

---

## 2. System Architecture

### Architecture Overview

```text
Browser Dashboard (HTML/CSS/JS)
       │
       │ HTTP (fetch every 200ms)
       ▼
FastAPI REST API (simulation/api.py)
       │
       │ direct Python method calls
       ▼
┌─────────────────────────────────────────────────────┐
│                 SimulationEngine                     │
│  ┌──────────┐ ┌──────────────┐ ┌──────────────────┐ │
│  │ Warehouse│ │ RobotManager │ │  TaskManager     │ │
│  └──────────┘ └──────────────┘ └──────────────────┘ │
│  ┌──────────────┐ ┌────────────┐ ┌────────────────┐ │
│  │AuctionManager│ │ Pathfinder │ │CollisionManager│ │
│  └──────────────┘ └────────────┘ └────────────────┘ │
│  ┌────────────────┐                                  │
│  │ChargingManager │                                  │
│  └────────────────┘                                  │
└─────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | File | Responsibility |
|---|---|---|
| **Warehouse** | `simulation/warehouse.py` | 30×20 grid generation with shelves, aisles, chargers, spawn area. Walkability checks and neighbor discovery for pathfinding. |
| **RobotManager** | `simulation/robot_manager.py` | Robot creation, spawning from warehouse spawn cells, robot lookup by ID, task assignment to individual robots. |
| **TaskManager** | `simulation/task_manager.py` | Task creation (pickup + delivery coordinates), assignment, unassignment, completion. Tracks task lifecycle. |
| **AuctionManager** | `simulation/auction_manager.py` | Auction-based task allocation. Computes bid = Manhattan distance + battery penalty. Filters robots by eligibility. Lowest bid wins. |
| **AStarPathfinder** | `simulation/pathfinder.py` | A* pathfinding on the warehouse grid. Manhattan heuristic. Returns list of coordinate tuples from start to goal. |
| **CollisionManager** | `simulation/collision_manager.py` | Per-step cell reservation. Prevents two robots from occupying the same cell in the same simulation step. |
| **ChargingManager** | `simulation/charging_manager.py` | Selects nearest charging station by Manhattan distance for low-battery robots. |
| **SimulationEngine** | `simulation/simulation_engine.py` | Orchestrates each simulation step: task assignment, battery handling, robot movement, task completion, charging. |
| **API** | `simulation/api.py` | FastAPI application. Initializes simulation, exposes REST endpoints, manages background simulation thread. |
| **Dashboard** | `simulation/templates/dashboard.html` | Browser-based visualization. Pure HTML/CSS/JS with Jinja2 templating. Polls API every 200ms. |
| **Main** | `simulation/main.py` | Console-based simulation runner (standalone, not used by API). |
| **Constants** | `simulation/constants.py` | Shared constants (currently not imported by other modules). |
| **Models** | `simulation/models.py` | Pydantic models: `Position`, `RobotStatus` enum, `Robot`. |

---

## 3. Repository Structure

```text
Warehouse Swarm Porject/
├── README.md
├── python311/                    # Local Python 3.11 installation
├── simulation/
│   ├── __init__.py               # Package marker (empty)
│   ├── api.py                    # FastAPI app (361 lines)
│   ├── auction_manager.py        # Auction-based task allocation (86 lines)
│   ├── charging_manager.py       # Charging station selection (52 lines)
│   ├── collision_manager.py      # Per-step collision avoidance (24 lines)
│   ├── constants.py              # Shared constants (11 lines)
│   ├── main.py                   # Console simulation runner (133 lines)
│   ├── models.py                 # Pydantic models (71 lines)
│   ├── pathfinder.py             # A* pathfinding (110 lines)
│   ├── robot_manager.py          # Robot lifecycle management (104 lines)
│   ├── simulation_engine.py      # Core step engine (227 lines)
│   ├── task_manager.py           # Task lifecycle management (99 lines)
│   ├── warehouse.py              # Grid generation (95 lines)
│   └── templates/
│       └── dashboard.html        # Browser visualization (756 lines)
```

---

## 4. Data Models

### Position (Pydantic BaseModel)

```python
class Position(BaseModel):
    x: int
    y: int
```

### RobotStatus (str, Enum)

| Value | Used In Engine |
|---|---|
| `IDLE` | ✅ Yes — default state, after task completion, after charging complete |
| `MOVING` | ✅ Yes — when assigned a task and navigating to pickup |
| `DELIVERING` | ✅ Yes — when carrying item and navigating to delivery |
| `CHARGING` | ✅ Yes — when battery ≤ 20, navigating to charger or charging |
| `WAITING` | ❌ Defined but unused |
| `PICKING` | ❌ Defined but unused |
| `NEEDS_CHARGE` | ❌ Defined but unused |

### Robot (Pydantic BaseModel)

| Field | Type | Default | Description |
|---|---|---|---|
| `id` | `int` | required | Unique robot identifier (1-indexed) |
| `battery` | `float` | required | Battery percentage (0–100) |
| `position` | `Position` | required | Current (x, y) on warehouse grid |
| `status` | `RobotStatus` | required | Current state |
| `current_task` | `int \| None` | `None` | Assigned task ID or None |
| `carrying_item` | `bool` | `False` | Whether robot has picked up the item |
| `path` | `list` | `[]` | Planned path as list of (x, y) tuples |
| `delivery_path` | `list` | `[]` | Path from pickup to delivery location |

### Task (dataclass)

| Field | Type | Default | Description |
|---|---|---|---|
| `id` | `int` | required | Unique task identifier (1-indexed, auto-incremented) |
| `pickup_x` | `int` | required | Pickup X coordinate |
| `pickup_y` | `int` | required | Pickup Y coordinate |
| `delivery_x` | `int` | required | Delivery X coordinate |
| `delivery_y` | `int` | required | Delivery Y coordinate |
| `completed` | `bool` | `False` | Whether task has been delivered |
| `assigned_robot` | `int \| None` | `None` | Assigned robot ID or None |

---

## 5. Warehouse Model

### Grid Specification

- **Dimensions:** 30 columns × 20 rows.
- **Data structure:** `self.grid[y][x]` — list of lists, indexed as `grid[row][column]`.
- **Cell types:**

| Symbol | Meaning | Walkable |
|---|---|---|
| `.` | Open aisle | ✅ Yes |
| `S` | Shelf (obstacle) | ❌ No |
| `C` | Charging station | ✅ Yes |
| `R` | Robot spawn cell | ✅ Yes |

### Generation Rules

1. `create_empty_grid()` — fills entire grid with `.`.
2. `add_shelves()` — places `S` on rows `2, 5, 8, 11, 14, 17` (every 3rd row starting at 2), columns `2` through `27` (inclusive). Leaves columns 0–1 and 28–29 free.
3. `add_charging_stations()` — places `C` at `(0,0)`, `(1,0)`, `(28,0)`, `(29,0)` (top row, corners).
4. `add_robot_spawn_area()` — places `R` at row `18`, columns `1` through `5`. These become the 5 spawn positions.

### Walkability

`is_walkable(x, y)` returns `True` if the cell is within bounds AND `grid[y][x] != "S"`. All non-shelf cells (`.`, `C`, `R`) are walkable.

### Neighbor Discovery

`get_neighbors(x, y)` returns walkable cells in 4 cardinal directions: north `(0,-1)`, south `(0,1)`, east `(1,0)`, west `(-1,0)`.

---

## 6. Robot System

### Spawning

`RobotManager.spawn_from_warehouse(warehouse)` scans the entire grid for `R` cells and creates one robot per cell with `battery=100.0` and `status=IDLE`. With the default warehouse, this produces 5 robots at positions `(1,18)`, `(2,18)`, `(3,18)`, `(4,18)`, `(5,18)`.

### State Transitions

```text
IDLE ──(task assigned)──► MOVING ──(arrived at pickup)──► DELIVERING ──(arrived at delivery)──► IDLE
  │                                                                                               ▲
  │                         ▲                                                                     │
  ├──(battery ≤ 20)──► CHARGING ──(battery = 100)─────────────────────────────────────────────────┘
  │                         ▲
  └─────────────────────────┘ (also from MOVING/DELIVERING if battery ≤ 20)
```

### Battery

- **Drain:** `-1` per movement step.
- **Charge threshold:** When `battery ≤ 20` and not already `CHARGING`.
- **Charge rate:** `+10` per simulation step while at a charging station (path length ≤ 1).
- **Charge cap:** Clamped to `100`.
- **Idle drain:** None. Idle robots do not consume battery.

---

## 7. Task System

### Task Creation

`TaskManager.create_task(pickup_x, pickup_y, delivery_x, delivery_y)` creates a task with an auto-incremented ID, `completed=False`, `assigned_robot=None`.

### Default Tasks (created at startup)

| Task ID | Pickup (x, y) | Delivery (x, y) |
|---|---|---|
| 1 | (10, 1) | (1, 1) |
| 2 | (15, 4) | (1, 4) |
| 3 | (20, 7) | (1, 7) |
| 4 | (25, 10) | (1, 10) |
| 5 | (27, 13) | (1, 13) |

### Task Lifecycle

1. **UNASSIGNED** — `assigned_robot is None`, `completed is False`.
2. **ASSIGNED** — `assigned_robot` set to a robot ID.
3. **COMPLETED** — `completed is True`.

### Task Unassignment

When a robot's battery drops ≤ 20 while it has an assigned task, `handle_battery()` calls `task_manager.unassign_task(task_id)`, making the task available for re-auction.

---

## 8. Pathfinding System

### A* Implementation

`AStarPathfinder.find_path(start, goal)`:

- **Input:** `start` and `goal` as `(x, y)` tuples.
- **Heuristic:** Manhattan distance: `abs(a[0] - b[0]) + abs(a[1] - b[1])`.
- **Open set:** Binary heap of `(f_score, node)`.
- **No explicit closed set.** Uses `g_score` dict for pruning.
- **Edge cost:** Uniform `1` per step.
- **Output:** List of `(x, y)` tuples from start to goal (inclusive), or `[]` if no path exists.

### Path Consumption

The simulation engine moves a robot by reading `robot.path[1]`, updating `robot.position`, then calling `robot.path.pop(0)`. When `len(robot.path) == 1`, the robot has arrived at the destination.

---

## 9. Auction Allocation System

### Bid Formula

```
bid = manhattan_distance(robot.position, task.pickup) + (100 - robot.battery) * 0.1
```

### Robot Eligibility

A robot can bid only if:

- `robot.current_task is None` (no active task).
- `robot.battery >= 30` (sufficient battery).

### Winner Selection

Bids are collected as `(bid_value, robot_id)` tuples, sorted ascending. The robot with the lowest bid wins. On ties, the lower robot ID wins (Python tuple sort).

---

## 10. Collision Avoidance

### Mechanism

`CollisionManager` maintains a `reserved_cells` set, cleared at the start of each step via `reset_step()`.

When a robot wants to move:

```python
if not collision_manager.reserve_cell(next_x, next_y):
    continue  # robot stays in place this step
```

The first robot to reserve a cell in iteration order wins. Other robots attempting the same cell remain stationary for that step.

### Limitations

- Step-local only (no multi-step path reservation).
- No swap detection.
- No deadlock avoidance.
- Iteration order creates a fixed priority bias.

---

## 11. Battery and Charging System

### Charging Stations

4 hardcoded stations at `(0,0)`, `(1,0)`, `(28,0)`, `(29,0)`.

### Charging Flow

1. Robot battery drops to ≤ 20 (and not already `CHARGING`).
2. `handle_battery()` unassigns any current task (returns it to auction pool).
3. `ChargingManager.get_nearest_station(robot)` selects the closest station by Manhattan distance.
4. A* path is computed from robot's position to the station.
5. Robot's status becomes `CHARGING`, path is set to charger path, `current_task = None`.
6. Robot moves toward the charger, draining battery `-1` per step.
7. Once arrived (path length ≤ 1), battery increments `+10` per simulation step.
8. When battery ≥ 100, it's clamped to 100 and status becomes `IDLE`.

---

## 12. Simulation Engine

### Step Sequence

`SimulationEngine.step()` executes the following sequence on every call:

1. Increment `current_step`.
2. Print step number.
3. Call `assign_new_tasks()` — iterates unassigned tasks, runs auctions, computes pickup paths and delivery paths, assigns winners.
4. Call `collision_manager.reset_step()` — clears cell reservations.
5. For each robot:
   a. Call `handle_battery(robot)` — check if battery ≤ 20, redirect to charger if needed.
   b. If `len(robot.path) <= 1`:
      - If `CHARGING`: add `+10` to battery. If ≥ 100, set `IDLE`.
      - `continue` (skip movement).
   c. Read `robot.path[1]` as next position.
   d. Attempt `collision_manager.reserve_cell(next_x, next_y)`. If fails, `continue`.
   e. Update `robot.position` to next cell, `path.pop(0)`, `battery -= 1`.
   f. If `len(robot.path) == 1` after move:
      - If `CHARGING`: arrived at charger (print message).
      - If `current_task is not None` and `not carrying_item`: pick up item → set `carrying_item = True`, swap path to `delivery_path`, set status `DELIVERING`.
      - If `current_task is not None` and `carrying_item`: deliver item → mark task complete, reset robot to `IDLE`, clear `carrying_item`, clear `delivery_path`.

### Pickup → Delivery Workflow

When a task is assigned to a robot:

1. `pickup_path` is computed (robot position → task pickup).
2. `delivery_path` is computed (task pickup → task delivery).
3. Robot navigates `pickup_path` in `MOVING` status.
4. On arrival at pickup: sets `carrying_item = True`, swaps `robot.path` to `delivery_path`, status becomes `DELIVERING`.
5. On arrival at delivery: marks task complete, resets robot to `IDLE`.

### Completion Detection

`is_complete()` returns `True` when:

- Zero unfinished tasks (all `completed == True`).
- Zero active robots (all `current_task is None`).

---

## 13. FastAPI REST API

### Application Setup

File: `simulation/api.py`

- FastAPI app version `2.0.0`.
- Jinja2 templates loaded from `simulation/templates/`.
- All simulation components initialized at module level via `initialize_simulation()` factory function.
- Background simulation thread managed by `threading.Thread` with `threading.Lock` for thread safety.
- Swagger UI available at `/docs`.

### Thread Safety

A single `threading.Lock` (`simulation_lock`) protects all mutation operations:

- `simulation.step()` — both manual and background loop.
- `task_manager.create_task()` — task creation.
- `initialize_simulation()` during reset.

The background thread acquires the lock only for the step call, not during `sleep(0.2)`, ensuring API responsiveness.

### Pydantic Request Model

```python
class TaskCreateRequest(BaseModel):
    pickup_x: int
    pickup_y: int
    delivery_x: int
    delivery_y: int
```

### API Endpoints

#### GET /

Root health check.

**Response:**

```json
{"message": "Warehouse Swarm API"}
```

---

#### GET /dashboard

Serves the browser-based warehouse visualization dashboard (Jinja2 HTML template).

**Response:** HTML page.

---

#### GET /warehouse/grid

Returns the warehouse grid layout for the dashboard to render.

**Response:**

```json
{
  "width": 30,
  "height": 20,
  "grid": [["C", "C", ".", ...], ...]
}
```

`grid` is a 2D array indexed as `grid[y][x]`. Each cell is one of `"."`, `"S"`, `"C"`, `"R"`.

---

#### GET /robots

Returns the current state of all robots.

**Response:**

```json
[
  {
    "id": 1,
    "position": {"x": 1, "y": 18},
    "battery": 95.0,
    "status": "MOVING",
    "current_task": 1
  }
]
```

---

#### GET /tasks

Returns the current state of all tasks.

**Response:**

```json
[
  {
    "id": 1,
    "assigned_robot": 1,
    "completed": false,
    "pickup_x": 10,
    "pickup_y": 1,
    "delivery_x": 1,
    "delivery_y": 1
  }
]
```

---

#### GET /simulation/status

Returns comprehensive simulation status.

**Response:**

```json
{
  "current_step": 42,
  "active_robots": 3,
  "unfinished_tasks": 2,
  "total_robots": 5,
  "total_tasks": 7,
  "simulation_complete": false,
  "running": true
}
```

---

#### POST /simulation/step

Execute exactly one simulation step. Thread-safe via lock.

**Response:**

```json
{"success": true, "current_step": 1}
```

---

#### POST /simulation/start

Start the autonomous background simulation loop (steps every 0.2 seconds).

**Response (success):**

```json
{"success": true, "message": "Simulation started"}
```

**Response (already running):**

```json
{"success": false, "message": "Simulation already running"}
```

---

#### POST /simulation/pause

Stop the background simulation loop.

**Response:**

```json
{"success": true, "message": "Simulation paused"}
```

---

#### POST /simulation/reset

Reset the entire simulation to initial state. Stops background thread, reconstructs all components, recreates default 5 tasks.

**Response:**

```json
{"success": true, "message": "Simulation reset"}
```

---

#### POST /tasks/create

Create a new task dynamically via API.

**Request body:**

```json
{
  "pickup_x": 10,
  "pickup_y": 5,
  "delivery_x": 1,
  "delivery_y": 10
}
```

**Response:**

```json
{"success": true, "task_id": 6}
```

---

## 14. Dashboard Visualization

### Overview

File: `simulation/templates/dashboard.html`

A single-page application served at `/dashboard`. Built with pure HTML, CSS, and JavaScript (no frameworks). Uses the Inter font via Google Fonts. Dark theme.

### Layout

- **Header** — title and connection status badge.
- **Sidebar** (left) — status panel, control buttons, legend, robot fleet list.
- **Main area** (right) — 30×20 warehouse grid visualization.

### Live Updates

Every 200ms, the dashboard calls 3 endpoints in parallel:

- `GET /robots`
- `GET /tasks`
- `GET /simulation/status`

It then redraws the grid, updates status values, and refreshes the robot fleet list. No page refresh required.

### Grid Rendering

On page load, the dashboard fetches `GET /warehouse/grid` once to get the static grid layout. It builds a CSS Grid of 34px × 34px cells. Each polling cycle:

1. All cells are reset to their base type (aisle, shelf, charger, spawn).
2. Incomplete task delivery locations are drawn in green (`D{id}`).
3. Incomplete task pickup locations are drawn in orange (`T{id}`).
4. Robot positions are drawn last (highest priority) in blue with ID and battery% label.

### Visual Encoding

| Element | Color | Label |
|---|---|---|
| Robot (normal) | Blue `#4a90e2` | `R{id}` + `{battery}%` |
| Robot (delivering) | Darker blue `#3a7ad6` | Same |
| Robot (charging) | Yellow `#c0a030` | Same |
| Task pickup | Orange `#e8913a` | `T{id}` |
| Task delivery | Green `#3dd68c` | `D{id}` |
| Charging station | Dark yellow background | ⚡ icon |
| Shelf | Purple-gray `#3a3550` | — |
| Aisle | Dark gray `#2a2e3b` | — |
| Spawn zone | Blue-gray `#2a3a45` | — |

### Control Buttons

| Button | Action |
|---|---|
| ▶ Start | `POST /simulation/start` |
| ⏸ Pause | `POST /simulation/pause` |
| ⏭ Step | `POST /simulation/step` |
| ↺ Reset | `POST /simulation/reset` |

### Robot Fleet Panel

Lists all robots with:

- Robot ID (e.g. `R1`)
- Status badge (IDLE / MOVING / CHARGING / DELIVERING) with color coding
- Battery bar (green > 50%, orange 21–50%, red ≤ 20%)
- Battery percentage text

---

## 15. Running the Project

### Prerequisites

- Python 3.11 (local installation at `python311/`)
- Required packages: `fastapi`, `uvicorn`, `pydantic`, `jinja2`

### Start the API Server

```bash
python311\python.exe -m uvicorn simulation.api:app --reload
```

Server starts at `http://127.0.0.1:8000`.

### Access Points

| URL | Description |
|---|---|
| `http://127.0.0.1:8000/` | API root (JSON health check) |
| `http://127.0.0.1:8000/docs` | Swagger UI (interactive API docs) |
| `http://127.0.0.1:8000/dashboard` | Live visualization dashboard |

### Console-Only Mode (standalone, no API)

```bash
python311\python.exe simulation\main.py
```

Runs the simulation in the console with print-based output until completion.

---

## 16. `simulation/main.py` Behavior

The standalone console runner:

1. Creates all simulation components (same as API).
2. Creates 5 default tasks.
3. Runs `simulation.step()` in a `while not simulation.is_complete()` loop.
4. At step 10: dynamically creates a task at `P(5,6) D(1,6)`.
5. At step 20: dynamically creates a task at `P(18,15) D(1,15)`.
6. Every 50 steps: prints debug info (task IDs, assigned robots, completion state).
7. Prints "SIMULATION COMPLETE" when done.

Note: `main.py` is independent from `api.py`. They share the same simulation modules but do not interact.

---

## 17. Module Dependency Graph

```text
models.py ◄── robot_manager.py ◄── auction_manager.py
                    ▲                      │
                    │                      │
warehouse.py ◄── pathfinder.py             │
    ▲                ▲                     │
    │                │                     │
    └── robot_manager.py                   │
                                           ▼
models.py ◄── simulation_engine.py ◄── api.py ──► dashboard.html
                    ▲                      ▲
                    │                      │
task_manager.py ────┘                      │
collision_manager.py ──────────────────────┘
charging_manager.py ───────────────────────┘
```

### Import Map (exact)

| File | Imports From |
|---|---|
| `models.py` | `enum.Enum`, `pydantic.BaseModel`, `pydantic.Field` |
| `warehouse.py` | (none) |
| `pathfinder.py` | `heapq` |
| `robot_manager.py` | `simulation.models` (Robot, Position, RobotStatus) |
| `task_manager.py` | `dataclasses.dataclass` |
| `auction_manager.py` | (none, receives `robot_manager` via constructor) |
| `collision_manager.py` | (none) |
| `charging_manager.py` | (none) |
| `simulation_engine.py` | `simulation.models.RobotStatus` |
| `api.py` | `sys`, `threading`, `time`, `pathlib.Path`, `fastapi`, `pydantic.BaseModel`, all simulation modules |
| `main.py` | `sys`, `pathlib.Path`, all simulation modules |
| `constants.py` | (none, currently not imported by any module) |

---

## 18. Key Implementation Details for AI Agents

### Path Format

Paths are lists of `(x, y)` tuples. Example: `[(3, 18), (3, 17), (3, 16), ..., (10, 1)]`. First element is current position, last is destination.

### Grid Coordinate System

- `x` = column (0–29, left to right).
- `y` = row (0–19, top to bottom).
- Grid access: `grid[y][x]`.

### Task Create Signature

```python
task_manager.create_task(pickup_x, pickup_y, delivery_x, delivery_y)
```

Takes 4 positional arguments. The task ID is auto-incremented internally.

### Simulation Factory

`initialize_simulation()` in `api.py` creates all 8 components and returns them as a tuple. Used at startup and by the `/simulation/reset` endpoint to rebuild from scratch.

### Background Thread

- `simulation_running` (bool) — controls the loop.
- `simulation_thread` (Thread, daemon) — runs `simulation_loop()`.
- `simulation_loop()` acquires `simulation_lock` → calls `simulation.step()` → releases lock → `time.sleep(0.2)`.
- Lock is never held during sleep.

### Global State in api.py

All simulation components are module-level variables in `api.py`. The `/simulation/reset` endpoint uses `global` to reassign them. The background thread references these globals.

### TemplateResponse Pattern

Due to recent FastAPI/Starlette API changes, `TemplateResponse` must be called with keyword arguments:

```python
templates.TemplateResponse(request=request, name="dashboard.html")
```

Not the older positional style `TemplateResponse("dashboard.html", {"request": request})`.

---

## 19. Known Limitations

- **No explicit closed set in A***. Relies on `g_score` for pruning. May produce duplicate heap entries.
- **Collision avoidance is step-local only.** No multi-step path reservation, no swap detection, no deadlock avoidance.
- **Iteration order bias.** Robots are iterated in fixed order; earlier robots get movement priority.
- **`path.pop(0)` is O(n).** Acceptable at current scale but would need `deque` for larger fleets.
- **Print-based logging.** All simulation output uses `print()`. Will pollute API server logs.
- **`constants.py` is unused.** Constants are defined but not imported anywhere.
- **No persistence.** All state is in-memory. Server restart loses everything.
- **No WebSocket support.** Dashboard uses polling (200ms interval), not push-based updates.
- **Single-threaded mutation.** All mutations go through one lock. Sufficient for current scale.
# Warehouse Swarm Project

## 1. Executive Summary

**Warehouse Swarm Project** is a Python-based multi-agent warehouse simulation with a FastAPI backend and a live browser-based visualization dashboard. It demonstrates how multiple autonomous robot agents and task agents communicate through a message bus, negotiate task allocation via the **Contract Net Protocol (CNP)**, navigate with A* pathfinding, avoid collisions, manage battery and charging behavior, and respond to dynamic task injection during runtime.

The system consists of:

- A **multi-agent simulation core** — autonomous RobotAgents and TaskAgents communicate via a MessageBus. TaskAgents issue Calls for Proposals (CFPs), RobotAgents submit bids (PROPOSALs), and TaskAgents award contracts (TASK_AWARDED). No centralized controller makes allocation decisions.
- A **FastAPI REST API** — exposes simulation state (robots, tasks, agents, messages), provides simulation control (step, start, pause, reset), and accepts dynamic task creation.
- A **browser dashboard** — a Jinja2-rendered HTML/CSS/JS page at `/dashboard` that visualizes the warehouse grid in real-time by polling the API every 200ms. It features live bidding logs, agent thought streams, and path intent overlays.

The simulation runs in-memory. All state lives in Python objects. There is no database, no Redis, no message queue. The warehouse environment (shelves, robot spawns, and tasks) is **procedurally generated** at startup and upon every simulation reset to ensure the AI agents learn to generalize their navigation and negotiation.

---

## 2. Multi-Agent Architecture

### Architecture Overview

```text
Browser Dashboard (HTML/CSS/JS)
       │
       │ HTTP (fetch every 200ms)
       ▼
FastAPI REST API (backend/api.py)
       │
       │ direct Python method calls
       ▼
┌──────────────────────────────────────────────────────────┐
│                   SimulationEngine                        │
│   (orchestration only — does NOT make decisions)          │
│                                                           │
│   ┌───────────────┐        ┌────────────────────┐        │
│   │  MessageBus   │◄──────►│  TaskAgentManager   │        │
│   │  (message_bus)│        │  ┌──────────────┐   │        │
│   │               │        │  │ TaskAgent T1  │   │        │
│   │  CFP ──────►  │        │  │ TaskAgent T2  │   │        │
│   │  PROPOSAL ◄── │        │  │ TaskAgent T3  │   │        │
│   │  AWARDED ───► │        │  │ ...           │   │        │
│   │               │        │  └──────────────┘   │        │
│   │  LOW_BATTERY  │        └────────────────────┘        │
│   │  BLOCKED_PATH │                                       │
│   │  TASK_RELEASED│        ┌────────────────────┐        │
│   │               │◄──────►│   AgentManager      │        │
│   │               │        │  ┌──────────────┐   │        │
│   │               │        │  │ RobotAgent R1 │   │        │
│   │               │        │  │ RobotAgent R2 │   │        │
│   │               │        │  │ RobotAgent R3 │   │        │
│   │               │        │  │ ...           │   │        │
│   │               │        │  └──────────────┘   │        │
│   └───────────────┘        └────────────────────┘        │
│                                                           │
│   ┌──────────┐ ┌──────────────┐ ┌──────────────────┐    │
│   │Warehouse │ │ RobotManager │ │  TaskManager     │    │
│   └──────────┘ └──────────────┘ └──────────────────┘    │
│   ┌────────────┐ ┌────────────────┐ ┌──────────────┐    │
│   │ Pathfinder │ │CollisionManager│ │ChargingManager│    │
│   └────────────┘ └────────────────┘ └──────────────┘    │
└──────────────────────────────────────────────────────────┘
```

### OLD Architecture (Centralized)

```text
SimulationEngine
  → AuctionManager (centralized decision authority)
  → Robot (passive data object)
```

### NEW Architecture (Multi-Agent)

```text
SimulationEngine (orchestration only)
  → MessageBus (communication backbone)
  → TaskAgentManager → TaskAgents (issue CFPs, award contracts)
  → AgentManager → RobotAgents (submit proposals, execute tasks)
```

Task assignment now **emerges through agent communication**, not centralized control.

---

## 3. Contract Net Protocol

The Contract Net Protocol (CNP) is the core negotiation mechanism for task allocation.

### CNP Lifecycle

```text
Step N:
  TaskAgent (WAITING) ──► broadcasts CFP to all RobotAgents

Step N (same tick):
  RobotAgent receives CFP ──► evaluates eligibility ──► sends PROPOSAL

Step N+1:
  TaskAgent (CFP_SENT) ──► collects PROPOSALs from inbox
                         ──► evaluates bids (lowest cost wins)
                         ──► sends TASK_AWARDED to winner
                         ──► marks task as assigned
  
  Winning RobotAgent receives TASK_AWARDED ──► updates memory
  (Robot already has path assigned by TaskAgent during award)
```

### CFP Message

```python
MessageType.CFP
payload = {
    "task_id": 3,
    "pickup_x": 20,
    "pickup_y": 7,
    "delivery_x": 1,
    "delivery_y": 7
}
```

Broadcast to all subscribed agents by the TaskAgent.

### PROPOSAL Message

```python
MessageType.PROPOSAL
payload = {
    "task_id": 3,
    "robot_id": 2,
    "estimated_cost": 28.5,
    "battery": 85.0,
    "distance": 27
}
```

Sent directly to the TaskAgent by each eligible RobotAgent.

### Bid Formula

```
estimated_cost = manhattan_distance(robot.position, task.pickup) + (100 - robot.battery) * 0.1
```

### Robot Eligibility for Bidding

A RobotAgent submits a proposal only if:
- `current_task is None` (no active task)
- `battery >= 30` (sufficient battery)
- `status != CHARGING` (not currently charging)

### TASK_AWARDED Message

```python
MessageType.TASK_AWARDED
payload = {
    "task_id": 3,
    "robot_id": 2
}
```

Sent directly to the winning RobotAgent by the TaskAgent.

### TaskAgent States

| State | Description |
|---|---|
| `WAITING` | Task exists, ready to issue CFP |
| `CFP_SENT` | CFP broadcast, collecting proposals for one tick |
| `AWARDED` | Contract awarded, robot is executing task |
| `COMPLETED` | Task delivered |

### Task Re-Auction

If a robot releases a task (e.g., battery low), the TaskAgent detects `assigned_robot is None` and transitions back to `WAITING`, re-issuing a CFP on the next tick.

---

## 4. Agent Communication

### MessageBus

File: `backend/message_bus.py`

An in-memory publish/subscribe system supporting:
- **Direct messaging**: `publish(message)` delivers to a specific recipient's inbox.
- **Broadcast**: `broadcast(message)` delivers to all subscribed inboxes except the sender's.
- **Per-agent inboxes**: each agent subscribes with a unique `agent_id`.
- **Non-blocking retrieval**: `get_messages(agent_id)` returns and clears pending messages.
- **Persistence**: messages remain in inboxes until consumed.

### Message Types

| Type | Direction | Purpose |
|---|---|---|
| `TASK_AVAILABLE` | broadcast | Announce a new task is available |
| `CFP` | broadcast | Call for Proposals (TaskAgent → all RobotAgents) |
| `PROPOSAL` | direct | Bid submission (RobotAgent → TaskAgent) |
| `TASK_AWARDED` | direct | Contract award (TaskAgent → winning RobotAgent) |
| `LOW_BATTERY` | broadcast | Robot reports low battery to peers |
| `BLOCKED_PATH` | broadcast | Robot reports a blocked cell to peers |
| `HELP_REQUEST` | broadcast | Robot requests assistance |
| `ROBOT_STATUS` | broadcast | Robot status update |
| `REROUTE` | direct | Suggest rerouting to a specific robot |
| `TASK_RELEASED` | broadcast | Robot released its assigned task |

### Message Format

```python
@dataclass
class Message:
    id: int              # auto-incremented
    sender: str          # e.g. "robot_1" or "task_3"
    recipient: str       # e.g. "robot_2" or "ALL"
    message_type: MessageType
    payload: dict        # arbitrary data
    timestamp: float     # time.time()
```

### Agent IDs

- Robot agents: `"robot_1"`, `"robot_2"`, etc.
- Task agents: `"task_1"`, `"task_2"`, etc.

### RobotAgent Communication

RobotAgents broadcast the following messages during their tick:

| Event | Message Type | When |
|---|---|---|
| Battery drops to ≤ 20 | `LOW_BATTERY` | During `need_charge` action |
| Path cell is blocked | `BLOCKED_PATH` | During `move` action (cell already reserved) |
| Task is released | `TASK_RELEASED` | During `need_charge` action (had assigned task) |

RobotAgents process incoming messages:

| Message Type | Agent Reaction |
|---|---|
| `CFP` | Evaluate eligibility, submit `PROPOSAL` if qualified |
| `TASK_AWARDED` | Record in memory |
| `LOW_BATTERY` | Update `nearby_low_battery` beliefs |
| `BLOCKED_PATH` | Update `nearby_blocked` beliefs |
| `TASK_RELEASED` | Record in memory |

---

## 5. Component Details

### Repository Structure

```text
Warehouse Swarm Porject/
├── README.md
├── python311/                        # Local Python 3.11
├── backend/
│   ├── __init__.py
│   ├── api.py                        # FastAPI app with MAS integration
│   ├── main.py                       # Console simulation runner
│   ├── core/                         # Base schemas and configurations
│   │   ├── models.py
│   │   └── constants.py
│   ├── state/                        # In-memory storage managers
│   │   ├── robot_state.py
│   │   └── task_state.py
│   ├── simulation/                   # Physics and environment
│   │   ├── engine.py
│   │   ├── warehouse.py
│   │   ├── pathfinder.py
│   │   ├── collision.py
│   │   └── charging.py
│   └── agents/                       # Multi-Agent System (MAS)
│       ├── robot.py
│       ├── task.py
│       ├── robot_orchestrator.py
│       ├── task_orchestrator.py
│       ├── message_bus.py
│       └── negotiation.py
└── frontend/
    ├── css/
    │   └── dashboard.css             # Stylesheet for live dashboard
    ├── dashboard.html                # Browser visualization template
    └── js/
        └── dashboard.js              # Live dashboard interaction scripts
```

### Component Responsibilities

| Component | File | Responsibility |
|---|---|---|
| **MessageBus** | `agents/message_bus.py` | In-memory pub/sub for agent communication |
| **RobotAgent** | `agents/robot.py` | Autonomous robot: perceive → process messages → decide → act. Responds to CFPs with proposals. Broadcasts events. |
| **TaskAgent** | `agents/task.py` | Autonomous task: issues CFPs, collects proposals, awards contracts. Manages CNP lifecycle. |
| **RobotOrchestrator** | `agents/robot_orchestrator.py` | Creates and ticks all RobotAgent instances. |
| **TaskOrchestrator** | `agents/task_orchestrator.py` | Creates and ticks all TaskAgent instances. Creates TaskAgents for dynamically added tasks. |
| **SimulationEngine** | `simulation/engine.py` | Orchestration only: increments step, resets collisions, ticks task agents, ticks robot agents. No decision authority. |
| **Warehouse** | `simulation/warehouse.py` | 30×20 grid with shelves, aisles, chargers, spawn area. |
| **RobotState** | `state/robot_state.py` | Robot creation, spawning, lookup, task assignment on the data model. |
| **TaskState** | `state/task_state.py` | Task creation, assignment, unassignment, completion on the data model. |
| **AStarPathfinder** | `simulation/pathfinder.py` | A* pathfinding on the warehouse grid. |
| **CollisionManager** | `simulation/collision.py` | Per-step cell reservation. Resolves deadlocks via LLM. |
| **ChargingManager** | `simulation/charging.py` | Nearest charging station selection. |
| **NegotiationService** | `agents/negotiation.py` | Resolves pathing deadlocks using a local LLM (Ollama/Mistral) by analyzing the conflict and reasoning about priority. |

---

## 6. Simulation Engine Execution Flow

### Step Sequence (Multi-Agent Mode)

`SimulationEngine.step()` executes:

1. Increment `current_step`.
2. Print step number.
3. `collision_manager.reset_step()` — clear cell reservations.
4. `task_agent_manager.tick_all()` — each TaskAgent runs its CNP lifecycle:
   - `WAITING` → broadcast CFP → transition to `CFP_SENT`
   - `CFP_SENT` → collect proposals → evaluate → award winner → transition to `AWARDED`
   - `AWARDED` → check if task was released → if so, back to `WAITING`
5. `agent_manager.tick_all()` — each RobotAgent runs:
   - `process_messages()` — handle CFPs (submit proposals), handle awards, handle peer notifications
   - `perceive()` — update beliefs from robot state
   - `decide()` — choose action (need_charge, charge, move, pickup, deliver, idle)
   - `act()` — execute the chosen action

### Decision Flow

```text
TaskAgent                  MessageBus                RobotAgent
   │                          │                          │
   │── CFP ──────────────────►│──── CFP ────────────────►│
   │                          │                          │── evaluate eligibility
   │                          │                          │── compute bid
   │                          │◄─── PROPOSAL ────────────│
   │◄─ PROPOSAL ──────────────│                          │
   │                          │                          │
   │── evaluate proposals     │                          │
   │── select winner          │                          │
   │── assign task            │                          │
   │── TASK_AWARDED ─────────►│──── TASK_AWARDED ───────►│
   │                          │                          │── update memory
```

---

## 7. Data Models

### Position (Pydantic BaseModel)

```python
class Position(BaseModel):
    x: int
    y: int
```

### RobotStatus (str, Enum)

| Value | Used |
|---|---|
| `IDLE` | ✅ Default state, after task completion, after charging |
| `MOVING` | ✅ Navigating to pickup |
| `DELIVERING` | ✅ Carrying item, navigating to delivery |
| `CHARGING` | ✅ Low battery, navigating to/at charger |
| `WAITING` | ❌ Defined but unused |
| `PICKING` | ❌ Defined but unused |
| `NEEDS_CHARGE` | ❌ Defined but unused |

### Robot (Pydantic BaseModel)

| Field | Type | Default | Description |
|---|---|---|---|
| `id` | `int` | required | Unique identifier |
| `battery` | `float` | required | Battery percentage (0–100) |
| `position` | `Position` | required | Current (x, y) |
| `status` | `RobotStatus` | required | Current state |
| `current_task` | `int \| None` | `None` | Assigned task ID |
| `carrying_item` | `bool` | `False` | Has picked up item |
| `path` | `list` | `[]` | Planned path as (x, y) tuples |
| `delivery_path` | `list` | `[]` | Path from pickup to delivery |

### Task (dataclass)

| Field | Type | Default | Description |
|---|---|---|---|
| `id` | `int` | required | Unique identifier |
| `pickup_x` | `int` | required | Pickup X |
| `pickup_y` | `int` | required | Pickup Y |
| `delivery_x` | `int` | required | Delivery X |
| `delivery_y` | `int` | required | Delivery Y |
| `completed` | `bool` | `False` | Whether delivered |
| `assigned_robot` | `int \| None` | `None` | Assigned robot ID |

---

## 8. RobotAgent Details

### Cognitive State

| Attribute | Type | Description |
|---|---|---|
| `goal` | `str` | IDLE, PICKUP, DELIVER, CHARGE |
| `beliefs` | `dict` | Local world model (battery_low, has_task, etc.) |
| `memory` | `list[dict]` | Chronological event log |
| `current_plan` | `list[str]` | Planned micro-actions |

### Beliefs

| Key | Type | Source |
|---|---|---|
| `battery_low` | `bool` | `robot.battery <= 20` |
| `battery_full` | `bool` | `robot.battery >= 100` |
| `has_task` | `bool` | `robot.current_task is not None` |
| `carrying_item` | `bool` | `robot.carrying_item` |
| `at_destination` | `bool` | `len(robot.path) <= 1` |
| `at_charger` | `bool` | `status == CHARGING and path <= 1` |
| `path_blocked` | `bool` | next cell in collision_manager.reserved_cells |
| `nearby_low_battery` | `list[int]` | robot IDs of peers that reported low battery |
| `nearby_blocked` | `list[int]` | robot IDs of peers that reported blocked paths |

### Memory Events

| Event | When |
|---|---|
| `sent_proposal` | After submitting a CNP proposal |
| `task_awarded` | After receiving TASK_AWARDED message |
| `released_task` | After releasing task due to low battery |
| `going_to_charge` | After setting charging path |
| `fully_charged` | After battery reaches 100 |
| `picked_item` | After picking up item at pickup location |
| `delivered_task` | After delivering item at delivery location |
| `blocked` | After failing to reserve next cell |
| `arrived_at_charger` | After arriving at charging station |
| `peer_low_battery` | After receiving LOW_BATTERY from another agent |
| `peer_blocked` | After receiving BLOCKED_PATH from another agent |
| `peer_task_released` | After receiving TASK_RELEASED from another agent |

### Tick Cycle

```text
process_messages() → perceive() → decide() → act()
```

Each RobotAgent runs this cycle once per simulation step.

---

## 9. Warehouse, Pathfinding, Collision, Charging

### Warehouse Grid

- **Dimensions:** 50 × 30
- **Shelf rows:** Procedurally generated with randomized gaps (85% shelf probability).
- **Charging stations:** (0,0), (1,0), (48,0), (49,0)
- **Pillars:** 10 randomly placed isolated structural pillar blocks ("S") in aisles to create bottlenecks.
- **Robot spawn:** 25 random locations in the bottom half of the warehouse.
- **Walkable:** everything except `S` (shelves and pillars)
- **Grid access:** `grid[y][x]`

### A* Pathfinding

- Manhattan heuristic, heap-based open set, uniform edge cost (1), **explicit closed set** to prevent stale node re-expansion.
- **Pre-validation**: start and goal cells are checked for walkability before search begins.
- **Post-validation**: `_validate_path_integrity()` verifies every cell in the returned path is walkable and all consecutive steps are exactly 1 orthogonal move apart. Invalid paths are rejected and return `[]`.
- Returns list of `(x, y)` tuples from start to goal inclusive, or `[]` if no valid path.

### Collision Avoidance

- Per-step cell reservation via `reserve_cell(x, y)`.
- First robot to reserve wins; others stay in place.

### Battery & Charging

- Drain: `-1` per movement step. Idle: no drain.
- Threshold: `battery <= 20` triggers charging.
- Charge rate: `+10` per step at station. Cap: `100`.
- Nearest station by Manhattan distance.

---

## 10. FastAPI REST API

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | API health check |
| `GET` | `/dashboard` | Browser visualization |
| `GET` | `/warehouse/grid` | Warehouse grid layout |
| `GET` | `/robots` | All robot states |
| `GET` | `/tasks` | All task states |
| `GET` | `/simulation/status` | Simulation status |
| `POST` | `/simulation/step` | Execute one step |
| `POST` | `/simulation/start` | Start background loop |
| `POST` | `/simulation/pause` | Pause background loop |
| `POST` | `/simulation/reset` | Reset entire simulation |
| `POST` | `/tasks/create` | Create task + TaskAgent |
| `GET` | `/agents/status` | Robot agent introspection |
| `GET` | `/agents/messages` | Pending messages per robot |
| `GET` | `/tasks/agents` | Task agent CNP status |
| `GET` | `/auction/logs` | Raw bids from recent task auctions |
| `GET` | `/negotiation/logs` | Deadlock resolution reasons from the local LLM |

### GET /agents/status

```json
{
  "agents": [
    {
      "robot_id": 1,
      "goal": "PICKUP",
      "beliefs": {"battery_low": false, "has_task": true, ...},
      "memory_size": 12,
      "pending_messages": 0
    }
  ]
}
```

### GET /agents/messages

```json
{
  "agents": [
    {
      "robot_id": 1,
      "pending_messages": [
        {"id": 5, "sender": "task_2", "type": "CFP", "payload": {...}}
      ]
    }
  ]
}
```

### GET /tasks/agents

```json
{
  "task_agents": [
    {
      "task_id": 1,
      "status": "AWARDED",
      "winner": 3,
      "proposal_count": 4
    }
  ]
}
```

### POST /tasks/create

Automatically creates a TaskAgent for the new task. The TaskAgent will issue a CFP on the next simulation step.

---

## 11. Running the Project

### Prerequisites

- Python 3.11 (local at `python311/`)
- Packages: `fastapi`, `uvicorn`, `pydantic`, `jinja2`, `requests`
- **Ollama** running locally on port `11434` with the `mistral` model installed (required for the LLM NegotiationService).

### Start the LLM Sidecar
Ensure Ollama is running before starting the simulation:
```bash
ollama run mistral
```

### Start the API Server

```bash
python311\python.exe -m uvicorn backend.api:app --reload
```

### Access Points

| URL | Description |
|---|---|
| `http://127.0.0.1:8000/` | API root |
| `http://127.0.0.1:8000/docs` | Swagger UI |
| `http://127.0.0.1:8000/dashboard` | Live dashboard |

---

## 12. Known Limitations

- Collision avoidance is step-local only. No multi-step path reservation.
- `path.pop(0)` is O(n). Acceptable at current scale.
- Print-based logging. Will pollute API server logs.
- `constants.py` is unused.
- No persistence. Server restart loses all state.
- No WebSocket support. Dashboard uses 200ms polling.
- `AuctionManager` is retained but unused when multi-agent system is active.

---

## 13. AI Operations Centre

An enterprise-grade advanced dashboard has been introduced alongside the original visualization to provide deep observability into the Multi-Agent System.

### Access Point
| URL | Description |
|---|---|
| `http://127.0.0.1:8000/OperationCentre` | AI Operations Centre |

### New Files
- `frontend/OperationCentre.html`
- `frontend/css/OperationCentre.css`
- `frontend/js/OperationCentre.js`

### UI Features & Visualization Capabilities
The AI Operations Centre provides a complete orchestration perspective:
- **Responsive Grid Layout**: Modern, dark-themed, card-based interface with smooth micro-animations.
- **Top Header**: Real-time simulation status, active connection indicator, and high-level agent/task counts.
- **Enhanced Warehouse Visualization**: Improved CSS-grid representation of the warehouse, displaying agent IDs, dynamic battery levels via tooltips, and color-coded status animations (e.g., pulsing when negotiating).
- **Agent Inspector**: Interactive panel that displays the internal cognitive state (current goal, active task, local beliefs, pending message count, and memory event count) of any robot clicked on the grid.
- **Live Message Bus**: A real-time scrolling feed of inter-agent communications (CFPs, Proposals, Awards, Blocked Paths) with payload previews and type-specific color coding.
- **Auction Monitor**: Live tracking of Contract Net Protocol (CNP) auctions, listing all bids and identifying the winning robot and estimated cost.
- **Negotiation Logs**: Deep dive into LLM-driven conflict resolution, displaying the deadlock participants, timestamp, the LLM's reasoning, and its final decision.
- **Live Metrics**: Computed metrics for completed tasks, average swarm battery level, moving/idle breakdown, and total messages processed.

### Note for Recruiters & Reviewers
The **AI Operations Centre** perfectly demonstrates an ability to build professional, enterprise-level observability tooling. It highlights proficiency in full-stack integration (FastAPI + Vanilla JS/CSS), real-time DOM manipulation, UI/UX design (dark mode, layout grids, animations), and the capacity to visualize complex backend AI state (message passing and LLM negotiations) in an accessible, visually impressive manner.

---

## 14. LLM Configuration & Bug Resolution Notes

### Crucial Timeout Configuration
To ensure robustness during local inference (e.g., running `mistral` via Ollama on consumer hardware), **all LLM request timeouts must be configured to at least 60 seconds**.
- **Important Note for AI Models**: Any future modification to the negotiation or social greeting LLM calls must preserve the `timeout=60.0` configuration on all HTTP requests (e.g., `requests.post`). Using small/default timeouts (like 5.0 seconds) will cause `ReadTimeout` exceptions when the local model takes time to initialize or generate responses.

### Pathfinding Enforcement
- **Orthogonal Strictness**: The `AStarPathfinder` strictly enforces orthogonal movement. Robots perform immediate collision verification before each step against static obstacles. Any path attempting to clip through `S` (Shelf or Pillar) blocks is instantly aborted.

### Concurrency Throttling & Fallback Logging
- **LLM Busy States**: The `NegotiationService` implements a non-blocking `threading.Lock()` to prevent concurrency spam. If multiple robots trigger deadlocks simultaneously or request social greetings at scale (e.g., 25 robots at step 1), only one request is routed to the local LLM. The remainder instantly fallback to deterministic rule-sets (e.g., lower ID yields) without blocking or queuing.
- **Log Schema**: The negotiation and social logs returned by the API `/negotiation/logs` must match the schema expected by the AI Operations Centre frontend (`event`, `timestamp`, `reasoning`, `decision`). Mismatches will cause the frontend JavaScript to throw a `TypeError` and crash the dashboard polling loop.
- **Fail-safe Logging**: If the LLM is offline or unreachable, the service must write a fallback log entry with error details rather than failing silently, ensuring UI dashboard stability and observability.

---

## 15. Obstacle Bypass Bug — Postmortem & Rules for Future Editors

> **⚠️ READ THIS BEFORE EDITING PATHFINDING, ROBOT MOVEMENT, OR GRID RENDERING CODE.**
>
> This section documents a critical multi-layered bug that caused robots to visually clip through structural obstacles (shelves and pillars). The fix required changes across both backend and frontend. Any future modification to the files listed below **must** preserve these invariants or the bug **will** recur.

### What the Bug Looked Like

On the `/dashboard` page, robots appeared to walk directly through shelf cells (`S`) and pillar cells. The simulation did not crash but obstacle avoidance was visually broken.

### Root Causes Found (5 bugs total)

| # | Root Cause | File | Layer |
|---|-----------|------|-------|
| 1 | **A\* had no closed set** — stale heap entries caused node re-expansion, producing paths through unwalkable cells | `pathfinder.py` | Backend |
| 2 | **No start/goal validation** — A\* accepted unwalkable start/goal without error | `pathfinder.py` | Backend |
| 3 | **Only next-cell validated** — `_handle_move` checked only the immediate next cell, not the full remaining path | `robot.py` | Backend |
| 4 | **Empty charge path not handled** — `_handle_need_charge` set status to CHARGING even with empty path, causing stuck robots | `robot.py` | Backend |
| 5 | **Frontend grid never refreshed after Reset** — `gridData` was fetched once at page load; after `/simulation/reset`, the backend generated a new random warehouse but the dashboard still showed old shelf positions | `dashboard.js` | Frontend |

Bug #5 was the **primary visual cause** — robots navigated the new grid correctly, but the dashboard displayed the old grid, making valid paths appear to cross through obstacles that no longer existed in the backend.

### Fixes Applied

#### `backend/simulation/pathfinder.py`
- Added `closed_set` to A\* to prevent re-expansion of already-processed nodes.
- Added `_validate_path_integrity()` post-search check: every cell must be walkable and consecutive cells must be exactly 1 orthogonal step apart.
- Added pre-validation: `find_path()` immediately returns `[]` if start or goal cell is unwalkable.

#### `backend/agents/robot.py`
- `_handle_move()`: Validates **ALL** remaining cells in the path (not just the next cell). If any cell is unwalkable, logs `[OBSTACLE BYPASS DETECTED]` with full diagnostics and attempts path recomputation.
- `_handle_need_charge()`: Checks if `charge_path` is empty before setting status to CHARGING. If no valid path exists, stays IDLE.
- `_handle_pickup()` and `_on_arrival()`: Validates `delivery_path` is non-empty before switching. If empty, releases the task via CNP and returns to IDLE.

#### `backend/agents/task.py`
- Added diagnostic logging when pickup or delivery path computation fails during contract award.

#### `frontend/js/dashboard.js`
- Added `refreshGrid()` that re-fetches `/warehouse/grid` and rebuilds the grid DOM.
- `apiPost()` now calls `refreshGrid()` after any `/simulation/reset` request.
- `poll()` tracks `lastKnownStep` and auto-detects resets (step counter drops to 0) to refresh the grid even if reset was triggered externally.

### Critical Rules for Future AI Editors

**DO NOT** remove or weaken any of the following:

1. **A\* closed set** (`pathfinder.py`): The `closed_set` in `find_path()` is mandatory. Without it, the heap can contain stale entries that cause A\* to re-expand nodes and produce paths through obstacles.

2. **Path integrity validation** (`pathfinder.py`): `_validate_path_integrity()` must run on every path returned by A\*. It is the final safety net that catches any path containing unwalkable cells or non-orthogonal jumps.

3. **Full remaining-path validation** (`robot.py` → `_handle_move`): The movement handler must check ALL remaining cells in `robot.path`, not just the next cell. Stale paths from prior grid states can contain future cells that are now obstacles.

4. **Empty path guards** (`robot.py`): `_handle_need_charge`, `_handle_pickup`, and `_on_arrival` must all check for empty paths/delivery_paths before proceeding. Empty paths cause stuck robots or silent state corruption.

5. **Grid refresh after reset** (`dashboard.js`): `refreshGrid()` must be called after every `/simulation/reset`. The warehouse is procedurally regenerated with new random shelves/pillars on each reset. If the frontend uses stale `gridData`, robots will APPEAR to bypass obstacles.

6. **Coordinate convention**: The entire codebase uses `(x, y)` tuples for positions and paths, with `grid[y][x]` for array access. **Never swap x and y.** The full pipeline is:
   - Backend grid: `grid[y][x]`
   - `is_walkable(x, y)` checks `grid[y][x] != "S"`
   - `get_neighbors(x, y)` returns `(nx, ny)` tuples
   - A\* paths: list of `(x, y)` tuples
   - Robot position: `Position(x=x, y=y)`
   - API response: `[[x, y], ...]` for paths, `{"x": x, "y": y}` for position
   - Frontend grid: `cells[y][x]`, robot drawn at `cells[ry][rx]`
   - SVG path overlay: `p[0]` = x, `p[1]` = y

7. **`warehouse` must be in agent context** (`engine.py`): The simulation engine must inject the `warehouse` object into the agent tick context so that `_handle_move` can perform walkability checks. If `warehouse` is missing from the context dict, the full-path validation silently skips.

### Error Handling Tags

All pathfinding errors use searchable log tags:

| Tag | File | Meaning |
|-----|------|---------|
| `[PATHFINDER ERROR]` | `pathfinder.py` | A\* produced or was asked for a path through unwalkable cells |
| `[PATHFINDER WARNING]` | `pathfinder.py` | A\* found no valid path between two points |
| `[OBSTACLE BYPASS DETECTED]` | `robot.py` | A robot's stored path contained an unwalkable cell at runtime |
| `[OBSTACLE BYPASS RECOVERY]` | `robot.py` | Path was successfully recomputed around the obstacle |
| `[OBSTACLE BYPASS RECOVERY FAILED]` | `robot.py` | No alternative path exists — robot stops |
| `[CHARGE ERROR]` | `robot.py` | No valid path to any charging station |
| `[DELIVERY PATH ERROR]` | `robot.py` | Delivery path was empty when robot tried to switch to it |
| `[TASK AGENT WARNING]` | `task.py` | Path computation failed during task contract award |
| `[GRID REFRESH]` | `dashboard.js` | Frontend re-fetched warehouse grid after reset |
| `[RESET DETECTED]` | `dashboard.js` | Frontend detected simulation step counter dropped (auto-refresh) |
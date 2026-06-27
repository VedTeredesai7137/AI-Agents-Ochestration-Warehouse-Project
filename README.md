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
FastAPI REST API (simulation/api.py)
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

File: `simulation/message_bus.py`

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
├── simulation/
│   ├── __init__.py                   # Package marker
│   ├── api.py                        # FastAPI app with multi-agent integration
│   ├── agent_manager.py              # Manages RobotAgent instances
│   ├── auction_manager.py            # Legacy centralized auction (kept for compat)
│   ├── charging_manager.py           # Charging station selection
│   ├── collision_manager.py          # Per-step collision avoidance
│   ├── constants.py                  # Shared constants (unused)
│   ├── main.py                       # Console simulation runner
│   ├── message_bus.py                # In-memory agent communication bus
│   ├── models.py                     # Pydantic models (Robot, Position, RobotStatus)
│   ├── pathfinder.py                 # A* pathfinding
│   ├── robot_agent.py                # Autonomous robot agent (perceive-decide-act + CNP)
│   ├── robot_manager.py              # Robot lifecycle management
│   ├── simulation_engine.py          # Orchestration engine (no decision authority)
│   ├── task_agent.py                 # Autonomous task agent (CNP lifecycle)
│   ├── task_agent_manager.py         # Manages TaskAgent instances
│   ├── task_manager.py               # Task data management
│   ├── warehouse.py                  # Grid generation
│   └── templates/
│       └── dashboard.html            # Browser visualization
```

### Component Responsibilities

| Component | File | Responsibility |
|---|---|---|
| **MessageBus** | `message_bus.py` | In-memory pub/sub for agent communication |
| **RobotAgent** | `robot_agent.py` | Autonomous robot: perceive → process messages → decide → act. Responds to CFPs with proposals. Broadcasts events. |
| **TaskAgent** | `task_agent.py` | Autonomous task: issues CFPs, collects proposals, awards contracts. Manages CNP lifecycle. |
| **AgentManager** | `agent_manager.py` | Creates and ticks all RobotAgent instances. |
| **TaskAgentManager** | `task_agent_manager.py` | Creates and ticks all TaskAgent instances. Creates TaskAgents for dynamically added tasks. |
| **SimulationEngine** | `simulation_engine.py` | Orchestration only: increments step, resets collisions, ticks task agents, ticks robot agents. No decision authority. |
| **Warehouse** | `warehouse.py` | 30×20 grid with shelves, aisles, chargers, spawn area. |
| **RobotManager** | `robot_manager.py` | Robot creation, spawning, lookup, task assignment on the data model. |
| **TaskManager** | `task_manager.py` | Task creation, assignment, unassignment, completion on the data model. |
| **AuctionManager** | `auction_manager.py` | **Legacy.** Retained for backward compatibility. Not used when multi-agent system is active. |
| **AStarPathfinder** | `pathfinder.py` | A* pathfinding on the warehouse grid. |
| **CollisionManager** | `collision_manager.py` | Per-step cell reservation. Resolves deadlocks via LLM. |
| **ChargingManager** | `charging_manager.py` | Nearest charging station selection. |
| **NegotiationService** | `negotiation_service.py` | Resolves pathing deadlocks using a local LLM (Ollama/Mistral) by analyzing the conflict and reasoning about priority. |

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

- **Dimensions:** 30 × 20
- **Shelf rows:** Procedurally generated along rows 2, 5, 8, 11, 14, 17 with randomized gaps (85% shelf probability).
- **Charging stations:** (0,0), (1,0), (28,0), (29,0)
- **Robot spawn:** 5 random locations in the bottom half of the warehouse.
- **Walkable:** everything except `S` (shelves)
- **Grid access:** `grid[y][x]`

### A* Pathfinding

- Manhattan heuristic, heap-based open set, uniform edge cost (1).
- Returns list of `(x, y)` tuples from start to goal inclusive, or `[]` if no path.

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
python311\python.exe -m uvicorn simulation.api:app --reload
```

### Access Points

| URL | Description |
|---|---|
| `http://127.0.0.1:8000/` | API root |
| `http://127.0.0.1:8000/docs` | Swagger UI |
| `http://127.0.0.1:8000/dashboard` | Live dashboard |

---

## 12. Known Limitations

- No explicit closed set in A*. Relies on `g_score` for pruning.
- Collision avoidance is step-local only. No multi-step path reservation.
- `path.pop(0)` is O(n). Acceptable at current scale.
- Print-based logging. Will pollute API server logs.
- `constants.py` is unused.
- No persistence. Server restart loses all state.
- No WebSocket support. Dashboard uses 200ms polling.
- `AuctionManager` is retained but unused when multi-agent system is active.
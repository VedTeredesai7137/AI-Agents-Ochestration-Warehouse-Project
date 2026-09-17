# Warehouse Swarm Project

## 1. Executive Summary

**Warehouse Swarm Project** is a Python-based multi-agent warehouse simulation with a FastAPI backend and a live browser-based visualization dashboard. It demonstrates how multiple autonomous robot agents and task agents communicate through a message bus, negotiate task allocation via the **Contract Net Protocol (CNP)**, navigate with A* pathfinding, avoid collisions, manage battery and charging behavior, and respond to dynamic task injection during runtime.

The system consists of:

- A **multi-agent simulation core** — autonomous RobotAgents and TaskAgents communicate via a MessageBus. TaskAgents issue Calls for Proposals (CFPs), RobotAgents submit bids (PROPOSALs), and TaskAgents award contracts (TASK_AWARDED). No centralized controller makes allocation decisions.
- A **FastAPI REST API** — exposes simulation state (robots, tasks, agents, messages), provides simulation control (step, start, pause, reset), and accepts dynamic task creation.
- A **browser dashboard** — a Jinja2-rendered HTML/CSS/JS page at `/dashboard` that visualizes the warehouse grid in real-time by polling the API every 200ms. It features live bidding logs, agent thought streams, and path intent overlays.

The simulation runs in-memory. All state lives in Python objects. There is no database or external message broker. Agent messages and the FIFO crisis queue are held in memory. The warehouse environment (shelves, robot spawns, and tasks) is **procedurally generated** at startup and upon every simulation reset using a run-scoped random generator. Resetting with the same seed reproduces the initial environment; the agents do not train or learn model weights.

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
estimated_cost = pickup_itinerary_cost + delivery_itinerary_cost + max(0, 20 - final_energy_margin) * 0.1
```

### Robot Eligibility for Bidding

A RobotAgent submits a proposal only if:
- For normal CFPs, `current_task is None`. CRITICAL emergency CFPs can preempt an ordinary task through safe release; an existing CRITICAL task is not preempted.
- `battery >= 30`.
- Status is neither `CHARGING`, `NEEDS_CHARGE`, nor `NEGOTIATING`.
- No active crisis pin, HOLD, or YIELD timer.

Both RobotAgent bidding and TaskAgent awarding check reachable, energy-feasible
pickup and loaded delivery itineraries, including real charging stops where needed.
Each movement to a stop must fit the available battery plus a 5-unit reserve.
At pickup, reserve enough energy to reach a charger **loaded**; after delivery,
reserve enough to reach one empty. A long task need not fit one battery, but its
individual legs must. No task is shortened and no parcel is teleported.

Itinerary cost estimates movement ticks + recharge ticks (`energy added / 10`) +
12 ticks per existing inbound charging robot at each proposed stop. The final
margin is energy at delivery minus empty return-to-charger energy minus 5.
Bids are ordered by cost, then robot ID. TaskAgent rechecks candidates in order;
if an earlier auction already took the cheapest bidder, it tries the next eligible
bidder in the same auction. Allocation remains decentralized CNP.

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

File: `backend/agents/message_bus.py`

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
| Charging begins after reserve/feasibility checks | `LOW_BATTERY` | During safe transition to charging |
| Path cell is blocked | `BLOCKED_PATH` | During `move` action (cell already reserved) |
| Task is safely released | `TASK_RELEASED` | Charging, critical preemption, or orchestrator reassignment |

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
│   │   ├── constants.py
│   │   └── llm_config.py             # Environment-based Ollama model selection
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
│       ├── negotiation.py
│       └── orchestrator_graph.py     # LangGraph crisis orchestrator
└── frontend/
    ├── css/
    │   ├── dashboard.css             # Stylesheet for live dashboard
    │   └── OperationCentre.css       # Stylesheet for AI Operations Centre
    ├── dashboard.html                # Browser visualization template
    ├── OperationCentre.html          # AI Operations Centre template
    └── js/
        ├── dashboard.js              # Live dashboard interaction scripts
        └── OperationCentre.js        # Operations Centre interaction scripts
```

### Backend hardening additions

The repository tree above shows the original layout. These modules extend it:

```text
backend/core/settings.py              # Validated run configuration
backend/core/events.py                # Bounded structured events and counters
backend/agents/plans.py                # Strict executable action schema/parser
backend/agents/llm_client.py           # Ollama boundary and fault clients
backend/agents/plan_validator.py       # Copied-state safety validation
backend/agents/action_executor.py      # Staged execution and fallback
backend/simulation/factory.py          # Shared seeded construction
backend/evaluation/                   # Scenarios, metrics, CLI runner
run_benchmark.py                      # Bundled-Python benchmark entry point
tests/                                # Backend and frontend regression tests
pytest.ini
requirements-dev.txt
.env.example
```

### Component Responsibilities

| Component | File | Responsibility |
|---|---|---|
| **MessageBus** | `agents/message_bus.py` | In-memory pub/sub for agent communication |
| **RobotAgent** | `agents/robot.py` | Autonomous robot: process messages → perceive → decide → act. Responds to CFPs with proposals. Broadcasts events. |
| **TaskAgent** | `agents/task.py` | Autonomous task: issues CFPs, collects proposals, awards contracts. Manages CNP lifecycle. |
| **RobotOrchestrator** | `agents/robot_orchestrator.py` | Creates and ticks all RobotAgent instances. |
| **TaskOrchestrator** | `agents/task_orchestrator.py` | Creates and ticks all TaskAgent instances. Creates TaskAgents for dynamically added tasks. |
| **SimulationEngine** | `simulation/engine.py` | Ticks task agents before robot agents, handles seeded crisis injection, and delegates exceptional recovery to the validated orchestrator or deterministic fallback. |
| **Warehouse** | `simulation/warehouse.py` | Default API/evaluation warehouse: 50×30 grid with shelves, aisles, chargers, and a 40-robot depot. |
| **RobotState** | `state/robot_state.py` | Robot creation, spawning, lookup, task assignment on the data model. |
| **TaskState** | `state/task_state.py` | Task creation, assignment, unassignment, completion on the data model. |
| **AStarPathfinder** | `simulation/pathfinder.py` | A* pathfinding on the warehouse grid. |
| **CollisionManager** | `simulation/collision.py` | Occupied-cell checks and per-step reservations; the engine escalates persistent deadlocks. |
| **ChargingManager** | `simulation/charging.py` | Energy-feasible charging itineraries, available-bay selection, and bounded static distance/route caches. |
| **NegotiationService** | `agents/negotiation.py` | Bounded UI-compatible logs and deterministic routine explanations; exceptional model decisions use the crisis graph. |
| **OrchestratorGraph** | `agents/orchestrator_graph.py` | LangGraph-based crisis orchestrator. Runs a deliberative state machine (diagnose → plan → validate → execute) with HITL interrupt and rejection feedback loop. |

---

## 6. Simulation Engine Execution Flow

### Step Sequence (Multi-Agent Mode)

`SimulationEngine.step()` executes:

1. Increment `current_step`.
2. Record the step at DEBUG level and trigger a periodic collapse when configured.
3. `collision_manager.reset_step(robot_manager.robots)` — clear reservations and snapshot occupied cells.
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
| `NEEDS_CHARGE` | Used when charging or movement cannot proceed safely because of energy/route constraints |
| `NEGOTIATING` | Compatibility state; excluded from bidding |

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
| `hold_steps_remaining` | `int` | `0` | Remaining intentional HOLD ticks |
| `yield_to_robot_id` | `int \| None` | `None` | Robot given temporary priority |
| `yield_steps_remaining` | `int` | `0` | Remaining stationary YIELD ticks |
| `orchestration_holds` | `set[str]` | empty | Only the currently active crisis ID may pin this robot; pending requests never do |
| `route_waypoint` | `tuple[int,int] \| None` | `None` | Reroute constraint retained until visited |

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
| `priority` | `str` | `NORMAL` | CNP priority, including CRITICAL preemption |
| `created_step` | `int` | `0` | Simulation creation timestamp |
| `assigned_step` | `int \| None` | `None` | Latest award timestamp |
| `completed_step` | `int \| None` | `None` | Completion timestamp |
| `reauction_count` | `int` | `0` | Number of actual ownership releases |

---

## 8. RobotAgent Details

### Cognitive State

| Attribute | Type | Description |
|---|---|---|
| `goal` | `str` | IDLE, PICKUP, DELIVER, CHARGE |
| `beliefs` | `dict` | Local world model (battery_low, has_task, etc.) |
| `memory` | bounded `deque[dict]` | Recent chronological agent events |
| `current_plan` | `list[str]` | Planned micro-actions |

### Beliefs

| Key | Type | Source |
|---|---|---|
| `battery_low` | `bool` | Unowned robots recharge at reachable charger distance + 5, or below the 30-unit bidding floor. Owned tasks use planned charging stops; charging failure remains a safe stopped state. |
| `battery_full` | `bool` | `robot.battery >= 100` |
| `has_task` | `bool` | `robot.current_task is not None` |
| `carrying_item` | `bool` | `robot.carrying_item` |
| `at_destination` | `bool` | `len(robot.path) <= 1` |
| `at_charger` | `bool` | Current cell is an actual warehouse charging station (`C`) |
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
- **Charging stations:** eight separated bays: x=12/37 at y=1/10/22/28. These use cross-aisle floor cells; they replace the four adjacent top-corner stations.
- **Pillars:** 10 randomly placed isolated structural pillar blocks ("S") in aisles to create bottlenecks.
- **Robot spawn:** 40 robots in the existing bottom-center depot (10 by 4 cells).
- **Walkable:** everything except `S` (shelves and pillars)
- **Grid access:** `grid[y][x]`

### A* Pathfinding

- Manhattan heuristic, heap-based open set, uniform edge cost (1), **explicit closed set** to prevent stale node re-expansion.
- **Pre-validation**: start and goal cells are checked for walkability before search begins.
- **Post-validation**: `_validate_path_integrity()` verifies every cell in the returned path is walkable and all consecutive steps are exactly 1 orthogonal move apart. Invalid paths are rejected and return `[]`.
- Returns list of `(x, y)` tuples from start to goal inclusive, or `[]` if no valid path.

### Collision Avoidance

- Per-step cell reservation via `reserve_cell(x, y)`.
- Occupied cells and per-step reservations block conflicting moves, including stationary robots and edge swaps. Active YIELD targets are ticked first; otherwise robot-ID order is deterministic.

### Battery & Charging

- Drain remains **1 unit per empty movement, 2 while carrying**. Idle/HOLD consume no energy.
- Rate remains **+10 per simulation tick**, only at a real `C` cell; battery remains 0..100. Charging speed was already sufficient; travel and blocked entrances were the bottleneck.
- CNP checks feasible pickup/delivery itineraries through charging stops, with a **5-unit planning reserve**. Tasks that exceed one battery can stop at a charger while retaining ownership and the parcel, then resume pickup/delivery.
- Unowned robots seek charging at `nearest reachable charger distance + 5`, or below the existing 30-unit bidding floor. An owned feasible task is not dropped merely because battery crosses a fixed threshold.
- Normal charger selection excludes occupied/already-inbound bays when choosing a new stop. If no feasible available bay exists, the robot waits/retries; deterministic congestion recovery remains available. This is lightweight admission, not a global time-slot reservation system.
- Every actual move also checks that the remaining energy can reach a charger. Traffic detours cannot spend the last escape energy. If necessary, the robot replans a charging leg; impossible movement stops safely.
- Charge completion resumes an owned task. Explicit `GO_TO_CHARGER`, critical preemption, and exceptional safe release still use the existing CNP release mechanism, preserving the parcel's current pickup location.
- Full robots leave service cells. Idle robots also clear nearby passing space around blocked episodes, including episodes whose fallback temporarily cleared their path.
- Existing A* generates movement routes. Bounded revision-keyed distance fields accelerate energy/bid estimates; they do not bypass full remaining-path validation, occupied cells, or step reservations.

---

## 10. FastAPI REST API

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | API health check |
| `GET` | `/dashboard` | Browser visualization |
| `GET` | `/OperationCentre` | Orchestration and agent dashboard |
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
| `GET` | `/agents/message-history` | Bounded published-message history for the frontend feed |
| `GET` | `/tasks/agents` | Task agent CNP status |
| `GET` | `/auction/logs` | Raw bids from recent task auctions |
| `GET` | `/negotiation/logs` | CNP explanations, greetings, and crisis execution summaries |
| `GET` | `/orchestrator/state` | Current LangGraph orchestrator status, plan, and HITL state |
| `POST` | `/orchestrator/override` | Accept/reject a valid review plan using its current `plan_id` |
| `POST` | `/simulation/crisis` | Inject a safe collapse using optional selected cells |
| `GET` | `/orchestrator/events` | Filter bounded structured orchestration events |

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
- Install runtime packages with `python311\python.exe -m pip install -r requirements.txt` (includes FastAPI, Pydantic, and LangGraph).
- **Ollama** on port `11434` with the selected model installed enables live inference. The backend also runs without Ollama using logged deterministic fallback. Tests and injected-fault demos do not require Ollama.

### Select the Local LLM Provider

Set `LLM_Provider` in the project `.env` file. The setting is read when the backend starts and is used by the LangGraph crisis orchestrator through `OllamaClient`.

```dotenv
# Use Mistral
LLM_Provider=mistral

# Or use Gemma 4 12B
# LLM_Provider=gemma
```

Provider mappings:

| `LLM_Provider` value | Ollama model |
|---|---|
| `mistral` | `mistral:latest` |
| `gemma` | `gemma4:12b` |

Use one active `LLM_Provider` line at a time. Restart the API server after changing the value because the selected model is loaded during backend startup.

### Start the LLM Sidecar
For live model-assisted orchestration, start Ollama:
```bash
ollama serve
```

The configured model must already be available locally. To keep a model loaded, you may also run `ollama run mistral` or `ollama run gemma4:12b` in a separate terminal.

### Start the API Server

```bash
python311\python.exe -m uvicorn backend.api:app --app-dir . --reload
```

### Access Points

| URL | Description |
|---|---|
| `http://127.0.0.1:8000/` | API root |
| `http://127.0.0.1:8000/docs` | Swagger UI |
| `http://127.0.0.1:8000/dashboard` | Live dashboard |
| `http://127.0.0.1:8000/OperationCentre` | Agent and orchestration dashboard |

---

## 12. Known Limitations

- Collision avoidance is step-local only. No multi-step path reservation. The crisis validator adds a read-only short-horizon prediction, described below.
- `path.pop(0)` is O(n). Acceptable at current scale.
- Orchestration uses structured Python logging; some legacy pathfinding diagnostics retain searchable console tags.
- `constants.py` is unused.
- No persistence. Server restart loses all state.
- No WebSocket support. Dashboard uses 200ms polling.
- `AuctionManager` is retained but unused when multi-agent system is active.

---

## 13. AI Operations Centre

An operations dashboard is provided alongside the original visualization to provide deep observability into the Multi-Agent System.

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
- **Negotiation Logs**: Timestamped CNP explanations, deterministic greetings, and crisis execution summaries. The orchestrator panel separately shows model-authored actions and reasons.
- **Live Metrics**: Computed metrics for completed tasks, average swarm battery level, moving/idle breakdown, and total messages processed.

### Engineering focus

The dashboard exposes CNP messages, task awards, robot state, and validated crisis
orchestration. It is a local research/demo UI, backed by the tests and evaluation
commands below. The frontend remains a polling-based vanilla JavaScript app.

---

## 14. LLM Configuration & Bug Resolution Notes

### Provider Selection

The backend centralizes Ollama configuration in `backend/core/llm_config.py`:

- `LLM_Provider=mistral` selects the installed `mistral:latest` model.
- `LLM_Provider=gemma` selects the installed `gemma4:12b` model.
- Provider names are case-insensitive and default to `mistral` when omitted.
- `OLLAMA_URL` may optionally override the default endpoint `http://localhost:11434/api/generate`.

Changing `.env` does not change an already-running process. Restart Uvicorn after switching providers.

### Crucial Timeout Configuration
To ensure robustness during local inference (e.g., running `mistral:latest` or `gemma4:12b` via Ollama on consumer hardware), **all LLM request timeouts must be configured to at least 60 seconds**.
- **Important Note for AI Models**: Any future modification to the exceptional orchestration LLM calls must preserve the `timeout=60.0` configuration on all HTTP requests (e.g., `requests.post`). Using small/default timeouts (like 5.0 seconds) will cause `ReadTimeout` exceptions when the local model takes time to initialize or generate responses.

### Pathfinding Enforcement
- **Orthogonal Strictness**: The `AStarPathfinder` strictly enforces orthogonal movement. Robots perform immediate collision verification before each step against static obstacles. Any path attempting to clip through `S` (Shelf or Pillar) blocks is instantly aborted.

### Exceptional inference and logging

Routine auction explanations and social greetings are deterministic templates.
LLM calls are reserved for structural crises and persistent reciprocal robot
blockage. `NegotiationService` retains the UI log schema (`event`, `timestamp`,
`reasoning`, `decision`); the structured orchestrator owns model decisions.
Each simulation has one daemon graph worker and a FIFO crisis queue. Inference
holds neither the simulation lock nor the runner lock. See Section 17.

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
- `_handle_need_charge()`: Checks if `charge_path` is empty before setting status to CHARGING. If no valid path exists, stops in NEEDS_CHARGE and preserves ownership.
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

5. **Grid refresh after reset** (`dashboard.js`): `refreshGrid()` must be called after every `/simulation/reset`. The warehouse is procedurally regenerated on reset; the selected seed determines shelves and pillars. If the frontend uses stale `gridData`, robots will APPEAR to bypass obstacles.

6. **Coordinate convention**: The entire codebase uses `(x, y)` tuples for positions and paths, with `grid[y][x]` for array access. **Never swap x and y.** The full pipeline is:
   - Backend grid: `grid[y][x]`
   - `is_walkable(x, y)` checks `grid[y][x] != "S"`
   - `get_neighbors(x, y)` returns `(nx, ny)` tuples
   - A\* paths: list of `(x, y)` tuples
   - Robot position: `Position(x=x, y=y)`
   - API response: `[[x, y], ...]` for paths, `{"x": x, "y": y}` for position
   - Frontend grid: `cells[y][x]`, robot drawn at `cells[ry][rx]`
   - SVG path overlay: `p[0]` = x, `p[1]` = y

7. **`warehouse` must be in agent context** (`engine.py`): The simulation engine must inject the `warehouse` object into the agent tick context so that `_handle_move` can perform walkability checks. The current movement handler additionally calls the pathfinder integrity validator directly, so missing optional context cannot silently skip path validation.

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

---

## 16. Controlled Chaos & Stress Testing

To rigorously test the multi-agent negotiation layers, deadlock resolution, and emergency handling, the simulation incorporates intentional "controlled chaos" mechanisms. These features dramatically increase swarm density and system stress, forcing agents to constantly adapt.

### Chaos Mechanisms Injected

1. **Massive Workload Overload**
   - **120 Initial Tasks**: The simulation boots with 120 procedurally generated tasks (up from 50), immediately saturating the swarm and triggering extensive Contract Net Protocol (CNP) bidding wars.
   - **Aggressive Battery Drain**: Robots carrying items now consume 2 battery units per step (instead of 1). Loaded movement retains the 2x energy cost. Planned charging stops avoid predictable mid-task drops.

2. **The "Depot" Spawn Choke Point**
   - Instead of distributing the 40 robots randomly across the bottom of the warehouse, they are exclusively spawned inside a dense 10x4 contiguous block in the bottom-center (Rows 25-28, Cols 20-30).
   - This intentional bottleneck forces immediate, massive traffic jams at Step 1, rigorously stress-testing the step-local collision manager and deterministic three-strike recovery. Only persistent unresolved reciprocal contention escalates to the LLM.

3. **Finite Demo Crisis Schedule (Aisle Collapses)**
   - **Normal schedule**: up to **3** automatic collapses, attempted every **200** steps (normally 200, 400, 600). `CRISIS_INTERVAL` and `AUTOMATIC_CRISIS_LIMIT` configure this; no automatic injection after task completion.
   - **Backpressure**: A scheduled collapse is skipped when active/pending structural orchestration exists or the pending queue is full. The next normal interval retries; skipped injections do not accumulate.
   - **Targeting**: three contiguous floor cells, biased toward central rows 10-20. Automatic selection excludes unfinished pickup/delivery cells and checks that robots, endpoints, and chargers retain structural connectivity. Manual selected-cell injection remains available and can create unrecoverable scenarios.

4. **Emergency Critical Orders**
   - Tasks can be dynamically injected with a `CRITICAL` priority flag.
   - TaskAgents broadcast `EMERGENCY_CFP`, permitting busy robots to bid, drop their current normal priority tasks, and immediately route to the emergency pickup.

5. **3-Strike Deadlock Protocol & Observability**
   - Robots track failed cell reservations via `blocked_counter`.
   - **Strike 3**: Records a blocked episode and attempts deterministic recovery. It never calls the LLM directly. After both robots have attempted recovery, six further reciprocal failed-movement ticks can escalate the same unresolved pair (see Section 17).
   - **Dashboard Chaos Metric**: The `dashboard.js` polling loop actively parses API statuses for `total_strikes` and outputs a `[CHAOS METRIC]` directly to the frontend console, providing visual proof of system stress. Banners and pulsing grid cells visually highlight these critical disruptions in real-time.

> **Normal demo rule**: retain 40 robots, 120 tasks, CNP, energy, and physical safety. Use only 2-3 automatic structural crises. Explicit stress configurations may raise the finite crisis limit and shorten the interval.

---

## 17. Structured Crisis Orchestration

The LLM selects **executable actions**. Deterministic services validate and execute
them. Routine CNP allocation, A*, movement, collision checks, and batteries remain
outside inference. `SimulationEngine.step()` still ticks TaskAgents before
RobotAgents; the crisis layer does not centrally award ordinary tasks.

### Local models: fast deterministic layer, slow emergency manager

Local Ollama is the only inference provider. The installed models are
`mistral:latest` (about 4.4 GB) and `gemma4:12b` (about 7.6 GB), selected through
`LLM_Provider=mistral` or `LLM_Provider=gemma`. They are intentionally treated as
slow strategic models: one request may span hundreds or thousands of simulation
ticks. There are no cloud fallback or API-key assumptions. Ollama metadata reports 7.2B parameters for the installed Mistral model and
11.9B for Gemma. The model tags are the authoritative selection identifiers.

The fast layer runs every tick: CNP, RobotAgents, A*, occupancy reservations,
charging, path invalidation, and deterministic recovery. The slow layer runs
LangGraph, structured plan generation, validation, HITL, execution, and fallback
only for exceptional incidents. Ollama retains its 60-second request timeout;
inference holds neither the simulation lock nor the runner lock. Unrelated robots
keep moving, bidding, completing tasks, and charging during inference.

**Exact deadlock escalation rule:**

1. A robot's third consecutive failed reservation attempts deterministic recovery.
   Non-movement actions reset its strike counter. Three strikes never call Ollama.
2. At the end of each tick, normalize the pair as `(min(id_a,id_b), max(id_a,id_b))`.
   Count only ticks where both robots actually failed to enter each other's
   occupied cell while executing tasks. Old blocked counters alone are insufficient.
3. Remember that each participant attempted deterministic recovery, even when their
   third strikes happen on different ticks. After both attempts, require **six
   additional reciprocal failed-movement ticks** (`DEADLOCK_PERSISTENCE_STEPS=6`).
   In the uninterrupted case the earliest escalation is tick 9 of the blockage.
4. Short recovery HOLD/replan pauses preserve the episode but add **zero** to its
   persistence count. Activation also requires both robots still eligible to move,
   with reciprocal next cells and no intentional holds. Charging, idle/no-task,
   HOLD, YIELD, and active crisis pins cannot create contention evidence.
5. Movement by either robot clears the pair episode immediately. Changed tasks or
   a different blocker during observation invalidate it. Submission is latched for
   that incident: completion or a temporary hold alone cannot submit it again.

This is a deliberately narrow detector for reciprocal pairs, not a general solver
for every multi-robot traffic cycle.

**Queue admission and backpressure:**

- Crisis kinds are `DEADLOCK` and `STRUCTURAL_COLLAPSE`.
- `ORCHESTRATOR_MAX_PENDING_CRISIS=5` limits pending work, in addition to one active
  crisis. This remains a process-local `deque`.
- Same-pair active/pending requests return the existing crisis ID and log
  `[CRISIS_QUEUE][DEDUPED]`. They never create duplicate entries or holds.
- Before admission and at dequeue, stale deadlocks are dropped. Checks include
  episode identity, existing robots, unchanged positions/tasks, recent reciprocal
  failures, and current movement intent. A last-completed-tick snapshot prevents
  beginning-of-tick queue checks from accidentally erasing valid evidence.
- Immediately before inference, the active deadlock is checked again; its own
  orchestration pin is excluded from that check. Stale work calls no Ollama.
- A full queue logs `[CRISIS_QUEUE][BACKPRESSURE]` and rejects admission without
  adding holds. Deterministic recovery remains available. The rejected pair is
  latched until a new incident begins, avoiding repeated admission spam.
- Periodic collapses use `CRISIS_INTERVAL=200` and `AUTOMATIC_CRISIS_LIMIT=3`.
  Active/pending structural work or a full queue skips that injection with `[CRISIS][PERIODIC_SKIPPED]` and reason
  `ORCHESTRATOR_BACKPRESSURE`; the next interval retries while below the finite limit.
- Manual structural injections still apply safe obstacle/path updates. If admission
  is full, they use deterministic recovery. Pending structural requests are not
  coalesced and are not discarded solely because some robots have already moved.

**Hold lifecycle and immediate safety:**

Queued requests never freeze robots. At activation, and only then, the request's
ID is added to its affected robots. Success, exhausted regeneration, model/network
failure, HITL timeout, execution/startup failure, cancellation, and reset all
release that ID. Final cleanup clears the active session even if completion logging
fails. A late cancelled worker cannot mutate a newer session.

Structural cells become `S` under the simulation lock. Affected remaining and
delivery paths are immediately replanned through existing A*, before any LLM wait.
Full remaining-path validation and occupancy checks still guard every movement.
Deterministic recovery for another incident cannot mutate a robot pinned by the
active crisis.

### Flow

```text
Crisis or persistent reciprocal deadlock
  -> bounded queue (robots continue deterministic operation)
  -> revalidate head request; discard resolved deadlocks
  -> activate and pin only the active crisis's affected robots
  -> diagnose -> generate JSON -> parse/Pydantic schema -> safety validation
       invalid -> bounded regeneration -> deterministic fallback if exhausted
       valid, no warnings, score >= threshold -> auto-execution policy
       other valid plan -> interrupt before execute -> operator review
           approve -> live validation -> execute
           reject -> generate a different strategy -> validate again
  -> completion -> release this crisis's pins -> start next queued crisis
```

`MemorySaver` and `interrupt_before=["execute"]` are retained. Each crisis owns
its graph/checkpointer, discarded after completion. The rejection edge explicitly
routes `human_approved=False` to `generate_plan`. There are at most
`1 + ORCHESTRATOR_MAX_REGENERATIONS` model requests per crisis (default **3 total**).
Human rejections share this budget. A change to reasons or action order alone
cannot disguise the same rejected strategy.

**Malformed or unsafe plans never enter HITL approval.** Exhaustion, unavailable
Ollama, timeout, stale approval, and failed execution activate deterministic
fallback. Operator inactivity also expires after 300 seconds by default, so a
forgotten review cannot block the queue forever.

### Strict action schema

`backend/agents/plans.py` defines `ActionType`, `RobotAction`, `CrisisPlan`, and
`ValidationReport`. Unknown fields/actions, duplicate JSON fields, non-integer
IDs/coordinates, missing fields, and parameters belonging to another action are
rejected. The parser accepts an accidental enclosing Markdown JSON fence.

Example **schema shape** (IDs and coordinates still require world validation):

```json
{
  "actions": [
    {"robot_id": 1, "action": "REROUTE", "waypoint": {"x": 2, "y": 3}, "reason": "Use the adjacent aisle"},
    {"robot_id": 2, "action": "HOLD", "hold_steps": 3, "reason": "Allow congestion to clear"}
  ],
  "rationale": "Separate the affected robots temporarily"
}
```

| Action | Required parameter | Actual simulator effect |
|---|---|---|
| `HOLD` | `hold_steps` (1..configured max, default 10) | Remains stationary for exactly that many subsequent robot ticks; no movement battery cost. Keeps task and route. |
| `YIELD` | `yield_to_robot_id` | Stays stationary for 3 ticks by default. The target gets first reservation opportunity. Cannot yield to self or form a cycle; holding in the target's immediate path is rejected. |
| `REROUTE` | `waypoint: {x,y}` | Installs `A*(position, waypoint) + A*(waypoint, true destination)`. Preserves the waypoint constraint during stale-path recovery until visited; task destinations come from task state. |
| `REASSIGN_TASK` | `task_id` | Releases the task owned by this robot. If carrying, the parcel's new pickup is the robot's current cell. TaskAgent returns to WAITING, then broadcasts a fresh CFP. No winner is assigned by the LLM. |
| `GO_TO_CHARGER` | none | Calls RobotAgent charging logic with a reachable `C` path supplied by ChargingManager. Preflights energy before release. A current task is safely released and its parcel location preserved. |

New actions replace prior temporary hold/yield controls. Multiple actions for one
robot are invalid. Every affected robot must have an action. Other robots may be
included, but their ownership/destination must still match the inference snapshot
at execution.

### Validation and score

The validator takes copied warehouse, robot, and task state. It checks:

- Existing robots, one action per robot, complete affected-robot coverage.
- Action parameters, hold limits, valid yield target and acyclic yielding.
- Bidirectional task ownership, unfinished tasks, and safe release conditions.
- In-bounds walkable waypoints, reachable route legs, real reachable chargers.
- Task pickup/delivery legs and the empty return to a charger.
- Movement energy (1 empty / 2 loaded), return energy, and initial charge preemption.
- Routes through known crisis cells, immediate conflicts, and future contention.

The score is **execution readiness**, with no random component. Five groups have
equal weight **0.20**: `valid_action_ratio`, `reachable_route_ratio`,
`battery_feasibility_ratio`, `task_consistency_ratio`, `collision_safety_ratio`.
For each action/group: pass = 1, warning = 0.8, error = 0. Each group averages over
actions; the weighted sum is rounded to four decimals. Missing coverage caps the
score at 0.8. **An ERROR always blocks execution regardless of score.**

Auto-execution requires `valid=True`, **no warnings**, and
`validation_score >= ORCHESTRATOR_AUTO_EXECUTE_THRESHOLD` (default **0.85**).
Any warning requires HITL even if the numerical score exceeds the threshold.
Examples: long holds, task re-auctions, narrow battery margins, and predicted
future contention. Scores are not probabilities of successful recovery.

The executor repeats validation under the simulation lock. Changed task ownership
or destination, newly introduced warnings after operator review, and newly invalid
routes stop execution and trigger fallback. Auto-approval is recorded separately
from human approval. Model output is never treated as executable code.

### Shadow prediction: scope and limits

The validator projects existing/proposed paths over **5 ticks** by default.
HOLD/YIELD delay a robot's route; contiguous pickup routes continue into delivery legs.
Charging trajectories stop at the current bay; retained task delivery is not spliced across a bay/pickup gap.
Immediate vertex collisions and swaps are errors; later conflicts are warnings
because runtime reservations can delay robots. Task release is held stationary in
prediction and explicitly requires review because the next CNP owner is unknown.

This is **not a cloned simulation**. It does not predict future auctions, future
collapses, all reactive battery decisions, or whether a congested/disconnected
warehouse will eventually recover. Actual movement still validates the complete
remaining path and enforces physical occupancy each step.

### Mutation, fallback, and concurrency

`ActionExecutor` stages every action on copies of robots and tasks using existing
release/charging helpers. A staging failure cannot partially alter live robots,
tasks, or MessageBus messages. Successful staging commits under one simulation
`RLock`. Already committed actions are logged individually.

Fallback uses existing A* around current occupied cells, deterministic robot-ID
ordering, a safe step aside where possible, charging preflight, or a bounded hold
when no route exists. Fallback retains task/parcel ownership unless it safely
releases it for charging. It contains failure; it does **not** promise delivery or
recovery from an unreachable charger or disconnected aisle.

FastAPI state responses are detached copies under the same simulation lock used by
ticks and execution. Snapshot reads release that lock before a model request.
Each request uses a daemon thread; exceptions are logged server-side. Resets close
the old engine, cancel its queue/HITL timers, and prevent old inference results from
mutating the new run. Lock ordering is simulation lock before runner lock.

Incoming crises use a bounded FIFO queue. Pending requests are metadata only and
never add `orchestration_holds`. Same-pair deadlocks are deduplicated across active
and pending work; stale requests and capacity rejections are explicitly logged.
Only activation adds holds. Completion removes the active ID from every robot
before activating another request. Reset cancels pending work and releases holds.

### Observability

The bounded event ring defaults to **2,000 events**. Cumulative counters survive
ring eviction for evaluation. Robot memory, message history, negotiation logs, and
auction history are also bounded; completed TaskAgents unsubscribe from broadcasts.
Tasks themselves remain the in-memory simulation record.

`GET /orchestrator/events?event_type=ACTION_OK&robot_id=1&limit=100` returns structured
events. Optional filters: `event_type`, `robot_id`, `crisis_id`. Events include
`run_id`, `event_id`, timestamp, step, and applicable crisis/plan/robot/task IDs,
node, model, latency, validation score, fallback flag, and error/reason codes.

Representative searchable console messages:

```text
[BOOT] ... seed=42 ... validator_enabled=true max_regenerations=2 auto_execute_threshold=0.85
[ORCH][ORCH_START] ... crisis_id=... affected=[1, 2]
[LLM][LLM_REQUEST] ... model=mistral attempt=1
[LLM][LLM_FAILURE] ... error_code=LLM_TIMEOUT latency_ms=...
[PLAN][PLAN_PARSED] ... plan_id=... actions=2
[VALIDATOR][VALIDATOR_PASS] ... validation_score=1.0 errors=0 warnings=0
[VALIDATOR][INVALID_PLAN] ... codes=['UNREACHABLE_WAYPOINT']
[ORCH][PLAN_REGENERATED] ... attempt=1 maximum=2
[HITL][HITL_REQUESTED] ... plan_id=...
[HITL][HITL_REJECTED] ... plan_id=...
[EXECUTOR][ACTION_START] ... robot_id=1 action=REROUTE
[EXECUTOR][ACTION_OK] ... robot_id=1 action=REROUTE
[FALLBACK][FALLBACK_ACTIVATED] ... reason=LLM_UNAVAILABLE
[CRISIS_QUEUE][CRISIS_QUEUED] ... depth=2
[CRISIS_QUEUE][CRISIS_DEQUEUED] ... remaining=1
[ORCH][ORCH_COMPLETE] ... executed_actions=2 fallback=False
```

Console context is ASCII-escaped for Windows terminal compatibility. Normal cell
movement is DEBUG-level, so it does not flood INFO logs. Pathfinding safety tags
from Section 15 remain intact. Negotiation UI records retain `event`, `timestamp`,
`reasoning`, and `decision`.

### Scheduling health logs

Every 100 steps, `[SIM][HEALTH]` records `step`, `completed_tasks`, `moving`,
`charging`, `intentional_hold`, `orchestration_pinned`, `queue_depth`,
`active_crisis`, `active_crisis_id`, `orphaned_holds`, `remaining`, `idle`,
`reauctioned`, and cumulative
`successful_moves`. `orphaned_holds` counts hold IDs that do not belong to the
currently active crisis and must remain zero. `charging` includes robots travelling
to a charger; it does not mean every such robot is receiving energy.

Additional searchable events are `[SIM][DEADLOCK_PERSISTENT]`,
`[CRISIS_QUEUE][DEDUPED]`, `[CRISIS_QUEUE][STALE_DROPPED]`,
`[CRISIS_QUEUE][BACKPRESSURE]`, and `[CRISIS][PERIODIC_SKIPPED]`.
Health snapshots are also available through the existing event endpoint using
`GET /orchestrator/events?event_type=HEALTH`.

### Configuration and reproducibility

Copy `.env.example` to `.env`; use one active `LLM_Provider` line. Settings are
validated once when creating a simulation. Important settings are:

| Variable | Default |
|---|---|
| `SIMULATION_SEED` | `42` |
| `ORCHESTRATOR_ENABLED` | `true` |
| `ORCHESTRATOR_MAX_REGENERATIONS` | `2` |
| `ORCHESTRATOR_MAX_PENDING_CRISIS` | `5` |
| `DEADLOCK_PERSISTENCE_STEPS` | `6` reciprocal failed-movement ticks after both recovery attempts |
| `ORCHESTRATOR_AUTO_EXECUTE_THRESHOLD` | `0.85` |
| `ORCHESTRATOR_MAX_HOLD_STEPS` | `10` |
| `ORCHESTRATOR_YIELD_STEPS` | `3` |
| `ORCHESTRATOR_SHADOW_HORIZON` | `5` |
| `ORCHESTRATOR_HITL_TIMEOUT_SECONDS` | `300` |
| `EVENT_HISTORY_LIMIT` | `2000` |
| `CRISIS_INTERVAL` | `200`; `0` disables periodic collapses |
| `AUTOMATIC_CRISIS_LIMIT` | `3`; maximum successful automatic injections per run |

Ollama inference retains its **60.0 second timeout**, JSON schema output request,
and temperature 0. Provider mapping stays in `backend/core/llm_config.py`.
The compact prompt contains affected robots only: IDs, positions, batteries,
parcel/task state, destinations, next three cells, adjacent walkable cells, crisis
cells, action syntax, and concise validation/rejection feedback. It does not dump
all robot paths, the full grid, or histories. The JSON grammar exposes each action's
required parameters (e.g. HOLD requires hold_steps); Pydantic and the deterministic
validator still verify the actual response. Temperature remains 0 and the timeout
remains 60 seconds. There is one configured provider, no model router or cloud fallback.

`create_simulation()` shares one `random.Random(seed)` across warehouse/task/crisis
generation. It never seeds the global random module. Reset defaults to the current
seed; `POST /simulation/reset {"seed":100}` selects another seed. Same seed means
same initial grid, spawns, tasks, and procedural choices. Run IDs are intentionally
new. LLM output, wall-clock timings, operator decisions, and concurrent production
scheduling are **not** promised to be bit-for-bit reproducible.

### API additions and compatibility

- `POST /simulation/crisis` triggers the existing collapse mechanism. Optional
  `{"coords":[[x,y],...]}` selects cells. Occupied cells and chargers are rejected.
- `POST /simulation/reset` still accepts no body. Optional body contains `seed`
  and `orchestrator_enabled`.
- `/simulation/status` adds `run_id`, `seed`, `grid_revision`, `orchestrator_enabled`.
- `/robots` adds `hold_steps_remaining`, `yield_to_robot_id`, `orchestration_held`.
- `/orchestrator/state` exposes `active`, `active_node`, `run_id`, `crisis_id`,
  `plan_id`, `crisis_location`, `affected_robots`, `proposed_plan.actions`,
  `validation_score`, `validation_status`, `validation_issues`, `validation_report`,
  `waiting_for_human`, `human_approved`, `approval_source`, `regeneration_count`,
  `rejection_count`, `fallback_used`, `fallback_reason`, `queued_crises`,
  `queued_crisis_ids`, `max_pending_crisis`, `crisis_kind`, `executed_actions`, and `error`/`error_code`.
- `POST /orchestrator/override` requires a strict boolean `approved` and the current
  `plan_id`; stale/duplicate decisions or a non-waiting graph return **409**.
- Bad operator coordinates return **400**; malformed request bodies **422**;
  unexpected exceptions return a stable **500** JSON message with server-side logs.

OperationCentre retains its layout and polling. It shows Validation Score/status,
error/warning counts, escaped structured actions/reasons, fallback status, queue
count, and the latest completed result. Grid revision/run changes trigger a refresh.
The old dashboard's grid refresh and polling continue to work.

## 18. Tests

```powershell
python311\python.exe -m pip install -r requirements-dev.txt
python311\python.exe -m pytest -q
python311\python.exe -m pytest -q tests/test_safety.py
python311\python.exe -m pytest -q tests/test_orchestrator.py
node --check frontend/js/OperationCentre.js
node --check frontend/js/dashboard.js
node --test tests/operation_centre.test.cjs
python311\python.exe -m compileall -q backend tests
```

Pytest config includes the project root for the bundled isolated Windows Python.
Tests mock/inject the model boundary; **Ollama is not required**. Coverage includes
A* and obstacle regressions, battery/arrival guards, CNP ownership and release,
strict parsing, deterministic validation, action staging, real control effects,
HITL approval/rejection, bounded retries, fault fallback, crisis queuing, concurrent
reads/reset cancellation, API errors, seed replay, metrics, and benchmark artifacts.
The older `test_repairs.py` regressions are retained and migrated to the new schema.
Node rendering tests exercise the existing HUD with a minimal DOM test fixture;
they do not replace a real-browser visual test.

Local-inference scheduling regressions are in `tests/test_local_llm_scheduling.py`:
transient/persistent pairs, asynchronous recovery timing, real narrow-aisle recovery
failure, active/pending deduplication, queue capacity, stale dropping, active-only
holds, failure/reset cleanup, intentional waits, and structural backpressure.
A `threading.Event` holds fake inference open for 1,000 simulation ticks while
asserting continued work, bounded queue depth, and zero orphaned holds. A separate
seed-42 test runs 3,000 ticks with offline inference, all 40 robots and 120 tasks,
periodic collapses, occupancy/orthogonal-movement/battery checks, and progress
assertions. Its evaluation barrier is explicit; it is not used in the slow-model
test or production.

```powershell
python311\python.exe -m pytest -q tests/test_local_llm_scheduling.py
# Retain health JSON files under a chosen test-output directory:
python311\python.exe -m pytest -q tests/test_local_llm_scheduling.py --basetemp evaluation_results/local_llm_tests
```

The tests write `slow_llm_health.json` and `seed42_health.json` beneath their pytest
temporary directories. The scheduling pass on 2026-09-16 passed 150 Python tests. The final performance-pass verification is recorded in Section 20. Starlette's installed TestClient/httpx integration emits one
deprecation warning.

The real `mistral:latest` smoke request reached the retained timeout (about 62
seconds measured end-to-end). During that wait the simulation advanced 1,903 ticks
and completed 45 tasks; fallback completed with zero orphaned holds. This verified
real local failure handling, not successful model planning. Gemma generation had not been tested at that stage; Section 20 records the later real-model tests. These are smoke observations, not comparative performance claims.

Historical **pre-performance-pass** seed-42 snapshots after each checkpoint's graph settled:

| Step | Completed | Moving | Charging | Pinned | Queue | Orphaned holds | Successful moves |
|---|---:|---:|---:|---:|---:|---:|---:|
| 100 | 10 | 8 | 30 | 0 | 0 | 0 | 2,850 |
| 300 | 16 | 7 | 32 | 0 | 0 | 0 | 4,751 |
| 500 | 21 | 7 | 30 | 0 | 0 | 0 | 6,765 |
| 1000 | 29 | 3 | 34 | 0 | 0 | 0 | 11,619 |
| 3000 | 31 | 2 | 33 | 0 | 0 | 0 | 16,205 |

The slow fake request retained exactly one pinned robot and five pending entries
through 1,000 ticks, completing 29 tasks with 11,661 successful moves. Persistent
charger congestion and disconnected tasks still constrain throughput in that **pre-performance baseline**; see Section 20 for measured completion with the current policy.

## 19. Evaluation Harness

Normal Python installation:

```bash
python -m backend.evaluation.runner --scenario aisle_collapse --seeds 42 100 123 --steps 500
```

Bundled isolated Windows Python (thin entry point supplies the project import path):

```powershell
python311\python.exe run_benchmark.py --scenario aisle_collapse --seeds 42 100 123 --steps 500
# Reproducible failure demo without an Ollama server:
python311\python.exe run_benchmark.py --scenario aisle_collapse --seeds 42 --steps 30 --fault LLM_OFFLINE
python311\python.exe run_benchmark.py --scenario llm_malformed_response --seeds 100 --steps 30
```

Default modes are `baseline` (orchestrator OFF) and `orchestrator` (ON). Both retain
CNP and use identical initial seed/scenario settings. Use `--modes baseline` to
avoid inference. ON uses **real Ollama by default**; fault injection is explicit.
No successful model responses or performance improvements are fabricated.

| Scenario | Configuration |
|---|---|
| `normal` | Existing 40-robot depot and 120 tasks; no scheduled collapse |
| `high_workload` | Same warehouse with 240 tasks |
| `depot_congestion` | Deliveries converge at one depot cell |
| `battery_stress` | Initial battery 45 |
| `aisle_collapse` | One seeded 3-cell collapse requested before evaluation tick 20 |
| `critical_order` | CRITICAL task injection before tick 20 |
| `llm_offline` | Aisle-collapse schedule plus injected unavailable model |
| `llm_malformed_response` | Aisle-collapse schedule plus malformed model text |

`--fault` also accepts `LLM_TIMEOUT`. Fault cells are chosen from the initial
warehouse with a separate scenario RNG, so their **requested** coordinates are
identical across modes. An occupied fault cell causes a logged skipped injection,
not a robot being crushed; `scenario_faults_skipped` reports this. Scenarios reuse
the existing engine, warehouse, task creation, and crisis entry points.

Fixed-step comparison evaluation waits for background orchestration between ticks.
The separate `--completion` acceptance mode uses asynchronous production stepping,
measures elapsed wall-clock time, and stops immediately when all tasks finish. This removes OS
thread timing from simulation-step comparisons; production does not wait.
`--hitl-policy approve` (default) **simulates an operator approving valid risky
plans**; `reject` exercises bounded regeneration/fallback. This policy is recorded
in each artifact and never bypasses invalid-plan checks. Recovery-step metrics
exclude inference wall-clock latency, which is reported separately. A 240-second
per-barrier watchdog reports benchmark failure rather than hanging indefinitely.

Results are written to `evaluation_results/benchmark_<UTC timestamp>.json` and
`.csv`, or `--output <directory>`. JSON includes settings, seed, mode, fault,
requested cells, HITL policy, metrics, and identified run errors. CSV contains one
row per successful run. Errors produce a nonzero exit code and a JSON error record.

### Metric definitions

| Metric | Measurement |
|---|---|
| `task_completion_count`, `task_completion_rate` | Completed tasks, and completed / all tasks including injected tasks |
| `mean_task_completion_steps` | Mean completion step minus creation step; includes auction/wait time |
| `p95_task_completion_steps` | Nearest-rank 95th percentile; only reported for at least 20 completions |
| `throughput_per_100_steps` | Completed tasks * 100 / simulated steps |
| `blocked_attempts` | Failed occupied/reserved cell requests; not actual physical collisions |
| `deadlock_count` | Per-robot episodes beginning after 3 consecutive blocked moves |
| `deadlocks_resolved`, `deadlocks_unresolved` | Episodes ended by that robot's next successful movement, or still open |
| `mean_deadlock_resolution_steps` | Steps from detection to next movement, for resolved episodes only |
| `tasks_reauctioned` | Count of actual task releases, including repeated releases of one task |
| `crisis_count` | Structural collapse events; deadlock episodes are counted separately |
| `crises_recovered`, `crises_unresolved` | Collapse for which every initially affected robot moved at least once, or still open; zero affected means immediate recovery |
| `mean_crisis_recovery_steps` | Mean steps to that first-movement recovery definition; not restoration of all task throughput |
| `llm_call_count`, `llm_success_count`, `llm_failure_count` | Requests, parseable/schema-valid responses, and transport/parse/schema/internal inference failures |
| `llm_fallback_count`, `llm_fallback_rate` | Graph sessions ending in fallback; rate = fallback sessions / completed graph sessions, including stale approvals/HITL expiry |
| `mean_llm_latency_ms` | Total measured request/parse wall-clock milliseconds divided by requests |
| `invalid_plan_count` | Invalid JSON/schema, repeated rejected strategies, and failed safety reports |
| `plan_regeneration_count` | Extra model requests after initial generation |
| `hitl_requested`, `hitl_approved`, `hitl_rejected` | Actual graph review requests and accepted operator decisions |

Unobserved means are JSON `null`, never made-up zero durations. Unresolved counts
are reported beside resolved means to avoid hiding censored failures. Metrics come
from cumulative counters and task timestamps, not a potentially evicted event ring.

### Remaining limitations

- Single-process in-memory simulation; no durability or distributed coordination.
- Conservative physical occupancy may reduce throughput; it is not a multi-agent
  pathfinding solver and cannot guarantee deadlock freedom.
- Short-horizon validation is a safety screen, not a guarantee that a plan resolves
  a crisis. A structurally valid HOLD can defer rather than solve a problem.
- Simulation-step evaluation excludes model/operator wall-clock waiting. Use the
  recorded latency and explicit HITL policy when interpreting comparisons.
- Runtime model quality is hardware/provider dependent and requires actual Ollama
  evaluation; fault-injected smoke runs establish plumbing, not LLM performance.
- Unreachable chargers, depleted robots, and disconnected pickups can require
  operator intervention. The simulator does not implement physical robot rescue.
- The bounded queue deduplicates deadlock pairs but does not coalesce structural
  incidents. At capacity, admission is rejected and deterministic handling remains.
  Reset logs cancellation instead of carrying work into a different warehouse.
- The detector recognizes reciprocal robot pairs, not arbitrary larger wait cycles.
  Recovery HOLD/replan pauses do not count toward persistence or create incidents.
- Active affected robots may wait through model retries/HITL; pending work never
  pins robots. Reset invalidates results but cannot instantly cancel work already
  being computed inside Ollama.
- The old 3,000-step scheduling baseline finished 31/120. Current completion acceptance is measured separately in Section 20; it is not a universal deadlock-freedom guarantee.
- Frontend polling remains; no UI redesign, WebSocket/SSE migration, or deployment
  work is included.

### Model-status probe troubleshooting

No frontend/backend source in this repository requests `/v1/models`. A 404 for that
path indicates an unsupported request; the originating external client was not
identified from repository code. This simulator exposes no OpenAI-compatible model
API. Ollama's native model-list endpoint is `http://localhost:11434/api/tags`;
model generation uses the configured `/api/generate` URL.


## 20. Completion Acceptance and Final Performance Pass

### Target and method

The normal demo target is **120 genuine task deliveries with 40 robots in less
than 900 wall-clock seconds**. CNP, batteries, charging, physical occupancy,
path safety, and crisis orchestration remain enabled. The acceptance command uses
the normal factory and asynchronous graph workers; it does not wait at an inference
barrier and stops immediately on completion. Time includes construction, stepping,
safety checks, model waiting, and the selected simulated operator policy.

```powershell
# Offline failure recovery, with AI orchestration still enabled:
python311\python.exe run_benchmark.py --completion --seeds 42 --fault LLM_OFFLINE --output evaluation_results/completion_offline
# Real configured local Ollama model (LLM_Provider=gemma or mistral):
python311\python.exe run_benchmark.py --completion --seeds 42 --output evaluation_results/completion_local
# Repeat across chosen seeds; each has its own deadline:
python311\python.exe run_benchmark.py --completion --seeds 42 100 123 --fault LLM_OFFLINE
```

`--timeout` defaults to 900 seconds; PASS always requires less than 900, even if a
larger watchdog is supplied. A 50,000-step ceiling and 500 consecutive steps without
positional progress (while no graph is active) report failure rather than silently
running forever. Failure artifacts include unfinished tasks and robot states.
The harness uses `--hitl-policy approve` by default to simulate an operator; invalid
plans still cannot execute. This is explicitly recorded, never an implicit bypass.

Every tick checks unique cell occupancy, walkability, orthogonal movement, battery
bounds, bidirectional/unique task ownership, bounded queue depth, and absence of
orphaned/queued holds. Completed tasks must carry delivery evidence: owning robot,
carried parcel, and actual delivery coordinates. `complete_task(..., robot=robot)`
checks those conditions before recording `delivered_by` and `delivery_position`.

JSON and CSV use `benchmark_<UTC timestamp>` beneath the selected output directory.
Completion mode adds elapsed seconds, simulation steps, successful moves, charging
entries, mean/max robots in charging/travel state, automatic crises, deadlock
escalations, and LLM timeouts to the metrics in Section 19. Charging entries count
transitions into charging/travel, including interrupted/replanned charging trips;
they are not a count of fully completed battery cycles. Re-auctions count actual
ownership releases. Fallback count is completed **orchestrator** fallback sessions,
not routine deterministic traffic recovery. Health snapshots accompany JSON.

### Diagnosed causes and fixes

The measured old seed-42 baseline reproduced **31/120 after 3,000 ticks**:
92,865 blocked attempts, 182 releases, and 60 synthetic collapses. Thirty-eight
initial tasks exceeded 100 energy units even from pickup when including loaded
delivery, charger return, and reserve. Thirty-seven unfinished task endpoints had
become structural obstacles. Merely increasing charge rate could not solve this.

The final policy retains movement drain and charge speed. It adds feasible recharge
itineraries, separates eight service bays, improves CNP bids/runner-up selection,
limits automatic crises to three, and protects task endpoints/connectivity during
automatic selection. Three-strike recovery retries after unsuccessful attempts.
Safe retreats can reach a passing space up to three cells away using existing A*;
robots still move one cell per tick. Parked robots clear nearby passing space.
A true narrow corridor without a passing space still holds/escalates. A per-move
escape-energy check prevents congestion detours from stranding robots.

This was necessary to handle threaded timing variations: an intermediate version
passed an individual benchmark but stalled at 119/120 in the full suite. The final
charger-entrance retreat and idle-clearance regressions cover that failure.

### Measured results

Final-code acceptance runs on 2026-09-17, seed 42:

| Metric | Injected offline | Real `gemma4:12b` |
|---|---:|---:|
| Delivered tasks | **120/120** | **120/120** |
| Wall-clock seconds | **40.531** | **77.157** |
| Simulation steps | 1,606 | 2,129 |
| Successful physical moves | 15,189 | 14,488 |
| Charging entries | 390 | 350 |
| Mean / max charging-or-travelling robots | 6.25 / 11 | 4.68 / 11 |
| Task re-auctions | 27 | 29 |
| Structural crises | 3 | 3 |
| Persistent deadlock escalations | 0 | 0 |
| LLM requests / schema-valid responses / timeouts | 2 / 0 / 0 | 4 / 4 / 0 |
| Orchestrator fallback sessions | 2 | 1 |
| Acceptance | **PASS** | **PASS** |

Artifacts:
- `evaluation_results/throughput/acceptance_offline/benchmark_20260917T150759182196Z.json` and matching CSV.
- `evaluation_results/throughput/acceptance_local/benchmark_20260917T150949289830Z.json` and matching CSV.
- `evaluation_results/throughput/final_suite.log` records the final test run.

The real run executed a validated HOLD for robot 20. Another crisis received three
schema-valid plans that failed deterministic safety/coverage validation (including
missing affected robots); retries exhausted and deterministic fallback completed
recovery. **Schema-valid response counts are not successful recovery counts.**
No invalid plan executed. All 120 delivery-evidence checks passed, with zero
orphaned holds and no physical invariant failures. Two of the three collapses
required LLM orchestration; a collapse that affects no active path needs no call.

The earlier controlled Gemma collapse completed generation, parsing, validation,
and action execution in 9.437 seconds. Mistral's original large-context request
hit the retained 60-second timeout. Its earlier compact-prompt trial returned
three schema errors in 33.562 seconds because HOLD omitted its parameter; this
motivated action-dependent JSON grammar. A later Mistral attempt found Ollama
unavailable and safely fell back. No successful final-schema Mistral generation
is claimed. Gemma is the provider used for the final real completion acceptance.
These trials differ in prompt/schema/server state and are not a controlled model
speed comparison.

These are **unpaced backend acceptance runs**, not measured browser sessions.
The API loop retains its 0.2-second tick delay. OS thread scheduling and local
inference can change step counts even with identical initial seeds. Do not treat
one successful seed or a short HOLD response as proof of optimal scheduling or
universal deadlock freedom. Manual obstacle injections, extreme stress settings,
other seeds, human delays, and hardware can produce different results.

### Verification

```powershell
python311\python.exe -m pytest -q
python311\python.exe -m pytest -q tests/test_throughput.py
python311\python.exe -m compileall -q backend tests
node --check frontend/js/OperationCentre.js
node --check frontend/js/dashboard.js
node --test tests/operation_centre.test.cjs
```

The final Python suite passed **169 tests** (one existing Starlette/httpx
deprecation warning). New focused tests cover energy feasibility, recharge-stop
ownership, loaded movement reserve, bay selection/departure, preserved traffic
detours, idle clearance, multi-cell charger-entrance retreat, real delivery
evidence, finite automatic crises, protected endpoints, compact prompts,
action-specific JSON grammar, and genuine 120-task completion. Existing tests
continue covering A*, CNP, structured validation/execution, HITL/rejection,
fallback, queue bounds, a stalled local request over 1,000 ticks, and a 3,000-step
safety run. The API charger-input test uses the new actual bay coordinate; it still
requires HTTP 400 for collapsing a charging station.

`[SIM][ALL_TASKS_COMPLETED]` logs tasks, steps, elapsed time, charging entries,
re-auctions, crises, LLM calls, and fallbacks. `[SIM][HEALTH]` reports remaining
work and congestion every 100 ticks. No frontend redesign or deployment changes
were made in this performance pass.

# Architecture and Agents

This guide preserves the architecture, coordination, data-model, movement, and path-safety material from the root README.

[Back to the project hub](../README.md) · [Operations and workspaces](OPERATIONS_AND_WORKSPACES.md) · [Crisis and LLM orchestration](CRISIS_AND_LLM_ORCHESTRATION.md) · [Deployment and benchmarks](DEPLOYMENT_AND_BENCHMARKS.md)

## 2. Multi-Agent Architecture

### Architecture Overview

```text
SwarmOS Workspaces (HTML/CSS/JS)
       │
       │ HTTP polling (400ms core / 1s summaries; legacy dashboard 200ms)
       ▼
FastAPI REST API (backend/api.py)
       │
       │ direct Python method calls
       ▼
┌──────────────────────────────────────────────────────────┐
│                   SimulationEngine                        │
│   (coordinates ticks; TaskAgents award routine tasks)      │
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
- No immobilization fault, active crisis pin, HOLD, or YIELD timer. TaskAgent checks these again before awarding a previously received bid.

Both RobotAgent bidding and TaskAgent awarding check reachable, energy-feasible
pickup and loaded delivery itineraries, including real charging stops where needed.
Each movement leg's energy cost plus a 5-unit reserve must fit the available battery.
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
| `EMERGENCY_CFP` | broadcast | CRITICAL task proposal request; eligible normal work can be safely preempted |
| `PROPOSAL` | direct | Bid submission (RobotAgent → TaskAgent) |
| `TASK_AWARDED` | direct | Contract award (TaskAgent → winning RobotAgent) |
| `LOW_BATTERY` | broadcast | Robot reports low battery to peers |
| `BLOCKED_PATH` | broadcast | Robot reports a blocked cell to peers |
| `HELP_REQUEST` | broadcast | Robot requests assistance |
| `ROBOT_STATUS` | broadcast | Robot status update |
| `REROUTE` | direct | Suggest rerouting to a specific robot |
| `TASK_RELEASED` | broadcast | Robot released its assigned task |
| `CRISIS_ALERT` | broadcast | Structural obstruction coordinates; higher-level recovery runs through the orchestrator |

The enum includes compatibility vocabulary; a defined message type does not by
itself prove that a production handler uses it. Executable LLM actions are
`CrisisPlan` actions checked by PlanValidator/ActionExecutor, not unchecked
MessageBus commands with similarly named types.

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
├── python311/                        # Optional local interpreter; not versioned
├── Dockerfile                        # Python 3.11, single-worker app image
├── docker-compose.yml                # App + local Ollama + model pull helper
├── .env.example                      # Supported local/hosted runtime settings; no real key
├── requirements.txt                  # Pinned runtime dependencies
├── requirements-dev.txt              # Runtime dependencies + pytest
├── backend/
│   ├── __init__.py
│   ├── api.py                        # FastAPI app with MAS integration
│   ├── main.py                       # Console simulation runner
│   ├── core/                         # Base schemas and configurations
│   │   ├── models.py
│   │   ├── constants.py
│   │   └── llm_config.py             # Environment-based Ollama/OpenRouter selection
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
    │   ├── OperationCentre.css       # Live Operations terminal
    │   ├── CrisisOrchestration.css   # Crisis desk
    │   ├── AgentAnalytics.css        # Fleet inspector
    │   └── SystemOverview.css        # Architecture field guide
    ├── dashboard.html                # Browser visualization template
    ├── OperationCentre.html          # Live Operations template
    ├── CrisisOrchestration.html      # Crisis + Orchestration template
    ├── AgentAnalytics.html           # Agent Analytics template
    ├── SystemOverview.html           # Recruiter/contributor architecture guide
    └── js/
        ├── dashboard.js              # Live dashboard interaction scripts
        ├── OperationCentre.js        # Live Operations interactions
        ├── CrisisOrchestration.js    # Observed crisis lifecycle and HITL controls
        ├── AgentAnalytics.js         # Read-only fleet evidence and rolling samples
        └── SystemOverview.js         # Read-only current facts; bounded polling
```

### Backend hardening additions

The abbreviated tree above is complemented by these runtime/test modules:

```text
backend/core/settings.py              # Validated run configuration
backend/core/events.py                # Bounded structured events and counters
backend/agents/plans.py                # Strict executable action schema/parser
backend/agents/llm_client.py           # Ollama/OpenRouter boundaries and fault clients
backend/agents/plan_validator.py       # Copied-state safety validation
backend/agents/action_executor.py      # Staged execution and fallback
backend/simulation/factory.py          # Shared seeded construction
backend/evaluation/                   # Scenarios, metrics, CLI runner
backend/evaluation/llm_smoke.py         # One explicit selected-provider schema smoke check
run_benchmark.py                      # Bundled-Python benchmark entry point
tests/                                # Backend and frontend regression tests
pytest.ini
requirements-dev.txt
.env.example
```

### Component Responsibilities

| Component | File | Responsibility |
|---|---|---|
| **MessageBus** | `backend/agents/message_bus.py` | In-memory pub/sub for agent communication |
| **RobotAgent** | `backend/agents/robot.py` | Process messages → perceive → decide → act; bidding, movement, charging and fault/hold guards |
| **TaskAgent** | `backend/agents/task.py` | Issue CFPs, collect proposals, recheck eligible bidders and award contracts through CNP |
| **RobotOrchestrator** | `backend/agents/robot_orchestrator.py` | Create and tick RobotAgents, preserving reservation priority |
| **TaskOrchestrator** | `backend/agents/task_orchestrator.py` | Create/tick TaskAgents for existing and dynamically added tasks |
| **SimulationEngine** | `backend/simulation/engine.py` | Task-first ticks, persistent-pair detection, shared-budget admission, deferred incident effects and cleanup |
| **Simulation factory** | `backend/simulation/factory.py` | Shared seeded construction for API, tests and evaluation |
| **Warehouse** | `backend/simulation/warehouse.py` | Default 50×30 shelves/aisles, eight chargers and 40-robot depot |
| **RobotState** | `backend/state/robot_state.py` | Robot creation, spawning, lookup and assignment state |
| **TaskState** | `backend/state/task_state.py` | Ownership checks, safe parcel-preserving release, delivery evidence and CNP release notification |
| **AStarPathfinder** | `backend/simulation/pathfinder.py` | A* with walkability, closed-set and returned-path integrity checks |
| **CollisionManager** | `backend/simulation/collision.py` | Occupied cells and per-step reservations; never permits overlapping robots |
| **ChargingManager** | `backend/simulation/charging.py` | Energy-feasible itineraries, available bays and bounded distance/route caches |
| **NegotiationService** | `backend/agents/negotiation.py` | Bounded UI-compatible deterministic explanations and crisis summaries |
| **OrchestratorRunner** | `backend/agents/orchestrator_graph.py` | Queue/session ownership and async `diagnose → generate_plan → validate → execute`, with HITL, rejection and fallback edges |
| **Provider configuration** | `backend/core/llm_config.py` | Environment loading, provider selection and exact model slug |
| **Inference clients** | `backend/agents/llm_client.py` | Ollama/OpenRouter HTTP requests, response extraction and sanitized transport diagnostics |
| **Plan schema/parser** | `backend/agents/plans.py` | Strict action models, JSON parsing, validation-report models and generation schema |
| **PlanValidator** | `backend/agents/plan_validator.py` | Non-mutating copied-world safety checks, readiness score and shadow prediction |
| **ActionExecutor** | `backend/agents/action_executor.py` | Live revalidation, staged deterministic actions and safe fallback |
| **Settings / events** | `backend/core/settings.py`, `backend/core/events.py` | Validated run settings, bounded structured history and cumulative counters |
| **Evaluation** | `backend/evaluation/`, `run_benchmark.py` | Scenarios, completion invariants, measured JSON/CSV artifacts and explicit provider smoke checks |

---
## 6. Simulation Engine Execution Flow

### Step Sequence (Multi-Agent Mode)

`SimulationEngine.step()` executes:

1. Increment `current_step`.
2. Record the step at DEBUG level and attempt a due automatic incident when budget and backpressure allow it.
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
6. Observe genuine reciprocal failed movement, clear resolved episodes and escalate only persistent pairs within the shared budget.
7. Update completion/charging counters and emit the bounded health summary every 100 steps.

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
| `fault_reason` | `str \| None` | `None` | Temporary immobilization blocks movement/bidding; terminal/reset cleanup clears it |
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
| `delivered_by` | `int \| None` | `None` | Robot recorded by the delivery-evidence check |
| `delivery_position` | `tuple[int,int] \| None` | `None` | Actual cell at successful delivery |

These tables describe backend models. REST responses expose selected fields:
`/robots` includes `fault_reason`, but `/tasks` currently returns task identity,
coordinates, priority, assignment and completion only. Task timestamps and
delivery evidence are retained internally and in evaluation artifacts. A robot
fault is a separate field, not a new `RobotStatus` enum value.

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

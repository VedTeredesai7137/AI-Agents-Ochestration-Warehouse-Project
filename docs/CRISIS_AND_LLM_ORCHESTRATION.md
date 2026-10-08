# Crisis and LLM Orchestration

This guide documents provider configuration, controlled incidents, slow-model scheduling, plan safety, HITL, fallback, and orchestration observability.

[Back to the project hub](../README.md) · [Architecture and agents](ARCHITECTURE_AND_AGENTS.md) · [Operations and workspaces](OPERATIONS_AND_WORKSPACES.md) · [Deployment and benchmarks](DEPLOYMENT_AND_BENCHMARKS.md)

## 14. LLM Configuration & Bug Resolution Notes

### Provider Selection

The backend centralizes provider configuration in `backend/core/llm_config.py`:

- `LLM_Provider=mistral` selects the installed `mistral:latest` model.
- `LLM_Provider=gemma` selects the installed `gemma4:12b` model.
- `LLM_Provider=openrouter` selects `OPENROUTER_MODEL` using OpenRouter Chat Completions; `OPENROUTER_API_KEY` is required.
- `OPENROUTER_MODEL` is required explicitly; withdrawn free models are never replaced by a paid slug automatically.
- Provider names are case-insensitive and default to `mistral` when omitted.
- `OLLAMA_URL` may optionally override the default endpoint `http://localhost:11434/api/generate`.
- `OPENROUTER_URL` defaults to `https://openrouter.ai/api/v1/chat/completions` and must use HTTPS.

Changing `.env` does not change an already-running process. Restart Uvicorn after switching providers.
OpenRouter requests ask for strict JSON Schema output with compatible-provider routing; the same Pydantic parser, deterministic plan validator, HITL gate and fallback still apply. HTTP/rate-limit failures never directly execute a plan. Missing `OPENROUTER_API_KEY` in OpenRouter mode fails startup with a configuration error rather than leaving a silently broken deployment. No extra SDK dependency is required; the existing `requests` package is used.

### Crucial Timeout Configuration
To ensure robustness during local inference (e.g., running `mistral:latest` or `gemma4:12b` via Ollama on consumer hardware), **the inference timeout remains 60 seconds** for both providers.
- **Important Note for AI Models**: Any future modification to the exceptional orchestration LLM calls must preserve the `timeout=60.0` configuration on all HTTP requests (e.g., `requests.post`). Using small/default timeouts (like 5.0 seconds) will cause `ReadTimeout` exceptions when the local model takes time to initialize or generate responses.

### Pathfinding Enforcement
- **Orthogonal Strictness**: The `AStarPathfinder` strictly enforces orthogonal movement. Robots perform immediate collision verification before each step against static obstacles. Any path attempting to clip through `S` (Shelf or Pillar) blocks is instantly aborted.

### Exceptional inference and logging

Routine auction explanations and social greetings are deterministic templates.
LLM calls are reserved for structural crises and persistent reciprocal robot
blockage. `NegotiationService` retains the UI log schema (`event`, `timestamp`,
`reasoning`, `decision`); the structured orchestrator owns model decisions.
Each simulation has one daemon graph worker and a FIFO crisis queue. Inference
holds neither the simulation lock nor the runner lock. See [Section 17](#17-structured-crisis-orchestration).

---
## 16. Controlled Chaos & Stress Testing

To rigorously test the multi-agent negotiation layers, deadlock resolution, and emergency handling, the simulation incorporates intentional "controlled chaos" mechanisms. These features dramatically increase swarm density and system stress, forcing agents to constantly adapt.

### Chaos Mechanisms Injected

1. **Massive Workload Overload**
   - **120 Initial Tasks**: The simulation boots with 120 procedurally generated tasks (up from 50), immediately saturating the swarm and triggering extensive Contract Net Protocol (CNP) bidding wars.
   - **Aggressive Battery Drain**: Robots carrying items now consume 2 battery units per step (instead of 1). Loaded movement retains the 2x energy cost. Planned charging stops avoid predictable mid-task drops.

2. **The "Depot" Spawn Choke Point**
   - Instead of distributing the 40 robots randomly across the bottom of the warehouse, they are exclusively spawned inside a dense 10x4 contiguous block in the bottom-center (Rows 25-28, Cols 20-29).
   - This intentional bottleneck forces immediate, massive traffic jams at Step 1, rigorously stress-testing the step-local collision manager and deterministic three-strike recovery. Only persistent unresolved reciprocal contention escalates to the LLM.

3. **Finite Demo Crisis Schedule (Aisle Collapses)**
   - **Normal schedule**: a shared run budget of **6** admitted incidents, with automatic attempts spaced **200** steps apart. `CRISIS_BUDGET` and `CRISIS_INTERVAL` configure this; manual and escalated incidents consume the same budget. No automatic injection follows task completion. Older `AUTOMATIC_CRISIS_LIMIT` remains a total-budget alias when `CRISIS_BUDGET` is absent.
   - **Backpressure**: A scheduled collapse is skipped when active/pending structural orchestration exists or the pending queue is full. The next normal interval retries; skipped injections do not accumulate.
   - **Targeting**: three contiguous floor cells, biased toward active routes and central rows 10–20. Selection preserves unfinished task endpoints, occupancy, charger connectivity and currently feasible owned-task energy itineraries. Explicit selected-cell requests use the same admission safety checks; unsafe coordinates are refused.

4. **Emergency Critical Orders**
   - Tasks can be dynamically injected with a `CRITICAL` priority flag.
   - TaskAgents broadcast `EMERGENCY_CFP`, permitting busy robots to bid, drop their current normal priority tasks, and immediately route to the emergency pickup.

5. **3-Strike Deadlock Protocol & Observability**
   - Robots track failed cell reservations via `blocked_counter`.
   - **Strike 3**: Records a blocked episode and attempts deterministic recovery. It never calls the LLM directly. After both robots have attempted recovery, six further reciprocal failed-movement ticks can escalate the same unresolved pair (see [Section 17](#17-structured-crisis-orchestration)).
   - **Dashboard Chaos Metric**: The `dashboard.js` polling loop actively parses API statuses for `total_strikes` and outputs a `[CHAOS METRIC]` directly to the frontend console, providing visual proof of system stress. Banners and pulsing grid cells visually highlight these critical disruptions in real-time.

> **Normal demo rule**: retain 40 robots, 120 tasks, CNP, energy and physical safety. Use a finite shared six-slot budget with varied incidents; structural collapse is one incident kind. Automatic attempts rotate through obstruction, immobilization, charger outage and urgent-order disruption. Deadlocks arise from genuine persistence. Explicit stress settings can change the bounded budget/interval.

---
## 17. Structured Crisis Orchestration

The LLM selects **executable actions**. Deterministic services validate and execute
them. Routine CNP allocation, A*, movement, collision checks, and batteries remain
outside inference. `SimulationEngine.step()` still ticks TaskAgents before
RobotAgents; the crisis layer does not centrally award ordinary tasks.

### Fast deterministic layer, exceptional model decisions

Local Ollama supports `mistral:latest` (about 4.4 GB) and `gemma4:12b` (about
7.6 GB), selected through `LLM_Provider=mistral` or `LLM_Provider=gemma`.
These are slow strategic models: one request may span hundreds of simulation
ticks. `LLM_Provider=openrouter` selects one hosted model using the private
`OPENROUTER_API_KEY`; it is an explicit alternative, never an automatic cloud
fallback from Ollama. The system still runs its safe deterministic fallback when
the selected provider times out or is unavailable. Ollama metadata reports 7.2B
parameters for the installed Mistral model and 11.9B for Gemma.

The fast layer runs every tick: CNP, RobotAgents, A*, occupancy reservations,
charging, path invalidation, and deterministic recovery. The slow layer runs
LangGraph, structured plan generation, validation, HITL, execution, and fallback
only for exceptional incidents. Inference retains its 60-second request timeout;
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

- Crisis kinds are `DEADLOCK`, `STRUCTURAL_COLLAPSE`, `ROBOT_IMMOBILIZED`, `CHARGER_OUTAGE`, and `CRITICAL_TASK`.
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
- Automatic attempts use `CRISIS_INTERVAL=200` and the shared `CRISIS_BUDGET=6`.
  The sequence rotates through obstruction, immobilization, charger outage and urgent-order disruption; deadlock is detected from genuine persistence rather than fabricated.
- Manual, automatic and natural escalations share the same admission budget.
  One accepted manual request removes one future automatic slot and resets its
  next due step to `current_step + CRISIS_INTERVAL`. Rejected input consumes no
  slot. A queued incident that becomes stale still consumes its admitted slot.
- Automatic attempts are postponed while any orchestration is active/pending.
  Manual requests can queue within capacity, but their physical effects wait until
  activation. Queued robots keep operating and never acquire orchestration holds.
  Eligibility is rechecked at the front; unsafe or stale work is dropped.
- `/simulation/status` and `/orchestrator/state` expose `crisis_budget`,
  `crises_submitted`, `crises_completed`, `crises_remaining`,
  `next_automatic_crisis_step`, `crisis_types`, and bounded incident summaries.
  Completed means terminal incident handling/effect cleanup; physical movement
  recovery remains a separate measurement. A run may finish with unused slots.

| Incident | Actual effect and recovery |
|---|---|
| `STRUCTURAL_COLLAPSE` | Eligible cells become `S`; endpoint/charger connectivity is preserved, and existing A* replans immediately at activation. Permanent obstruction remains after orchestration. |
| `DEADLOCK` | Only an unresolved reciprocal pair after deterministic recovery escalates; pair deduplication and stale dropping remain in force. |
| `ROBOT_IMMOBILIZED` | Temporary movement/bidding fault; movement actions are rejected by the validator. Safe reassignment/fallback uses TaskManager release and CNP. Terminal/reset cleanup clears the fault. |
| `CHARGER_OUTAGE` | An unoccupied bay temporarily becomes walkable non-charging floor. Selection cannot strand robots without charging energy. Charging routes replan; terminal/reset cleanup restores the bay. |
| `CRITICAL_TASK` | An owned unfinished order becomes CRITICAL without adding tasks or skipping delivery. Reassignment/fallback safely releases it into existing emergency CNP. Priority persists after recovery. |

The Crisis desk's incident selector calls the existing POST endpoint with
`{"kind":"ROBOT_IMMOBILIZED","robot_ids":[1]}`, for example. `kind` defaults to
structural collapse for backward compatibility; `coords` applies to that type,
and `task_id` can select an urgent order. Invalid input returns 400/422; exhausted
budget, unavailable incident or queue capacity returns 409.

**Hold lifecycle and immediate safety:**

Queued requests never freeze robots. At activation, and only then, the request's
ID is added to its affected robots. Success, exhausted regeneration, model/network
failure, HITL timeout, execution/startup failure, cancellation, and reset all
release that ID. Final cleanup clears the active session even if completion logging
fails. A late cancelled worker cannot mutate a newer session.

Structural cells become `S` under the simulation lock when the incident activates.
Affected remaining and delivery paths are immediately replanned through existing A*, before any LLM wait.
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
model service, timeout, stale approval, and failed execution activate deterministic
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
releases it for charging, immobilization or urgent-order recovery through the
existing TaskManager/CNP mechanism. It contains failure; it does **not** promise delivery or
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
[LLM][LLM_REQUEST] ... provider=openrouter model=nvidia/nemotron-3-super-120b-a12b:free attempt=1
[LLM][LLM_RESPONSE_RECEIVED] ... http_status=200 latency_ms=...
[LLM][LLM_PARSE_ERROR] ... error_code=LLM_SCHEMA_ERROR
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
[CRISIS][CRISIS_ACTIVATED] ... crisis_kind=CHARGER_OUTAGE
[CRISIS][CRISIS_HANDLING_COMPLETE] ... temporary_effects_restored=True
[ORCH][ORCH_COMPLETE] ... executed_actions=2 fallback=False
```

Console context is ASCII-escaped for Windows terminal compatibility. Normal cell
movement is DEBUG-level, so it does not flood INFO logs. Pathfinding safety tags
from [Section 15](ARCHITECTURE_AND_AGENTS.md#15-obstacle-bypass-bug-postmortem-rules-for-future-editors) remain intact. Negotiation UI records retain `event`, `timestamp`,
`reasoning`, and `decision`.

`CRISIS_HANDLING_COMPLETE` records terminal handling; it does not mean every
physical effect was reversed. `temporary_effects_restored` applies to
immobilization/outage cleanup. Structural `S` cells and promoted CRITICAL priority
remain after completion. `CRISIS_RECOVERED` separately records first movement
by each initially affected robot.

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
| `LLM_Provider` | `mistral`; `gemma` for local Gemma or `openrouter` for hosted inference |
| `OPENROUTER_MODEL` | Explicit available slug required for OpenRouter; no automatic paid substitution |
| `OPENROUTER_URL` | `https://openrouter.ai/api/v1/chat/completions`; HTTPS required |
| `OPENROUTER_API_KEY` | Required only for OpenRouter; configure as a secret, never commit |
| `ORCHESTRATOR_MAX_REGENERATIONS` | `2` |
| `ORCHESTRATOR_MAX_PENDING_CRISIS` | `5` |
| `DEADLOCK_PERSISTENCE_STEPS` | `6` reciprocal failed-movement ticks after both recovery attempts |
| `ORCHESTRATOR_AUTO_EXECUTE_THRESHOLD` | `0.85` |
| `ORCHESTRATOR_MAX_HOLD_STEPS` | `10` |
| `ORCHESTRATOR_YIELD_STEPS` | `3` |
| `ORCHESTRATOR_SHADOW_HORIZON` | `5` |
| `ORCHESTRATOR_HITL_TIMEOUT_SECONDS` | `300` |
| `EVENT_HISTORY_LIMIT` | `2000` |
| `CRISIS_INTERVAL` | `200`; `0` disables automatic attempts |
| `CRISIS_BUDGET` | Effective default `6`; shared manual/automatic/natural admission budget |
| `AUTOMATIC_CRISIS_LIMIT` | Legacy total-budget alias, default `6`; `CRISIS_BUDGET` takes precedence |

Ollama and OpenRouter inference retain the **60.0 second timeout**, JSON schema
output request, and temperature 0. Provider mapping stays in
`backend/core/llm_config.py`.
The compact prompt contains affected robots only: IDs, positions, batteries,
parcel/task state, destinations, next three cells, adjacent walkable cells, crisis
cells, action syntax, and concise validation/rejection feedback. It does not dump
all robot paths, the full grid, or histories. The JSON grammar exposes each action's
required parameters (e.g. HOLD requires hold_steps); Pydantic and the deterministic
validator still verify the actual response. Temperature remains 0 and the timeout
remains 60 seconds. There is one configured provider and no automatic provider fallback.

`create_simulation()` shares one `random.Random(seed)` across warehouse/task/crisis
generation. It never seeds the global random module. Reset defaults to the current
seed; `POST /simulation/reset {"seed":100}` selects another seed. Same seed means
same initial grid, spawns, tasks, and procedural choices. Run IDs are intentionally
new. LLM output, wall-clock timings, operator decisions, and concurrent production
scheduling are **not** promised to be bit-for-bit reproducible.

### API additions and compatibility

- `POST /simulation/crisis` accepts the five `CrisisKind` values. A missing body
  or missing `kind` selects `STRUCTURAL_COLLAPSE`; an accepted request returns
  `success`, `crisis_id` and the current budget summary. Admission can mean queued
  work rather than an immediately applied physical effect.
- `POST /simulation/reset` still accepts no body. Optional body contains `seed`
  and `orchestrator_enabled`.
- `/simulation/status` exposes `run_id`, `seed`, `grid_revision`,
  `orchestrator_enabled` and the shared budget fields below.
- `/robots` exposes `hold_steps_remaining`, `yield_to_robot_id`,
  `orchestration_held`, `fault_reason` and the current path.
- `/orchestrator/state` exposes `active`, `active_node`, `run_id`, `crisis_id`,
  `plan_id`, `crisis_location`, `affected_robots`, `proposed_plan.actions`,
  `validation_score`, `validation_status`, `validation_issues`, `validation_report`,
  `waiting_for_human`, `human_approved`, `approval_source`, `regeneration_count`,
  `rejection_count`, `fallback_used`, `fallback_reason`, `queued_crises`,
  `queued_crisis_ids`, `max_pending_crisis`, `crisis_kind`, `executed_actions`, and `error`/`error_code`.
- The same state response includes `llm_provider`, `model` and, once a request is
  observed, `llm_status`, `llm_latency_ms`, `http_status`, `failure_type`,
  `provider_error` and available finish/provider/transport details. Absent HTTP
  receipts or validation results remain unknown, never fabricated successes.
- Both state endpoints include `crisis_budget`, `crises_submitted`,
  `crises_completed`, `crises_remaining`, `next_automatic_crisis_step`,
  `crisis_types` and `incidents`. Remaining means unused admission slots, not
  unresolved incidents. Completed means terminal handling, including stale drops,
  not proven physical recovery. Incident records are bounded by the run budget.
- `POST /orchestrator/override` requires a strict boolean `approved` and the current
  `plan_id`; stale/duplicate decisions or a non-waiting graph return **409**.
- Bad operator input returns **400**; malformed request bodies/unknown kinds **422**;
  exhausted budget, full queue or no eligible incident returns **409**;
  unexpected exceptions return a stable **500** JSON message with server-side logs.

OperationCentre now presents the Live Operations layout described in [Section 13](OPERATIONS_AND_WORKSPACES.md#13-live-operations-terminal).
It retains validation, escaped structured actions, fallback, queue state and HITL.
Grid revision/run changes trigger a refresh. The legacy dashboard remains available.

#### Manual incident request shapes

Examples below describe request shapes; IDs and coordinates must match the live run.
Use the Crisis desk selector or Swagger UI at `/docs` to submit them.

| Kind | Example body | Preconditions |
|---|---|---|
| Structural obstruction | `{"kind":"STRUCTURAL_COLLAPSE"}` | Selects eligible cells automatically; optional `coords` selects 1–10 explicit cells |
| Immobilization | `{"kind":"ROBOT_IMMOBILIZED","robot_ids":[1]}` | Exactly one existing eligible robot; omitted IDs select a robot deterministically |
| Charger outage | `{"kind":"CHARGER_OUTAGE"}` | At least two bays; an unoccupied, energy-safe bay must exist |
| Urgent order | `{"kind":"CRITICAL_TASK","task_id":31}` | Existing owned unfinished task; omitted ID selects an eligible task |
| Persistent pair | `{"kind":"DEADLOCK","robot_ids":[4,5]}` | A current reciprocal episode must already meet the deterministic-recovery/persistence gate |

Coordinates are supported only for structural collapse. Occupied cells, chargers,
unfinished endpoints, disconnected access or invalidated feasible energy
itineraries are refused. `task_id` applies only to urgent-order disruption.
Requests that reach runner admission are deduplicated against an existing pair
and return its crisis ID without consuming another slot. Engine budget/capacity
checks can reject a request before that point. A pre-admission rejection consumes
no budget; an admitted request that fails eligibility at activation still consumes
its slot, even if activation was attempted immediately rather than after a wait.
Inspect the returned incident status/events to distinguish admission from an
applied fault.

Pause stops simulation ticks; it does not cancel an in-flight model request or
HITL timer. Reset creates a new run, cancels old orchestration, restores temporary
fault effects and refreshes the frontend grid. A rejected HITL plan regenerates
within the same incident and model-request retry budget; it is not a new crisis
admission.

## LLM diagnostics and current provider setup

The Crisis desk shows the configured provider/model before the first request,
then request timing, HTTP status, parse outcome and a sanitized provider message.
Transport failure is labelled **NO PLAN / MODEL FAILURE**, rather than suggesting
that a world validator rejected a plan which never arrived. Event traces include
`LLM_REQUEST`, `LLM_RESPONSE_RECEIVED`, `LLM_PARSE_ERROR`, `LLM_SUCCESS` or
`LLM_FAILURE`, then the existing validator, HITL, executor and fallback events.
HTTP 401, 402, 429, 404 and 400 are distinguished with `failure_type` while
retaining `LLM_UNAVAILABLE` for the safe fallback branch. Neither request headers,
keys nor raw provider metadata are logged.

Current hosted configuration (keep the real key private):

```dotenv
LLM_Provider=openrouter
OPENROUTER_MODEL=nvidia/nemotron-3-super-120b-a12b:free
ORCHESTRATOR_ENABLED=true
CRISIS_BUDGET=6
```

Set `LLM_Provider=gemma` and restart to use local `gemma4:12b` instead. The model
readout on the Crisis desk and Overview page follows the configured provider;
it does not hardcode GPT-OSS or Gemma.

Reproduce a single explicit inference check (uses the selected provider, may
consume its quota/cost):

```bash
python -m backend.evaluation.llm_smoke
```

For the bundled isolated Windows interpreter:

```powershell
python311\python.exe -c "import sys,runpy; sys.path.insert(0,'.'); runpy.run_module('backend.evaluation.llm_smoke',run_name='__main__')"
```

Incident preflight also checks owned-task energy itineraries using the existing
ChargingManager on copied grid state. Connected floor space alone does not prove
that a loaded robot can still reach charging stops. Structural/outage faults that
would invalidate a currently feasible itinerary are refused; movement and battery
guards remain unchanged.

The new shared budget is controlled by `CRISIS_BUDGET=6`. Keep `CRISIS_INTERVAL=200`
for the normal demo; `0` disables automatic attempts while allowing budgeted manual
requests. An energy-unsafe charger outage is skipped before admission and does
not consume a slot. Queued requests revalidate at activation; stale admitted work
still consumes its slot. Manual deadlock requests cannot bypass the persistence
gate. The incident selector, current budget and terminal count are visible on the
Crisis desk. See [Section 17](CRISIS_AND_LLM_ORCHESTRATION.md#17-structured-crisis-orchestration) for each incident's physical effect and cleanup.

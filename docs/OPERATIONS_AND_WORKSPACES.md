# Operations and Workspaces

This guide covers the HTTP contract and the SwarmOS operator-facing pages.

[Back to the project hub](../README.md) · [Architecture and agents](ARCHITECTURE_AND_AGENTS.md) · [Crisis and LLM orchestration](CRISIS_AND_LLM_ORCHESTRATION.md) · [Deployment and benchmarks](DEPLOYMENT_AND_BENCHMARKS.md)

## 10. FastAPI REST API

Response examples illustrate payload shape and may show a subset of fields;
their IDs/coordinates are examples, not captured live-run evidence. Consult
`/docs` and the current source for request validation and complete contracts.

### Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/` | API liveness response; does not test model readiness or simulation progress |
| `GET` | `/dashboard` | Browser visualization |
| `GET` | `/OperationCenter`, `/OperationCentre` | Live Operations terminal (same template) |
| `GET` | `/CrisisOrchestration` | Crisis timeline, impact map, structured plans, validation and HITL desk |
| `GET` | `/AgentAnalytics` | Read-only fleet browser, task portfolio and agent evidence |
| `GET` | `/SystemOverview` | Architecture story, safety gates, incident playbook and observed run facts |
| `GET` | `/DeveloperCentre` | Read-only bounded application console workspace |
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
| `POST` | `/simulation/crisis` | Admit a typed, budgeted incident; structural collapse remains the default |
| `GET` | `/orchestrator/events` | Filter bounded structured orchestration events |
| `GET` | `/developer/logs` | Read up to 100,000 redacted INFO-and-higher records plus successful robot MOVE debug records for the current run; supports cursor paging |

### GET /agents/status

```json
{
  "agents": [
    {
      "robot_id": 1,
      "goal": "PICKUP",
      "beliefs": {"battery_low": false, "has_task": true},
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
        {"id": 5, "sender": "task_2", "type": "CFP", "payload": {"task_id": 2, "pickup_x": 4, "pickup_y": 7, "delivery_x": 6, "delivery_y": 9}}
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
## 13. Live Operations Terminal

`/OperationCenter` is the primary Live Operations page. The existing British-spelling
`/OperationCentre` URL remains an alias to the same template. `/dashboard` remains
the legacy fleet view, with the same SwarmOS navigation.
The page answers "What is happening in the warehouse right now?" using existing
REST snapshots, Jinja2, vanilla JavaScript and CSS; it introduces no simulation logic.

### Layout and controls

- Top navbar: **SwarmOS**, centered **01 Operations / 02 Crisis / 03 Analytics / 04 Dashboard / 05 Overview** links, with an underline on the current workspace.
  A compact row below contains run/model/seed/step, simulation/API status and the existing page controls.
  Completion displays a non-modal **RUN COMPLETE** strip; it does not imply disconnection.
- Start, Pause, Step and confirmed Reset call existing simulation endpoints. Step is
  disabled while the background loop runs. Reset refreshes the grid and clears selection/history.
- Telemetry strip: deliveries/remaining tasks, moving, charging, idle, blocked beliefs,
  active/queued orchestration, recent LLM requests/fallback sessions and average battery.
- A large SVG floor plan uses `grid[y][x]`. Fit, zoom and real-data layer toggles cover
  robots, chargers, the selected path and known crisis cells. Fit uses rectangular
  logical cells to fill the available area; coordinates and route connectivity are unchanged.
- Click or keyboard-select a robot, or use the robot selector, to inspect its task,
  current route endpoint, battery, hold state, beliefs and recent event trace. Its
  available route and task pickup/delivery endpoints appear on the map.
- Amber bays and markers distinguish charging travel from charging at a bay. Active
  crisis robots have a crimson outline; selected robots and their route use bright cyan.
  Moving/delivering fleet markers remain quieter. Blocked robots use dashed amber;
  energy-stopped robots use crimson. Zero-state crisis/blocked/fallback KPIs stay muted,
  while actual incidents and active fallback receive emphasis. Charging warnings show
  separate charging / energy-stopped counts, derived from robot statuses.
- CRISIS / SELECTED ROBOT / EVENTS tabs keep context compact. The crisis tab shows
  **NO ACTIVE CRISIS** when idle, plus the last incident when available. During a
  crisis it shows graph progress, structured actions, validation, retries, queue and fallback.
- Valid HITL plans retain explicit Approve / Reject controls with the current `plan_id`.
  Reject still requests regeneration. Invalid plans never expose approval controls.
- The bounded bottom event tape and Events tab support category filters and
  **LIVE / PAUSED-FOLLOW**. Scrolling away from the latest rows freezes that reading
  snapshot; resume explicitly. Each view renders at most 100 entries.
- Diagnostics preserves auction winners/bids, negotiation explanations and the existing
  explicit "Show latest" message-reading snapshot. It loads these extra sources only while open.
- Confirmed **Inject aisle collapse** uses the existing manual crisis endpoint.
- Navigation connects the operational workspaces, legacy Dashboard and architecture Overview; Analytics opens the read-only fleet inspector. Scenario/speed controls
  are omitted because the production API does not provide them.

### Resizable workspace

On desktop (at least 1051px wide and 650px tall), drag the thin divider beside the
inspector to change its width, or the divider above Event Tape to change its height.
The default map/inspector split is approximately 68/32. The tape starts at 100px on
short screens, 142px normally, or 166px on wide screens.

- Inspector: minimum 320px, maximum half the available workspace width. The map
  retains at least the other half, excluding the 6px separator.
- Tape: minimum 96px, maximum 45% of available height while retaining at least
  360px for the main workspace. Its filter/header row stays fixed; event rows scroll.
- Separators support pointer capture, visible focus, orientation and current-size
  accessibility metadata. Arrow keys move 10px; Shift + Arrow moves 40px.
  Left/Up enlarges the trailing pane; Right/Down shrinks it.
- Double-click a divider or press Home on it to reset that pane. **Diagnostics >
  Reset layout** restores both defaults and clears the saved preference.
- Dimensions are stored locally under `warehouse-swarm-operation-layout`, using
  `rightPanelWidth` and `eventTapeHeight` in pixels. Reload restores them; viewport
  changes clamp the visible dimensions. Invalid values fall back to defaults.
  If browser storage is blocked, resizing still works for the current session.
- `ResizeObserver` recalculates the SVG bounds without resetting zoom or selection.
  Fit, route coordinates and robot hit targets continue to use the same logical grid.
  At maximum tape height, fleet labels are necessarily smaller; zoom or select a
  robot for details. Short/narrow screens use the existing scrollable stacked layout.

### Page structure and visual system

OperationCentre uses a black and graphite control-room presentation. The structure
is intentionally dense and functional rather than card-based:

```text
TOP NAVBAR
  SwarmOS | centered Operations / Crisis / Analytics / Dashboard / Overview links
STATUS / ACTION ROW
  run metadata, model/seed/step, connection state and simulation controls
TELEMETRY STRIP
  delivery, movement, charging, idle, blocked, crisis, LLM and battery KPIs
OPERATIONS WORKSPACE
  WAREHOUSE FLOOR | 6px RESIZER | CONTEXT PANEL
  map toolbar, SVG warehouse, legend | crisis/robot/events tabs
6px EVENT RESIZER
EVENT TAPE
  category filters, follow state and bounded event rows
TERMINAL FOOTER
  local-first status and data freshness
```

The workspace is implemented as a resizable split pane. The warehouse is the main
visual surface; the context panel is the inspector and crisis control surface; the
event tape remains a separate lower reading surface. On narrow screens these regions
stack vertically without changing their controls or data contracts.

#### Base palette

Large surfaces use neutral black and graphite so semantic colors remain reserved for
state and operator attention. The stylesheet uses these primary combinations:

| Role | Color | Usage |
|---|---|---|
| Root / warehouse | `#030405` | Page background, map viewport and floor |
| Header | `#050607` | Command header and warehouse section chrome |
| Command / KPI | `#070809` | Status/action row, telemetry strip and event tape |
| Context panel | `#0B0D0F` | Inspector, crisis panel and dialogs |
| Raised control | `#0F1113` | Buttons, active filters and elevated controls |
| Hover | `#15181B` | Control hover state |
| Soft border | `#171A1E` | Quiet separators and event row rules |
| Normal border | `#202428` | Section boundaries and panel dividers |
| Strong border | `#343A40` | Shelves, focused controls and stronger outlines |

#### Text and semantic colors

| Role | Color | Usage |
|---|---|---|
| Primary text | `#F4F6F8` | Headings, values and high-contrast labels |
| Secondary text | `#B8BEC5` | Supporting labels and event details |
| Muted text | `#68717B` | Inactive metadata, quiet states and timestamps |
| Disabled text | `#464C53` | Disabled controls |
| Cyan | `#5BD8F4` | Selection, active tabs, routes and moving robots |
| Green | `#50D890` | Healthy state, delivery, completion and connected status |
| Amber | `#E8B34F` | Charging, charger cells and charging warnings |
| Orange | `#F08A45` | Blocked movement and deadlock attention |
| Red | `#EF6673` | Critical robot state and errors |
| Crimson | `#D94A5F` | Crisis-specific overlays and active crisis information |
| Violet | `#9B8CFF` | Configured LLM, Nemotron/Gemma, LangGraph and orchestration state |

The UI does not use gradients or large colored panels. Active KPI values receive a
semantic color and a thin bottom rail, while zero or healthy values recede into the
neutral palette. Selected tabs use transparent graphite backgrounds with a thin cyan
underline rather than filled blue blocks. Event rows remain neutral; only category
labels are colored: CNP cyan, CHARGING amber, DEADLOCK orange, LLM and ORCH violet,
CRISIS crimson, and SYSTEM gray.

#### Warehouse encoding

The SVG floor uses near-black aisles and map cells. Shelves use graphite fill
`#24282C` with strong graphite stroke `#343A40`; chargers use dark amber fill with
an amber outline. Robot markers combine neutral geometry with state color: cyan for
moving, green for delivery, gray for idle, amber for charging, orange for blocked,
and red for critical or energy-stopped. A selected robot becomes black with a strong
cyan border and restrained glow. Selected routes are cyan, charging routes are amber,
and crisis cells use translucent crimson fill with a crimson border.

### Data freshness and interpretation

Core status/robots/tasks poll on a non-overlapping 400ms-after-response loop;
agent/event/orchestration summaries poll every 1000ms after response. Status is checked
at both ends of a core batch to discard resets/grid revisions that cross the reads.
The grid refreshes on run/revision changes, including external resets and collapses.
Polling keeps the last good map during failures and shows stale/reconnecting/error
indicators. Failed endpoints are logged once per failure transition, not every poll.

- Model identity is shown only once an actual model event exposes it; the API does
  not currently provide configured model metadata before inference.
- LLM/fallback values count requests and completed orchestrator fallback sessions in
  the **retained event window**, not lifetime totals. Routine deterministic traffic
  fallback is excluded from that KPI. The tape still shows its actual events.
- Blocked counts come from agent `path_blocked` beliefs and exclude intentional
  holds/charging/idle. They are not a count of persistent reciprocal deadlocks.
- Charging includes travel. "At bay" requires a charger cell and an arrived route.
  A route endpoint can be an intermediate recovery leg, not the eventual delivery.
- Independent REST endpoints are not one atomic fleet snapshot; summaries may lag
  movement. The freshness footer makes that visible. Known crisis overlays use
  available crisis state/events; other structural obstacles remain ordinary shelf cells.
- No synthetic telemetry, cloud model probe, external fonts, new frontend framework,
  or WebSocket dependency is used.

### UI verification

```powershell
node --check frontend/js/OperationCentre.js
node --test tests/operation_centre.test.cjs
python311\python.exe -m pytest -q
# Optional visual checks; installs browser tooling only, not an app dependency:
python311\python.exe -m pip install playwright
# In a separate terminal, start a DEDICATED test API (the browser check resets it):
python311\python.exe -m uvicorn backend.api:app --app-dir . --port 8010 --no-access-log
python311\python.exe tests/live_operations_browser.py --url http://127.0.0.1:8010
```

The optional script uses installed Microsoft Edge in headless mode. It checks real
controls, movement, charging, selection, manual collapse, reset and diagnostics.
It also drags both separators at all three desktop sizes, checks large-map, wide-
inspector and tall-tape configurations, saved-layout reload, viewport clamping,
keyboard resizing, reset, corrupt storage and the narrow-screen fallback.
Completion, malformed API response/recovery and HITL transitions use explicitly
identified browser-only response fixtures; these do not claim real model execution.
Screenshots and `browser-checks.json` go to `evaluation_results/ui/` by default.
Desktop layout was visually checked at 1440x900, 1366x768 and 1920x1080 with no
page-level overflow; context panels and the event tape scroll internally. Narrow
screens use a stacked, scrollable layout. The UI pass passed 170 Python tests
(one existing Starlette/httpx warning) and 12 Node tests.

---

### Agent Analytics (Page 3)

The operational workspaces and architecture guide answer complementary questions:

| Page | Question |
|---|---|
| `/OperationCenter` — Live Operations | What is happening? |
| `/CrisisOrchestration` — Crisis desk | What did the AI do? |
| `/AgentAnalytics` — Agent Analytics | Why is the swarm behaving this way? |
| `/SystemOverview` — Architecture guide | How does the system work, and where is AI allowed to act? |

Page 3 is read-only, with dedicated HTML/CSS/JavaScript. It provides a filterable,
sortable fleet browser; selected-agent battery/task/route/hold state; published
CNP messages and events; a task portfolio; and current/recent anomalies. Desktop
panels scroll internally. Pages 1 and 2 retain their controls and behavior.

Delivery progress and blocked-position/presence heatmaps retain up to 120
distinct-step browser samples. Presence is not proof of congestion. Charger bays
show current occupancy and inbound charging-route endpoints, distinguishing
travel from charging at a bay. The low-battery filter (<30%) is a display threshold,
not a change to charging policy. Evidence does not represent hidden reasoning.

One non-overlapping polling cycle refreshes state about every second and evidence
about every two seconds. Existing `/simulation/status`, `/robots`, `/tasks`,
`/agents/status`, `/tasks/agents`, `/agents/message-history`, `/auction/logs`,
`/orchestrator/events` and `/warehouse/grid` supply all data. No data API was added.
Events/messages are capped at 1,000 each, sampled changes at 1,200 and visible trace
rows at 100. Reset clears selection/history and refreshes the grid. API failures
retain the last valid view with a stale indicator. Reload loses browser samples;
separate REST snapshots can differ slightly. Published messages do not prove
consumption, and release evidence is a retained window rather than a lifetime count.

Verification (browser check resets its dedicated server):

```powershell
node --check frontend/js/AgentAnalytics.js
python311\python.exe -m py_compile backend/api.py
python311\python.exe -m pytest -q tests/test_api_evaluation.py
python311\python.exe -m uvicorn backend.api:app --port 8012 --no-access-log
# Separate terminal; installed Playwright + Microsoft Edge:
python311\python.exe tests/agent_analytics_browser.py
```

The browser check covers navigation, real fleet/tasks, selection, filter/sort,
polling, reset, outage/recovery and desktop bounds at 1366×768, 1440×900 and
1920×1080. Screenshots go to `evaluation_results/agent_analytics/`.

### Crisis + Orchestration desk (Page 2)

`/CrisisOrchestration` answers **"A crisis happened. What did the AI actually do?"**
Dedicated `frontend/CrisisOrchestration.html`, `frontend/css/CrisisOrchestration.css`
and `frontend/js/CrisisOrchestration.js` retain the same black/graphite palette,
compact typography, neutral row surfaces and semantic accents as Live Operations.
The page consumes existing state/event/control APIs and the fields documented in
[Section 17](CRISIS_AND_LLM_ORCHESTRATION.md#17-structured-crisis-orchestration). It does not implement a second orchestrator or invent historical plans.

- **Live telemetry:** active incident, queue/capacity, affected robots, current graph
  node, validation readiness, latest observed request latency, review/retry/fallback.
  These KPIs describe the live session; the workspace below describes the selected incident.
- **Incident timeline:** active, queued and recent entries from current state and
  retained events. Selection persists across polls; **Follow active** returns to
  the live incident. Unknown queued type/location is labeled as not retained.
- **Impact map:** real `grid[y][x]`, crimson incident cells/affected robots, subdued
  unrelated fleet, amber chargers, cyan selection and current route (amber when
  charging). The default camera fits affected positions/cells; **Full floor** toggles
  the complete warehouse. Geometry remains square. Selecting a robot shows its
  current task/battery/position, available route, task endpoints and proposed waypoint.
  Historical incidents explicitly show **current positions**, not a recorded replay.
- **Pipeline:** actual `diagnose`, `generate_plan`, `validate`, `execute` nodes and
  completion evidence. Parsing is part of generation, not an invented graph node.
  HITL is the interrupt before execution; fallback and regeneration appear as
  explicit branches. A schema failure does not claim safety validation was reached.
- **Plan + safety:** configured Ollama/OpenRouter provider and model, request/response
  timestamps, HTTP status, measured latency, sanitized provider failures,
  parsed actions with parameters/reasons, deterministic score, issues/codes,
  available validator component ratios and execution receipts. **PROPOSED** and
  **ACTION_OK** are distinct. Full prompts are not displayed.
- **HITL:** fixed review controls remain visible while evidence scrolls. Approve or
  Reject/Regenerate submits the existing `approved` + `plan_id` contract after a
  fresh identity check. Historical, invalid, stale and already-submitted plans
  cannot be approved. Server-side live validation and HTTP 409 handling remain intact.
- **Trace/outcomes:** up to 200 trace rows for the selected incident, with
  LIVE/PAUSED-FOLLOW reading behavior. Graph completion is distinct from the
  simulator's first-movement recovery event; fallback is never labeled successful
  model execution. Recent outcomes show only recorded durations/action counts.
- **Controls:** Start/Pause/Step/confirmed Reset and a confirmed typed incident
  selector for obstruction, immobilization, charger outage or urgent order. The
  run-budget readout distinguishes submitted, terminal and remaining slots.
  Natural deadlocks remain persistence-gated. Navigation also includes Dashboard
  and System Overview.
- **Idle/failure:** SYSTEM NOMINAL, no retained request/plan and an idle pipeline
  form the ready state. Failure codes, validator rejection, retries, fallback and
  executor failure remain visible. API failures preserve the last map and disable
  mutation controls; completion does not imply disconnection.

The desk uses one non-overlapping polling batch every 1,000ms after the previous
response. It reuses `/simulation/status`, `/orchestrator/state`,
`/orchestrator/events?limit=1000`, `/robots`, `/tasks` and `/warehouse/grid`.
Status/run/revision checks discard batches crossing a reset or grid change. Grid
changes refresh the floor. No new data endpoint or backend history store is added.

**History limits:** the server event ring is bounded. The tab retains at most 2,000
observed events and 40 incidents, including observed plan snapshots. Reload loses
those browser-only snapshots; full historical action parameters may be unavailable
even when parsing/execution events remain. Missing stages are "not observed", not
assumed successes. Current configured provider/model comes from state even before
the first request; historical provider/model is shown only when retained evidence
identifies it. Configuration does not prove a successful response.
Separate REST snapshots can differ by a few simulation ticks.

Verification commands (browser check resets its dedicated test server):

```powershell
node --check frontend/js/CrisisOrchestration.js
node --test tests/crisis_orchestration.test.cjs tests/operation_centre.test.cjs
python311\python.exe -m pytest -q tests/test_crisis_page.py tests/test_api_evaluation.py tests/test_orchestrator.py
python311\python.exe -m uvicorn backend.api:app --app-dir . --port 8011 --no-access-log
# Separate terminal; optional installed Playwright + Microsoft Edge:
python311\python.exe tests/crisis_orchestration_browser.py --url http://127.0.0.1:8011
```

The browser script checks actual routes, both navigation directions, controls,
grid/robots and manual collapse. Explicit browser-only fixtures cover queue,
local-model telemetry, structured plans, validation/rejection, HITL payloads,
regeneration, execution, failure codes, bounded trace and API outage/recovery.
`test_crisis_page.py` separately exercises the real override endpoint and LangGraph
rejection/regeneration/approval flow with an injected model client. These fixtures
do not claim live Ollama success. Screenshots and `browser-checks.json` are written
to `evaluation_results/crisis_desk/`; desktop checks cover 1366x768, 1440x900 and
1920x1080. Evidence panels scroll internally; narrow screens stack.

## System Overview workspace

`GET /SystemOverview` is the recruiter-facing architecture guide. Dedicated
`frontend/SystemOverview.html`, `frontend/css/SystemOverview.css` and
`frontend/js/SystemOverview.js` use the same black/graphite SwarmOS design.
Navigation links to it from all existing workspaces. The guide explains the
coordination problem, CNP communication, deterministic movement, exceptional
LangGraph recovery, the parser/validator gate, operator review, fallback and the
five executable actions. Its small live readout polls existing status/state APIs
every five seconds; it creates no additional backend storage or telemetry history.
Unavailable API telemetry leaves the static architecture story readable.

## Developer Centre

`GET /DeveloperCentre` polls `GET /developer/logs` and displays application
`warehouse` logger records at INFO or higher, plus successful per-cell robot
moves at DEBUG. CNP CFPs, received proposals, awards, task releases/completions,
charging, path errors, crises, LangGraph/LLM stages, validation, HITL, executor,
fallback, and exception tracebacks are retained with credential-like values
redacted. Each run retains up to 100,000 records in memory; simulation reset
starts a fresh console history. Use **LOAD EARLIER** to page through older
records and **COPY ALL LOGS** to copy the complete retained run history,
independent of the visible filters. If the run exceeds the retention cap, the
console marks the history as truncated. Successful cell moves are captured only
in the Developer Centre and do not flood the normal terminal output.

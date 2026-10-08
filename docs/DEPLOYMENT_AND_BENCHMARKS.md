# Deployment and Benchmarks

This guide contains setup, runtime constraints, tests, evaluation, deployment configuration, and dated verification evidence.

[Back to the project hub](../README.md) · [Architecture and agents](ARCHITECTURE_AND_AGENTS.md) · [Operations and workspaces](OPERATIONS_AND_WORKSPACES.md) · [Crisis and LLM orchestration](CRISIS_AND_LLM_ORCHESTRATION.md)

## Current reference snapshot (2026-10-08)

SwarmOS is a single-process, in-memory warehouse simulator. The normal factory
creates **40 robots, 120 tasks, a 50×30 grid and eight charging bays**. Routine
CNP, navigation, collision recovery and charging are deterministic. LangGraph
uses the selected LLM only for exceptional recovery, with strict parsing,
deterministic validation, optional HITL and a safe executor/fallback boundary.

- **Hosted model verified:** `nvidia/nemotron-3-super-120b-a12b:free` through
  OpenRouter returned HTTP 200 and one schema-valid HOLD action in 3.047 seconds.
  This was a transport/schema smoke check, not a full live-model completion run.
- **Local alternatives:** `LLM_Provider=gemma` selects `gemma4:12b`;
  `mistral` selects `mistral:latest`. Change the provider and restart the backend.
- **Incident policy:** five supported kinds, one shared **six-slot run budget**
  by default, and automatic attempts every 200 steps. Manual admissions consume
  that budget and postpone the next automatic attempt. Queued effects wait for
  activation and never pin robots.
- **Latest recorded verification:** 193 Python tests and 25 frontend DOM tests
  passed. A seed-42 offline/fallback run delivered 120/120 tasks in 37.844 seconds
  across 1,768 steps, with six admitted incidents. These are dated local results,
  not a guarantee for every seed, provider, machine or hosting platform.

| Need | Read |
|---|---|
| Install, configure, and run | [Deployment and benchmarks](DEPLOYMENT_AND_BENCHMARKS.md#11-running-the-project) |
| Agents, CNP, and movement | [Architecture and agents](ARCHITECTURE_AND_AGENTS.md#2-multi-agent-architecture) |
| APIs and operator workspaces | [Operations and workspaces](OPERATIONS_AND_WORKSPACES.md) |
| Crisis lifecycle, budget, actions, and validation | [Crisis and LLM orchestration](CRISIS_AND_LLM_ORCHESTRATION.md#17-structured-crisis-orchestration) |
| Tests and benchmarks | [Tests](DEPLOYMENT_AND_BENCHMARKS.md#18-tests) · [Evaluation harness](DEPLOYMENT_AND_BENCHMARKS.md#19-evaluation-harness) |
| Docker and Render configuration | [Container configuration](DEPLOYMENT_AND_BENCHMARKS.md#21-container-configuration-and-deployment-readiness) |
| Latest provider and acceptance evidence | [Evidence](DEPLOYMENT_AND_BENCHMARKS.md#latest-nemotron-incident-and-acceptance-evidence) |

Sections 15 and 20 retain useful postmortems and earlier measurements. Dated
verification notes describe the code/configuration tested at that time; use the
current configuration table and latest evidence section for current behavior.
Source code and `.env.example` are authoritative when documentation drifts. Keep
`.env` and API keys private; this documentation contains no real credentials.

### Contributor handoff

Read [`AGENTS.md`](../AGENTS.md) when present. Use Code Review Graph for focused dependency/impact
navigation when available, but verify its freshness and read the current source
for affected contracts. An older graph or dated test result is not authoritative
for new working-tree changes.

- Routine task allocation belongs to TaskAgent/RobotAgent CNP, not a new central
  scheduler. Preserve `grid[y][x]`, A* integrity checks, physical occupancy,
  movement energy and safe task release.
- Production incident injection goes through `SimulationEngine.trigger_crisis()`.
  Its compatibility wrapper `trigger_warehouse_crisis()` selects structural
  collapse. Direct runner invocation is used in isolated graph tests; it bypasses
  engine-managed budget/effect admission and should not replace those entry points.
- Provider HTTP handling belongs in `llm_client.py`; model selection belongs in
  `core/llm_config.py`. Read OpenRouter `message.content`, not `reasoning` fields.
  Preserve sanitized diagnostics and never print `.env`, keys or authorization headers.
- Keep inference outside simulation locks. Only active incidents may pin robots;
  all terminal/reset paths must clear pins and temporary faults before activating
  the next queued request. Invalid plans must never execute, even after approval.
- Run relevant regressions after behavior changes. Movement/charging/incident
  changes also need the seeded completion acceptance run and its real delivery
  evidence. Record configuration, injected faults and dates with results.
- Screenshots and `evaluation_results/` are generated local artifacts, not
  guaranteed files in a clean clone. Use the documented commands to regenerate them.



## 11. Running the Project

### Prerequisites

- Python 3.11. The optional `python311/` interpreter is local tooling, not included in a clean clone.
- On Windows with that interpreter, install runtime packages with `python311\python.exe -m pip install -r requirements.txt`. Otherwise create a virtual environment with `python3.11 -m venv .venv`, activate it, and use `python -m pip install -r requirements.txt`. Install `requirements-dev.txt` for pytest. Node.js is only needed for optional frontend syntax/DOM checks; it is not an application runtime dependency.
- For local inference, **Ollama** on port `11434` needs the selected model installed. For hosted inference, set a private OpenRouter key and an explicit model slug. Runtime network/model failures activate logged deterministic fallback. Missing OpenRouter key/model is a startup configuration error. Automated inference tests use injected clients; no live model request is needed for pytest.

### Select the Crisis LLM Provider

Set `LLM_Provider` in the project `.env` file. The setting is read when the backend starts and selects exactly one LangGraph inference client. Copy `.env.example` to `.env` first. The example selects Gemma; when omitted, the provider defaults to Mistral. Keep `.env` private and never commit a real API key.

```dotenv
# Use Mistral
LLM_Provider=mistral

# Or use Gemma 4 12B locally
# LLM_Provider=gemma

# Or use OpenRouter (uncomment and set the key privately)
# LLM_Provider=openrouter
# OPENROUTER_API_KEY=your-key
# OPENROUTER_MODEL=nvidia/nemotron-3-super-120b-a12b:free
# OPENROUTER_URL=https://openrouter.ai/api/v1/chat/completions
```

Provider mappings:

| `LLM_Provider` value | Backend/model |
|---|---|
| `mistral` | Ollama `mistral:latest` |
| `gemma` | Ollama `gemma4:12b` |
| `openrouter` | OpenRouter `OPENROUTER_MODEL` (explicit model slug required) |

Use one active `LLM_Provider` line at a time. Switching to `gemma` requires reachable Ollama; switching to `openrouter` requires `OPENROUTER_API_KEY` and an explicit `OPENROUTER_MODEL`. Those cloud settings are ignored by Ollama mode. Restart the API after changing the provider. The example now uses `nvidia/nemotron-3-super-120b-a12b:free`, which passed a real structured-plan smoke check on 2026-10-08. **The earlier check returned HTTP 404 for `openai/gpt-oss-120b:free`: OpenRouter reported that model is unavailable for free.** The application never switches to a paid model automatically. Catalog pages and past availability do not guarantee current inference access.

### Start the LLM Sidecar
For local model-assisted orchestration, start Ollama:
```bash
ollama serve
```

The configured model must already be available locally. To keep a model loaded, you may also run `ollama run mistral` or `ollama run gemma4:12b` in a separate terminal.

### Start the API Server

```bash
python311\python.exe -m uvicorn backend.api:app --app-dir . --reload
```

### Access Points

The `--reload` command above is for local development. A non-reloading launch is
`python -m uvicorn backend.api:app --app-dir . --host 0.0.0.0 --port 8000 --workers 1`.
Always keep one worker: independent workers would each own a different warehouse.

| URL | Description |
|---|---|
| `http://127.0.0.1:8000/` | API root |
| `http://127.0.0.1:8000/docs` | Swagger UI |
| `http://127.0.0.1:8000/dashboard` | Live dashboard |
| `http://127.0.0.1:8000/OperationCenter` | Live Operations terminal (`/OperationCentre` also supported) |
| `http://127.0.0.1:8000/CrisisOrchestration` | Crisis + Orchestration desk |
| `http://127.0.0.1:8000/AgentAnalytics` | Read-only fleet/agent inspector |
| `http://127.0.0.1:8000/SystemOverview` | Architecture story, safety gates and current run facts |

---
## 12. Known Limitations

- Collision avoidance is step-local only. No multi-step path reservation. The crisis validator adds a read-only short-horizon prediction, described below.
- `path.pop(0)` is O(n). Acceptable at current scale.
- Orchestration uses structured Python logging; some legacy pathfinding diagnostics retain searchable console tags.
- `constants.py` is unused.
- No persistence. Server restart loses all state.
- No WebSocket support. The legacy dashboard polls every 200ms; Operations uses 400ms core/1s summary loops, Crisis and Analytics use roughly 1s state loops (after responses), and Overview refreshes its small readout every 5s.
- All operators share one simulation. There is no authentication, authorization or built-in TLS; public hosting needs external access control and HTTPS.
- `AuctionManager` is retained but unused when multi-agent system is active.

---
## 18. Tests

```powershell
python311\python.exe -m pip install -r requirements-dev.txt
python311\python.exe -m pytest -q
python311\python.exe -m pytest -q tests/test_safety.py
python311\python.exe -m pytest -q tests/test_orchestrator.py
node --check frontend/js/OperationCentre.js
node --check frontend/js/dashboard.js
node --check frontend/js/CrisisOrchestration.js
node --check frontend/js/AgentAnalytics.js
node --check frontend/js/SystemOverview.js
node --test tests/operation_centre.test.cjs tests/crisis_orchestration.test.cjs
python311\python.exe -m compileall -q backend tests
```

Pytest config includes the project root for the bundled isolated Windows Python.
Tests mock/inject the model boundary; **Ollama is not required**. Coverage includes
A* and obstacle regressions, battery/arrival guards, CNP ownership and release,
strict parsing, deterministic validation, action staging, real control effects,
HITL approval/rejection, bounded retries, fault fallback, crisis queuing, concurrent
reads/reset cancellation, API errors, seed replay, metrics, and benchmark artifacts.
The older `test_repairs.py` regressions are retained and migrated to the new schema.
Node rendering tests exercise Live Operations with a minimal DOM test fixture;
they do not replace a real-browser visual test.

Latest recorded result (2026-10-08): **193 pytest tests** and **25 frontend DOM
tests passed**. `tests/test_llm_providers.py` covers provider selection, request
shape, error classification and secret redaction. `tests/test_crisis_budget.py`
covers shared-budget admission, manual postponement, queued physical effects,
fault cleanup, emergency CNP release, persistence gating and energy-safe incidents.
`tests/test_system_overview.py` checks the guide route/assets/navigation and API
contracts. These tests use mocks; run `backend.evaluation.llm_smoke` explicitly
for a real provider check, which can consume quota/cost. Section 22 separates
live smoke evidence from automated safety/execution verification.

Local-inference scheduling regressions are in `tests/test_local_llm_scheduling.py`:
transient/persistent pairs, asynchronous recovery timing, real narrow-aisle recovery
failure, active/pending deduplication, queue capacity, stale dropping, active-only
holds, failure/reset cleanup, intentional waits, and structural backpressure.
A `threading.Event` holds fake inference open for 1,000 simulation ticks while
asserting continued work, bounded queue depth, and zero orphaned holds. A separate
seed-42 test runs 3,000 ticks with offline inference, all 40 robots and 120 tasks,
scheduled incidents, occupancy/orthogonal-movement/battery checks, and progress
assertions. Its evaluation barrier is explicit; it is not used in the slow-model
test or production.

```powershell
python311\python.exe -m pytest -q tests/test_local_llm_scheduling.py
# Retain health JSON files under a chosen test-output directory:
python311\python.exe -m pytest -q tests/test_local_llm_scheduling.py --basetemp evaluation_results/local_llm_tests
```

The tests write `slow_llm_health.json` and `seed42_health.json` beneath their pytest
temporary directories. The scheduling pass on 2026-09-16 passed 150 Python tests. The final performance-pass verification is recorded in [Section 20](#20-completion-acceptance-and-earlier-performance-results). Starlette's installed TestClient/httpx integration emits one
deprecation warning.

The real `mistral:latest` smoke request reached the retained timeout (about 62
seconds measured end-to-end). During that wait the simulation advanced 1,903 ticks
and completed 45 tasks; fallback completed with zero orphaned holds. This verified
real local failure handling, not successful model planning. Gemma generation had not been tested at that stage; [Section 20](#20-completion-acceptance-and-earlier-performance-results) records the later real-model tests. These are smoke observations, not comparative performance claims.

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
charger congestion and disconnected tasks still constrained throughput in that
**pre-performance baseline**. [Section 20](#20-completion-acceptance-and-earlier-performance-results) retains the earlier performance-pass
results; Section 22 records the latest six-slot acceptance result.
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
avoid inference. ON uses the **selected real provider** (Ollama by default);
fault injection is explicit.
No successful model responses or performance improvements are fabricated.

| Scenario | Configuration |
|---|---|
| `normal` | Existing 40-robot depot and 120 tasks; automatic incident attempts disabled in fixed-step comparison mode |
| `high_workload` | Same warehouse with 240 tasks |
| `depot_congestion` | Deliveries converge at one depot cell |
| `battery_stress` | Initial battery 45 |
| `aisle_collapse` | One seeded 3-cell collapse requested before evaluation tick 20 |
| `critical_order` | CRITICAL task injection before tick 20 |
| `llm_offline` | Aisle-collapse schedule plus injected unavailable model |
| `llm_malformed_response` | Aisle-collapse schedule plus malformed model text |

`--fault` also accepts `LLM_TIMEOUT`. A separate seeded scenario RNG orders eligible
cell groups. Before tick 20, the collapse scenario selects a group crossing a real
active route and passing the engine's admission checks. Candidate order matches
across modes; selected coordinates can differ if the worlds have diverged. They
are recorded as `requested_crisis_cells` so comparisons can be checked. No eligible
group means no fault injection and null requested cells. A ValueError from an
attempted injection emits `SCENARIO_FAULT_SKIPPED`; that counter is not a count of
every candidate rejected during selection. Scenarios reuse the real engine and
never crush a robot merely to force an LLM call.

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
| `crisis_count` | Managed incidents admitted through the engine across all five kinds; manual/automatic/natural requests share the budget |
| `automatic_crises` | Accepted automatic incidents, not all scheduled attempts or all crisis types observed |
| `deadlock_escalations` | Persistent-pair detections; ordinary three-strike recovery remains separate from LLM crisis admission |
| `crises_recovered`, `crises_unresolved` | Activated incidents with affected robots: all affected robots subsequently moved at least once, or remain open. Zero-affected/stale requests have no physical recovery record |
| `mean_crisis_recovery_steps` | Mean steps to that first-movement recovery definition; not restoration of all task throughput |
| `llm_call_count`, `llm_success_count`, `llm_failure_count` | Requests, parseable/schema-valid responses, and transport/parse/schema/internal inference failures |
| `llm_fallback_count`, `llm_fallback_rate` | Completed orchestrator sessions using fallback; rate = that count / `ORCH_COMPLETE` count. It is a session-level rate, not failures / HTTP requests; completions with no model call can be in the denominator |
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
- Runtime model quality is hardware/provider dependent and requires actual
  provider evaluation; fault-injected smoke runs establish plumbing, not LLM performance.
- Unreachable chargers, depleted robots, and disconnected pickups can require
  operator intervention. The simulator does not implement physical robot rescue.
- The bounded queue deduplicates deadlock pairs but does not coalesce structural
  incidents. At capacity, admission is rejected and deterministic handling remains.
  Reset logs cancellation instead of carrying work into a different warehouse.
- The detector recognizes reciprocal robot pairs, not arbitrary larger wait cycles.
  Recovery HOLD/replan pauses do not count toward persistence or create incidents.
- Active affected robots may wait through model retries/HITL; pending work never
  pins robots. Reset invalidates results but cannot instantly cancel work already
  being computed by the selected inference service.
- The old 3,000-step scheduling baseline finished 31/120. Latest completion acceptance is recorded in Section 22, with earlier results in [Section 20](#20-completion-acceptance-and-earlier-performance-results); neither is a universal deadlock-freedom guarantee.
- Frontend polling remains. The Live Operations redesign is described in [Section 13](OPERATIONS_AND_WORKSPACES.md#13-live-operations-terminal);
  no WebSocket/SSE migration is included. Container configuration and its static
  audit limits are documented in [Section 21](#21-container-configuration-and-deployment-readiness).

### Model-status probe troubleshooting

No frontend/backend source in this repository requests `/v1/models`. A 404 for that
path indicates an unsupported request; the originating external client was not
identified from repository code. This simulator exposes no OpenAI-compatible model
API. Ollama's native model-list endpoint is `http://localhost:11434/api/tags`;
model generation uses the configured `/api/generate` URL.
## 20. Completion Acceptance and Earlier Performance Results

The harness and safety invariants below remain current. The measured Gemma/offline
results in this section are historical **2026-09-17** runs with the then-current
three-collapse schedule. Section 22 records the **2026-10-08** six-slot incident
run and Nemotron smoke check. Do not present the older timing/LLM counts as tests
of the current model or budget.

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
escalations, and LLM timeouts to the metrics in [Section 19](#19-evaluation-harness). Charging entries count
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

That performance pass retained movement drain and charge speed, added feasible
recharge itineraries, separated eight service bays, improved CNP bids/runner-up
selection, and capped automatic collapses at three at that time. The current
shared six-slot policy also protects endpoints, connectivity and feasible energy
itineraries ([Section 17](CRISIS_AND_LLM_ORCHESTRATION.md#17-structured-crisis-orchestration)). Three-strike recovery retries after unsuccessful attempts.
Safe retreats can reach a passing space up to three cells away using existing A*;
robots still move one cell per tick. Parked robots clear nearby passing space.
A true narrow corridor without a passing space still holds/escalates. A per-move
escape-energy check prevents congestion detours from stranding robots.

This was necessary to handle threaded timing variations: an intermediate version
passed an individual benchmark but stalled at 119/120 in the full suite. The final
charger-entrance retreat and idle-clearance regressions cover that failure.

### Measured results

Acceptance runs recorded on 2026-09-17, seed 42:

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
is claimed. Gemma was used for the 2026-09-17 real completion acceptance.
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

The 2026-09-17 performance-pass Python suite passed **169 tests** (one existing Starlette/httpx
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

---
## 21. Container Configuration and Deployment Readiness

### Deployment shape

The Dockerfile packages Python 3.11, pinned runtime dependencies, `backend/` and
`frontend/`. It runs Uvicorn as an unprivileged user with **one worker**, without
reload. Templates/static paths resolve from the project directory, and browser
requests use relative API URLs. Node.js and the optional Windows interpreter are
not needed inside the image. Tests, `.env`, local Codex/graph data and generated
evaluation artifacts are excluded from the build context.

Compose defines three services on the same `warehouse-network`:

| Service | Purpose |
|---|---|
| `warehouse-swarm` | FastAPI on container port 8000; published to `127.0.0.1:8000` by default |
| `ollama` | Local inference on internal port 11434; model weights persist in `ollama_data` |
| `ollama-setup` | One-off pull of the selected local model; no-op when `LLM_Provider=openrouter` |

The pull helper maps `mistral` to `mistral:latest` and `gemma` to `gemma4:12b`,
case-insensitively. `openrouter` skips the pull. Other local model names are passed through. It does not
mount a second model store or assume preinstalled host models are in the volume.
The app waits only for the Ollama service to start, **not** for model readiness:
failed downloads, unavailable inference or a missing model still produce logged
deterministic fallback. For a live-AI demo, finish the pull before injecting a crisis.

### Configuration and networking

Copy `.env.example` to `.env` and set one `LLM_Provider` value. Compose explicitly
passes the supported seed, orchestration, queue, validation, HITL and crisis
settings plus OpenRouter key/model/URL; a Compose `.env` file alone does not export
those values to a container. When OpenRouter is selected, Compose still starts
the Ollama sidecar but does not use it for inference; use a native Render Python
Web Service for a hosted-only deployment.
Absent a provider setting, both the app and helper select Mistral.

**Container generation URL:** `http://ollama:11434/api/generate`. The code reads
`OLLAMA_URL`, not `OLLAMA_BASE_URL`. Compose deliberately sets the internal URL,
so the localhost URL in the host-development example cannot override it.
Standalone images can override `OLLAMA_URL` to an accessible Ollama server.
`localhost` inside the app container refers to that container, not the host or sidecar.
OpenRouter mode ignores `OLLAMA_URL` and sends requests only to the HTTPS
`OPENROUTER_URL`.

`APP_BIND_HOST` and `APP_PORT` optionally change the published app address/port.
The default loopback binding is suitable for a local demo or a host reverse proxy.
Ollama is not published to the host. Frontend assets are baked into the image;
there is no deployment-time bind mount hiding packaged templates.

Application liveness uses Python's standard library to request `/`. Ollama
liveness uses `ollama list`, avoiding a dependency on curl in the Ollama image.
Neither check proves model readiness, task progress or successful crisis recovery.

### Operational limits before public hosting

- This is one shared, in-memory simulation. Do not increase worker count or run
  independent replicas behind a load balancer; resets/restarts lose robots, tasks,
  graph checkpoints, messages, crisis queues and event history. Only model weights persist.
- Mutating controls and HITL endpoints have no authentication or authorization.
  Use a trusted network or external authenticated HTTPS reverse proxy before
  exposing the service publicly. TLS is not implemented in FastAPI here.
- Compose defaults to CPU inference and makes no GPU reservation. Allocate RAM,
  disk and, if desired, host-specific GPU access for the selected local model.
  Stored weights are approximately 4.4GB for Mistral or 7.6GB for Gemma; inference
  needs additional memory. The retained 60-second timeout can still trigger fallback
  on slow hardware. Earlier host benchmarks are not container performance results.
- First model download needs outbound access and sufficient disk. The helper can
  fail independently of the app; check its outcome before claiming live inference.
- Python packages are pinned, but `python:3.11-slim` and `ollama/ollama:latest` are
  moving image tags. Pin tested image digests for a reproducible release. This audit
  is not a dependency vulnerability scan or an availability/security certification.
- The source checkout must include `.env.example`, `requirements-dev.txt`,
  `pytest.ini`, `run_benchmark.py` and `tests/`; these existing files are no longer
  excluded by `.gitignore`. The application image intentionally omits test tooling.

### Render Python Web Service with OpenRouter

For a one-instance hosted demo, select the **Python 3** runtime and the branch
containing these changes. Leave Root Directory and Pre-Deploy Command blank.
Use `pip install -r requirements.txt` as Build Command and
`python -m uvicorn backend.api:app --host 0.0.0.0 --port $PORT --workers 1`
as Start Command. Set Health Check Path to `/` (liveness only). Render supplies
`PORT`; do not set it yourself. Keep exactly one worker because every process
would otherwise own a separate in-memory warehouse.

Set these environment variables in Render (mark the key secret):

| Key | Value / purpose |
|---|---|
| `PYTHON_VERSION` | `3.11.16` (fully qualified Python 3.11 security release) |
| `LLM_Provider` | `openrouter` |
| `OPENROUTER_API_KEY` | Your private OpenRouter API key; never add it to Git or README |
| `OPENROUTER_MODEL` | `nvidia/nemotron-3-super-120b-a12b:free` passed the 2026-10-08 structured smoke check; select explicitly |
| `OPENROUTER_URL` | `https://openrouter.ai/api/v1/chat/completions` (optional; this is the default) |
| `ORCHESTRATOR_ENABLED` | `true` to demonstrate model-assisted crisis handling |
| `SIMULATION_SEED` | `42` for reproducible initial warehouse; optional default |
| `EVENT_HISTORY_LIMIT` | `2000` bounded in-memory history; optional default |
| `CRISIS_BUDGET` | `6` total admitted incidents; set explicitly when migrating from an older `.env` with `AUTOMATIC_CRISIS_LIMIT=3` |

`OLLAMA_URL` is unnecessary on Render with OpenRouter. No Ollama container,
pre-deploy migration, database or API-key file is needed. If OpenRouter is
unavailable, crisis plans use the existing deterministic fallback. Missing
`OPENROUTER_API_KEY` is a startup configuration error.

This is **demo deployment**, not authenticated/durable multi-user production:
public visitors can operate reset/HITL endpoints, and service restarts, redeploys
or free-instance idle spin-down reset the in-memory simulation and event history.
Use external access control or add authentication before sharing control access
widely. A live Render deploy and a real OpenRouter crisis should be smoke-tested
before claiming hosted inference works; local mocked tests do not prove that.

### Audit verification (2026-09-27)

The static audit corrected separate Compose networks, the unused Ollama URL
variable, the doubled Ollama pull entrypoint, an unreliable curl health probe,
missing container setting propagation and ignored reproducibility/test files.
No simulation, CNP, movement, graph, validator, executor, HITL or UI behavior changed.

- Python suite: **172 passed**, with one existing Starlette/httpx deprecation warning.
- Frontend DOM suites: **25 passed**; all four JavaScript files passed `node --check`.
- `compileall` passed for `backend` and `tests`; all four pages, the Operations alias,
  their CSS/JS assets and the checked state endpoints returned HTTP 200 via TestClient.
- Compose YAML and network/environment/entrypoint contracts were checked using
  PyYAML, not Docker. `pip check` found no broken installed requirements.
- A pip dry run resolved the pinned requirements against CPython 3.11 Linux x86-64
  wheels. The report is `evaluation_results/dependency-audit.json`; it does not prove
  a container boots or that every platform/environment marker matches Linux.

**No Docker/Compose commands, image builds, containers or deployments were run.**
Docker runtime verification, model downloads and GPU/resource sizing remain release
checks. No new live-model or browser screenshot verification is claimed in this audit.

### OpenRouter provider verification (2026-09-30)

The selected provider now controls the inference transport: Ollama's generation
endpoint for `mistral`/`gemma`, or OpenRouter Chat Completions for `openrouter`.
OpenRouter requests include a strict-compatible action schema and use the same
Pydantic parsing, world validation, HITL and fallback as local inference. The
server never returns the API key to a browser response.

- `python311\python.exe -m pytest -q`: **180 passed**, one existing
  Starlette/httpx deprecation warning. Provider tests mock HTTP and cover
  switching, request shape, valid response parsing, malformed envelopes,
  timeout, rate limit and release of crisis holds after fallback.
- `python311\python.exe -m compileall -q backend tests` and `git diff --check`:
  passed. Compose YAML and OpenRouter environment propagation were parsed
  without running Docker.
- No live OpenRouter or Render deployment was performed. A successful real
  `gpt-oss-120b` plan and the hosted memory/latency budget remain to be verified.

## Latest Nemotron, incident, and acceptance evidence

The live OpenRouter check on **2026-10-08** made one network request with the
configured `openai/gpt-oss-120b:free` model and the actual action schema. It returned
**HTTP 404 in about 703 ms**, with the provider reporting that this model is
unavailable for free and suggesting its paid slug. No usable plan was returned.
The client previously caught its own `PlanError` under `ValueError`, relabelling
that response as invalid JSON; the catch order is now corrected and covered by a
404/redaction/fallback regression. No paid request or second live model call was
made in that check. After the configured model was changed to
`nvidia/nemotron-3-super-120b-a12b:free`, one additional authorized smoke request
returned **HTTP 200 from Nvidia in 3047 ms**, with one valid `HOLD` action parsed
by the actual Pydantic schema. It used the production client's strict JSON Schema
request and compatible-provider routing. This proves transport and plan parsing;
world validation, HITL and execution are covered separately by the automated
integration suite. No model reasoning text or API key was logged or exposed.

Focused regressions are in `tests/test_crisis_budget.py`,
`tests/test_llm_providers.py`, `tests/test_system_overview.py` and the existing
scheduling/throughput suites. The browser check uses a dedicated local server and
mocked inference, never a second real provider request:

```powershell
python311\python.exe -m pytest -q
python311\python.exe -m compileall -q backend tests
node --check frontend/js/SystemOverview.js
node --check frontend/js/CrisisOrchestration.js
node --test tests/crisis_orchestration.test.cjs tests/operation_centre.test.cjs
python311\python.exe tests/system_overview_browser.py
$env:CRISIS_BUDGET='6'
python311\python.exe run_benchmark.py --completion --seeds 42 --fault LLM_OFFLINE --output evaluation_results/release_verification
```

Browser verification covered 1366×768, 1440×900 and 1920×1080, internal story
scrolling without document overflow, navigation, provider-error visibility,
manual budget consumption and a usable API-stale state. Screenshots were inspected;
there were no JavaScript page errors. Artifacts are in
`evaluation_results/system_overview/`. This does not claim successful live inference.

Final non-Docker verification on 2026-10-08: **193 pytest tests passed**, with one
existing Starlette/httpx deprecation warning; **25 frontend DOM tests passed**.
Python compilation, both changed JavaScript syntax checks and `git diff --check`
passed. The final focused crisis-budget suite also passed all **9** tests.

The seed-42 normal completion harness used 40 robots, 120 tasks, an explicit
six-slot budget and injected offline inference. It checked delivery evidence,
occupancy, orthogonal movement, battery range, queue bounds and orphaned holds
throughout the run. Final measured result:

| Measurement | Observed value |
|---|---|
| Genuine deliveries | `120 / 120` |
| Wall-clock time (including setup/checks) | `37.844 seconds` |
| Simulation steps | `1768` |
| Successful moves | `16046` |
| Admitted crises / automatic crises | `6 / 6` |
| Charging events | `419` |
| Task re-auctions | `43` |
| Injected model requests / failures / fallbacks | `6 / 6 / 6` |
| Live model successes in this benchmark | `0`; inference was explicitly offline |
| Orphaned holds in retained health checkpoints | `0` |
| Completion acceptance (<900 seconds) | **PASS** |

JSON/CSV evidence is in `evaluation_results/release_verification/`, including
`benchmark_20261007T195522846547Z.json`. This is a measured local acceptance run,
not a promised Render/Gemma/OpenRouter performance improvement. Earlier failed
checks exposed and led to fixes for an empty charging-route counter and
energy-infeasible incident admission; tests were not weakened to hide them.

This remains an in-memory demo: public controls/HITL have no authentication,
restart clears the run/budget, and the conservative validator cannot guarantee
deadlock freedom or plan usefulness. Free provider availability and hosted
capacity still require operational verification.

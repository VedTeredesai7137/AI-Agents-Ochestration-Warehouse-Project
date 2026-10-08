# Warehouse Swarm / SwarmOS — Comprehensive System Audit

**Audit date:** 2026-10-08. **Scope:** diagnosis only; current working-tree source plus offline analysis of the supplied console export. No simulation, test suite, browser session, Docker operation, deployment, or external model request was run. Application code, configuration, tests, README, and the graph database were not edited during this audit.

## 1. Executive summary

The supplied evidence supports a functioning warehouse run, rather than a crashed or permanently frozen swarm: the completion event reports **120 tasks delivered at step 1898 in 490.703 wall-clock seconds**, and the last health record at step 1900 reports no active crisis, no pending queue, and no orphaned orchestration holds. Those are recorded measurements, not an independent replay or continuous verification of physical invariants.

The most important qualification is that the supplied JSON is **a late-run excerpt**. All **1,947 records** were parsed and analyzed; their logging IDs are contiguous from **38598 to 40544**, but they begin after the run was already well underway. The first retained explicit step is 1211. Consequently, the file cannot reconstruct startup, crises 0001–0003, the start of crisis 0004, or every model attempt in the run.

The aggregate completion record reports **6 admitted crises, 12 LLM request events, and 3 orchestration sessions using fallback**. This contradicts a simple conclusion that only 3–4 model interactions occurred in the entire run. However, 12 request attempts are not 12 distinct successful recovery decisions. The visible excerpt verifies four schema-valid model responses, two rejected safety-validation reports, and two executed plans consisting of **HOLD**, while one visible crisis ends in deterministic fallback. The actual model in all retained model telemetry is **`nvidia/nemotron-3-super-120b-a12b:free` over OpenRouter**, not GPT-OSS or local Gemma.

The primary demonstration problem is the inability to explain causality: a recruiter can see that a graph ended and an action was committed, but cannot reliably reconstruct the diagnosis, exact historical plan, hold duration, affected task, operator tradeoffs, or evidence that the AI action resolved the operational cause. Several limits are deliberate: routine traffic recovery is deterministic, the admission budget is six by default, only one crisis is actively orchestrated, validation establishes execution readiness rather than recovery effectiveness, and HITL offers approve/reject for one candidate plan.

This report identifies **5 confirmed defects**, **10 design/behavior/UX limitations**, **6 observability gaps**, and **3 unverified suspicions**. “Confirmed defect” can mean a deterministically incorrect code path whose occurrence in this particular excerpt is not established; each finding distinguishes that case. **No P0 physical-safety failure is established.** No implementation plans or proposed fixes are included.

### Evidence and navigation integrity

- Primary file: [public/warehouse-console-2026-10-08T16-22-48.413Z.json](public/warehouse-console-2026-10-08T16-22-48.413Z.json), 615,893 bytes; SHA-256 `673e0476ff85229019c76b4a991a065f3c7522c6155a65cb6fa2c63dddbb14f5`.
- Every record was processed for tags, severity, run identity, IDs, timestamps, explicit steps, crisis/plan identity, latency, warnings, recovery durations, and task completions. No duplicate IDs or internal ID gaps were found; retained explicit step values never move backward.
- One retained run ID: `ccb3f6c04783`. Timestamps in this report are UTC; console-row IDs identify evidence within the JSON array. A console ID is not the structured `event_id` used by the event API.
- Code Review Graph was queried first for review context, impact radius, dependencies, and runner symbols. It identifies the engine, runner, API, frontend workspaces, and related tests, but was built at `ab2eeaab7587f918b76a5c068f53282fdc8839ca`; current HEAD is `5dbaf277d471bbc0963e57960f3d98239754ac40`, with additional uncommitted changes. Its older node ranges/types were not treated as current truth. The database was not rebuilt. Current source supplied the line references below.
- Read the root README/AGENTS, relevant crisis/workspace documentation, and the Interface Design skill for state clarity, hierarchy, and evidence-based UX assessment. Existing documentation already describes several deliberate limits, including terminal handling versus movement recovery and admission latching under backpressure.
- The confidential `.env` was not inspected. Source defaults are labeled as defaults; effective settings not present in the excerpt are not assumed.

## 2. Simulation timeline reconstructed from the complete supplied JSON

There is no hard-coded 2,000-step termination in the inspected API loop. `SimulationEngine.step()` advances and detects task completion; the autonomous API loop continues until its stop event, cancellation, or failure. See `backend/api.py:127` (`simulation_loop`) and `backend/simulation/engine.py:213` (`step`). The observed lifecycle ends its delivery work near 1,900 steps, rather than proving a fixed 2,000-step run contract.

| UTC / console ID | Step | Verified event | Interpretation and evidence boundary |
|---|---:|---|---|
| Before retained window | Unknown | Startup and initial controls absent | No BOOT, START, RESET, or initial state is retained. The aggregate duration cannot substitute for a logged start event. |
| 16:19:49.719 / 38598 | No step on row; first explicit step later is 1211 | CFP for task 118 | File starts inside ongoing CNP activity, not at run start. |
| 16:19:53.605 / 38689–38691 | 1229 | Crisis 0004, plan 002: HTTP 200; schema-valid response; one action parsed | Nemotron/Nvidia response latency 41,406 ms. Its matching request is outside the excerpt. HTTP and schema success do not imply safety acceptance. |
| 16:19:53.612 / 38692 | 1229 | Plan 002 rejected | Score 0.8; 9 errors and 1 warning. Codes contain nine `MISSING_AFFECTED_ROBOT` entries and `PATH_CONFLICT`. At least nine affected robots lack actions; the full affected set and proposed action are not retained here. |
| 16:19:53.614 / 38693–38694 | 1229 | Regeneration, then plan 003 request | Logged regeneration attempt 2, maximum 2; generated-plan IDs show this is the third candidate in the crisis. Earlier candidate evidence is missing. Prompt size 3,482 characters. |
| 16:19:58.419 / 38783–38786 | 1250 | Plan 003 response parsed, then rejected | HTTP 200; latency 4,797 ms; one action; same missing-coverage/error-code pattern, score 0.8, 9 errors and 1 warning. Invalid plans did not reach the visible executor. |
| 16:19:58.511–.533 / 38788–38790 | 1251 | Crisis 0004 fallback and terminal handling | Reason `PLAN_VALIDATION_FAILED`; structural collapse; `executed_actions=0`, `fallback=True`, graph duration 56,640 ms. Permanent structural effects are not restored. |
| 16:20:09.517 / 38896 | 1300 | Health | 86 tasks complete, 34 remaining; 22 moving, 6 charging; no active crisis/queue/orphaned holds. |
| 16:20:29.932 / 39052 | 1390 | Crisis 0004 `CRISIS_RECOVERED` | `recovery_steps=390`. Code defines this as each affected robot having recorded movement since activation, not removal of the obstruction or measured task recovery. Activation at step 1000 is an arithmetic inference from this metric, not a retained activation event. |
| 16:20:32.662–.707 / 39071–39074 | 1400 | Crisis 0005 activates, runner starts, then creation is logged; diagnose marker follows | Automatic `CHARGER_OUTAGE`, affected robot 13, location `(12,1)`, remaining budget 1. Creation logging follows activation/start in timestamp order. |
| 16:20:32.896 / 39078 | 1400 | Plan 001 request for crisis 0005 | OpenRouter/Nemotron; 1,111-character prompt. Health reports one pinned robot and zero orphaned holds. |
| 16:20:37.916–.927 / 39114–39117 | 1420 | Response, parse, validation pass | HTTP 200, 5,016 ms, one action, score 1.0, zero warnings/errors. Immediate execution is consistent with the graph's automatic policy. |
| 16:20:37.949–.953 / 39118–39121 | 1420 | HOLD committed for robot 13; charger restored; graph complete | Action duration/reason are absent from the log. `temporary_effects_restored=True`, one executed action, no fallback, graph duration 5,281 ms. The charger is restored by terminal cleanup, not by HOLD itself. |
| 16:20:46.821 / 39189 | 1452 | Crisis 0005 movement recovery recorded | 52 ticks since activation, 32 after the action/graph completion. This does not establish charger utilization recovery. |
| 16:20:58.186 / 39274 | 1500 | Health | 96 complete, 24 remaining; 7 moving, 8 charging; zero active crisis/queue/orphaned holds. |
| 16:21:22.057–.113 / 39567–39573 | 1600 | Crisis 0006 activates, starts, is logged as created, diagnoses, requests model | Automatic `CRITICAL_TASK`, affected robot 28, location `(2,18)`, remaining budget 0. Prompt 1,124 characters. Affected task ID is not in these events. |
| 16:21:35.102–.122 / 39751–39754 | 1657 | Response, parse, validation pass | HTTP 200, latency 13,000 ms, one action, score 1.0, zero warnings/errors. |
| 16:21:35.215–.219 / 39755–39758 | 1657 | HOLD committed for robot 28; crisis handling and graph complete | One action, no fallback, graph duration 13,156 ms. No visible reassignment or emergency CNP award is attributable to this plan. |
| 16:21:35.738 / 39768 | 1660 | Crisis 0006 movement recovery recorded | 60 ticks after activation and 3 after action commitment. The log does not identify or prove completion of the urgent task. |
| 16:21:44.789 / 40035 | 1700 | Health | 108 complete, 12 remaining; 8 moving, 7 charging; zero active crisis/queue/orphaned holds. |
| 16:22:06.783 / 40443 | 1800 | Health | 111 complete, 9 remaining; 5 moving, 7 charging; one intentional hold. |
| 16:22:27.719 / 40543 | 1898 | `ALL_TASKS_COMPLETED` | Reports 120 tasks, 490.703 seconds, 477 charging events, 28 re-auctions, 6 crises, 12 request events, 3 orchestration fallbacks. These are cumulative counters. |
| 16:22:28.134 / 40544 | 1900 | Final retained health | 120 complete, 0 remaining, 38 idle, 1 charging, 0 moving/pinned/queued/orphaned; 16,521 successful moves. Steps continue beyond first task-completion detection. |

The visible elapsed span is approximately **158.414 seconds**, not the full 490.703 seconds. No manual crisis injection can be identified in the retained excerpt; the source explicitly marks crises 0005 and 0006 automatic. Sources for crises 0001–0004 cannot be established from this file alone. A skipped automatic attempt near step 1200 is compatible with active-crisis backpressure but is not retained evidence and is not asserted as fact.

## 3. Quantitative findings

### Counts with distinct meanings

| Measure | Retained individual evidence | Full-run aggregate evidence | Interpretation |
|---|---:|---:|---|
| Console records | 1,947 | Final logging ID 40544 | IDs are sequence positions, not a full record collection. |
| Admitted crisis creation records | 2 | 6 crises at completion | Three distinct crisis IDs appear in the excerpt; crisis 0004 crosses its beginning. |
| Runner starts | 2 | Unknown | Starts for 0005/0006; completion for 0004 confirms a third session existed. All six starts are not retained. |
| `LLM_REQUEST` events | 3 | 12 | Cumulative field counts emitted generation-request events, before the client call; it is not an independently verified HTTP transaction count. |
| HTTP response receipts | 4, all 200 | Unknown | One receipt corresponds to a request before the retained window. All use OpenRouter/Nemotron/Nvidia. |
| `LLM_SUCCESS` events | 4 | Unknown | In source, success is emitted after Pydantic plan parsing and before world safety validation. |
| `PLAN_PARSED` events | 4 | Unknown | Two parsed plans were subsequently unsafe/incomplete. |
| Safety validation passes | 2 | Unknown | Both score 1.0, zero warnings/errors. |
| Safety validation rejections | 2 | Unknown | Each score 0.8, 9 errors, 1 warning; 18 error entries in total, not 18 distinct robots. |
| Plans with successful action receipts | 2 | Unknown | One HOLD each for R13 and R28. No visible REROUTE, YIELD, REASSIGN_TASK, or GO_TO_CHARGER receipt. |
| `ACTION_START` / `ACTION_OK` | 2 / 2 | Unknown | Demonstrates two action commits, not two proven operational recoveries. |
| `ORCH_COMPLETE` | 3 | Unknown total terminal-session records | Crisis 0004 fallback; 0005/0006 execute HOLD. |
| Orchestration fallback sessions | 1 individually traceable | 3 | Completion aggregate is the runner fallback-session counter. |
| `FALLBACK_ACTIVATED` records | 324 | Unknown | 323 are ordinary `DETERMINISTIC_DEADLOCK`; only 1 is visible plan-validation fallback. These are not 324 model failures. |
| `FALLBACK_HELD` records | 66 | Unknown | All visible examples report `NO_SAFE_RECOVERY_ROUTE`; some are recurring routine traffic containment. |
| Regeneration markers | 1 | Unknown | Crisis 0004 plan numbering establishes a third candidate, but earlier regeneration records are missing. |
| HITL request/approval/rejection/timeout | 0 retained | Unknown | No inference about earlier crises or the operator's full interaction history is justified. |
| Transport/parse failures / action failures | 0 retained | Unknown | Absence here does not exclude earlier timeouts, rate limits, or executor failures. |
| Queue/dequeue/stale-dropped markers | 0 retained | Unknown | All seven retained health samples show queue depth zero. |
| Task-completion events | 36, distinct task IDs | 120 tasks at completion | The other task-completion records are outside the export. |
| Task-reauction events | 9 | 28 re-auctions | No proof of a failed reassignment in the excerpt. |
| Charging warnings | 94 across 31 robot IDs | 477 charging events | All warnings use the same battery-feasible-route text; not enough detail to distinguish bay admission from energy failure. |
| Deadlock detected / resolved | 276 / 283 | Unknown | Per-robot three-strike episodes, not unique persistent reciprocal pairs or LLM crises. Some detected episodes start before the excerpt. |
| Resolution events at least 100 ticks | 19 | Unknown | Largest reported duration is 774 ticks. Duration does not prove continuous mutual deadlock. |
| Successful-move DEBUG records | 0 | Aggregate 16,521 moves | Confirmed instrumentation mismatch, WS-D01. |

The four retained schema-valid response latencies are **41.406, 4.797, 5.016, and 13.000 seconds**, averaging **16.055 seconds** for this selected response subset. The 41.406-second response is under the configured source timeout of 60 seconds; no retained event proves a timeout. Mean latency for all 12 attempts cannot be calculated from this excerpt.

Seven recurring recovery/warning families account for **1,628 records (83.62%)**: 324 fallback activations, 66 fallback holds, 321 generic route-recovery messages, 276 deadlock detections, 283 resolutions, 264 pathfinder warnings, and 94 charging warnings. This ratio describes the console export, not an observed screenshot of the OperationCentre tape, whose data sources differ.

### The requested 10–12 meaningful interactions

The default **six-incident shared budget** limits independent admitted crisis sessions. With two regenerations, each session can emit up to three request attempts, so six incidents can produce up to 18 attempts without representing 18 distinct recovery decisions. This run's aggregate 12 request events already falls in the requested numerical band, but it cannot establish 10–12 meaningful successful orchestrations.

At the source default interval of 200, there are at most ten automatic due-step opportunities through step 2000 before considering admission limits, active/pending backpressure, ineligibility, manual postponement, natural incidents, or earlier task completion. The observed delivery completion at 1898 precedes the tenth nominal due step. Ten or twelve independent useful incidents are not demonstrated by this scenario; ordinary three-strike traffic recoveries are not evidence that they deserve model escalation. The architecture can represent more sessions within its configurable bounds, but this audit cannot establish that doing so would produce meaningful safe recovery opportunities in this run.

## 4. Confirmed defects

### WS-D01 — Normal multi-agent movement and action transitions are absent from the promised console trace

**Classification:** logging integration defect. **Severity/priority:** High / P1. **Confidence:** Confirmed in current code; omission corroborated by the supplied run.

**Expected versus actual:** DeveloperCentre describes successful per-cell movement and major task/charging actions as captured. In the active multi-agent branch, RobotAgent emits movement as `[SIM] ...` at DEBUG, while the console handler only accepts DEBUG beginning `[ROBOT][MOVE]`. The matching MOVE instrumentation sits in the legacy engine branch. Normal pickup/charger-arrival information is local agent memory rather than a captured console record; fully charged is also excluded `[SIM]` DEBUG.

**Evidence:** No `[ROBOT][MOVE]` records occur anywhere in the 1,947-entry file, while ID 40544 at 16:22:28.134, step 1900, reports 16,521 successful moves. There are no DEBUG rows. Sources: `backend/agents/robot.py:528` (`_handle_move`, DEBUG at 582), `:586` (`_on_arrival`), `:603` (`_handle_pickup`), `:483` (`_handle_charge_complete`, DEBUG at 497); `backend/core/events.py:23` (`ConsoleHistoryHandler.filter`); `backend/simulation/engine.py:269` (active agent branch, returns before legacy movement) and `:349` (legacy MOVE logging); `frontend/DeveloperCentre.html:81` (capture-scope claim).

**Root cause:** emission tags and instrumentation locations do not match the actual execution path and handler's allowlist. **Impact:** users cannot reconstruct a robot's movement or charging/task transitions from the advertised console stream, even though aggregate progress exists. This is missing evidence, not proof that robots did not move.

### WS-D02 — DeveloperCentre's newer-record cursor can silently skip an entire backlog

**Classification:** pagination/data-loss defect. **Severity/priority:** High / P1. **Confidence:** Confirmed conditional code defect; occurrence in this export is unverified.

**Expected versus actual:** A paged newer-record reader should retain continuity through all returned and still-pending records. The backend returns the first `limit` newer records but advertises the current overall `latest_id`; the frontend advances its cursor to that overall ID instead of the last record actually received.

**Evidence:** `backend/core/events.py:72` (`ConsoleHistoryHandler.query`, newer-page selection at 83 and response latest ID at 91); `frontend/js/DeveloperCentre.js:170` (`acceptPage`, cursor at 175), `:187` (`pollLogs`, limit 500). For example, with cursor 1000 and latest ID 2000, one poll returns 1001–1500, then advances to 2000; the next poll excludes 1501–2000. This follows directly from the code without running it. The provided IDs 38598–40544 are contiguous, so this file does not prove such a gap occurred; startup CFP/proposal bursts can exceed one page, but their exact burst size is not retained.

**Root cause:** the frontend treats a backend head pointer as a consumed-page cursor. **Impact:** the live view/export can omit records despite the backend retaining them. The separate copy-all path reads the retained backend buffer directly and does not use this polling cursor.

### WS-D03 — Terminal invalid/fallback plans are still described as regenerating

**Classification:** incorrect UI state rendering. **Severity/priority:** Medium / P2. **Confidence:** Confirmed rendering defect; exact screen appearance during this run was not captured.

**Expected versus actual:** A final rejected plan whose retries are exhausted should be distinguished from an ongoing retry. OperationCentre maps every `validation_status==='INVALID'` to “PLAN REJECTED BY VALIDATOR. Regenerating...” even when the runner is inactive, its active node is `complete`, and fallback has finished.

**Evidence:** Plan 003 was rejected at ID 38786, 16:19:58.444, step 1250, followed by fallback and `ORCH_COMPLETE` at ID 38790, 16:19:58.533, step 1251, with zero executed actions. `frontend/js/OperationCentre.js:235` (`updateOrchestrator`, unconditional text at 246); `backend/agents/orchestrator_graph.py:558` (`_finish`, terminal node at 572, retained last state at 574). The runner retains INVALID validation status after this terminal fallback.

**Root cause:** the validation label does not consider terminal state or retry exhaustion. **Impact:** a recruiter can believe the system is still thinking or stuck after handling has already ended.

### WS-D04 — Crisis creation telemetry is emitted after activation and runner start

**Classification:** lifecycle event-ordering defect. **Severity/priority:** Medium / P2. **Confidence:** Confirmed in logs and source.

**Expected versus actual:** The displayed detection/creation event should identify the crisis before its activation and orchestration start in the causal timeline. The engine calls `invoke_async` synchronously through activation/start before recording `CRISIS_CREATED`.

**Evidence:** Crisis 0005: ID 39071 `CRISIS_ACTIVATED` at 16:20:32.662, ID 39072 `ORCH_START` at .676, ID 39073 `CRISIS_CREATED` at .677, all step 1400. Crisis 0006 repeats the ordering at IDs 39567–39569, step 1600. Source: `backend/simulation/engine.py:587` (`trigger_crisis`, invocation at 653, creation at 675); `backend/agents/orchestrator_graph.py:206` (`_start_locked`, activation at 214 and start event at 237); `frontend/js/CrisisOrchestration.js:69` (timestamp sorting).

**Root cause:** event emission occurs after the admission call's activation side effects. **Impact:** the recruiter-facing detect → diagnose story begins out of order. This does not establish duplicate physical injection or unsafe scheduling.

### WS-D05 — Charging errors incorrectly diagnose admission congestion as energy impossibility

**Classification:** misleading failure diagnosis. **Severity/priority:** Medium / P2. **Confidence:** Confirmed code-path ambiguity; causes of individual observed warnings remain unverified.

**Expected versus actual:** “No battery-feasible route” should identify a measured energy/reachability failure. `start_charging` uses congestion-aware selection, where a bay with another inbound/occupying robot is rejected even when reachable within battery; an empty selection uses the same battery-failure exception text.

**Evidence:** 94 warnings across 31 robots use exactly this text. ID 38673, 16:19:53.161, reports R20; ID 40533, 16:22:20.303, reports R3. Sources: `backend/agents/robot.py:399` (`start_charging`, exception at 404), `:459` (`_handle_need_charge`, warning at 464); `backend/simulation/charging.py:75` (`get_charge_path`, combined energy/demand exclusion at 88). The warnings omit battery, bay demand, route length, and candidate exclusion reason.

**Root cause:** unavailable admission and infeasible energy share the same empty-path/error condition. **Impact:** users may conclude battery tuning or connectivity is broken when the real condition is temporary charger demand. The excerpt cannot establish how many of the 94 warnings are false energy diagnoses.

## 5. Design / behavior limitations

### WS-L01 — Six independent incidents cannot demonstrate 10–12 independent AI recoveries

**Classification:** deliberate configuration/demo limit. **Severity/priority:** High for demo interpretation / P1. **Confidence:** Confirmed behavior; desired additional meaningful opportunities are unverified.

**Expected versus actual:** The desired demonstration is 10–12 meaningful recovery interactions over about 2000 steps. The inspected defaults admit six total manual/automatic/natural incidents; model retries can inflate request counts without creating new recovery scenarios.

**Evidence:** ID 40543, 16:22:27.719, step 1898 reports 6 crises and 12 calls; crisis 0006 creation at ID 39569, step 1600, reports remaining 0. `backend/core/settings.py:21` (`crisis_interval`), `:22`/`:29` (effective budget); `backend/simulation/engine.py:253` (`_step`), `:599`/`:668` (`trigger_crisis`); `backend/agents/orchestrator_graph.py:315` (attempt bound).

**Root cause:** shared finite incident admission and per-incident retries are intentionally different counters. **Impact:** a small number of visible incidents may be misread as too few API calls, while retries may be misread as more substantive intelligence. No evidence justifies escalating every routine traffic block to satisfy a numerical target.

### WS-L02 — Persistence, backpressure, and admission latching deliberately reduce escalation opportunities

**Classification:** intentional slow-model scheduling tradeoff. **Severity/priority:** Medium / P2. **Confidence:** Confirmed in source/documentation; full-run admission losses are not measurable here.

**Expected versus actual:** A frequent-interaction demo might expect every detected deadlock or due interval to call the model. Three-strike blocks first invoke deterministic recovery. Escalation requires both pair recoveries plus six further qualifying reciprocal observations by default; active/pending work skips automatic attempts. Rejected pair admission remains latched until a new episode, a behavior explicitly documented to avoid admission spam.

**Evidence:** 276 per-robot detection and 323 deterministic fallback records but zero retained `DEADLOCK_PERSISTENT`; seven health snapshots have queue depth 0. `backend/simulation/engine.py:415` (`request_deadlock`), `:466` (`_update_deadlock_pairs`, submitted latch at 508), `:603` (`trigger_crisis`); `backend/agents/orchestrator_graph.py:151` (`_is_stale`), `:166` (`invoke_async`); `docs/CRISIS_AND_LLM_ORCHESTRATION.md:124` (deduplication/latching/backpressure).

**Root cause:** safety and slow-model scheduling policy, not evidence of a broken API. **Impact:** many busy-looking traffic events produce no AI interaction. Temporary admission refusal can suppress another attempt for the same unmoved episode; that is a documented limitation, not reported here as an accidental queue-loss defect.

### WS-L03 — The model can satisfy safety policy with a HOLD that does not address the crisis cause

**Classification:** orchestration effectiveness/demo limitation. **Severity/priority:** High / P1. **Confidence:** Confirmed capability limit; exact causal contribution of observed holds is unverified.

**Expected versus actual:** Meaningful AI recovery should be distinguishable from waiting. The prompt's example is one HOLD and it explicitly recommends short HOLD when a detour is unknown. Validation checks allowed action/state/path safety; it has no incident-specific success objective requiring restored charger service, urgent-order coordination, or reduced congestion.

**Evidence:** IDs 39118–39119, 16:20:37.949–.950, step 1420 execute HOLD for R13; IDs 39755–39756, 16:21:35.215–.216, step 1657 execute HOLD for R28. Both plans score 1.0, no warnings. `backend/agents/orchestrator_graph.py:275` (`_plan_prompt`, example/preferences at 294–301); `backend/agents/plan_validator.py:95` (HOLD checks); `backend/agents/action_executor.py:80` (`_stage`).

**Root cause:** readiness validation and conservative generation behavior do not measure operational benefit. **Impact:** technically real model-driven actions can look ceremonial rather than demonstrating useful planning. No exact hold duration or rationale is retained in the artifact.

### WS-L04 — Temporary crisis restoration is coupled to graph termination rather than the selected action

**Classification:** synthetic incident behavior limitation. **Severity/priority:** High for causal demonstration / P1. **Confidence:** Confirmed.

**Expected versus actual:** A viewer may interpret successful execution as the action restoring the service. Charger outage and robot immobilization effects are removed whenever managed crisis handling terminates, including fallback, stale dropping, or cancellation; HOLD itself does not repair either. CRITICAL_TASK changes an existing order's priority; its effect can persist without any new coordination when the selected action simply waits.

**Evidence:** ID 39120 at 16:20:37.953, step 1420 records `temporary_effects_restored=True` immediately after R13 HOLD. ID 39757 at 16:21:35.219, step 1657 ends urgent handling without reassignment. `backend/simulation/engine.py:739`, `:745`, `:751` (`activate_crisis` effects); `:780` (`finish_crisis`, clear fault at 789 and restore bay at 792); `backend/agents/action_executor.py:80` (HOLD timer only).

**Root cause:** the current incident model deliberately supplies temporary effects and terminal cleanup, not action-specific repairs. **Impact:** a successful-looking recovery can be partly the end of a synthetic fault, independent of AI decision quality. Structural cells, by contrast, remain obstructed after terminal handling.

### WS-L05 — HITL offers one candidate plan and a binary gate, not alternative recovery choices

**Classification:** HITL capability/design mismatch. **Severity/priority:** High / P1. **Confidence:** Confirmed; no operator interaction is observed in this excerpt.

**Expected versus actual:** The desired experience includes several meaningful recovery options and one AI recommendation. `CrisisPlan` contains one action list plus an optional rationale. One candidate is generated at a time; override accepts only `approved` and `plan_id`. Rejection requests a new strategy within the same bounded attempt budget. There is no option-set, comparative tradeoff, ranked recommendation, editable plan, or candidate-selection operation.

**Evidence:** Zero HITL records in the retained window, so this is a contract finding rather than an observed rejection failure. `backend/agents/plans.py:55` (`CrisisPlan`); `backend/api.py:534` (`OrchestratorOverrideRequest`); `backend/agents/orchestrator_graph.py:521` (`human_override`); `frontend/CrisisOrchestration.html:54` and `frontend/OperationCentre.html:42` (two buttons).

**Root cause:** human input is an approval gate for one already validated proposal. **Impact:** the recruiter cannot demonstrate human selection among concrete alternatives using the current interface/API. The optional rationale is model-provided explanation, not hidden reasoning or a comparative recommendation.

### WS-L06 — HITL appears only for certain valid plans and its notification is contextual

**Classification:** policy, notification, and review-lifecycle UX limitation. **Severity/priority:** High / P1. **Confidence:** Confirmed code behavior; operator noticing or missing a prompt is unverified.

**Expected versus actual:** The desired crisis decision popup might appear whenever a crisis needs an operator choice. Current policy auto-approves valid plans with no warnings and score at least the configured threshold (default 0.85). Any warning requires human review; invalid plans regenerate/fallback instead. OperationCentre shows an inline review area and switches to the crisis tab; CrisisOrchestration shows review controls in its right panel. Neither supplies the requested multi-option modal experience.

**Evidence:** The two visible valid plans have score 1.0/no warnings and immediate action receipts; zero HITL events is expected for that policy, not a broken interrupt. `backend/agents/orchestrator_graph.py:395` (`validate`), `:459` (`_drive`), `:544` (`_expire`); `backend/agents/plans.py:120` (`requires_human`); `frontend/js/OperationCentre.js:252`; `frontend/js/CrisisOrchestration.js:231`; corresponding HTML review blocks lack dialog semantics. Active affected robots remain pinned; the rest of the swarm continues, with a default 300-second review timeout.

**Root cause:** conditional review is distinct from all-crisis intervention. Other robots/world conditions can change while review is pending; plan-ID checks, ownership/live-validation checks, and warning comparison protect execution but may cause a previously reviewed plan to fall back. **Impact:** intervention is infrequent, easy to miss in a context panel, and a decision is not guaranteed to remain executable. Approval means accepting the proposal subject to live safety checks, not guaranteed recovery.

### WS-L07 — The live tape represents technical records rather than a readable incident story

**Classification:** event terminology/hierarchy UX limitation. **Severity/priority:** High / P1. **Confidence:** Confirmed rendering behavior; exact observed browser composition is unverified.

**Expected versus actual:** A first-time viewer should connect a trigger, decision, and result. The tape joins raw structured event fields and raw message JSON, sorts newest first, and displays at most 100 filtered rows. It combines timestamps for messages with step numbers for events. Distinct messages/events for one award or crisis remain separate records, with no logical incident grouping. Route recovery is always called `OBSTACLE BYPASS RECOVERY`, including ordinary route rebuilding; traffic recovery shares FALLBACK terminology with model failure.

**Evidence:** 83.62% of the console excerpt is recurring recovery/warning families, including 321 route-recovery messages but zero retained `OBSTACLE BYPASS DETECTED`; this is corroborating terminology/noise evidence, not proof every console line appears in the tape. `frontend/js/OperationCentre.js:213` (`category`), `:220` (`eventRows`), `:225` (`renderEvents`); `backend/agents/robot.py:501` (`_recover_route`); `backend/agents/action_executor.py:105`; `backend/agents/task.py:199` and `:213` (award message and structured award event).

**Root cause:** a union of separate telemetry streams preserves transport-level records without incident/action-result semantics. **Impact:** ordinary contention can resemble repeated AI failure, reverse chronology makes causality harder to read, and meaningful orchestration may be buried. Category colors help identify type but do not explain the decision.

### WS-L08 — Validation readiness is not a crisis-resolution score

**Classification:** validator scope and score-interpretation limitation. **Severity/priority:** Medium / P2. **Confidence:** Confirmed.

**Expected versus actual:** A recruiter may read a high validation score as a strong recovery recommendation. The score is an equal-weight average over five safety/readiness groups; groups irrelevant to HOLD remain satisfied. Prediction covers five ticks by default, not complete auctions, reactive charging, permanent progress, or incident-specific effectiveness. Missing affected coverage caps score at 0.8 while validity still blocks execution.

**Evidence:** IDs 38692/38786 have 9 errors each yet score 0.8; IDs 39117/39754 have score 1.0 for HOLD plans. `backend/agents/plan_validator.py:45` (`SCORE_WEIGHTS`), `:194` (trajectory prediction), `:247` (score), `:254` (coverage cap); `backend/agents/plans.py:113` (`ValidationReport`).

**Root cause:** the metric intentionally describes execution readiness, not confidence, optimality, or probability of resolving a crisis. **Impact:** comparing 0.8 and 1.0 alone is misleading; invalidity and scope are essential. The invalid plans were correctly stopped, so this is not a safety-bypass defect.

### WS-L09 — Delivery completion is a milestone, not a stopped simulation or a 2,000-step boundary

**Classification:** lifecycle design limit. **Severity/priority:** Medium / P2. **Confidence:** Confirmed.

**Expected versus actual:** A viewer may expect COMPLETE to imply no more simulation activity, or assume 2000 is a fixed execution limit. The loop advances until explicitly stopped; engine completion records the first moment all tasks complete without terminating the loop. Completion does not itself wait for arbitrary active model/queued work to become terminal.

**Evidence:** ID 40543 reports completion at step 1898; ID 40544 is a subsequent health event at step 1900, with one robot still in CHARGING status. `backend/api.py:127` (`simulation_loop`); `backend/simulation/engine.py:213` (`step`, completion milestone at 229); `frontend/js/OperationCentre.js:109` (`updateHeader`) and `frontend/js/CrisisOrchestration.js:145` (COMPLETE label). No active orchestration remains in the final retained sample, so completion-with-active-LLM is a source possibility, not an observed incident.

**Root cause:** task completion and simulator stop are separate conditions. **Impact:** post-completion motion/charging and continuing steps can look contradictory without understanding that distinction.

### WS-L10 — Routine traffic recovery has a substantial long tail despite successful final delivery

**Classification:** observed congestion/recovery behavior limitation. **Severity/priority:** Medium / P2. **Confidence:** Confirmed measurements; exact underlying bottleneck is Probable, not established.

**Expected versus actual:** Agents should appear to make understandable steady progress. The run ultimately completes, but repeatedly contains traffic episodes, unsuccessful immediate recovery, charge-admission warnings, and long per-robot intervals before the next recorded move.

**Evidence:** 323 routine fallback activations, 66 no-safe-route holds, 94 charging warnings, and 19 resolved episodes of at least 100 ticks in the excerpt. R35 resolves after 774 ticks at ID 39254, 16:20:56.952, step 1495; R4 after 638 at ID 38624, step 1214; R16 after 513 at ID 40472, step 1817. Full-run charging counter is 477 and re-auction counter 28. `backend/simulation/engine.py:415`/`:536` (episode metrics); `backend/agents/action_executor.py:95` (`fallback`); `backend/simulation/charging.py:75` (bay admission).

**Root cause boundary:** per-robot episodes end at the next successful move; this metric is not continuous reciprocal-block duration. Congestion/admission and repeated recovery are visible, but geometric bottlenecks, battery distributions, and exact route churn cannot be reconstructed. **Impact:** a working system can look erratic or inefficient; evidence does not establish permanent immobility or task corruption.

## 6. Observability gaps

### WS-G01 — The supplied export cannot establish the complete run history

**Classification:** evidence/provenance gap. **Severity/priority:** High / P1. **Confidence:** Confirmed.

**Expected versus actual:** Whole-run analysis requires startup through completion plus export coverage metadata. This file begins at ID 38598, has only 36 of 120 completion events, and lacks earlier request/crisis/HITL history. It contains no export manifest identifying active filters, loaded range, buffer truncation, effective settings, or source commit.

**Evidence:** First/last IDs 38598/40544, 16:19:49.719–16:22:28.134; first explicit step 1211. `frontend/js/DeveloperCentre.js:216` (`exportVisible`) serializes only filtered, loaded rows; `:224` (`copyAllLogs`) is a separate full-retained-buffer operation; `backend/core/events.py:16` (current 100000-record cap). This filename matches the view-export function. A partial loaded view is a plausible explanation, not a proven account of the user's export actions; current IDs alone do not require eviction under the inspected cap.

**Root cause:** artifact coverage differs from cumulative counters and lacks a coverage declaration. **Impact:** full-run API success/failure rates, manual decisions, early queue behavior, and frequency cannot be independently audited from this export.

### WS-G02 — Historical plans and action parameters disappear even when execution events remain

**Classification:** backend/API/history evidence gap. **Severity/priority:** High / P1. **Confidence:** Confirmed.

**Expected versus actual:** Selecting a completed incident should substantiate the exact proposed and executed actions, reasons, targets, and validation context. The runner keeps only the current or last session state. PLAN_PARSED records action count, and action receipts record robot/action/plan identity but not hold duration, yield target, waypoint, route, or reason. The browser can retain snapshots only if it observed them before replacement; those snapshots are lost on reload.

**Evidence:** HOLD receipts at IDs 39119 and 39756 contain no `hold_steps` or reason. Parsed rejected plans at IDs 38691/38785 have only `actions=1`. Sources: `backend/agents/orchestrator_graph.py:124` (`get_state`), `:360` (parse event), `:574` (last state); `backend/agents/action_executor.py:47`/`:71` (receipts); `frontend/js/CrisisOrchestration.js:80` (`ingest` snapshots), `:210` (`renderPlan`).

**Root cause:** events prove transitions but do not archive complete plans/reports; browser-only snapshots are contingent. **Impact:** a recruiter can be told “plan parsed; full action parameters were not retained” for a completed crisis, precisely where the AI's work should be inspectable.

### WS-G03 — Diagnosis, severity, affected-task evidence, and pre-incident impact are not supplied

**Classification:** crisis-context/diagnosis gap. **Severity/priority:** High / P1. **Confidence:** Confirmed.

**Expected versus actual:** DIAGNOSE should provide evidence explaining the issue, and the page should distinguish impact/severity and involved tasks. The diagnosis node only sets a node label and emits affected IDs. Crisis records expose kind/location/robots/source/step/status, not a diagnosis report or severity. Request details contain a critical task ID internally and are used in the prompt, but that ID is absent from the captured crisis/action receipts and current public crisis context. The complete prompt/world snapshot and raw response are not retained in these events.

**Evidence:** IDs 39074/39571 contain only graph node and affected robot, steps 1400/1600. CRITICAL_TASK creation ID 39569 does not identify its task. `backend/agents/orchestrator_graph.py:308` (`diagnose`), `:275` (`_plan_prompt`), `:222` (public session state); `backend/simulation/engine.py:673` (incident metadata), `:675` (creation event); `frontend/js/CrisisOrchestration.js:183` (`renderIncident`).

**Root cause:** the stage currently marks workflow entry; meaningful crisis data is transient prompt context rather than retained diagnostic output. **Impact:** a recruiter can see DIAGNOSE lit green without knowing what was diagnosed. Missing raw text is an evidence boundary, not permission to fabricate model reasoning.

### WS-G04 — Completion and movement recovery do not prove incident-specific resolution or AI causality

**Classification:** outcome/causal-evidence gap. **Severity/priority:** High / P1. **Confidence:** Confirmed metric definition; actual causal recovery quality is unverified.

**Expected versus actual:** Resolution evidence should establish that the operational cause and affected work recovered. `finish_crisis` means terminal handling/effect cleanup. `record_movement` removes each affected robot from a set on its first successful reservation/move; after all affected robots have done so, it records CRISIS_RECOVERED. It does not assess sustained progress, task completion, queue clearance, or charger throughput. Historical impact maps show current positions/routes, explicitly labeled as such.

**Evidence:** Crisis 0004 graph ends with zero actions/fallback at step 1251, movement recovery later at 1390. Crisis 0005 charger cleanup occurs at 1420, movement recovery at 1452. `backend/simulation/engine.py:536` (`record_movement`, set clearance at 550), `:780` (`finish_crisis`); `backend/agents/orchestrator_graph.py:558` (`_finish`); `frontend/js/CrisisOrchestration.js:167`, `:239`, `:253` (outcome wording/current map).

**Root cause:** operational resolution is represented by a minimal liveness proxy, with no preserved before/after evidence. **Impact:** ACTION_OK and COMPLETE are real execution/lifecycle evidence but cannot support a claim that AI solved the crisis. Even the UI's “first movement” wording compresses the backend's all-affected-robots-first-movement definition.

### WS-G05 — Routine recovery events lack enough entity and outcome linkage to explain traffic incidents

**Classification:** correlation/context gap. **Severity/priority:** Medium / P2. **Confidence:** Confirmed.

**Expected versus actual:** A recovery record should be attributable to a specific robot/pair and its result. Routine `FALLBACK_ACTIVATED` receives only the reason, because affected IDs are an argument rather than emitted context. Successful route changes/retreats can return without an outcome record. Deadlock detected/resolved messages use robot IDs but no common episode ID; generic route and charge warnings lack steps/task/battery/context.

**Evidence:** 323 routine fallback events have `reason=DETERMINISTIC_DEADLOCK` without robot ID or crisis ID; ID 38617 at 16:19:50.146, step 1213 is one example. Compare 276 detected episodes and 283 resolutions, which cannot simply be paired by record counts. `backend/simulation/engine.py:434` (`request_deadlock` call), `:548` (resolution event); `backend/agents/action_executor.py:105` (fallback event), `:135`/`:173` (successful return paths); `backend/state/task_state.py:130` (completion event lacks delivered robot/position, although state stores them).

**Root cause:** action arguments and physical outcomes are not fully represented in emitted event context. **Impact:** the operator cannot group the warnings/replans into understandable incidents or trace a completed task back to delivered-by evidence from the event alone.

### WS-G06 — Workspace history and frequency telemetry omit cumulative and already retained incident data

**Classification:** API-to-UI visibility gap. **Severity/priority:** High / P1. **Confidence:** Confirmed code behavior; exact screen counts at observation time are unverified.

**Expected versus actual:** The UI should allow a reader to distinguish total sessions, request attempts, parsed responses, valid plans, fallbacks, and executed recoveries. OperationCentre counts requests/fallback sessions only in its latest 300-event snapshot and labels that as a recent window. CrisisOrchestration fetches 1000 events, retains up to 2000 in the tab, and builds incidents from those events/current state; it does not seed history from the backend's `incidents` list. Server events are bounded at the configured limit, default 2000, while cumulative totals exist internally.

**Evidence:** Completion ID 40543 says 12 requests/6 crises/3 fallbacks, but the visible excerpt has only 3 request events and 2 starts. `frontend/js/OperationCentre.js:73`/`:79` (`pollSlow`), `:139` (`updateMetrics`); `frontend/OperationCentre.html:26` honestly labels the recent window, but not its relationship to totals. `frontend/js/CrisisOrchestration.js:61` (`ingest`), `:317` (`poll`); `backend/simulation/engine.py:573` (`crisis_summary`, incidents at 581); `backend/core/events.py:118`/`:150` (bounded ring/cumulative totals).

**Root cause:** workspace history is a bounded observation window rather than a complete run read model, even where summary metadata survives in the API. **Impact:** calls and incidents can appear to vanish or remain at only 3–4; reload can erase historical plan/context evidence. This is a plausible contributor to the observation, not proof of what the user saw.

## 7. Recruiter UX assessment across the three requested surfaces

This section consolidates the issue IDs above rather than adding duplicate findings.

| Recruiter question | Current evidence/UI capability | Identified problem |
|---|---|---|
| Is there a crisis, and where? | Active kind/location/affected robot IDs, current map, queue depth, budget | Historical context can disappear; task/severity/evidence baseline is incomplete (WS-G03, WS-G06). |
| What did diagnosis establish? | DIAGNOSE marker with affected IDs | No diagnosis report or supporting observations are produced (WS-G03). |
| Was the model called successfully? | Request, response, provider/model, HTTP/latency, schema parse status | Cumulative attempts versus successes/validated decisions are not presented together; excerpt is partial (WS-L01, WS-G01, WS-G06). |
| What did it propose and why? | Live observed action list/reasons/rationale, if snapshot survives | Historical actions/parameters can be unavailable (WS-G02); no comparative alternatives (WS-L05). |
| Did validation accept it? | Score, valid/invalid, issue list or retained codes | Numeric score is not recovery quality; terminal state can still say regenerating (WS-L08, WS-D03). |
| What can I decide? | Conditional approve/reject controls with plan-ID freshness checks | Single proposal, contextual notification, conditional rather than every-crisis HITL (WS-L05, WS-L06). |
| What actually executed? | ACTION_OK/FAILED receipts, visible live parameters when retained | Parameters and entity linkage are incomplete in historical records (WS-G02, WS-G05); real movement logs are excluded (WS-D01). |
| Did it solve the crisis? | Graph duration, fallback flag, terminal cleanup, movement recovery proxy | Safety/commit evidence is not operational or causal proof (WS-L03, WS-L04, WS-G04). |
| Why so many scary events? | Technical tape filters/colors and raw event/message data | Routine recovery, model fallback, duplicate logical actions, generic route labels, and mixed time/step ordering are difficult to interpret (WS-L07, WS-D04, WS-D05). |

The visual system itself is coherent and dense; this audit does not establish a palette, layout, clipping, or responsive defect without a rendered browser session. The strongest UX problems are state semantics, evidence retention, and causal explanation, not a demonstrated need for a structural redesign.

## 8. Unverified suspicions

### WS-U01 — Physical safety, continuous occupancy, and battery corruption cannot be ruled in from this artifact

**Classification:** unverified physical-state concern. **Severity/priority if true:** Critical / P0; not an established P0 finding. **Confidence:** Unverified.

**Expected versus actual evidence:** A physical audit would need positions, reservations, battery, paths, ownership, and delivered coordinates over time. The log contains no normal MOVE records and no complete state snapshots. Zero retained obstacle-bypass-detected messages and seven zero-orphaned-hold samples do not prove continuous invariants.

**Evidence/source:** ID 40544, step 1900 reports 16521 moves without corresponding move records. `backend/agents/robot.py:528` (path/energy/reservation checks), `backend/state/task_state.py:119` (delivery requires parcel/owner/destination), `backend/agents/action_executor.py:21` (live validation/staging). **Root cause:** unknown; safeguards exist in source. **Impact if true:** corrupted simulation claims or unsafe motion. No duplicate occupancy, obstacle traversal, fake task completion, or out-of-range battery is established here.

### WS-U02 — Earlier model failures and provider problems are not reconstructable

**Classification:** unverified inference-history concern. **Severity/priority if true:** High / P1. **Confidence:** Unverified for the missing portion.

**Expected versus actual evidence:** Twelve full-run request events should be separable into received/parsed/rejected/failed/timeout outcomes. Only four response receipts, three request markers, and one of three aggregate fallback sessions are retained. There are no LLM_FAILURE or HITL records in this window.

**Evidence/source:** ID 40543 cumulative counters; IDs 38689, 38783, 39114, 39751 successful HTTP receipts. `backend/agents/llm_client.py:60` (`OpenRouterClient.generate`, 60-second timeout, typed 401/402/404/429/provider/transport errors), `backend/agents/orchestrator_graph.py:361` (failure diagnostics), `:384` (fallback/retry routing). **Root cause:** unknown in earlier calls, with incomplete evidence. **Impact if true:** provider/parse reliability may have driven prior fallbacks. The visible Nemotron path is functional; an unavailable GPT-OSS model, rate limiting, or silently swallowed timeout cannot be asserted from this file.

### WS-U03 — Queue loss, HITL rejection failure, or task-reassignment corruption is not demonstrated

**Classification:** unverified lifecycle/ownership concern. **Severity/priority if true:** High / P1. **Confidence:** Unverified.

**Expected versus actual evidence:** Verifying these flows requires actual queued/dequeued episodes, human decisions, and REASSIGN_TASK execution/ownership traces. None is retained. Nine task re-auctions are observed, but they are not evidence of a failed model reassignment. Queue depth is zero at all sampled health points.

**Evidence/source:** Seven HEALTH rows, zero HITL/queue/action-failed records; `backend/agents/orchestrator_graph.py:166` (dedup/queue), `:521` (override), `:558` (hold cleanup/next queue); `backend/agents/action_executor.py:90` (safe release), `backend/state/task_state.py:132` (`release_task`). **Root cause:** unknown. **Impact if true:** blocked decisions, wrong ownership, lost incidents. Existing safety paths are present; the lack of exercised evidence must not be described as a confirmed defect.

## 9. Priority matrix

Priorities express the audit's verified impact and demonstration value. Unverified rows show conditional severity only; they are not confirmed failures.

| ID | Priority / severity | Classification | Main impact | Affected components | Confidence |
|---|---|---|---|---|---|
| WS-D01 | P1 / High | Confirmed defect | Actual robot actions missing from promised logs | RobotAgent, engine legacy path, console handler | Confirmed |
| WS-D02 | P1 / High | Confirmed conditional defect | Backlog records silently skipped by polling | DeveloperCentre JS, log API/history | Confirmed code; run occurrence unverified |
| WS-D03 | P2 / Medium | Confirmed defect | Finished fallback still described as regenerating | OperationCentre rendering, retained runner state | Confirmed |
| WS-D04 | P2 / Medium | Confirmed defect | Creation appears after start/activation | Engine admission, runner, event timeline | Confirmed |
| WS-D05 | P2 / Medium | Confirmed diagnostic defect | Congestion can be described as battery infeasibility | ChargingManager, RobotAgent | Confirmed code ambiguity |
| WS-L01 | P1 / High demo impact | Configuration/design limit | Six sessions versus desired 10–12 meaningful recoveries | Settings, admission, regeneration | Confirmed |
| WS-L02 | P2 / Medium | Scheduling tradeoff | Deliberate non-escalation/backpressure/latching | Engine deadlock policy, runner queue | Confirmed |
| WS-L03 | P1 / High | Effectiveness limit | HOLD can pass without addressing cause | Prompt, validator, executor | Confirmed capability limit |
| WS-L04 | P1 / High demo impact | Synthetic-effect limit | Cleanup can appear to be AI repair | Crisis activation/finish | Confirmed |
| WS-L05 | P1 / High | HITL capability mismatch | No alternative-plan decision experience | Plan schema, graph, override, review UI | Confirmed |
| WS-L06 | P1 / High | HITL notification/lifecycle limit | Infrequent contextual review; live conditions change | Validation policy, timers, pages | Confirmed |
| WS-L07 | P1 / High | Event readability limit | Technical noise obscures logical incidents | Tape/message union, recovery terminology | Confirmed rendering behavior |
| WS-L08 | P2 / Medium | Score/prediction limit | Readiness mistaken for recovery quality | Validator, validation UI | Confirmed |
| WS-L09 | P2 / Medium | Lifecycle limit | COMPLETE does not stop ticks | API loop, engine completion, headers | Confirmed |
| WS-L10 | P2 / Medium | Observed performance/behavior limit | Long traffic recovery tail despite eventual delivery | Collision recovery, charging, routes | Measurements confirmed; root cause probable |
| WS-G01 | P1 / High | Evidence gap | Entire-run outcomes cannot be audited | Export/artifact coverage | Confirmed |
| WS-G02 | P1 / High | Historical-plan gap | AI's exact work unavailable after replacement/reload | Runner state, receipts, Crisis desk | Confirmed |
| WS-G03 | P1 / High | Diagnosis/impact gap | DIAGNOSE without explanatory evidence | Graph diagnose/prompt, incident API, UI | Confirmed |
| WS-G04 | P1 / High | Outcome/causality gap | Commit/cleanup/movement treated as recovery evidence | Engine metrics, outcomes, historical map | Confirmed |
| WS-G05 | P2 / Medium | Correlation gap | Traffic/actions cannot be grouped or attributed | Fallback/events/task completion | Confirmed |
| WS-G06 | P1 / High | Counter/history visibility gap | Frequency and history shrink with retained window | Event API, workspace ingest/KPIs | Confirmed |
| WS-U01 | Conditional P0 / Critical | Unverified suspicion | Physical/ownership/battery safety if violated | Movement, reservations, task state | Unverified |
| WS-U02 | Conditional P1 / High | Unverified suspicion | Earlier provider/parse failures if present | OpenRouter/Ollama clients, graph | Unverified |
| WS-U03 | Conditional P1 / High | Unverified suspicion | Queues/review/reassignment if broken | Runner, HITL, executor, task lifecycle | Unverified |

## Investigation limitations

Only this specified JSON was used as runtime evidence. Its complete contents were analyzed, but it is not a complete run recording. Current source and documentation can establish code behavior; they cannot establish the precise effective environment, UI snapshots, earlier model outputs, or operator actions at capture time. Graph edges are stale relative to HEAD, and the working tree contains pre-existing uncommitted feature/documentation changes. Source references describe the inspected working tree, not a claimed captured-runtime commit.

No live browser was used, so actual viewport readability, popup visibility, focus behavior, and what the recruiter saw remain unverified beyond static DOM/rendering logic. No new simulation or model call was made; no new performance, safety, network, queue, or HITL behavior is claimed as tested. The aggregate task completion is supported by current delivery validation in source, but this audit did not independently inspect all 120 delivery positions. The excerpt shows safe rejection and eventual progress; it does not prove arbitrary-seed liveness, continuous safety, or that AI rather than deterministic recovery/cleanup caused every recovered outcome.

"""Scheduling regressions for local inference slower than hundreds of robot ticks."""
import json
import threading

import pytest

from backend.agents.llm_client import FaultClient
from backend.agents.orchestrator_graph import CrisisKind
from backend.agents.plans import PlanError
from backend.core.models import RobotStatus
from backend.core.settings import Settings
from backend.evaluation.runner import settle
from backend.simulation.factory import create_simulation
from conftest import ScriptedClient, action, assign, plan, wait_for


class SlowLLMClient:
    model = "slow-local-test"

    def __init__(self):
        self.entered = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def generate(self, prompt, schema):
        self.calls += 1
        self.entered.set()
        if not self.release.wait(90):
            raise AssertionError("Test failed to release simulated inference")
        raise PlanError("LLM_TIMEOUT", "Injected slow local inference timeout")


def set_pair(e):
    a, b = e.robot_manager.robots[:2]
    a.position.x, a.position.y = 2, 2
    b.position.x, b.position.y = 3, 2
    assign(e, 1, pickup=(3, 2), delivery=(4, 2))
    assign(e, 2, pickup=(2, 2), delivery=(1, 2))
    return a, b


def fail_recovery(e, monkeypatch):
    # Isolate scheduling after a deterministic attempt that failed to resolve
    # reciprocal movement. Actual A*, reservation failures, and ticks still run.
    calls = []
    monkeypatch.setattr(e.orchestrator_runner.executor, "fallback", lambda *a, **k: calls.append((a, k)))
    return calls


def assert_holds(e):
    state = e.orchestrator_runner.get_state()
    active_id = state["crisis_id"] if state["active"] else None
    for r in e.robot_manager.robots:
        assert r.orchestration_holds <= {active_id}
        if r.orchestration_holds:
            assert r.id in state["affected_robots"]
    assert state["queued_crises"] <= e.settings.max_pending_crisis
    return state


def test_transient_three_strikes_only_attempt_deterministic_recovery(engine_factory, monkeypatch):
    client = ScriptedClient(plan(action(hold_steps=1)))
    e = engine_factory(client)
    set_pair(e)
    attempts = fail_recovery(e, monkeypatch)
    for _ in range(3):
        e.step()
    assert len(attempts) == 2
    assert client.calls == 0
    assert e.events.totals()[0].get("LLM_REQUEST", 0) == 0


def test_persistent_pair_escalates_once_and_dedupes_active(engine_factory, monkeypatch):
    client = SlowLLMClient()
    e = engine_factory(client)
    a, b = set_pair(e)
    fail_recovery(e, monkeypatch)
    try:
        for _ in range(3 + e.settings.deadlock_persistence_steps - 1):
            e.step()
        assert client.calls == 0
        e.step()
        assert client.entered.wait(2)
        first = assert_holds(e)
        episode = e._deadlock_pairs[(1, 2)]["id"]
        for _ in range(20):
            assert e.orchestrator_runner.invoke_async([], [2, 1], kind="deadlock", episode_id=episode) == first["crisis_id"]
            e.step()
            assert_holds(e)
        assert client.calls == 1
        assert e.orchestrator_runner.get_state()["queued_crises"] == 0
        assert e.events.totals()[0]["DEDUPED"] == 20
        client.release.set()
        wait_for(e, lambda s: not s["active"])
        for _ in range(20):
            e.step()
        assert client.calls == 1  # completion/holding cannot re-arm this episode
        assert not a.orchestration_holds and not b.orchestration_holds
        e.record_movement(1)
        assert (1, 2) not in e._deadlock_pairs
    finally:
        client.release.set()


def test_queued_structural_crisis_does_not_pin_or_stop_robot(engine_factory):
    client = SlowLLMClient()
    e = engine_factory(client)
    r, _ = assign(e, 2, pickup=(6, 5), delivery=(6, 6))
    try:
        active = e.orchestrator_runner.invoke_async([], [1])
        assert client.entered.wait(2)
        pending = e.orchestrator_runner.invoke_async([], [2])
        before = (r.position.x, r.position.y)
        assert not r.orchestration_holds
        assert e.robot_manager.get_robot(1).orchestration_holds == {active}
        e.step()
        assert (r.position.x, r.position.y) != before
        assert pending not in r.orchestration_holds
        assert_holds(e)
    finally:
        client.release.set()
        wait_for(e, lambda s: not s["active"])
    assert_holds(e)


def test_queued_pair_dedupes_then_drops_after_actual_movement(engine_factory, monkeypatch):
    client = SlowLLMClient()
    e = engine_factory(client)
    e.robot_manager.create_robot(3, 6, 6)
    e.agent_manager.create_agents()
    a, _ = set_pair(e)
    fail_recovery(e, monkeypatch)
    try:
        e.orchestrator_runner.invoke_async([], [3])
        assert client.entered.wait(2)
        for _ in range(9):
            e.step()
        state = assert_holds(e)
        assert state["queued_crises"] == 1
        queued = state["queued_crisis_ids"][0]
        episode = e._deadlock_pairs[(1, 2)]["id"]
        for _ in range(20):
            assert e.orchestrator_runner.invoke_async([], [2, 1], kind=CrisisKind.DEADLOCK, episode_id=episode) == queued
        assert not a.orchestration_holds
        a.path = [(2, 2), (2, 3)]
        e.step()  # actual successful movement invalidates the episode token
        assert (a.position.x, a.position.y) == (2, 3)
        client.release.set()
        wait_for(e, lambda s: not s["active"])
        assert client.calls == 1
        dropped = e.events.query(event_type="STALE_DROPPED")
        assert any(r["crisis_id"] == queued and r["reason"] == "DEADLOCK_ALREADY_RESOLVED" for r in dropped)
        assert_holds(e)
    finally:
        client.release.set()


def test_queue_cap_and_no_pending_holds(engine_factory):
    client = SlowLLMClient()
    e = engine_factory(client, max_pending_crisis=2)
    try:
        e.orchestrator_runner.invoke_async([], [1])
        assert client.entered.wait(2)
        admitted = [e.orchestrator_runner.invoke_async([], [2]) for _ in range(10)]
        assert sum(x is not None for x in admitted) == 2
        assert e.events.totals()[0]["BACKPRESSURE"] == 8
        assert not e.robot_manager.get_robot(2).orchestration_holds
        assert_holds(e)
    finally:
        client.release.set()
        e.close()
    assert all(not r.orchestration_holds for r in e.robot_manager.robots)


@pytest.mark.parametrize("control", ["HOLD", "YIELD", "CHARGING", "IDLE"])
def test_intentional_stationary_state_cannot_escalate(engine_factory, control):
    client = ScriptedClient(plan(action(hold_steps=1)))
    e = engine_factory(client)
    a, b = set_pair(e)
    if control == "HOLD":
        b.hold_steps_remaining = 50
    elif control == "YIELD":
        b.yield_steps_remaining = 50
        b.yield_to_robot_id = 1
    elif control == "CHARGING":
        e.task_manager.release_task(b)
        b.status = RobotStatus.CHARGING
        b.path = [(3, 2), (2, 2), (1, 2), (0, 2), (0, 1), (0, 0)]
    else:
        # No re-auction should turn this idle fixture into a moving worker.
        e.task_manager.complete_task(b.current_task)
        b.current_task = None
        b.status = RobotStatus.IDLE
        b.path = []
        b.delivery_path = []
    for _ in range(30):
        e.step()
    assert client.calls == 0
    assert not e._deadlock_pairs


@pytest.mark.parametrize("output", [
    plan(action(hold_steps=1)), "{malformed", plan(action(robot_id=99, hold_steps=1)),
    PlanError("LLM_TIMEOUT", "timeout"), PlanError("LLM_UNAVAILABLE", "offline"), RuntimeError("unexpected")])
def test_all_terminal_outcomes_remove_active_holds(engine_factory, output):
    e = engine_factory(ScriptedClient(output), max_regenerations=0)
    crisis = e.orchestrator_runner.invoke_async([], [1])
    wait_for(e, lambda s: not s["active"] and s["active_node"] == "complete")
    assert all(crisis not in r.orchestration_holds for r in e.robot_manager.robots)
    assert_holds(e)


def test_hitl_timeout_and_execution_exception_cleanup(engine_factory, monkeypatch):
    e = engine_factory(ScriptedClient(plan(action(hold_steps=8))), hitl_timeout_seconds=0.02)
    e.orchestrator_runner.invoke_async([], [1])
    state = wait_for(e, lambda s: not s["active"] and s["active_node"] == "complete")
    assert state["fallback_reason"] == "HITL_TIMEOUT"
    assert_holds(e)
    e = engine_factory()
    def fail(*args, **kwargs):
        raise RuntimeError("executor failure")
    monkeypatch.setattr(e.orchestrator_runner.executor, "execute", fail)
    e.orchestrator_runner.invoke_async([], [1])
    wait_for(e, lambda s: not s["active"] and s["active_node"] == "complete")
    assert_holds(e)


def test_periodic_collapse_backpressure_keeps_grid_unchanged(engine_factory):
    client = SlowLLMClient()
    e = engine_factory(client)
    e.settings = e.settings.model_copy(update={"crisis_interval": 2})
    try:
        e.orchestrator_runner.invoke_async([], [1])
        assert client.entered.wait(2)
        assign(e,robot_id=1)
        revision = e.pathfinder.warehouse.revision
        for _ in range(8):
            e.step()
        assert e.pathfinder.warehouse.revision == revision
        assert e.events.totals()[0]["PERIODIC_SKIPPED"] == 4
        assert_holds(e)
    finally:
        client.release.set()


def test_queued_collapse_waits_then_replans_at_activation(engine_factory):
    client = SlowLLMClient()
    e = engine_factory(client)
    r, _ = assign(e, 2, pickup=(5, 2), delivery=(6, 2))
    assert (5, 4) in r.path
    try:
        e.orchestrator_runner.invoke_async([], [1])
        assert client.entered.wait(2)
        crisis = e.trigger_warehouse_crisis([(5, 4)])
        assert crisis is not None and not r.orchestration_holds
        assert e.pathfinder.warehouse.grid[4][5] == "."
        assert (5, 4) in r.path  # Queued physical effects have not happened yet.
        client.release.set()
        wait_for(e, lambda s: not s["active"] and s["crisis_id"] == crisis)
        assert e.pathfinder.warehouse.grid[4][5] == "S"
        assert (5, 4) not in r.path
        assert e.pathfinder._validate_path_integrity(r.path)
        e.step()
        assert (r.position.x, r.position.y) != (5, 4)
    finally:
        client.release.set()


def test_slow_local_llm_allows_1000_ticks_without_queue_freeze(tmp_path):
    client = SlowLLMClient()
    e = create_simulation(seed=42, settings=Settings(crisis_interval=50), llm_client=client)
    snapshots = []
    try:
        active = e.orchestrator_runner.invoke_async([], [1])
        assert client.entered.wait(2)
        for _ in range(20):
            e.orchestrator_runner.invoke_async([], [2])
        for step in range(1, 1001):
            e.step()
            state = assert_holds(e)
            assert state["crisis_id"] == active
            assert not e.robot_manager.get_robot(2).orchestration_holds
            if step in (100, 300, 500, 1000):
                snapshots.append(e.health_snapshot())
        assert client.calls == 1 and not client.release.is_set()
        assert all(s["orchestration_pinned"] == 1 and s["orphaned_holds"] == 0 for s in snapshots)
        assert all(b["completed_tasks"] == 120 or b["successful_moves"] > a["successful_moves"] for a, b in zip(snapshots, snapshots[1:]))
        assert snapshots[-1]["completed_tasks"] > 0
        assert any(s["charging"] > 0 for s in snapshots)
        assert 0 < e.events.totals()[0]["PERIODIC_SKIPPED"] <= 20
        (tmp_path / "slow_llm_health.json").write_text(json.dumps(snapshots, indent=2))
        print("SLOW_LLM_HEALTH=" + json.dumps(snapshots))
    finally:
        e.close()
        client.release.set()
    assert all(not r.orchestration_holds for r in e.robot_manager.robots)


def test_seed42_3000_steps_progress_queue_and_path_safety(tmp_path):
    e = create_simulation(seed=42, settings=Settings(), llm_client=FaultClient("LLM_OFFLINE"))
    snapshots = []
    try:
        assert len(e.robot_manager.robots) == 40 and len(e.task_manager.tasks) == 120
        for step in range(1, 3001):
            before = {r.id: (r.position.x, r.position.y) for r in e.robot_manager.robots}
            e.step()
            settle(e)  # deterministic comparison barrier; slow concurrency has its own test
            assert_holds(e)
            positions = [(r.position.x, r.position.y) for r in e.robot_manager.robots]
            assert len(set(positions)) == 40
            for r in e.robot_manager.robots:
                pos = (r.position.x, r.position.y)
                assert e.pathfinder.warehouse.is_walkable(*pos)
                assert sum(abs(a-b) for a, b in zip(before[r.id], pos)) <= 1
                assert 0 <= r.battery <= 100
            if step in (100, 300, 500, 1000, 3000):
                snapshots.append(e.health_snapshot())
        assert all(s["orphaned_holds"] == 0 and s["orchestration_pinned"] == 0 for s in snapshots)
        assert all(b["completed_tasks"] == 120 or b["successful_moves"] > a["successful_moves"] for a, b in zip(snapshots, snapshots[1:]))
        assert snapshots[-1]["completed_tasks"] > snapshots[0]["completed_tasks"]
        (tmp_path / "seed42_health.json").write_text(json.dumps(snapshots, indent=2))
        print("LONG_RUN_HEALTH=" + json.dumps(snapshots))
    finally:
        e.close()


def test_startup_and_recovery_failure_still_release_holds(engine_factory, monkeypatch):
    e = engine_factory()
    def fail(*args, **kwargs):
        raise RuntimeError("startup failure")
    monkeypatch.setattr(e.orchestrator_runner, "_build_graph", fail)
    monkeypatch.setattr(e.orchestrator_runner.executor, "fallback", fail)
    e.orchestrator_runner.invoke_async([], [1])
    assert not e.orchestrator_runner.is_active
    assert_holds(e)


def test_stale_queue_pruned_before_capacity_check(engine_factory, monkeypatch):
    client = SlowLLMClient()
    e = engine_factory(client, max_pending_crisis=1)
    e.robot_manager.create_robot(3, 6, 6)
    e.agent_manager.create_agents()
    a, _ = set_pair(e)
    fail_recovery(e, monkeypatch)
    try:
        e.orchestrator_runner.invoke_async([], [3])
        assert client.entered.wait(2)
        for _ in range(9):
            e.step()
        assert e.orchestrator_runner.get_state()["queued_crises"] == 1
        e.task_manager.release_task(a)
        assert e.orchestrator_runner.invoke_async([], [1]) is not None
        assert e.events.totals()[0]["STALE_DROPPED"] == 1
        assert e.events.totals()[0].get("BACKPRESSURE", 0) == 0
        assert_holds(e)
    finally:
        e.close()
        client.release.set()


def test_clearing_current_tick_does_not_erase_queued_evidence(engine_factory, monkeypatch):
    client = SlowLLMClient()
    e = engine_factory(client)
    e.robot_manager.create_robot(3, 6, 6)
    e.agent_manager.create_agents()
    set_pair(e)
    fail_recovery(e, monkeypatch)
    try:
        e.orchestrator_runner.invoke_async([], [3])
        assert client.entered.wait(2)
        for _ in range(9):
            e.step()
        e._contention.clear()  # beginning of next tick, before periodic injection
        episode = e._deadlock_pairs[(1, 2)]["id"]
        queued = e.orchestrator_runner.get_state()["queued_crisis_ids"][0]
        assert e.orchestrator_runner.invoke_async([], [1, 2], kind="deadlock", episode_id=episode) == queued
        assert e.events.totals()[0].get("STALE_DROPPED", 0) == 0
    finally:
        e.close()
        client.release.set()


def test_real_failed_recovery_in_narrow_aisle_eventually_escalates(engine_factory):
    client = SlowLLMClient()
    e = engine_factory(client)
    a, b = set_pair(e)
    warehouse = e.pathfinder.warehouse
    warehouse.grid = [["S"] * 8 for _ in range(8)]
    for x in range(7):
        warehouse.grid[2][x] = "."
    warehouse.grid[2][0] = "C"
    warehouse.revision += 1
    try:
        for _ in range(40):
            e.step()
            if e.orchestrator_runner.is_active:
                break
        assert client.entered.wait(2)
        assert client.calls == 1
        assert e.events.totals()[0]["DEADLOCK_PERSISTENT"] == 1
        assert e._deadlock_pairs[(1, 2)]["persistent_ticks"] >= 6
        assert e.current_step > 9  # deterministic hold/replan pauses don't count
        assert_holds(e)
    finally:
        e.close()
        client.release.set()


def test_recoveries_on_different_ticks_are_remembered(engine_factory):
    client = SlowLLMClient()
    e = engine_factory(client)
    set_pair(e)
    e.agent_manager.get_agent(1).blocked_counter = 1
    warehouse = e.pathfinder.warehouse
    warehouse.grid = [["S"] * 8 for _ in range(8)]
    for x in range(7):
        warehouse.grid[2][x] = "."
    warehouse.grid[2][0] = "C"
    warehouse.revision += 1
    try:
        for _ in range(80):
            e.step()
            if e.orchestrator_runner.is_active:
                break
        assert client.entered.wait(2)
        assert e._deadlock_pairs[(1, 2)]["recovered"] == {1, 2}
        assert_holds(e)
    finally:
        e.close()
        client.release.set()

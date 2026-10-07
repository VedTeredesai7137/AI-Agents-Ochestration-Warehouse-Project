"""Admission, physical activation, cleanup and shared run budget regressions."""
import threading
import pytest

from backend.agents.llm_client import FaultClient
from backend.agents.orchestrator_graph import CrisisKind
from backend.agents.plans import PlanError
from backend.core.settings import Settings
from backend.core.models import RobotStatus
from backend.evaluation.runner import settle
from backend.simulation.factory import create_simulation
from conftest import assign, wait_for


class PendingClient:
    model = "pending-test"

    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()

    def generate(self, prompt, schema):
        self.entered.set()
        assert self.release.wait(5)
        raise PlanError("LLM_TIMEOUT", "injected timeout")


def test_manual_uses_budget_and_postpones_next_auto(engine_factory):
    client = PendingClient()
    e = engine_factory(client, crisis_budget=2)
    robot, task = assign(e)
    initial_position = (robot.position.x,robot.position.y)
    e.settings = e.settings.model_copy(update={"crisis_interval": 10})
    e.current_step = 9
    crisis = e.trigger_crisis(CrisisKind.ROBOT_IMMOBILIZED, robot_ids=[1])
    try:
        assert client.entered.wait(1)
        summary = e.crisis_summary()
        assert summary["crises_submitted"] == 1 and summary["crises_remaining"] == 1
        assert summary["next_automatic_crisis_step"] == 19
        for _ in range(9):
            e.step()
        assert e.measurements["automatic_crises"] == 0
        assert e.robot_manager.get_robot(1).fault_reason
        assert (robot.position.x,robot.position.y) == initial_position and not task.completed
    finally:
        client.release.set()
    wait_for(e, lambda s: not s["active"] and s["crisis_id"] == crisis)
    assert e.crisis_summary()["crises_completed"] == 1
    assert not e.robot_manager.get_robot(1).fault_reason


def test_manual_plus_auto_never_exceeds_six_and_deliveries_remain_real():
    e = create_simulation(settings=Settings(crisis_interval=2, crisis_budget=6), llm_client=FaultClient("LLM_OFFLINE"))
    try:
        assert e.trigger_crisis(CrisisKind.ROBOT_IMMOBILIZED, robot_ids=[1])
        settle(e)
        for _ in range(60):
            e.step()
            settle(e)
        assert e.measurements["crisis_count"] == 6
        assert e.measurements["manual_crises"] == 1
        assert e.measurements["automatic_crises"] + e.measurements["natural_crises"] == 5
        assert e.crisis_summary()["crises_remaining"] == 0
        assert e.trigger_crisis(CrisisKind.ROBOT_IMMOBILIZED, robot_ids=[1]) is None
        assert e.measurements["crisis_count"] == 6
        assert e.health_snapshot()["orphaned_holds"] == 0
        assert all(t.delivery_position == (t.delivery_x,t.delivery_y) for t in e.task_manager.tasks if t.completed)
    finally:
        e.close()


def test_queued_incident_adds_no_fault_until_activation(engine_factory):
    client = PendingClient()
    e = engine_factory(client, crisis_budget=2)
    active = e.trigger_crisis(CrisisKind.ROBOT_IMMOBILIZED, robot_ids=[1])
    try:
        assert client.entered.wait(1)
        queued = e.trigger_crisis(CrisisKind.ROBOT_IMMOBILIZED, robot_ids=[2])
        second = e.robot_manager.get_robot(2)
        assert queued != active and queued is not None
        assert not second.fault_reason and not second.orchestration_holds
        assert e.orchestrator_runner.get_state()["queued_crises"] == 1
    finally:
        client.release.set()
    wait_for(e, lambda s: not s["active"] and s["crisis_id"] == queued)
    assert e.crisis_summary()["crises_completed"] == 2
    assert all(not r.fault_reason and not r.orchestration_holds for r in e.robot_manager.robots)


def test_charger_outage_is_real_and_restored_on_reset(engine_factory):
    client = PendingClient()
    e = engine_factory(client)
    warehouse = e.pathfinder.warehouse
    warehouse.grid[7][7] = "C"
    warehouse.revision += 1
    e.trigger_crisis(CrisisKind.CHARGER_OUTAGE)
    try:
        assert client.entered.wait(1)
        assert len(e.charging_manager.stations(e.pathfinder)) == 1
        e.orchestrator_runner.reset()
        assert len(e.charging_manager.stations(e.pathfinder)) == 2
        assert all(not r.orchestration_holds for r in e.robot_manager.robots)
    finally:
        client.release.set()


def test_failure_releases_task_through_cnp(engine_factory):
    e = engine_factory(FaultClient("LLM_OFFLINE"))
    robot, task = assign(e)
    crisis = e.trigger_crisis(CrisisKind.ROBOT_IMMOBILIZED, robot_ids=[robot.id])
    wait_for(e, lambda s: not s["active"] and s["crisis_id"] == crisis)
    assert task.reauction_count == 1 and task.assigned_robot is None
    assert robot.current_task is None and not robot.fault_reason
    e.step()
    assert e.task_agent_manager.get_agent(task.id).status in ("WAITING", "CFP_SENT")


def test_urgent_disruption_promotes_existing_order_and_reauctions(engine_factory):
    e = engine_factory(FaultClient("LLM_OFFLINE"))
    robot, task = assign(e)
    crisis = e.trigger_crisis(CrisisKind.CRITICAL_TASK, task_id=task.id)
    wait_for(e, lambda s: not s["active"] and s["crisis_id"] == crisis)
    assert len(e.task_manager.tasks) == 1 and task.priority == "CRITICAL"
    assert task.reauction_count == 1 and robot.current_task is None


def test_manual_deadlock_cannot_bypass_persistence_gate(engine):
    a,b = engine.robot_manager.robots
    b.position.x,b.position.y = 3,2
    assign(engine,1,pickup=(3,2),delivery=(4,2))
    assign(engine,2,pickup=(2,2),delivery=(1,2))
    pair=(1,2)
    engine._last_contention={1:2,2:1}
    engine._deadlock_pairs[pair] = dict(id=1, positions=engine._pair_positions(pair),
                                       tasks=engine._pair_tasks(pair), persistent_ticks=1)
    assert engine.trigger_crisis(CrisisKind.DEADLOCK,robot_ids=list(pair),episode_id=1) is None
    assert engine.crisis_summary()["crises_submitted"] == 0


def test_charger_outage_handles_charging_robot_with_empty_route(engine_factory):
    e = engine_factory(FaultClient("LLM_OFFLINE"))
    e.pathfinder.warehouse.grid[7][7] = "C"
    e.pathfinder.warehouse.revision += 1
    r = e.robot_manager.get_robot(1)
    r.status = RobotStatus.CHARGING
    r.path = []
    crisis = e.trigger_crisis(CrisisKind.CHARGER_OUTAGE)
    assert crisis is not None
    wait_for(e, lambda s: not s["active"] and s["crisis_id"] == crisis)
    assert len(e.charging_manager.stations(e.pathfinder)) == 2
    assert not r.orchestration_holds


def test_connected_collapse_cannot_strand_loaded_task_energy(engine):
    w = engine.pathfinder.warehouse
    for y in range(7):
        w.grid[y][1] = "S"
    w.grid[2][1] = "."
    w.grid[7][7] = "C"
    w.revision += 1
    robot,task = assign(engine,1,pickup=(2,2),delivery=(3,2))
    robot.battery = 14
    robot.carrying_item = True
    robot.path = [(2,2),(3,2)]
    robot.status = RobotStatus.DELIVERING
    assert engine._collapse_preserves_access([(1,2)],{(2,2),(3,2),(5,5)})
    with pytest.raises(ValueError,match="charging-energy"):
        engine.trigger_warehouse_crisis([(1,2)])
    assert w.grid[2][1] == "." and task.assigned_robot == robot.id
    assert engine.crisis_summary()["crises_submitted"] == 0

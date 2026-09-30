import threading
import time
import pytest
import requests

from backend.agents.llm_client import OllamaClient
from backend.agents.plans import PlanError
from backend.core.models import RobotStatus
from conftest import ScriptedClient, action, plan, wait_for, assign


def start(engine, affected=(1,)):
    return engine.orchestrator_runner.invoke_async([],list(affected))


def completed(engine):
    return wait_for(engine,lambda s: not s["active"] and s["active_node"]=="complete")


def test_high_score_autoexecutes(engine):
    start(engine)
    state=completed(engine)
    assert state["validation_status"]=="VALID"
    assert state["validation_score"]==1
    assert state["executed_actions"]==1 and not state["fallback_used"]
    assert engine.robot_manager.get_robot(1).hold_steps_remaining==1
    assert engine.events.totals()[0].get("HITL_REQUESTED",0)==0


def test_risky_valid_pauses_and_approval_executes(engine_factory):
    client=ScriptedClient(plan(action(hold_steps=8)))
    e=engine_factory(client,auto_execute_threshold=0.99)
    start(e)
    state=wait_for(e,lambda s:s["waiting_for_human"])
    assert state["validation_status"]=="VALID" and state["validation_score"]<0.99
    assert e.robot_manager.get_robot(1).hold_steps_remaining==0
    assert e.orchestrator_runner.human_override(True,state["plan_id"])["success"]
    assert completed(e)["executed_actions"]==1
    assert e.robot_manager.get_robot(1).hold_steps_remaining==8


def test_reject_regenerates_different_and_pauses_again(engine_factory):
    client=ScriptedClient(plan(action(hold_steps=8)),plan(action(hold_steps=9)))
    e=engine_factory(client)
    start(e)
    first=wait_for(e,lambda s:s["waiting_for_human"])
    assert e.orchestrator_runner.human_override(False,first["plan_id"])["success"]
    second=wait_for(e,lambda s:s["waiting_for_human"] and s["plan_id"]!=first["plan_id"])
    assert second["regeneration_count"]==1
    assert second["rejection_count"]==1
    assert second["proposed_plan"]["actions"][0]["hold_steps"]==9
    e.orchestrator_runner.human_override(True,second["plan_id"])
    assert completed(e)["executed_actions"]==1


def test_reject_repeated_strategy_cannot_be_reapproved(engine_factory):
    client=ScriptedClient(plan(action(hold_steps=8)))
    e=engine_factory(client,max_regenerations=1)
    start(e)
    state=wait_for(e,lambda s:s["waiting_for_human"])
    e.orchestrator_runner.human_override(False,state["plan_id"])
    state=completed(e)
    assert state["fallback_used"] and state["fallback_reason"]=="REJECTED_STRATEGY"
    assert client.calls==2


@pytest.mark.parametrize("code", ["LLM_TIMEOUT","LLM_UNAVAILABLE"])
def test_transport_failure_fallback(engine_factory,code):
    client=ScriptedClient(PlanError(code,"Injected failure"))
    e=engine_factory(client)
    start(e)
    state=completed(e)
    assert state["fallback_used"] and state["fallback_reason"]==code
    assert client.calls==1
    assert not e.robot_manager.get_robot(1).orchestration_holds
    e.step()
    assert e.current_step==1
    events=e.events.query(limit=100)
    assert any(row["event_type"]=="LLM_FAILURE" and row["error_code"]==code for row in events)


def test_malformed_json_repairs_then_executes(engine_factory):
    client=ScriptedClient("{oops",plan(action(hold_steps=1)))
    e=engine_factory(client)
    start(e)
    state=completed(e)
    assert not state["fallback_used"] and client.calls==2
    assert state["regeneration_count"]==1
    assert "LLM_INVALID_JSON" not in client.prompts[0]
    assert "Expecting" in client.prompts[1]


@pytest.mark.parametrize("payload", ["{broken",plan(action(robot_id=99,hold_steps=1)),plan(action("MAGIC"))])
def test_max_regeneration_bounded_no_unsafe_execute(engine_factory,monkeypatch,payload):
    client=ScriptedClient(payload)
    e=engine_factory(client,max_regenerations=2)
    calls=[]
    monkeypatch.setattr(e.orchestrator_runner.executor,"execute",lambda *a,**k:calls.append(a))
    start(e)
    state=completed(e)
    assert state["fallback_used"] and client.calls==3
    assert state["regeneration_count"]==2 and not calls
    assert not state["waiting_for_human"]


def test_human_rejections_also_bounded(engine_factory):
    client=ScriptedClient(plan(action(hold_steps=8)),plan(action(hold_steps=9)))
    e=engine_factory(client,max_regenerations=1)
    start(e)
    first=wait_for(e,lambda s:s["waiting_for_human"])
    e.orchestrator_runner.human_override(False,first["plan_id"])
    second=wait_for(e,lambda s:s["waiting_for_human"] and s["plan_id"]!=first["plan_id"])
    e.orchestrator_runner.human_override(False,second["plan_id"])
    assert completed(e)["fallback_used"]
    assert client.calls==2


def test_queue_keeps_all_entries_and_starts_next(engine_factory):
    client=ScriptedClient(plan(action(hold_steps=8)),plan(action(robot_id=2,hold_steps=8)),plan(action(hold_steps=8)))
    e=engine_factory(client)
    first=start(e)
    first_state=wait_for(e,lambda s:s["waiting_for_human"])
    second=start(e,(2,))
    third=start(e)
    assert e.orchestrator_runner.get_state()["queued_crises"]==2
    e.orchestrator_runner.human_override(True,first_state["plan_id"])
    state=wait_for(e,lambda s:s["waiting_for_human"] and s["crisis_id"]==second)
    assert state["queued_crises"]==1
    e.orchestrator_runner.human_override(True,state["plan_id"])
    state=wait_for(e,lambda s:s["waiting_for_human"] and s["crisis_id"]==third)
    e.orchestrator_runner.human_override(True,state["plan_id"])
    completed(e)
    events=e.events.query(limit=100)
    assert [r["crisis_id"] for r in events if r["event_type"]=="ORCH_START"]==[first,second,third]
    assert len([r for r in events if r["event_type"]=="ORCH_COMPLETE"])==3
    assert all(not r.orchestration_holds for r in e.robot_manager.robots)


def test_reset_cancels_inflight_mutation_without_waiting(engine_factory):
    entered,release=threading.Event(),threading.Event()
    def delayed():
        entered.set()
        release.wait(3)
        return '{"actions":[{"robot_id":1,"action":"HOLD","hold_steps":8,"reason":"delayed"}]}'
    e=engine_factory(ScriptedClient(delayed))
    start(e)
    assert entered.wait(2)
    began=time.monotonic()
    e.close()
    assert time.monotonic()-began<0.2
    release.set()
    time.sleep(0.05)
    assert not e.orchestrator_runner.is_active
    assert e.robot_manager.get_robot(1).hold_steps_remaining==0


def test_no_lock_held_during_inference(engine_factory):
    entered,release=threading.Event(),threading.Event()
    def delayed():
        entered.set(); release.wait(3)
        return '{"actions":[{"robot_id":1,"action":"HOLD","hold_steps":1,"reason":"wait"}]}'
    e=engine_factory(ScriptedClient(delayed))
    start(e)
    assert entered.wait(2)
    e.step()
    assert e.current_step==1
    release.set()
    completed(e)


def test_stale_operator_plan_is_conflict(engine_factory):
    e=engine_factory(ScriptedClient(plan(action(hold_steps=8))))
    start(e)
    state=wait_for(e,lambda s:s["waiting_for_human"])
    assert not e.orchestrator_runner.human_override(True,"wrong-plan")["success"]
    assert e.orchestrator_runner.get_state()["waiting_for_human"]
    assert e.orchestrator_runner.human_override(True,state["plan_id"])["success"]
    assert not e.orchestrator_runner.human_override(True,state["plan_id"])["success"]
    completed(e)


def test_live_validation_catches_changes_after_hitl(engine_factory):
    e=engine_factory(ScriptedClient(plan(action("REROUTE",waypoint={"x":2,"y":3}))),auto_execute_threshold=1)
    robot,_=assign(e)
    # A long-horizon conflict is a warning and requires human approval.
    other=e.robot_manager.get_robot(2)
    other.position.x,other.position.y=4,2
    start(e)
    state=wait_for(e,lambda s:s["waiting_for_human"])
    with e.lock:
        e.pathfinder.warehouse.grid[3][2]="S"
    e.orchestrator_runner.human_override(True,state["plan_id"])
    state=completed(e)
    assert state["fallback_used"] and state["executed_actions"]==0
    assert (robot.position.x,robot.position.y)==(2,2)


def test_worker_exception_visible_and_queue_continues(engine_factory):
    e=engine_factory(ScriptedClient(RuntimeError("injected worker failure")))
    start(e)
    state=completed(e)
    assert state["fallback_used"] and state["error"]
    assert not e.robot_manager.get_robot(1).orchestration_holds


def test_operator_timeout_releases_queue(engine_factory):
    e=engine_factory(ScriptedClient(plan(action(hold_steps=8))),hitl_timeout_seconds=0.05)
    start(e)
    state=completed(e)
    assert state["fallback_reason"]=="HITL_TIMEOUT"


@pytest.mark.parametrize("error,code", [(requests.Timeout(),"LLM_TIMEOUT"),(requests.ConnectionError(),"LLM_UNAVAILABLE")])
def test_ollama_boundary_categories_and_timeout(error,code):
    def post(url,**kwargs):
        assert kwargs["timeout"]==60.0
        assert kwargs["json"]["stream"] is False
        raise error
    with pytest.raises(PlanError) as exc:
        OllamaClient(post).generate("prompt",{})
    assert exc.value.code==code


def test_event_history_is_bounded(engine):
    for i in range(2100):
        engine.events.emit("TEST",robot_id=i%2)
    assert len(engine.events.query(limit=10000))==2000
    assert engine.events.totals()[0]["TEST"]==2100
    assert all(e["robot_id"]==1 for e in engine.events.query(robot_id=1))


def test_zero_regeneration_limit(engine_factory):
    client=ScriptedClient("{malformed")
    e=engine_factory(client,max_regenerations=0)
    start(e)
    assert completed(e)["fallback_used"] and client.calls==1


def test_failed_old_inference_after_reset_does_not_fallback_into_new_session(engine_factory):
    entered,release=threading.Event(),threading.Event()
    def delayed_failure():
        entered.set(); release.wait(2)
        raise PlanError("LLM_UNAVAILABLE","late failure")
    e=engine_factory(ScriptedClient(delayed_failure))
    start(e)
    assert entered.wait(1)
    e.orchestrator_runner.reset()
    before=[r.model_dump() for r in e.robot_manager.robots]
    release.set()
    time.sleep(.05)
    assert before==[r.model_dump() for r in e.robot_manager.robots]
    assert not e.orchestrator_runner.is_active

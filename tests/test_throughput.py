"""Throughput regressions retain real CNP, movement, energy, and delivery guards."""
import json
import pytest
from backend.core.models import RobotStatus, Position
from backend.agents.plans import generation_schema, parse_plan
from backend.evaluation.completion import run_completion, assert_invariants
from backend.simulation.factory import create_simulation
from backend.core.settings import Settings
from backend.agents.llm_client import FaultClient
from conftest import assign, action, plan


def test_task_offer_rejects_insufficient_pickup_energy(engine):
    r,t = assign(engine,pickup=(7,7),delivery=(6,7))
    r.battery = 8
    assert engine.charging_manager.task_offer(r,t,engine.pathfinder) is None


def test_task_offer_accounts_for_loaded_delivery_and_return(engine):
    r,t = assign(engine,pickup=(2,2),delivery=(7,7))
    r.battery = 40
    offer = engine.charging_manager.task_offer(r,t,engine.pathfinder)
    assert offer is not None  # 20 loaded +14 return +5 reserve fits.
    engine.pathfinder.warehouse.grid[0][0] = "."
    engine.pathfinder.warehouse.revision += 1
    assert engine.charging_manager.task_offer(r,t,engine.pathfinder) is None


def test_owned_feasible_task_does_not_charge_at_fixed_30(engine):
    r,t = assign(engine,pickup=(3,2),delivery=(4,2))
    r.battery = 25
    e = engine.agent_manager.get_agent(r.id)
    e.tick(**engine.context())
    assert r.current_task == t.id and r.status != RobotStatus.CHARGING
    assert (r.position.x,r.position.y) == (3,2)


def test_charger_selection_avoids_occupied_and_inbound_bays(engine):
    w = engine.pathfinder.warehouse
    w.grid[0][7] = "C"; w.revision += 1
    a,b = engine.robot_manager.robots
    b.status = RobotStatus.CHARGING; b.path = [(5,5),(0,0)]
    path = engine.charging_manager.get_charge_path(a,engine.pathfinder,congestion=True)
    assert path[-1] == (7,0)
    b.position = Position(x=7,y=0); b.path = []
    assert engine.charging_manager.get_charge_path(a,engine.pathfinder,congestion=True)[-1] == (0,0)


def test_full_robot_can_depart_station_toward_next_station(engine):
    r = engine.robot_manager.get_robot(1)
    r.position = Position(x=0,y=0); r.status = RobotStatus.CHARGING
    r.path = [(0,0),(1,0),(2,0)]
    a = engine.agent_manager.get_agent(1)
    a.perceive(ctx=engine.context())
    assert a.decide() == "move"


def test_loaded_charging_retains_owner_and_resumes_delivery(engine):
    r,t = assign(engine,delivery=(6,2))
    r.carrying_item = True; r.position = Position(x=0,y=0)
    r.status = RobotStatus.CHARGING; r.path = [(0,0)]; r.battery = 90
    a = engine.agent_manager.get_agent(1)
    a.tick(**engine.context()); a.tick(**engine.context())
    assert r.current_task == t.id and t.assigned_robot == r.id
    assert r.carrying_item and r.status == RobotStatus.DELIVERING
    assert r.path[-1] == (6,2) and t.reauction_count == 0


def test_long_delivery_plans_real_recharge_stop(engine):
    w=engine.pathfinder.warehouse
    w.width=70; w.height=4; w.create_empty_grid()
    for x in (0,20,40,60): w.grid[0][x]="C"
    w.revision+=1
    r=engine.robot_manager.get_robot(1);r.position=Position(x=0,y=0)
    route=engine.charging_manager.journey((0,0),(60,0),100,engine.pathfinder,loaded=True)
    assert route is not None and route[0][-1] != (60,0)
    assert (len(route[0])-1)*2+5 <= 100


def test_movement_detour_preserves_energy_to_charger(engine):
    r,t=assign(engine,pickup=(7,7),delivery=(6,7))
    r.battery=4; r.path=[(2,2),(3,2)]
    engine.agent_manager.get_agent(1)._handle_move(engine.context())
    assert (r.position.x,r.position.y)==(2,2)
    assert r.status==RobotStatus.CHARGING and r.current_task==t.id
    assert r.path[-1]==(0,0)


def test_feasible_traffic_detour_is_not_replaced_by_shortest_path(engine):
    r,t=assign(engine)
    r.path=[(2,2),(2,3),(3,3),(4,3),(5,3),(5,2)]
    before=list(r.path)
    engine.agent_manager.get_agent(1)._plan_task_charging(engine.context())
    assert r.path==before


def test_delivery_evidence_rejects_remote_completion(engine):
    r,t=assign(engine)
    r.carrying_item=True
    with pytest.raises(ValueError): engine.task_manager.complete_task(t.id,robot=r)
    assert not t.completed and t.delivered_by is None


def test_generation_grammar_requires_action_parameter():
    schema=generation_schema()
    branches=schema["$defs"]["RobotAction"]["oneOf"]
    hold=next(b for b in branches if b["properties"]["action"]["const"]=="HOLD")
    assert "hold_steps" in hold["required"]
    assert hold["properties"]["hold_steps"]["type"]=="integer"
    assert not hold["additionalProperties"]
    parse_plan(json.dumps(plan(action(hold_steps=2))))


def test_prompt_only_contains_affected_robots(engine):
    from backend.agents.orchestrator_graph import CrisisRequest
    from backend.agents.plan_validator import WorldSnapshot
    request=CrisisRequest("test",[(3,2)],[1],0)
    prompt=engine.orchestrator_runner._plan_prompt(request,WorldSnapshot.capture(engine),{})
    assert len(prompt)<2500 and '"grid"' not in prompt
    assert '"robot_id":2' not in prompt and '"robot_id":1' in prompt


def test_automatic_crises_obey_legacy_configured_total_limit(engine):
    from backend.evaluation.runner import settle
    assign(engine)
    engine.robot_manager.get_robot(1).hold_steps_remaining=100
    engine.settings=Settings(crisis_interval=2,automatic_crisis_limit=3)
    engine.orchestrator_runner.client=FaultClient("LLM_OFFLINE")
    engine.pathfinder.warehouse.grid[7][7]="C"
    engine.pathfinder.warehouse.revision+=1
    for _ in range(30):
        engine.step()
        settle(engine)
    assert engine.measurements["crisis_count"]==3
    assert engine.crisis_summary()["crises_remaining"]==0


def test_automatic_collapse_preserves_unfinished_endpoints():
    e=create_simulation(settings=Settings(crisis_interval=0),llm_client=FaultClient("LLM_OFFLINE"))
    try:
        for _ in range(3): e.trigger_warehouse_crisis(periodic=True)
        assert all(e.pathfinder.warehouse.is_walkable(t.pickup_x,t.pickup_y)
                   and e.pathfinder.warehouse.is_walkable(t.delivery_x,t.delivery_y) for t in e.task_manager.tasks)
    finally: e.close()


def test_normal_120_task_completion_under_15_minutes(tmp_path,monkeypatch):
    monkeypatch.setenv("CRISIS_BUDGET","6")
    result=run_completion(seed=42,fault="LLM_OFFLINE",timeout=900)
    (tmp_path/"completion.json").write_text(json.dumps(result,indent=2))
    assert result["passed"]
    assert result["metrics"]["task_completion_count"]==120
    assert 0 < result["metrics"]["crisis_count"] <= 6
    assert result["metrics"]["successful_moves"]>0
    assert result["metrics"]["charging_events"]>0
    assert all(s["orphaned_holds"]==0 for s in result["health"])


def test_idle_robot_clears_passing_space_when_blocked_path_was_cleared(engine):
    idle=engine.robot_manager.get_robot(2)
    idle.position=Position(x=3,y=2)
    waiting=engine.robot_manager.get_robot(1)
    waiting.position=Position(x=3,y=3)
    waiting.path=[]
    engine._deadlocks[1]=0
    agent=engine.agent_manager.get_agent(2)
    agent._handle_idle(engine.context())
    assert len(idle.path)==2
    before=abs(3-waiting.position.x)+abs(2-waiting.position.y)
    after=sum(abs(a-b) for a,b in zip(idle.path[-1],(3,3)))
    assert after>before
    engine.collision_manager.reset_step(engine.robot_manager.robots)
    agent._handle_move(engine.context())
    assert (idle.position.x,idle.position.y)==tuple(idle.path[-1])


def test_charger_entrance_retreat_reaches_nearby_passing_space(engine):
    # Two robots oppose each other; the free bay cell has degree two, but
    # a genuine passing space is two moves away. Neither robot may teleport.
    w=engine.pathfinder.warehouse
    w.grid=[["S"]*8 for _ in range(8)]
    for cell in ((1,3),(2,3),(3,3),(4,3),(5,3),(5,2),(5,4),(6,3)):
        w.grid[cell[1]][cell[0]]="."
    w.grid[3][4]="C";w.revision+=1
    a=engine.robot_manager.get_robot(1);a.position=Position(x=3,y=3)
    b=engine.robot_manager.get_robot(2);b.position=Position(x=2,y=3)
    b.status=RobotStatus.CHARGING;b.path=[(2,3),(3,3),(4,3)];b.battery=6
    a,t=assign(engine,pickup=(2,3),delivery=(1,3))
    engine.orchestrator_runner.executor.fallback([1],"DETERMINISTIC_DEADLOCK")
    assert a.path==[(3,3),(4,3),(5,3)]
    before=(a.position.x,a.position.y)
    engine.collision_manager.reset_step(engine.robot_manager.robots)
    engine.agent_manager.get_agent(1)._handle_move(engine.context())
    assert (a.position.x,a.position.y)==(4,3) and before==(3,3)
    assert a.current_task==t.id


def test_owned_charging_reroute_targets_bay_without_fake_delivery_leg(engine,capsys):
    from backend.agents.plan_validator import WorldSnapshot
    r,t=assign(engine)
    r.status=RobotStatus.CHARGING
    r.path=engine.pathfinder.find_path((2,2),(0,0))
    world=WorldSnapshot.capture(engine)
    assert world.destination(world.robots[1])==(0,0)
    report=engine.orchestrator_runner.validator.validate(
        parse_plan(json.dumps(plan(action("REROUTE",waypoint={"x":2,"y":1})))),world)
    assert report.valid
    assert report.action_results[0].route[-1]==(0,0)
    assert report.action_results[0].delivery_route==[]
    assert "non-adjacent" not in capsys.readouterr().out


def test_owned_charging_recovery_keeps_immediate_charger_destination(engine):
    r,t=assign(engine)
    r.status=RobotStatus.CHARGING;r.carrying_item=True;r.path=[]
    engine.agent_manager.get_agent(1)._recover_route(engine.context())
    assert r.path[-1]==(0,0) and r.current_task==t.id and r.carrying_item

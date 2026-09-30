import json
from copy import deepcopy
import pytest

from backend.agents.plans import CrisisPlan, PlanError, parse_plan
from backend.agents.plan_validator import WorldSnapshot
from backend.agents.action_executor import ExecutionError
from backend.agents.message_bus import MessageType
from backend.core.models import RobotStatus
from backend.simulation.factory import create_simulation
from backend.core.settings import Settings
from conftest import action, plan, assign


def validate(engine, payload):
    return engine.orchestrator_runner.validator.validate(CrisisPlan.model_validate(payload), WorldSnapshot.capture(engine))


def execute(engine, payload, approved=False):
    return engine.orchestrator_runner.executor.execute(CrisisPlan.model_validate(payload), human_approved=approved)


def test_astar_obstacle_and_orthogonal(engine):
    engine.pathfinder.warehouse.grid[2][3] = "S"
    path = engine.pathfinder.find_path((2,2),(5,2))
    assert path and (3,2) not in path
    assert all(abs(a[0]-b[0])+abs(a[1]-b[1]) == 1 for a,b in zip(path,path[1:]))


@pytest.mark.parametrize("start,goal", [((-1,0),(1,1)),((1,1),(8,0)),((3,2),(5,2)),((2,2),(3,2))])
def test_astar_rejects_bad_endpoints(engine,start,goal):
    engine.pathfinder.warehouse.grid[2][3] = "S"
    assert engine.pathfinder.find_path(start,goal) == []


@pytest.mark.parametrize("route", [[(1,1),(2,2)],[(1,1),(3,1)],[(1,1),(-1,1)]])
def test_path_integrity_rejects_corruption(engine,route):
    assert not engine.pathfinder._validate_path_integrity(route)


def test_pathfinder_dynamic_occupancy(engine):
    route = engine.pathfinder.find_path((2,2),(5,2), blocked_cells={(3,2)})
    assert route and (3,2) not in route


def test_cnp_awards_valid_proposals_and_unique_ownership(engine):
    for x in (3,4,5):
        task = engine.task_manager.create_task(x,2,x,3)
        engine.task_agent_manager.create_agent_for_task(task.id)
    for _ in range(8):
        engine.step()
        for t in engine.task_manager.tasks:
            claimants = [r.id for r in engine.robot_manager.robots if r.current_task == t.id]
            assert len(claimants) <= 1
            if claimants:
                assert t.assigned_robot == claimants[0]
    assert any(t.assigned_step is not None for t in engine.task_manager.tasks)


def test_task_cannot_be_overwritten(engine):
    _, task = assign(engine)
    with pytest.raises(ValueError):
        engine.task_manager.assign_task(task.id,2)


def test_release_reenters_cnp_and_keeps_carried_parcel(engine):
    robot, task = assign(engine)
    robot.carrying_item = True
    engine.task_manager.release_task(robot,engine.agent_manager.message_bus)
    assert (task.pickup_x,task.pickup_y) == (2,2)
    assert task.assigned_robot is None and robot.current_task is None
    assert task.reauction_count == 1
    engine.task_agent_manager.tick_all(engine.robot_manager,engine.pathfinder)
    assert engine.task_agent_manager.get_agent(task.id).status == "WAITING"
    engine.task_agent_manager.tick_all(engine.robot_manager,engine.pathfinder)
    assert engine.task_agent_manager.get_agent(task.id).status == "CFP_SENT"


def test_completed_task_never_reauctions(engine):
    robot, task = assign(engine)
    engine.task_manager.complete_task(task.id)
    engine.task_manager.unassign_task(task.id)
    engine.task_agent_manager.tick_all(engine.robot_manager,engine.pathfinder)
    assert engine.task_agent_manager.get_agent(task.id).status == "COMPLETED"
    assert task not in engine.task_manager.get_unassigned_tasks()
    with pytest.raises(ValueError):
        engine.task_manager.assign_task(task.id,2)


@pytest.mark.parametrize("battery", [-10,0,0.5,100,130])
def test_battery_is_bounded(engine,battery):
    robot = engine.robot_manager.get_robot(1)
    robot.battery = battery
    engine.agent_manager.get_agent(1).tick(**engine.context())
    assert 0 <= robot.battery <= 100


@pytest.mark.parametrize("bad_path", [[(2,2),(3,2),(4,2),(5,2)],[(2,2),(4,2),(5,2)],[(0,0),(1,0)]])
def test_stale_path_recovers_without_movement(engine,bad_path):
    robot, _ = assign(engine)
    robot.path = bad_path
    engine.pathfinder.warehouse.grid[2][4] = "S"
    engine.agent_manager.get_agent(1)._handle_move(engine.context())
    assert (robot.position.x,robot.position.y) == (2,2)
    assert not robot.path or engine.pathfinder._validate_path_integrity(robot.path)


def test_empty_path_does_not_teleport_pickup_or_delivery(engine):
    robot,task = assign(engine)
    robot.path = []
    engine.agent_manager.get_agent(1).tick(**engine.context())
    assert not robot.carrying_item and not task.completed
    robot.carrying_item = True
    robot.path = []
    engine.agent_manager.get_agent(1)._handle_deliver(engine.context())
    assert not task.completed


def test_empty_delivery_guard(engine):
    robot,task = assign(engine,pickup=(2,2))
    robot.delivery_path=[]
    engine.agent_manager.get_agent(1)._handle_pickup(engine.context())
    assert task.assigned_robot is None and not robot.carrying_item


def test_hold_really_holds_exact_steps(engine):
    robot,_ = assign(engine)
    execute(engine,plan(action(hold_steps=2)))
    for _ in range(2):
        engine.step()
        assert (robot.position.x,robot.position.y) == (2,2)
    engine.step()
    assert (robot.position.x,robot.position.y) != (2,2)


def test_stationary_robots_and_swaps_are_blocked(engine):
    robot, _ = assign(engine)
    other=engine.robot_manager.get_robot(2)
    other.position.x,other.position.y=3,2
    other.path=[(3,2),(2,2)]
    engine.collision_manager.reset_step(engine.robot_manager.robots)
    engine.agent_manager.get_agent(1)._handle_move(engine.context())
    engine.agent_manager.get_agent(2)._handle_move(engine.context())
    assert (robot.position.x,robot.position.y)==(2,2)
    assert (other.position.x,other.position.y)==(3,2)


def test_yield_changes_conflict_winner(engine):
    one=engine.robot_manager.get_robot(1)
    two=engine.robot_manager.get_robot(2)
    two.position.x,two.position.y=4,2
    one.path=[(2,2),(3,2)]
    two.path=[(4,2),(3,2)]
    # HOLD/YIELD target does not occupy the actor's position.
    execute(engine,plan(action("YIELD",yield_to_robot_id=2)),approved=True)
    engine.step()
    assert (one.position.x,one.position.y)==(2,2)
    assert (two.position.x,two.position.y)==(3,2)


@pytest.mark.parametrize("raw", ['{','[]','{}','{"actions": []}',json.dumps(plan(action("MAGIC")))])
def test_invalid_llm_schema_rejected(raw):
    with pytest.raises(PlanError):
        parse_plan(raw)


def test_fenced_json_parses():
    p = parse_plan("```json\n"+json.dumps(plan(action(hold_steps=1)))+"\n```")
    assert p.actions[0].robot_id == 1


@pytest.mark.parametrize("payload", [plan(action(hold_steps=0)),plan(action(hold_steps=1,waypoint={"x":1,"y":2})),
                                     plan(action("REROUTE")),plan(action("YIELD",yield_to_robot_id=1)),
                                     plan(action(hold_steps=True)),plan(action("REROUTE",waypoint={"x":"1","y":2}))])
def test_action_specific_schema(payload):
    with pytest.raises(PlanError):
        parse_plan(json.dumps(payload))


@pytest.mark.parametrize("payload,code", [(plan(action(robot_id=99,hold_steps=1)),"INVALID_ROBOT"),
     (plan(action(hold_steps=99)),"HOLD_OUT_OF_RANGE"),
     (plan(action("REROUTE",waypoint={"x":-1,"y":2})),"INVALID_WAYPOINT"),
     (plan(action("REASSIGN_TASK",task_id=99)),"INVALID_TASK_REASSIGNMENT"),
     (plan(action(hold_steps=1),action(hold_steps=2)),"DUPLICATE_ACTION"),
     (plan(action("YIELD",yield_to_robot_id=99)),"INVALID_YIELD_TARGET")])
def test_invalid_semantics(engine,payload,code):
    report=validate(engine,payload)
    assert not report.valid
    assert code in [i.code for i in report.issues]


def test_unreachable_waypoint(engine):
    assign(engine)
    for x,y in ((0,1),(1,0),(2,1),(1,2)):
        engine.pathfinder.warehouse.grid[y][x]="S"
    report=validate(engine,plan(action("REROUTE",waypoint={"x":1,"y":1})))
    assert not report.valid
    assert "UNREACHABLE_WAYPOINT" in [i.code for i in report.issues]


def test_reroute_accepted_deterministic_and_nonmutating(engine):
    robot,_=assign(engine)
    payload=plan(action("REROUTE",waypoint={"x":2,"y":3}))
    before=robot.model_dump()
    a,b=validate(engine,payload),validate(engine,payload)
    assert a.valid and a.validation_score==b.validation_score
    assert a.model_dump()==b.model_dump() and before==robot.model_dump()


def test_reroute_visits_selected_waypoint(engine):
    robot,_=assign(engine)
    execute(engine,plan(action("REROUTE",waypoint={"x":2,"y":3})))
    assert robot.path[1]==(2,3)
    engine.step()
    assert (robot.position.x,robot.position.y)==(2,3)


def test_reassign_executor_uses_cnp(engine):
    robot,task=assign(engine)
    execute(engine,plan(action("REASSIGN_TASK",task_id=task.id)),approved=True)
    assert robot.current_task is None and task.assigned_robot is None
    engine.step()
    assert engine.task_agent_manager.get_agent(task.id).status=="WAITING"


def test_charger_executor_releases_safely(engine):
    robot,task=assign(engine)
    robot.carrying_item=True
    execute(engine,plan(action("GO_TO_CHARGER")),approved=True)
    assert robot.status==RobotStatus.CHARGING
    assert robot.path[-1]==(0,0)
    assert not robot.carrying_item and task.assigned_robot is None
    assert (task.pickup_x,task.pickup_y)==(2,2)


def test_execution_staging_failure_has_no_partial_mutation(engine,monkeypatch):
    one,_=assign(engine)
    robots=[r.model_dump() for r in engine.robot_manager.robots]
    tasks=deepcopy(engine.task_manager.tasks)
    executor=engine.orchestrator_runner.executor
    original=executor._stage
    def fail_second(action,result,robot,tm):
        original(action,result,robot,tm)
        if robot.id==2:
            raise RuntimeError("injected staging failure")
    monkeypatch.setattr(executor,"_stage",fail_second)
    with pytest.raises(RuntimeError):
        execute(engine,plan(action(hold_steps=1),action(robot_id=2,hold_steps=1)))
    assert robots==[r.model_dump() for r in engine.robot_manager.robots]
    assert tasks==engine.task_manager.tasks


def test_unsafe_plan_cannot_mutate(engine):
    before=[r.model_dump() for r in engine.robot_manager.robots]
    with pytest.raises(ExecutionError):
        execute(engine,plan(action("REROUTE",waypoint={"x":99,"y":99})),approved=True)
    assert before==[r.model_dump() for r in engine.robot_manager.robots]


def test_battery_infeasible_and_no_charger(engine):
    robot,_=assign(engine)
    robot.battery=1
    report=validate(engine,plan(action("GO_TO_CHARGER")))
    assert "BATTERY_INFEASIBLE" in [i.code for i in report.issues]
    engine.pathfinder.warehouse.grid[0][0]="."
    report=validate(engine,plan(action("GO_TO_CHARGER")))
    assert "INVALID_CHARGER_ROUTE" in [i.code for i in report.issues]


def test_message_bus_delivery_and_clear(engine):
    bus=engine.agent_manager.message_bus
    msg=bus.create_message("robot_1","robot_2",MessageType.HELP_REQUEST)
    bus.publish(msg)
    assert bus.get_messages("robot_2")==[msg]
    assert bus.get_messages("robot_2")==[]
    bus.broadcast(msg)
    assert bus.get_messages("robot_1")==[]
    assert bus.get_messages("robot_2")==[msg]


def test_seed_reproduces_grid_tasks_spawns():
    settings=Settings(orchestrator_enabled=False,crisis_interval=0)
    a=create_simulation(seed=42,settings=settings,task_count=3)
    b=create_simulation(seed=42,settings=settings,task_count=3)
    try:
        assert a.run_id != b.run_id
        assert a.pathfinder.warehouse.grid==b.pathfinder.warehouse.grid
        assert a.robot_manager.robots==b.robot_manager.robots
        assert a.task_manager.tasks==b.task_manager.tasks
        for _ in range(6):
            a.step(); b.step()
        assert a.robot_manager.robots==b.robot_manager.robots
    finally:
        a.close(); b.close()


def test_duplicate_json_keys_rejected():
    with pytest.raises(PlanError):
        parse_plan('{"actions":[],"actions":[]}')


def test_reroute_crisis_cells_rejected_even_on_walkable_grid(engine):
    assign(engine)
    candidate=CrisisPlan.model_validate(plan(action("REROUTE",waypoint={"x":2,"y":3})))
    report=engine.orchestrator_runner.validator.validate(candidate,WorldSnapshot.capture(engine),[(2,3)])
    assert not report.valid and "CRISIS_CELL" in [i.code for i in report.issues]


def test_bidirectional_ownership_checked_for_hold(engine):
    robot,task=assign(engine)
    task.assigned_robot=2
    report=validate(engine,plan(action(hold_steps=1)))
    assert not report.valid and "INVALID_TASK_OWNER" in [i.code for i in report.issues]


def test_immediate_path_conflict_cannot_be_approved(engine):
    assign(engine)
    other=engine.robot_manager.get_robot(2)
    other.position.x,other.position.y=2,3
    payload=plan(action("REROUTE",waypoint={"x":2,"y":3}))
    report=validate(engine,payload)
    assert not report.valid
    with pytest.raises(ExecutionError):
        execute(engine,payload,approved=True)


def test_charging_failure_retains_owned_parcel(engine):
    robot,task=assign(engine)
    robot.battery=1
    robot.carrying_item=True
    engine.agent_manager.get_agent(1)._handle_need_charge(engine.context())
    assert robot.current_task==task.id and task.assigned_robot==robot.id
    assert robot.carrying_item and robot.status==RobotStatus.NEEDS_CHARGE


def test_completed_task_unsubscribes_from_broadcasts(engine):
    robot,task=assign(engine)
    engine.task_manager.complete_task(task.id)
    engine.task_agent_manager.tick_all(engine.robot_manager,engine.pathfinder)
    bus=engine.agent_manager.message_bus
    bus.broadcast(bus.create_message("robot_1","ALL",MessageType.BLOCKED_PATH))
    assert bus.pending_count(f"task_{task.id}")==0

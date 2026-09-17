"""Wall-clock acceptance run using normal asynchronous production stepping."""
import time
from backend.agents.llm_client import FaultClient
from backend.core.settings import Settings
from backend.simulation.factory import create_simulation
from backend.evaluation.metrics import measure


def assert_invariants(engine, before):
    robots = engine.robot_manager.robots
    positions = [(r.position.x,r.position.y) for r in robots]
    assert len(set(positions)) == len(robots), "Overlapping robots"
    scheduling = engine.orchestrator_runner.scheduling_state()
    active = scheduling["active_crisis_id"]
    assert scheduling["queued_crises"] <= engine.settings.max_pending_crisis
    claims = {}
    for robot in robots:
        pos = (robot.position.x,robot.position.y)
        assert engine.pathfinder.warehouse.is_walkable(*pos), "Robot inside obstacle"
        assert sum(abs(a-b) for a,b in zip(before[robot.id],pos)) <= 1, "Nonphysical movement"
        assert 0 <= robot.battery <= 100
        assert not robot.orchestration_holds - {active}, "Orphaned or pending hold"
        if robot.current_task is not None:
            assert robot.current_task not in claims, "Duplicate task owner"
            claims[robot.current_task] = robot.id
    for task in engine.task_manager.tasks:
        if task.completed:
            assert task.delivered_by is not None
            assert task.delivery_position == (task.delivery_x,task.delivery_y)
            assert task.assigned_robot is None and task.id not in claims
        elif task.assigned_robot is not None:
            assert claims.get(task.id) == task.assigned_robot


def run_completion(seed=42, fault="LLM_OFFLINE", timeout=900, max_steps=50000, hitl_policy="approve"):
    started = time.monotonic()
    settings = Settings.from_env().model_copy(update={"orchestrator_enabled": True})
    engine = create_simulation(seed=seed, settings=settings, llm_client=FaultClient(fault) if fault else None)
    snapshots = []
    last_progress_step = 0
    last_moves = 0
    stopped_reason = None
    try:
        while not engine.is_complete() and engine.current_step < max_steps and time.monotonic()-started < timeout:
            with engine.lock:
                before = {r.id:(r.position.x,r.position.y) for r in engine.robot_manager.robots}
                engine.step()
                assert_invariants(engine,before)
                if engine.current_step % 100 == 0:
                    snapshots.append(engine.health_snapshot())
            state = engine.orchestrator_runner.get_state()
            if state["waiting_for_human"]:
                engine.orchestrator_runner.human_override(hitl_policy == "approve", state["plan_id"])
            moves = engine.measurements["successful_moves"]
            if moves != last_moves or state["active"]:
                last_progress_step, last_moves = engine.current_step, moves
            elif engine.current_step-last_progress_step >= 500:
                stopped_reason = "NO_POSITIONAL_PROGRESS_FOR_500_STEPS"
                engine.events.emit("BENCH_STALLED",tag="BENCH",reason=stopped_reason,**engine.health_snapshot())
                break
            if state["active"]:
                time.sleep(0)  # Give the daemon a scheduling opportunity; no inference barrier.
        elapsed = time.monotonic()-started
        metrics = measure(engine)
        metrics["wall_clock_seconds"] = elapsed  # Includes construction, inference, checks, operator policy.
        passed = engine.is_complete() and elapsed < min(timeout,900) and len(engine.task_manager.tasks) == 120
        return dict(scenario="normal_completion",seed=seed,mode="orchestrator",fault=fault,
                    run_id=engine.run_id,model=engine.orchestrator_runner.client.model,
                    hitl_policy=hitl_policy,steps=engine.current_step,settings=settings.model_dump(),
                    passed=passed,metrics=metrics,health=snapshots,stopped_reason=stopped_reason,
                    unfinished=[t.__dict__ for t in engine.task_manager.tasks if not t.completed],
                    robots=[r.model_dump(mode="json") for r in engine.robot_manager.robots])
    finally:
        engine.close()

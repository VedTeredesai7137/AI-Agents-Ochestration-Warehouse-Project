from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from fastapi.testclient import TestClient

from backend import api
from backend.evaluation.runner import run_one, main
from backend.evaluation.scenarios import Scenario, ScenarioSchedule
from backend.evaluation.metrics import measure
from conftest import ScriptedClient, action, plan, wait_for


@pytest.fixture
def client():
    with TestClient(api.app, raise_server_exceptions=False) as client:
        client.post("/simulation/reset",json={"seed":42,"orchestrator_enabled":False})
        yield client
        client.post("/simulation/pause")
        api.simulation.close()


@pytest.mark.parametrize("endpoint", ["/", "/dashboard", "/OperationCentre", "/OperationCenter", "/SystemOverview", "/DeveloperCentre", "/robots", "/tasks", "/warehouse/grid",
    "/agents/status", "/agents/messages", "/agents/message-history", "/tasks/agents", "/auction/logs",
    "/negotiation/logs", "/simulation/status", "/orchestrator/state", "/orchestrator/events", "/developer/logs"])
def test_endpoints_healthy(client,endpoint):
    response=client.get(endpoint)
    assert response.status_code==200


def test_operator_input_and_conflicts(client):
    assert client.post("/orchestrator/override",json={"approved":True,"plan_id":"old"}).status_code==409
    assert client.post("/orchestrator/override",json={"approved":"yes"}).status_code==422
    assert client.post("/tasks/create",json={"pickup_x":-1,"pickup_y":1,"delivery_x":1,"delivery_y":1}).status_code==400
    assert client.post("/tasks/create",json={"pickup_x":1,"pickup_y":1,"delivery_x":1,"delivery_y":1,"priority":"FAKE"}).status_code==422
    assert client.post("/simulation/crisis",json={"coords":[[12,1]]}).status_code==400
    assert client.get("/orchestrator/events?limit=-1").status_code==422


def test_reset_seed_and_grid(client):
    before=client.get("/warehouse/grid").json()
    run=client.get("/simulation/status").json()["run_id"]
    client.post("/simulation/step")
    client.post("/simulation/reset")
    after=client.get("/simulation/status").json()
    assert after["seed"]==42 and after["current_step"]==0 and after["run_id"]!=run
    assert client.get("/warehouse/grid").json()==before
    client.post("/simulation/reset",json={"seed":100})
    assert client.get("/warehouse/grid").json()!=before


def test_parallel_reads_during_steps_are_detached(client):
    def poll(_):
        return client.get("/robots").status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(poll,i) for i in range(8)]
        client.post("/simulation/step")
        assert all(f.result()==200 for f in futures)


def test_loop_lifecycle_conflicts(client):
    assert client.post("/simulation/start").status_code==200
    assert client.post("/simulation/start").status_code==409
    assert client.post("/simulation/pause").status_code==200
    assert client.get("/simulation/status").json()["running"] is False


def test_api_hitl_and_events(client):
    api.simulation.orchestrator_runner.client=ScriptedClient(plan(action(hold_steps=8)))
    api.simulation.orchestrator_runner.invoke_async([], [1])
    state=wait_for(api.simulation,lambda s:s["waiting_for_human"])
    public=client.get("/orchestrator/state").json()
    assert "confidence_score" not in public and public["validation_score"] is not None
    assert client.post("/orchestrator/override",json={"approved":True,"plan_id":state["plan_id"]}).status_code==200
    wait_for(api.simulation,lambda s:not s["active"])
    rows=client.get("/orchestrator/events?event_type=ACTION_OK&robot_id=1").json()["events"]
    assert rows and all(r["robot_id"]==1 for r in rows)


def test_api_internal_failure_does_not_expose_traceback(client,monkeypatch):
    def fail():
        raise RuntimeError("private implementation details")
    monkeypatch.setattr(api.simulation,"step",fail)
    response=client.post("/simulation/step")
    assert response.status_code==500
    assert "private implementation details" not in response.text


def test_benchmark_baseline_reproducible():
    a=run_one("normal",42,8,"baseline")
    b=run_one("normal",42,8,"baseline")
    assert a["metrics"]==b["metrics"]
    assert a["metrics"]["llm_call_count"]==0


def test_benchmark_json_csv_smoke(tmp_path):
    assert main(["--scenario","aisle_collapse","--seeds","42","--steps","21","--fault","LLM_OFFLINE",
                 "--output",str(tmp_path)])==0
    artifact=json.loads(next(tmp_path.glob("*.json")).read_text())
    assert not artifact["errors"]
    assert len(artifact["results"])==2
    assert next(tmp_path.glob("*.csv")).exists()
    assert artifact["results"][0]["requested_crisis_cells"]==artifact["results"][1]["requested_crisis_cells"]
    assert artifact["results"][1]["metrics"]["llm_failure_count"]>0


@pytest.mark.parametrize("scenario",list(Scenario))
def test_scenario_configuration(engine,scenario):
    # Scenario presets use the real 50x30 warehouse in integration; the enum
    # itself is checked here through real factory runs with a short horizon.
    result=run_one(scenario.value,100,1,"baseline",fault="LLM_OFFLINE")
    assert result["steps"]==1
    assert result["metrics"]["llm_call_count"]==0


def test_metrics_do_not_fabricate_unobserved_durations(engine):
    result=measure(engine)
    assert result["mean_task_completion_steps"] is None
    assert result["mean_deadlock_resolution_steps"] is None
    assert result["mean_crisis_recovery_steps"] is None
    assert result["p95_task_completion_steps"] is None

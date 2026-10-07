from fastapi.testclient import TestClient
from backend import api


def test_overview_assets_navigation_and_live_contract():
    with TestClient(api.app) as client:
        response = client.get("/SystemOverview")
        assert response.status_code == 200
        assert 'aria-current="page"' in response.text and 'DETERMINISTIC EVERY TICK' in response.text
        for asset in ("css/SystemOverview.css", "js/SystemOverview.js"):
            assert client.get("/static/"+asset).status_code == 200
        for page in ("/OperationCenter", "/CrisisOrchestration", "/AgentAnalytics", "/dashboard"):
            assert 'href="/SystemOverview"' in client.get(page).text
        status = client.get("/simulation/status").json()
        assert len(status["crisis_types"]) == 5
        assert status["crises_remaining"] + status["crises_submitted"] == status["crisis_budget"]
        state = client.get("/orchestrator/state").json()
        assert state["llm_provider"] in ("openrouter", "ollama", "injected")


def test_manual_api_budget_and_bad_kind():
    with TestClient(api.app) as client:
        client.post("/simulation/reset", json={"seed":42,"orchestrator_enabled":False})
        response = client.post("/simulation/crisis", json={"kind":"ROBOT_IMMOBILIZED","robot_ids":[1]})
        assert response.status_code == 200
        assert response.json()["crises_submitted"] == 1
        assert response.json()["crises_completed"] == 1
        assert client.post("/simulation/crisis", json={"kind":"NOT_A_CRISIS"}).status_code == 422
        assert client.post("/simulation/crisis", json={"kind":"ROBOT_IMMOBILIZED","robot_ids":[9999]}).status_code == 400
        api.simulation.close()

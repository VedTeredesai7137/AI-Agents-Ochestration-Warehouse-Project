"""Page route and existing HITL API integration, with an injected local-model boundary."""
from fastapi.testclient import TestClient
from conftest import ScriptedClient, action, plan, wait_for


def test_crisis_page_and_navigation():
    from backend.api import app
    client = TestClient(app)
    page = client.get('/CrisisOrchestration')
    assert page.status_code == 200
    assert 'css/CrisisOrchestration.css' in page.text
    assert 'js/CrisisOrchestration.js' in page.text
    assert 'href="/OperationCenter"' in page.text
    assert 'href="/CrisisOrchestration"' in client.get('/OperationCenter').text
    assert client.get('/static/css/CrisisOrchestration.css').status_code == 200
    assert client.get('/static/js/CrisisOrchestration.js').status_code == 200


def test_desk_override_contract_reject_regenerate_approve(monkeypatch, engine_factory):
    from backend import api
    engine = engine_factory(ScriptedClient(plan(action(hold_steps=8)), plan(action(hold_steps=9))))
    monkeypatch.setattr(api, 'simulation', engine)
    monkeypatch.setattr(api, 'simulation_lock', engine.lock)
    client = TestClient(api.app)
    engine.orchestrator_runner.invoke_async([], [1])
    first = wait_for(engine, lambda s:s['waiting_for_human'])
    assert client.get('/orchestrator/state').json()['plan_id'] == first['plan_id']
    assert client.post('/orchestrator/override', json={'approved':False, 'plan_id':first['plan_id']}).status_code == 200
    second = wait_for(engine, lambda s:s['waiting_for_human'] and s['plan_id'] != first['plan_id'])
    assert client.post('/orchestrator/override', json={'approved':True, 'plan_id':first['plan_id']}).status_code == 409
    assert client.post('/orchestrator/override', json={'approved':True, 'plan_id':second['plan_id']}).status_code == 200
    final = wait_for(engine, lambda s:not s['active'] and s['active_node']=='complete')
    assert final['executed_actions'] == 1
    events = client.get('/orchestrator/events').json()['events']
    assert {'HITL_REQUESTED','HITL_REJECTED','PLAN_REGENERATED','HITL_APPROVED','ACTION_OK','ORCH_COMPLETE'} <= {e['event_type'] for e in events}

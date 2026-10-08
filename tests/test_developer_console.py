import logging

from backend.core.events import ConsoleHistoryHandler
from backend.agents.task import TaskAgent
from backend.agents.message_bus import MessageBus
from backend.state.task_state import Task
from fastapi.testclient import TestClient
from backend import api


def _record(message, level=logging.INFO):
    return logging.LogRecord(
        name="warehouse", level=level, pathname="engine.py", lineno=12,
        msg=message, args=(), exc_info=None,
    )


def test_console_history_is_bounded_and_redacts_credentials():
    history = ConsoleHistoryHandler(limit=2)
    history.emit(_record("[BOOT] OPENROUTER_API_KEY=top-secret"))
    history.emit(_record("[SIM] step=1"))
    history.emit(_record("[ERROR] Authorization: Bearer sensitive-token"))

    result = history.query(limit=10)
    assert [entry["id"] for entry in result["entries"]] == [2, 3]
    assert result["entries"][0]["message"] == "[SIM] step=1"
    assert "top-secret" not in str(result)
    assert "sensitive-token" not in str(result)
    assert "[REDACTED]" in result["entries"][1]["message"]


def test_console_history_supports_newer_and_older_cursor_reads():
    history = ConsoleHistoryHandler(limit=4)
    for step in range(1, 5):
        history.emit(_record(f"[SIM] step={step}"))

    newer = history.query(after_id=2, limit=2)
    older = history.query(before_id=4, limit=2)
    assert [entry["id"] for entry in newer["entries"]] == [3, 4]
    assert [entry["id"] for entry in older["entries"]] == [2, 3]


def test_console_history_clear_starts_a_fresh_run():
    history = ConsoleHistoryHandler(limit=3)
    history.set_run_id("run-one")
    history.emit(_record("[SIM] old run"))
    history.clear()
    history.set_run_id("run-two")
    history.emit(_record("[BOOT] new run"))

    result = history.query(limit=10)
    assert len(result["entries"]) == 1
    assert result["entries"][0]["run_id"] == "run-two"
    assert result["entries"][0]["id"] == 1


def test_cnp_call_for_proposals_is_recorded_for_developer_centre():
    history = ConsoleHistoryHandler(limit=5)
    logger = logging.getLogger("warehouse")
    logger.addHandler(history)
    try:
        task_agent = TaskAgent(Task(7, 2, 3, 9, 10), MessageBus())
        task_agent._send_cfp()
        entries = history.query(limit=5)["entries"]
    finally:
        logger.removeHandler(history)

    assert any("[CNP][CFP] task_id=7" in entry["message"] for entry in entries)


def test_console_history_keeps_robot_moves_but_ignores_other_debug_noise():
    history = ConsoleHistoryHandler(limit=5)
    history.handle(_record("[ROBOT][MOVE] robot_id=3 position=(2,4)", logging.DEBUG))
    history.handle(_record("[SIM] internal tick detail", logging.DEBUG))

    entries = history.query(limit=5)["entries"]
    assert len(entries) == 1
    assert "[ROBOT][MOVE]" in entries[0]["message"]
    assert entries[0]["level"] == "DEBUG"


def test_developer_workspace_serves_its_assets_and_validates_log_limits():
    with TestClient(api.app, raise_server_exceptions=False) as client:
        page = client.get("/DeveloperCentre")
        assert page.status_code == 200
        assert "/static/css/DeveloperCentre.css" in page.text
        assert "/static/js/DeveloperCentre.js" in page.text
        assert "COPY ALL LOGS" in page.text
        assert client.get("/developer/logs?limit=0").status_code == 422
        assert client.get("/developer/logs?limit=100001").status_code == 422


def test_reset_starts_a_new_run_log_with_its_boot_record():
    with TestClient(api.app, raise_server_exceptions=False) as client:
        client.post("/simulation/reset", json={"seed": 42, "orchestrator_enabled": False})
        run_id = client.get("/simulation/status").json()["run_id"]
        entries = client.get("/developer/logs?limit=100000").json()["entries"]

    assert entries
    assert all(entry["run_id"] == run_id for entry in entries)
    assert any("[BOOT]" in entry["message"] for entry in entries)

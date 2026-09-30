"""Provider selection and OpenRouter transport are tested without contacting either API."""
import json

import pytest
import requests

from backend.agents.llm_client import OllamaClient, OpenRouterClient, create_llm_client
from backend.agents.plans import PlanError, generation_schema, parse_plan
from backend.core.llm_config import get_llm_model
from conftest import wait_for


def test_provider_switch_preserves_ollama_models(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-oss-120b:free")
    for provider, model, kind in (("gemma", "gemma4:12b", OllamaClient),
                                  ("mistral", "mistral:latest", OllamaClient),
                                  ("openrouter", "openai/gpt-oss-120b:free", OpenRouterClient)):
        monkeypatch.setenv("LLM_Provider", provider)
        assert get_llm_model() == model
        assert isinstance(create_llm_client(), kind)


def test_openrouter_requires_key_without_disclosing_it(monkeypatch):
    monkeypatch.setenv("LLM_Provider", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY is required"):
        create_llm_client()


def test_openrouter_request_and_plan_parsing(monkeypatch):
    monkeypatch.setenv("LLM_Provider", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("OPENROUTER_MODEL", "openai/gpt-oss-120b:free")
    def post(url, **kwargs):
        assert url == "https://openrouter.ai/api/v1/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer test-key"
        assert kwargs["timeout"] == 60.0
        body = kwargs["json"]
        assert body["model"] == "openai/gpt-oss-120b:free"
        assert body["messages"] == [{"role": "user", "content": "crisis prompt"}]
        cloud_schema = body["response_format"]["json_schema"]["schema"]
        assert cloud_schema["required"] == ["actions", "rationale"]
        assert "anyOf" in cloud_schema["$defs"]["RobotAction"]
        assert "oneOf" not in cloud_schema["$defs"]["RobotAction"]
        assert "maxItems" not in cloud_schema["properties"]["actions"]
        assert body["provider"] == {"require_parameters": True}
        assert body["stream"] is False
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"choices": [{"message": {"content":
            json.dumps({"actions": [{"robot_id": 1, "action": "HOLD", "hold_steps": 2,
                                       "reason": "clear aisle"}]})}, "finish_reason": "stop"}]}).encode()
        return response
    plan = parse_plan(OpenRouterClient(post).generate("crisis prompt", generation_schema()))
    assert plan.actions[0].hold_steps == 2


@pytest.mark.parametrize("failure,code", [
    (requests.Timeout("secret-error"), "LLM_TIMEOUT"),
    (requests.ConnectionError("secret-error"), "LLM_UNAVAILABLE"),
])
def test_openrouter_transport_failure_is_safe(monkeypatch, failure, code):
    monkeypatch.setenv("LLM_Provider", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    def post(*args, **kwargs):
        raise failure
    with pytest.raises(PlanError) as caught:
        OpenRouterClient(post).generate("prompt", generation_schema())
    assert caught.value.code == code
    assert "test-key" not in str(caught.value)
    assert "secret-error" not in str(caught.value)


def test_openrouter_bad_envelope_cannot_become_plan(monkeypatch):
    monkeypatch.setenv("LLM_Provider", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    def post(*args, **kwargs):
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"choices":[{"message":{"content":""}}]}'
        return response
    with pytest.raises(PlanError) as caught:
        OpenRouterClient(post).generate("prompt", generation_schema())
    assert caught.value.code == "LLM_SCHEMA_ERROR"


def test_openrouter_rate_limit_is_unavailable_and_redacted(monkeypatch):
    monkeypatch.setenv("LLM_Provider", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    def post(*args, **kwargs):
        response = requests.Response()
        response.status_code = 429
        response._content = b'{"error":"private provider details"}'
        return response
    with pytest.raises(PlanError) as caught:
        OpenRouterClient(post).generate("prompt", generation_schema())
    assert caught.value.code == "LLM_UNAVAILABLE"
    assert str(caught.value) == "OpenRouter HTTP 429"


def test_openrouter_timeout_releases_crisis_and_falls_back(monkeypatch, engine_factory):
    monkeypatch.setenv("LLM_Provider", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    def post(*args, **kwargs):
        raise requests.Timeout()
    engine = engine_factory(OpenRouterClient(post))
    engine.orchestrator_runner.invoke_async([], [1])
    state = wait_for(engine, lambda snapshot: not snapshot["active"] and snapshot["active_node"] == "complete")
    assert state["fallback_used"] and state["fallback_reason"] == "LLM_TIMEOUT"
    assert not engine.robot_manager.get_robot(1).orchestration_holds

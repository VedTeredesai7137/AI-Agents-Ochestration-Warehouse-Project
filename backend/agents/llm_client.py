"""Small injectable Ollama boundary; inference never receives mutable world objects."""
import requests

from backend.core.llm_config import OLLAMA_URL, get_llm_model
from backend.core.settings import LLM_TIMEOUT_SECONDS
from backend.agents.plans import PlanError


class OllamaClient:
    def __init__(self, post=None):
        self.post = post or requests.post
        self.model = get_llm_model()

    def generate(self, prompt, schema):
        try:
            response = self.post(OLLAMA_URL, json={"model": self.model, "prompt": prompt,
                                 "format": schema, "stream": False,
                                 "options": {"temperature": 0, "seed": 42}},
                                 timeout=LLM_TIMEOUT_SECONDS)
            response.raise_for_status()
            envelope = response.json()
        except requests.exceptions.Timeout as error:
            raise PlanError("LLM_TIMEOUT", "Ollama exceeded the 60 second inference timeout") from error
        except requests.exceptions.JSONDecodeError as error:
            raise PlanError("LLM_INVALID_JSON", "Ollama returned an invalid response envelope") from error
        except requests.exceptions.RequestException as error:
            raise PlanError("LLM_UNAVAILABLE", "Ollama connection or HTTP request failed") from error
        except ValueError as error:
            raise PlanError("LLM_INVALID_JSON", "Ollama returned an invalid response envelope") from error
        if not isinstance(envelope, dict) or not isinstance(envelope.get("response"), str):
            raise PlanError("LLM_SCHEMA_ERROR", "Ollama envelope is missing response text")
        return envelope["response"]


class FaultClient:
    """Explicit development dependency injection; never selected implicitly."""
    model = "fault-injection"

    def __init__(self, fault):
        self.fault = fault.upper()

    def generate(self, prompt, schema):
        if self.fault == "LLM_OFFLINE":
            raise PlanError("LLM_UNAVAILABLE", "Injected offline Ollama")
        if self.fault == "LLM_TIMEOUT":
            raise PlanError("LLM_TIMEOUT", "Injected inference timeout")
        if self.fault == "LLM_MALFORMED_RESPONSE":
            return "{malformed"
        raise ValueError("Unsupported fault injection")

"""Injectable inference boundaries; neither provider receives mutable world objects."""
import os
import re
from copy import deepcopy

import requests

from backend.core.llm_config import OLLAMA_URL, OPENROUTER_URL, get_llm_model, get_llm_provider
from backend.core.settings import LLM_TIMEOUT_SECONDS
from backend.agents.plans import PlanError


class OllamaClient:
    provider = "ollama"
    def __init__(self, post=None):
        self.post = post or requests.post
        self.model = get_llm_model()
        self.last_response = {}

    def generate(self, prompt, schema):
        self.last_response = {}
        try:
            response = self.post(OLLAMA_URL, json={"model": self.model, "prompt": prompt,
                                 "format": schema, "stream": False,
                                 "options": {"temperature": 0, "seed": 42}},
                                 timeout=LLM_TIMEOUT_SECONDS)
            self.last_response = {"http_status": response.status_code}
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


class OpenRouterClient:
    """One Chat Completions request; the graph still parses and validates the plan."""

    provider = "openrouter"

    def __init__(self, post=None):
        self.post = post or requests.post
        self.model = get_llm_model()
        self.api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
        self.last_response = {}
        if not self.api_key:
            raise ValueError("OPENROUTER_API_KEY is required when LLM_Provider=openrouter")
        if not self.model:
            raise ValueError("OPENROUTER_MODEL must be nonempty when LLM_Provider=openrouter")
        if not OPENROUTER_URL.startswith("https://"):
            raise ValueError("OPENROUTER_URL must use HTTPS")

    def generate(self, prompt, schema):
        self.last_response = {}
        try:
            response = self.post(
                OPENROUTER_URL,
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "response_format": {"type": "json_schema", "json_schema": {
                        "name": "crisis_plan", "strict": True, "schema": _openrouter_schema(schema)}},
                    "provider": {"require_parameters": True},
                    "stream": False,
                    "temperature": 0,
                },
                timeout=LLM_TIMEOUT_SECONDS,
            )
            self.last_response = {"http_status": response.status_code}
            if response.status_code >= 400:
                try:
                    error_body = response.json().get("error", {})
                except (ValueError, AttributeError):
                    error_body = {}
                message = error_body.get("message", "") if isinstance(error_body, dict) else ""
                # Never record response headers, request bodies, keys or raw metadata.
                message = re.sub(r"sk-[\w-]+", "[REDACTED]", str(message).replace(self.api_key, "[REDACTED]"))
                message = " ".join(message.split())[:300]
                failure_type = {401: "LLM_AUTH_ERROR", 402: "LLM_CREDIT_ERROR", 429: "LLM_RATE_LIMIT",
                                404: "LLM_PROVIDER_UNAVAILABLE", 400: "LLM_REQUEST_REJECTED"}.get(
                                    response.status_code, "LLM_PROVIDER_ERROR")
                self.last_response.update(failure_type=failure_type, provider_error=message)
                raise PlanError("LLM_UNAVAILABLE", f"OpenRouter HTTP {response.status_code}" +
                                (f": {message}" if message else ""), **self.last_response)
            response.raise_for_status()
            envelope = response.json()
        except requests.exceptions.Timeout as error:
            raise PlanError("LLM_TIMEOUT", "OpenRouter exceeded the 60 second inference timeout",
                            failure_type="LLM_TIMEOUT", **self.last_response) from error
        except requests.exceptions.JSONDecodeError as error:
            raise PlanError("LLM_INVALID_JSON", "OpenRouter returned an invalid response envelope") from error
        except requests.exceptions.RequestException as error:
            status = getattr(getattr(error, "response", None), "status_code", None)
            reason = f"OpenRouter HTTP {status}" if status else "OpenRouter request failed"
            raise PlanError("LLM_UNAVAILABLE", reason, transport_type=type(error).__name__,
                            **self.last_response) from error
        except PlanError:
            raise
        except ValueError as error:
            raise PlanError("LLM_INVALID_JSON", "OpenRouter returned an invalid response envelope") from error
        if not isinstance(envelope, dict) or not isinstance(envelope.get("choices"), list) or not envelope["choices"]:
            raise PlanError("LLM_SCHEMA_ERROR", "OpenRouter envelope is missing choices")
        choice = envelope["choices"][0]
        if isinstance(choice, dict):
            self.last_response["finish_reason"] = choice.get("finish_reason")
        if isinstance(envelope.get("provider"), str):
            self.last_response["inference_provider"] = envelope["provider"][:100]
        if not isinstance(choice, dict) or choice.get("finish_reason") == "length":
            raise PlanError("LLM_SCHEMA_ERROR", "OpenRouter response is incomplete")
        message = choice.get("message")
        if not isinstance(message, dict) or not isinstance(message.get("content"), str) or not message["content"].strip():
            raise PlanError("LLM_SCHEMA_ERROR", "OpenRouter envelope is missing plan text")
        return message["content"]


def _openrouter_schema(schema):
    """Use the common strict-schema subset; Pydantic retains all finer limits."""
    output = deepcopy(schema)
    output["required"] = list(output["properties"])

    def simplify(node):
        if isinstance(node, list):
            for child in node:
                simplify(child)
        elif isinstance(node, dict):
            for key in ("default", "minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems"):
                node.pop(key, None)
            if "oneOf" in node:
                node["anyOf"] = node.pop("oneOf")
            if "const" in node:
                node["enum"] = [node.pop("const")]
            for child in node.values():
                simplify(child)

    simplify(output)
    return output


def create_llm_client():
    """Select OpenRouter only when requested; retain custom Ollama model support."""
    return OpenRouterClient() if get_llm_provider() == "openrouter" else OllamaClient()


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

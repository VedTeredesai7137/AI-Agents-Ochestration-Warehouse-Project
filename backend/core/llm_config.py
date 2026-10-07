import os

from dotenv import load_dotenv


load_dotenv()

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434/api/generate",
).strip()
OPENROUTER_URL = os.getenv(
    "OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions"
).strip()

_PROVIDER_MODELS = {
    "mistral": "mistral:latest",
    "gemma": "gemma4:12b",
}


def get_llm_provider() -> str:
    """Select one inference backend; other names remain custom Ollama models."""
    provider = os.getenv("LLM_Provider", os.getenv("LLM_PROVIDER", "mistral"))
    return provider.strip().lower() or "mistral"


def get_llm_model() -> str:
    """Return the model identifier used for inference and operational logs."""
    provider = get_llm_provider()
    if provider == "openrouter":
        return os.getenv("OPENROUTER_MODEL", "").strip()
    return _PROVIDER_MODELS.get(provider, provider)

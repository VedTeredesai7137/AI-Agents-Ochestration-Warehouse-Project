import os

from dotenv import load_dotenv


load_dotenv()

OLLAMA_URL = os.getenv(
    "OLLAMA_URL",
    "http://localhost:11434/api/generate",
).strip()

_PROVIDER_MODELS = {
    "mistral": "mistral",
    "gemma": "gemma4:12b",
}


def get_llm_model() -> str:
    """Return the configured Ollama model for the selected provider."""
    provider = os.getenv("LLM_Provider", os.getenv("LLM_PROVIDER", "mistral"))
    provider = provider.strip().lower()
    return _PROVIDER_MODELS.get(provider, provider or "mistral")
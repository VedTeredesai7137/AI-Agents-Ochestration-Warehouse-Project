"""Validated process settings. Simulation code receives an explicit Settings object."""
import os

from pydantic import BaseModel, ConfigDict, Field

from backend.core import llm_config  # loads .env once, using the existing provider selection


class Settings(BaseModel):
    model_config = ConfigDict(frozen=True)
    simulation_seed: int = 42
    orchestrator_enabled: bool = True
    max_pending_crisis: int = Field(default=5, ge=1, le=50)
    deadlock_persistence_steps: int = Field(default=6, ge=1, le=100)
    max_regenerations: int = Field(default=2, ge=0, le=10)
    auto_execute_threshold: float = Field(default=0.85, ge=0, le=1)
    max_hold_steps: int = Field(default=10, ge=1, le=100)
    yield_steps: int = Field(default=3, ge=1, le=10)
    shadow_horizon: int = Field(default=5, ge=1, le=10)
    event_history_limit: int = Field(default=2000, ge=100, le=100000)
    crisis_interval: int = Field(default=200, ge=0)
    automatic_crisis_limit: int = Field(default=3, ge=0)
    # Wall-clock operator timeout prevents a forgotten HITL session blocking the queue.
    hitl_timeout_seconds: float = Field(default=300, gt=0)
    battery_margin: int = Field(default=5, ge=0, le=20)

    @classmethod
    def from_env(cls):
        names = {
            "simulation_seed": "SIMULATION_SEED",
            "orchestrator_enabled": "ORCHESTRATOR_ENABLED",
            "max_pending_crisis": "ORCHESTRATOR_MAX_PENDING_CRISIS",
            "deadlock_persistence_steps": "DEADLOCK_PERSISTENCE_STEPS",
            "max_regenerations": "ORCHESTRATOR_MAX_REGENERATIONS",
            "auto_execute_threshold": "ORCHESTRATOR_AUTO_EXECUTE_THRESHOLD",
            "max_hold_steps": "ORCHESTRATOR_MAX_HOLD_STEPS",
            "yield_steps": "ORCHESTRATOR_YIELD_STEPS",
            "shadow_horizon": "ORCHESTRATOR_SHADOW_HORIZON",
            "event_history_limit": "EVENT_HISTORY_LIMIT",
            "crisis_interval": "CRISIS_INTERVAL",
            "automatic_crisis_limit": "AUTOMATIC_CRISIS_LIMIT",
            "hitl_timeout_seconds": "ORCHESTRATOR_HITL_TIMEOUT_SECONDS",
        }
        return cls(**{field: os.environ[name] for field, name in names.items() if name in os.environ})


LLM_TIMEOUT_SECONDS = 60.0

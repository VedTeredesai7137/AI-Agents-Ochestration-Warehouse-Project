"""One explicit provider request; prints diagnostics without credentials or raw output."""
import json
import os
import time

from backend.agents.llm_client import create_llm_client
from backend.agents.plans import PlanError, generation_schema, parse_plan
from backend.core.llm_config import get_llm_model, get_llm_provider


def main():
    provider = get_llm_provider()
    result = {"provider": provider, "model": get_llm_model()}
    if provider == "openrouter" and not os.getenv("OPENROUTER_API_KEY", "").strip():
        print(json.dumps({**result, "status": "SKIPPED", "reason": "API key unavailable"}))
        return 0
    started = time.monotonic()
    client = create_llm_client()
    try:
        raw = client.generate(
            'Return JSON only. A safe warehouse test requires robot 1 to HOLD for 1 step. '
            'Return {"actions":[{"robot_id":1,"action":"HOLD","hold_steps":1,'
            '"reason":"allow aisle to clear"}],"rationale":"safe brief pause"}.', generation_schema())
        plan = parse_plan(raw)
        assert len(plan.actions) == 1 and plan.actions[0].robot_id == 1 and plan.actions[0].hold_steps == 1
        result.update(status="PARSED", actions=len(plan.actions), **client.last_response)
    except PlanError as error:
        result.update(status="FAILED", error_code=error.code, reason=str(error),
                      **client.last_response, **error.details)
    except AssertionError:
        result.update(status="FAILED", error_code="UNEXPECTED_PLAN")
    result["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
    print(json.dumps(result))
    return 0 if result["status"] == "PARSED" else 1


if __name__ == "__main__":
    raise SystemExit(main())

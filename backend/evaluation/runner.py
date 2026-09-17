"""CLI benchmark with deterministic step barriers and explicit simulated HITL decisions."""
import argparse
import csv
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time

from backend.agents.llm_client import FaultClient
from backend.core.settings import Settings
from backend.evaluation.scenarios import Scenario, ScenarioSchedule
from backend.evaluation.metrics import measure
from backend.simulation.factory import create_simulation


def settle(engine, policy="approve", timeout=240):
    """Evaluation barrier: let background graph settle before advancing another tick.

    Production never waits like this. It removes worker scheduling from simulated
    recovery-step measurements. Inference latency is measured separately.
    """
    deadline = time.monotonic() + timeout
    while engine.orchestrator_runner.is_active:
        state = engine.orchestrator_runner.get_state()
        if state["waiting_for_human"]:
            engine.orchestrator_runner.human_override(policy == "approve", state["plan_id"])
        if time.monotonic() >= deadline:
            raise TimeoutError("Orchestrator did not settle before evaluation deadline")
        time.sleep(0.005)


def run_one(scenario, seed, steps, mode, fault=None, hitl_policy="approve"):
    if steps < 1 or mode not in ("baseline", "orchestrator"):
        raise ValueError("steps must be positive and mode must be baseline or orchestrator")
    scenario = Scenario(scenario.lower()).value
    fault = fault or (scenario.upper() if scenario.startswith("llm_") else None)
    client = FaultClient(fault) if fault else None
    settings = Settings.from_env().model_copy(update={"orchestrator_enabled": mode == "orchestrator", "crisis_interval": 0})
    engine = create_simulation(seed=seed, settings=settings, llm_client=client,
                               task_count=240 if scenario == "high_workload" else 120)
    schedule = ScenarioSchedule(engine, scenario)
    print(f"[BENCH] scenario={scenario} seed={seed} mode={mode} fault={fault or 'none'}")
    try:
        for _ in range(steps):
            with engine.lock:
                schedule.before_step(engine)
            settle(engine, hitl_policy)
            engine.step()
            settle(engine, hitl_policy)
        metrics = measure(engine)
        print(f"[BENCH] completed={metrics['task_completion_count']}/{metrics['task_total']} "
              f"deadlocks={metrics['deadlock_count']} crisis_recovery={metrics['mean_crisis_recovery_steps']}")
        return {"scenario": scenario, "seed": seed, "mode": mode, "steps": steps, "fault": fault,
                "hitl_policy": hitl_policy, "run_id": engine.run_id, "settings": settings.model_dump(),
                "requested_crisis_cells": schedule.requested_cells, "metrics": metrics}
    except Exception:
        logging.getLogger("warehouse").exception("[BENCH][ERROR] scenario=%s seed=%s mode=%s", scenario, seed, mode)
        raise
    finally:
        engine.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--completion", action="store_true", help="Run normal 40/120 wall-clock acceptance; stops on completion")
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--scenario", type=str.lower, choices=[s.value for s in Scenario], default="aisle_collapse")
    parser.add_argument("--seeds", type=int, nargs="+", default=[42, 100, 123])
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--modes", nargs="+", choices=["baseline", "orchestrator"], default=["baseline", "orchestrator"])
    parser.add_argument("--fault", choices=["LLM_OFFLINE", "LLM_TIMEOUT", "LLM_MALFORMED_RESPONSE"])
    parser.add_argument("--hitl-policy", choices=["approve", "reject"], default="approve")
    parser.add_argument("--output", type=Path, default=Path("evaluation_results"))
    args = parser.parse_args(argv)
    if args.steps < 1:
        parser.error("--steps must be positive")
    results, errors = [], []
    if args.completion:
        from backend.evaluation.completion import run_completion
        for seed in args.seeds:
            try:
                result = run_completion(seed, args.fault, args.timeout, hitl_policy=args.hitl_policy)
                results.append(result)
                print(f"[BENCH] seed={seed} completed={result['metrics']['task_completion_count']}/120 seconds={result['metrics']['wall_clock_seconds']:.3f} PASS={result['passed']}")
                if not result["passed"]:
                    errors.append(dict(seed=seed,error="Completion acceptance failed"))
            except Exception as error:
                logging.getLogger("warehouse").exception("[BENCH][ERROR] normal_completion seed=%s",seed)
                errors.append(dict(seed=seed,error=str(error)))
    for seed in ([] if args.completion else args.seeds):
        for mode in args.modes:
            try:
                results.append(run_one(args.scenario, seed, args.steps, mode, args.fault, args.hitl_policy))
            except Exception as error:
                errors.append(dict(scenario=args.scenario, seed=seed, mode=mode, error=str(error)))
    args.output.mkdir(parents=True, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    json_path = args.output / f"benchmark_{name}.json"
    json_path.write_text(json.dumps({"results": results, "errors": errors}, indent=2), encoding="utf-8")
    if results:
        with (args.output / f"benchmark_{name}.csv").open("w", newline="", encoding="utf-8") as stream:
            rows = [{**{k:r[k] for k in ("scenario","seed","mode","steps","fault","hitl_policy")}, **r["metrics"]} for r in results]
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    print(f"[BENCH] results={json_path} failures={len(errors)}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

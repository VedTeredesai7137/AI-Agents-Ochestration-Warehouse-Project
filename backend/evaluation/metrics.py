"""Metrics computed from real counters and simulation-step timestamps."""
from statistics import mean
import math


def measure(engine):
    tasks = engine.task_manager.tasks
    completed = [t for t in tasks if t.completed]
    durations = sorted(t.completed_step - t.created_step for t in completed if t.completed_step is not None)
    counts, latency_sum = engine.events.totals()
    m = engine.measurements
    calls = counts.get("LLM_REQUEST", 0)
    # Only graph completions with fallback count as LLM-orchestrator fallback;
    # ordinary deterministic deadlock handling is not an LLM failure.
    fallbacks = m.get("orchestrator_fallback_count", 0)
    finished = counts.get("ORCH_COMPLETE", 0)
    return {
        "wall_clock_seconds": engine.completion_seconds,
        "simulation_steps": engine.current_step,
        "successful_moves": m.get("successful_moves",0),
        "charging_events": m.get("charging_events",0),
        "average_charging_robots": m.get("charging_robot_ticks",0)/engine.current_step if engine.current_step else 0,
        "max_charging_robots": m.get("max_charging_robots",0),
        "deadlock_escalations": counts.get("DEADLOCK_PERSISTENT",0),
        "llm_timeout_count": counts.get("LLM_TIMEOUT",0),
        "automatic_crises": m.get("automatic_crises",0),
        "task_total": len(tasks), "task_completion_count": len(completed),
        "task_completion_rate": len(completed)/len(tasks) if tasks else 0,
        "mean_task_completion_steps": mean(durations) if durations else None,
        "p95_task_completion_steps": durations[math.ceil(0.95*len(durations))-1] if len(durations) >= 20 else None,
        "throughput_per_100_steps": len(completed)*100/engine.current_step if engine.current_step else 0,
        "blocked_attempts": engine.collision_manager.blocked_attempts,
        "deadlock_count": m.get("deadlock_count", 0),
        "deadlocks_resolved": m.get("deadlocks_resolved", 0),
        "deadlocks_unresolved": len(engine._deadlocks),
        "mean_deadlock_resolution_steps": m["deadlock_resolution_steps"]/m["deadlocks_resolved"] if m["deadlocks_resolved"] else None,
        "tasks_reauctioned": sum(t.reauction_count for t in tasks),
        "crisis_count": m.get("crisis_count", 0),
        "crises_recovered": m.get("crises_recovered", 0), "crises_unresolved": len(engine._crises),
        "mean_crisis_recovery_steps": m["crisis_recovery_steps"]/m["crises_recovered"] if m["crises_recovered"] else None,
        "llm_call_count": calls, "llm_success_count": counts.get("LLM_SUCCESS", 0),
        "llm_failure_count": counts.get("LLM_FAILURE", 0), "llm_fallback_count": fallbacks,
        "llm_fallback_rate": fallbacks/finished if finished else 0,
        "mean_llm_latency_ms": latency_sum/calls if calls else None,
        "invalid_plan_count": counts.get("INVALID_PLAN", 0),
        "plan_regeneration_count": counts.get("PLAN_REGENERATED", 0),
        "hitl_requested": counts.get("HITL_REQUESTED", 0), "hitl_approved": counts.get("HITL_APPROVED", 0),
        "hitl_rejected": counts.get("HITL_REJECTED", 0),
        "scenario_faults_skipped": counts.get("SCENARIO_FAULT_SKIPPED", 0),
        "orchestrations_completed": finished,
    }

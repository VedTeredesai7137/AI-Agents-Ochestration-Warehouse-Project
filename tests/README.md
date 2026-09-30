# Tests

Run from the repository root:

```powershell
python311\python.exe -m pytest -q
node --test tests/operation_centre.test.cjs
python311\python.exe -m compileall -q backend tests
node --check frontend/js/OperationCentre.js
node --check frontend/js/dashboard.js
```

Install test dependencies with `python311\python.exe -m pip install -r requirements-dev.txt`.
Pytest adds the repository root to the bundled interpreter's import path.

- `test_safety.py`: A* and obstacle regressions, CNP ownership/re-auction,
  batteries, strict plan parsing, deterministic validation, and action effects.
- `test_orchestrator.py`: real LangGraph checkpoints with injected model clients;
  HITL, rejection/regeneration, retry limits, fallback, queueing, and reset races.
- `test_api_evaluation.py`: API validation and controls, seeded scenarios,
  measured metrics, and benchmark artifacts.
- `test_repairs.py`: retained charging, message history, encoding, and graph
  approval/reset regressions, migrated to the structured plan schema.
- `operation_centre.test.cjs`: a lightweight DOM fixture checks structured HUD
  rendering, escaped model text, validation/fallback/queue fields, and absence
  of the approval overlay for an invalid plan.

Automated tests do not require Ollama. Human decisions must identify the current
`plan_id`; stale submissions are rejected. Reset invalidates the old run's workers.

The DOM fixture is not a browser. Visual layout, scrolling, and a live Ollama
model's output quality require separate manual verification. See the root README
for evaluation commands, metric definitions, and the validation limits.

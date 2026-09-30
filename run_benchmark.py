"""Entry point for the bundled Windows Python, whose isolated path omits cwd."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backend.evaluation.runner import main

if __name__ == "__main__":
    raise SystemExit(main())

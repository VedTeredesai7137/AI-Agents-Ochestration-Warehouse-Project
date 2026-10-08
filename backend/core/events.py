"""Bounded structured history and cumulative counters (independent of ring eviction)."""
from collections import Counter, deque
from copy import deepcopy
import logging
import re
import threading
import time


logger = logging.getLogger("warehouse")


class ConsoleHistoryHandler(logging.Handler):
    """Bounded, redacted copy of application log records for DeveloperCentre."""

    def __init__(self, limit=100000):
        super().__init__(level=logging.DEBUG)
        self._entries = deque(maxlen=limit)
        self._next_id = 0
        self._run_id = None
        self._lock = threading.RLock()

    def filter(self, record):
        # Keep successful per-cell movement visible in DeveloperCentre without
        # flooding the normal terminal output or capturing unrelated DEBUG noise.
        return record.levelno >= logging.INFO or (
            record.levelno == logging.DEBUG
            and record.name == "warehouse"
            and record.getMessage().startswith("[ROBOT][MOVE]")
        )

    def clear(self):
        """Start a fresh console history for a newly reset simulation run."""
        with self._lock:
            self._entries.clear()
            self._next_id = 0

    def set_run_id(self, run_id):
        with self._lock:
            self._run_id = run_id

    @staticmethod
    def _safe_message(record):
        message = record.getMessage()
        if record.exc_info:
            message = f"{message}\n{logging.Formatter().formatException(record.exc_info)}"
        message = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", message)
        message = re.sub(
            r"(?i)(\b(?:OPENROUTER_)?API[_-]?KEY\b|\bkey\b|\bAuthorization\b|\b(?:access[_-]?)?token\b|\bsecret\b|\bpassword\b)(\s*[=:]\s*)([^\s,;]+)",
            r"\1\2[REDACTED]",
            message,
        )
        return message

    def emit(self, record):
        try:
            entry = {
                "timestamp": record.created,
                "level": record.levelname,
                "logger": record.name,
                "source": f"{record.filename}:{record.lineno}",
                "message": self._safe_message(record),
            }
            with self._lock:
                self._next_id += 1
                entry["run_id"] = self._run_id
                entry["id"] = self._next_id
                self._entries.append(entry)
        except Exception:
            self.handleError(record)

    def query(self, *, after_id=None, before_id=None, limit=500):
        with self._lock:
            entries = list(self._entries)
        oldest_id = entries[0]["id"] if entries else None
        latest_id = entries[-1]["id"] if entries else 0
        truncated = bool(oldest_id is not None and oldest_id > 1)
        if before_id is not None:
            candidates = [entry for entry in entries if entry["id"] < before_id]
            page = candidates[-limit:]
            has_older = bool(page and candidates[0]["id"] < page[0]["id"])
        elif after_id is not None and not truncated:
            page = [entry for entry in entries if entry["id"] > after_id][:limit]
            has_older = False
        else:
            page = entries[-limit:]
            has_older = bool(page and entries[0]["id"] < page[0]["id"])
        return {
            "entries": deepcopy(page),
            "oldest_id": oldest_id,
            "latest_id": latest_id,
            "has_older": has_older,
            "truncated": truncated,
        }


console_history = ConsoleHistoryHandler()


def configure_logging(run_id=None):
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(logging.INFO)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    else:
        for handler in logger.handlers:
            if handler is not console_history:
                handler.setLevel(logging.INFO)
    if console_history not in logger.handlers:
        logger.addHandler(console_history)
    if run_id is not None:
        console_history.set_run_id(run_id)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False


class EventRecorder:
    def __init__(self, run_id, limit=2000):
        self.run_id = run_id
        self._events = deque(maxlen=limit)
        self._counts = Counter()
        self._latency_sum = 0.0
        self._lock = threading.RLock()
        self._next_id = 0

    def emit(self, event_type, *, tag="ORCH", step=None, **context):
        with self._lock:
            self._next_id += 1
            event = dict(run_id=self.run_id, event_id=f"{self.run_id}:event_{self._next_id:06d}",
                         timestamp=time.time(), step=step, event_type=event_type, **context)
            self._events.append(deepcopy(event))
            self._counts[event_type] += 1
            if event_type == "LLM_FAILURE":
                self._counts[context.get("error_code", "LLM_UNKNOWN_ERROR")] += 1
            if event_type in ("LLM_SUCCESS", "LLM_FAILURE"):
                self._latency_sum += context.get("latency_ms", 0)
        fields = " ".join(f"{key}={str(value).encode('ascii', errors='backslashreplace').decode('ascii')}" for key, value in event.items()
                          if value is not None and key not in ("timestamp", "event_type", "event_id"))
        level = logging.ERROR if event_type.endswith("FAILED") or event_type == "LLM_FAILURE" else logging.INFO
        logger.log(level, "[%s][%s] %s", tag, event_type, fields)
        return event

    def query(self, limit=100, **filters):
        with self._lock:
            rows = [event for event in self._events
                    if all(value is None or event.get(key) == value for key, value in filters.items())]
            return deepcopy(rows[-limit:])

    def totals(self):
        with self._lock:
            return dict(self._counts), self._latency_sum

"""Bounded structured history and cumulative counters (independent of ring eviction)."""
from collections import Counter, deque
from copy import deepcopy
import logging
import threading
import time


logger = logging.getLogger("warehouse")


def configure_logging():
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
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

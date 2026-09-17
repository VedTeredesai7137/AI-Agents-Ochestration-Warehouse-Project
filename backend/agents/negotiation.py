"""Compatibility log facade. Exceptional LLM decisions use the structured graph.

Routine auction explanations and greetings use deterministic templates, leaving
local inference capacity for crisis/deadlock actions that affect the simulation.
"""
from collections import deque
from copy import deepcopy
import threading
import time


class NegotiationService:
    def __init__(self):
        self.negotiation_logs = deque(maxlen=300)
        self.social_logs = deque(maxlen=100)
        self.lock = threading.RLock()

    def record(self, event, reasoning, decision, **context):
        with self.lock:
            self.negotiation_logs.append(dict(event=event, timestamp=time.time(), reasoning=reasoning,
                                              decision=decision, **context))

    def recent(self, limit=5):
        with self.lock:
            return deepcopy(list(self.negotiation_logs)[-limit:])

    def explain_auction_winner(self, task_id, winner_id, bids):
        self.record(f"Auction Task {task_id}", f"Lowest eligible CNP bid: {bids}", f"R{winner_id} won")

    def generate_greeting(self, robot_id, target_id):
        self.record(f"Greeting: R{robot_id} to R{target_id}", "Passing nearby", "Beep boop, hello!")

    def generate_initial_greeting(self, robot_id):
        self.record(f"Initial Greeting R{robot_id}", "Simulation started", "Swarm activated")

    def generate_crisis_report(self, start_x, start_y, end_x, end_y):
        self.record("Crisis: Aisle Collapse", f"Blocked cells ({start_x},{start_y}) to ({end_x},{end_y})", "Obstacle added")

    def resolve_deadlock(self, robot1_id, robot2_id, cell_x, cell_y, callback=None):
        # Legacy callers get an explicit deterministic decision. The engine routes
        # exceptional deadlocks to OrchestratorRunner for validated LLM execution.
        winner = min(robot1_id, robot2_id)
        reason = "Deterministic robot-ID priority"
        self.record("Deadlock", reason, f"R{winner} passes")
        if callback:
            callback(winner, reason)


negotiation_service = NegotiationService()

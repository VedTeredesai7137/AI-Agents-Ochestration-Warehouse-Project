"""
MessageBus — In-memory publish/subscribe message system for agent communication.

Provides:
  - Direct messaging between agents (publish to specific recipient)
  - Broadcast messaging to all subscribers
  - Per-agent inbox with non-blocking retrieval
  - Messages persist until consumed
"""

import time
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Message Types
# ---------------------------------------------------------------------------

class MessageType(str, Enum):
    """Types of messages agents can exchange."""

    TASK_AVAILABLE = "TASK_AVAILABLE"
    CFP = "CFP"
    EMERGENCY_CFP = "EMERGENCY_CFP"
    PROPOSAL = "PROPOSAL"
    TASK_AWARDED = "TASK_AWARDED"
    LOW_BATTERY = "LOW_BATTERY"
    BLOCKED_PATH = "BLOCKED_PATH"
    HELP_REQUEST = "HELP_REQUEST"
    ROBOT_STATUS = "ROBOT_STATUS"
    REROUTE = "REROUTE"
    TASK_RELEASED = "TASK_RELEASED"
    CRISIS_ALERT = "CRISIS_ALERT"


# ---------------------------------------------------------------------------
# Message
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """A lightweight message exchanged between agents."""

    id: int
    sender: str
    recipient: str          # agent_id or "ALL" for broadcast
    message_type: MessageType
    payload: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# MessageBus
# ---------------------------------------------------------------------------

class MessageBus:
    """
    In-memory message bus supporting direct and broadcast messaging.

    Each agent subscribes with a unique agent_id.
    Messages are stored in per-agent inboxes until consumed via get_messages().
    """

    def __init__(self):
        self._inboxes: dict[str, list[Message]] = {}
        self._next_id: int = 1
        self.session_id = uuid.uuid4().hex
        self._history = deque(maxlen=1000)
        self._history_lock = threading.Lock()

    def subscribe(self, agent_id: str):
        """Register an agent's inbox. Idempotent."""
        if agent_id not in self._inboxes:
            self._inboxes[agent_id] = []

    def publish(self, message: Message):
        """
        Deliver a message to a specific recipient's inbox.
        If the recipient has not subscribed, the message is silently dropped.
        """
        self._record(message)
        if message.recipient in self._inboxes:
            self._inboxes[message.recipient].append(message)

    def broadcast(self, message: Message):
        """
        Deliver a copy of the message to every subscribed inbox
        except the sender's own.
        """
        self._record(message)
        for agent_id, inbox in self._inboxes.items():
            if agent_id != message.sender:
                inbox.append(message)

    def get_messages(self, agent_id: str) -> list[Message]:
        """
        Return and clear all pending messages for the given agent.
        Non-blocking — returns an empty list if no messages.
        """
        if agent_id not in self._inboxes:
            return []
        messages = self._inboxes[agent_id]
        self._inboxes[agent_id] = []
        return messages

    def peek_messages(self, agent_id: str) -> list[Message]:
        """
        Return pending messages without consuming them.
        """
        return list(self._inboxes.get(agent_id, []))

    def create_message(
        self,
        sender: str,
        recipient: str,
        message_type: MessageType,
        payload: dict = None
    ) -> Message:
        """
        Factory method to create a Message with auto-incremented ID.
        """
        msg = Message(
            id=self._next_id,
            sender=sender,
            recipient=recipient,
            message_type=message_type,
            payload=payload or {},
        )
        self._next_id += 1
        return msg

    def pending_count(self, agent_id: str) -> int:
        """Return number of pending messages for the given agent."""
        return len(self._inboxes.get(agent_id, []))

    def __repr__(self):
        total = sum(len(v) for v in self._inboxes.values())
        return f"MessageBus(subscribers={len(self._inboxes)}, pending={total})"

    def _record(self, message):
        with self._history_lock:
            self._history.append({"id": message.id, "sender": message.sender,
                                  "recipient": message.recipient, "type": message.message_type.value,
                                  "payload": dict(message.payload), "timestamp": message.timestamp})

    def history(self):
        with self._history_lock:
            return {"session_id": self.session_id, "messages": list(self._history)}

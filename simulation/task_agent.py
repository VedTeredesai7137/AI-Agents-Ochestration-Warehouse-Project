"""
TaskAgent — Autonomous agent representing a single Task.

Implements the Contract Net Protocol (CNP) lifecycle:
  1. Issue CFP (Call For Proposals) via MessageBus broadcast.
  2. Collect PROPOSAL messages from RobotAgents for one tick.
  3. Evaluate proposals and select winner (lowest cost).
  4. Send TASK_AWARDED message to the winning RobotAgent.
  5. Mark the task as assigned.

The TaskAgent does NOT directly modify Robot state — it communicates
through the MessageBus and lets the winning RobotAgent accept the contract.
"""

from simulation.message_bus import MessageType


class TaskAgentStatus:
    """Lifecycle states of a TaskAgent."""
    WAITING = "WAITING"           # task exists, not yet sent CFP
    CFP_SENT = "CFP_SENT"         # CFP broadcast, collecting proposals
    AWARDED = "AWARDED"           # contract awarded to a robot
    COMPLETED = "COMPLETED"       # task has been delivered


class TaskAgent:
    """
    Autonomous agent managing the Contract Net Protocol for one task.

    Attributes
    ----------
    task : Task
        Reference to the underlying Task dataclass.
    status : str
        Current lifecycle state (see TaskAgentStatus).
    received_proposals : list[dict]
        Proposals collected during the current CFP round.
    winner : int | None
        Robot ID of the contract winner, or None.
    agent_id : str
        Unique identifier for MessageBus subscription (e.g., "task_3").
    message_bus : MessageBus
        Reference to the shared message bus.
    """

    def __init__(self, task, message_bus):
        self.task = task
        self.message_bus = message_bus
        self.status = TaskAgentStatus.WAITING
        self.received_proposals = []
        self.winner = None
        self.agent_id = f"task_{task.id}"

        # Subscribe to the message bus
        self.message_bus.subscribe(self.agent_id)

    def tick(self, task_manager, robot_manager, pathfinder):
        """
        Run one lifecycle step based on current status.

        Parameters
        ----------
        task_manager : TaskManager
            For assigning/completing tasks.
        robot_manager : RobotManager
            For looking up robot references when awarding.
        pathfinder : AStarPathfinder
            For computing paths when awarding contracts.
        """
        # Sync with underlying task state
        if self.task.completed:
            self.status = TaskAgentStatus.COMPLETED
            return

        if self.status == TaskAgentStatus.COMPLETED:
            return

        if self.status == TaskAgentStatus.AWARDED:
            # Task is assigned — nothing to do until it completes or is released
            if self.task.assigned_robot is None:
                # Task was released (e.g., robot went to charge)
                self.status = TaskAgentStatus.WAITING
                self.winner = None
                self.received_proposals = []
            return

        if self.status == TaskAgentStatus.WAITING:
            self._send_cfp()
            return None

        if self.status == TaskAgentStatus.CFP_SENT:
            return self._collect_and_evaluate(task_manager, robot_manager, pathfinder)
        
        return None

    def _send_cfp(self):
        """Broadcast a Call For Proposals to all robot agents."""
        msg = self.message_bus.create_message(
            sender=self.agent_id,
            recipient="ALL",
            message_type=MessageType.CFP,
            payload={
                "task_id": self.task.id,
                "pickup_x": self.task.pickup_x,
                "pickup_y": self.task.pickup_y,
                "delivery_x": self.task.delivery_x,
                "delivery_y": self.task.delivery_y,
            }
        )
        self.message_bus.broadcast(msg)
        self.status = TaskAgentStatus.CFP_SENT
        self.received_proposals = []

    def _collect_and_evaluate(self, task_manager, robot_manager, pathfinder):
        """
        Read proposals from inbox, pick the winner, award the contract.
        """
        # Collect proposals from inbox
        messages = self.message_bus.get_messages(self.agent_id)
        for msg in messages:
            if msg.message_type == MessageType.PROPOSAL:
                if msg.payload.get("task_id") == self.task.id:
                    self.received_proposals.append(msg.payload)

        if not self.received_proposals:
            # No proposals received — go back to WAITING to re-issue CFP next tick
            self.status = TaskAgentStatus.WAITING
            return None

        # Evaluate: lowest estimated_cost wins
        self.received_proposals.sort(
            key=lambda p: (p["estimated_cost"], p["robot_id"])
        )
        best = self.received_proposals[0]
        winner_id = best["robot_id"]

        # Verify the robot is still eligible
        robot = robot_manager.get_robot(winner_id)
        if robot is None or robot.current_task is not None or robot.battery < 30:
            # Winner no longer eligible — retry next tick
            self.received_proposals = []
            self.status = TaskAgentStatus.WAITING
            return None

        # Compute paths
        pickup_path = pathfinder.find_path(
            (robot.position.x, robot.position.y),
            (self.task.pickup_x, self.task.pickup_y)
        )
        delivery_path = pathfinder.find_path(
            (self.task.pickup_x, self.task.pickup_y),
            (self.task.delivery_x, self.task.delivery_y)
        )

        if not pickup_path or not delivery_path:
            self.received_proposals = []
            self.status = TaskAgentStatus.WAITING
            return None

        # Award the contract
        task_manager.assign_task(self.task.id, winner_id)
        robot_manager.assign_task(winner_id, self.task.id, pickup_path)
        robot.delivery_path = delivery_path

        self.winner = winner_id
        self.status = TaskAgentStatus.AWARDED

        # Send TASK_AWARDED message to the winning robot
        award_msg = self.message_bus.create_message(
            sender=self.agent_id,
            recipient=f"robot_{winner_id}",
            message_type=MessageType.TASK_AWARDED,
            payload={
                "task_id": self.task.id,
                "robot_id": winner_id,
            }
        )
        self.message_bus.publish(award_msg)

        print(f"Task {self.task.id} awarded to Robot {winner_id} via CNP")
        
        log = {
            "task_id": self.task.id,
            "bids": [{"robot_id": p["robot_id"], "bid": p["estimated_cost"]} for p in self.received_proposals],
            "winner": winner_id
        }

        try:
            from simulation.negotiation_service import negotiation_service
            bids_str = ", ".join([f"R{p['robot_id']}: {p['estimated_cost']:.1f}" for p in self.received_proposals])
            negotiation_service.explain_auction_winner(self.task.id, winner_id, bids_str)
        except Exception:
            pass

        return log

    @property
    def proposal_count(self):
        return len(self.received_proposals)

    def __repr__(self):
        return (
            f"TaskAgent(task_id={self.task.id}, "
            f"status={self.status}, "
            f"winner={self.winner})"
        )

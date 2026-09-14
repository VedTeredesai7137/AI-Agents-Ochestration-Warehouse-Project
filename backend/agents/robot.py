"""
RobotAgent — Autonomous agent wrapper for a Robot.

Each RobotAgent is responsible for:
  - Perception:  observing the warehouse environment and own state.
  - Decision:    choosing what to do next (charge, move, pick, deliver).
  - Action:      executing the chosen action on the underlying Robot.
  - Memory:      maintaining a local history of events and beliefs.
  - Communication: sending/receiving messages via the MessageBus.
  - Contract Net: responding to CFP messages with PROPOSAL bids.

This agent participates in the Contract Net Protocol by:
  1. Receiving CFP broadcasts from TaskAgents.
  2. Evaluating whether to bid (based on battery, current task, distance).
  3. Submitting PROPOSAL messages back to the issuing TaskAgent.
  4. Receiving TASK_AWARDED messages and updating goal/memory.
"""

from backend.core.models import RobotStatus
from backend.agents.message_bus import MessageType


# ---------------------------------------------------------------------------
# Agent goal enum
# ---------------------------------------------------------------------------

class AgentGoal:
    """High-level goals an agent can pursue."""

    IDLE = "IDLE"
    PICKUP = "PICKUP"
    DELIVER = "DELIVER"
    CHARGE = "CHARGE"


# ---------------------------------------------------------------------------
# RobotAgent
# ---------------------------------------------------------------------------

class RobotAgent:
    """
    Autonomous agent that controls a single Robot and communicates
    via the MessageBus using the Contract Net Protocol.

    Attributes
    ----------
    robot : Robot
        Reference to the underlying Robot model (owned by RobotManager).
    goal : str
        Current high-level goal (see AgentGoal).
    beliefs : dict
        Agent's local beliefs about the world.
    memory : list[dict]
        Chronological log of notable events.
    current_plan : list[str]
        Ordered list of planned micro-actions for the current goal.
    message_bus : MessageBus | None
        Reference to the shared message bus.
    agent_id : str
        Unique identifier for MessageBus subscription (e.g., "robot_1").
    """

    def __init__(self, robot, message_bus=None):
        self.robot = robot
        self.message_bus = message_bus
        self.agent_id = f"robot_{robot.id}"

        self.messages = []

        self.beliefs = {
            "battery_low": False,
            "has_task": False,
            "carrying_item": False,
            "at_destination": False,
            "at_charger": False,
            "battery_full": False,
            "path_blocked": False,
            "nearby_low_battery": [],
            "nearby_blocked": [],
        }
        self.goal = AgentGoal.IDLE
        self.has_greeted = False
        self.blocked_counter = 0
        self.memory = []
        self.current_plan = []

        # Subscribe to message bus
        if self.message_bus is not None:
            self.message_bus.subscribe(self.agent_id)

    # ------------------------------------------------------------------
    #  MESSAGING — send, broadcast, process incoming
    # ------------------------------------------------------------------

    def send_message(self, recipient, message_type, payload=None):
        """Send a direct message to a specific agent."""
        if self.message_bus is None:
            return
        msg = self.message_bus.create_message(
            sender=self.agent_id,
            recipient=recipient,
            message_type=message_type,
            payload=payload or {},
        )
        self.message_bus.publish(msg)

    def broadcast(self, message_type, payload=None):
        """Broadcast a message to all other agents."""
        if self.message_bus is None:
            return
        msg = self.message_bus.create_message(
            sender=self.agent_id,
            recipient="ALL",
            message_type=message_type,
            payload=payload or {},
        )
        self.message_bus.broadcast(msg)

    def process_messages(self):
        """
        Read and process all pending messages from the inbox.
        Handles CFP, TASK_AWARDED, LOW_BATTERY, BLOCKED_PATH, TASK_RELEASED.
        """
        if self.message_bus is None:
            return

        messages = self.message_bus.get_messages(self.agent_id)

        for msg in messages:
            if msg.message_type in (MessageType.CFP, MessageType.EMERGENCY_CFP):
                self._handle_cfp(msg)
            elif msg.message_type == MessageType.TASK_AWARDED:
                self._handle_task_awarded(msg)
            elif msg.message_type == MessageType.LOW_BATTERY:
                self._handle_low_battery_notification(msg)
            elif msg.message_type == MessageType.BLOCKED_PATH:
                self._handle_blocked_notification(msg)
            elif msg.message_type == MessageType.TASK_RELEASED:
                self._handle_task_released(msg)

    def _handle_cfp(self, msg):
        """
        Evaluate a Call For Proposals and submit a PROPOSAL if eligible.
        Eligibility: no current task, battery >= 30, status is IDLE.
        """
        robot = self.robot
        is_emergency = msg.message_type == MessageType.EMERGENCY_CFP

        # Eligibility check
        if not is_emergency and robot.current_task is not None:
            return
        if robot.battery < 30:
            return
        if robot.status == RobotStatus.CHARGING:
            return

        task_id = msg.payload.get("task_id")
        pickup_x = msg.payload.get("pickup_x")
        pickup_y = msg.payload.get("pickup_y")

        # Calculate bid: Manhattan distance + battery penalty
        distance = (
            abs(robot.position.x - pickup_x)
            + abs(robot.position.y - pickup_y)
        )
        battery_penalty = (100 - robot.battery) * 0.1
        estimated_cost = distance + battery_penalty

        # Submit proposal
        self.send_message(
            recipient=msg.sender,
            message_type=MessageType.PROPOSAL,
            payload={
                "task_id": task_id,
                "robot_id": robot.id,
                "estimated_cost": estimated_cost,
                "battery": robot.battery,
                "distance": distance,
            }
        )

        self._remember("sent_proposal", {
            "task_id": task_id,
            "estimated_cost": estimated_cost,
        })

    def _handle_task_awarded(self, msg):
        """Process a TASK_AWARDED message — update memory."""
        dropped = msg.payload.get("dropped_task_id")
        if dropped is not None:
            self.broadcast(MessageType.TASK_RELEASED, {"robot_id": self.robot.id, "task_id": dropped})
        self._remember("task_awarded", {
            "task_id": msg.payload.get("task_id"),
        })

    def _handle_low_battery_notification(self, msg):
        """Another robot reported low battery — update beliefs."""
        sender_id = msg.payload.get("robot_id")
        if sender_id not in self.beliefs["nearby_low_battery"]:
            self.beliefs["nearby_low_battery"].append(sender_id)
        self._remember("peer_low_battery", {
            "robot_id": sender_id,
        })

    def _handle_blocked_notification(self, msg):
        """Another robot reported a blocked path — update beliefs."""
        sender_id = msg.payload.get("robot_id")
        cell = msg.payload.get("cell")
        if sender_id not in self.beliefs["nearby_blocked"]:
            self.beliefs["nearby_blocked"].append(sender_id)
        self._remember("peer_blocked", {
            "robot_id": sender_id,
            "cell": cell,
        })

    def _handle_task_released(self, msg):
        """Another robot released a task — note in memory."""
        self._remember("peer_task_released", {
            "robot_id": msg.payload.get("robot_id"),
            "task_id": msg.payload.get("task_id"),
        })

    # ------------------------------------------------------------------
    #  PERCEPTION — observe environment + own state
    # ------------------------------------------------------------------

    def perceive(self, collision_manager=None, negotiation_service=None, ctx=None):
        """Update beliefs from the robot's current state."""
        robot = self.robot
        if ctx is None: ctx = {}

        robot.battery = min(100, max(0, robot.battery))
        charge_path = []
        if ctx.get("charging_manager") and ctx.get("pathfinder"):
            charge_path = ctx["charging_manager"].get_charge_path(robot, ctx["pathfinder"])
        reserve = max(20, len(charge_path) - 1 + 5) if charge_path else 100
        self.beliefs["battery_low"] = robot.battery <= reserve
        self.beliefs["battery_full"] = robot.battery >= 100
        self.beliefs["has_task"] = robot.current_task is not None
        self.beliefs["carrying_item"] = robot.carrying_item
        self.beliefs["at_destination"] = len(robot.path) <= 1
        self.beliefs["at_charger"] = (
            bool(ctx.get("warehouse"))
            and ctx["charging_manager"].at_station(robot, ctx["warehouse"])
        )

        if len(robot.path) > 1 and collision_manager is not None:
            next_x, next_y = robot.path[1]
            self.beliefs["path_blocked"] = (
                (next_x, next_y) in collision_manager.reserved_cells
            )
        else:
            self.beliefs["path_blocked"] = False

        # Initial greeting when simulation/agent starts, regardless of step or other conditions
        if negotiation_service and not self.has_greeted:
            self.has_greeted = True
            negotiation_service.generate_initial_greeting(robot.id)

        # Check for greeting conditions when passing by other robots
        robot_manager = ctx.get("robot_manager")
        if negotiation_service and robot_manager:
            # Check nearby robots for greeting
            for other_robot in robot_manager.robots:
                if other_robot.id == robot.id:
                    continue
                dist = abs(robot.position.x - other_robot.position.x) + \
                       abs(robot.position.y - other_robot.position.y)
                if dist <= 2:
                    last_greeted = self.beliefs.get("last_greeted")
                    if last_greeted != other_robot.id:
                        self.beliefs["last_greeted"] = other_robot.id
                        negotiation_service.generate_greeting(robot.id, other_robot.id)

    def _remember(self, event, data):
        self.memory.append({"event": event, "data": data})

    # ------------------------------------------------------------------
    #  DECISION — choose the next action
    # ------------------------------------------------------------------

    def decide(self):
        """
        Determine the agent's next action based on current beliefs.

        Returns
        -------
        str
            Action tag: "need_charge", "charge", "charge_complete",
                        "wait_at_dest", "move", "pickup", "deliver", "idle"
        """
        b = self.beliefs
        robot = self.robot

        if robot.status == RobotStatus.NEGOTIATING:
            return "negotiating"

        # Priority 1 — battery critical and not already charging
        if b["battery_low"] and robot.status != RobotStatus.CHARGING:
            self.goal = AgentGoal.CHARGE
            return "need_charge"

        # Priority 2 — currently charging
        if robot.status == RobotStatus.CHARGING:
            self.goal = AgentGoal.CHARGE
            if b["at_charger"]:
                if b["battery_full"]:
                    return "charge_complete"
                return "charge"
            if b["at_destination"]:
                return "need_charge"
            return "move"

        # Priority 3 — at destination with a task
        if b["at_destination"] and b["has_task"]:
            if not b["carrying_item"]:
                return "pickup"
            else:
                return "deliver"

        # Priority 4 — has a path to follow
        if not b["at_destination"]:
            if b["has_task"]:
                self.goal = (
                    AgentGoal.DELIVER if b["carrying_item"]
                    else AgentGoal.PICKUP
                )
            return "move"

        # Default — nothing to do
        self.goal = AgentGoal.IDLE
        return "idle"

    # ------------------------------------------------------------------
    #  ACT — execute the chosen action
    # ------------------------------------------------------------------

    def act(self, action, **context):
        """
        Execute *action* using helpers from *context*.

        Parameters
        ----------
        action : str
            The action tag produced by decide().
        context : dict
            Injected dependencies:
              - task_manager
              - charging_manager
              - pathfinder
              - collision_manager
        """
        handler = self._action_handlers().get(action)
        if handler is not None:
            handler(context)

    def _action_handlers(self):
        return {
            "need_charge": self._handle_need_charge,
            "charge": self._handle_charge,
            "charge_complete": self._handle_charge_complete,
            "move": self._handle_move,
            "pickup": self._handle_pickup,
            "deliver": self._handle_deliver,
            "idle": self._handle_idle,
            "negotiating": self._handle_negotiating,
        }

    def _handle_negotiating(self, ctx):
        """Skip movement while waiting for LLM negotiation response."""
        pass

    # ---- need_charge ----

    def _handle_need_charge(self, ctx):
        """Unassign current task, compute path to nearest charger."""
        robot = self.robot
        task_manager = ctx["task_manager"]
        charging_manager = ctx["charging_manager"]
        pathfinder = ctx["pathfinder"]

        if robot.current_task is not None:
            released_task_id = robot.current_task
            task_manager.unassign_task(robot.current_task)
            self._remember(
                "released_task",
                {"task_id": released_task_id}
            )
            print(
                f"Robot {robot.id} released Task "
                f"{released_task_id}"
            )

            # Broadcast TASK_RELEASED so other agents and TaskAgents know
            self.broadcast(
                MessageType.TASK_RELEASED,
                {"robot_id": robot.id, "task_id": released_task_id}
            )

        robot.current_task = None
        robot.carrying_item = False
        robot.delivery_path = []
        charge_path = charging_manager.get_charge_path(robot, pathfinder)
        station = charge_path[-1] if charge_path else None

        if not charge_path:
            # No valid path to charger — stay IDLE and retry next tick
            print(
                f"[CHARGE ERROR] Robot {robot.id}: no valid path to "
                f"charger at {station}. Staying IDLE."
            )
            robot.current_task = None
            robot.path = []
            robot.status = RobotStatus.IDLE
            self._remember("charge_path_failed", {"station": station})
            return

        if len(charge_path) - 1 > robot.battery:
            print(f"[CHARGE ERROR] Robot {robot.id}: insufficient energy to reach charger; assistance needed.")
            robot.path = []
            robot.status = RobotStatus.NEEDS_CHARGE
            return
        robot.path = charge_path
        robot.current_task = None
        robot.status = RobotStatus.CHARGING

        # Broadcast LOW_BATTERY to inform peers
        self.broadcast(
            MessageType.LOW_BATTERY,
            {"robot_id": robot.id, "battery": robot.battery}
        )

        self._remember(
            "going_to_charge",
            {"station": station}
        )
        print(f"Robot {robot.id} going to charge")

    # ---- charge ----

    def _handle_charge(self, ctx):
        """Increment battery while sitting at charger."""
        robot = self.robot
        if not ctx["charging_manager"].at_station(robot, ctx["warehouse"]):
            print(f"[CHARGE ERROR] Robot {robot.id}: cannot charge away from a station.")
            return
        robot.battery = min(100, max(0, robot.battery) + 10)
        if robot.battery >= 100:
            robot.battery = 100

    # ---- charge_complete ----

    def _handle_charge_complete(self, ctx):
        """Battery full — return to IDLE."""
        robot = self.robot
        robot.battery = 100
        robot.status = RobotStatus.IDLE
        self.goal = AgentGoal.IDLE

        self._remember("fully_charged", {})
        print(f"Robot {robot.id} fully charged")

    # ---- move ----

    def _handle_move(self, ctx):
        """Attempt to move one step along the current path."""
        robot = self.robot
        collision_manager = ctx["collision_manager"]
        pathfinder = ctx["pathfinder"]

        if len(robot.path) <= 1:
            return

        energy = 2 if robot.carrying_item else 1
        if robot.battery < energy:
            print(f"[CHARGE ERROR] Robot {robot.id}: insufficient movement energy; assistance needed.")
            robot.battery = max(0, robot.battery)
            robot.status = RobotStatus.NEEDS_CHARGE
            return
        next_x, next_y = robot.path[1]

        # --- Full remaining-path integrity check ---
        # Validate ALL remaining cells in the path, not just the next one.
        # If any future cell is unwalkable, the entire path is corrupt and
        # must be recomputed. This catches stale paths from prior grid states.
        warehouse = ctx.get("warehouse")
        if warehouse:
            for step_idx in range(1, len(robot.path)):
                check_x, check_y = robot.path[step_idx]
                if not warehouse.is_walkable(check_x, check_y):
                    print(
                        f"[OBSTACLE BYPASS DETECTED] Robot {robot.id}: "
                        f"path cell ({check_x},{check_y}) at step {step_idx} "
                        f"is NOT walkable (grid='{warehouse.grid[check_y][check_x]}'). "
                        f"Robot pos=({robot.position.x},{robot.position.y}), "
                        f"status={robot.status.value}, task={robot.current_task}. "
                        f"Full path: {robot.path}. "
                        f"Path INVALIDATED — attempting recompute."
                    )
                    self._remember("path_invalidated", {
                        "cell": (check_x, check_y),
                        "step_index": step_idx,
                        "reason": "obstacle_in_remaining_path",
                        "grid_value": warehouse.grid[check_y][check_x],
                    })

                    # Attempt to recompute path to the original destination
                    if len(robot.path) > 0:
                        destination = robot.path[-1]
                        new_path = pathfinder.find_path(
                            (robot.position.x, robot.position.y),
                            destination
                        )
                        if new_path:
                            robot.path = new_path
                            print(
                                f"[OBSTACLE BYPASS RECOVERY] Robot {robot.id}: "
                                f"recomputed valid path to {destination}, "
                                f"length={len(new_path)}"
                            )
                        else:
                            robot.path = []
                            print(
                                f"[OBSTACLE BYPASS RECOVERY FAILED] Robot {robot.id}: "
                                f"no valid path to {destination}. Path cleared."
                            )
                    else:
                        robot.path = []
                    return

        success, conflicting_robot_id = collision_manager.reserve_cell(next_x, next_y, robot.id)
        if not success:
            self.blocked_counter += 1
            print(f"\n[⚠️ DEADLOCK] Robot {robot.id} blocked at ({next_x}, {next_y}). Strike {self.blocked_counter}/3.")
            
            self._remember(
                "blocked",
                {"cell": (next_x, next_y)}
            )
            # Broadcast BLOCKED_PATH
            self.broadcast(
                MessageType.BLOCKED_PATH,
                {"robot_id": robot.id, "cell": (next_x, next_y)}
            )
            
            if self.blocked_counter >= 3:
                negotiation_service = ctx.get("negotiation_service")
                if conflicting_robot_id is not None and robot.status != RobotStatus.NEGOTIATING and negotiation_service:
                    previous_status = robot.status
                    robot.status = RobotStatus.NEGOTIATING
                    
                    def on_negotiation_complete(winner_id, reason):
                        # Default back to IDLE so it re-decides next tick
                        robot.status = previous_status
                        
                    negotiation_service.resolve_deadlock(robot.id, conflicting_robot_id, next_x, next_y, on_negotiation_complete)
                
            return

        self.blocked_counter = 0
        robot.position.x = next_x
        robot.position.y = next_y
        robot.path.pop(0)
        robot.battery = max(0, robot.battery - energy)

        print(
            f"Robot {robot.id} -> ({next_x},{next_y}) "
            f"Battery={robot.battery:.0f}"
        )

        # Post-move arrival checks
        if len(robot.path) == 1:
            self._on_arrival(ctx)

    def _on_arrival(self, ctx):
        """Handle events that trigger when the robot reaches a destination."""
        robot = self.robot
        task_manager = ctx["task_manager"]

        if robot.status == RobotStatus.CHARGING:
            self._remember(
                "arrived_at_charger", {}
            )
            print(f"Robot {robot.id} arrived at charger")
            return

        if robot.current_task is not None:
            if not robot.carrying_item:
                # Validate delivery_path before switching
                if not robot.delivery_path:
                    print(
                        f"[DELIVERY PATH ERROR] Robot {robot.id}: "
                        f"delivery_path is empty at pickup arrival. "
                        f"Releasing task {robot.current_task}."
                    )
                    task_manager.unassign_task(robot.current_task)
                    self.broadcast(
                        MessageType.TASK_RELEASED,
                        {"robot_id": robot.id, "task_id": robot.current_task}
                    )
                    self._remember("delivery_path_empty", {"task_id": robot.current_task})
                    robot.current_task = None
                    robot.carrying_item = False
                    robot.delivery_path = []
                    robot.status = RobotStatus.IDLE
                    self.goal = AgentGoal.IDLE
                    return

                robot.carrying_item = True
                robot.path = robot.delivery_path
                robot.status = RobotStatus.DELIVERING
                self.goal = AgentGoal.DELIVER

                self._remember(
                    "picked_item",
                    {"task_id": robot.current_task}
                )
                print(f"Robot {robot.id} picked item")
            else:
                self._remember(
                    "delivered_task",
                    {"task_id": robot.current_task}
                )
                print(
                    f"Robot {robot.id} delivered Task "
                    f"{robot.current_task}"
                )

                task_manager.complete_task(robot.current_task)
                robot.current_task = None
                robot.carrying_item = False
                robot.delivery_path = []
                robot.status = RobotStatus.IDLE
                self.goal = AgentGoal.IDLE

    # ---- pickup ----

    def _handle_pickup(self, ctx):
        """Pick up item at current location."""
        robot = self.robot
        task_manager = ctx["task_manager"]

        # Validate delivery_path before switching
        if not robot.delivery_path:
            print(
                f"[DELIVERY PATH ERROR] Robot {robot.id}: "
                f"delivery_path is empty during pickup. "
                f"Releasing task {robot.current_task}."
            )
            task_manager.unassign_task(robot.current_task)
            self.broadcast(
                MessageType.TASK_RELEASED,
                {"robot_id": robot.id, "task_id": robot.current_task}
            )
            self._remember("delivery_path_empty", {"task_id": robot.current_task})
            robot.current_task = None
            robot.carrying_item = False
            robot.delivery_path = []
            robot.status = RobotStatus.IDLE
            self.goal = AgentGoal.IDLE
            return

        robot.carrying_item = True
        robot.path = robot.delivery_path
        robot.status = RobotStatus.DELIVERING
        self.goal = AgentGoal.DELIVER

        self._remember(
            "picked_item",
            {"task_id": robot.current_task}
        )
        print(f"Robot {robot.id} picked item")

    # ---- deliver ----

    def _handle_deliver(self, ctx):
        """Deliver item at current location."""
        robot = self.robot
        task_manager = ctx["task_manager"]

        self._remember(
            "delivered_task",
            {"task_id": robot.current_task}
        )
        print(
            f"Robot {robot.id} delivered Task "
            f"{robot.current_task}"
        )

        task_manager.complete_task(robot.current_task)
        robot.current_task = None
        robot.carrying_item = False
        robot.delivery_path = []
        robot.status = RobotStatus.IDLE
        self.goal = AgentGoal.IDLE

    # ---- idle ----

    def _handle_idle(self, ctx):
        """Nothing to do right now."""
        pass

    # ------------------------------------------------------------------
    #  MEMORY helpers
    # ------------------------------------------------------------------

    def _remember(self, event_type, data):
        """Append an event to local memory."""
        self.memory.append({
            "event": event_type,
            "data": data,
            "robot_id": self.robot.id,
        })

    def get_memory(self, last_n=None):
        """Return recent memory entries."""
        if last_n is None:
            return list(self.memory)
        return list(self.memory[-last_n:])

    # ------------------------------------------------------------------
    #  Full tick (convenience wrapper used by AgentManager)
    # ------------------------------------------------------------------

    def tick(self, **context):
        """
        Run one full cycle: process_messages → perceive → decide → act.
        """
        self.process_messages()
        self.perceive(
            collision_manager=context.get("collision_manager"),
            negotiation_service=context.get("negotiation_service"),
            ctx=context
        )
        action = self.decide()
        self.act(action, **context)

    # ------------------------------------------------------------------
    #  Representation
    # ------------------------------------------------------------------

    def __repr__(self):
        return (
            f"RobotAgent(robot_id={self.robot.id}, "
            f"goal={self.goal}, "
            f"beliefs={self.beliefs})"
        )

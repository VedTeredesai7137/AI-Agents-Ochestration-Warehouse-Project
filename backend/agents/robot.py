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

from collections import deque

from backend.core.events import logger
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
        self.context = {}

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
        self.memory = deque(maxlen=300)
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

        # Control actions also exclude this robot from new CNP work.
        if robot.orchestration_holds or robot.hold_steps_remaining or robot.yield_steps_remaining:
            return
        # Eligibility check
        if not is_emergency and robot.current_task is not None:
            return
        if robot.battery < 30:
            return
        if robot.status in (RobotStatus.CHARGING, RobotStatus.NEEDS_CHARGE, RobotStatus.NEGOTIATING):
            return

        task_id = msg.payload.get("task_id")
        pickup_x = msg.payload.get("pickup_x")
        pickup_y = msg.payload.get("pickup_y")

        # Route/energy feasibility includes explicit recharge stops, never a doomed delivery.
        ctx = self.context
        task = ctx.get("task_manager") and ctx["task_manager"].get_task(task_id)
        offer = ctx["charging_manager"].task_offer(robot, task, ctx["pathfinder"]) if task else None
        if task and offer is None:
            return
        # Compatibility for standalone message-only agents without a simulation context.
        distance = (
            abs(robot.position.x - pickup_x)
            + abs(robot.position.y - pickup_y)
        )
        battery_penalty = (100 - robot.battery) * 0.1
        estimated_cost = offer if offer is not None else distance + battery_penalty

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
        reserve = len(charge_path) - 1 + 5 if charge_path else 100
        if robot.current_task is not None and robot.status != RobotStatus.CHARGING and not robot.orchestration_holds:
            self._plan_task_charging(ctx)
        # Owned tasks use their planned charging itinerary; do not drop a feasible parcel.
        if robot.current_task is not None and robot.status != RobotStatus.NEEDS_CHARGE:
            reserve = -1
        self.beliefs["battery_low"] = robot.battery <= reserve or (robot.current_task is None and robot.battery < 30)
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

        if negotiation_service and not self.has_greeted:
            self.has_greeted = True
            negotiation_service.generate_initial_greeting(robot.id)
        # Existing social visibility, with bounded local messages and no model call.
        if negotiation_service and ctx.get("robot_manager"):
            nearby = next((other for other in ctx["robot_manager"].robots
                           if other.id != robot.id and abs(other.position.x-robot.position.x)
                           + abs(other.position.y-robot.position.y) <= 2), None)
            if nearby and self.beliefs.get("last_greeted") != nearby.id:
                self.beliefs["last_greeted"] = nearby.id
                negotiation_service.generate_greeting(robot.id, nearby.id)

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

        if robot.orchestration_holds or robot.hold_steps_remaining or robot.yield_steps_remaining:
            return "hold"
        if robot.status == RobotStatus.NEGOTIATING:
            return "negotiating"

        # Priority 1 — battery critical and not already charging
        if b["battery_low"] and robot.status != RobotStatus.CHARGING:
            self.goal = AgentGoal.CHARGE
            return "need_charge"

        # Priority 2 — currently charging
        if robot.status == RobotStatus.CHARGING:
            self.goal = AgentGoal.CHARGE
            if b["at_charger"] and b["at_destination"]:
                if b["battery_full"]:
                    return "charge_complete"
                return "charge"
            if b["at_destination"]:
                return "need_charge"
            return "move"

        # Priority 3 — at destination with a task
        if b["at_destination"] and b["has_task"]:
            if not robot.path:
                return "recover"
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
            "hold": self._handle_hold,
            "recover": self._recover_route,
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

    def _handle_hold(self, ctx):
        robot = self.robot
        if robot.orchestration_holds:
            return
        robot.hold_steps_remaining = max(0, robot.hold_steps_remaining - 1)
        robot.yield_steps_remaining = max(0, robot.yield_steps_remaining - 1)
        if not robot.yield_steps_remaining:
            robot.yield_to_robot_id = None

    def start_charging(self, ctx, charge_path=None):
        """Preflight before releasing a task. Also used by the action executor."""
        robot = self.robot
        path = charge_path if charge_path is not None else ctx["charging_manager"].get_charge_path(robot, ctx["pathfinder"], congestion=True)
        if not path or len(path) - 1 > robot.battery:
            raise ValueError("No battery-feasible route to a real charger")
        if robot.current_task is not None:
            ctx["task_manager"].release_task(robot, self.message_bus, "going_to_charger")
        robot.path = list(path)
        robot.delivery_path = []
        robot.carrying_item = False
        robot.route_waypoint = None
        if ctx.get("engine") and robot.status != RobotStatus.CHARGING:
            ctx["engine"].measurements["charging_events"] += 1
        robot.status = RobotStatus.CHARGING
        self.goal = AgentGoal.CHARGE
        self.broadcast(MessageType.LOW_BATTERY, {"robot_id": robot.id, "battery": robot.battery})

    def _plan_task_charging(self, ctx):
        robot = self.robot
        task = ctx["task_manager"].get_task(robot.current_task)
        if not task or task.completed or task.assigned_robot != robot.id:
            return
        charging, pf = ctx["charging_manager"], ctx["pathfinder"]
        goal = (task.delivery_x, task.delivery_y) if robot.carrying_item else (task.pickup_x, task.pickup_y)
        rate = 2 if robot.carrying_item else 1
        escape = charging.nearest_distance(goal, pf)*(1 if robot.carrying_item else 2)+charging.RESERVE
        # Keep working routes/LLM waypoints when feasible. A* safety remains in movement.
        if robot.path and charging.distance((robot.position.x,robot.position.y),goal,pf)*rate+escape <= robot.battery:
            return
        trip = charging.journey((robot.position.x,robot.position.y), goal, robot.battery, pf,
                                loaded=robot.carrying_item, pickup=not robot.carrying_item)
        if trip and tuple(trip[0][-1]) != goal:
            # A single inbound owner per bay leaves room for charged robots to exit.
            stop = tuple(trip[0][-1])
            others = ctx.get("robot_manager").robots if ctx.get("robot_manager") else []
            if any(r.id != robot.id and (r.position.x,r.position.y) == stop
                   or r.id != robot.id and r.status == RobotStatus.CHARGING and r.path and tuple(r.path[-1]) == stop
                   for r in others):
                alternative = charging.get_charge_path(robot,pf,congestion=True,loaded=robot.carrying_item)
                if alternative:
                    trip = (alternative,trip[1],trip[2])
                else:
                    # Do not join a blocked bay's entrance queue. Retry next tick.
                    robot.hold_steps_remaining = max(robot.hold_steps_remaining,1)
                    return
            robot.path = trip[0]
            robot.route_waypoint = None
            robot.status = RobotStatus.CHARGING
            if ctx.get("engine"):
                ctx["engine"].measurements["charging_events"] += 1
        elif trip:
            # A traffic detour may exceed the remaining budget even though the
            # direct leg is feasible. Replace that stale detour before movement.
            robot.path = trip[0]
        elif trip is None:
            # A changed aisle can invalidate an accepted itinerary. Safe release is
            # still available; battery-impossible motion is never attempted.
            self._handle_need_charge(ctx)

    def _handle_need_charge(self, ctx):
        try:
            self.start_charging(ctx)
        except ValueError as error:
            if self.robot.status != RobotStatus.NEEDS_CHARGE:
                logger.warning("[CHARGE ERROR] robot_id=%s reason=%s", self.robot.id, error)
            # Keep task/parcel ownership; assistance may be necessary.
            self.robot.path = []
            self.robot.status = RobotStatus.NEEDS_CHARGE

    # ---- charge ----

    def _handle_charge(self, ctx):
        """Increment battery while sitting at charger."""
        robot = self.robot
        if not ctx["charging_manager"].at_station(robot, ctx["warehouse"]):
            print(f"[CHARGE ERROR] Robot {robot.id}: cannot charge away from a station.")
            return
        robot.battery = min(100, max(0, robot.battery) + ctx["charging_manager"].CHARGE_RATE)
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
        if robot.current_task is not None:
            robot.status = RobotStatus.DELIVERING if robot.carrying_item else RobotStatus.MOVING
            robot.path = []
            self._recover_route(ctx)
        else:
            robot.path = []
        logger.debug("[SIM] robot_id=%s fully charged", robot.id)

    # ---- move ----

    def _recover_route(self, ctx):
        robot = self.robot
        task = ctx["task_manager"].get_task(robot.current_task)
        destination = None
        if robot.status == RobotStatus.CHARGING:
            path = ctx["charging_manager"].get_charge_path(robot, ctx["pathfinder"], loaded=robot.carrying_item)
            destination = path[-1] if path else None
        elif task and not task.completed:
            destination = ((task.delivery_x, task.delivery_y) if robot.carrying_item
                           else (task.pickup_x, task.pickup_y))
        elif robot.path:
            destination = robot.path[-1]
        start = (robot.position.x, robot.position.y)
        path = []
        if destination is not None:
            if robot.route_waypoint and start != robot.route_waypoint:
                first = ctx["pathfinder"].find_path(start, robot.route_waypoint)
                second = ctx["pathfinder"].find_path(robot.route_waypoint, destination)
                path = first + second[1:] if first and second else []
            else:
                path = ctx["pathfinder"].find_path(start, destination)
        robot.path = path
        if path:
            logger.info("[OBSTACLE BYPASS RECOVERY] robot_id=%s length=%s", robot.id, len(path))
        else:
            logger.warning("[OBSTACLE BYPASS RECOVERY FAILED] robot_id=%s destination=%s", robot.id, destination)

    def _handle_move(self, ctx):
        """Full remaining-path validation precedes every orthogonal movement."""
        robot = self.robot
        if len(robot.path) <= 1:
            return
        start = (robot.position.x, robot.position.y)
        pathfinder = ctx["pathfinder"]
        if tuple(robot.path[0]) != start or not pathfinder._validate_path_integrity(robot.path):
            logger.warning("[OBSTACLE BYPASS DETECTED] robot_id=%s path invalidated", robot.id)
            self._remember("path_invalidated", {"reason": "invalid_remaining_path"})
            self._recover_route(ctx)
            return
        energy = 2 if robot.carrying_item else 1
        if robot.battery < energy:
            logger.warning("[CHARGE ERROR] robot_id=%s insufficient movement energy", robot.id)
            robot.battery = max(0, robot.battery)
            robot.status = RobotStatus.NEEDS_CHARGE
            return
        next_x, next_y = robot.path[1]
        if ctx.get("engine"):
            task = ctx["task_manager"].get_task(robot.current_task)
            delivering_now = task and robot.carrying_item and (next_x,next_y) == (task.delivery_x,task.delivery_y) and robot.status != RobotStatus.CHARGING
            return_rate = 1 if delivering_now else energy
            escape = ctx["charging_manager"].nearest_distance((next_x,next_y),pathfinder)*return_rate
            if energy+escape > robot.battery:
                # A congestion reroute must not spend the last energy needed to
                # reach charging. Replan a loaded stop without losing ownership.
                path = ctx["charging_manager"].get_charge_path(robot,pathfinder,loaded=robot.carrying_item)
                if path and (len(path)-1)*energy <= robot.battery:
                    robot.path = path
                    if robot.status != RobotStatus.CHARGING:
                        ctx["engine"].measurements["charging_events"] += 1
                    robot.status = RobotStatus.CHARGING
                else:
                    robot.path = []
                    robot.status = RobotStatus.NEEDS_CHARGE
                return
        collision = ctx["collision_manager"]
        success, other = collision.reserve_cell(next_x, next_y, robot.id)
        if not success:
            self.blocked_counter += 1
            self.broadcast(MessageType.BLOCKED_PATH, {"robot_id": robot.id, "cell": (next_x, next_y)})
            if ctx.get("engine"):
                ctx["engine"].request_deadlock(robot.id, other, (next_x, next_y))
            return
        self.blocked_counter = 0
        if ctx.get("engine"):
            ctx["engine"].record_movement(robot.id)
        robot.position.x, robot.position.y = next_x, next_y
        collision.moved(robot.id, start, (next_x, next_y))
        robot.path.pop(0)
        robot.battery = max(0, robot.battery - energy)
        if robot.route_waypoint == (next_x, next_y):
            robot.route_waypoint = None
        logger.debug("[SIM] robot_id=%s position=%s battery=%s", robot.id, (next_x, next_y), robot.battery)
        if len(robot.path) == 1:
            self._on_arrival(ctx)

    def _on_arrival(self, ctx):
        if self.robot.status == RobotStatus.CHARGING:
            self._remember("arrived_at_charger", {})
        elif self.robot.current_task is not None:
            if self.robot.carrying_item:
                self._handle_deliver(ctx)
            else:
                self._handle_pickup(ctx)

    def _at_task_destination(self, ctx, delivery=False):
        robot = self.robot
        task = ctx["task_manager"].get_task(robot.current_task)
        if not task or task.completed or task.assigned_robot != robot.id:
            return False
        target = (task.delivery_x, task.delivery_y) if delivery else (task.pickup_x, task.pickup_y)
        return bool(robot.path) and (robot.position.x, robot.position.y) == target

    def _handle_pickup(self, ctx):
        robot = self.robot
        if not self._at_task_destination(ctx):
            self._recover_route(ctx)
            return
        # Empty/stale delivery paths never become a pickup transition.
        if (not robot.delivery_path or tuple(robot.delivery_path[0]) != (robot.position.x, robot.position.y)
                or not ctx["pathfinder"]._validate_path_integrity(robot.delivery_path)):
            logger.warning("[DELIVERY PATH ERROR] robot_id=%s releasing task_id=%s", robot.id, robot.current_task)
            ctx["task_manager"].release_task(robot, self.message_bus, "invalid_delivery_path")
            return
        robot.carrying_item = True
        robot.path = list(robot.delivery_path)
        robot.status = RobotStatus.DELIVERING
        self.goal = AgentGoal.DELIVER
        self._remember("picked_item", {"task_id": robot.current_task})

    def _handle_deliver(self, ctx):
        robot = self.robot
        if not self._at_task_destination(ctx, delivery=True) or not robot.carrying_item:
            self._recover_route(ctx)
            return
        self._remember("delivered_task", {"task_id": robot.current_task})
        ctx["task_manager"].complete_task(robot.current_task, robot=robot)
        robot.current_task = None
        robot.carrying_item = False
        robot.path = []
        robot.delivery_path = []
        robot.route_waypoint = None
        robot.status = RobotStatus.IDLE
        self.goal = AgentGoal.IDLE

    # ---- idle ----

    def _handle_idle(self, ctx):
        """Vacate charging/service cells and next-step traffic using normal movement."""
        robot = self.robot
        robots = ctx.get("robot_manager").robots if ctx.get("robot_manager") else []
        pos = (robot.position.x,robot.position.y)
        next_cells = {tuple(r.path[1]) for r in robots if r.id != robot.id and len(r.path)>1}
        # Parked robots must also leave passing space around a blocked episode.
        # The blocked robot's fallback can have cleared its path, so next-cell
        # intent alone misses this case (especially near a charging bay).
        blocked = [(r.position.x,r.position.y) for r in robots
                   if ctx.get("engine") and r.id in ctx["engine"]._deadlocks and r.id != robot.id]
        distance = lambda p: min((abs(p[0]-b[0])+abs(p[1]-b[1]) for b in blocked), default=1000)
        nearby_contention = distance(pos) <= 2
        if pos not in next_cells and not nearby_contention and not ctx["charging_manager"].at_station(robot,ctx["warehouse"]):
            return
        occupied = {(r.position.x,r.position.y) for r in robots}
        routes = {tuple(p) for r in robots if r.id != robot.id for p in r.path}
        neighbors = [p for p in ctx["warehouse"].get_neighbors(*pos) if p not in occupied | next_cells
                     and ctx["warehouse"].grid[p[1]][p[0]] != "C"]
        if neighbors and robot.battery > 5:
            # Move outward from contention rather than oscillating around it.
            if nearby_contention:
                neighbors = [p for p in neighbors if distance(p)>distance(pos)]
            if neighbors:
                target = min(neighbors, key=lambda p:(p in routes,-distance(p),p))
                robot.path = [pos,target]

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
        return list(self.memory)[-last_n:]

    # ------------------------------------------------------------------
    #  Full tick (convenience wrapper used by AgentManager)
    # ------------------------------------------------------------------

    def tick(self, **context):
        """
        Run one full cycle: process_messages → perceive → decide → act.
        """
        self.context = context
        self.process_messages()
        self.perceive(
            collision_manager=context.get("collision_manager"),
            negotiation_service=context.get("negotiation_service"),
            ctx=context
        )
        action = self.decide()
        if action != "move":
            self.blocked_counter = 0
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

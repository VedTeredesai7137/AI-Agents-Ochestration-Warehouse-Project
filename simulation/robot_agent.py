"""
RobotAgent — Autonomous agent wrapper for a Robot.

Each RobotAgent is responsible for:
  - Perception:  observing the warehouse environment and own state.
  - Decision:    choosing what to do next (charge, move, pick, deliver).
  - Action:      executing the chosen action on the underlying Robot.
  - Memory:      maintaining a local history of events and beliefs.

This module does NOT contain LLM integration or Contract Net Protocol.
It wraps the existing deterministic logic so that each robot behaves as
an autonomous agent while preserving identical simulation semantics.
"""

from simulation.models import RobotStatus


# ---------------------------------------------------------------------------
# Agent goal enum (lightweight, no Pydantic needed)
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
    Autonomous agent that controls a single Robot.

    Attributes
    ----------
    robot : Robot
        Reference to the underlying Robot model (owned by RobotManager).
    goal : str
        Current high-level goal (see AgentGoal).
    beliefs : dict
        Agent's local beliefs about the world (battery_low, has_task, etc.).
    memory : list[dict]
        Chronological log of notable events.
    current_plan : list[str]
        Ordered list of planned micro-actions for the current goal.
    """

    def __init__(self, robot):
        self.robot = robot

        # --- cognitive state ---
        self.goal = AgentGoal.IDLE
        self.beliefs = {
            "battery_low": False,
            "has_task": False,
            "carrying_item": False,
            "at_destination": False,
            "at_charger": False,
            "battery_full": False,
            "path_blocked": False,
        }
        self.memory = []
        self.current_plan = []

    # ------------------------------------------------------------------
    #  PERCEPTION — observe environment + own state
    # ------------------------------------------------------------------

    def perceive(self, collision_manager=None):
        """
        Update beliefs from the robot's current state.

        Parameters
        ----------
        collision_manager : CollisionManager | None
            If provided, used to check whether the next cell is blocked.
        """
        robot = self.robot

        self.beliefs["battery_low"] = robot.battery <= 20
        self.beliefs["battery_full"] = robot.battery >= 100
        self.beliefs["has_task"] = robot.current_task is not None
        self.beliefs["carrying_item"] = robot.carrying_item
        self.beliefs["at_destination"] = len(robot.path) <= 1
        self.beliefs["at_charger"] = (
            robot.status == RobotStatus.CHARGING
            and len(robot.path) <= 1
        )

        # Check if next move would be blocked
        if len(robot.path) > 1 and collision_manager is not None:
            next_x, next_y = robot.path[1]
            # Peek without reserving — we just want to know
            self.beliefs["path_blocked"] = (
                (next_x, next_y) in collision_manager.reserved_cells
            )
        else:
            self.beliefs["path_blocked"] = False

    # ------------------------------------------------------------------
    #  DECISION — choose the next action
    # ------------------------------------------------------------------

    def decide(self):
        """
        Determine the agent's next action based on current beliefs.

        Returns
        -------
        str
            Action tag:  "need_charge", "charge", "charge_complete",
                         "wait_at_dest", "move", "pickup", "deliver",
                         "idle"
        """
        b = self.beliefs
        robot = self.robot

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
            # Still en-route to charger — treat as movement
            if b["at_destination"]:
                # At charger (path exhausted)
                if b["battery_full"]:
                    return "charge_complete"
                return "charge"
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
            The action tag produced by ``decide()``.
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

    # ---- private action handlers ----

    def _action_handlers(self):
        return {
            "need_charge": self._handle_need_charge,
            "charge": self._handle_charge,
            "charge_complete": self._handle_charge_complete,
            "move": self._handle_move,
            "pickup": self._handle_pickup,
            "deliver": self._handle_deliver,
            "idle": self._handle_idle,
        }

    # ---- need_charge ----

    def _handle_need_charge(self, ctx):
        """Unassign current task, compute path to nearest charger."""
        robot = self.robot
        task_manager = ctx["task_manager"]
        charging_manager = ctx["charging_manager"]
        pathfinder = ctx["pathfinder"]

        if robot.current_task is not None:
            task_manager.unassign_task(robot.current_task)
            self._remember(
                "released_task",
                {"task_id": robot.current_task}
            )
            print(
                f"Robot {robot.id} released Task "
                f"{robot.current_task}"
            )

        station = charging_manager.get_nearest_station(robot)

        robot.path = pathfinder.find_path(
            (robot.position.x, robot.position.y),
            station
        )
        robot.current_task = None
        robot.status = RobotStatus.CHARGING

        self._remember(
            "going_to_charge",
            {"station": station}
        )
        print(f"Robot {robot.id} going to charge")

    # ---- charge ----

    def _handle_charge(self, ctx):
        """Increment battery while sitting at charger."""
        robot = self.robot
        robot.battery += 10
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

        if len(robot.path) <= 1:
            return  # nothing to move toward

        next_x, next_y = robot.path[1]

        if not collision_manager.reserve_cell(next_x, next_y):
            self._remember(
                "blocked",
                {"cell": (next_x, next_y)}
            )
            return  # cell taken this step

        robot.position.x = next_x
        robot.position.y = next_y
        robot.path.pop(0)
        robot.battery -= 1

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
                # Arrived at pickup
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
                # Arrived at delivery
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

    # ---- pickup (at destination, not yet carrying) ----

    def _handle_pickup(self, ctx):
        """
        Pick up item at current location.
        This mirrors the arrival-at-pickup logic for the edge case
        where the robot is already at the pickup cell when assigned.
        """
        robot = self.robot
        robot.carrying_item = True
        robot.path = robot.delivery_path
        robot.status = RobotStatus.DELIVERING
        self.goal = AgentGoal.DELIVER

        self._remember(
            "picked_item",
            {"task_id": robot.current_task}
        )
        print(f"Robot {robot.id} picked item")

    # ---- deliver (at destination, carrying item) ----

    def _handle_deliver(self, ctx):
        """
        Deliver item at current location.
        This mirrors the arrival-at-delivery logic for the edge case
        where the delivery path was zero-length.
        """
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
        """
        Return recent memory entries.

        Parameters
        ----------
        last_n : int | None
            If given, return only the most recent *last_n* entries.
        """
        if last_n is None:
            return list(self.memory)
        return list(self.memory[-last_n:])

    # ------------------------------------------------------------------
    #  Full tick (convenience wrapper used by AgentManager)
    # ------------------------------------------------------------------

    def tick(self, **context):
        """
        Run one full perceive → decide → act cycle.

        Parameters
        ----------
        context : dict
            Same keyword arguments accepted by ``act()``.
        """
        self.perceive(
            collision_manager=context.get("collision_manager")
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

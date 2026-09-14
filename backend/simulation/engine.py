"""
SimulationEngine — Orchestration infrastructure for the warehouse simulation.

The engine coordinates execution but does NOT make task assignment decisions.
Task allocation is handled by TaskAgents via the Contract Net Protocol.
Robot behavior is handled by RobotAgents via the perceive-decide-act cycle.

Responsibilities:
  - Advance simulation step counter.
  - Reset collision reservations each step.
  - Tick TaskAgentManager (CNP lifecycle).
  - Tick AgentManager (robot perceive-decide-act).
  - Detect simulation completion.
"""

from backend.core.models import RobotStatus
from backend.agents.orchestrator_graph import orchestrator_runner


class SimulationEngine:

    def __init__(
        self,
        robot_manager,
        collision_manager,
        task_manager,
        charging_manager,
        pathfinder,
        agent_manager=None,
        task_agent_manager=None,
        negotiation_service=None
    ):
        self.robot_manager = robot_manager
        self.collision_manager = collision_manager
        self.task_manager = task_manager
        self.charging_manager = charging_manager
        self.pathfinder = pathfinder
        self.agent_manager = agent_manager
        self.task_agent_manager = task_agent_manager
        self.negotiation_service = negotiation_service
        self.current_step = 0

    # ------------------------------------------------------------------
    # Orchestrator observability
    # ------------------------------------------------------------------

    @property
    def orchestrator_active(self):
        """True when the LangGraph crisis orchestrator is running."""
        return orchestrator_runner.is_active

    # ------------------------------------------------------------------
    # Legacy assign_new_tasks — kept for backward compatibility when
    # no task_agent_manager is present.
    # ------------------------------------------------------------------

    def assign_new_tasks(self):
        """Centralized auction fallback (used only if no task_agent_manager)."""
        for task in self.task_manager.get_unassigned_tasks():
            bids = []
            for robot in self.robot_manager.robots:
                if robot.current_task is not None:
                    continue
                if robot.battery < 30:
                    continue
                distance = (
                    abs(robot.position.x - task.pickup_x)
                    + abs(robot.position.y - task.pickup_y)
                )
                battery_penalty = (100 - robot.battery) * 0.1
                bid = distance + battery_penalty
                bids.append((bid, robot.id))

            if not bids:
                continue

            bids.sort()
            winner = bids[0][1]

            try:
                if self.negotiation_service is not None:
                    bids_str = ", ".join([f"R{r_id}: {b:.1f}" for b, r_id in bids])
                    self.negotiation_service.explain_auction_winner(task.id, winner, bids_str)
            except Exception:
                pass

            robot = self.robot_manager.get_robot(winner)

            pickup_path = self.pathfinder.find_path(
                (robot.position.x, robot.position.y),
                (task.pickup_x, task.pickup_y)
            )

            delivery_path = self.pathfinder.find_path(
                (task.pickup_x, task.pickup_y),
                (task.delivery_x, task.delivery_y)
            )

            if not pickup_path:
                continue

            if not delivery_path:
                continue

            path = pickup_path

            if not path:
                continue

            self.task_manager.assign_task(
                task.id,
                winner
            )

            self.robot_manager.assign_task(
                winner,
                task.id,
                path
            )
            robot.delivery_path = delivery_path

            print(
                f"Task {task.id} assigned to Robot {winner}"
            )

    # ------------------------------------------------------------------
    # Legacy handle_battery — kept for backward compatibility when
    # no agent_manager is present.
    # ------------------------------------------------------------------

    def handle_battery(self, robot):

        if robot.battery > 20:
            return

        if robot.status == RobotStatus.CHARGING:
            return

        if robot.current_task is not None:

            self.task_manager.unassign_task(
                robot.current_task
            )

            print(
                f"Robot {robot.id} released Task "
                f"{robot.current_task}"
            )

        robot.path = self.charging_manager.get_charge_path(robot, self.pathfinder)
        robot.carrying_item = False
        robot.delivery_path = []
        if not robot.path or len(robot.path) - 1 > robot.battery:
            robot.path = []
            robot.current_task = None
            robot.status = RobotStatus.NEEDS_CHARGE
            print(f"[CHARGE ERROR] Robot {robot.id}: cannot reach a charger.")
            return

        robot.current_task = None
        robot.status = RobotStatus.CHARGING

        print(
            f"Robot {robot.id} going to charge"
        )

    # ------------------------------------------------------------------
    # STEP — main simulation tick
    # ------------------------------------------------------------------

    def step(self):

        self.current_step += 1

        print(f"\nSTEP {self.current_step}")
        
        if self.current_step > 0 and self.current_step % 50 == 0:
            self.trigger_warehouse_crisis()

        self.collision_manager.reset_step()

        # ----- Multi-Agent path (new: CNP + agents) -----
        if self.task_agent_manager is not None and self.agent_manager is not None:
            # 1. Tick task agents (issue CFPs, collect proposals, award contracts)
            self.task_agent_manager.tick_all(
                robot_manager=self.robot_manager,
                pathfinder=self.pathfinder,
            )

            # 2. Tick robot agents (process messages, perceive, decide, act)
            self.agent_manager.tick_all(
                current_step=self.current_step,
                robot_manager=self.robot_manager,
                task_manager=self.task_manager,
                charging_manager=self.charging_manager,
                pathfinder=self.pathfinder,
                collision_manager=self.collision_manager,
                negotiation_service=self.negotiation_service,
                warehouse=self.pathfinder.warehouse,
            )
            return

        # ----- Agent-only path (agents without CNP) -----
        if self.agent_manager is not None:
            self.assign_new_tasks()
            self.agent_manager.tick_all(
                current_step=self.current_step,
                robot_manager=self.robot_manager,
                task_manager=self.task_manager,
                charging_manager=self.charging_manager,
                pathfinder=self.pathfinder,
                collision_manager=self.collision_manager,
                negotiation_service=self.negotiation_service,
                warehouse=self.pathfinder.warehouse,
            )
            return

        # ----- Legacy path (no agents at all) -----
        self.assign_new_tasks()

        for robot in self.robot_manager.robots:

            self.handle_battery(robot)

            if len(robot.path) <= 1:

                if robot.status == RobotStatus.CHARGING and self.charging_manager.at_station(robot, self.pathfinder.warehouse):

                    robot.battery += 10

                    if robot.battery >= 100:

                        robot.battery = 100
                        robot.status = RobotStatus.IDLE

                        print(
                            f"Robot {robot.id} fully charged"
                        )

                continue

            if robot.battery < 1:
                robot.battery = max(0, robot.battery)
                robot.status = RobotStatus.NEEDS_CHARGE
                continue
            next_x, next_y = robot.path[1]

            success, _ = self.collision_manager.reserve_cell(
                next_x,
                next_y,
                robot.id
            )
            if not success:
                continue

            robot.position.x = next_x
            robot.position.y = next_y

            robot.path.pop(0)

            robot.battery = max(0, robot.battery - 1)

            print(
                f"Robot {robot.id} -> ({next_x},{next_y}) "
                f"Battery={robot.battery:.0f}"
            )

            if len(robot.path) == 1:

                if robot.status == RobotStatus.CHARGING:

                    print(
                        f"Robot {robot.id} arrived at charger"
                    )

                elif robot.current_task is not None:

                    task = self.task_manager.get_task(
                        robot.current_task
                    )

                    if not robot.carrying_item:

                        robot.carrying_item = True

                        robot.path = (
                            robot.delivery_path
                        )

                        robot.status = (
                            RobotStatus.DELIVERING
                        )

                        print(
                            f"Robot {robot.id} "
                            f"picked item"
                        )

                    else:

                        print(
                            f"Robot {robot.id} "
                            f"delivered Task "
                            f"{robot.current_task}"
                        )

                        self.task_manager.complete_task(
                            robot.current_task
                        )

                        robot.current_task = None

                        robot.carrying_item = False

                        robot.delivery_path = []

                        robot.status = (
                            RobotStatus.IDLE
                        )

    def is_complete(self):

        unfinished_tasks = [
            task
            for task in self.task_manager.tasks
            if not task.completed
        ]

        active_robots = [
            robot
            for robot in self.robot_manager.robots
            if robot.current_task is not None
        ]

        return (
            len(unfinished_tasks) == 0
            and len(active_robots) == 0
        )

    def trigger_warehouse_crisis(self):
        import random
        warehouse = self.pathfinder.warehouse
        
        candidates = []
        for y in range(10, min(21, warehouse.height - 1)):
            for x in range(5, warehouse.width - 7):
                if warehouse.grid[y][x] == "." and warehouse.grid[y][x+1] == "." and warehouse.grid[y][x+2] == ".":
                    candidates.append((x, y))
                    
        if not candidates:
            # Fallback to whole grid
            for y in range(1, warehouse.height - 1):
                for x in range(1, warehouse.width - 3):
                    if warehouse.grid[y][x] == "." and warehouse.grid[y][x+1] == "." and warehouse.grid[y][x+2] == ".":
                        candidates.append((x, y))
        
        if not candidates:
            return
            
        cx, cy = random.choice(candidates)
        warehouse.grid[cy][cx] = "S"
        warehouse.grid[cy][cx+1] = "S"
        warehouse.grid[cy][cx+2] = "S"
        
        print(f"\n[🚨 CRISIS] AISLE COLLAPSE AT ({cx},{cy}) to ({cx+2},{cy})! Rerouting swarm...")
        
        if self.agent_manager and self.agent_manager.message_bus:
            from backend.agents.message_bus import MessageType
            msg = self.agent_manager.message_bus.create_message(
                sender="System",
                recipient="ALL",
                message_type=MessageType.CRISIS_ALERT,
                payload={"coords": [(cx, cy), (cx+1, cy), (cx+2, cy)]}
            )
            self.agent_manager.message_bus.broadcast(msg)
            
        if self.negotiation_service:
            self.negotiation_service.generate_crisis_report(cx, cy, cx+2, cy)

        # --- LangGraph Orchestrator: Identify affected robots and invoke ---
        crisis_cells = {(cx, cy), (cx+1, cy), (cx+2, cy)}
        affected_ids = []
        for robot in self.robot_manager.robots:
            # Check if any cell in the robot's current path is now blocked
            for step in robot.path:
                if (step[0], step[1]) in crisis_cells:
                    affected_ids.append(robot.id)
                    break
            # Also check delivery_path
            if robot.id not in affected_ids and hasattr(robot, 'delivery_path'):
                for step in robot.delivery_path:
                    if (step[0], step[1]) in crisis_cells:
                        affected_ids.append(robot.id)
                        break

        if affected_ids:
            print(f"[ORCHESTRATOR TRIGGER] {len(affected_ids)} robots affected: {affected_ids}")
            orchestrator_runner.invoke_async(
                crisis_coords=list(crisis_cells),
                affected_robot_ids=affected_ids,
                pathfinder=self.pathfinder,
                robot_manager=self.robot_manager,
            )
        else:
            print("[ORCHESTRATOR TRIGGER] No robots directly affected by this collapse.")
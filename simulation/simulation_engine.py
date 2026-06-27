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

from simulation.models import RobotStatus


class SimulationEngine:

    def __init__(
        self,
        robot_manager,
        collision_manager,
        task_manager,
        charging_manager,
        pathfinder,
        auction_manager=None,
        agent_manager=None,
        task_agent_manager=None,
        negotiation_service=None
    ):
        self.robot_manager = robot_manager
        self.collision_manager = collision_manager
        self.task_manager = task_manager
        self.charging_manager = charging_manager
        self.pathfinder = pathfinder
        self.auction_manager = auction_manager
        self.agent_manager = agent_manager
        self.task_agent_manager = task_agent_manager
        self.negotiation_service = negotiation_service
        self.current_step = 0

    # ------------------------------------------------------------------
    # Legacy assign_new_tasks — kept for backward compatibility when
    # no task_agent_manager is present.
    # ------------------------------------------------------------------

    def assign_new_tasks(self):
        """Centralized auction fallback (used only if no task_agent_manager)."""
        if self.auction_manager is None:
            return

        for task in self.task_manager.get_unassigned_tasks():

            winner = self.auction_manager.run_auction(task)

            if winner is None:
                continue

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

        station = self.charging_manager.get_nearest_station(
            robot
        )

        robot.path = self.pathfinder.find_path(
            (robot.position.x, robot.position.y),
            station
        )

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
            )
            return

        # ----- Legacy path (no agents at all) -----
        self.assign_new_tasks()

        for robot in self.robot_manager.robots:

            self.handle_battery(robot)

            if len(robot.path) <= 1:

                if robot.status == RobotStatus.CHARGING:

                    robot.battery += 10

                    if robot.battery >= 100:

                        robot.battery = 100
                        robot.status = RobotStatus.IDLE

                        print(
                            f"Robot {robot.id} fully charged"
                        )

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

            robot.battery -= 1

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
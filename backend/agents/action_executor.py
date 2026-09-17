"""Validated actions are staged on copies, then committed while holding engine.lock."""
from copy import copy, deepcopy

from backend.agents.plans import ActionType
from backend.agents.plan_validator import PlanValidator, WorldSnapshot
from backend.agents.robot import RobotAgent
from backend.core.models import RobotStatus


class ExecutionError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


class ActionExecutor:
    def __init__(self, engine):
        self.engine = engine
        self.validator = PlanValidator(engine.settings)

    def execute(self, plan, crisis_cells=(), affected_ids=(), human_approved=False,
                expected_ownership=None, expected_issues=None, **trace):
        engine = self.engine
        with engine.lock:
            if engine.closed:
                raise ExecutionError("RUN_CANCELLED", "Simulation was reset")
            world = WorldSnapshot.capture(engine)
            report = self.validator.validate(plan, world, crisis_cells, affected_ids)
            if not report.valid:
                raise ExecutionError("PLAN_VALIDATION_FAILED", ",".join(i.code for i in report.issues if i.level == "ERROR"))
            if expected_ownership is not None and world.ownership_key(expected_ownership) != expected_ownership:
                raise ExecutionError("STALE_PLAN", "Task ownership or destination changed after generation")
            if (report.requires_human or report.validation_score < engine.settings.auto_execute_threshold) and not human_approved:
                raise ExecutionError("APPROVAL_REQUIRED", "Live validation requires human approval")
            if human_approved and expected_issues is not None:
                reviewed = {(i["level"], i["code"], i.get("robot_id"), i["message"]) for i in expected_issues}
                live = {(i.level, i.code, i.robot_id, i.message) for i in report.issues}
                if not live.issubset(reviewed):
                    raise ExecutionError("STALE_VALIDATION", "New risks appeared since operator review")
            # All potentially failing work happens on isolated copies. In particular,
            # charging/release call the same helpers as RobotAgent's deterministic tick.
            staged_tasks = copy(engine.task_manager)
            staged_tasks.tasks = deepcopy(engine.task_manager.tasks)
            staged_tasks.events = None
            staged_robots, released = {}, []
            for action, result in zip(plan.actions, report.action_results):
                engine.events.emit("ACTION_START", tag="EXECUTOR", step=engine.current_step,
                                   robot_id=action.robot_id, action=action.action.value, **trace)
                robot = world.robots[action.robot_id].model_copy(deep=True)
                before_task = robot.current_task
                try:
                    self._stage(action, result, robot, staged_tasks)
                except Exception as error:
                    # No live robot, task, or MessageBus has changed at this point.
                    engine.events.emit("ACTION_FAILED", tag="EXECUTOR", step=engine.current_step,
                                       robot_id=action.robot_id, action=action.action.value,
                                       error_code="ACTION_EXECUTION_FAILED", reason=str(error), **trace)
                    raise
                if before_task is not None and robot.current_task is None:
                    released.append((robot.id, before_task))
                staged_robots[robot.id] = robot
            for rid, robot in staged_robots.items():
                if robot.status == RobotStatus.CHARGING and engine.robot_manager.get_robot(rid).status != RobotStatus.CHARGING:
                    engine.measurements["charging_events"] += 1
                engine.robot_manager.get_robot(rid).__dict__.update(deepcopy(robot.__dict__))
            for original, staged in zip(engine.task_manager.tasks, staged_tasks.tasks):
                original.__dict__.update(staged.__dict__)
            for rid, tid in released:
                engine.task_manager.notify_release(rid, tid, engine.agent_manager.message_bus, "orchestrator_action")
            for action in plan.actions:
                engine.events.emit("ACTION_OK", tag="EXECUTOR", step=engine.current_step,
                                   robot_id=action.robot_id, task_id=action.task_id,
                                   action=action.action.value, **trace)
            return report

    def _stage(self, action, result, robot, tasks):
        robot.hold_steps_remaining = 0
        robot.yield_steps_remaining = 0
        robot.yield_to_robot_id = None
        if action.action == ActionType.HOLD:
            robot.hold_steps_remaining = action.hold_steps
        elif action.action == ActionType.YIELD:
            robot.yield_to_robot_id = action.yield_to_robot_id
            robot.yield_steps_remaining = self.engine.settings.yield_steps
        elif action.action == ActionType.REROUTE:
            robot.path = list(result.route)
            robot.route_waypoint = (action.waypoint.x, action.waypoint.y)
            if result.delivery_route:
                robot.delivery_path = list(result.delivery_route)
        elif action.action == ActionType.REASSIGN_TASK:
            tasks.release_task(robot, reason="orchestrator_reassignment")
        elif action.action == ActionType.GO_TO_CHARGER:
            RobotAgent(robot).start_charging({"task_manager": tasks}, charge_path=result.route)

    def fallback(self, affected_ids, reason, **trace):
        """Conservative recovery using existing A*, task release, and charging.

        Recover routes avoiding current occupancy where possible, otherwise stop.
        This guarantees containment, not recovery from disconnected warehouses.
        """
        engine = self.engine
        with engine.lock:
            if engine.closed:
                return
            engine.events.emit("FALLBACK_ACTIVATED", tag="FALLBACK", step=engine.current_step,
                               fallback=True, reason=reason, **trace)
            occupied = {(r.position.x, r.position.y) for r in engine.robot_manager.robots}
            for rid in sorted(set(affected_ids)):
                robot = engine.robot_manager.get_robot(rid)
                if robot is None or robot.orchestration_holds - {trace.get("crisis_id")}:
                    continue
                start = (robot.position.x, robot.position.y)
                task = engine.task_manager.get_task(robot.current_task)
                destination = ((task.delivery_x, task.delivery_y) if robot.carrying_item else
                               (task.pickup_x, task.pickup_y)) if task and not task.completed else None
                robot.route_waypoint = None
                charge_path = engine.charging_manager.get_charge_path(robot, engine.pathfinder)
                if robot.current_task is None and robot.status != RobotStatus.CHARGING and robot.battery <= len(charge_path) - 1 + 5 and charge_path:
                    try:
                        engine.agent_manager.get_agent(rid).start_charging(engine.context(), charge_path)
                        continue
                    except ValueError:
                        pass  # Expected energy impossibility; explicitly recorded below.
                if destination and robot.status != RobotStatus.CHARGING:
                    robot.path = engine.pathfinder.find_path(start, destination, blocked_cells=occupied - {start})
                    if not robot.carrying_item:
                        robot.delivery_path = engine.pathfinder.find_path(
                            (task.pickup_x, task.pickup_y), (task.delivery_x, task.delivery_y))
                    if robot.path:
                        robot.hold_steps_remaining = 1 if rid != min(affected_ids) else 0
                        continue
                if robot.status == RobotStatus.CHARGING:
                    # Preserve a carrying robot's task during planned charging.
                    charge_path = engine.charging_manager.get_charge_path(robot, engine.pathfinder,
                        congestion=True, loaded=robot.carrying_item)
                    if not charge_path:
                        charge_path = engine.charging_manager.get_charge_path(robot,engine.pathfinder,loaded=robot.carrying_item)
                    destination = charge_path[-1] if charge_path else None
                    if charge_path:
                        route = engine.pathfinder.find_path(start, destination, blocked_cells=occupied-{start})
                        if route and (len(route)-1)*(2 if robot.carrying_item else 1) <= robot.battery:
                            robot.path = route
                            continue
                # Step into a real passing space to break larger traffic cycles.
                # A one-cell-wide corridor has no passing space: HOLD/escalation
                # still applies there, instead of spending energy oscillating.
                others_next = {tuple(r.path[1]) for r in engine.robot_manager.robots
                               if r.id != rid and len(r.path)>1}
                warehouse = engine.pathfinder.warehouse
                # The passing space can be two or three cells away, e.g. just
                # beyond a single-width charger entrance. Still move one cell/tick.
                candidates = [(x,y) for y in range(max(0,start[1]-3),min(warehouse.height,start[1]+4))
                              for x in range(max(0,start[0]-3),min(warehouse.width,start[0]+4))
                              if 0 < abs(x-start[0])+abs(y-start[1]) <= 3
                              and (x,y) not in occupied | others_next and warehouse.is_walkable(x,y)
                              and len(warehouse.get_neighbors(x,y)) >= 3]
                candidates.sort(key=lambda cell:(abs(cell[0]-start[0])+abs(cell[1]-start[1]),cell))
                rate = 2 if robot.carrying_item else 1
                retreat = []
                for cell in candidates:
                    route = engine.pathfinder.find_path(start,cell,blocked_cells=(occupied | others_next)-{start})
                    if (route and len(route)<=4 and (len(route)-1)*rate
                            + engine.charging_manager.nearest_distance(cell,engine.pathfinder)*rate
                            + engine.charging_manager.RESERVE <= robot.battery):
                        retreat = route
                        break
                if retreat:
                    robot.path = retreat
                    occupied.add(retreat[-1])
                    continue
                robot.path = []
                robot.hold_steps_remaining = min(3, engine.settings.max_hold_steps)
                engine.events.emit("FALLBACK_HELD", tag="FALLBACK", step=engine.current_step,
                                   robot_id=rid, reason="NO_SAFE_RECOVERY_ROUTE", fallback=True, **trace)

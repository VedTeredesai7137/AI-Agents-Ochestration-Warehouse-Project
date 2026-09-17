"""Read-only route prediction. This is NOT a cloned simulation or a liveness proof."""
from copy import deepcopy
from dataclasses import dataclass

from backend.agents.plans import ActionType, ActionResult, ValidationIssue, ValidationReport
from backend.core.models import RobotStatus
from backend.simulation.pathfinder import AStarPathfinder
from backend.simulation.charging import ChargingManager


@dataclass
class WorldSnapshot:
    warehouse: object
    robots: dict
    tasks: dict
    step: int

    @classmethod
    def capture(cls, engine):
        # Caller holds engine.lock; neither validation nor inference mutates these copies.
        return cls(deepcopy(engine.pathfinder.warehouse),
                   {r.id: r.model_copy(deep=True) for r in engine.robot_manager.robots},
                   {t.id: deepcopy(t) for t in engine.task_manager.tasks}, engine.current_step)

    def destination(self, robot):
        # A planned charging stop can retain a task and a carried parcel.
        # Its immediate destination is the bay, not the task endpoint.
        if robot.status == RobotStatus.CHARGING and robot.path:
            return tuple(robot.path[-1])
        task = self.tasks.get(robot.current_task)
        if task and not task.completed:
            return ((task.delivery_x, task.delivery_y) if robot.carrying_item
                    else (task.pickup_x, task.pickup_y))
        if robot.status == RobotStatus.CHARGING and robot.path:
            return tuple(robot.path[-1])
        if robot.current_task is None and robot.path:
            return tuple(robot.path[-1])
        return None

    def ownership_key(self, ids):
        return {rid: (r.current_task, r.carrying_item, self.destination(r))
                for rid in ids if (r := self.robots.get(rid)) is not None}


# Equal weights make the score an auditable fraction of five satisfied check groups.
# Each group is the fraction of actions with no associated error. A warning deducts
# 0.20 for that action/group (once). This is execution readiness, never model certainty.
SCORE_WEIGHTS = {key: 0.2 for key in ("valid_action_ratio", "reachable_route_ratio",
                 "battery_feasibility_ratio", "task_consistency_ratio", "collision_safety_ratio")}


class PlanValidator:
    def __init__(self, settings):
        self.settings = settings

    def validate(self, plan, world, crisis_cells=(), affected_ids=()):
        pathfinder = AStarPathfinder(world.warehouse)
        charging = ChargingManager()
        issues, results, groups = [], [], {}
        cells = {tuple(cell) for cell in crisis_cells}
        actions = {a.robot_id: a for a in plan.actions}

        def issue(level, code, message, rid=None, group="valid_action_ratio"):
            issues.append(ValidationIssue(level=level, code=code, message=message, robot_id=rid))
            if rid in groups:
                groups[rid][group] = min(groups[rid][group], 0 if level == "ERROR" else 0.8)

        for action in plan.actions:
            rid = action.robot_id
            groups.setdefault(rid, dict.fromkeys(SCORE_WEIGHTS, 1.0))
            result = ActionResult(robot_id=rid, action=action.action)
            results.append(result)
            robot = world.robots.get(rid)
            if not robot:
                issue("ERROR", "INVALID_ROBOT", "Robot does not exist", rid)
                continue
            pos = (robot.position.x, robot.position.y)
            task = world.tasks.get(robot.current_task)
            owners = [t for t in world.tasks.values() if not t.completed and t.assigned_robot == rid]
            claimants = [r for r in world.robots.values() if robot.current_task is not None
                         and r.current_task == robot.current_task]
            if ((robot.current_task is not None and (not task or task.completed or task.assigned_robot != rid))
                    or len(owners) != int(robot.current_task is not None) or len(claimants) > 1
                    or (robot.carrying_item and task is None)):
                issue("ERROR", "INVALID_TASK_OWNER", "Robot/task ownership is inconsistent", rid,
                      "task_consistency_ratio")
            if not world.warehouse.is_walkable(*pos):
                issue("ERROR", "INVALID_ROBOT_POSITION", "Robot is on an obstacle", rid)
            if robot.battery < 0 or robot.battery > 100:
                issue("ERROR", "INVALID_BATTERY", "Battery is outside 0..100", rid,
                      "battery_feasibility_ratio")
            kind = action.action
            if kind == ActionType.HOLD:
                if action.hold_steps > self.settings.max_hold_steps:
                    issue("ERROR", "HOLD_OUT_OF_RANGE", "Hold exceeds configured maximum", rid)
                if action.hold_steps > self.settings.shadow_horizon:
                    issue("WARNING", "LONG_HOLD", "Hold exceeds prediction horizon", rid)
            elif kind == ActionType.YIELD:
                other = world.robots.get(action.yield_to_robot_id)
                if other is None:
                    issue("ERROR", "INVALID_YIELD_TARGET", "Yield target does not exist", rid)
                elif len(other.path) > 1 and tuple(other.path[1]) == pos:
                    issue("ERROR", "YIELD_BLOCKS_WINNER", "Holding here blocks the intended winner", rid,
                          "collision_safety_ratio")
                seen, current = {rid}, action.yield_to_robot_id
                while current in actions and actions[current].action == ActionType.YIELD:
                    if current in seen:
                        issue("ERROR", "CYCLIC_YIELD", "Yield priorities form a cycle", rid,
                              "collision_safety_ratio")
                        break
                    seen.add(current)
                    current = actions[current].yield_to_robot_id
            elif kind == ActionType.REASSIGN_TASK:
                if not task or action.task_id != robot.current_task or task.completed or task.assigned_robot != rid:
                    issue("ERROR", "INVALID_TASK_REASSIGNMENT", "Robot must own this unfinished task", rid,
                          "task_consistency_ratio")
                else:
                    issue("WARNING", "TASK_REAUCTION", "Release changes task ownership; CNP must find a new owner", rid,
                          "task_consistency_ratio")
            elif kind == ActionType.REROUTE:
                charge = charging.get_charge_path(robot, pathfinder)
                if robot.current_task is None and robot.status != RobotStatus.CHARGING and (robot.battery < 30 or robot.battery <= len(charge)-1+charging.RESERVE):
                    issue("ERROR", "CHARGE_PREEMPTION", "Battery policy would immediately preempt this reroute", rid,
                          "battery_feasibility_ratio")
                waypoint = (action.waypoint.x, action.waypoint.y)
                destination = world.destination(robot)
                if waypoint in cells:
                    issue("ERROR", "CRISIS_CELL", "Waypoint is a crisis cell", rid, "reachable_route_ratio")
                if not world.warehouse.is_walkable(*waypoint):
                    issue("ERROR", "INVALID_WAYPOINT", "Waypoint must be in bounds and walkable", rid,
                          "reachable_route_ratio")
                elif destination is None:
                    issue("ERROR", "NO_DESTINATION", "Robot has no task or routing destination", rid,
                          "task_consistency_ratio")
                else:
                    first = pathfinder.find_path(pos, waypoint)
                    second = pathfinder.find_path(waypoint, destination)
                    if not first:
                        issue("ERROR", "UNREACHABLE_WAYPOINT", "No route to waypoint", rid, "reachable_route_ratio")
                    if not second:
                        issue("ERROR", "UNREACHABLE_DESTINATION", "No route from waypoint to true destination", rid,
                              "reachable_route_ratio")
                    if first and second:
                        result.route = first + second[1:]
                        if task and not robot.carrying_item and robot.status != RobotStatus.CHARGING:
                            result.delivery_route = pathfinder.find_path(destination, (task.delivery_x, task.delivery_y))
                            if not result.delivery_route:
                                issue("ERROR", "UNREACHABLE_DELIVERY", "Delivery leg is unreachable", rid,
                                      "reachable_route_ratio")
            elif kind == ActionType.GO_TO_CHARGER:
                result.route = charging.get_charge_path(robot, pathfinder)
                if not result.route:
                    issue("ERROR", "INVALID_CHARGER_ROUTE", "No reachable real charger", rid, "reachable_route_ratio")
                if task:
                    issue("WARNING", "TASK_REAUCTION", "Charging will release task safely for CNP", rid,
                          "task_consistency_ratio")

            if result.route:
                route_cells = result.route + result.delivery_route
                if any(tuple(cell) in cells for cell in route_cells):
                    issue("ERROR", "CRISIS_CELL", "Proposed route crosses crisis cells", rid, "reachable_route_ratio")
                # Include all work and the empty return to a charger. Reassignment/drop
                # makes GO_TO_CHARGER unladen, using the actual movement energy rules.
                energy = (len(result.route) - 1) * (2 if robot.carrying_item and kind == ActionType.REROUTE else 1)
                if result.delivery_route:
                    energy += (len(result.delivery_route) - 1) * 2
                if kind == ActionType.REROUTE:
                    probe = robot.model_copy(deep=True)
                    probe.position.x, probe.position.y = route_cells[-1]
                    home = charging.get_charge_path(probe, pathfinder)
                    if not home:
                        issue("ERROR", "NO_RETURN_CHARGER", "Destination has no reachable charger", rid,
                              "battery_feasibility_ratio")
                    else:
                        energy += len(home) - 1
                result.energy_required = energy
                if energy > robot.battery:
                    issue("ERROR", "BATTERY_INFEASIBLE", "Route and charger reserve exceed battery", rid,
                          "battery_feasibility_ratio")
                elif robot.battery - energy < self.settings.battery_margin:
                    issue("WARNING", "LOW_BATTERY_MARGIN", "Little energy remains after planned work", rid,
                          "battery_feasibility_ratio")

        for rid in sorted(set(affected_ids) - set(actions)):
            issue("ERROR", "MISSING_AFFECTED_ROBOT", "Every affected robot needs an action", rid)
        seen = set()
        for action in plan.actions:
            if action.robot_id in seen:
                issue("ERROR", "DUPLICATE_ACTION", "Only one action per robot is allowed", action.robot_id)
            seen.add(action.robot_id)

        prepared = {result.robot_id: result for result in results}
        trajectories = {}
        for rid, robot in world.robots.items():
            pos = (robot.position.x, robot.position.y)
            action = actions.get(rid)
            result = prepared.get(rid)
            if action and action.action in (ActionType.REROUTE, ActionType.GO_TO_CHARGER):
                route = result.route + result.delivery_route[1:]
            else:
                route = list(robot.path)
                if (robot.current_task and not robot.carrying_item and robot.status != RobotStatus.CHARGING
                        and robot.delivery_path and route and tuple(route[-1]) == tuple(robot.delivery_path[0])):
                    route += robot.delivery_path[1:]
            delay = 0
            if action and action.action == ActionType.HOLD:
                delay = action.hold_steps
            elif action and action.action == ActionType.YIELD:
                delay = self.settings.yield_steps
            elif action and action.action == ActionType.REASSIGN_TASK:
                delay = self.settings.shadow_horizon
            elif not action:
                delay = max(robot.hold_steps_remaining, robot.yield_steps_remaining)
                if robot.orchestration_holds:
                    delay = self.settings.shadow_horizon
            route = [tuple(p) for p in route] if route else [pos]
            if route[0] != pos or not pathfinder._validate_path_integrity(route):
                route = [pos]
            trajectories[rid] = [route[min(max(0,t-delay), len(route)-1)]
                                 for t in range(self.settings.shadow_horizon+1)]
        pairs = set()
        for rid in actions:
            if rid not in trajectories:
                continue
            for other in trajectories:
                pair = tuple(sorted((rid, other)))
                if other == rid or pair in pairs:
                    continue
                pairs.add(pair)
                a, b = trajectories[rid], trajectories[other]
                for t in range(1, self.settings.shadow_horizon + 1):
                    vertex = a[t] == b[t]
                    swap = a[t] == b[t-1] and b[t] == a[t-1] and a[t] != a[t-1]
                    if vertex or swap:
                        # Immediate requested collisions are errors; later contention
                        # is a warning because step-local reservations may resolve it.
                        level = "ERROR" if t == 1 else "WARNING"
                        for who in pair:
                            if who in actions:
                                issue(level, "PATH_CONFLICT", f"Predicted conflict with robots {pair} at offset {t}",
                                      who, "collision_safety_ratio")
                        break
        for result in results:
            result.valid = not any(i.level == "ERROR" and i.robot_id in (None, result.robot_id) for i in issues)
        count = max(1, len(plan.actions))
        metrics = {key: sum(groups[a.robot_id][key] for a in plan.actions) / count for key in SCORE_WEIGHTS}
        metrics["shadow_horizon"] = self.settings.shadow_horizon
        errors = sum(i.level == "ERROR" for i in issues)
        metrics.update(errors=errors, warnings=sum(i.level == "WARNING" for i in issues))
        score = round(sum(metrics[key] * weight for key, weight in SCORE_WEIGHTS.items()), 4)
        # Missing action coverage is a schema-level failure outside per-action groups.
        if set(affected_ids) - set(actions):
            score = min(score, 0.8)
        return ValidationReport(valid=errors == 0, validation_score=score, issues=issues,
                                action_results=results, metrics=metrics)

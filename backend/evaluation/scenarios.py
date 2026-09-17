"""Scenario configuration/fault injection reuses SimulationEngine and its crisis hook."""
from enum import Enum
from random import Random


class Scenario(str, Enum):
    NORMAL = "normal"
    HIGH_WORKLOAD = "high_workload"
    DEPOT_CONGESTION = "depot_congestion"
    BATTERY_STRESS = "battery_stress"
    AISLE_COLLAPSE = "aisle_collapse"
    CRITICAL_ORDER = "critical_order"
    LLM_OFFLINE = "llm_offline"
    LLM_MALFORMED_RESPONSE = "llm_malformed_response"


class ScenarioSchedule:
    def __init__(self, engine, scenario):
        self.scenario = Scenario(scenario.lower())
        self.inject_step = 20
        self.requested_cells = None
        warehouse = engine.pathfinder.warehouse
        rng = Random(engine.seed + 10000)
        candidates = [[(x+i, y) for i in range(3)] for y in range(10, 21) for x in range(5, 43)
                      if all(warehouse.grid[y][x+i] == "." for i in range(3))]
        if candidates:
            self.requested_cells = rng.choice(candidates)
        if self.scenario == Scenario.BATTERY_STRESS:
            for robot in engine.robot_manager.robots:
                robot.battery = 45
        elif self.scenario == Scenario.DEPOT_CONGESTION:
            for task in engine.task_manager.tasks:
                task.delivery_x, task.delivery_y = 25, 24

    def before_step(self, engine):
        if engine.current_step + 1 != self.inject_step:
            return
        if self.scenario in (Scenario.AISLE_COLLAPSE, Scenario.LLM_OFFLINE, Scenario.LLM_MALFORMED_RESPONSE):
            if self.requested_cells:
                try:
                    engine.trigger_warehouse_crisis(self.requested_cells)
                except ValueError as error:
                    # Identical requested fault across modes; never crush a robot
                    # merely to force the benchmark to contain a crisis.
                    engine.events.emit("SCENARIO_FAULT_SKIPPED", tag="BENCH", step=engine.current_step,
                                       reason=str(error), requested_cells=self.requested_cells)
        elif self.scenario == Scenario.CRITICAL_ORDER:
            grid = engine.pathfinder.warehouse
            candidates = [(x,y) for y in range(1, grid.height-1) for x in range(1, grid.width-1)
                          if grid.grid[y][x] == "."]
            start, goal = candidates[0], candidates[-1]
            task = engine.task_manager.create_task(*start, *goal, priority="CRITICAL")
            engine.task_agent_manager.create_agent_for_task(task.id)

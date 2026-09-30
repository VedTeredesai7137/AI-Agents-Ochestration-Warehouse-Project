import json
import time
import pytest

from backend.core.models import RobotStatus
from backend.core.settings import Settings
from backend.agents.message_bus import MessageBus
from backend.agents.robot_orchestrator import AgentManager
from backend.agents.task_orchestrator import TaskAgentManager
from backend.agents.negotiation import NegotiationService
from backend.simulation.warehouse import Warehouse
from backend.simulation.pathfinder import AStarPathfinder
from backend.simulation.charging import ChargingManager
from backend.simulation.collision import CollisionManager
from backend.simulation.engine import SimulationEngine
from backend.state.robot_state import RobotManager
from backend.state.task_state import TaskManager


class ScriptedClient:
    model = "scripted-test-model"
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.calls = 0
        self.prompts = []
    def generate(self, prompt, schema):
        self.prompts.append(prompt)
        output = self.outputs[min(self.calls, len(self.outputs)-1)]
        self.calls += 1
        if isinstance(output, Exception):
            raise output
        if callable(output):
            return output()
        return output if isinstance(output, str) else json.dumps(output)


def action(kind="HOLD", robot_id=1, **kwargs):
    return {"robot_id":robot_id, "action":kind, "reason":"test strategy", **kwargs}


def plan(*actions):
    return {"actions":list(actions)}


def wait_for(engine, predicate, timeout=5):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        state = engine.orchestrator_runner.get_state()
        if predicate(state):
            return state
        time.sleep(0.005)
    raise AssertionError(f"Orchestrator did not reach expected state: {engine.orchestrator_runner.get_state()}")


@pytest.fixture
def engine_factory():
    engines = []
    def create(client=None, **settings):
        w = Warehouse(8,8)
        w.create_empty_grid()
        w.grid[0][0] = "C"
        robots = RobotManager()
        robots.create_robot(1,2,2)
        robots.create_robot(2,5,5)
        tasks = TaskManager()
        bus = MessageBus()
        agents = AgentManager(robots,bus)
        agents.create_agents()
        ta = TaskAgentManager(tasks,bus)
        e = SimulationEngine(robots, CollisionManager(), tasks, ChargingManager(), AStarPathfinder(w),
                             agents, ta, NegotiationService(), Settings(crisis_interval=0, **settings),
                             llm_client=client or ScriptedClient(plan(action(hold_steps=1))))
        engines.append(e)
        return e
    yield create
    for e in engines:
        e.close()


@pytest.fixture
def engine(engine_factory):
    return engine_factory()


def assign(engine, robot_id=1, pickup=(5,2), delivery=(5,3)):
    robot = engine.robot_manager.get_robot(robot_id)
    task = engine.task_manager.create_task(*pickup,*delivery)
    engine.task_agent_manager.create_agent_for_task(task.id)
    engine.task_manager.assign_task(task.id, robot_id)
    route = engine.pathfinder.find_path((robot.position.x, robot.position.y), pickup)
    engine.robot_manager.assign_task(robot_id,task.id,route)
    robot.delivery_path = engine.pathfinder.find_path(pickup,delivery)
    ta = engine.task_agent_manager.get_agent(task.id)
    ta.status = "AWARDED"
    ta.winner = robot_id
    return robot, task

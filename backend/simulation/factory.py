"""One reproducible construction path for API, tests, and evaluation."""
from random import Random

from backend.core.settings import Settings
from backend.core.events import configure_logging, logger
from backend.core.llm_config import get_llm_model
from backend.simulation.warehouse import Warehouse
from backend.state.robot_state import RobotManager
from backend.state.task_state import TaskManager
from backend.simulation.pathfinder import AStarPathfinder
from backend.simulation.collision import CollisionManager
from backend.simulation.charging import ChargingManager
from backend.simulation.engine import SimulationEngine
from backend.agents.robot_orchestrator import AgentManager
from backend.agents.task_orchestrator import TaskAgentManager
from backend.agents.message_bus import MessageBus
from backend.agents.negotiation import NegotiationService


def create_simulation(seed=None, settings=None, llm_client=None, lock=None, task_count=120):
    settings = settings or Settings.from_env()
    seed = settings.simulation_seed if seed is None else seed
    rng = Random(seed)
    warehouse = Warehouse(50, 30, rng=rng)
    warehouse.generate()
    robots = RobotManager()
    robots.spawn_from_warehouse(warehouse)
    tasks = TaskManager()
    walkable = [(x, y) for y in range(1, warehouse.height - 1) for x in range(1, warehouse.width - 1)
                if warehouse.grid[y][x] == "."]
    for _ in range(task_count):
        px, py = rng.choice(walkable)
        dx, dy = rng.choice(walkable)
        tasks.create_task(px, py, dx, dy)
    pathfinder = AStarPathfinder(warehouse)
    collision = CollisionManager()
    charging = ChargingManager()
    bus = MessageBus()
    agents = AgentManager(robots, bus)
    agents.create_agents()
    task_agents = TaskAgentManager(tasks, bus)
    task_agents.create_agents_for_existing_tasks()
    negotiation = NegotiationService()
    engine = SimulationEngine(robots, collision, tasks, charging, pathfinder, agents, task_agents, negotiation,
                              settings=settings, seed=seed, rng=rng, lock=lock, llm_client=llm_client)
    configure_logging()
    logger.info("[BOOT] Warehouse Swarm backend starting run_id=%s seed=%s llm_provider=%s "
                "orchestrator_enabled=%s validator_enabled=true max_regenerations=%s auto_execute_threshold=%s",
                engine.run_id, seed, get_llm_model(), settings.orchestrator_enabled,
                settings.max_regenerations, settings.auto_execute_threshold)
    return engine

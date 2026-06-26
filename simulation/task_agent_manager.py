"""
TaskAgentManager — Creates and orchestrates TaskAgent instances.

Responsibilities:
  - Create a TaskAgent for every task (at startup and dynamically).
  - Tick all task agents each simulation step.
  - Remove completed task agents.
  - Provide introspection data for the API.
"""

from simulation.task_agent import TaskAgent, TaskAgentStatus


class TaskAgentManager:
    """
    Manages the lifecycle of all TaskAgent instances.

    Parameters
    ----------
    task_manager : TaskManager
        Source of Task objects.
    message_bus : MessageBus
        Shared message bus for agent communication.
    """

    def __init__(self, task_manager, message_bus):
        self.task_manager = task_manager
        self.message_bus = message_bus
        self.task_agents: list[TaskAgent] = []
        self._agent_map: dict[int, TaskAgent] = {}  # task_id -> TaskAgent
        self.latest_logs = []

    def create_agents_for_existing_tasks(self):
        """Create a TaskAgent for every task currently in the TaskManager."""
        for task in self.task_manager.tasks:
            if task.id not in self._agent_map:
                self._create_agent(task)

    def create_agent_for_task(self, task_id: int):
        """Create a TaskAgent for a newly created task."""
        task = self.task_manager.get_task(task_id)
        if task is not None and task_id not in self._agent_map:
            self._create_agent(task)

    def _create_agent(self, task):
        """Internal: instantiate and register a TaskAgent."""
        agent = TaskAgent(task, self.message_bus)
        self.task_agents.append(agent)
        self._agent_map[task.id] = agent

    def tick_all(self, robot_manager, pathfinder):
        """
        Run one lifecycle tick for every active task agent.

        Parameters
        ----------
        robot_manager : RobotManager
            For looking up robots during contract award.
        pathfinder : AStarPathfinder
            For computing paths during contract award.
        """
        for agent in self.task_agents:
            if agent.status != TaskAgentStatus.COMPLETED:
                log = agent.tick(
                    task_manager=self.task_manager,
                    robot_manager=robot_manager,
                    pathfinder=pathfinder
                )
                if log:
                    self.latest_logs.append(log)
                    print(f"DEBUG: Backend generated auction log for Task {log['task_id']}")

    def get_agent(self, task_id: int):
        """Return the TaskAgent for the given task_id, or None."""
        return self._agent_map.get(task_id)

    def get_all_status(self):
        """Return introspection data for all task agents."""
        return [
            {
                "task_id": agent.task.id,
                "status": agent.status,
                "winner": agent.winner,
                "proposal_count": agent.proposal_count,
            }
            for agent in self.task_agents
        ]

    def __len__(self):
        return len(self.task_agents)

    def __repr__(self):
        return f"TaskAgentManager(task_agents={len(self.task_agents)})"

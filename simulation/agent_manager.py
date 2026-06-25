"""
AgentManager — Maintains and orchestrates all RobotAgent instances.

Responsibilities:
  - Create one RobotAgent per Robot (after RobotManager has spawned them).
  - Provide lookup by robot_id.
  - Run the per-step tick cycle for every agent.
"""

from simulation.robot_agent import RobotAgent


class AgentManager:
    """
    Manages the collection of RobotAgent instances.

    The AgentManager does NOT own the Robot objects themselves —
    those remain under RobotManager.  It holds *agents* that wrap
    and control those robots.

    Parameters
    ----------
    robot_manager : RobotManager
        Used to access the list of Robot instances.
    """

    def __init__(self, robot_manager):
        self.robot_manager = robot_manager
        self.agents = []
        self._agent_map = {}  # robot_id -> RobotAgent

    # ------------------------------------------------------------------
    #  Creation
    # ------------------------------------------------------------------

    def create_agents(self):
        """
        Create one RobotAgent for every Robot currently held by
        the RobotManager.  Safe to call only once after spawning.
        """
        self.agents = []
        self._agent_map = {}

        for robot in self.robot_manager.robots:
            agent = RobotAgent(robot)
            self.agents.append(agent)
            self._agent_map[robot.id] = agent

    # ------------------------------------------------------------------
    #  Lookup
    # ------------------------------------------------------------------

    def get_agent(self, robot_id):
        """
        Return the RobotAgent for the given robot_id, or None.
        """
        return self._agent_map.get(robot_id)

    def get_agent_for_robot(self, robot):
        """
        Return the RobotAgent wrapping the given Robot instance.
        """
        return self._agent_map.get(robot.id)

    # ------------------------------------------------------------------
    #  Orchestration
    # ------------------------------------------------------------------

    def tick_all(self, **context):
        """
        Run one perceive → decide → act cycle for every agent.

        Parameters
        ----------
        context : dict
            Dependencies forwarded to each agent's ``tick()`` call:
              - task_manager
              - charging_manager
              - pathfinder
              - collision_manager
        """
        for agent in self.agents:
            agent.tick(**context)

    # ------------------------------------------------------------------
    #  Introspection
    # ------------------------------------------------------------------

    def get_all_beliefs(self):
        """
        Return a dict mapping robot_id -> beliefs snapshot.
        Useful for debugging and future dashboard enhancements.
        """
        return {
            agent.robot.id: dict(agent.beliefs)
            for agent in self.agents
        }

    def get_all_goals(self):
        """
        Return a dict mapping robot_id -> current goal string.
        """
        return {
            agent.robot.id: agent.goal
            for agent in self.agents
        }

    def __len__(self):
        return len(self.agents)

    def __repr__(self):
        return (
            f"AgentManager(agents={len(self.agents)})"
        )

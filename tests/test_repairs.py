import contextlib
import io
import threading
import time
import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from unittest.mock import Mock, patch
from backend.core.models import Robot, Position, RobotStatus
from backend.agents.robot import RobotAgent
from backend.agents.message_bus import MessageBus, MessageType
from backend.simulation.warehouse import Warehouse
from backend.simulation.pathfinder import AStarPathfinder
from backend.simulation.charging import ChargingManager
from backend.simulation.collision import CollisionManager
from backend.state.task_state import TaskManager
from backend.agents.orchestrator_graph import OrchestratorRunner
from backend.core.events import EventRecorder, logger
from backend.core.settings import Settings
from backend.simulation.engine import SimulationEngine
from backend.state.robot_state import RobotManager
from backend.agents.robot_orchestrator import AgentManager
from backend.agents.task_orchestrator import TaskAgentManager
from conftest import ScriptedClient, action, plan
import logging


class Repairs(unittest.TestCase):
    def setUp(self):
        output = contextlib.redirect_stdout(io.StringIO())
        output.__enter__()
        self.addCleanup(output.__exit__, None, None, None)
        self.w = Warehouse(50, 4)
        self.w.create_empty_grid()
        self.w.grid[0][49] = "C"
        self.r = Robot(id=1, battery=50, position=Position(x=0, y=0), status=RobotStatus.IDLE)
        self.agent = RobotAgent(self.r, MessageBus())
        self.ctx = dict(warehouse=self.w, pathfinder=AStarPathfinder(self.w),
                        charging_manager=ChargingManager(), collision_manager=CollisionManager(),
                        task_manager=TaskManager())

    def runner(self, client):
        robots=RobotManager()
        robots.robots=[self.r]
        agents=AgentManager(robots,self.agent.message_bus)
        agents.create_agents()
        task_agents=TaskAgentManager(self.ctx["task_manager"],self.agent.message_bus)
        engine=SimulationEngine(robots,self.ctx["collision_manager"],self.ctx["task_manager"],
                                self.ctx["charging_manager"],self.ctx["pathfinder"],agents,task_agents,
                                settings=Settings(crisis_interval=0),llm_client=client)
        self.addCleanup(engine.close)
        return engine.orchestrator_runner

    def test_graph_logging_on_windows_encoding(self):
        raw=io.BytesIO()
        console=io.TextIOWrapper(raw,encoding="cp1252")
        handler=logging.StreamHandler(console)
        logger.addHandler(handler)
        previous=logger.level
        logger.setLevel(logging.INFO)
        try:
            EventRecorder("test").emit("ORCH_START",reason="\U0001f9e0 Test")
            console.flush()
            self.assertIn(b"ORCH_START",raw.getvalue())
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous)

    def test_route_reserve_and_actual_station(self):
        self.agent.perceive(ctx=self.ctx)
        self.assertTrue(self.agent.beliefs["battery_low"])
        self.agent.act(self.agent.decide(), **self.ctx)
        self.assertEqual(self.r.path[-1], (49, 0))
        self.r.path = []
        self.agent.perceive(ctx=self.ctx)
        self.assertFalse(self.agent.beliefs["at_charger"])
        self.assertEqual(self.agent.decide(), "need_charge")
        self.agent.act("charge", **self.ctx)
        self.assertEqual(self.r.battery, 50)

    def test_empty_energy_and_loaded_cost(self):
        self.r.path = [(0, 0), (1, 0), (2, 0)]
        self.r.carrying_item = True
        self.r.battery = 1
        self.agent.act("move", **self.ctx)
        self.assertEqual(self.r.position.x, 0)
        self.assertEqual(self.r.battery, 1)
        self.r.battery = 2
        self.agent.act("move", **self.ctx)
        self.assertEqual(self.r.battery, 0)
        self.assertEqual(self.r.position.x, 1)

    def test_charge_cap_and_task_release(self):
        task = self.ctx["task_manager"].create_task(0, 0, 1, 0)
        task = self.ctx["task_manager"].tasks[-1]
        self.ctx["task_manager"].assign_task(task.id,self.r.id)
        self.r.current_task = task.id
        self.r.carrying_item = True
        self.r.delivery_path = [(0, 0), (1, 0)]
        self.agent.act("need_charge", **self.ctx)
        self.assertFalse(self.r.carrying_item)
        self.assertIsNone(self.r.current_task)
        self.assertEqual(self.r.delivery_path, [])
        self.r.position = Position(x=49, y=0)
        self.r.battery = 99
        self.agent.act("charge", **self.ctx)
        self.assertEqual(self.r.battery, 100)

    def test_unreachable_charger(self):
        self.w.grid[0][48] = self.w.grid[1][49] = "S"
        self.agent.act("need_charge", **self.ctx)
        self.assertEqual(self.r.path, [])
        self.agent.act("charge", **self.ctx)
        self.assertEqual(self.r.battery, 50)

    def test_message_history_survives_consumption(self):
        bus = MessageBus()
        for name in ("a", "b", "c"):
            bus.subscribe(name)
        msg = bus.create_message("a", "ALL", MessageType.CFP)
        bus.broadcast(msg)
        self.assertEqual(bus.get_messages("a"), [])
        self.assertEqual(bus.get_messages("b"), [msg])
        self.assertEqual(bus.get_messages("c"), [msg])
        self.assertEqual(bus.history()["messages"][0]["recipient"], "ALL")
        for _ in range(1100):
            bus.publish(bus.create_message("a", "b", MessageType.PROPOSAL))
        self.assertEqual(len(bus.history()["messages"]), 1000)
        self.assertNotEqual(bus.session_id, MessageBus().session_id)

    def wait_for(self, runner, predicate):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = runner.get_state()
            if predicate(state):
                return state
            time.sleep(.01)
        self.fail(str(runner.get_state()))

    def test_real_graph_reject_approve_repeat_and_stale_plan(self):
        client=ScriptedClient(plan(action(hold_steps=8)),plan(action(hold_steps=9)),
                              plan(action(hold_steps=8)),plan(action(hold_steps=9)))
        runner=self.runner(client)
        for crisis in range(2):
            runner.invoke_async([(3,2)],[1])
            old=self.wait_for(runner,lambda s:s["waiting_for_human"])["plan_id"]
            self.assertTrue(runner.human_override(False,old)["success"])
            state=self.wait_for(runner,lambda s:s["waiting_for_human"] and s["rejection_count"]==1)
            self.assertFalse(runner.human_override(True,old)["success"])
            self.assertTrue(runner.human_override(True,state["plan_id"])["success"])
            final=self.wait_for(runner,lambda s:not s["active"])
            self.assertEqual(final["executed_actions"],1)
        self.assertEqual(client.calls,4)

    def test_high_validation_score_auto_approval(self):
        runner=self.runner(ScriptedClient(plan(action(hold_steps=1))))
        runner.invoke_async([(3,2)],[1])
        final=self.wait_for(runner,lambda s:not s["active"])
        self.assertEqual(final["executed_actions"],1)
        self.assertFalse(final["waiting_for_human"])

    def test_deadlock_preserves_charge_status(self):
        self.r.status = RobotStatus.CHARGING
        self.r.path = [(0, 0), (1, 0), (2, 0)]
        self.agent.blocked_counter = 2
        self.ctx["collision_manager"] = Mock(reserve_cell=Mock(return_value=(False, 2)))
        service = Mock()
        service.resolve_deadlock.side_effect = lambda *args: args[-1](1, "test")
        self.ctx["negotiation_service"] = service
        self.agent.act("move", **self.ctx)
        self.assertEqual(self.r.status, RobotStatus.CHARGING)

    def test_reset_ignores_inflight_result(self):
        entered,release=threading.Event(),threading.Event()
        def response():
            entered.set()
            release.wait(2)
            return '{"actions":[{"robot_id":1,"action":"HOLD","hold_steps":8,"reason":"delayed"}]}'
        runner=self.runner(ScriptedClient(response))
        runner.invoke_async([(3,2)],[1])
        self.assertTrue(entered.wait(2))
        runner.reset()
        release.set()
        time.sleep(.1)
        self.assertFalse(runner.get_state()["active"])
        self.assertFalse(runner.get_state()["waiting_for_human"])


if __name__ == "__main__":
    with contextlib.redirect_stdout(io.StringIO()):
        unittest.main()

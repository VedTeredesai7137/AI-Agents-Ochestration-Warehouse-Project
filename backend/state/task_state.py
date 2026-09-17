from dataclasses import dataclass

from backend.core.models import RobotStatus
from backend.agents.message_bus import MessageType
from backend.core.events import logger


@dataclass
class Task:
    id: int

    pickup_x: int
    pickup_y: int

    delivery_x: int
    delivery_y: int

    priority: str = "NORMAL"
    completed: bool = False

    assigned_robot: int | None = None
    created_step: int = 0
    assigned_step: int | None = None
    completed_step: int | None = None
    reauction_count: int = 0
    delivered_by: int | None = None
    delivery_position: tuple[int, int] | None = None


class TaskManager:

    def __init__(self):
        self.tasks = []
        self.next_task_id = 1
        self.current_step = 0
        self.events = None
        self.negotiation_service = None

    def create_task(
        self,
        pickup_x,
        pickup_y,
        delivery_x,
        delivery_y,
        priority="NORMAL"
    ):

        task = Task(
            id=self.next_task_id,
            pickup_x=pickup_x,
            pickup_y=pickup_y,
            delivery_x=delivery_x,
            delivery_y=delivery_y,
            created_step=self.current_step,
            priority=priority
        )

        self.tasks.append(task)

        self.next_task_id += 1

        logger.debug("[CNP] created task_id=%s", task.id)
        return task

    def get_task(self, task_id):

        for task in self.tasks:

            if task.id == task_id:
                return task

        return None

    def get_unassigned_tasks(self):

        return [
            task
            for task in self.tasks
            if task.assigned_robot is None
            and not task.completed
        ]

    def assign_task(
        self,
        task_id,
        robot_id
    ):

        task = self.get_task(task_id)

        if not task or task.completed or task.assigned_robot not in (None, robot_id):
            raise ValueError("Task cannot be awarded in its current state")
        if any(t.id != task_id and not t.completed and t.assigned_robot == robot_id for t in self.tasks):
            raise ValueError("Robot already owns a task")
        task.assigned_robot = robot_id
        task.assigned_step = self.current_step

    def unassign_task(
        self,
        task_id
    ):

        task = self.get_task(task_id)

        if task and not task.completed and task.assigned_robot is not None:
            task.assigned_robot = None
            task.reauction_count += 1

    def complete_task(
        self,
        task_id,
        robot=None,
    ):

        task = self.get_task(task_id)

        if not task or task.completed or task.assigned_robot is None:
            raise ValueError("Only an owned unfinished task can complete")
        if robot is not None:
            position = (robot.position.x,robot.position.y)
            if (robot.current_task != task_id or task.assigned_robot != robot.id
                    or not robot.carrying_item or position != (task.delivery_x,task.delivery_y)):
                raise ValueError("Delivery requires the owning robot and parcel at the delivery cell")
            task.delivered_by = robot.id
            task.delivery_position = position
        task.completed = True
        task.completed_step = self.current_step
        task.assigned_robot = None
        if self.events:
            self.events.emit("TASK_COMPLETED", tag="CNP", step=self.current_step, task_id=task_id)

    def release_task(self, robot, message_bus=None, reason="released"):
        """Atomically release ownership. A carried parcel becomes a pickup here.

        Caller holds the simulation lock. TaskAgent observes unassignment and
        returns to WAITING, then broadcasts a fresh CFP on its following tick.
        """
        task = self.get_task(robot.current_task)
        if not task or task.completed or task.assigned_robot != robot.id:
            raise ValueError("Cannot release a task the robot does not own")
        if robot.carrying_item:
            task.pickup_x, task.pickup_y = robot.position.x, robot.position.y
        self.unassign_task(task.id)
        robot.current_task = None
        robot.carrying_item = False
        robot.path = []
        robot.delivery_path = []
        robot.route_waypoint = None
        robot.status = RobotStatus.IDLE
        self.notify_release(robot.id, task.id, message_bus, reason)
        return task.id

    def notify_release(self, robot_id, task_id, message_bus, reason):
        if message_bus:
            message_bus.broadcast(message_bus.create_message(
                sender=f"robot_{robot_id}", recipient="ALL", message_type=MessageType.TASK_RELEASED,
                payload={"robot_id": robot_id, "task_id": task_id, "reason": reason}))
        if self.events:
            self.events.emit("TASK_REAUCTIONED", tag="CNP", step=self.current_step,
                             robot_id=robot_id, task_id=task_id, reason=reason)
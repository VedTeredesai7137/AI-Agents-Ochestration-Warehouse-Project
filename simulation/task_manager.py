from dataclasses import dataclass


@dataclass
class Task:
    id: int
    pickup_x: int
    pickup_y: int
    completed: bool = False
    assigned_robot: int | None = None


class TaskManager:

    def __init__(self):
        self.tasks = []
        self.next_task_id = 1

    def create_task(self, pickup_x, pickup_y):
        task = Task(
            id=self.next_task_id,
            pickup_x=pickup_x,
            pickup_y=pickup_y
        )

        self.tasks.append(task)
        self.next_task_id += 1

        print(f"NEW TASK -> Task {task.id} ({pickup_x},{pickup_y})")

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

    def assign_task(self, task_id, robot_id):

        task = self.get_task(task_id)

        if task:
            task.assigned_robot = robot_id

    def unassign_task(self, task_id):

        task = self.get_task(task_id)

        if task:
            task.assigned_robot = None

    def complete_task(self, task_id):

        task = self.get_task(task_id)

        if task:
            task.completed = True
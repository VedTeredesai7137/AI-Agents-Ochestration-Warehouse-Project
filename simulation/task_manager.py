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

    def create_task(
        self,
        task_id,
        pickup_x,
        pickup_y
    ):

        task = Task(
            id=task_id,
            pickup_x=pickup_x,
            pickup_y=pickup_y
        )

        self.tasks.append(task)

    def display_tasks(self):

        for task in self.tasks:

            print(
                f"Task {task.id}"
                f" -> "
                f"({task.pickup_x},"
                f"{task.pickup_y})"
            )

    def get_unassigned_tasks(self):

        return [

            task

            for task in self.tasks

            if task.assigned_robot is None
        ]

    def assign_task(
        self,
        task_id,
        robot_id
    ):

        for task in self.tasks:

            if task.id == task_id:

                task.assigned_robot = (
                    robot_id
                )

                return task

        return None
from enum import Enum

from pydantic import (
    BaseModel,
    Field
)


class Position(BaseModel):

    x: int
    y: int


class RobotStatus(str, Enum):

    IDLE = "IDLE"

    MOVING = "MOVING"

    WAITING = "WAITING"

    PICKING = "PICKING"

    DELIVERING = "DELIVERING"

    CHARGING = "CHARGING"


class Robot(BaseModel):

    id: int

    battery: float

    position: Position

    status: RobotStatus

    current_task: int | None = None

    path: list = Field(
        default_factory=list
    )

    def __str__(self):

        return (
            f"Robot("
            f"id={self.id}, "
            f"position="
            f"({self.position.x},"
            f"{self.position.y}), "
            f"battery={self.battery:.1f}, "
            f"task={self.current_task}, "
            f"status={self.status.value}"
            f")"
        )
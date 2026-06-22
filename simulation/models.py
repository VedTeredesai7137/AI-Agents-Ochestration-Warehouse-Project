from enum import Enum
from pydantic import BaseModel


class Position(BaseModel):
    x: int
    y: int


class RobotStatus(str, Enum):
    IDLE = "IDLE"
    MOVING = "MOVING"
    PICKING = "PICKING"
    DELIVERING = "DELIVERING"
    CHARGING = "CHARGING"


class Robot(BaseModel):
    id: int
    battery: float
    position: Position
    status: RobotStatus

    path: list = []

    def __str__(self):

        return (
            f"Robot("
            f"id={self.id}, "
            f"position=({self.position.x},{self.position.y}), "
            f"battery={self.battery}, "
            f"status={self.status.value}"
            f")"
        )
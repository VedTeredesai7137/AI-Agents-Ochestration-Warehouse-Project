from pydantic import BaseModel


class Position(BaseModel):
    x: int
    y: int


class Package(BaseModel):
    id: int
    pickup_location: Position
    drop_location: Position
    priority: int


class Robot(BaseModel):
    id: int
    battery: float
    position: Position
    status: str
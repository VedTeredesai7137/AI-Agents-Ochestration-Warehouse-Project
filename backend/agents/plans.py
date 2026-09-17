"""Untrusted model output crosses this strict schema before any world validation."""
from enum import Enum
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, ValidationError, model_validator

from backend.core.models import Position


class ActionType(str, Enum):
    HOLD = "HOLD"
    YIELD = "YIELD"
    REROUTE = "REROUTE"
    REASSIGN_TASK = "REASSIGN_TASK"
    GO_TO_CHARGER = "GO_TO_CHARGER"


class Waypoint(Position):
    model_config = ConfigDict(extra="forbid")
    x: StrictInt
    y: StrictInt


class RobotAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    robot_id: StrictInt = Field(ge=1)
    action: ActionType
    waypoint: Waypoint | None = None
    task_id: StrictInt | None = Field(default=None, ge=1)
    yield_to_robot_id: StrictInt | None = Field(default=None, ge=1)
    hold_steps: StrictInt | None = Field(default=None, ge=1)
    reason: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def action_parameters(self):
        required = {
            ActionType.HOLD: "hold_steps", ActionType.YIELD: "yield_to_robot_id",
            ActionType.REROUTE: "waypoint", ActionType.REASSIGN_TASK: "task_id",
            ActionType.GO_TO_CHARGER: None,
        }[self.action]
        for field in ("waypoint", "task_id", "yield_to_robot_id", "hold_steps"):
            if field == required and getattr(self, field) is None:
                raise ValueError(f"{self.action.value} requires {field}")
            if field != required and getattr(self, field) is not None:
                raise ValueError(f"{self.action.value} does not accept {field}")
        if self.yield_to_robot_id == self.robot_id:
            raise ValueError("A robot cannot yield to itself")
        if not self.reason.strip():
            raise ValueError("reason cannot be blank")
        return self


class CrisisPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    actions: list[RobotAction] = Field(min_length=1, max_length=100)
    rationale: str | None = Field(default=None, max_length=4000)

    def strategy_key(self):
        """Reasons and action order cannot disguise the same rejected strategy."""
        return json.dumps(sorted((a.model_dump(mode="json", exclude={"reason"}, exclude_none=True)
                                  for a in self.actions), key=lambda a: a["robot_id"]), sort_keys=True)


class PlanError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def parse_plan(raw: str) -> CrisisPlan:
    if not isinstance(raw, str):
        raise PlanError("LLM_INVALID_JSON", "Model response must be JSON text")
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*\n?", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"Duplicate JSON field: {key}")
            result[key] = value
        return result
    try:
        data = json.loads(text, object_pairs_hook=unique_keys)
    except (json.JSONDecodeError, ValueError) as error:
        raise PlanError("LLM_INVALID_JSON", str(error)) from error
    try:
        return CrisisPlan.model_validate(data)
    except ValidationError as error:
        raise PlanError("LLM_SCHEMA_ERROR", str(error)) from error


class ValidationIssue(BaseModel):
    level: Literal["ERROR", "WARNING"]
    code: str
    message: str
    robot_id: int | None = None


class ActionResult(BaseModel):
    robot_id: int
    action: ActionType
    valid: bool = True
    route: list[tuple[int, int]] = Field(default_factory=list)
    delivery_route: list[tuple[int, int]] = Field(default_factory=list)
    energy_required: float = 0


class ValidationReport(BaseModel):
    valid: bool
    validation_score: float
    issues: list[ValidationIssue] = Field(default_factory=list)
    action_results: list[ActionResult] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)

    @property
    def requires_human(self):
        return any(issue.level == "WARNING" for issue in self.issues)


def generation_schema():
    """Expose action-dependent required fields to Ollama's JSON grammar too.

    Pydantic's after-validator enforces these at runtime but does not automatically
    express them in JSON Schema; an optional hold_steps let local models omit it.
    """
    schema = CrisisPlan.model_json_schema()
    properties = schema["$defs"]["RobotAction"]["properties"]
    alternatives = []
    for kind, parameter in (("HOLD","hold_steps"),("YIELD","yield_to_robot_id"),
                            ("REROUTE","waypoint"),("REASSIGN_TASK","task_id"),("GO_TO_CHARGER",None)):
        fields = {"robot_id":properties["robot_id"],"action":{"const":kind},"reason":properties["reason"]}
        if parameter:
            fields[parameter] = next(p for p in properties[parameter]["anyOf"] if p.get("type") != "null")
        alternatives.append({"type":"object","properties":fields,"required":list(fields),"additionalProperties":False})
    schema["$defs"]["RobotAction"] = {"oneOf":alternatives}
    return schema

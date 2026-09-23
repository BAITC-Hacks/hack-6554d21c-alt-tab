from typing import Any, Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator


class TurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=4000)

    @field_validator("text")
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError("Empty utterance")
        return value.strip()


class ScenarioChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario_id: str
    confidence: float = Field(ge=0, le=1)


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenarios: list[ScenarioChoice] = Field(min_length=1, max_length=10)
    alternatives: list[ScenarioChoice] = Field(max_length=3)
    language: Literal["ru", "kk", "mixed"]
    response_language: Literal["ru", "kk"]
    reason: str = Field(min_length=1, max_length=1000)
    slots: dict[str, Any]
    is_continuation: bool


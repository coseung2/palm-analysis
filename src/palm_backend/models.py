import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

LINE_NAMES = ("life", "head", "heart", "fate")
DISCLAIMER = (
    "손금 해석과 전생 이야기는 오락용 창작이며, 건강·수명·미래에 대한 사실 판단이 아닙니다."
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateSession(StrictModel):
    external_processing_consent: bool = False


class BoothConfig(StrictModel):
    version: int = Field(default=1, ge=1)
    title: str = Field(default="오늘의 손금", min_length=1, max_length=80)
    story_theme: Literal["river", "forest", "stars"] = "river"
    scan_step_ms: int = Field(default=1600, ge=400, le=5000)
    vision_step_ms: int = Field(default=1900, ge=600, le=5000)


class ConfigUpdate(BoothConfig):
    pass


class TracePoint(StrictModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class LineObservation(StrictModel):
    name: Literal["life", "head", "heart", "fate"]
    visibility: Literal["visible", "unclear", "not_visible"]
    trait: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    trace: list[TracePoint] = Field(default_factory=list)

    @field_validator('trace', mode='before')
    @classmethod
    def valid_trace(cls, value):
        if not isinstance(value, list) or not 2 <= len(value) <= 24:
            return []
        for point in value:
            data = point.model_dump() if isinstance(point, TracePoint) else point
            if not isinstance(data, dict) or set(data) != {'x', 'y'}:
                return []
            if not all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and 0 <= v <= 1 for v in data.values()):
                return []
        return value

    @model_validator(mode='after')
    def withhold_uncertain_trace(self):
        if self.visibility != 'visible':
            self.trace = []
        return self


class Observation(StrictModel):
    hand: Literal["left", "right", "unknown"]
    quality: Literal["usable", "retake"]
    retake_reason: str = Field(max_length=300)
    lines: list[LineObservation] = Field(min_length=4, max_length=4)

    @model_validator(mode="after")
    def check_lines(self):
        if {line.name for line in self.lines} != set(LINE_NAMES):
            raise ValueError("Exactly one observation per palm line is required")
        if self.quality == "retake" and not self.retake_reason.strip():
            raise ValueError("A retake must explain how to improve the photo")
        return self


class LineReading(StrictModel):
    name: Literal["life", "head", "heart", "fate"]
    reading: str = Field(min_length=1, max_length=500)


class Story(StrictModel):
    readings: list[LineReading] = Field(min_length=4, max_length=4)
    visions: list[str] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def check_content(self):
        if {line.name for line in self.readings} != set(LINE_NAMES):
            raise ValueError("Exactly one reading per palm line is required")
        if any(not vision.strip() or len(vision) > 200 for vision in self.visions):
            raise ValueError("Each vision must contain 1–200 characters")
        return self


class ResultLine(LineObservation):
    reading: str


class AnalysisResult(StrictModel):
    mode: Literal["demo", "claude", "ocx"]
    is_demo: bool
    hand: Literal["left", "right", "unknown"]
    lines: list[ResultLine]
    visions: list[str]
    disclaimer: str = DISCLAIMER
    config_version: int


class PublicError(StrictModel):
    code: str
    message: str
    retryable: bool = False


class SessionView(StrictModel):
    id: str
    status: Literal["awaiting_image", "analyzing", "completed", "failed", "cancelled"]
    created_at: float
    expires_at: float
    external_processing_consent: bool
    attempts: int
    config: BoothConfig
    result: AnalysisResult | None = None
    error: PublicError | None = None


class SessionCreated(SessionView):
    access_token: str

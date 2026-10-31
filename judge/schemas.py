from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Language = Literal["python", "cpp"]


class UserIn(BaseModel):
    username: str = Field(min_length=3, max_length=50, pattern=r"^[A-Za-z0-9_]+$")
    password: str = Field(min_length=8, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CaseIn(BaseModel):
    input: str
    output: str
    is_sample: bool = False


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    score: int = Field(ge=0)
    cases: list[CaseIn] = Field(min_length=1)


class TestsIn(BaseModel):
    groups: list[GroupIn] = Field(min_length=1)


class ProblemIn(TestsIn):
    title: str = Field(min_length=1, max_length=200)
    statement: str = Field(min_length=1)
    time_limit_ms: int = Field(ge=100, le=15000)
    memory_limit_mb: int = Field(ge=16, le=1024)
    checker: Literal["exact", "token", "float", "custom"] = "token"
    float_tolerance: float = Field(default=1e-6, gt=0)
    checker_language: Language | None = None
    checker_source: str | None = None
    stop_on_first_fail: bool = True

    @model_validator(mode="after")
    def custom_checker_needs_source(self):
        if self.checker == "custom" and not (self.checker_language and self.checker_source):
            raise ValueError("custom checker needs checker_language and checker_source")
        return self


class ProblemSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    time_limit_ms: int
    memory_limit_mb: int


class SampleOut(BaseModel):
    input: str
    output: str


class ProblemOut(ProblemSummary):
    statement: str
    max_score: int
    samples: list[SampleOut]


class SubmissionIn(BaseModel):
    problem_id: int
    language: Language
    source_code: str = Field(min_length=1)
    contest_id: int | None = None


class SubmissionCreated(BaseModel):
    id: int
    status: str


class CaseResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    test_number: int
    group_name: str
    verdict: str
    time_ms: int
    memory_kb: int
    exit_code: int | None
    signal: int | None


class SubmissionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    problem_id: int
    contest_id: int | None
    language: str
    status: str
    verdict: str | None
    score: int
    time_ms: int | None
    memory_kb: int | None
    compile_output: str | None
    results: list[CaseResultOut]


class RejudgeOut(BaseModel):
    queued: int


class ContestIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    start_time: datetime
    end_time: datetime
    style: Literal["icpc", "score"] = "icpc"
    penalty_minutes: int = Field(default=20, ge=0)
    problem_ids: list[int] = Field(min_length=1)

    @field_validator("start_time", "end_time")
    @classmethod
    def to_naive_utc(cls, value):
        if value.tzinfo:
            return value.astimezone(UTC).replace(tzinfo=None)
        return value

    @model_validator(mode="after")
    def end_after_start(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class ContestOut(BaseModel):
    id: int
    name: str
    start_time: datetime
    end_time: datetime
    style: str
    penalty_minutes: int
    problem_ids: list[int]

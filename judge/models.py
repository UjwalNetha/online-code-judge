from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from judge.db import Base

ACCEPTED = "Accepted"
WRONG_ANSWER = "Wrong Answer"
TIME_LIMIT = "Time Limit Exceeded"
MEMORY_LIMIT = "Memory Limit Exceeded"
OUTPUT_LIMIT = "Output Limit Exceeded"
RUNTIME_ERROR = "Runtime Error"
COMPILATION_ERROR = "Compilation Error"
INTERNAL_ERROR = "Internal Error"

QUEUED = "queued"
RUNNING = "running"
DONE = "done"


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True)
    password_hash: Mapped[str] = mapped_column(String(200))
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    last_claimed_at: Mapped[datetime | None] = mapped_column(DateTime)


class Problem(Base):
    __tablename__ = "problems"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    statement: Mapped[str] = mapped_column(Text)
    time_limit_ms: Mapped[int] = mapped_column(Integer)
    memory_limit_mb: Mapped[int] = mapped_column(Integer)
    checker: Mapped[str] = mapped_column(String(20), default="token")
    float_tolerance: Mapped[float] = mapped_column(Float, default=1e-6)
    checker_language: Mapped[str | None] = mapped_column(String(20))
    checker_source: Mapped[str | None] = mapped_column(Text)
    stop_on_first_fail: Mapped[bool] = mapped_column(Boolean, default=True)

    groups: Mapped[list["Group"]] = relationship(
        cascade="all, delete-orphan", order_by="Group.position"
    )


class Group(Base):
    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    score: Mapped[int] = mapped_column(Integer)
    position: Mapped[int] = mapped_column(Integer)

    cases: Mapped[list["Case"]] = relationship(
        cascade="all, delete-orphan", order_by="Case.position"
    )


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    input: Mapped[str] = mapped_column(Text)
    expected_output: Mapped[str] = mapped_column(Text)
    is_sample: Mapped[bool] = mapped_column(Boolean, default=False)


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (
        Index("ix_submissions_status", "status"),
        Index("ix_submissions_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    problem_id: Mapped[int] = mapped_column(ForeignKey("problems.id"), index=True)
    contest_id: Mapped[int | None] = mapped_column(ForeignKey("contests.id"), index=True)
    language: Mapped[str] = mapped_column(String(20))
    source_code: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    status: Mapped[str] = mapped_column(String(20), default=QUEUED)
    verdict: Mapped[str | None] = mapped_column(String(50))
    score: Mapped[int] = mapped_column(Integer, default=0)
    time_ms: Mapped[int | None] = mapped_column(Integer)
    memory_kb: Mapped[int | None] = mapped_column(Integer)
    compile_output: Mapped[str | None] = mapped_column(Text)

    worker_id: Mapped[str | None] = mapped_column(String(100))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    results: Mapped[list["CaseResult"]] = relationship(
        cascade="all, delete-orphan", order_by="CaseResult.test_number"
    )
    user: Mapped[User] = relationship()


class CaseResult(Base):
    __tablename__ = "case_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    submission_id: Mapped[int] = mapped_column(ForeignKey("submissions.id"), index=True)
    test_number: Mapped[int] = mapped_column(Integer)
    group_name: Mapped[str] = mapped_column(String(100))
    verdict: Mapped[str] = mapped_column(String(50))
    time_ms: Mapped[int] = mapped_column(Integer, default=0)
    memory_kb: Mapped[int] = mapped_column(Integer, default=0)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    signal: Mapped[int | None] = mapped_column(Integer)


contest_problems = Table(
    "contest_problems",
    Base.metadata,
    Column("contest_id", ForeignKey("contests.id"), primary_key=True),
    Column("problem_id", ForeignKey("problems.id"), primary_key=True),
)


class Contest(Base):
    __tablename__ = "contests"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    start_time: Mapped[datetime] = mapped_column(DateTime)
    end_time: Mapped[datetime] = mapped_column(DateTime)
    style: Mapped[str] = mapped_column(String(20), default="icpc")
    penalty_minutes: Mapped[int] = mapped_column(Integer, default=20)

    problems: Mapped[list[Problem]] = relationship(secondary=contest_problems)

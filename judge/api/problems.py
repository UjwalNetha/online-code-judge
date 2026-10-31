from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from judge import queue
from judge.api.deps import admin_user, get_db
from judge.models import Case, Group, Problem, Submission
from judge.schemas import ProblemIn, ProblemOut, ProblemSummary, RejudgeOut, SampleOut, TestsIn

router = APIRouter(prefix="/problems", tags=["problems"])


def build_groups(groups):
    return [
        Group(
            name=group.name,
            score=group.score,
            position=g,
            cases=[
                Case(position=c, input=case.input, expected_output=case.output, is_sample=case.is_sample)
                for c, case in enumerate(group.cases)
            ],
        )
        for g, group in enumerate(groups)
    ]


def get_problem(problem_id, db):
    problem = db.get(Problem, problem_id)
    if problem is None:
        raise HTTPException(404, "Problem not found")
    return problem


def problem_out(problem):
    samples = [
        SampleOut(input=case.input, output=case.expected_output)
        for group in problem.groups
        for case in group.cases
        if case.is_sample
    ]
    return ProblemOut(
        id=problem.id,
        title=problem.title,
        statement=problem.statement,
        time_limit_ms=problem.time_limit_ms,
        memory_limit_mb=problem.memory_limit_mb,
        max_score=sum(group.score for group in problem.groups),
        samples=samples,
    )


@router.post("", response_model=ProblemOut, status_code=201)
def create_problem(body: ProblemIn, db=Depends(get_db), _=Depends(admin_user)):
    fields = body.model_dump(exclude={"groups"})
    problem = Problem(**fields, groups=build_groups(body.groups))
    db.add(problem)
    db.commit()
    return problem_out(problem)


@router.get("", response_model=list[ProblemSummary])
def list_problems(db=Depends(get_db)):
    return db.scalars(select(Problem).order_by(Problem.id)).all()


@router.get("/{problem_id}", response_model=ProblemOut)
def read_problem(problem_id: int, db=Depends(get_db)):
    return problem_out(get_problem(problem_id, db))


@router.put("/{problem_id}/tests", response_model=ProblemOut)
def replace_tests(problem_id: int, body: TestsIn, db=Depends(get_db), _=Depends(admin_user)):
    problem = get_problem(problem_id, db)
    problem.groups = build_groups(body.groups)
    db.commit()
    return problem_out(problem)


@router.post("/{problem_id}/rejudge", response_model=RejudgeOut, status_code=202)
def rejudge_problem(problem_id: int, db=Depends(get_db), _=Depends(admin_user)):
    get_problem(problem_id, db)
    submissions = db.scalars(select(Submission).where(Submission.problem_id == problem_id)).all()
    queue.rejudge(db, submissions)
    return RejudgeOut(queued=len(submissions))

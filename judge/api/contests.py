from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from judge.api.deps import admin_user, current_user, get_db
from judge.contests import build_leaderboard
from judge.models import DONE, Contest, Problem, Submission
from judge.schemas import ContestIn, ContestOut

router = APIRouter(prefix="/contests", tags=["contests"])


def contest_out(contest):
    return ContestOut(
        id=contest.id,
        name=contest.name,
        start_time=contest.start_time,
        end_time=contest.end_time,
        style=contest.style,
        penalty_minutes=contest.penalty_minutes,
        problem_ids=[problem.id for problem in contest.problems],
    )


def get_contest(contest_id, db):
    contest = db.get(Contest, contest_id)
    if contest is None:
        raise HTTPException(404, "Contest not found")
    return contest


@router.post("", response_model=ContestOut, status_code=201)
def create_contest(body: ContestIn, db=Depends(get_db), _=Depends(admin_user)):
    problems = db.scalars(select(Problem).where(Problem.id.in_(body.problem_ids))).all()
    if len(problems) != len(set(body.problem_ids)):
        raise HTTPException(404, "Problem not found")
    contest = Contest(
        name=body.name,
        start_time=body.start_time,
        end_time=body.end_time,
        style=body.style,
        penalty_minutes=body.penalty_minutes,
        problems=problems,
    )
    db.add(contest)
    db.commit()
    return contest_out(contest)


@router.get("/{contest_id}", response_model=ContestOut)
def read_contest(contest_id: int, db=Depends(get_db), _=Depends(current_user)):
    return contest_out(get_contest(contest_id, db))


@router.get("/{contest_id}/leaderboard")
def leaderboard(contest_id: int, db=Depends(get_db), _=Depends(current_user)):
    contest = get_contest(contest_id, db)
    submissions = db.scalars(
        select(Submission)
        .where(Submission.contest_id == contest_id, Submission.status == DONE)
        .order_by(Submission.created_at, Submission.id)
    ).all()
    return build_leaderboard(contest, submissions)

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from judge import config, queue
from judge.api.deps import admin_user, current_user, get_db
from judge.models import Contest, Problem, Submission, utcnow
from judge.schemas import RejudgeOut, SubmissionCreated, SubmissionIn, SubmissionOut

router = APIRouter(prefix="/submissions", tags=["submissions"])


def check_rate_limit(user, db):
    since = utcnow() - timedelta(minutes=1)
    recent = db.scalar(
        select(func.count(Submission.id)).where(
            Submission.user_id == user.id, Submission.created_at > since
        )
    )
    if recent >= config.SUBMISSIONS_PER_MINUTE:
        raise HTTPException(429, "Too many submissions, try again in a minute")


def check_contest(body, db):
    contest = db.get(Contest, body.contest_id)
    if contest is None:
        raise HTTPException(404, "Contest not found")
    if not contest.start_time <= utcnow() <= contest.end_time:
        raise HTTPException(400, "Contest is not running")
    if body.problem_id not in [problem.id for problem in contest.problems]:
        raise HTTPException(400, "Problem is not part of this contest")


@router.post("", response_model=SubmissionCreated, status_code=202)
def create_submission(body: SubmissionIn, db=Depends(get_db), user=Depends(current_user)):
    if len(body.source_code.encode()) > config.MAX_SOURCE_BYTES:
        raise HTTPException(413, "Source code is too large")
    check_rate_limit(user, db)
    if db.get(Problem, body.problem_id) is None:
        raise HTTPException(404, "Problem not found")
    if body.contest_id is not None:
        check_contest(body, db)

    submission = Submission(
        user_id=user.id,
        problem_id=body.problem_id,
        contest_id=body.contest_id,
        language=body.language,
        source_code=body.source_code,
    )
    db.add(submission)
    db.commit()
    return SubmissionCreated(id=submission.id, status=submission.status)


@router.get("/{submission_id}", response_model=SubmissionOut)
def read_submission(submission_id: int, db=Depends(get_db), user=Depends(current_user)):
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(404, "Submission not found")
    if submission.user_id != user.id and not user.is_admin:
        raise HTTPException(403, "This is not your submission")
    return submission


@router.post("/{submission_id}/rejudge", response_model=RejudgeOut, status_code=202)
def rejudge_submission(submission_id: int, db=Depends(get_db), _=Depends(admin_user)):
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(404, "Submission not found")
    queue.rejudge(db, [submission])
    return RejudgeOut(queued=1)

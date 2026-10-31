"""The job queue. It lives in the submissions table.

A submission goes queued -> running -> done. Each claim gets a new lease token
and the worker has to show it to save results, so a worker that was presumed
dead can't overwrite a newer run.
"""
import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.exc import OperationalError

from judge import config
from judge.models import DONE, INTERNAL_ERROR, QUEUED, RUNNING, CaseResult, Submission, User, utcnow


def claim(session, worker_id):
    """Take the next submission or return None.

    The user who was served longest ago goes first, which gives round robin
    between users no matter how many submissions one of them has queued.
    """
    try:
        submission = session.scalars(
            select(Submission)
            .join(User, User.id == Submission.user_id)
            .where(Submission.status == QUEUED)
            .order_by(User.last_claimed_at.asc().nulls_first(), Submission.id)
            .limit(1)
            .with_for_update(of=Submission, skip_locked=True)
        ).first()
        if submission is None:
            session.rollback()
            return None

        now = utcnow()
        # sqlite has no row locks, so the status check here is what makes it safe there
        claimed = session.execute(
            update(Submission)
            .where(Submission.id == submission.id, Submission.status == QUEUED)
            .values(
                status=RUNNING,
                worker_id=worker_id,
                lease_token=str(uuid.uuid4()),
                heartbeat_at=now,
                attempts=Submission.attempts + 1,
            )
        ).rowcount
        if not claimed:
            session.rollback()
            return None

        session.execute(update(User).where(User.id == submission.user_id).values(last_claimed_at=now))
        session.commit()
        session.refresh(submission)
        return submission
    except OperationalError:
        session.rollback()
        return None


def heartbeat(session, leases):
    if not leases:
        return
    session.execute(
        update(Submission)
        .where(Submission.lease_token.in_(leases), Submission.status == RUNNING)
        .values(heartbeat_at=utcnow())
    )
    session.commit()


def requeue_stale(session):
    """Put back running submissions whose worker stopped sending heartbeats."""
    deadline = utcnow() - timedelta(seconds=config.LEASE_SECONDS)
    stale = (Submission.status == RUNNING, Submission.heartbeat_at < deadline)

    session.execute(
        update(Submission)
        .where(*stale, Submission.attempts >= config.MAX_ATTEMPTS)
        .values(status=DONE, verdict=INTERNAL_ERROR, lease_token=None)
    )
    requeued = session.execute(
        update(Submission).where(*stale).values(status=QUEUED, worker_id=None, lease_token=None)
    ).rowcount
    session.commit()
    return requeued


def finish(session, submission_id, lease, outcome):
    """Save the outcome. Returns False if this worker no longer owns the submission."""
    saved = session.execute(
        update(Submission)
        .where(
            Submission.id == submission_id,
            Submission.lease_token == lease,
            Submission.status == RUNNING,
        )
        .values(
            status=DONE,
            verdict=outcome.verdict,
            score=outcome.score,
            time_ms=outcome.time_ms,
            memory_kb=outcome.memory_kb,
            compile_output=outcome.compile_output,
            lease_token=None,
        )
    ).rowcount
    if not saved:
        session.rollback()
        return False

    for number, result in enumerate(outcome.results, start=1):
        session.add(CaseResult(
            submission_id=submission_id,
            test_number=number,
            group_name=result.group_name,
            verdict=result.verdict,
            time_ms=result.time_ms,
            memory_kb=result.memory_kb,
            exit_code=result.exit_code,
            signal=result.signal,
        ))
    session.commit()
    return True


def rejudge(session, submissions):
    for submission in submissions:
        submission.status = QUEUED
        submission.verdict = None
        submission.score = 0
        submission.time_ms = None
        submission.memory_kb = None
        submission.compile_output = None
        submission.worker_id = None
        submission.lease_token = None
        submission.attempts = 0
        submission.results.clear()
    session.commit()

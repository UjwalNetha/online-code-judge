"""Worker process. Each thread runs one sandbox at a time, so MAX_SANDBOXES
threads means at most that many sandboxes per worker.

Start it with: python -m judge.worker
"""
import logging
import os
import signal
import socket
import threading

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from judge import config, queue
from judge.db import SessionLocal
from judge.judging import Outcome, judge
from judge.models import INTERNAL_ERROR, Group, Problem

logger = logging.getLogger("judge.worker")


def load_problem(session, problem_id):
    return session.scalars(
        select(Problem)
        .options(selectinload(Problem.groups).selectinload(Group.cases))
        .where(Problem.id == problem_id)
    ).one()


def process_one(worker_id, active):
    """Claim and judge one submission. Returns False if the queue was empty."""
    with SessionLocal() as session:
        submission = queue.claim(session, worker_id)
        if submission is None:
            return False
        lease = submission.lease_token
        submission_id = submission.id
        language = submission.language
        source = submission.source_code
        problem = load_problem(session, submission.problem_id)

    active.add(lease)
    try:
        try:
            outcome = judge(language, source, problem)
        except Exception:
            logger.exception("submission %s failed", submission_id)
            outcome = Outcome(verdict=INTERNAL_ERROR)
        with SessionLocal() as session:
            saved = queue.finish(session, submission_id, lease, outcome)
        logger.info("submission %s: %s (saved=%s)", submission_id, outcome.verdict, saved)
    finally:
        active.discard(lease)
    return True


def slot_loop(worker_id, active, stop):
    while not stop.is_set():
        try:
            if not process_one(worker_id, active):
                stop.wait(config.POLL_SECONDS)
        except Exception:
            logger.exception("slot error")
            stop.wait(config.POLL_SECONDS)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    worker_id = f"{socket.gethostname()}-{os.getpid()}"
    active = set()
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    slots = [
        threading.Thread(target=slot_loop, args=(worker_id, active, stop))
        for _ in range(config.MAX_SANDBOXES)
    ]
    for slot in slots:
        slot.start()
    logger.info("worker %s started with %s slots", worker_id, len(slots))

    while not stop.is_set():
        try:
            with SessionLocal() as session:
                queue.heartbeat(session, list(active))
                queue.requeue_stale(session)
        except Exception:
            logger.exception("heartbeat error")
        stop.wait(config.HEARTBEAT_SECONDS)

    for slot in slots:
        slot.join()


if __name__ == "__main__":
    main()

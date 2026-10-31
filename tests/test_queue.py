import multiprocessing
import os
import signal
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import timedelta

from conftest import make_user
from helpers import needs_linux

from judge import config, queue, worker
from judge.db import SessionLocal
from judge.judging import Outcome
from judge.models import (
    ACCEPTED,
    DONE,
    INTERNAL_ERROR,
    QUEUED,
    RUNNING,
    Case,
    Group,
    Problem,
    Submission,
    utcnow,
)


def add_problem():
    with SessionLocal() as db:
        case = Case(position=0, input="", expected_output="1\n")
        group = Group(name="all", score=100, position=0, cases=[case])
        problem = Problem(title="t", statement="s", time_limit_ms=1000, memory_limit_mb=64, groups=[group])
        db.add(problem)
        db.commit()
        return problem.id


def add_submissions(user_id, problem_id, count, source="print(1)"):
    with SessionLocal() as db:
        items = [
            Submission(user_id=user_id, problem_id=problem_id, language="python", source_code=source)
            for _ in range(count)
        ]
        db.add_all(items)
        db.commit()
        return [item.id for item in items]


def claim_all(worker_id):
    claimed = []
    misses = 0
    while misses < 20:
        with SessionLocal() as db:
            submission = queue.claim(db, worker_id)
        if submission:
            claimed.append(submission.id)
            misses = 0
        else:
            misses += 1
            time.sleep(0.01)
    return claimed


def test_claim_marks_running_and_empty_queue_returns_none(session):
    ids = add_submissions(make_user("a"), add_problem(), 1)
    submission = queue.claim(session, "w1")
    assert submission.id == ids[0]
    assert submission.status == RUNNING
    assert submission.worker_id == "w1"
    assert submission.lease_token
    assert submission.attempts == 1
    assert queue.claim(session, "w2") is None


def test_no_submission_is_claimed_twice_by_many_processes():
    ids = add_submissions(make_user("a"), add_problem(), 60)

    context = multiprocessing.get_context("spawn")
    with context.Pool(6) as pool:
        batches = pool.map(claim_all, [f"w{i}" for i in range(6)])
        pool.close()
        pool.join()

    claimed = [submission_id for batch in batches for submission_id in batch]
    assert sorted(claimed) == sorted(ids)
    assert max(Counter(claimed).values()) == 1
    assert sum(1 for batch in batches if batch) >= 2


def test_flooding_user_cannot_starve_others(session):
    problem_id = add_problem()
    flooder = make_user("flooder")
    add_submissions(flooder, problem_id, 50)
    other = make_user("other")
    add_submissions(other, problem_id, 2)

    order = [queue.claim(session, "w").user_id for _ in range(5)]
    assert order.count(other) == 2
    assert order[:4].count(other) == 2


def test_new_user_goes_ahead_of_a_long_backlog(session):
    problem_id = add_problem()
    flooder = make_user("flooder")
    add_submissions(flooder, problem_id, 20)
    queue.claim(session, "w")

    other = make_user("other")
    late = add_submissions(other, problem_id, 1)
    assert queue.claim(session, "w").id == late[0]


def make_stale(session, submission):
    submission.heartbeat_at = utcnow() - timedelta(seconds=config.LEASE_SECONDS + 5)
    session.commit()


def test_stale_submission_is_requeued(session):
    add_submissions(make_user("a"), add_problem(), 1)
    submission = queue.claim(session, "dead")
    make_stale(session, submission)

    assert queue.requeue_stale(session) == 1
    session.refresh(submission)
    assert submission.status == QUEUED
    assert submission.lease_token is None
    assert queue.claim(session, "alive").attempts == 2


def test_healthy_submission_is_left_alone(session):
    add_submissions(make_user("a"), add_problem(), 1)
    submission = queue.claim(session, "w")
    queue.heartbeat(session, [submission.lease_token])
    assert queue.requeue_stale(session) == 0
    session.refresh(submission)
    assert submission.status == RUNNING


def test_heartbeat_keeps_lease_alive(session):
    add_submissions(make_user("a"), add_problem(), 1)
    submission = queue.claim(session, "w")
    make_stale(session, submission)
    queue.heartbeat(session, [submission.lease_token])
    assert queue.requeue_stale(session) == 0


def test_submission_that_keeps_crashing_ends_as_internal_error(session):
    add_submissions(make_user("a"), add_problem(), 1)
    for _ in range(config.MAX_ATTEMPTS):
        submission = queue.claim(session, "w")
        make_stale(session, submission)
        queue.requeue_stale(session)

    session.refresh(submission)
    assert submission.status == DONE
    assert submission.verdict == INTERNAL_ERROR
    assert queue.claim(session, "w") is None


def test_stale_worker_cannot_overwrite_a_newer_run(session):
    add_submissions(make_user("a"), add_problem(), 1)
    first = queue.claim(session, "old")
    old_lease = first.lease_token
    make_stale(session, first)
    queue.requeue_stale(session)
    second = queue.claim(session, "new")
    new_lease = second.lease_token

    assert not queue.finish(session, second.id, old_lease, Outcome(verdict="Wrong Answer"))
    assert queue.finish(session, second.id, new_lease, Outcome(verdict=ACCEPTED, score=100))
    session.refresh(second)
    assert second.verdict == ACCEPTED


def test_rejudge_during_a_run_drops_the_old_result(session):
    add_submissions(make_user("a"), add_problem(), 1)
    submission = queue.claim(session, "w")
    lease = submission.lease_token
    queue.rejudge(session, [submission])

    assert not queue.finish(session, submission.id, lease, Outcome(verdict=ACCEPTED))
    session.refresh(submission)
    assert submission.status == QUEUED


def test_concurrent_sandboxes_are_capped(monkeypatch):
    add_submissions(make_user("a"), add_problem(), 8)
    lock = threading.Lock()
    running = 0
    highest = 0

    def slow_judge(language, source, problem):
        nonlocal running, highest
        with lock:
            running += 1
            highest = max(highest, running)
        time.sleep(0.05)
        with lock:
            running -= 1
        return Outcome(verdict=ACCEPTED)

    monkeypatch.setattr(worker, "judge", slow_judge)
    stop = threading.Event()
    active = set()
    slots = [threading.Thread(target=worker.slot_loop, args=("w", active, stop)) for _ in range(2)]
    for slot in slots:
        slot.start()

    deadline = time.time() + 20
    with SessionLocal() as db:
        while time.time() < deadline:
            db.expire_all()
            done = db.query(Submission).filter(Submission.status == DONE).count()
            if done == 8:
                break
            time.sleep(0.05)
    stop.set()
    for slot in slots:
        slot.join()

    assert done == 8
    assert highest <= 2


def start_worker():
    env = {**os.environ, "LEASE_SECONDS": "1", "HEARTBEAT_SECONDS": "0.2", "POLL_SECONDS": "0.1"}
    return subprocess.Popen([sys.executable, "-m", "judge.worker"], env=env)


def wait_for_status(submission_id, status, seconds=20):
    deadline = time.time() + seconds
    while time.time() < deadline:
        with SessionLocal() as db:
            submission = db.get(Submission, submission_id)
            if submission.status == status:
                return submission
        time.sleep(0.05)
    raise AssertionError(f"submission never reached {status}")


@needs_linux
def test_killed_worker_is_recovered_by_another():
    source = "import time\ntime.sleep(60)"
    submission_id = add_submissions(make_user("a"), add_problem(), 1, source=source)[0]

    victim = start_worker()
    try:
        wait_for_status(submission_id, RUNNING)
    finally:
        os.kill(victim.pid, signal.SIGKILL)
        victim.wait()

    rescuer = start_worker()
    try:
        submission = wait_for_status(submission_id, DONE, seconds=30)
    finally:
        rescuer.terminate()
        rescuer.wait()

    assert submission.attempts == 2
    assert submission.verdict == "Time Limit Exceeded"

from datetime import timedelta

from conftest import headers_for, make_user
from helpers import problem_payload, needs_linux

from judge.models import Submission, utcnow
from judge.queue import rejudge
from judge.worker import process_one


def create_problem(client, admin_headers, **fields):
    response = client.post("/problems", json=problem_payload(**fields), headers=admin_headers)
    assert response.status_code == 201
    return response.json()["id"]


def submit(client, headers, problem_id, source="print(1)", language="python"):
    body = {"problem_id": problem_id, "language": language, "source_code": source}
    return client.post("/submissions", json=body, headers=headers)


def test_register_and_login(client):
    credentials = {"username": "bob", "password": "password123"}
    assert client.post("/auth/register", json=credentials).status_code == 201
    assert client.post("/auth/register", json=credentials).status_code == 400

    response = client.post("/auth/login", json=credentials)
    assert response.status_code == 200
    token = response.json()["access_token"]

    wrong = client.post("/auth/login", json={"username": "bob", "password": "wrong-password"})
    assert wrong.status_code == 401

    response = client.post("/submissions", json={}, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 422


def test_register_validates_input(client):
    response = client.post("/auth/register", json={"username": "x", "password": "short"})
    assert response.status_code == 422


def test_registered_user_is_never_admin(client):
    body = {"username": "bob", "password": "password123", "is_admin": True}
    client.post("/auth/register", json=body)
    token = client.post("/auth/login", json=body).json()["access_token"]
    response = client.post(
        "/problems", json=problem_payload(), headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 403


def test_problem_create_needs_admin(client, user_headers):
    assert client.post("/problems", json=problem_payload()).status_code == 401
    assert client.post("/problems", json=problem_payload(), headers=user_headers).status_code == 403


def test_bad_token_is_rejected(client):
    response = client.post(
        "/problems", json=problem_payload(), headers={"Authorization": "Bearer not-a-token"}
    )
    assert response.status_code == 401


def test_custom_checker_needs_source(client, admin_headers):
    response = client.post("/problems", json=problem_payload(checker="custom"), headers=admin_headers)
    assert response.status_code == 422


def test_hidden_tests_do_not_leak(client, admin_headers):
    problem_id = create_problem(client, admin_headers)

    listing = client.get("/problems")
    detail = client.get(f"/problems/{problem_id}")
    assert listing.status_code == 200
    assert detail.status_code == 200
    assert "HIDDEN" not in listing.text
    assert "HIDDEN" not in detail.text
    assert detail.json()["samples"] == [{"input": "1 2\n", "output": "3\n"}]


def test_missing_problem(client, user_headers):
    assert client.get("/problems/999").status_code == 404
    assert submit(client, user_headers, 999).status_code == 404


def test_submit_returns_202_and_status(client, admin_headers, user_headers):
    problem_id = create_problem(client, admin_headers)
    response = submit(client, user_headers, problem_id)
    assert response.status_code == 202
    submission_id = response.json()["id"]

    response = client.get(f"/submissions/{submission_id}", headers=user_headers)
    assert response.status_code == 200
    assert response.json()["status"] == "queued"
    assert response.json()["verdict"] is None


def test_submit_needs_login(client, admin_headers):
    problem_id = create_problem(client, admin_headers)
    assert submit(client, {}, problem_id).status_code == 401


def test_unknown_language(client, admin_headers, user_headers):
    problem_id = create_problem(client, admin_headers)
    assert submit(client, user_headers, problem_id, language="cobol").status_code == 422


def test_source_too_large(client, admin_headers, user_headers):
    problem_id = create_problem(client, admin_headers)
    assert submit(client, user_headers, problem_id, source="#" * 2000).status_code == 413
    assert submit(client, user_headers, problem_id, source="#" * 20000).status_code == 413


def test_rate_limit(client, admin_headers, user_headers):
    problem_id = create_problem(client, admin_headers)
    for _ in range(5):
        assert submit(client, user_headers, problem_id).status_code == 202
    assert submit(client, user_headers, problem_id).status_code == 429


def test_rate_limit_is_per_user(client, admin_headers, user_headers):
    problem_id = create_problem(client, admin_headers)
    for _ in range(5):
        submit(client, user_headers, problem_id)
    other = headers_for(make_user("bob"))
    assert submit(client, other, problem_id).status_code == 202


def test_cannot_read_other_users_submission(client, admin_headers, user_headers):
    problem_id = create_problem(client, admin_headers)
    submission_id = submit(client, user_headers, problem_id).json()["id"]
    other = headers_for(make_user("bob"))

    assert client.get(f"/submissions/{submission_id}", headers=other).status_code == 403
    assert client.get(f"/submissions/{submission_id}", headers=admin_headers).status_code == 200
    assert client.get("/submissions/999", headers=other).status_code == 404


@needs_linux
def test_submission_flow_and_no_leak_in_results(client, admin_headers, user_headers):
    payload = problem_payload(groups=[
        {"name": "hidden", "score": 100, "cases": [{"input": "SECRET\n", "output": "SECRET\n"}]}
    ])
    problem_id = create_problem(client, admin_headers, **payload)
    source = "import sys\ndata = input()\nprint(data)\nprint(data, file=sys.stderr)\nraise SystemExit(3)"
    submission_id = submit(client, user_headers, problem_id, source=source).json()["id"]

    assert process_one("test-worker", set())

    response = client.get(f"/submissions/{submission_id}", headers=user_headers)
    body = response.json()
    assert body["status"] == "done"
    assert body["verdict"] == "Runtime Error"
    assert body["results"][0]["exit_code"] == 3
    assert "SECRET" not in response.text


@needs_linux
def test_rejudge_after_tests_change(client, admin_headers, user_headers):
    payload = problem_payload(groups=[
        {"name": "all", "score": 100, "cases": [{"input": "", "output": "2\n"}]}
    ])
    problem_id = create_problem(client, admin_headers, **payload)
    submission_id = submit(client, user_headers, problem_id, source="print(1)").json()["id"]
    process_one("test-worker", set())
    url = f"/submissions/{submission_id}"
    assert client.get(url, headers=user_headers).json()["verdict"] == "Wrong Answer"

    tests = {"groups": [{"name": "all", "score": 100, "cases": [{"input": "", "output": "1\n"}]}]}
    assert client.put(f"/problems/{problem_id}/tests", json=tests, headers=user_headers).status_code == 403
    assert client.put(f"/problems/{problem_id}/tests", json=tests, headers=admin_headers).status_code == 200

    assert client.post(f"/problems/{problem_id}/rejudge", headers=user_headers).status_code == 403
    response = client.post(f"/problems/{problem_id}/rejudge", headers=admin_headers)
    assert response.status_code == 202
    assert response.json() == {"queued": 1}
    assert client.get(url, headers=user_headers).json()["status"] == "queued"

    process_one("test-worker", set())
    body = client.get(url, headers=user_headers).json()
    assert body["verdict"] == "Accepted"
    assert body["score"] == 100
    assert len(body["results"]) == 1


def test_rejudge_one_submission(client, admin_headers, user_headers, session):
    problem_id = create_problem(client, admin_headers)
    submission_id = submit(client, user_headers, problem_id).json()["id"]
    submission = session.get(Submission, submission_id)
    submission.status = "done"
    submission.verdict = "Wrong Answer"
    session.commit()

    assert client.post(f"/submissions/{submission_id}/rejudge", headers=user_headers).status_code == 403
    assert client.post("/submissions/999/rejudge", headers=admin_headers).status_code == 404
    assert client.post(f"/submissions/{submission_id}/rejudge", headers=admin_headers).status_code == 202

    session.refresh(submission)
    assert submission.status == "queued"
    assert submission.verdict is None


def contest_payload(problem_id, start=-10, end=60, **fields):
    now = utcnow()
    return {
        "name": "Round 1",
        "start_time": (now + timedelta(minutes=start)).isoformat(),
        "end_time": (now + timedelta(minutes=end)).isoformat(),
        "problem_ids": [problem_id],
        **fields,
    }


def test_contest_create_rules(client, admin_headers, user_headers):
    problem_id = create_problem(client, admin_headers)
    assert client.post("/contests", json=contest_payload(problem_id), headers=user_headers).status_code == 403
    assert client.post("/contests", json=contest_payload(999), headers=admin_headers).status_code == 404
    bad_times = contest_payload(problem_id, start=10, end=5)
    assert client.post("/contests", json=bad_times, headers=admin_headers).status_code == 422
    assert client.post("/contests", json=contest_payload(problem_id), headers=admin_headers).status_code == 201


def test_contest_submission_window(client, admin_headers, user_headers):
    problem_id = create_problem(client, admin_headers)
    other_problem = create_problem(client, admin_headers)
    future = contest_payload(problem_id, start=10, end=20)
    running = contest_payload(problem_id)
    future_id = client.post("/contests", json=future, headers=admin_headers).json()["id"]
    running_id = client.post("/contests", json=running, headers=admin_headers).json()["id"]

    def enter(contest_id, problem):
        body = {
            "problem_id": problem,
            "language": "python",
            "source_code": "print(1)",
            "contest_id": contest_id,
        }
        return client.post("/submissions", json=body, headers=user_headers).status_code

    assert enter(future_id, problem_id) == 400
    assert enter(running_id, other_problem) == 400
    assert enter(999, problem_id) == 404
    assert enter(running_id, problem_id) == 202


def test_leaderboard_endpoint(client, admin_headers, user_headers, session):
    problem_id = create_problem(client, admin_headers)
    contest_id = client.post(
        "/contests", json=contest_payload(problem_id), headers=admin_headers
    ).json()["id"]
    body = {
        "problem_id": problem_id,
        "language": "python",
        "source_code": "print(1)",
        "contest_id": contest_id,
    }
    submission_id = client.post("/submissions", json=body, headers=user_headers).json()["id"]
    submission = session.get(Submission, submission_id)
    submission.status = "done"
    submission.verdict = "Accepted"
    session.commit()

    assert client.get(f"/contests/{contest_id}/leaderboard").status_code == 401
    response = client.get(f"/contests/{contest_id}/leaderboard", headers=user_headers)
    assert response.status_code == 200
    assert response.json()[0]["username"] == "alice"
    assert response.json()[0]["total"] == 1

    rejudge(session, [submission])
    response = client.get(f"/contests/{contest_id}/leaderboard", headers=user_headers)
    assert response.json() == []

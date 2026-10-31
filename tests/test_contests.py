from datetime import datetime, timedelta
from types import SimpleNamespace

from judge.contests import build_leaderboard
from judge.models import ACCEPTED, COMPILATION_ERROR, INTERNAL_ERROR, WRONG_ANSWER

START = datetime(2026, 1, 1, 10, 0)


def contest(style="icpc", penalty=20):
    return SimpleNamespace(style=style, start_time=START, penalty_minutes=penalty)


def attempt(user, problem, minute, verdict, score=0):
    return SimpleNamespace(
        user=SimpleNamespace(username=user),
        problem_id=problem,
        created_at=START + timedelta(minutes=minute),
        verdict=verdict,
        score=score,
    )


def test_icpc_penalty_counts_wrong_attempts_before_accepted():
    board = build_leaderboard(contest(), [
        attempt("ann", 1, 5, WRONG_ANSWER),
        attempt("ann", 1, 10, WRONG_ANSWER),
        attempt("ann", 1, 30, ACCEPTED),
        attempt("ann", 1, 40, WRONG_ANSWER),
    ])
    assert board[0]["total"] == 1
    assert board[0]["penalty"] == 30 + 2 * 20
    assert board[0]["problems"][1]["wrong_attempts"] == 2


def test_icpc_order_is_solved_then_penalty():
    board = build_leaderboard(contest(), [
        attempt("slow", 1, 100, ACCEPTED),
        attempt("slow", 2, 120, ACCEPTED),
        attempt("fast", 1, 1, ACCEPTED),
        attempt("mid", 1, 50, ACCEPTED),
    ])
    assert [row["username"] for row in board] == ["slow", "fast", "mid"]
    assert [row["rank"] for row in board] == [1, 2, 3]


def test_ties_share_a_rank():
    board = build_leaderboard(contest(), [
        attempt("a", 1, 10, ACCEPTED),
        attempt("b", 1, 10, ACCEPTED),
        attempt("c", 1, 20, ACCEPTED),
    ])
    assert [row["rank"] for row in board] == [1, 1, 3]


def test_unsolved_problem_has_no_penalty():
    board = build_leaderboard(contest(), [attempt("ann", 1, 5, WRONG_ANSWER)])
    assert board[0]["total"] == 0
    assert board[0]["penalty"] == 0
    assert board[0]["problems"][1]["wrong_attempts"] == 1


def test_compile_and_internal_errors_cost_nothing():
    board = build_leaderboard(contest(), [
        attempt("ann", 1, 1, COMPILATION_ERROR),
        attempt("ann", 1, 2, INTERNAL_ERROR),
        attempt("ann", 1, 3, ACCEPTED),
    ])
    assert board[0]["penalty"] == 3


def test_score_style_uses_best_score_per_problem():
    board = build_leaderboard(contest("score", penalty=5), [
        attempt("ann", 1, 10, WRONG_ANSWER, score=40),
        attempt("ann", 1, 20, WRONG_ANSWER, score=0),
        attempt("ann", 1, 30, ACCEPTED, score=100),
        attempt("ann", 2, 40, WRONG_ANSWER, score=60),
        attempt("ann", 2, 50, WRONG_ANSWER, score=60),
        attempt("bob", 1, 5, ACCEPTED, score=100),
    ])
    assert board[0]["username"] == "ann"
    assert board[0]["total"] == 160
    assert board[0]["problems"][1]["penalty"] == 30 + 5
    assert board[0]["problems"][2]["penalty"] == 40
    assert board[1]["total"] == 100

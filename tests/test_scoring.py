from helpers import make_problem, needs_linux

from judge.judging import judge
from judge.models import ACCEPTED, RUNTIME_ERROR, WRONG_ANSWER
from judge.scoring import final_verdict, group_points

# prints the input back unless it is "bad"
ECHO = "line = input()\nprint('wrong' if line == 'bad' else line)"


def two_groups(**fields):
    return make_problem(
        [
            (30, [("a\n", "a\n"), ("b\n", "b\n")]),
            (70, [("c\n", "c\n"), ("bad\n", "bad\n"), ("d\n", "d\n")]),
        ],
        **fields,
    )


def test_group_points():
    assert group_points(40, [ACCEPTED, ACCEPTED], 2) == 40
    assert group_points(40, [ACCEPTED, WRONG_ANSWER], 2) == 0
    assert group_points(40, [ACCEPTED], 2) == 0


def test_final_verdict_is_first_failure():
    assert final_verdict([ACCEPTED, ACCEPTED]) == ACCEPTED
    assert final_verdict([ACCEPTED, RUNTIME_ERROR, WRONG_ANSWER]) == RUNTIME_ERROR


@needs_linux
def test_partial_points_when_running_all_tests():
    outcome = judge("python", ECHO, two_groups(stop_on_first_fail=False))
    assert outcome.verdict == WRONG_ANSWER
    assert outcome.score == 30
    assert len(outcome.results) == 5
    assert [r.verdict for r in outcome.results].count(ACCEPTED) == 4


@needs_linux
def test_stop_at_first_failure_keeps_earlier_groups():
    outcome = judge("python", ECHO, two_groups(stop_on_first_fail=True))
    assert outcome.verdict == WRONG_ANSWER
    assert outcome.score == 30
    assert len(outcome.results) == 4


@needs_linux
def test_full_score():
    outcome = judge("python", "print(input())", make_problem(
        [(30, [("a\n", "a\n")]), (70, [("b\n", "b\n")])]
    ))
    assert outcome.verdict == ACCEPTED
    assert outcome.score == 100

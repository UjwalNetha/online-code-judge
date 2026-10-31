import sys

import pytest

from judge.models import Case, Group, Problem

needs_linux = pytest.mark.skipif(sys.platform != "linux", reason="the sandbox needs Linux")


def make_problem(groups=None, **fields):
    """A problem that is not in the database, for calling judge() directly.

    groups is a list of (score, [(input, output), ...]).
    """
    settings = dict(
        title="Test",
        statement="Test",
        time_limit_ms=1000,
        memory_limit_mb=128,
        checker="token",
        float_tolerance=1e-6,
        stop_on_first_fail=True,
    )
    settings.update(fields)
    groups = groups or [(100, [("", "ok\n")])]
    return Problem(
        **settings,
        groups=[
            Group(
                name=f"group{g}",
                score=score,
                position=g,
                cases=[
                    Case(position=c, input=given, expected_output=expected)
                    for c, (given, expected) in enumerate(cases)
                ],
            )
            for g, (score, cases) in enumerate(groups)
        ],
    )


def problem_payload(**fields):
    payload = {
        "title": "A Plus B",
        "statement": "Add two numbers",
        "time_limit_ms": 1000,
        "memory_limit_mb": 128,
        "groups": [
            {
                "name": "samples",
                "score": 0,
                "cases": [{"input": "1 2\n", "output": "3\n", "is_sample": True}],
            },
            {
                "name": "hidden",
                "score": 100,
                "cases": [{"input": "HIDDENINPUT 5\n", "output": "HIDDENOUTPUT\n"}],
            },
        ],
    }
    payload.update(fields)
    return payload

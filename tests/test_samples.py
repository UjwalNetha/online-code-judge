from pathlib import Path

import pytest
from helpers import needs_linux
from sqlalchemy import select

import seed
from judge.db import SessionLocal
from judge.judging import judge
from judge.models import ACCEPTED, Problem, User
from judge.worker import load_problem

SAMPLES = Path(__file__).parent.parent / "samples"
SOLUTIONS = [
    (name, file, "cpp" if file.endswith(".cpp") else "python")
    for name in ("a_plus_b", "circle_area", "two_sum")
    for file in ("solution.py", "solution.cpp")
]


def test_seed_can_run_twice(monkeypatch):
    monkeypatch.setenv("ADMIN_PASSWORD", "password123")
    seed.main()
    seed.main()
    with SessionLocal() as db:
        assert len(db.scalars(select(Problem)).all()) == 3
        assert db.scalars(select(User)).one().is_admin


@needs_linux
@pytest.mark.parametrize("folder,file,language", SOLUTIONS)
def test_reference_solution_is_accepted(folder, file, language):
    seed.main()
    title = seed.load_problem(SAMPLES / folder).title
    with SessionLocal() as db:
        problem_id = db.scalar(select(Problem.id).where(Problem.title == title))
        problem = load_problem(db, problem_id)

    outcome = judge(language, (SAMPLES / folder / file).read_text(), problem)
    assert outcome.verdict == ACCEPTED
    assert outcome.score == sum(group.score for group in problem.groups)

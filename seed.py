"""Creates the admin user and loads the sample problems. Safe to run twice.

Start it with: python seed.py
"""
import json
import os
from pathlib import Path

from sqlalchemy import select

from judge.api.problems import build_groups
from judge.db import SessionLocal, init_db
from judge.models import Problem, User
from judge.schemas import ProblemIn
from judge.security import hash_password

SAMPLES = Path(__file__).parent / "samples"


def load_problem(folder):
    data = json.loads((folder / "problem.json").read_text())
    checker = folder / "checker.py"
    if checker.exists():
        data["checker_language"] = "python"
        data["checker_source"] = checker.read_text()
    return ProblemIn(**data)


def main():
    init_db()
    with SessionLocal() as session:
        username = os.environ.get("ADMIN_USERNAME", "admin")
        password = os.environ.get("ADMIN_PASSWORD")
        if password and not session.scalar(select(User).where(User.username == username)):
            session.add(User(username=username, password_hash=hash_password(password), is_admin=True))

        for folder in sorted(path for path in SAMPLES.iterdir() if path.is_dir()):
            body = load_problem(folder)
            if not session.scalar(select(Problem).where(Problem.title == body.title)):
                fields = body.model_dump(exclude={"groups"})
                session.add(Problem(**fields, groups=build_groups(body.groups)))
        session.commit()


if __name__ == "__main__":
    main()

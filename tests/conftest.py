import os
import tempfile

os.environ.setdefault("JWT_SECRET", "test-secret-only-used-by-the-test-suite")
os.environ.setdefault("DATABASE_URL", f"sqlite:///{tempfile.mkdtemp()}/test.db")
os.environ["SUBMISSIONS_PER_MINUTE"] = "5"
os.environ["MAX_SOURCE_BYTES"] = "1024"
os.environ["MAX_OUTPUT_BYTES"] = str(1024 * 1024)

import pytest
from fastapi.testclient import TestClient

from judge.api.app import app
from judge.db import Base, SessionLocal, engine, init_db
from judge.models import User
from judge.security import create_token, hash_password


@pytest.fixture(autouse=True)
def clean_database():
    Base.metadata.drop_all(engine)
    init_db()
    yield


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def session():
    with SessionLocal() as db:
        yield db


def make_user(name, is_admin=False):
    with SessionLocal() as db:
        user = User(username=name, password_hash=hash_password("password123"), is_admin=is_admin)
        db.add(user)
        db.commit()
        return user.id


def headers_for(user_id):
    return {"Authorization": f"Bearer {create_token(user_id)}"}


@pytest.fixture
def admin_headers():
    return headers_for(make_user("admin", is_admin=True))


@pytest.fixture
def user_headers():
    return headers_for(make_user("alice"))

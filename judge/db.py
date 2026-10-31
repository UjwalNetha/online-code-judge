from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from judge import config

connect_args = {"timeout": 30} if config.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(config.DATABASE_URL, connect_args=connect_args)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db():
    import judge.models  # noqa: F401

    Base.metadata.create_all(engine)

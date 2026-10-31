import os


def _int(name, default):
    return int(os.environ.get(name, default))


DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./judge.db")

JWT_SECRET = os.environ["JWT_SECRET"]
JWT_MINUTES = _int("JWT_MINUTES", 120)

MAX_SOURCE_BYTES = _int("MAX_SOURCE_BYTES", 64 * 1024)
SUBMISSIONS_PER_MINUTE = _int("SUBMISSIONS_PER_MINUTE", 10)

MAX_OUTPUT_BYTES = _int("MAX_OUTPUT_BYTES", 16 * 1024 * 1024)

MAX_SANDBOXES = _int("MAX_SANDBOXES", 2)
POLL_SECONDS = float(os.environ.get("POLL_SECONDS", 0.5))
HEARTBEAT_SECONDS = float(os.environ.get("HEARTBEAT_SECONDS", 5))
LEASE_SECONDS = float(os.environ.get("LEASE_SECONDS", 30))
MAX_ATTEMPTS = _int("MAX_ATTEMPTS", 3)

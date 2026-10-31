import hashlib
import hmac
import os
from datetime import UTC, datetime, timedelta

import jwt

from judge import config

ALGORITHM = "HS256"


def _scrypt(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)


def hash_password(password):
    salt = os.urandom(16)
    return f"{salt.hex()}${_scrypt(password, salt).hex()}"


def verify_password(password, stored):
    salt, expected = stored.split("$")
    return hmac.compare_digest(_scrypt(password, bytes.fromhex(salt)).hex(), expected)


def create_token(user_id):
    expires = datetime.now(UTC) + timedelta(minutes=config.JWT_MINUTES)
    return jwt.encode({"sub": str(user_id), "exp": expires}, config.JWT_SECRET, algorithm=ALGORITHM)


def read_token(token):
    """Returns the user id, or None if the token is bad or expired."""
    try:
        return int(jwt.decode(token, config.JWT_SECRET, algorithms=[ALGORITHM])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None

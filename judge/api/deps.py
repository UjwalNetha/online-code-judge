from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from judge.db import SessionLocal
from judge.models import User
from judge.security import read_token

bearer = HTTPBearer(auto_error=False)


def get_db():
    with SessionLocal() as session:
        yield session


def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db=Depends(get_db)):
    user_id = read_token(credentials.credentials) if credentials else None
    user = db.get(User, user_id) if user_id else None
    if user is None:
        raise HTTPException(401, "Not authenticated", headers={"WWW-Authenticate": "Bearer"})
    return user


def admin_user(user=Depends(current_user)):
    if not user.is_admin:
        raise HTTPException(403, "Admin only")
    return user

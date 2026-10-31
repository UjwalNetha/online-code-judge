from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from judge import config
from judge.api import auth, contests, problems, submissions
from judge.db import init_db


@asynccontextmanager
async def lifespan(_):
    init_db()
    yield


app = FastAPI(title="Online Code Judge", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(problems.router)
app.include_router(submissions.router)
app.include_router(contests.router)


@app.middleware("http")
async def limit_submission_body(request: Request, call_next):
    # stops huge bodies before they are parsed, json escapes can add a lot of bytes
    size = request.headers.get("content-length", "0")
    if request.url.path == "/submissions" and size.isdigit() and int(size) > 8 * config.MAX_SOURCE_BYTES:
        return JSONResponse({"detail": "Source code is too large"}, status_code=413)
    return await call_next(request)


@app.get("/health")
def health():
    return {"status": "ok"}

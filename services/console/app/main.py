"""HarnessGuard analyst console -- stub (D1). Dashboard lands in D5."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from harnessguard_core import db


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="HarnessGuard console", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return JSONResponse({"status": "ok", "service": "console"})

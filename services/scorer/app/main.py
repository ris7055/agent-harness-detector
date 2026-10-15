"""HarnessGuard scorer -- stub (D1). Real ingest/decide endpoints land in D2."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from harnessguard_core import db


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="HarnessGuard scorer", lifespan=lifespan)


@app.get("/healthz")
def healthz():
    return JSONResponse({"status": "ok", "service": "scorer"})

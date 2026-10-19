"""HTTP API for project search.

- GET /api/search?q=...&source=surg|expo&from=YEAR&to=YEAR&n=20 returns
  {"results": [...]}, each result as search.public describes it.
- GET /api/health returns {"ok": true} once the index is loaded.

Usage: uv run uvicorn app:app [--reload]
"""

from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, Query

import search


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.index = search.Index()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/api/search")
def search_projects(
    q: str = Query(min_length=1, max_length=300),
    source: Literal["surg", "expo"] | None = None,
    year_from: int | None = Query(None, alias="from"),
    year_to: int | None = Query(None, alias="to"),
    n: int = Query(20, ge=1, le=50),
) -> dict:
    years = None if year_from is None and year_to is None else (year_from or 0, year_to or 9999)
    return {"results": [search.public(p) for p in app.state.index.search(q, source, years, n)]}


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}

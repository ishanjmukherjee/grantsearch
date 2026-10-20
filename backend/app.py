"""HTTP API for project search.

- GET /api/search?q=...&source=surg|expo&from=YEAR&to=YEAR&n=20&offset=0
  returns {"results": [...], "more": bool}, each result as search.public
  describes it; "more" says whether a later offset has results. An empty or
  missing q browses all projects, most recent first.
- GET /api/health returns {"ok": true} once the index is loaded.
- Everything else serves the built frontend from frontend/dist, when it
  exists; in development the Vite dev server serves it instead.

Usage: uv run uvicorn app:app [--reload]
"""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Query
from fastapi.staticfiles import StaticFiles

import search

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.index = search.Index()
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/api/search")
def search_projects(
    q: str = Query("", max_length=300),
    source: Literal["surg", "expo"] | None = None,
    year_from: int | None = Query(None, alias="from"),
    year_to: int | None = Query(None, alias="to"),
    n: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
) -> dict:
    years = None if year_from is None and year_to is None else (year_from or 0, year_to or 9999)
    results = app.state.index.search(q, source, years, n + 1, offset)
    return {"results": [search.public(p) for p in results[:n]], "more": len(results) > n}


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True))

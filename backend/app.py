"""HTTP API for project search.

- GET /api/search?q=...&source=surg|expo&from=YEAR&to=YEAR&n=20&offset=0
  returns {"results": [...], "total": int}, each result as search.public
  describes it; "total" counts the matches at every offset. An empty or
  missing q browses all projects, most recent first.
- GET /api/project/NUMBER returns {"project": ..., "similar": [...]} for the
  project a share number leads to (see pipeline.share_ids), or 404.
- GET /api/health returns {"ok": true} once the index is loaded.
- GET /p/NUMBER serves the frontend's page with the project's title and a
  description in its head, for link previews.
- Everything else serves the built frontend from frontend/dist, when it
  exists; in development the Vite dev server serves it instead.

Requests for www.prowl.nu are redirected permanently to the same path and
query on prowl.nu, the site's one canonical host.

Usage: uv run uvicorn app:app [--reload]
"""

from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import search

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend" / "dist"
SITE = "Prowl"
DESCRIPTION_CHARS = 200
CANONICAL_HOST = "prowl.nu"
REDIRECTED_HOSTS = {"www.prowl.nu"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.index = search.Index()
    yield


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def canonical_host(request: Request, call_next):
    if request.headers.get("host", "").split(":")[0].lower() in REDIRECTED_HOSTS:
        return RedirectResponse(str(request.url.replace(scheme="https", netloc=CANONICAL_HOST)), status_code=301)
    return await call_next(request)


@app.get("/api/search")
def search_projects(
    q: str = Query("", max_length=2000),
    source: Literal["surg", "expo"] | None = None,
    year_from: int | None = Query(None, alias="from"),
    year_to: int | None = Query(None, alias="to"),
    n: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
) -> dict:
    years = None if year_from is None and year_to is None else (year_from or 0, year_to or 9999)
    results, total = app.state.index.search(q, source, years, n, offset)
    return {"results": [search.public(p) for p in results], "total": total}


@app.get("/api/project/{number}")
def project(number: int) -> dict:
    p = app.state.index.project(number)
    if p is None:
        raise HTTPException(404, "No project has this number.")
    return {"project": search.public(p), "similar": [search.public(x) for x in app.state.index.similar(p)]}


def description(r: dict) -> str:
    """A link preview's description: the start of the first abstract, or who
    won a title-only grant."""
    if r["expo"]:
        text = " ".join(r["expo"][0]["abstract"].split())
        return text if len(text) <= DESCRIPTION_CHARS else text[:DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"
    awardees = r["grant"]["awardees"]
    names = " and ".join(awardees) if len(awardees) <= 2 else f"{', '.join(awardees[:-1])}, and {awardees[-1]}"
    return f"SURG {r['grant']['year']} grant awarded to {names}."


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


if FRONTEND_DIR.exists():
    page = (FRONTEND_DIR / "index.html").read_text()

    @app.get("/p/{number}", response_class=HTMLResponse)
    def project_page(number: str) -> HTMLResponse:
        p = app.state.index.project(int(number)) if number.isdigit() else None
        if p is None:
            return HTMLResponse(page, status_code=404)
        r = search.public(p)
        title, desc = escape(f"{r['title']} — {SITE}"), escape(description(r))
        head = (
            f'<meta name="description" content="{desc}" />'
            f'<meta property="og:title" content="{escape(r["title"])}" />'
            f'<meta property="og:description" content="{desc}" />'
            f'<meta property="og:site_name" content="{SITE}" />'
            f'<meta property="og:type" content="article" />'
            '<meta name="twitter:card" content="summary" />'
        )
        return HTMLResponse(page.replace(f"<title>{SITE}</title>", f"<title>{title}</title>{head}"))

    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True))

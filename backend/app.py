"""HTTP API for project search.

- GET /api/search?q=...&source=surg|expo|theses|nurj&from=YEAR&to=YEAR&n=20&offset=0
  returns {"results": [...], "total": int}, each result as search.public
  describes it; "total" counts the matches at every offset. An empty or
  missing q browses all projects, most recent first.
- GET /api/project/NUMBER returns {"project": ..., "similar": [...]} for the
  project a share number leads to (see pipeline.share_ids), or 404.
- GET /api/health returns {"ok": true} once the index is loaded.
- POST /api/event takes a browser's report of what a visitor did with a
  result (see querylog.report) and always answers 204.
- GET /p/NUMBER serves the frontend's page with the project's title and a
  description in its head, for link previews.
- Everything else serves the built frontend from frontend/dist, when it
  exists; in development the Vite dev server serves it instead.

Searches, project page loads and those reports go to the query log (see
querylog), with the X-Visit, X-Seq, X-Shown, X-Cause and X-Internal headers
the frontend sends.

Requests for www.prowl.nu and the service's Railway address are redirected
permanently to the same path and query on prowl.nu, the site's one canonical
host.

Usage: uv run uvicorn app:app [--reload]
"""

import time
from contextlib import asynccontextmanager
from html import escape
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

import querylog
import search

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend" / "dist"
SITE = "Prowl"
DESCRIPTION_CHARS = 200
CANONICAL_HOST = "prowl.nu"
REDIRECTED_HOSTS = {"www.prowl.nu", "web-production-b5a13.up.railway.app"}
CAUSES = ("load", "type", "filter", "page", "back")
MAX_REPORT = 2000  # bytes of a browser's report; they run to about 200


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.index = index = search.Index()
    app.state.known = {r["id"] for p in index.projects for r in p["records"]} | {e["id"] for p in index.projects for e in p["entries"]}
    app.state.log = querylog.QueryLog()
    yield
    app.state.log.close()


app = FastAPI(lifespan=lifespan)


@app.middleware("http")
async def canonical_host(request: Request, call_next):
    if request.headers.get("host", "").split(":")[0].lower() in REDIRECTED_HOSTS:
        return RedirectResponse(str(request.url.replace(scheme="https", netloc=CANONICAL_HOST)), status_code=301)
    return await call_next(request)


def log(request: Request, kind: str, data: dict) -> None:
    """Add what a request did to the query log, with the visit its headers name."""
    headers = request.headers
    app.state.log.put(querylog.visit(headers.get("x-visit")), kind, headers.get("x-internal") == "1", headers.get("user-agent"), data)


@app.get("/api/search")
def search_projects(
    request: Request,
    q: str = Query("", max_length=2000),
    source: Literal["surg", "expo", "theses", "nurj"] | None = None,
    year_from: int | None = Query(None, alias="from"),
    year_to: int | None = Query(None, alias="to"),
    n: int = Query(20, ge=1, le=50),
    offset: int = Query(0, ge=0),
) -> dict:
    years = None if year_from is None and year_to is None else (year_from or 0, year_to or 9999)
    start = time.perf_counter()
    results, total = app.state.index.search(q, source, years, n, offset)
    cause = request.headers.get("x-cause")
    log(request, "search", {
        "q": q.replace("\x00", ""),  # Postgres refuses JSON holding a NUL
        "source": source,
        "from": year_from,
        "to": year_to,
        "n": n,
        "offset": offset,
        "total": total,
        "results": [p["id"] for p in results],
        "ms": round((time.perf_counter() - start) * 1000),
        "seq": querylog.number(request.headers.get("x-seq")),
        "shown": querylog.number(request.headers.get("x-shown")),
        "cause": cause if cause in CAUSES else None,
    })
    return {"results": [search.public(p) for p in results], "total": total}


@app.get("/api/project/{number}")
def project(request: Request, number: int) -> dict:
    p = app.state.index.project(number)
    similar = app.state.index.similar(p) if p else []
    log(request, "project", {"number": number, "project": p and p["id"], "similar": [x["id"] for x in similar]})
    if p is None:
        raise HTTPException(404, "No project has this number.")
    return {"project": search.public(p), "similar": [search.public(x) for x in similar]}


@app.post("/api/event", status_code=204)
async def event(request: Request) -> Response:
    body = b""
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_REPORT:
            return Response(status_code=204)
    if (found := querylog.report(body, app.state.known)) and app.state.log.allow_report():
        visit, kind, internal, data = found
        app.state.log.put(visit, kind, internal, request.headers.get("user-agent"), data)
    return Response(status_code=204)


def description(r: dict) -> str:
    """A link preview's description: the start of the first abstract (a
    poster's, else a thesis's or paper's), or who won a title-only grant or
    wrote a title-only thesis."""
    listings = sorted((e for x in r["records"] for e in x.get("listings", [])), key=lambda e: e["id"])
    abstracts = [e["abstract"] for e in listings] + [x["abstract"] for x in r["records"] if x.get("abstract")]
    if abstracts:
        text = " ".join(abstracts[0].split())
        return text if len(text) <= DESCRIPTION_CHARS else text[:DESCRIPTION_CHARS].rsplit(" ", 1)[0] + "…"

    def names(people: list[str]) -> str:
        return " and ".join(people) if len(people) <= 2 else f"{', '.join(people[:-1])}, and {people[-1]}"

    if grant := next((x for x in r["records"] if x["kind"] == "grant"), None):
        return f"{'AY URG' if grant['source'] == 'ay_urg' else 'SURG'} {grant['year']} grant awarded to {names(grant['students'])}."
    x = next(x for x in r["records"] if x["kind"] in ("thesis", "paper"))
    what = f"{x['department']} honors thesis" if x["kind"] == "thesis" else "NURJ paper"
    return f"{what} by {names(x['students'])}, {x['year']}."


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
        # As the frontend shows a project whose sources print no title.
        name = r["title"] or (f"Untitled Project: {r['made_title']}" if r["made_title"] else "Untitled Project")
        title, desc = escape(f"{name} — {SITE}"), escape(description(r))
        head = (
            f'<meta name="description" content="{desc}" />'
            f'<meta property="og:title" content="{escape(name)}" />'
            f'<meta property="og:description" content="{desc}" />'
            f'<meta property="og:site_name" content="{SITE}" />'
            f'<meta property="og:type" content="article" />'
            '<meta name="twitter:card" content="summary" />'
        )
        return HTMLResponse(page.replace(f"<title>{SITE}</title>", f"<title>{title}</title>{head}"))

    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True))

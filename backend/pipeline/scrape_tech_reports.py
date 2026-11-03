"""Download the Computer Science department's technical reports into data/raw/cs_tech_reports/.

The department lists its technical reports on two pages, one per era:
post-2000 (NU-CS-YYYY-N, and the NU-EECS and NWU-EECS numbers before them)
and pre-1999 (NWU-CS-99-N and the Institute for the Learning Sciences'
tech_rep_N). Each report is a <p> under an <h2> for its year, with a link to
its PDF where the department has one. Undergraduate honors theses are among
them, unmarked: only a thesis's own title page says what it is.

Both pages are saved as fetched, as post-2000.html and pre-1999.html. Every
linked PDF is saved under documents/ at its path in the department's
documents folder, so the files keep the department's names without
colliding. reports.json lists
each report in page order: the page and year heading it is under, its report
number, the listing's text, and its PDF's URL, saved path and download
status (null where the listing has no link), and any other links the
listing gives, which are not downloaded (one, NU-EECS-12-03, links its
design files on its author's site).

The listings are kept as the page gives them, errors included: the 2013
heading lists NU-EECS-13-06 twice, once as "NWU-EECS-06-13", and
NWU-CS-03-27 links NWU-CS-04-30's PDF (03-27's own is not at the
matching address), so two PDFs are each listed twice. Nothing is filtered out, so
reports that are not honors theses are kept too.

Run from backend/: uv run python pipeline/scrape_tech_reports.py
"""

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "cs_tech_reports"
BASE = "https://www.mccormick.northwestern.edu/computer-science/research/tech-reports/"
PAGES = ["post-2000", "pre-1999"]
DOCUMENTS = "/computer-science/documents/"
HEADERS = {"User-Agent": "grantsearch/0.1 (student research search tool)"}

YEAR = re.compile(r"Reports published in (\d{4})", re.I)
# The report number the listing opens with: "NU-CS-2025-10", "NU-EECS-16-02",
# "NWU-EECS-09-20,", "NWU-CS-99-1:", "NU_EECS_12_05", "tech_rep_74,".
NUMBER = re.compile(r"^\s*((?:NU|NWU)[-_][A-Z]+[-_][\d_-]*\d|tech_rep_\d+)")


def get(client: httpx.Client, url: str) -> httpx.Response:
    for attempt in range(4):
        try:
            return client.get(url)
        except httpx.TransportError:
            if attempt == 3:
                raise
        time.sleep(2 ** attempt)


def fetch_page(client: httpx.Client, page: str, refresh: bool) -> str:
    path = OUT / f"{page}.html"
    if refresh or not path.exists():
        resp = get(client, BASE + f"{page}.html")
        resp.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
    return path.read_text(encoding="utf-8")


def segments(p) -> list[list]:
    """A paragraph's top-level nodes, split where a node opens with a report
    number: one paragraph holds two reports (NWU-EECS-09-04 and 09-03)."""
    out = [[]]
    for node in p.children:
        text = node.get_text(" ") if hasattr(node, "get_text") else str(node)
        if out[-1] and NUMBER.match(text.replace("\xa0", " ")):
            out.append([])
        out[-1].append(node)
    return out


def listings(page: str, html: str) -> list[dict]:
    """The reports on a page, in page order, each under the last year heading."""
    main = BeautifulSoup(html, "html.parser").find(id="main-content")
    out, year = [], None
    for el in main.find_all(["h2", "p"]):
        if el.name == "h2":
            year = int(YEAR.search(el.get_text(" ")).group(1))
            continue
        for nodes in segments(el):
            text = re.sub(r"\s+", " ", "".join(
                n.get_text("") if hasattr(n, "get_text") else str(n) for n in nodes)).strip()
            links = [a["href"] for n in nodes if hasattr(n, "find_all")
                     for a in ([n] if n.name == "a" else []) + n.find_all("a")
                     if a.get("href") and a["href"] != "#top"]
            if year is None or not (text or links) or text == "Return to Top":
                continue
            m = NUMBER.match(text)
            links = [urljoin(BASE + f"{page}.html", href).split("#")[0] for href in links]
            reports = [u for u in links if DOCUMENTS in u]
            if len(reports) > 1:
                raise SystemExit(f"more than one report link: {text[:100]!r}")
            out.append({
                "page": page,
                "year": year,
                "number": m.group(1) if m else None,
                "listing": text,
                "url": reports[0] if reports else None,
                "other_links": [u for u in links if u not in reports],
            })
    return out


def saved_path(url: str) -> Path:
    path = unquote(urlsplit(url).path)
    if DOCUMENTS not in path:
        raise SystemExit(f"PDF outside the documents folder: {url}")
    return OUT / "documents" / path.split(DOCUMENTS, 1)[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch the saved pages and PDFs")
    args = parser.parse_args()

    reports = []
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=120) as client:
        for page in PAGES:
            rows = listings(page, fetch_page(client, page, args.refresh))
            print(f"{page}: {len(rows)} reports, {sum(1 for r in rows if r['url'])} linked")
            reports += rows
        for r in reports:
            r["file"] = r["status"] = None
            if not r["url"]:
                continue
            path = saved_path(r["url"])
            r["file"] = str(path.relative_to(OUT))
            if path.exists() and not args.refresh:
                r["status"] = 200
                continue
            resp = get(client, r["url"])
            r["status"] = resp.status_code
            if resp.status_code == 200 and resp.content.startswith(b"%PDF"):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(resp.content)
            else:
                print(f"not saved ({resp.status_code}, {resp.headers.get('content-type')}): {r['url']}")
                r["file"] = None
            time.sleep(0.3)

    (OUT / "reports.json").write_text(json.dumps(reports, indent=2, ensure_ascii=False) + "\n")
    saved = sum(1 for r in reports if r["file"])
    print(f"wrote {len(reports)} reports to {OUT / 'reports.json'}; {saved} PDFs saved")


if __name__ == "__main__":
    main()

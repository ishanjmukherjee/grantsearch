"""Scrape Summer Undergraduate Research Grant (SURG) winner tables.

Fetches each year's winners page from the Office of Undergraduate Research
site, caches the raw HTML under data/raw/, and writes data/grants.json with one
record per project. Students who share a title within a year are grouped into a
single project with several awardees.

Usage: uv run python -m pipeline.scrape_surg [--refresh]
"""

import argparse
import json
import re
import unicodedata
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

BASE = "https://undergradresearch.northwestern.edu"
PAGES = {
    2020: f"{BASE}/2020-surg-winners/",
    2021: f"{BASE}/2021-summer-undergraduate-research-grant-winners/",
    2022: f"{BASE}/2022-summer-undergraduate-research-grant-winners/",
    2023: f"{BASE}/2023-summer-undergraduate-research-grant-winners/",
    2024: f"{BASE}/2024-summer-undergraduate-research-grant-winners/",
}
# 2020 has no header row; its columns are first name, last name, title.
DEFAULT_COLUMNS = ("first", "last", "title")
# The server drops connections that send httpx's default User-Agent.
HEADERS = {"User-Agent": "grantsearch/0.1 (student research search tool)"}

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RAW_DIR = DATA_DIR / "raw"


def fetch(year: int, url: str, refresh: bool) -> str:
    path = RAW_DIR / f"surg{year}.html"
    if path.exists() and not refresh:
        return path.read_text()
    resp = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=30)
    resp.raise_for_status()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(resp.text)
    return resp.text


QUOTES = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"'})


def clean(text: str) -> str:
    # Some titles carry Windows-1252 punctuation as raw C1 control characters.
    text = re.sub(r"[\x80-\x9f]", lambda m: bytes([ord(m.group())]).decode("cp1252"), text)
    text = unicodedata.normalize("NFKC", text).translate(QUOTES)
    return re.sub(r"\s+", " ", text).strip()


def column_roles(headers: list[str]) -> tuple[str, ...]:
    if not headers:
        return DEFAULT_COLUMNS
    roles = []
    for h in headers:
        h = h.lower()
        if "first" in h:
            roles.append("first")
        elif "last" in h:
            roles.append("last")
        elif "title" in h:
            roles.append("title")
        else:
            raise ValueError(f"unrecognized column header: {h!r}")
    return tuple(roles)


def parse(year: int, html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.select("article table")
    if len(tables) != 1:
        raise ValueError(f"{year}: expected 1 table, found {len(tables)}")
    table = tables[0]
    roles = column_roles([clean(th.get_text()) for th in table.select("thead th")])

    rows = []
    for tr in table.select("tbody tr"):
        cells = [clean(td.get_text()) for td in tr.find_all("td")]
        if len(cells) != len(roles):
            raise ValueError(f"{year}: row has {len(cells)} cells: {cells}")
        rows.append(dict(zip(roles, cells)))
    return rows


def title_key(title: str) -> str:
    return re.sub(r"[^\w]+", " ", title.casefold()).strip()


def group(year: int, rows: list[dict]) -> list[dict]:
    projects: dict[str, dict] = {}
    for row in rows:
        key = title_key(row["title"])
        if key not in projects:
            projects[key] = {
                "id": f"surg-{year}-{len(projects) + 1:03d}",
                "year": year,
                "title": row["title"],
                "awardees": [],
            }
        projects[key]["awardees"].append({"first": row["first"], "last": row["last"]})
    return list(projects.values())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch cached pages")
    args = parser.parse_args()

    projects = []
    for year, url in PAGES.items():
        rows = parse(year, fetch(year, url, args.refresh))
        grouped = group(year, rows)
        print(f"{year}: {len(rows)} awardees, {len(grouped)} projects")
        projects.extend(grouped)

    out = DATA_DIR / "grants.json"
    out.write_text(json.dumps(projects, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(projects)} projects to {out}")


if __name__ == "__main__":
    main()

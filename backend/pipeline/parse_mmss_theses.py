"""Read the MMSS senior theses out of a checkout of the private mmss-papers repository.

The Mathematical Methods in the Social Sciences program keeps its senior
theses in a SharePoint library that needs a Northwestern login, 1980 to
2024. The private mmss-papers repository backs it up: records.json, one
record per library item with the catalog's columns, and fields.jsonl, what
each of the 325 papers the library actually has prints about itself (title,
authors, date, advisors, abstract, funding), every string checked against
the paper's text. The other 814 items are the library's placeholder page for
a paper it doesn't have (and one item filed with another item's paper), so
for those only the catalog is known. Its checkout is read from MMSS_PAPERS,
by default mmss-papers-wt/mmss-papers beside this repository's grantsearch-wt.

One thesis per work. A joint thesis is catalogued once per author, as items
of the same title and year (or, where the library has the paper, the same
file); those items are one work. For each field the paper's own text is
used, and the catalog where the paper is silent or its text illegible:

- title: the paper's, else the catalog's.
- students: the paper's authors, else the catalog's (with any coauthors its
  notes name: "with Tony Colucci and Yan Ng"). A name is split at the
  catalog's surname for that person, where the catalog has one, and an
  author printed in capitals takes the catalog's case or is capitalized;
  a name in parentheses stays with the first name, as a preferred name
  ("Weijia (Cassie)").
- year: the year in the paper's date, else the catalog's; academic_year the
  year before it to it.
- advisor: the people the paper names as advisor, supervisor or reader,
  without degrees ("Ph.D."), joined with commas, or None (the catalog has
  no advisors).
- abstract: the paper's, or None.
- source: the paper's file on SharePoint, or the library for a work without one.

MMSS works also keep what only this library has: paper (whether the library
has it), funding (grants the paper credits), prizes (from the catalog's
notes, such as the Dacey awards) and items (the library item ids).

Used by pipeline.scrape_theses, which writes data/theses.json.
"""

import json
import os
import re
from pathlib import Path

from pipeline.parse_expo import PARTICLES

DEPARTMENT = "Mathematical Methods in the Social Sciences"
LIBRARY = "https://nuwildcat.sharepoint.com/sites/WNB-MMSS-Library/Thesis%20Library%20Public/"
DEFAULT_CHECKOUT = Path(__file__).resolve().parents[4] / "mmss-papers-wt" / "mmss-papers"


def checkout() -> Path:
    path = Path(os.environ.get("MMSS_PAPERS", DEFAULT_CHECKOUT))
    if not (path / "records.json").exists() or not (path / "fields.jsonl").exists():
        raise SystemExit(f"no mmss-papers checkout at {path} (set MMSS_PAPERS)")
    return path


def words(s: str | None) -> str:
    return " ".join(re.findall(r"\w+", (s or "").casefold()))


def works(records: list[dict]) -> list[list[dict]]:
    """The items grouped into works, each group ordered by item id, groups by their first item."""
    parent = {r["id"]: r["id"] for r in records}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    keys: dict[tuple, list[int]] = {}
    for r in records:
        if r["has_document"]:
            keys.setdefault(("file", r["sha256"]), []).append(r["id"])
        if r["title"]:
            keys.setdefault(("title", words(r["title"]), r["year"]), []).append(r["id"])
    for ids in keys.values():
        for i in ids[1:]:
            parent[find(i)] = find(ids[0])
    groups: dict[int, list[dict]] = {}
    for r in sorted(records, key=lambda r: r["id"]):
        groups.setdefault(find(r["id"]), []).append(r)
    return sorted(groups.values(), key=lambda g: g[0]["id"])


def recase(word: str, known: dict[str, str]) -> str:
    """A word of a name printed in capitals, in the catalog's case where it has the word."""
    return known.get(word.casefold()) or "-".join(p.capitalize() for p in word.split("-"))


def student(name: str, catalog: list[dict]) -> dict:
    """A {first, last} from an author as the paper prints them (see the module docstring)."""
    known = {w.casefold(): w for a in catalog for w in f"{a['first'] or ''} {a['last'] or ''}".split()}
    preferred = re.findall(r"\(([^)]*)\)", name)
    name = re.sub(r"\s*\([^)]*\)", "", name).strip()
    if "," in name:  # "Lim You Jie, Benedict": the name, then a preferred name
        name, rest = (p.strip() for p in name.split(",", 1))
        preferred.append(rest)
    if name.isupper():
        name = " ".join(recase(w, known) for w in name.split())
    parts = name.split()
    surnames = {w.casefold() for a in catalog if a["last"] for w in a["last"].split()}
    at = next((i for i, w in enumerate(parts) if w.casefold() in surnames and (i or len(parts) > 1)), None)
    if at is None:
        at = len(parts) - 1
        while at > 1 and parts[at - 1].casefold() in PARTICLES:
            at -= 1
    if at == 0:  # surname first ("Lim You Jie")
        first, last = parts[1:], parts[:1]
    else:
        first, last = parts[:at], parts[at:]
    first = " ".join(first) + "".join(f" ({p})" for p in preferred if p)
    return {"first": first.strip(), "last": " ".join(last)}


def catalog_students(group: list[dict]) -> list[dict]:
    """The catalog's authors of a work's items, and the coauthors their notes name."""
    out = [a for r in group for a in r["authors"]]
    for r in group:
        for name in r["coauthors"]:
            if not any(a["last"] and words(name).endswith(words(a["last"])) for a in out):
                *first, last = name.split()
                out.append({"first": " ".join(first), "last": last})
    seen, unique = set(), []
    for a in out:
        if (k := (words(a["first"]), words(a["last"]))) not in seen:
            seen.add(k)
            unique.append(a)
    return unique


# A degree after an advisor's name ("Molly Losh, Ph.D."), which would read
# as a second advisor once the names are joined with commas.
DEGREE = re.compile(r",?\s*\b(?:Ph\.?\s?D|M\.?D|M\.?A|M\.?S|J\.?D|MBA)\b\.?", re.I)


def advisor(name: str) -> str:
    return DEGREE.sub("", name).strip(" ,")


def year(date: str | None, catalog_year: int | None) -> int | None:
    """The year in the paper's date ("June 6, 2008", "5-26-87"), else the catalog's."""
    found = set(re.findall(r"(?<!\d)(?:19|20)\d\d(?!\d)", date or ""))
    if len(found) == 1:
        return int(found.pop())
    if not found and (m := re.fullmatch(r"\d{1,2}[-/]\d{1,2}[-/](\d\d)", (date or "").strip())):
        return 1900 + int(m.group(1)) if int(m.group(1)) > 30 else 2000 + int(m.group(1))
    return catalog_year


def parse() -> list[dict]:
    """The MMSS theses, one per work, ordered by year and then by library item id."""
    root = checkout()
    records = json.loads((root / "records.json").read_text())
    fields = {f["id"]: f["fields"] for f in map(json.loads, (root / "fields.jsonl").open())}
    out = []
    for group in works(records):
        paper = next((fields[r["id"]] for r in group if r["has_document"]), None)
        with_paper = next((r for r in group if r["has_document"]), None)
        catalog = catalog_students(group)
        catalog_year = next((r["year"] for r in group if r["year"]), None)
        students = [student(a, catalog) for a in paper["authors"]] if paper and paper["authors"] else catalog
        y = year(paper and paper["date"], catalog_year)
        out.append({
            "department": DEPARTMENT,
            "year": y,
            "academic_year": f"{y - 1}-{y}" if y else None,
            "students": students,
            "advisor": (", ".join(advisor(a["name"]) for a in paper["advisors"]) or None) if paper else None,
            "title": (paper and paper["title"]) or next((r["title"] for r in group if r["title"]), None),
            "abstract": paper and paper["abstract"],
            "source": with_paper["url"] if with_paper else LIBRARY,
            "paper": bool(with_paper),
            "funding": [f["name"] for f in paper["funding"]] if paper else [],
            "prizes": list(dict.fromkeys(p for r in group for p in r["prizes"])),
            "items": [r["id"] for r in group],
        })
    return sorted(out, key=lambda t: (t["year"] or 0, t["items"][0]))

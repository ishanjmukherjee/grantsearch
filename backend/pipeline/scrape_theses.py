"""Scrape department honors thesis lists into data/theses.json.

So far one department: Political Science, whose honors theses page lists
every thesis from 2010-11 on (but 2015-16) under its academic year, as a
heading "Student | Title" and a body with the abstract (labelled
"Abstract:" from 2017-18 on) and "Thesis Advisor: Name". The page is saved
as fetched in data/raw/theses/polisci.html, and parsing reads the saved copy.

Each thesis is a record:

- id: "polisci-YYYY-NNN", numbered in page order within its year
- department, year (the academic year's second, the graduating year),
  academic_year ("2024-2025")
- students: [{first, last}]; first is "" for the one student named by
  surname alone
- advisor (the names as printed, without "Professor"), title, source (the page)
- abstract, or None for the 10 the page has none for: the 8 of 2022-23
  ("[Update coming soon]"), one withheld for IRB reasons and one left blank

Usage: uv run python -m pipeline.scrape_theses [--refresh]
"""

import argparse
import json
import re

import httpx
from bs4 import BeautifulSoup

from pipeline.parse_expo import split_people, text
from pipeline.scrape_surg import DATA_DIR, HEADERS, RAW_DIR

SOURCES = {
    "polisci": ("Political Science", "https://polisci.northwestern.edu/undergraduate/honors/honors-theses.html"),
}
ACADEMIC_YEAR = re.compile(r"(\d{4})\s*-\s*(\d{4})")
# "Thesis Advisor:", once "Research Advisor:"; the last one in the body, so
# an abstract that mentions an advisor is not cut there.
# The plural's "s" is sometimes set apart from "Advisor" ("Advisor s:").
ADVISOR = re.compile(r"\b(?:Thesis|Research)\s+Advis[eo]r\s*s?\s*:?", re.I)
ABSTRACT_LABEL = re.compile(r"\s*Abstract\s*:?\s*", re.I)
# Titles before advisors' names ("Professor Chloe Thurston and Professor Grisinger").
HONORIFIC = re.compile(r"\b(?:Professor|Prof\.|Dr\.)\s+")
# Abstracts the page holds back: "[Update coming soon]" (all of 2022-23), and
# one withheld for IRB reasons.
NO_ABSTRACT = re.compile(r"\[Update coming soon\]|For IRB reasons, the abstract for this thesis is not publicly available\.?", re.I)


def fetch(key: str, refresh: bool) -> str:
    path = RAW_DIR / "theses" / f"{key}.html"
    if refresh or not path.exists():
        resp = httpx.get(SOURCES[key][1], headers=HEADERS, follow_redirects=True, timeout=60)
        resp.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
    return path.read_text(encoding="utf-8")


def block_text(el) -> str:
    """An element's text with inline tags joined as written (the page splits
    words across spans, "record</span><span>ed", and sets "20<sup>th</sup>"),
    and a space at each paragraph or line break."""
    for br in el.find_all(["br", "p", "h1", "li"]):
        br.insert_after(" ")
    return el.get_text("")


def students(names: str) -> list[dict]:
    """The students named in a heading; one is named by surname alone ("Svabek")."""
    if len(names.split()) == 1:
        return [{"first": "", "last": names}]
    return split_people(names, last_first=False)


def abstract(body: str) -> str | None:
    """The abstract without its label, or None where the page has none or holds it back."""
    # One abstract opens with a stray "p>" from the page's broken tag (2013).
    a = text(ABSTRACT_LABEL.sub("", re.sub(r"^\s*p>", "", body), count=1))
    return None if not a or NO_ABSTRACT.fullmatch(a) else a


def parse_polisci(html: str) -> list[dict]:
    """The theses in page order: each <h4> "Student | Title" under an <h3>
    academic year, with the <div> after it holding the abstract and advisor."""
    department, source = SOURCES["polisci"]
    main = BeautifulSoup(html, "html.parser").find("main")
    out, academic_year = [], None
    for el in main.find_all(["h3", "h4"]):
        if el.name == "h3":
            m = ACADEMIC_YEAR.search(el.get_text())
            academic_year = f"{m.group(1)}-{m.group(2)}"
            continue
        student, _, title = block_text(el).partition("|")
        body = text(block_text(el.find_next_sibling("div")))
        m = next(reversed(list(ADVISOR.finditer(body))), None)
        if not (academic_year and title.strip() and m):
            raise SystemExit(f"unparsed thesis: {el.get_text(' ')[:100]!r}")
        out.append({
            "department": department,
            "year": int(academic_year[-4:]),
            "academic_year": academic_year,
            "students": students(text(student)),
            "advisor": text(HONORIFIC.sub("", body[m.end():]).replace(" & ", " and ")),
            "title": text(title),
            "abstract": abstract(body[: m.start()]),
            "source": source,
        })
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch the saved pages")
    args = parser.parse_args()

    theses = []
    for key in SOURCES:
        rows = parse_polisci(fetch(key, args.refresh))
        counts: dict[int, int] = {}
        for t in rows:
            counts[t["year"]] = counts.get(t["year"], 0) + 1
            theses.append({"id": f"{key}-{t['year']}-{counts[t['year']]:03d}", **t})
        print(f"{key}: {len(rows)} theses")
    path = DATA_DIR / "theses.json"
    path.write_text(json.dumps(theses, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(theses)} theses to {path}")


if __name__ == "__main__":
    main()

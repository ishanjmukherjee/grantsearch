"""Scrape department honors thesis lists into data/theses.json.

Four departments so far. Two list their theses on a page, saved as
fetched in data/raw/theses/<key>.html and parsed from the saved copy:

- Political Science ("polisci") lists every thesis from 2010-11 on (but
  2015-16) under its academic year, as a heading "Student | Title" and a
  body with the abstract (labelled "Abstract:" from 2017-18 on) and "Thesis
  Advisor: Name".
- Economics ("econ") lists every thesis from 2001 on under its graduating
  year as "Student - Title", the title in italics: in bulleted lists from
  2020 on and in tables, one thesis to a cell, before. It gives no advisors
  or abstracts.

Computer Science ("cs") publishes its theses as technical reports instead,
read from their PDFs by pipeline.parse_cs_theses: 7 from 2022 on, each with
its advisor (but one) and abstract, and report, its report number.

Mathematical Methods in the Social Sciences ("mmss") keeps its theses in a
SharePoint library behind a Northwestern login, backed up in the private
mmss-papers repository and read from a checkout of it by
pipeline.parse_mmss_theses: 1,079 from 1980 to 2024, 321 of them with the
paper, which gives the advisor and abstract where it prints them. Running
this needs that checkout (see that module).

Each thesis is a record:

- id: "<key>-YYYY-NNN", numbered in page order (Computer Science: report
  order; MMSS: library item order) within its year
- department, year (the academic year's second, the graduating year),
  academic_year ("2024-2025")
- students: [{first, last}]; first is "" for the one student named by
  surname alone
- advisor (the names as printed, without "Professor"), or None for
  Economics and for the MMSS theses whose paper names none or isn't in the
  library. data/overrides.jsonl gives the one Computer Science thesis that
  names none its advisor, read from the thesis.
- title, source (the page, or for Computer Science the PDF, or for MMSS the
  paper on SharePoint, or the library where it doesn't have the paper)
- mmss (Economics only): whether the page marks the thesis for
  Interdisciplinary Honors with Mathematical Methods in the Social Sciences
- abstract, or None for all of Economics, for the 10 Political Science
  theses the page has none for (the 8 of 2022-23, "[Update coming soon]",
  one withheld for IRB reasons and one left blank) and for the MMSS theses
  without one
- MMSS only: paper (whether the library has it), funding, prizes and items
  (see pipeline.parse_mmss_theses)

Usage: uv run python -m pipeline.scrape_theses [--refresh]
"""

import argparse
import json
import re

import httpx
from bs4 import BeautifulSoup

from pipeline import parse_cs_theses, parse_mmss_theses
from pipeline.parse_expo import split_people, text
from pipeline.projects import OVERRIDES, merge_patch
from pipeline.scrape_surg import DATA_DIR, HEADERS, RAW_DIR

SOURCES = {
    "polisci": ("Political Science", "https://polisci.northwestern.edu/undergraduate/honors/honors-theses.html"),
    "econ": ("Economics", "https://economics.northwestern.edu/undergraduate/major/undergraduate-economics-honors-senior-theses.html"),
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


# The dash between an Economics student and title, which the page writes
# as "-", "–" or "—", spaced or not, inside or outside the italics. A dash
# inside a name ("Lal-Tabak") is never spaced.
SEPARATOR = re.compile(r"\s+[-\u2013\u2014]+(?:\s+|$)")
DASHES = re.compile(r"^[\s\-\u2013\u2014]+|[\s\-\u2013\u2014]+$")
# Three of the oldest Economics titles have their curly quotes in a symbol
# font, each as an italic run of its own: "A" opens a quote and "@" closes it.
SYMBOL_QUOTES = {"A": "\u201c", "@": "\u201d"}
ECON_SYMBOL_QUOTED = 3
# "*" after a title marks "Interdisciplinary Honors with Mathematical Methods
# in the Social Sciences".
MMSS_MARK = "*"


def parse_econ_entry(el) -> tuple[str, str, bool, bool]:
    """An Economics list item or table cell as its student, title, whether
    it is marked for MMSS honors, and whether its quotes were in the symbol
    font. The student is the text before the first italics, up to a spaced
    dash; the title is the rest (once, "Tom Del Carlo - Poverty<em>
    Alleviation through Trade?</em>", it starts before the italics)."""
    strings = el.find_all(string=True)
    first = next(i for i, x in enumerate(strings) if x.find_parent("em"))
    quoted = any(x.find_parent("em") and x.strip() == "@" for x in strings)
    student, *lead = SEPARATOR.split(text("".join(strings[:first])), maxsplit=1)
    rest = "".join(SYMBOL_QUOTES.get(x.strip(), x) if quoted and x.find_parent("em") else x for x in strings[first:])
    title = text(DASHES.sub("", " ".join(lead + [rest])))
    mmss = title.endswith(MMSS_MARK)
    return text(DASHES.sub("", student)), text(title.removesuffix(MMSS_MARK)), mmss, quoted


def parse_econ(html: str) -> list[dict]:
    """The theses in page order: each <li> under an <h5> year (2020 on) and
    each non-empty <td> of a table captioned with its year (2001-2019). A
    thesis two students wrote is listed once for each, one after the other;
    the two make one record."""
    department, source = SOURCES["econ"]
    main = BeautifulSoup(html, "html.parser").find("main")
    out, quoted = [], 0
    for el in main.find_all(["li", "td"]):
        if not el.get_text(strip=True):
            continue
        if el.name == "li":
            heading = el.find_previous("h5")
            while not heading.get_text(strip=True):
                heading = heading.find_previous("h5")
        else:
            heading = el.find_parent("table").caption
        year = int(heading.get_text(strip=True))
        student, title, mmss, symbol_quoted = parse_econ_entry(el)
        quoted += symbol_quoted
        if not (student and title) or len(student.split()) > 6 or re.search(r"\b(?:and|the|of)\b|[\u2013\u2014*]|\s-|-\s", student):
            raise SystemExit(f"unparsed thesis: {el.get_text(' ')[:100]!r}")
        if out and (out[-1]["year"], out[-1]["title"], out[-1]["mmss"]) == (year, title, mmss):
            out[-1]["students"] += students(student)
            continue
        out.append({
            "department": department,
            "year": year,
            "academic_year": f"{year - 1}-{year}",
            "students": students(student),
            "advisor": None,
            "title": title,
            "abstract": None,
            "mmss": mmss,
            "source": source,
        })
    if quoted != ECON_SYMBOL_QUOTED:
        raise SystemExit(f"expected {ECON_SYMBOL_QUOTED} titles quoted in the symbol font, found {quoted}")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch the saved pages")
    args = parser.parse_args()

    theses = []
    for key in SOURCES:
        rows = {"polisci": parse_polisci, "econ": parse_econ}[key](fetch(key, args.refresh))
        counts: dict[int, int] = {}
        for t in rows:
            counts[t["year"]] = counts.get(t["year"], 0) + 1
            theses.append({"id": f"{key}-{t['year']}-{counts[t['year']]:03d}", **t})
        print(f"{key}: {len(rows)} theses")
    for key, module in (("cs", parse_cs_theses), ("mmss", parse_mmss_theses)):
        rows = module.parse()
        counts = {}
        for t in rows:
            counts[t["year"]] = counts.get(t["year"], 0) + 1
            theses.append({"id": f"{key}-{t['year']}-{counts[t['year']]:03d}", **t})
        print(f"{key}: {len(rows)} theses")
    path = DATA_DIR / "theses.json"
    by_id = {t["id"]: i for i, t in enumerate(theses)}
    patched = 0
    for o in map(json.loads, (DATA_DIR / OVERRIDES).open()):
        if o["file"] == path.name:
            theses[by_id[o["id"]]] = merge_patch(theses[by_id[o["id"]]], o["patch"])
            patched += 1
    print(f"applied {patched} overrides from {OVERRIDES}")
    path.write_text(json.dumps(theses, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(theses)} theses to {path}")


if __name__ == "__main__":
    main()

"""Read the Computer Science honors theses out of the department's technical reports.

Computer Science publishes undergraduate theses as technical reports, which
pipeline/scrape_tech_reports.py saves in data/raw/cs_tech_reports/. The
listing does not mark them; THESES names the seven that are undergraduate
theses, found by reading every report's opening pages:

- Six have a title page saying so: "An undergraduate senior thesis submitted
  in partial fulfillment of the honors requirements" or "In partial
  fulfillment of the Honors requirements for the degree of Bachelor of Arts".
- NU-CS-2024-16 has no title page, but its author, Mercedes Sandu, is an
  Expo 2021 presenter and a SURG 2022 grantee.

Two other single-author theses name no degree and are left out:
NU-CS-2022-01 (Drew Kersnar, whose "thesis committee" had co-chairs, and
whose report is dated after his class year, so likely a master's thesis) and
NU-CS-2023-06 (Jackson Michaels).

Most reports open with the department's cover (number, date, title, author
and a short abstract) before the thesis's own title page and abstract; two
(NU-CS-2022-09, 2026-23) have no cover. Each thesis is read from its own
pages where it has them, and from the cover where it doesn't:

- title, students and advisor from the title page (the student's name as the
  listing gives it, checked against the page); the advisor is "Advisor:" or
  "Supervisor(s)" there, without "Dr." and "Ph.D.", several joined by "and".
  NU-CS-2024-16 names no advisor, so advisor is None here; the advisor
  read from its acknowledgements is a hand edit in
  data/thesis_overrides.jsonl, which scrape_theses applies.
- year from the title page's date (each is dated in the spring of the year
  the student graduates), academic_year the year before it to it.
- abstract: the text under the first "Abstract" heading from the title page
  on, to the next heading (Keywords, Contents, Acknowledgements, the
  introduction), without page numbers or the title and author the heading
  repeats. Superscripts, which the text layer sets as separate raised text,
  are written with a caret ("deg(f)^1.63"), and the two TeX math symbols
  NU-CS-2022-08's abstract uses that lack a Unicode mapping are restored
  ("≤" and "∈"). A word broken across lines is
  joined without its hyphen if the document spells it whole elsewhere or
  does not spell it hyphenated anywhere else, and keeps the hyphen if the
  document hyphenates it mid-line.

Each record also keeps report, the technical report number, and source, the
PDF's address.
"""

import json
import re

import pymupdf

from pipeline.parse_expo import split_people, text
from pipeline.scrape_surg import RAW_DIR

REPORTS = RAW_DIR / "cs_tech_reports"
DEPARTMENT = "Computer Science"
THESES = [
    "NU-CS-2022-08", "NU-CS-2022-09", "NU-CS-2024-09", "NU-CS-2024-12",
    "NU-CS-2024-16", "NU-CS-2025-10", "NU-CS-2026-23",
]

TITLE_PAGE = re.compile(r"undergraduate senior thesis|honors requirements?\s+for the degree", re.I)
# Lines on a title page that end the title.
AFTER_TITLE = re.compile(r"^(?:Northwestern University|Department of|An undergraduate|By)\b", re.I)
DATE = re.compile(r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\b\s*(?:\d{1,2})?,?\s*(\d{4})")
ADVISOR = re.compile(r"(?:Advisor:?|Supervisors?)\s*\n?\s*(.+)")
CREDENTIALS = re.compile(r"\b(?:Dr\.|Prof\.|Professor)\s+|,?\s*Ph\.\s?D\.?")
ABSTRACT = re.compile(r"^\s*abstract\s*$", re.I)
STOP = re.compile(
    r"^\s*(?:keywords|notation|(?:table of )?contents|acknowledge?ments|chapter 1|(?:\d+\.?\s+)?introduction\b.*|list of (?:figures|tables))\s*$",
    re.I,
)
# TeX's math symbol font (CMSY) in NU-CS-2022-08's abstract has no Unicode
# mapping for these, so the text layer gives its private-use placeholder for
# "≤" and the font's character code for "∈", checked against the page. TeX
# spaces relations itself, so the text layer has no spaces around them.
CMSY = str.maketrans({"\uf8ff": " ≤ ", "2": " ∈ "})
PAGE_NUMBER = re.compile(r"^\s*(?:\d+|[ivxlc]+)\s*$", re.I)


def lines(page) -> list[str]:
    """A page's lines in reading order, each run of superscript spans marked
    by one caret ("1", ".", "63" set raised give "^1.63"), and TeX math
    symbols that have no Unicode mapping restored (CMSY)."""
    out = []
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            s, raised = "", False
            for span in line["spans"]:
                t = span["text"]
                if span["font"].startswith("CMSY"):
                    t = t.translate(CMSY)
                sup = bool(span["flags"] & pymupdf.TEXT_FONT_SUPERSCRIPT) and bool(t.strip()) and bool(s.strip())
                if sup:
                    t = ("" if raised else "^") + t.strip()
                s += t
                raised = sup or (raised and not t.strip())
            out.append(s.strip())
    return out


def join_lines(rows: list[str], whole: str) -> str:
    """rows joined into one paragraph, with words broken across lines rejoined
    (see the module docstring); whole is the document's text, for lookups."""
    out = ""
    for row in rows:
        m = re.search(r"(\w+)-$", out)
        n = re.match(r"([a-z]\w*)", row)
        if m and n:
            joined, hyphenated = m.group(1) + n.group(1), f"{m.group(1)}-{n.group(1)}"
            keep = hyphenated.lower() in whole and joined.lower() not in whole
            out = out[:-1] + ("-" if keep else "") + row
        else:
            out += (" " if out else "") + row
    return out


def report_rows() -> dict[str, dict]:
    reports = json.loads((REPORTS / "reports.json").read_text())
    return {r["number"]: r for r in reports if r["number"] in THESES}


def parse_thesis(report: dict) -> dict:
    doc = pymupdf.open(REPORTS / report["file"])
    pages = [lines(p) for p in doc]
    whole = re.sub(r"\s+", " ", " ".join(p.get_text() for p in doc)).lower()
    student = re.match(r"\S+\s+(.+?),", report["listing"]).group(1)

    title_at = next((i for i, p in enumerate(pages[:5]) if TITLE_PAGE.search(" ".join(p))), None)
    if title_at is None:
        # No title page: the department's cover, "... Number, Date, Title, Name, Abstract".
        first = pages[0]
        date_at = next(i for i, s in enumerate(first) if DATE.search(s))
        name_at = first.index(student)
        title_lines, front, start = first[date_at + 1:name_at], first, 0
    else:
        front = [s for s in pages[title_at] if s]
        rows = [s for s in front if s.upper() != "NORTHWESTERN UNIVERSITY"]
        end = next(i for i, s in enumerate(rows) if s == student or AFTER_TITLE.match(s))
        title_lines, start = rows[:end], title_at
        if student not in front:
            raise SystemExit(f"{report['number']}: {student!r} not on its title page")
    title = text(" ".join(title_lines))
    year = int(next(DATE.search(s) for s in front if DATE.search(s)).group(1))

    advisor = None
    if title_at is not None:
        m = ADVISOR.search("\n".join(front))
        names = [CREDENTIALS.sub("", n).strip() for n in m.group(1).split(",")]
        advisor = " and ".join(n for n in names if n)

    body = [s for p in pages[start:] for s in p]
    at = next(i for i, s in enumerate(body) if ABSTRACT.match(s))
    rows = []
    for s in body[at + 1:]:
        if STOP.match(s):
            break
        if s and not PAGE_NUMBER.match(s):
            rows.append(s)
    # The heading may repeat the title and author before the abstract.
    while rows and (rows[0] == student or rows[0] in title_lines or rows[0].lower() in title.lower()):
        rows.pop(0)

    return {
        "department": DEPARTMENT,
        "year": year,
        "academic_year": f"{year - 1}-{year}",
        "students": split_people(student, last_first=False),
        "advisor": advisor,
        "title": title,
        "abstract": text(join_lines(rows, whole)),
        "report": report["number"],
        "source": report["url"],
    }


def parse() -> list[dict]:
    """The theses in report order (by year, then number)."""
    rows = report_rows()
    missing = set(THESES) - set(rows)
    if missing:
        raise SystemExit(f"not in reports.json: {sorted(missing)}")
    return [parse_thesis(rows[n]) for n in THESES]


if __name__ == "__main__":
    for t in parse():
        print(json.dumps(t, indent=2, ensure_ascii=False))

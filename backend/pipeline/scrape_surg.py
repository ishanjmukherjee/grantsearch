"""Scrape Summer Undergraduate Research Grant (SURG) winner lists, 2007-2024.

Each year's list is one web page. 2020-2024 are on the Office of Undergraduate
Research (OUR) site. Earlier years survive only in the Wayback Machine, each
read from a pinned capture (ARCHIVED): 2007-2009 from the Provost's
Undergraduate Research Grants site, 2010-2019 from OUR's earlier sites. 2014's
announcement page was never captured, but OUR's news listing showed it in full,
so it is read from a capture of that listing. No list for 2006 or earlier was
ever posted. The raw pages are cached under data/raw/surgYEAR.html.

The pages come in five layouts, each with its parser:

- 2007-2010: grouped under department headings, "Name*, "Title" Advisor:
  Name, Department"; * marks a project listed under more than one heading.
- 2011-2012: "Name (Majors), "Title" (Faculty Advisor: Name, Department)".
- 2013-2017 (2014 in the news listing): "Name (Majors) "Title"" with
  "Faculty Advisor:" (2013) or "Faculty Sponsor:" (2014-2017) on the next line.
  From 2014 the parenthesis starts with the student's school.
- 2018-2019: a table of last name, first name, title.
- 2020-2024: a table whose header row names the columns (2020 has none).

The pages before 2018 name each project's faculty advisor; "advisor" and
"sponsor" are the same role (the faculty member who supervises the project and
endorses the proposal), so both are recorded as advisors. They also mark some
grants as co-funded (by ISEN, a department fellowship and the like), kept
verbatim as the awardee's notes.

Writes data/grants.json with one record per project: students who share a title
within a year are one project with several awardees. A record has id, year,
title and awardees (first, last, and when the page gives them school, majors
as written, and notes); then advisors (name and department as given) and, for 2007-2010,
fields (the department headings it is listed under), when the page has them.

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
WAYBACK = "https://web.archive.org/web"
# Years read from the Wayback Machine: (capture timestamp, captured URL). Each
# is the latest capture of the year's list, checked to list the same projects
# as every other capture of it (some later captures only changed the page
# around the list).
ARCHIVED = {
    2007: ("20090214230045", "http://www.northwestern.edu:80/undergrad-research/awards/summer_grant_winners.htm"),
    2008: ("20090213155608", "http://www.northwestern.edu:80/undergrad-research/awards/summer_grant_winners08.htm"),
    2009: ("20100525211711", "http://www.northwestern.edu/undergrad-research/awards/summer_grant_winners09.htm"),
    2010: ("20140202045609", "https://undergradresearch.northwestern.edu/previous-winners-summer-urg"),
    2011: ("20140202052334", "http://undergradresearch.northwestern.edu/congratulations-2011-summer-urg-winners"),
    2012: ("20140202013058", "http://undergradresearch.northwestern.edu/urnu-news-and-events/2012-summer-urg-winners-announced"),
    2013: ("20140202011723", "http://undergradresearch.northwestern.edu/urnu-news-and-events/summer-undergraduate-research-grant-winners-2013-announced-congratulations"),
    2014: ("20140820084138", "http://undergradresearch.northwestern.edu/urnu-news-and-events/latest-news?page=1"),
    2015: ("20200711210035", "https://undergradresearch.northwestern.edu/summer-2015-grant-winners"),
    2016: ("20160601163758", "https://undergradresearch.northwestern.edu/2016-summer-undergraduate-research-grant-winners"),
    2017: ("20200711184032", "https://undergradresearch.northwestern.edu/2017-summer-undergraduate-research-grant-winners/"),
    2018: ("20200711183816", "https://undergradresearch.northwestern.edu/2018-summer-undergraduate-research-grant-winners"),
    2019: ("20200711134213", "http://undergradresearch.northwestern.edu/2019-summer-undergraduate-research-grant-winners"),
}
LIVE = {
    2020: f"{BASE}/2020-surg-winners/",
    2021: f"{BASE}/2021-summer-undergraduate-research-grant-winners/",
    2022: f"{BASE}/2022-summer-undergraduate-research-grant-winners/",
    2023: f"{BASE}/2023-summer-undergraduate-research-grant-winners/",
    2024: f"{BASE}/2024-summer-undergraduate-research-grant-winners/",
}
# The page each year's list is read from, for linking to it.
PAGES = {**{y: f"{WAYBACK}/{ts}/{url}" for y, (ts, url) in ARCHIVED.items()}, **LIVE}
# 2020 has no header row; its columns are first name, last name, title.
DEFAULT_COLUMNS = ("first", "last", "title")
# The server drops connections that send httpx's default User-Agent.
HEADERS = {"User-Agent": "grantsearch/0.1 (student research search tool)"}

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
RAW_DIR = DATA_DIR / "raw"


def fetch(year: int, refresh: bool) -> bytes:
    """The year's page as served: the live page, or for ARCHIVED years the
    capture's original bytes (Wayback's id_ form, without its toolbar)."""
    path = RAW_DIR / f"surg{year}.html"
    if path.exists() and not refresh:
        return path.read_bytes()
    if year in ARCHIVED:
        ts, url = ARCHIVED[year]
        url = f"{WAYBACK}/{ts}id_/{url}"
    else:
        url = LIVE[year]
    resp = httpx.get(url, headers=HEADERS, follow_redirects=True, timeout=60)
    resp.raise_for_status()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return resp.content


# Typographic ligatures (U+FB00-FB06: ff, fi, fl, ffi, ffl, long st, st) as
# the letters they join.
LIGATURES = {c: unicodedata.normalize("NFKC", chr(c)) for c in range(0xFB00, 0xFB07)}


# Curly quotes and apostrophes as the straight ones people type.
STRAIGHT = str.maketrans({"‘": "'", "’": "'", "ʼ": "'", "“": '"', "”": '"'})


def fold(text: str) -> str:
    """Text as matching should compare it: NFKC (math letters, superscripts and
    the like as plain characters) with straight quotes. For comparing only;
    stored text keeps its characters (see tidy)."""
    return unicodedata.normalize("NFKC", text).translate(STRAIGHT)


def tidy(text: str) -> str:
    """Text with its characters kept as the source has them: raw C1 control
    characters (Windows-1252 punctuation some pages carry) decoded, accents
    composed (NFC, which changes no character's identity), ligatures written
    as their letters, and whitespace collapsed. Unlike NFKC it keeps curly
    quotes, superscripts, ellipses and the like."""
    text = re.sub(r"[\x80-\x9f]", lambda m: bytes([ord(m.group())]).decode("cp1252"), text)
    text = unicodedata.normalize("NFC", text).translate(LIGATURES)
    return re.sub(r"\s+", " ", text).strip()


# Lower-case words that begin a surname ("Ludwig van Beethoven").
PARTICLES = {"van", "von", "den", "der", "de", "da", "del", "della", "di", "du", "dos", "la", "le", "al", "el"}
SUFFIXES = {"jr", "jr.", "sr", "sr.", "ii", "iii", "iv"}


def split_name(name: str) -> dict:
    """A full name as first and last: the last word (with a suffix such as Jr.
    and any particles before it) is the last name, the rest the first. Joining
    them with a space gives the name back. A name written "Last, First" is
    read that way."""
    if "," in name:
        last, first = (s.strip() for s in name.split(",", 1))
        return {"first": first, "last": last}
    words = name.split()
    cut = len(words) - 1
    if cut > 1 and words[cut].lower() in SUFFIXES:
        cut -= 1
    while cut > 1 and words[cut - 1].lower() in PARTICLES:
        cut -= 1
    return {"first": " ".join(words[:cut]), "last": " ".join(words[cut:])}


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


def parse_table(year: int, html: bytes) -> list[dict]:
    """2020-2024: the page's one table, named by its header row (2020 has none)."""
    soup = BeautifulSoup(html, "html.parser")
    tables = soup.select("article table")
    if len(tables) != 1:
        raise ValueError(f"{year}: expected 1 table, found {len(tables)}")
    table = tables[0]
    roles = column_roles([tidy(th.get_text()) for th in table.select("thead th")])

    rows = []
    for tr in table.select("tbody tr"):
        cells = [tidy(td.get_text()) for td in tr.find_all("td")]
        if len(cells) != len(roles):
            raise ValueError(f"{year}: row has {len(cells)} cells: {cells}")
        rows.append(dict(zip(roles, cells)))
    return rows


def parse_2018(year: int, html: bytes) -> list[dict]:
    """2018-2019: the page body's first table, without a header row: last
    name, first name, title. (The page's other tables are sidebar links.)"""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one("div.field-name-body")
    table = body.find("table") if body else None
    if table is None:
        raise ValueError(f"{year}: no table in the page body")
    rows = []
    for tr in table.find_all("tr"):
        cells = [tidy(td.get_text()) for td in tr.find_all("td")]
        if len(cells) != 3:
            raise ValueError(f"{year}: row has {len(cells)} cells: {cells}")
        rows.append(dict(zip(("last", "first", "title"), cells)))
    return rows


def lines(el) -> list[tuple[str, bool]]:
    """The text lines of an element: each innermost paragraph-like block,
    split at line breaks, tidied, without empty lines; each with whether its
    block is a heading (a heading element, or a paragraph holding a named
    anchor, as the 2007-2009 pages mark their department headings)."""
    for br in el.find_all("br"):
        br.replace_with("\n")
    blocks = [b for b in el.find_all(["p", "h1", "h2", "h3", "h4", "h5", "li"]) if not b.find(["p", "li"])]
    out = []
    for b in blocks:
        heading = b.name.startswith("h") or b.find("a", attrs={"name": True}) is not None
        out += [(t, heading) for line in b.get_text().split("\n") if (t := tidy(line))]
    return out


QUOTE = "“\""
# An advisor label, at a line's start or inline after the title, misspellings
# and all ("Advisor, Name" and "Adviosr:" in 2008-2009). A plural label lists
# several advisors, separated by semicolons.
ADVISOR = re.compile(r"\s*\(?(?:Faculty\s+)?(Advis[oe]r|Adviosr|Sponsor)(s?)\s*[:,]\s*")
# A note on how a grant was funded, on its own line after the entry (2012-2013).
NOTE = re.compile(r"\*?\s*(funded (?:by|in partnership with) .+)")
# Notes some years attach to the title or the advisor line.
TITLE_NOTE = re.compile(r"\s*\((URG-ISEN Grant)\)$")  # 2010
ADVISOR_NOTE = re.compile(r"\s+(\d{4} ISEN-URG Awardee)$")  # 2015
# What an asterisk after a name means, where the page says and no note line
# follows (2007-2010 asterisks mark cross-listing, which fields records).
STAR_NOTE = {2011: "URG-ISEN award recipient"}
# A funding note at the end of an advisor line (2013).
NOTE_AT_END = re.compile(r"\s*" + NOTE.pattern + "$")
SCHOOL = re.compile(r"School|College|Medill|McCormick|Weinberg|Bienen|Feinberg|NU in Qatar|NU-Q")


def entry(year: int, text: str, advisor: tuple[str, bool] | None) -> dict:
    """One student's entry, from its line ("Name* (Majors), "Title"" or, in
    2010, "Name*, Majors, "Title"") and its advisor text with whether its
    label was plural; 2010-2012 put the advisor on the entry's own line."""
    if inline := ADVISOR.search(text):
        if advisor is not None:
            raise ValueError(f"{year}: two advisors for {text!r}")
        text, advisor = text[: inline.start()], (text[inline.end() :], bool(inline.group(2)))
    at = min(i for i in (text.find(q) for q in QUOTE) if i >= 0)
    who, title = text[:at].strip().rstrip(",").strip(), text[at + 1 :].strip()
    out: dict = {"notes": []}

    if m := TITLE_NOTE.search(title):
        out["notes"].append(m.group(1))
        title = title[: m.start()]
    title = title.rstrip().removesuffix(",").rstrip()
    if title[-1:] in "”\"":
        title = title[:-1]
    # 2014 and 2015 put the sentence's period inside the closing quote.
    if year in (2014, 2015) and title.endswith("."):
        title = title[:-1]
    out["title"] = title.strip()

    study = None
    if m := re.fullmatch(r"(.*?)\s*\((.*)\)", who):
        who, study = m.group(1), m.group(2)
    elif "," in who:  # 2010: "Name*, Majors,"
        who, study = (s.strip() for s in who.split(",", 1))
    star = who.endswith("*")
    out["name"] = who.rstrip("*").strip()
    if study:
        if year >= 2014:  # "School, Major; Major"
            school, _, study = study.partition(",")
            if not SCHOOL.search(school):
                raise ValueError(f"{year}: no school in {school!r}")
            out["school"] = school.strip()
        # Kept as written: majors are separated by commas, semicolons or
        # "and", which also occur inside major names.
        if study.strip():
            out["majors"] = study.strip()
    if star and year in STAR_NOTE:
        out["notes"].append(STAR_NOTE[year])

    if advisor is not None:
        advisor, plural = advisor
        advisor = advisor.strip().removesuffix(")").strip()
        if m := ADVISOR_NOTE.search(advisor):
            out["notes"].append(m.group(1))
            advisor = advisor[: m.start()]
        advisor = re.sub(r"\s+funded by$", "", advisor)  # 2013: the start of the next line's note
        if m := NOTE_AT_END.search(advisor):
            out["notes"].append(m.group(1))
            advisor = advisor[: m.start()]
        out["advisors"] = []
        for one in advisor.split(";") if plural else [advisor]:
            name, _, department = one.partition(",")
            out["advisors"].append({"name": name.strip(), "department": department.strip() or None})
    return out


def open_title(found: list[dict]) -> bool:
    """Whether the last entry's title is still open: its opening quote is not
    closed and no advisor follows, on its line or the next."""
    if not found or found[-1]["advisor"] is not None or ADVISOR.search(found[-1]["line"]):
        return False
    return found[-1]["line"].count("“") > found[-1]["line"].count("”")


def entries(year: int, text_lines: list[tuple[str, bool]], headings: bool) -> list[dict]:
    """The entries in a list's lines. An entry line holds a quoted title; an
    advisor line and funding notes may follow it. With headings (2007-2010), a
    heading (by its markup, or a line with no quote, colon or comma) names the
    department the entries that follow are listed under; without, lines before
    the first entry are introduction. Any other line is an error."""
    found, field = [], None
    for line, heading in text_lines:
        if m := ADVISOR.match(line):
            if not found or found[-1]["advisor"] is not None:
                raise ValueError(f"{year}: advisor line without its entry: {line!r}")
            found[-1]["advisor"] = (line[m.end() :], bool(m.group(2)))
        elif m := NOTE.fullmatch(line):
            if not found:
                raise ValueError(f"{year}: note before any entry: {line!r}")
            found[-1]["notes"].append(m.group(1))
        elif open_title(found):
            found[-1]["line"] += " " + line  # a title broken across lines (2008)
        elif headings and (heading or not re.search(r"[“\":,]", line)):
            field = line
        elif any(q in line for q in QUOTE):
            found.append({"line": line, "advisor": None, "notes": [], "field": field})
        elif line.startswith("*") or " | " in line:
            continue  # the legend for asterisks; a row of links to department headings
        elif found:
            raise ValueError(f"{year}: unexpected line: {line!r}")
    out = []
    for f in found:
        e = entry(year, f["line"], f["advisor"])
        e["notes"] += f["notes"]
        if f["field"]:
            e["field"] = f["field"]
        out.append(e)
    return out


def list_element(year: int, soup: BeautifulSoup):
    """The element of a 2007-2017 page that holds the list."""
    if year <= 2009:
        el = soup.select_one("table.nobold")
    elif year <= 2013:
        el = soup.select_one("div.node div.content")
    elif year == 2014:  # the announcement's item in the news listing
        link = soup.find("a", href=re.compile(r"summer-2014-undergraduate-research-grant-winners-announced"))
        el = link and link.find_parent("div", class_="views-row").select_one(".views-field-body")
    else:
        el = soup.select_one("div.field-name-body")
    if el is None:
        raise ValueError(f"{year}: list not found")
    return el


def parse_prose(year: int, html: bytes) -> list[dict]:
    """2007-2017: one entry per student, as student and title rows with the
    page's extra details (school, majors, notes, advisor, field)."""
    rows = []
    for e in entries(year, lines(list_element(year, BeautifulSoup(html, "html.parser"))), headings=year <= 2010):
        student = split_name(e["name"]) | {k: e[k] for k in ("school", "majors") if k in e}
        if e["notes"]:
            student["notes"] = e["notes"]
        rows.append({"student": student, "title": e["title"], "advisors": e.get("advisors", []), "field": e.get("field")})
    return rows


def parse(year: int, html: bytes) -> list[dict]:
    """The year's rows: per student, the student (first, last and any details)
    and title, with the advisors and field where the page gives them."""
    if year <= 2017:
        return parse_prose(year, html)
    rows = parse_2018(year, html) if year <= 2019 else parse_table(year, html)
    return [{"student": {"first": r["first"], "last": r["last"]}, "title": r["title"], "advisors": [], "field": None} for r in rows]


def title_key(title: str) -> str:
    return re.sub(r"[^\w]+", " ", title.casefold()).strip()


def group(year: int, rows: list[dict]) -> list[dict]:
    """Projects: the rows of one title in a year, in page order. A student
    listed more than once (under several department headings) is one awardee."""
    projects: dict[str, dict] = {}
    for row in rows:
        key = title_key(row["title"])
        if key not in projects:
            projects[key] = {"id": f"surg-{year}-{len(projects) + 1:03d}", "year": year, "title": row["title"], "awardees": [], "advisors": [], "fields": []}
        p = projects[key]
        s = row["student"]
        same = next((a for a in p["awardees"] if (a["first"], a["last"]) == (s["first"], s["last"])), None)
        if same is None:
            p["awardees"].append(dict(s))
        else:  # listed again: keep the details either listing gives
            for k, v in s.items():
                if same.setdefault(k, v) != v:
                    raise ValueError(f"{year}: {s['first']} {s['last']} listed twice with different {k}")
        # One per advisor: students of one project may give the department differently.
        p["advisors"] += [a for a in row["advisors"] if a["name"] not in {b["name"] for b in p["advisors"]}]
        if row["field"] and row["field"] not in p["fields"]:
            p["fields"].append(row["field"])
    return [{k: v for k, v in p.items() if v != [] or k == "awardees"} for p in projects.values()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch cached pages")
    args = parser.parse_args()

    projects = []
    for year in sorted(PAGES):
        rows = parse(year, fetch(year, args.refresh))
        grouped = group(year, rows)
        advised = sum(1 for p in grouped if "advisors" in p)
        print(f"{year}: {len(rows)} rows, {len(grouped)} projects, {advised} with advisors")
        projects.extend(grouped)

    out = DATA_DIR / "grants.json"
    out.write_text(json.dumps(projects, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(projects)} projects to {out}")


if __name__ == "__main__":
    main()

"""Parse the academic-year URG winner pages saved in data/raw/ay_urg/ into data/records/ay_urg.jsonl.

Academic-year Undergraduate Research Grants were announced a cycle at a
time, 2006-07 to 2014-15, on pages pipeline.fetch_ay_urg saved from the
Wayback Machine (PAGES gives each page's academic year and cycle). Each
entry names a student, with their school and majors from 2010-11 on, the
project's title and its faculty advisor or sponsor (both recorded as
advisors, as in pipeline.scrape_surg), "Name, Department". The pages come
in five layouts:

- 2006-09, one page: each academic year under its own heading, entries
  grouped under department headings, "Name, "Title" Advisor: Name,
  Department". A student listed under more than one heading is one awardee;
  the headings are kept as the record's fields.
- 2010-11's October post: the winners alone, "Name (School - Majors),",
  with no titles or advisors.
- 2010-11 to 2013-14, a post per cycle: "Name (Majors), "Title"", the
  advisor inline or on the next line. From 2012-13 the parenthesis may start
  with the student's school ("WCAS, Anthropology"). An asterisk after a name
  means what the post's legend says ("*indicates ISEN-URG winner"); a line
  "***funded by ISEN" is a funding note.
- 2013-14 winter quarter: the same, inside a capture of OUR's news listing,
  as its own post was never captured.
- 2014-15, a page per quarter in sections: Academic Year URGs, Conference
  Travel Grants and Undergraduate Language Grants.

Every entry is kept, as a grant of its kind (extra.grant):

- Academic Year URGs.
- Conference Travel Grants, which pay for presenting work at a conference.
  Where a post lists them among the URGs without a section (2012-13's 4th
  and 5th cycles, 2013-14's fall quarter), an entry is a travel grant when
  the venue follows its title ("poster to be presented at ..."); the venue
  is kept. Robert Dorfman's 2013 grant, to chair a session, has no title of
  his own (the quoted title is the session's); what it was for is kept as
  its purpose.
- Undergraduate Language Grants (2014-15), for language study abroad: no
  title, and what the student will study as the purpose ("will study Arabic
  at the Arabic Language Intensive Program in Egypt.").

Writes data/records/ay_urg.jsonl (see pipeline.records), one record per
project: students of one academic year who share a title (and kind of
grant) are one project with several awardees; an entry without a title is
a record of its own. A record's year is the first year of its academic year
(2013 for 2013-14), as a SURG's is the summer before that academic year,
and its records are numbered in page order within that year, those without
a title after those with one. Its url is the capture it was read from; its
extra has the grant, the academic_year, the cycle as the page names it, and
where given the venue, the purpose and the 2006-09 department headings
(fields).

Usage: uv run python -m pipeline.parse_ay_urg
"""

import re

from bs4 import BeautifulSoup

from pipeline import records
from pipeline.fetch_ay_urg import ARCHIVED, SOURCE
from pipeline.scrape_surg import RAW_DIR, SUFFIXES, lines, split_name, title_key

URG = "Academic Year URG"
TRAVEL = "Conference Travel Grant"
LANGUAGE = "Undergraduate Language Grant"

# Saved page: (academic year, cycle as the page names it). 2006-09 gives its
# academic years in headings, and no cycles.
PAGES = {
    "2006-09_previous-winners-academic-year-urg": (None, None),
    "2010-11_new-academic-year-urg-winners": ("2010-11", "1st cycle"),
    "2010-11_november-urg-winners": ("2010-11", "2nd cycle"),
    "2010-11_december-urg-winners": ("2010-11", "3rd cycle"),
    "2010-11_january-urg-winners": ("2010-11", "4th cycle"),
    "2010-11_february-urg-winners": ("2010-11", "5th cycle"),
    "2011-12_october-urg-winners": ("2011-12", "1st cycle"),
    "2011-12_november-urg-winners-0": ("2011-12", "November 2011"),
    "2011-12_recent-academic-year-urg-winners": ("2011-12", "Winter Quarter"),
    "2012-13_fall-quarter-urg-winners": ("2012-13", "Fall Quarter"),
    "2012-13_4th-cycle": ("2012-13", "4th cycle"),
    "2012-13_5th-cycle": ("2012-13", "5th cycle"),
    "2013-14_fall-quarter": ("2013-14", "Fall Quarter 2013"),
    "2013-14_latest-news-page-1": ("2013-14", "Winter Quarter"),
    "2014-15_fall-2014-winners": ("2014-15", "Fall 2014"),
    "2014-15_winter-2015-grant-winners": ("2014-15", "Winter 2015"),
}
# Posts that list Conference Travel Grants among the URGs, without a section.
MIXED = {"2012-13_4th-cycle", "2012-13_5th-cycle", "2013-14_fall-quarter"}
# Posts that name their winners alone.
NAMES_ONLY = {"2010-11_new-academic-year-urg-winners"}
WINTER_2014 = "congratulations-winter-quarter-academic-year-urg-winners"

QUOTES = "“\""
CLOSING = "”\""
ADVISOR = re.compile(r"\s*\(?(?:Faculty\s+)?(?:Advis[oe]r|Sponsor)s?\s*:\s*")
STAR_LEGEND = re.compile(r"\*\s*indicates\s+(.+)", re.IGNORECASE)
FUNDING = re.compile(r"\*+\s*(funded (?:by|in partnership with) .+)", re.IGNORECASE)
FUNDING_AT_END = re.compile(r"\s*" + FUNDING.pattern + "$", re.IGNORECASE)
ACADEMIC_YEAR = re.compile(r"(\d{4})-(\d{2})")
# 2014-15's section headings.
SECTIONS = {r"Academic Year Undergraduate Research Grant Winners": URG, r"Conference Travel Grant Winners": TRAVEL, r"Undergraduate Language Grant Winners": LANGUAGE}
# Lines around the entries that are neither entries nor headings.
FURNITURE = re.compile(r"Link:|There is one more academic year deadline.*|Academic Year Undergraduate Research Grants|Learn more about Academic Year URGs|CONGRATULATIONS!|(?:Fall|Winter|Spring) 20\d\d|The next deadline for URG submissions is .*", re.IGNORECASE)
# What a mixed post's entry says before its title that is not the student's.
URG_PREFIX = re.compile(r",?\s*Academic Year Grant for$")
# A travel grant for something other than the student's own work.
NOT_THEIR_WORK = re.compile(r",?\s*(Selected to chair the session .+)", re.IGNORECASE)
# A Language Grant's entry: "Name (School, Majors) will study ...".
LANGUAGE_ENTRY = re.compile(r"(.+?\))\s+(will study .+)")
# The October 2010 post's entries: "Name (School - Majors)," the last but one
# followed by "and".
NAME_ENTRY = re.compile(r"(.+?\(.+\))\s*,?(?:\s+and)?")
# A school at the start of a student's parenthesis ("WCAS, Anthropology").
SCHOOL = re.compile(r"(?:WCAS|Weinberg(?: College of Arts and Sciences)?|McCormick(?: School of Engineering and Applied Science)?|Medill(?: School of Journalism)?|School of Communication|SESP|School of Education and Social Policy|Bienen(?: School of Music)?|School of Continuing Studies)")
SCHOOL_FIRST = re.compile(rf"({SCHOOL.pattern})(?:\s*[,;]\s*|\s+(?=[A-Z])|$)(.*)")
# The October 2010 post's "WCAS/SoC - RTVF, Psychology": schools in capitals.
SCHOOL_DASH = re.compile(r"([A-Za-z/]+) - (.+)")


def content(name: str, soup: BeautifulSoup):
    """The element of a saved page that holds its list."""
    if name == "2013-14_latest-news-page-1":
        link = soup.find("a", href=re.compile(WINTER_2014))
        el = link and link.find_parent("div", class_="views-row").select_one(".views-field-body")
    elif name.startswith("2014-15"):
        el = soup.select_one("div.field-name-body")
    else:
        el = soup.select_one("div.node div.content")
    if el is None:
        raise ValueError(f"{name}: list not found")
    return el


def student(who: str, star_note: str | None) -> dict:
    """A student from the text before their entry's title: "Name* (School,
    Majors)," or "Name,"."""
    who = who.strip().rstrip(",").strip()
    study = None
    if m := re.fullmatch(r"(.*?)\s*,?\s*\((.*)\)\s*,?", who):
        who, study = m.group(1), m.group(2).strip()
    star = who.endswith("*")
    out = split_name(who.rstrip("*").strip().rstrip(",").strip())
    if study and (m := SCHOOL_FIRST.fullmatch(study) or SCHOOL_DASH.fullmatch(study)):
        out["school"], study = m.group(1), m.group(2).strip()
    if study:
        out["majors"] = study  # as written, as SURG keeps them
    if star:
        if not star_note:
            raise ValueError(f"asterisk without a legend: {who!r}")
        out["notes"] = [star_note]
    return out


def advisors(text: str) -> list[dict]:
    """The advisors after an advisor label: "Name, Department", several
    separated by semicolons ("Richard Ashley, School of Music; Brady Clark and
    Stefan Kaufmann, Linguistics"). A semicolon followed by no comma is inside
    a department ("William Leonard, Anthropology; Global Health")."""
    text = re.sub(r"\s+and$", "", text.strip().removesuffix(")").strip())
    groups: list[str] = []
    for part in text.split(";"):
        if groups and "," not in part:
            groups[-1] += ";" + part
        else:
            groups.append(part)
    out = []
    for g in groups:
        names, _, department = (s.strip() for s in g.partition(","))
        # "Dalton Surmeier, Jr., Physiology"
        if (first := department.split(",")[0].strip()).lower().rstrip(".") in SUFFIXES:
            names, department = f"{names} {first}", department[len(first) :].lstrip(", ").strip()
        for name in re.split(r"\s+and\s+|\s*&\s*", names):
            if parts := records.name_parts(name):
                out.append(records.person("advisor", parts, department=department or None))
    return out


def title_and_rest(text: str) -> tuple[str, str]:
    """A title starting at text's opening quote, and what follows its closing
    quote (a venue, or nothing). The title ends at the last closing quote
    before a venue, so quotes inside it ("Reconstruction of an Ordovician
    "Sea Scorpion"") stay; a sentence's period or comma inside the closing
    quote ("Ethics."", 2013-14 on) is dropped."""
    body = text[1:]
    venue = re.search(r"[”\"]\s*,?\s*(?:(?:poster|paper|project)\s+)?(?:to be\s+)?(?:presented|preseted|at\s)", body)
    end = venue.start() if venue else max(body.rfind(q) for q in CLOSING)
    if end < 0:  # never closed
        end = len(body)
    title, rest = body[:end].strip(), body[end + 1 :].strip()
    title = re.sub(r"(?<!\.\.)[.,]$", "", title).strip()
    if title.count('"') % 2:  # an inner quote whose closing one ended the title
        title += '"'
    return title, rest.lstrip(",. ").strip()


def entry(person: dict, title: str | None, grant: str, academic_year: str, field: str | None, line_no: int, venue: str | None = None, purpose: str | None = None) -> dict:
    return {"student": person, "title": title, "advisors": [], "grant": grant, "academic_year": academic_year, "venue": venue, "purpose": purpose, "field": field, "line": line_no}


def page_entries(name: str, html: bytes) -> list[dict]:
    """A page's entries, as {student, title, advisors, grant, academic_year,
    venue, purpose, field, line}."""
    academic_year, _ = PAGES[name]
    grant = None if name in MIXED else URG
    field = star_note = None
    found: list[dict] = []
    pending_advisor = False  # a label whose names are on the next line (2012-13)

    for line_no, (line, heading) in enumerate(lines(content(name, BeautifulSoup(html, "html.parser"))), 1):
        if name.startswith("2006-09") and heading:
            if ACADEMIC_YEAR.fullmatch(line):
                academic_year, field = line, None
            else:
                field = line
            continue
        if section := next((g for pattern, g in SECTIONS.items() if re.fullmatch(pattern, line, re.IGNORECASE)), None):
            grant = section
            continue
        if m := STAR_LEGEND.fullmatch(line):
            star_note = m.group(1)
            continue
        if pending_advisor or (m := ADVISOR.match(line)):
            if not found or found[-1]["advisors"]:
                raise ValueError(f"{name}: advisor line without its entry: {line!r}")
            # Every work of the entry's line (two on one line, 2012-13).
            for e in found:
                if e["line"] == found[-1]["line"]:
                    e["advisors"] = advisors(line if pending_advisor else line[m.end() :])
            pending_advisor = not found[-1]["advisors"] and not pending_advisor
            continue
        if m := FUNDING.fullmatch(line):
            if not found:
                raise ValueError(f"{name}: note before any entry: {line!r}")
            found[-1]["student"].setdefault("notes", []).append(m.group(1))
            continue
        if name in NAMES_ONLY and (m := NAME_ENTRY.fullmatch(line)):
            found.append(entry(student(m.group(1), star_note), None, URG, academic_year, field, line_no))
            continue
        if grant == LANGUAGE:
            if not (m := LANGUAGE_ENTRY.fullmatch(line)):
                raise ValueError(f"{name}: unexpected Language Grant line: {line!r}")
            found.append(entry(student(m.group(1), star_note), None, LANGUAGE, academic_year, field, line_no, purpose=m.group(2)))
            continue
        at = min((i for i in (line.find(q) for q in QUOTES) if i >= 0), default=-1)
        if at < 0:
            if found and not FURNITURE.fullmatch(line):
                raise ValueError(f"{name}: unexpected line: {line!r}")
            continue  # an introduction before the first entry

        inline = ADVISOR.search(line, at)
        text, advisor_text = (line[: inline.start()], line[inline.end() :]) if inline else (line, None)
        # A funding note after the title, on its line (2013-14).
        funding = FUNDING_AT_END.search(text)
        if funding:
            text = text[: funding.start()]
        if other := NOT_THEIR_WORK.search(text):
            e = entry(student(text[: other.start()], star_note), None, TRAVEL, academic_year, field, line_no, purpose=other.group(1))
            if advisor_text is not None:
                e["advisors"] = advisors(advisor_text)
            found.append(e)
            continue
        who, works_text = text[:at].strip(), text[at:]
        entry_grant = grant
        if URG_PREFIX.search(who):
            who, entry_grant = URG_PREFIX.sub("", who), URG
        # A line opening with a quote is the previous student's next work (2012-13).
        person = student(who, star_note) if who else dict(found[-1]["student"])
        if funding:
            person.setdefault("notes", []).append(funding.group(1))
        # Two works on one line, each with its venue (2012-13): "...” poster
        # to be presented at A and “...” poster to be presented at B".
        for work in re.split(r"\s+and\s+(?=“)", works_text):
            title, venue = title_and_rest(work)
            kind = entry_grant or (TRAVEL if venue else URG)
            if venue and kind != TRAVEL:
                raise ValueError(f"{name}: text after a URG's title: {line!r}")
            e = entry(person, title, kind, academic_year, field, line_no, venue=venue or None)
            if advisor_text is not None:
                e["advisors"] = advisors(advisor_text)
            found.append(e)
    return found


def projects(entries: list[dict]) -> list[dict]:
    """Records: the entries of one title and kind of grant in an academic
    year, in page order; an entry without a title is a record of its own. A
    student listed more than once (under several department headings) is one
    awardee. Records are numbered within the first year of the academic year,
    those without a title after those with one."""
    groups: dict[tuple, dict] = {}
    for i, e in enumerate(entries):
        key = (e["academic_year"], e["grant"], title_key(e["title"]) if e["title"] else i)
        if key not in groups:
            groups[key] = {**e, "students": [], "advisors": [], "fields": [], "venues": []}
        g = groups[key]
        s = e["student"]
        same = next((a for a in g["students"] if (a["first"], a["last"]) == (s["first"], s["last"])), None)
        if same is None:
            g["students"].append(dict(s))
        else:
            for k, v in s.items():
                if same.setdefault(k, v) != v:
                    raise ValueError(f"{e['academic_year']}: {s['first']} {s['last']} listed twice with different {k}")
        g["advisors"] += [a for a in e["advisors"] if (a["first"], a["last"]) not in {(b["first"], b["last"]) for b in g["advisors"]}]
        for k, v in (("fields", e["field"]), ("venues", e["venue"])):
            if v and v not in g[k]:
                g[k].append(v)

    out, counts = [], {}
    for g in [g for g in groups.values() if g["title"]] + [g for g in groups.values() if not g["title"]]:
        year = int(g["academic_year"][:4])
        counts[year] = counts.get(year, 0) + 1
        people = [records.person("student", s) for s in g["students"]] + g["advisors"]
        extra = {"grant": g["grant"], "academic_year": g["academic_year"], "cycle": g["cycle"], "venue": "; ".join(g["venues"]) or None, "purpose": g["purpose"], "fields": g["fields"] or None}
        out.append(records.record(f"ayurg-{year}-{counts[year]:03d}", SOURCE, "grant", year, g["title"], people, None, g["url"], extra=extra))
    return out


def url(name: str) -> str:
    timestamp, original = ARCHIVED[name]
    return f"https://web.archive.org/web/{timestamp}/{original}"


def main() -> None:
    entries = []
    for name in PAGES:
        path = next((RAW_DIR / SOURCE / "wayback").glob(f"{name}_*.html"))
        found = page_entries(name, path.read_bytes())
        for e in found:
            e |= {"cycle": PAGES[name][1], "url": url(name)}
        counts = ", ".join(f"{n} {g}" for g in (URG, TRAVEL, LANGUAGE) if (n := sum(e["grant"] == g for e in found)))
        untitled = sum(not e["title"] for e in found)
        unadvised = sum(not e["advisors"] for e in found)
        print(f"{name}: {counts}" + (f", {untitled} without a title" if untitled else "") + (f", {unadvised} without advisors" if unadvised else ""))
        entries += found
    records.write(SOURCE, projects(entries))


if __name__ == "__main__":
    main()

"""Parse the Leopold Fellows pages saved in data/raw/leopold/ into data/records/leopold.jsonl.

The Chabraja Center for Historical Studies pays undergraduates of any major,
Leopold Fellows, to work as research assistants on a faculty member's
history project (see pipeline.fetch_leopold). Its pages list each academic
year's fellows, 2008-09 to 2026-27: the student, often with class and
school, the faculty mentor, the project and the quarters worked, and an
asterisk for a returning fellow. The Library Leopold Fellows of 2026-27,
library student employees rather than research assistants, are left out.

Every saved capture of the lists is read (PAGES), and each academic year is
read from every capture that lists it, since the lists change after they are
first posted: fellows are added and dropped (2014-15's list had 13 fellows in
February 2015 and has 9 now), names are corrected ("Sofia Franco" becomes
"Sofia Lopez Franco"), classes advance ("rising junior" becomes "junior"),
and the pages written before 2014 print surnames in capitals, which the
current page no longer does for 2008-13. A year's fellows are those of every
capture that lists it, matched by name across captures (see align). What a
fellow's entry says is the newest capture's, but for where their surname
starts, taken from a capture printing it in capitals; every value another
capture prints differently is kept in the record (extra.variants), with the
captures that print it, and so is every fellow only older captures list
(with the captures listing them, as listed_by). Nothing a capture prints
about a fellow is dropped.

A run fails, naming every case at once, on a line inside a year's list that
is neither an entry nor known furniture (FURNITURE), and on a fellow listed
in some captures of a year but missing from a newer capture that lists the
year, unless DROPPED names them: those are checked by hand, since the newer
capture may have dropped a fellow who never took up the fellowship.

The pages come in these layouts:

- 2008-09, first posted in August 2008 as each faculty project followed by
  its fellow ("1. Professor Josef Barton: Mexican rural women ...--Marcella
  CASTILLO (winter/spring 2009);"), then as each fellow with a description
  of their work ("Cristina BURACK (senior) working winter/spring 2009 with
  Professor Benjamin Frommer on Czechs and Czechoslovakia ...").
- 2009-10, the same with varied verbs ("is researching all academic year
  ... with Professor T.H. BREEN how a Dutch company ...").
- 2010-11 to 2012-13: "Sarah COLLINS (Medill senior) working with Prof. Carl
  Smith—City Water, City Life (summer and Fall 2010)", the project's title
  after a dash.
- 2013-14 on: the title in quotes, "Name (class, school), working with Prof.
  First SURNAME on "Title" (quarters)", sometimes numbered.

Where a fellow's entry gives a description instead of a title (2008-10, and
a few later entries such as "on a book about Latino history over the past
500 years"), the description is kept as extra.description and the record's
title comes from the Center's list of faculty projects for that year, if it
lists the project: the Word file of 2008-09 projects, the 2009-10 research
page, and the calls for applications for 2010-11 and 2012-13 (OFFERED). A
listed project gives its record its abstract, the faculty member's own
description of the project. A fellow is matched to a listed project of the
same year and mentor whose title has the same words as theirs, or, for a
fellow with a description, by MATCHED, read by hand: a mentor sometimes
listed one project and took a fellow on another (T.H. Breen listed the
Scots-Irish in New England for 2009-10 and his fellow worked on maple syrup
speculation).

Writes data/records/leopold.jsonl (see pipeline.records), one record per
project and academic year: the fellows of one year who work with one mentor
on one title (or one description) are one record, with the fellows as
students and the mentor as advisor; a fellow on two projects is in each.
Records of one project in different years are joined by links, not here. A
record's year is the first year of its academic year, as for the AY URGs,
and records are numbered within it in the order of the newest capture
listing the year. Its url is the newest capture's: the live page, or the
capture on the Wayback Machine. Each fellow has, where given, their level
("rising junior"), school as printed, another name the parenthesis with
their class and school gives ("Sienna LAURENT (Yun Jin CHOI, senior, ...)",
other_name; a preferred name in parentheses after a given name stays in
first, as records keep it), the quarters they worked (terms), returning (the asterisk),
and listed_by (above). The mentor is named one way in all their records: the
form the pages print most, with capitals (see same_mentor); a form printed
otherwise is a variant. The record's extra has the academic_year, every
entry as printed (lines), the variants, the description, the listed project
matched (offered: its title, requirements and url) and notes the page gives
("originally Prof. Sarah Pearsall"). A variant is {fellow, field, value,
captures}, a capture given by its Wayback timestamp, or the live pages by
the day they were saved (LIVE_SAVED); field project with value null is a capture not listing that
project for the fellow, and a capture leaving out a level, school or
quarters is not a variant.

Usage: uv run python -m pipeline.parse_leopold
"""

import re
import subprocess
import sys
from collections import Counter
from difflib import SequenceMatcher

from bs4 import BeautifulSoup

from pipeline import records
from pipeline.fetch_leopold import ARCHIVED, LIVE, SOURCE
from pipeline.scrape_surg import RAW_DIR, lines, tidy

RAW = RAW_DIR / SOURCE
# When the live pages were saved (see pipeline.fetch_leopold).
LIVE_SAVED = {"live/main.html": "20261106", "live/previous.html": "20261107"}
# Saved pages that list fellows. The others are the calls for applications and
# faculty project lists (OFFERED).
PAGES = [p for p in [*LIVE, *ARCHIVED] if p.startswith(("live/", "wayback/", "wayback-pre2015/old-leopold", "wayback-pre2015/old-previous"))]
WORD_FILE = "wayback-pre2015/old-Leopoldfacultyprojects_20100609020013.doc"
# Saved page or Word file listing faculty projects: (academic year, layout).
OFFERED = {
    WORD_FILE: ("2008-09", "word"),
    "wayback-pre2015/old-Leopoldresearch2009-2010_20100609032657.html": ("2009-10", "colon"),
    "wayback-pre2015/old-CallfornewLF_20100609015408.html": ("2010-11", "dash"),
    "wayback-pre2015/old-LFCallforApplications_20120523152421.html": ("2012-13", "dash"),
}

ACADEMIC_YEAR = re.compile(r"(20\d\d)\s*[-–]\s*(?:20)?(\d\d)\b")
# A line that starts a year's list: short, naming the year and its fellows.
# Lines naming a year's faculty projects or call, or the Library Fellows, end
# a list without starting one.
HEADING = re.compile(r"(?=.*\bfellows\b)(?!.*\b(?:call|projects for)\b)(?!.*\bfellowships\b).*" + ACADEMIC_YEAR.pattern + r".*", re.I)
END = re.compile(r"library fellows:?|\d{4}-\d{4} history faculty projects:?|history faculty research projects .*|call for .*|\d{4}-\d{4} leopold fellowships.*", re.I)
# The sidebars and footers of the pages before 2016, after their lists.
SIDEBAR = re.compile(r"(?:announcements\b|events\b|northwestern university //|(?:nicholas d\. )?chabraja center for historical studies$).*", re.I)
MAX_HEADING = 80

# Lines inside a list that are neither entries nor headings: the asterisk's
# legend, captions, notes and the pages' furniture.
FURNITURE = re.compile(
    r"\*\s*(?:an\s+)?asterisk denotes .*|and their faculty research projects.*|for 2009-2010 we received .*"
    r"|.*(?:talks to|presents the|reports on|listen with|spoke about|presented their|tells the|meet with|listening to|at their archival|explaining their"
    r"|met at|lunch|started work in|had been working through).*"
    r"|(?:the|each|students|university president|recently|exploring)\b.{60,}|the portrait .*|nu alumnus .*|\"my leopold .*|leopold fellows (?:do not|present) .*|leopold"
    r"|archival research information session .*|\(art research center.*"
    r"|congratulations to .*|(?:note: )?more detailed descriptions .*|for details and descriptions .*|for more information.*|scroll down.*"
    r"|graduating leopold fellows.*|spring 20\d\d|[-*_]{5,}|undergrads .*",
    re.I,
)

LEVEL = r"(?:rising\s+)?(?:freshman|sophomore|junior|senior)"
VERB = re.compile(r"\b(?:continues working|continuing work|working|worked|is (?:researching|exploring|working|examining|preparing))\b")
TITLE_PREFIX = re.compile(r"(?:Prof(?:essor)?|Prod|prof|professor)\.?\s+")
QUOTE_OPEN = "“\"”"
QUOTE_CLOSE = "”\"“"
# Words of a name: capitalized, initials, or particles.
NAME_WORD = re.compile(r"(?:[A-ZÀ-ÖØ-Þİ][\w'’.\-]*|[A-Z]\.(?:[A-Z]\.)*|(?:van|von|de|da|del|la|le|di|du|bin|al)(?=\s))")

# Saved page: {the start of an entry: the academic year it starts}, for lists
# whose heading a capture lost (it was an image, or deleted).
MISSING_HEADINGS = {
    "wayback-pre2015/old-previous-leopold-fellows_20150227133525.html": {"Brian Earl (WCAS junior)": "2012-13"},
    "wayback/previous_20170430130027.html": {"Martin AMESQUITA (WCAS senior)": "2013-14"},
}
# (Academic year, fellow): why a fellow older captures list is missing from a
# newer one, checked against every later capture. All are kept.
DROPPED = {
    ("2013-14", "teresa spinelli"): "listed by both February 2014 captures with Robert Lerner's German refugee scholar project; later lists give her only under 2012-13",
    ("2014-15", "alexandra baxter"): "listed in February 2015; in no later list",
    ("2014-15", "zachary elvove"): "listed in February 2015; in no later list",
    ("2014-15", "vivien hastings"): "listed in February 2015; in no later list",
    ("2014-15", "lydia xiao"): "listed in February 2015; in no later list",
    ("2017-18", "victor saavedra"): "listed in January 2018; in no later list",
    ("2018-19", "peyton greenberg"): "listed in April 2019; in no later list",
    ("2018-19", "aidan ziliak"): "listed in April 2019 as continuing; later lists give him only under 2017-18",
    ("2020-21", "milena deguere"): "listed in 2020 with Helen Tilley; later lists give her under 2021-22 with Sarah Cushman",
    ("2020-21", "margot ricketts"): "listed in 2020; in no later list",
    ("2020-21", "shloka shetty"): "listed in 2020; in no later list",
    ("2020-21", "dylan zou"): "listed in 2020; in no later list",
    ("2021-22", "may nguyen"): "listed in July 2021; in no later list",
}
# (Academic year, fellow): the title of the listed project of their mentor the
# fellow worked on, read by hand where the fellow's entry gives a description
# or a title worded otherwise; "" for a project the 2008-09 Word file lists
# without a title. Left out: Margaret Donnelly (2008-09), on "colonial America
# at the onset of the Revolution" with T.H. Breen, whose listed project is
# Kate Stephensen's on coastal Maine; Stephanie Asplundh (2009-10), on maple
# syrup speculation, where Breen listed the Scots-Irish in New England; and
# Hana Suckstorff (2009-10), on a treatise on the Great Schism, where Robert
# Lerner listed Ernst Kantorowicz's letters (he listed the treatise for 2010-11).
MATCHED = {
    ("2008-09", "cristina burack"): "",
    ("2008-09", "marcela castillo"): "Crumbs of Fresh Bread for Everyone: Mexican Rural Women and the Reconstruction of Community",
    ("2008-09", "laura colee"): "",
    ("2008-09", "stephanie denotto"): "",
    ("2008-09", "julia hotopp"): "Small Business in Poor Urban Communities",
    ("2008-09", "huiju jeon"): "",
    ("2008-09", "jasmine nazek"): "The Unknowns: Skepticism in Early Modern Venice",
    ("2008-09", "jack neubauer"): "Go Directly to Jail: The Punitive Turn in American Life",
    ("2008-09", "kate stephensen"): "",
    ("2009-10", "heidi beth dessecker"): "Small Business in Poor Urban Communities",
    ("2009-10", "esther divovich"): "Ukrainian Jewish poet in Soviet newspapers of the 1930s and 1940s",
    ("2009-10", "richard h murphy"): "Go Directly to Jail: The Punitive Turn in American Life",
    ("2009-10", "parvathi santosh kumar"): "Marketplace Solutions: Southern Segregationists and the Surprising Career of School Vouchers",
    ("2009-10", "devin l sizer"): "Civil rights in 19th-C. Washington, D.C",
    ("2009-10", "craig spencer"): "War Orphan Adoption",
    ("2009-10", "sisi tang"): "Chinese Modernity",
    ("2012-13", "teresa spinelli"): "Biography of an Eminent Historian",
}


def capture(page: str) -> str:
    """A page's capture timestamp, or the day the live page was saved."""
    return LIVE_SAVED.get(page) or ARCHIVED[page][0]


def page_url(page: str) -> str:
    if page in LIVE:
        return LIVE[page]
    ts, url = ARCHIVED[page]
    return f"https://web.archive.org/web/{ts}/{url}"


def academic_year(text: str) -> str:
    m = ACADEMIC_YEAR.search(text)
    return f"{m.group(1)}-{m.group(2)}"


def page_lines(page: str) -> list[str]:
    soup = BeautifulSoup((RAW / page).read_bytes(), "html.parser")
    for el in soup(["script", "style", "nav", "header", "footer"]):
        el.decompose()
    return [t for t, _ in lines(soup.body or soup)]


def caps(word: str) -> bool:
    """Whether a word is a surname printed in capitals: all its letters upper
    case but for a prefix such as Mc, Mac or De ("McALLISTER", "DeROSE")."""
    if re.fullmatch(r"(?:[A-Z]\.)+", word):  # initials ("T.H.")
        return False
    letters = re.sub(r"[^\w]", "", re.sub(r"^(?:Mc|Mac|De|Le|La|Di|Du|Da|O’|O')", "", word))
    return len(letters) >= 2 and letters.isupper() and not letters.isdigit()


def recase(word: str) -> str:
    """A surname printed in capitals in title case, a prefix kept
    ("DeROSE" -> "DeRose", "PETROVSKY-SHTERN" -> "Petrovsky-Shtern")."""
    if not caps(word) or re.fullmatch(r"[IVX]+", word):  # a numeral ("STEIN II")
        return word
    m = re.match(r"(Mc|Mac|De|Le|La|Di|Du|Da|O’|O')?(.*)", word)
    return (m.group(1) or "") + re.sub(r"[^\W\d_]+", lambda w: w.group()[0] + w.group()[1:].lower(), m.group(2))


def split(name: str) -> dict:
    """A printed name as {first, last, caps}: the surname is its words in
    capitals where it prints them so ("Ana Karin ITURRALDE ZURITA"), else its
    last word with any particles (records.name_parts); caps says which."""
    words = name.split()
    i = len(words)
    while i > 0 and caps(words[i - 1]):
        i -= 1
    if 0 < i < len(words):
        return {"first": " ".join(words[:i]), "last": " ".join(recase(w) for w in words[i:]), "caps": True}
    parts = records.name_parts(name) or {"first": "", "last": name}
    return {**parts, "caps": False}


def key(name: str) -> str:
    return " ".join(records.words(name))


def dehyphenate(text: str, vocabulary: set[str]) -> str:
    """Text with the hyphens of words broken across lines removed ("His-tory",
    "PE-TROVSKY-SHTERN"): a hyphenated word that the pages never print
    otherwise, and that without one of its hyphens is a word they print."""

    def fix(m: re.Match) -> str:
        w = m.group()
        for i in [i for i, c in enumerate(w) if c == "-"]:
            joined = w[:i] + w[i + 1 :]
            if joined.casefold() in vocabulary:
                return joined
        return w

    return re.sub(r"[^\W\d_]+(?:-[^\W\d_]+)+", fix, text)


def info(text: str) -> dict:
    """A fellow's parenthesis as {level, school, other_name}: "(sophomore,
    WCAS)", "(WCAS and Bienen Music School senior)", "(Yun Jin CHOI, senior,
    School of Communication/WCAS)"."""
    out = {}
    if m := re.search(LEVEL, text, re.I):
        out["level"] = " ".join(m.group().split()).lower()
        before, after = text[: m.start()], text[m.end() :]
        parts = [p.strip(" ,") for p in (before, after)]
        if parts[0] and "," in before and any(caps(w) for w in parts[0].split()):
            other = split(parts[0])
            out["other_name"], parts[0] = f"{other['first']} {other['last']}".strip(), ""  # "Yun Jin CHOI, senior, ..."
        school = " ".join(p for p in parts if p).strip(" ,")
    else:
        school = text.strip(" ,")
    if school:
        out["school"] = school
    return out


def strip_quotes(title: str) -> str:
    """A title without the quotes around it, keeping quotes inside it ("'The
    Wisdom of the Peoples': African Decolonization ...")."""
    t = title.strip().rstrip(",.;").strip()
    if t and t[0] in QUOTE_OPEN:
        t = t[1:]
        if t and t[-1] in QUOTE_CLOSE:
            t = t[:-1]
        # A quote closed early ("The Wisdom of the Peoples”: African ...") or
        # around part of the title ("Les Misérables” in the United States).
        t = re.sub(r"^([^“”\"]+)[”\"](?=\s*[:\w(])", r"\1", t)
        if t.count("(") > t.count(")"):  # "Spies and Censorship in Mexico” (The Mexican ... (MIDAS) Project"
            t += ")"
    return t.strip().strip("“”\"").strip()


def mentor_and_rest(text: str) -> tuple[str | None, str]:
    """The mentor's name at the start of text, after "with"/"for" and a
    title, and the text after it. The name is its words in capitals and those
    before them where it has any (so "Nancy MacLEAN Southern segregationists"
    ends at MacLEAN), else every name word up to the first that is not one."""
    text = re.sub(r"^\s*(?:with|for)\b\s*", "", text)
    text = TITLE_PREFIX.sub("", text, count=1) if TITLE_PREFIX.match(text) else text
    text = re.sub(r"^((?:[A-Z]\.)+)(?=[A-Z])", r"\1 ", text)  # "T.H.BREEN", "T.H.Breen"
    text = re.sub(r"^((?:\S+\s+){0,3}[^\s—–]+?)\s*([—–])\s*", r"\1 \2 ", text, count=1)  # "Prof. Carl Smith—City Water"
    words = []
    for m in re.finditer(r"\S+", text):
        w = m.group()
        core = w.rstrip(",;:—–)")
        if not NAME_WORD.fullmatch(core):
            break
        words.append(core)
        if core != w:
            break
    if any(caps(w) for w in words):
        last = max(i for i, w in enumerate(words) if caps(w))
        words = words[: last + 1]
    name = " ".join(words)
    rest = text[len(name) :] if text.startswith(name) else text[text.find(words[-1]) + len(words[-1]) :] if words else text
    return (name or None), rest


def projects_of(rest: str) -> list[dict]:
    """The projects after an entry's verb: each {mentor, title, description,
    terms, note}. Most entries have one; a few two ("... (summer 2021) and
    with Prof. Henry BINFORD (F/W/S) on "Small Business ..." (F/W/S)", or two
    titles with one mentor)."""
    rest = rest.strip()
    pre_terms = None
    # Quarters before the mentor ("working winter/spring 2009 with ...", "is
    # researching all academic year (Fall 2009, ...) with ...").
    if not re.match(r"(?:with|for)\b|(?:Prof|prof|Professor|Prod)\b", rest):
        m = re.match(r"(.*?)\s*\b(with|for)\b\s*", rest)
        if not m:
            raise ValueError(f"no mentor: {rest!r}")
        pre = re.sub(r"^in the\s+", "", m.group(1).strip())
        if pre.startswith("(") and pre.count("(") > pre.count(")"):  # "is preparing (all academic year with ..."
            pre = pre[1:]
        pre_terms = pre.strip() or None
        rest = rest[m.start(2) :]
    parts = re.split(r"(?<=\))\s+and\s+(?=with\b|[“\"])|\s+and\s+(?=with\s+(?:Prof|Professor)\b)", rest)
    out, mentor = [], None
    for part in parts:
        part = part.strip()
        if re.match(r"(?:with|for)\b", part) or TITLE_PREFIX.match(part):
            mentor, part = mentor_and_rest(part)
        out.append(project(mentor, part, pre_terms))
    return out


def project(mentor: str | None, text: str, pre_terms: str | None) -> dict:
    """One project from the text after its mentor's name."""
    note = terms = None
    text = text.strip()
    if m := re.match(r"\(\s*(originally [^)]*)\)\s*", text):  # "(originally Prof. Sarah Pearsall)"
        note, text = m.group(1), text[m.end() :]
    text = re.sub(r"^\)\s*", "", text)  # "is preparing (all academic year with Professor X) a ..."
    if m := re.match(r"\(([^)]*)\)\s*", text):  # "with Henry BINFORD (F/W/S) on ..."
        terms, text = m.group(1), text[m.end() :]
    if m := re.match(r"in (summer \d{4})\s*", text):  # "with Professor Caitlin FITZ in summer 2018 on ..."
        terms, text = m.group(1), text[m.end() :]
    # The quarters at the end: the last parenthesis, if it names quarters.
    text = text.strip().rstrip(";,.").strip()
    if m := re.search(r"\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)\s*\.?\s*$", text):
        inner = m.group(1)
        if re.search(r"summer|fall|winter|spring|quarter|year|\b[FWS](?:/|\b)|semester", inner, re.I) and not re.match(r"[A-Z][a-z]+ [A-Z]", inner):
            inner = inner.strip(" .")
            # Quarters after the mentor and after the title too: one if the same, both if not.
            terms, text = (terms + "; " + inner if terms and terms != inner else inner), text[: m.start()]
    # "(The Mexican Intelligence Digital Archives (MIDAS) Project (summer 2017, F/W/S)": an unclosed parenthesis.
    if m := re.search(r"\s*\(([^()]*\([^()]*\)[^()]*)\(([^()]*)\)\s*$", text):
        text, terms = text[: m.start()] + " (" + m.group(1).strip() + ")", m.group(2)
    elif m := re.search(r"\(([^()]*\b(?:summer|fall|winter|spring|quarters?|year)\b[^()]*)\)?\s*$", text, re.I):
        terms, text = m.group(1), text[: m.start()]
    if pre_terms:
        terms = pre_terms + ("; " + terms if terms else "")
    text = text.strip().rstrip("—–-,;.").strip()
    title = description = None
    if m := re.match(r"(?:—|–|-|:)\s*(.*)", text, re.S):  # "Prof. Carl Smith—City Water, City Life"
        title = strip_quotes(m.group(1).rstrip("—– "))
    elif m := re.match(r"(?:on\s+)?(?:his\s+|a\s+)?([“\"”].*)", text):
        title = strip_quotes(m.group(1))
    elif text:
        description = re.sub(r"^on\s+", "", text).strip()
    return {"mentor": mentor, "title": title or None, "description": description or None, "terms": terms, "note": note}


def parse_entry(line: str) -> dict | None:
    """A fellow's entry: {star, name, info, projects}, or None if the line is
    not one."""
    text = re.sub(r"^\d+\.\s*", "", line.strip())
    m = VERB.search(text)
    if not m:
        return None
    head, rest = text[: m.start()].strip(" ,—–-"), text[m.end() :]
    star = head.startswith("*") or bool(re.search(r"\*\s*(?:\(|$)", head))
    head = head.lstrip("* ").strip()
    details = {}
    if pm := re.search(r"\(([^()]*)\)\s*$", head):
        inner = pm.group(1)
        if re.search(LEVEL, inner, re.I) or re.search(r"WCAS|SESP|Medill|Music|Communication|Journalism|McCormick|Weinberg|Bienen", inner):
            details, head = info(inner), head[: pm.start()].strip()
    name = head.rstrip("* ,").strip()
    if not name or len(name.split()) > 6 or not re.match(r"[(\"A-ZÀ-Þ]", name):
        return None
    try:
        projects = projects_of(rest)
    except ValueError:
        return None
    return {"star": star, "name": name, "info": details, "projects": projects}


def project_first(line: str) -> dict | None:
    """An entry of the first 2008-09 list: "1. Professor Josef Barton:
    description--Marcella CASTILLO (winter/spring 2009);"."""
    m = re.fullmatch(r"\d+\.\s*Professor\s+(.+?):\s*(.+?)\s*--\s*(.+?)\s*\(([^)]*)\);?\.?", line.strip())
    if not m:
        return None
    description = re.sub(r"\s*\([^)]*needed\)?$", "", m.group(2)).strip()
    return {"star": False, "name": m.group(3), "info": {}, "projects": [{"mentor": m.group(1), "title": None, "description": description, "terms": m.group(4), "note": None}]}


def starts_entry(text: str) -> bool:
    """Whether a line opens a fellow's entry: a name, perhaps with a
    parenthesis after it, then the entry's verb."""
    m = VERB.search(text)
    if not m:
        return False
    head = re.sub(r"\([^)]*\)|[\"“”*]", " ", re.sub(r"^\d+\.\s*", "", text[: m.start()])).strip(" ,—–-")
    words = head.split()
    return 0 < len(words) <= 6 and all(w[0].isupper() or w in records.PARTICLES for w in words)


def page_entries(page: str) -> tuple[dict[str, list[dict]], list[str]]:
    """A page's entries by academic year, each {star, name, info, projects,
    line, page}, and the lines in its lists it could not read.

    An entry may be broken across lines (the pre-2015 pages break them where
    the editor's window did): a line continues the entry before it when that
    entry has not ended at a closing parenthesis, period or semicolon, or when
    the line opens with the entry's verb."""
    by_year: dict[str, list[dict]] = {}
    unread: list[str] = []
    year = None
    pending = ""
    group = None  # "SPECIAL Summer Leopold Fellows working with ...": the entries after it are names alone

    def add(text: str) -> None:
        nonlocal group
        if m := re.match(r"SPECIAL (.+?) working with (.*)", text):
            group = projects_of("with " + m.group(2))
            if re.match(r"summer\b", m.group(1), re.I):  # "SPECIAL Summer Leopold Fellows"
                group = [p | {"terms": p["terms"] or "summer"} for p in group]
            return
        e = project_first(text) or parse_entry(text)
        if e is None and group and (m := re.fullmatch(r"(\*?\s*.+?)\s*\(([^()]*)\)", text)):
            e = {"star": m.group(1).startswith("*"), "name": m.group(1).lstrip("* "), "info": info(m.group(2)), "projects": [dict(p) for p in group]}
        if e is not None:
            by_year.setdefault(year, []).append(e | {"line": text, "page": page})
        elif not FURNITURE.fullmatch(text):
            unread.append(f"{page} [{year}]: {text}")

    for text in page_lines(page) + [""]:
        if pending and text.startswith(")"):  # an entry's closing parenthesis printed at the next one's start (July 2021)
            pending, text = pending + ")", text[1:].strip()
        heading = len(text) <= MAX_HEADING and HEADING.fullmatch(text)
        ends = not text or END.fullmatch(text) or text.startswith("©") or SIDEBAR.match(text)
        # Furniture on a line of its own, not the start of a caption broken across lines.
        alone = FURNITURE.fullmatch(text) and not VERB.search(text) and (re.search(r"[).;:]\s*$", text) or re.fullmatch(r"[-*_]{5,}|leopold", text, re.I))
        complete = re.search(r"(?:\)|;|(?<!Prof)(?<![\s.][A-Z])\.)\s*$", pending)
        # A line that is an entry on its own starts one, even after an entry
        # that did not end in punctuation (2008-10 on the pre-2015 pages).
        entry = starts_entry(text)
        continues = pending and not heading and not ends and ((not complete and not entry) or (not alone and VERB.match(text)))
        if pending and not continues:
            add(pending)
            pending = ""
        if year and (lost := next((y for start, y in MISSING_HEADINGS.get(page, {}).items() if text.startswith(start)), None)):
            year = lost
        if heading:
            year, group = academic_year(text), None
        elif ends:
            year = None
        elif year and (continues or not alone):
            pending = f"{pending} {text}" if pending else text
    return by_year, unread


def same_fellow(a: str, b: str) -> bool:
    """Whether two printed names of a year's fellows are one person: the same
    words, one person by records.same_person, or near the same spelling
    ("Laura COLLEE", "Laura Colee")."""
    if key(a) == key(b) or sorted(records.words(a)) == sorted(records.words(b)):  # "(Jennifer) Ellie GRAHAM", 'Ellie "Jennifer" Graham'
        return True
    pa, pb = split(a), split(b)
    if records.same_person(pa, pb):
        return True
    return SequenceMatcher(None, key(a), key(b)).ratio() >= 0.85


def align(year: str, versions: list[list[dict]]) -> list[list[dict]]:
    """A year's fellows as each capture lists them, newest capture first:
    the fellows, each as the list of their entries in the captures that list
    them, in the order of the newest capture listing them."""
    fellows: list[list[dict]] = []
    for entries in versions:
        for e in entries:
            match = [f for f in fellows if same_fellow(f[0]["name"], e["name"]) and not any(x["page"] == e["page"] for x in f)]
            if not match:
                # One fellow of a surname in each of two captures' lists of a
                # year is one fellow ("Maggie DONNELLY", "Margaret Donnelly").
                surname = records.surname_parts(split(e["name"])["last"])
                same = [f for f in fellows if surname & records.surname_parts(split(f[0]["name"])["last"]) and not any(x["page"] == e["page"] for x in f)]
                if len(same) == 1 and sum(bool(surname & records.surname_parts(split(x["name"])["last"])) for x in entries) == 1:
                    match = same
            if len(match) > 1:  # two fellows of one name: by mentor
                match = [f for f in match if key(f[0]["projects"][0]["mentor"] or "") == key(e["projects"][0]["mentor"] or "")] or match
            if match:
                match[0].append(e)
            else:
                fellows.append([e])
    return fellows


def offered_projects() -> list[dict]:
    """The faculty projects the Center listed for fellows to apply to (see
    OFFERED), as {academic_year, mentor, title, description, requirements,
    url}. A call's "*** Whole year ..." lines, the quarters and languages
    a project needs, are its requirements."""
    out = []
    for page, (year, layout) in OFFERED.items():
        if layout == "word":
            text_path = (RAW / page).with_suffix(".txt")
            if not text_path.exists():
                # LibreOffice's conversion is committed, so parsing needs no Word reader.
                subprocess.run(["soffice", "--headless", "--convert-to", "txt:Text (encoded):UTF8", "--outdir", str(text_path.parent), str(RAW / page)], check=True, capture_output=True)
            paras = [tidy(t) for t in text_path.read_text(encoding="utf-8-sig").splitlines()]
            paras = [p for p in paras if p]
            # A paragraph the conversion broke mid-sentence ("an able assistant might be" / "asked to visit").
            joined: list[str] = []
            for p in paras:
                if joined and not re.search(r"[.:;?!)\"”]$", joined[-1]) and p[:1].islower():
                    joined[-1] += " " + p
                else:
                    joined.append(p)
            paras = joined
            heads = [i for i, p in enumerate(paras) if len(p) < 40 and re.fullmatch(r"[A-Z][\w.\- ]*?\b[A-Z]{2,}[\w\-]*:?", p)]
            for n, i in enumerate(heads):
                body = paras[i + 1 : heads[n + 1] if n + 1 < len(heads) else len(paras)]
                title = None
                if body and len(body[0]) < 120:
                    title = strip_quotes(re.sub(r"^Book project:\s*", "", body.pop(0)).strip()).rstrip(" .")
                out.append({"academic_year": year, "mentor": paras[i].rstrip(":"), "title": title, "description": "\n\n".join(body) or None, "requirements": None, "url": page_url(page)})
            continue
        found: list[dict] = []
        for text in page_lines(page):
            if m := re.fullmatch(r"\d+\.\s*(.+?)\s*(?::|—)\s*(.+)", text) if layout in ("colon", "dash") else None:
                mentor = m.group(1)
                if len(mentor.split()) <= 4 and any(caps(w) for w in mentor.split()):
                    found.append({"academic_year": year, "mentor": mentor, "title": strip_quotes(m.group(2).rstrip(" .")), "description": [], "requirements": [], "url": page_url(page)})
                    continue
            if found and not re.match(r"(?:©|Nicholas D\. Chabraja|Chabraja Center)", text):
                (found[-1]["requirements"] if text.startswith("***") else found[-1]["description"]).append(text.lstrip("* ").strip())
        for f in found:
            f["description"] = re.sub(r"\s*\[cont\. on next page\]", "", " ".join(f["description"])) or None
            f["requirements"] = " ".join(f["requirements"]) or None
        out += found
    for o in out:
        o["mentor"] = " ".join(o["mentor"].split())
    return out


def title_words(title: str | None) -> tuple[str, ...]:
    """A title's words for matching, without a leading article."""
    w = records.words(title or "")
    return tuple(w[1:] if w[:1] in (["a"], ["an"], ["the"]) else w)


def mentor_parts(name: str) -> dict:
    p = split(name)
    return {"first": p["first"], "last": p["last"]}


def same_mentor(a: str, b: str) -> bool:
    """Whether two printed names of mentors are one faculty member's: a shared
    surname part and the same first initial ("Gerry Cadava", "Geraldo
    CADAVA"; "J-Yeon YUH", "Ji-Yeon YUH"). No two mentors share a surname."""
    pa, pb = mentor_parts(a), mentor_parts(b)
    return bool(records.surname_parts(pa["last"]) & records.surname_parts(pb["last"])) and records.words(pa["first"])[:1][:1] and records.words(pa["first"])[0][0] == (records.words(pb["first"]) or [" "])[0][0]


def chosen(entries: list[dict], vocabulary: set[str]) -> dict:
    """A fellow's entry as the record gives it, from their entries in every
    capture (newest first): the newest entry, but for the boundaries that
    depend on capitals (where the fellow's surname starts, where the mentor's
    name ends and a description starts), taken from the newest entry that
    prints them in capitals and says the same in other respects."""
    primary = entries[0]
    out = {"star": primary["star"], "name": primary["name"], "info": dict(primary["info"]), "projects": [dict(p) for p in primary["projects"]], "line": primary["line"], "page": primary["page"]}
    for e in entries:
        if split(e["name"])["caps"] and key(e["name"]) == key(primary["name"]):
            out["name"] = e["name"]
            break
    for i, p in enumerate(out["projects"]):
        flat = key(f"{p['mentor'] or ''} {p['title'] or p['description'] or ''}")
        for e in entries:
            if i < len(e["projects"]) and (q := e["projects"][i])["mentor"] and any(caps(w) for w in q["mentor"].split()):
                if key(f"{q['mentor']} {q['title'] or q['description'] or ''}") == flat:
                    out["projects"][i] = {**p, "mentor": q["mentor"], "title": q["title"], "description": q["description"]}
                    break
    out["name"] = dehyphenate(out["name"], vocabulary)
    for p in out["projects"]:
        for k in ("mentor", "title", "description"):
            if p[k]:
                p[k] = dehyphenate(p[k], vocabulary)
    return out


FIELDS = ("name", "level", "school", "other_name", "returning", "mentor", "title", "description", "terms", "note")


def values(e: dict, i: int, vocabulary: set[str]) -> dict:
    """An entry's values of FIELDS for its i-th project, for comparing."""
    p = e["projects"][i] if i < len(e["projects"]) else {}
    out = {"name": e["name"], **{k: e["info"].get(k) for k in ("level", "school", "other_name")}, "returning": e["star"] or None}
    out |= {k: p.get(k) for k in ("mentor", "title", "description", "terms", "note")}
    return {k: dehyphenate(v, vocabulary) if isinstance(v, str) else v for k, v in out.items()}


def variants(entries: list[dict], best: dict, i: int, vocabulary: set[str]) -> list[dict]:
    """Every value of a fellow's i-th project that a capture prints otherwise
    than best does (by its words, not case or spacing), with the captures that
    print it. A capture that does not list the project for the fellow gives
    it as project: null. Where the mentor's name ends in a capture without
    capitals ("Nancy MacLean Southern segregationists") is not a variant."""
    want = values(best, i, vocabulary)
    flat = key(f"{want['mentor'] or ''} {want['title'] or want['description'] or ''}")
    found: dict[tuple[str, str], dict] = {}
    for e in entries:
        if i >= len(e["projects"]):
            found.setdefault(("project", "None"), {"field": "project", "value": None, "captures": []})["captures"].append(capture(e["page"]))
            continue
        got = values(e, i, vocabulary)
        if key(f"{got['mentor'] or ''} {got['title'] or got['description'] or ''}") == flat:
            got |= {k: want[k] for k in ("mentor", "title", "description")}
        for k, v in got.items():
            same = (key(v) == key(want[k])) if isinstance(v, str) and isinstance(want[k], str) else v == want[k]
            if v is None and k in ("level", "school", "other_name", "terms", "note"):
                continue  # a capture that leaves the detail out, not one giving another
            if not same:
                found.setdefault((k, repr(v)), {"field": k, "value": v, "captures": []})["captures"].append(capture(e["page"]))
    return [{**v, "captures": sorted(set(v["captures"]))} for v in found.values()]


def build() -> tuple[list[dict], list[str], list[str]]:
    """The records, what a run must fail on, and what it reports."""
    by_page = {}
    problems: list[str] = []
    for page in PAGES:
        by_page[page], unread = page_entries(page)
        problems += [f"unread line: {u}" for u in unread]
    vocabulary = {w.casefold() for page in by_page.values() for es in page.values() for e in es for w in re.findall(r"[^\W\d_]+(?:-[^\W\d_]+)*", e["line"])}
    years = sorted({y for page in by_page.values() for y in page})
    offered = offered_projects()
    report: list[str] = []
    all_fellows = []  # (year, chosen entry, entries, newest page of the year)
    for year in years:
        pages = sorted((p for p in by_page if year in by_page[p]), key=capture, reverse=True)
        for fellow in align(year, [by_page[p][year] for p in pages]):
            best = chosen(fellow, vocabulary)
            missing = [p for p in pages if capture(p) > capture(fellow[0]["page"])]
            if missing:
                why = DROPPED.get((year, key(best["name"])))
                listed = ", ".join(sorted({capture(e["page"]) for e in fellow}))
                if why is None:
                    problems.append(f"{year}: {best['name']} is listed by {listed} but not by the newer {capture(missing[-1])}: {best['line'][:160]}")
                best["listed_by"] = sorted({page_url(e["page"]) for e in fellow})
            all_fellows.append((year, best, fellow, pages[0]))

    # One name for each mentor: the form most often printed (rule-based, so one
    # mentor's records agree), a mentor given by first name alone completed
    # from the fellows of the same year and title.
    printed = Counter(p["mentor"] for _, b, _, _ in all_fellows for p in b["projects"] if p["mentor"])
    forms: list[list[str]] = []
    for name, _ in printed.most_common():
        group = next((g for g in forms if same_mentor(g[0], name)), None)
        (group.append(name) if group else forms.append([name]))
    canonical = {}
    for g in forms:
        best_form = max(g, key=lambda n: (any(caps(w) for w in n.split()), printed[n]))
        for n in g:
            canonical[n] = best_form
        if len(g) > 1:
            report.append(f"mentor {best_form!r} also printed {[n for n in g if n != best_form]}")
    for year, b, _, _ in all_fellows:
        for p in b["projects"]:
            if p["mentor"] and len(p["mentor"].split()) == 1:
                peers = {canonical[q["mentor"]] for y, c, _, _ in all_fellows if y == year for q in c["projects"] if q["mentor"] and len(q["mentor"].split()) > 1 and title_words(q["title"]) == title_words(p["title"]) and split(q["mentor"])["first"].startswith(p["mentor"])}
                if len(peers) == 1:
                    report.append(f"{year}: mentor {p['mentor']!r} of {b['name']} completed as {peers.copy().pop()!r} from the same year's fellows on {p['title']!r}")
                    canonical[p["mentor"]] = peers.pop()
                else:
                    problems.append(f"{year}: mentor {p['mentor']!r} of {b['name']} has no surname")

    groups: dict[tuple, dict] = {}
    for year, b, fellow, newest in all_fellows:
        for i, p in enumerate(b["projects"]):
            mentor = canonical.get(p["mentor"], p["mentor"])
            what = title_words(p["title"]) or tuple(records.words(p["description"] or "")) or ("fellow", key(b["name"]))
            g = groups.setdefault((year, key(mentor or ""), what), {"year": year, "mentor": mentor, "title": p["title"], "description": p["description"], "fellows": [], "notes": [], "url": page_url(newest), "lines": [], "variants": []})
            g.setdefault("titles", Counter())[p["title"]] += 1
            person = records.person("student", {k: v for k, v in split(b["name"]).items() if k != "caps"}, **b["info"], terms=p["terms"], returning=b["star"] or None, listed_by=b.get("listed_by"))
            g["fellows"].append(person)
            g["lines"].append(b["line"])
            if p["note"]:
                g["notes"].append(p["note"])
            # The mentor as captures print them, where the record names them otherwise.
            printed_as: dict[str, set[str]] = {}
            for e in fellow:
                if i < len(e["projects"]) and (m := e["projects"][i]["mentor"]) and key(m) != key(mentor or "") and same_mentor(m, mentor or m):
                    printed_as.setdefault(key(m), set()).add(capture(e["page"]))
            for k, caps_ in printed_as.items():
                form = next(e["projects"][i]["mentor"] for e in fellow if i < len(e["projects"]) and key(e["projects"][i]["mentor"] or "") == k)
                g["variants"].append({"fellow": b["name"], "field": "mentor", "value": form, "captures": sorted(caps_)})
            g["variants"] += [{"fellow": b["name"], **v} for v in variants(fellow, b, i, vocabulary) if not (v["field"] == "mentor" and v["value"] and same_mentor(v["value"], mentor or v["value"]))]

    # The listed faculty projects: by title, or by hand (MATCHED).
    for g in groups.values():
        candidates = [o for o in offered if o["academic_year"] == g["year"] and g["mentor"] and same_mentor(o["mentor"], g["mentor"])]
        pinned = {MATCHED[k] for f in g["fellows"] if (k := (g["year"], key(f["first"] + " " + f["last"]))) in MATCHED}
        match = [o for o in candidates if (g["title"] and title_words(o["title"]) == title_words(g["title"])) or title_words(o["title"]) in {title_words(t) for t in pinned}]
        if len(match) > 1:
            problems.append(f"{g['year']}: {g['title'] or g['description']!r} matches {len(match)} listed projects")
        if match:
            g["offered"] = match[0]
        elif candidates:
            report.append(f"{g['year']}: not matched to a listed project of its mentor: {g['title'] or g['description']!r} ({', '.join(f['first'] + ' ' + f['last'] for f in g['fellows'])}); listed: {[o['title'] or (o['description'] or '')[:60] for o in candidates]}")

    out, counts = [], Counter()
    for g in groups.values():
        start = int(g["year"][:4])
        counts[start] += 1
        o = g.get("offered")
        # The title as most of its fellows' entries print it, capitals first ("History of Laughter", not "history of Laughter").
        printed_title = max(g["titles"], key=lambda t: (g["titles"][t], sum(c.isupper() for c in t or ""))) if g["title"] else None
        title = printed_title or (o and o["title"])
        extra = {
            "academic_year": g["year"],
            "description": g["description"],
            "offered": {"title": o["title"], "requirements": o["requirements"], "url": o["url"]} if o else None,
            "notes": sorted(set(g["notes"])) or None,
            "lines": g["lines"],
            "variants": g["variants"] or None,
        }
        people = g["fellows"] + ([records.person("advisor", mentor_parts(g["mentor"]))] if g["mentor"] else [])
        out.append(records.record(f"leopold-{start}-{counts[start]:03d}", SOURCE, "fellowship", start, title, people, o and o["description"], g["url"], extra=extra))
    return out, problems, report


def main() -> None:
    out, problems, report = build()
    for line in report:
        print(line)
    fellows = sum(1 for r in out for p in r["people"] if p["role"] == "student")
    variants_n = sum(len(r.get("extra", {}).get("variants") or []) for r in out)
    print(f"{len(out)} records, {fellows} fellow-projects, {variants_n} values printed otherwise by some capture")
    for year, n in sorted(Counter(r["extra"]["academic_year"] for r in out).items()):
        print(f"  {year}: {n} records, {sum(1 for r in out if r['extra']['academic_year'] == year for p in r['people'] if p['role'] == 'student')} fellows")
    if problems:
        print(f"\n{len(problems)} problems:", file=sys.stderr)
        for p in problems:
            print("  " + p, file=sys.stderr)
        sys.exit(1)
    records.write(SOURCE, out)


if __name__ == "__main__":
    main()

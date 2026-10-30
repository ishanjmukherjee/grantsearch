"""Parse Undergraduate Research & Arts Expo abstracts, 2012-2019 and 2021-2026.

Two layouts exist:

- Programs (2012-2019, 2021-2023): presenter in bold, "Faculty Advisor:" in
  italics, title in bold, abstract in regular weight, small page footers and a
  running page header. Parsed line by line from font weights. The 2012-2019
  programs vary more and have their own parser (see parse_old_program).
- Abstract guides (2024-2026): one font throughout. Each entry is a header
  block (presenter and advisor), a title block, abstract blocks, and a closing
  block starting with "Presentation Format:". Parsed from block boundaries.

Advisor affiliations go in parentheses after the advisor's name, so that
"Joseph Contessa, Yale University" or "Monika Nanda [UNC Chapel Hill]" reads
as one advisor, "Joseph Contessa (Yale University)".

Each entry records the 1-based PDF page its header starts on, so a link can
open the program at the abstract (`source#page=N`).

Writes data/expo_abstracts.json.

Usage: uv run python -m pipeline.parse_expo [--refresh]
"""

import argparse
import json
import re
from pathlib import Path

import httpx
import pymupdf

from pipeline.scrape_surg import DATA_DIR, HEADERS, RAW_DIR, tidy

BASE = "https://undergradresearch.northwestern.edu/files"
SOURCES = {
    2012: f"{BASE}/2020/09/FINAL-EXPO-PROGRAM-2012.pdf",
    2013: f"{BASE}/2020/09/2013_Undergraduate_Research__Arts_Program.pdf",
    2014: f"{BASE}/2020/09/2014ExpoProgram_0.pdf",
    2015: f"{BASE}/2020/09/Expo-2015_FULL-PROGRAM_0.pdf",
    2016: f"{BASE}/2020/09/EXPO-Program_Complete_23-May-16_0.pdf",
    2017: f"{BASE}/2020/09/Expo-Program_2017.pdf",
    2018: f"{BASE}/2020/09/Expo-Program-2018_3.pdf",
    2019: f"{BASE}/2016/03/Expo-Program-2019.pdf",
    2021: f"{BASE}/2024/03/The-2021-Virtual-Undergraduate-Research-and-Arts-Exposition-7e95f42a523aba52.pdf",
    2022: f"{BASE}/2024/03/2022-Undergraduate-Research-Arts-Exposition-Digital-Program-a15a7699ca7c2d29.pdf",
    2023: f"{BASE}/2024/03/2023-Undergraduate-Research-and-Arts-Expo-Program-439f378a3b0164f8.pdf",
    2024: f"{BASE}/2024/05/2024-Exposition-Abstract-Guide.pdf",
    2025: f"{BASE}/2025/05/2025_Expo_Abstract_Guide_05.19.25.pdf",
    2026: f"{BASE}/2026/05/2026-Undergraduate-Research-Expo-Abstract-Guide.pdf",
}
OLD_PROGRAM_YEARS = set(range(2012, 2020))
# The 2012-2019 programs' sections that list projects, as 0-based page ranges:
# abstracts, and creative works in one of parse_old_creative's layouts. The
# pages around them hold schedules, judges, high-school projects and the like.
OLD_SECTIONS = {
    2012: [(range(38, 100), "abstracts"), (range(29, 31), "presenter"), (range(31, 36), "title"), (range(36, 38), "visual")],
    2013: [(range(36, 102), "abstracts"), (range(29, 34), "presenter"), (range(34, 36), "visual")],
    2014: [(range(40, 110), "abstracts"), (range(33, 38), "presenter"), (range(38, 40), "visual")],
    2015: [(range(23, 62), "abstracts"), (range(68, 94), "abstracts"), (range(95, 101), "presenter")],
    2016: [(range(26, 63), "abstracts"), (range(69, 93), "abstracts"), (range(94, 100), "presenter")],
    2017: [(range(28, 82), "abstracts"), (range(88, 112), "abstracts"), (range(113, 118), "presenter")],
    2018: [(range(27, 74), "abstracts"), (range(80, 106), "abstracts"), (range(107, 114), "presenter")],
    2019: [(range(27, 92), "abstracts"), (range(98, 124), "abstracts"), (range(127, 136), "presenter")],
}
# Listings left out, by year and title.
EXCLUDED = {
    # A high-school student's project (Evanston Township High School).
    (2015, "Unclenching the Feminist Fist: Rebranding The Movement"),
    # The program prints these under the abstract of the entry before them
    # (Shenkman's medical tourism study, Yi's speech-in-noise study).
    (2019, "Unani Tibb as Resistance: Bodily Practice at the Intersection of Colonial and Postcolonial Systems of Power"),
    (2019, "Learning from Whom and from What? How Performance Feedback Affects the Diffusion of New Practices"),
}
PROGRAM_YEARS = {2021, 2022, 2023}
LAST_FIRST_YEARS = {2025, 2026}

# The guides' font maps the fi and fl ligatures to private-use code points.
LIGATURES = str.maketrans({"\uf001": "fi", "\uf002": "fl"})
# Older programs set some symbols in SymbolMT, whose characters come out as
# private-use code points: delta and Delta (sulfur isotopes), eta (effect
# sizes), and a horizontal bar used as an em dash.
SYMBOL_FONT = str.maketrans({"\uf064": "δ", "\uf044": "Δ", "\uf068": "η", "\uf8e7": "—"})
# Cambria Math letters (U+1D400-1D7FF) come out of the PDFs twice each.
MATH_DOUBLED = re.compile(r"([\U0001D400-\U0001D7FF])\1")
PARTICLES = {"van", "von", "den", "der", "de", "da", "del", "della", "di", "du", "dos", "la", "le", "al", "el"}
ADVISOR = re.compile(r"Faculty Advisors?:\s*(.*)", re.S)
# An advisor line in the 2012-2019 programs: "Faculty Advisor(s):", and also
# "Faculty:", "Faculty Adviser:", "Advisor:" and "Faculty/Choreography:".
OLD_ADVISOR = re.compile(r"\s*(?:Faculty(?: Advis[eo]rs?|/\w+)?|Advisor):\s*(.*)", re.S)
# Lines between an old program's advisor and title that name other people.
OLD_CREDITS = re.compile(r"\s*(?:Reader|Performed by):")
PRODUCED_BY = re.compile(r"\s*Produced by ")
MODERATOR = re.compile(r"\s*Moderator:")
# Subheadings dividing a creative work's description (2018-2019).
SUBHEAD = re.compile(r"\s*(?:Description(?: and Artists?[’']? Statement)?|Artist(?:[’']s|s[’']|ic)? Statement)\s*:?\s*")
# A structured abstract's first heading, bold at the start of its first line.
ABSTRACT_HEADING = re.compile(r"\s*(?:Background|Introduction|Objectives?|Purpose|Aims?|Methods|Hypothesis)\s*:")
CONTINUED = re.compile(r".*, continued\s*")
# A creative work listed as "COLLIDEscope by Briana Nicholson-Klingerman",
# with no separate title line.
TITLE_BY = re.compile(r"\s*(.+?) by ([A-Z][\w.’'-]*(?: [A-Z][\w.’'-]*)+)\s*")
GUIDE_END = "Presentation Format:"
# An advisor list item naming an institution rather than a person.
INSTITUTION = re.compile(r"\b(?:University|College|Laborator(?:y|ies)|Hospital|Clinic|Institute|School|Center|Department|Films|Retired)\b")
BOLD = 16
ITALIC = 2
HEADING_SIZE = 13  # section headings, times and rooms are set larger than the 12pt body
MIN_BODY_SIZE = 10  # lines of only smaller text are page footers
# Running page headers are set at or near body size, so match them by text:
# "Undergraduate Research & Arts Exposition 12" (2021), and in older programs
# "..., 13", "14. ..." or "... 15" with "and" for "&".
RUNNING_HEADER = re.compile(r"\s*(?:\d+\.?\s+)?Undergraduate Research (?:&|and) Arts Exposition(?:[,.]?\s*\d+\.?)?\s*")


def fetch(year: int, refresh: bool) -> Path:
    path = RAW_DIR / "expo" / f"{year}.pdf"
    if path.exists() and not refresh:
        return path
    resp = httpx.get(SOURCES[year], headers=HEADERS, follow_redirects=True, timeout=60)
    resp.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return path


def text(s: str) -> str:
    s = s.translate(LIGATURES).translate(SYMBOL_FONT).replace("&amp;", "&")
    s = MATH_DOUBLED.sub(r"\1", s)
    # A hyphen ending a line joins a compound ("Mexican-American", "COVID-19");
    # the programs and guides never break words with soft hyphens.
    s = re.sub(r"(\w)-\n(\w)", r"\1-\2", s)
    s = tidy(s)
    # Drop stray spaces inside brackets ("[PSI+ ]") and before punctuation
    # ("results ,"), but not before a decimal point ("p < .001").
    s = re.sub(r"([(\[]) +| +([)\]])", r"\1\2", s)
    return re.sub(r"(?<=[\w)\]\"']) +([,;:.])(?=\s|$)", r"\1", s)


def affiliations(advisor: str) -> str:
    """Put an advisor's affiliation in parentheses after their name."""
    advisor = re.sub(r"\s*\[([^\]]*)\]", r" (\1)", advisor)
    items = re.split(r"\s*,\s*", advisor)
    out = [items[0]]
    for item in items[1:]:
        if INSTITUTION.search(item):
            # A second item of one affiliation ("Retired Urbana", "IL School
            # Teacher") joins the first inside its parentheses.
            out[-1] = f"{out[-1][:-1]}, {item})" if out[-1].endswith(")") else f"{out[-1]} ({item})"
        else:
            out.append(item)
    return ", ".join(out)


def split_people(s: str, last_first: bool) -> list[dict]:
    """Split a presenter string into first/last names.

    Older years list "First Last and First Last"; 2025 on list "Last, First"
    with several presenters separated by semicolons or line breaks.
    """
    people = []
    if last_first:
        for part in re.split(r"\s*(?:;|\n|&| and )\s*", s):
            if "," in part:
                last, first = (p.strip() for p in part.split(",", 1))
                if first and last:
                    people.append({"first": text(first), "last": text(last)})
    else:
        for part in re.split(r"\s*(?:,\s*and\s+|,|;|\n|&| and )\s*", s):
            words = part.split()
            if len(words) >= 2:
                cut = len(words) - 1
                while cut > 1 and words[cut - 1].lower() in PARTICLES:
                    cut -= 1
                people.append({"first": text(" ".join(words[:cut])), "last": text(" ".join(words[cut:]))})
    return people


def drop_name_notes(names: str) -> str:
    """Names without the notes in parentheses after them: roles ("Alice Li
    (Director)"), stage names ("Maris Maeve O'Tierney (maris maeve)") and
    schools. A nickname inside a name stays, as in the newer programs:
    "Jungwha (Paula) Ham"."""
    return re.sub(r"\s*\([^)]*\)(?=\s*(?:,|;|&|\band\b|$))", "", names, flags=re.M)


def entry(people: list[dict], advisor: str | None, title: str, abstract: str, page: int) -> dict | None:
    """An entry, or None if a field is missing. page is the 0-based index of
    the page its header starts on."""
    if not people or not title or not abstract:
        return None
    return {"presenters": people, "advisor": advisor or None, "title": title, "abstract": abstract, "page": page + 1}


def join_spans(spans: list[dict]) -> str:
    """Join a line's font runs, restoring spaces the PDF encodes as gaps."""
    out = spans[0]["text"]
    for prev, cur in zip(spans, spans[1:]):
        gap = cur["bbox"][0] - prev["bbox"][2]
        if gap > 1 and not out.endswith(" ") and not cur["text"].startswith(" "):
            out += " "
        out += cur["text"]
    return out


def program_line_spans(doc: pymupdf.Document, pages: range | None = None) -> list[list[dict]]:
    """A program's body lines, each as its font runs, from all pages or the given ones.
    Each run carries the 0-based index of its page as "page"."""
    lines = []
    for page in doc if pages is None else (doc[n] for n in pages):
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = []
                space = False
                for s in line["spans"]:
                    if "Wingdings" in s["font"]:
                        continue
                    if not s["text"].strip():
                        # A run of only a space can be the sole space between
                        # two words ("Caenorhabditis", " ", "elegans").
                        space = True
                        continue
                    if space and spans and not s["text"].startswith(" "):
                        s = {**s, "text": " " + s["text"]}
                    spans.append({**s, "page": page.number})
                    space = False
                # A line of only small text is a page footer; small text in a
                # body-size line is a subscript or superscript (CO2, 1H NMR).
                body = [s for s in spans if s["size"] >= MIN_BODY_SIZE]
                if not body or RUNNING_HEADER.fullmatch(join_spans(spans)):
                    continue
                lines.append(spans)
    return lines


def weight(spans: list[dict]) -> str:
    """A line's weight from its body-size runs: "bold", "mixed" or "plain"."""
    bold = [bool(s["flags"] & BOLD) for s in spans if s["size"] >= MIN_BODY_SIZE]
    return "bold" if all(bold) else "mixed" if any(bold) else "plain"


def parse_program(doc: pymupdf.Document) -> list[dict]:
    spans = program_line_spans(doc)
    # Each line as (text, kind), kind in {"bold", "mixed", "plain"}.
    lines = [(join_spans(s), weight(s)) for s in spans]
    entries = []
    i = 0
    while i < len(lines):
        if not lines[i][0].lstrip().startswith("Faculty Advisor"):
            i += 1
            continue
        advisor = ADVISOR.search(lines[i][0]).group(1)
        # Presenter: the bold line just before the advisor, plus earlier bold
        # lines when the name list wraps ("A, B, and" / "C").
        j = i - 1
        names = [lines[j][0]] if j >= 0 and lines[j][1] == "bold" else []
        while j > 0 and lines[j - 1][1] == "bold" and re.search(r"(,|\band)\s*$", lines[j - 1][0]):
            j -= 1
            names.insert(0, lines[j][0])
        page = spans[j if names else i][0]["page"]
        i += 1
        title = []
        while i < len(lines) and lines[i][1] != "plain" and not lines[i][0].lstrip().startswith("Faculty Advisor"):
            title.append(lines[i][0])
            i += 1
        body = []
        # The abstract ends at the next all-bold line: a presenter or a heading.
        while i < len(lines) and lines[i][1] != "bold":
            body.append(lines[i][0])
            i += 1
        e = entry(split_people("\n".join(names), last_first=False), text(advisor), text("\n".join(title)), text("\n".join(body)), page)
        if e:
            entries.append(e)
    return entries


def italic(spans: list[dict]) -> bool:
    return all(s["flags"] & ITALIC or "Italic" in s["font"] for s in spans)


def line_width(spans: list[dict]) -> float:
    return max(s["bbox"][2] for s in spans) - min(s["bbox"][0] for s in spans)


def full_width(spans: list[list[dict]]) -> float:
    """The width of a full line of body text: an abstract's first line fills the column."""
    widths = sorted(line_width(s) for s in spans if weight(s) == "plain")
    return widths[int(len(widths) * 0.9)]


def parse_old_abstracts(spans: list[list[dict]]) -> list[dict]:
    """Like parse_program, for the abstract pages of the 2012-2019 programs.
    Besides the advisor label variants (OLD_ADVISOR), these vary in ways the
    newer programs do not:

    - "Reader:" or "Performed by:" lines between the advisor and the title
    - an advisor list wrapped onto a line starting "and", and once a doubled
      label ("Faculty Advisor: Advisor: ...")
    - once an advisor line with no label, in italics (2013, "Renee Engeln"),
      and once no advisor line at all (2015, Nishant Subramani)
    - a title ending in a species name set in regular weight that wraps onto
      a line of its own ("... the planarian Schmidtea" / "mediterranea")
    - a structured abstract whose first line opens with a bold "Background:"
    """
    lines = [(join_spans(s), weight(s)) for s in spans]

    def abstract_text(k: int) -> bool:
        return k >= 0 and lines[k][1] == "plain" and not italic(spans[k]) and not OLD_ADVISOR.match(lines[k][0])

    def unlabeled_advisor(k: int) -> bool:
        # Presenter, an advisor's name alone in italics, title.
        return (
            0 < k < len(lines) - 1
            and lines[k][1] == "plain"
            and italic(spans[k])
            and not OLD_ADVISOR.match(lines[k][0])
            and not OLD_CREDITS.match(lines[k][0])
            and lines[k - 1][1] == "bold"
            and abstract_text(k - 2)
            and lines[k + 1][1] == "bold"
        )

    def is_advisor(k: int) -> bool:
        return 0 <= k < len(lines) and (bool(OLD_ADVISOR.match(lines[k][0])) or unlabeled_advisor(k))

    def no_advisor(k: int) -> bool:
        # Presenter and title in bold right after the last abstract, with no
        # advisor line before the next abstract.
        if not (lines[k][1] == "bold" and abstract_text(k - 1) and k + 1 < len(lines) and lines[k + 1][1] != "plain"):
            return False
        m = k + 1
        while m < len(lines) and lines[m][1] != "plain":
            m += 1
        return m < len(lines) and abstract_text(m) and not any(is_advisor(n) for n in range(k, m + 1))

    def is_title_line(k: int, title: list[str]) -> bool:
        if is_advisor(k) or ABSTRACT_HEADING.match(lines[k][0]):
            return False
        if lines[k][1] != "plain":
            return True
        # A species name set in regular weight that wraps onto a line of its
        # own. An abstract's first line is never this short.
        return bool(title) and len(lines[k][0].split()) <= 3

    entries = []
    i = 0
    while i < len(lines):
        if is_advisor(i):
            m = OLD_ADVISOR.match(lines[i][0])
            advisor = m.group(1) if m else lines[i][0]
            j = i - 1
            names = [lines[j][0]] if j >= 0 and lines[j][1] != "plain" else []
            while j > 0 and lines[j - 1][1] != "plain" and re.search(r"(,|\band)\s*$", lines[j - 1][0]):
                j -= 1
                names.insert(0, lines[j][0])
            page = spans[j if names else i][0]["page"]
            i += 1
            while i < len(lines) and lines[i][1] == "plain" and lines[i][0].lstrip().startswith("and "):
                advisor += " " + lines[i][0]
                i += 1
            advisor = re.sub(r"^\s*(?:Advisors?:\s*)+", "", advisor)
        elif no_advisor(i):
            names, advisor = [lines[i][0]], ""
            page = spans[i][0]["page"]
            i += 1
        else:
            i += 1
            continue
        while i < len(lines) and OLD_CREDITS.match(lines[i][0]):
            i += 1
        title = []
        while i < len(lines) and is_title_line(i, title):
            title.append(lines[i][0])
            i += 1
        body = []
        # The abstract ends at the next all-bold line (a presenter, a title or
        # a heading) or at the line before the next advisor (a presenter).
        while i < len(lines) and lines[i][1] != "bold" and not is_advisor(i) and not is_advisor(i + 1):
            body.append(lines[i][0])
            i += 1
        people = split_people(drop_name_notes("\n".join(names)), last_first=False)
        e = entry(people, text(advisor), text("\n".join(title)), text("\n".join(body)), page)
        if e:
            entries.append(e)
    return entries


def parse_old_creative(spans: list[list[dict]], layout: str) -> list[dict]:
    """The creative works in a 2012-2019 program: films, performances, writing
    and visual art. Unlike the abstracts, most have no advisor line, so an
    entry starts at the first bold line after a description (or a section
    heading). Its header is, in order:

    - presenters in bold, or in mixed weight with a nickname in parentheses
      ("Maris Maeve O'Tierney (maris maeve) and ..."), wrapping after a comma
      or "and"
    - an optional advisor line, labeled or (once, in 2014) a name alone in
      italics: "Leo Chiang, New Day Films"
    - the title in bold or mixed weight, or (2017) on a short plain line
    - optional "Performed by:" credits, a plain subtitle ("A musical fusion of
      classical technique and folk/pop songwriting", or the pieces of a recital
      on lines of their own) and bold "Description" or
      "Artist Statement" subheadings, which also divide the description

    That is the "presenter" layout. In the "visual" one (2012-2014 visual
    art) an entry starts with "COLLIDEscope by Briana Nicholson-Klingerman" on
    one line. In the "title" one (2012 films and performances) the title comes
    first, then an optional "By" line or plain subtitle, then the people in
    bold, mixed weight or italics, then an optional advisor and "Produced by"
    credits.
    """
    lines = [(join_spans(s), weight(s)) for s in spans]
    full = full_width(spans)

    def heading(k: int) -> bool:
        return max(s["size"] for s in spans[k]) > HEADING_SIZE or bool(MODERATOR.match(lines[k][0]))

    def description(k: int) -> bool:
        return lines[k][1] == "plain" and not italic(spans[k]) and not OLD_ADVISOR.match(lines[k][0])

    def short(k: int) -> bool:
        return line_width(spans[k]) < 0.8 * full

    def is_title_by(k: int) -> bool:
        return layout == "visual" and short(k) and not italic(spans[k]) and bool(TITLE_BY.fullmatch(lines[k][0]))

    def starts(k: int) -> bool:
        if heading(k) or SUBHEAD.fullmatch(lines[k][0]):
            return False
        if layout == "visual":
            return is_title_by(k)
        return lines[k][1] != "plain" and (k == 0 or heading(k - 1) or description(k - 1))

    def unlabeled_advisor(k: int) -> bool:
        return lines[k][1] == "plain" and italic(spans[k]) and not OLD_CREDITS.match(lines[k][0])

    def wraps(k: int) -> bool:
        return re.search(r"(,|\band)\s*$", lines[k][0]) is not None

    entries = []
    i = 0
    while i < len(lines):
        if not starts(i):
            i += 1
            continue
        names, title, advisor = [], [], ""
        page = spans[i][0]["page"]
        if is_title_by(i):
            m = TITLE_BY.fullmatch(lines[i][0])
            title, names = [m.group(1)], [m.group(2)]
            i += 1
        elif layout == "title":
            title = [lines[i][0]]
            i += 1
            if i < len(lines) and lines[i][0].strip() == "By":
                i += 1
            elif i + 1 < len(lines) and description(i) and not description(i + 1):
                title.append(lines[i][0])
                i += 1
            while (
                i < len(lines)
                and (lines[i][1] != "plain" or italic(spans[i]))
                and not OLD_ADVISOR.match(lines[i][0])
                and not PRODUCED_BY.match(lines[i][0])
                and not heading(i)
            ):
                names.append(lines[i][0])
                i += 1
        else:
            names = [lines[i][0]]
            i += 1
            while i < len(lines) and lines[i][1] != "plain" and wraps(i - 1):
                names.append(lines[i][0])
                i += 1
        if i < len(lines) and OLD_ADVISOR.match(lines[i][0]):
            advisor = OLD_ADVISOR.match(lines[i][0]).group(1)
            i += 1
            while i < len(lines) and description(i) and lines[i][0].lstrip().startswith("and "):
                advisor += " " + lines[i][0]
                i += 1
        elif layout == "presenter" and i < len(lines) and unlabeled_advisor(i):
            advisor = lines[i][0]
            i += 1
        while i < len(lines) and (OLD_CREDITS.match(lines[i][0]) or PRODUCED_BY.match(lines[i][0])):
            i += 1
        if not title:
            while i < len(lines) and lines[i][1] != "plain" and not heading(i) and not SUBHEAD.fullmatch(lines[i][0]):
                title.append(lines[i][0])
                i += 1
        if not title and i < len(lines) and description(i) and short(i):
            title = [lines[i][0]]
            i += 1
        while i < len(lines) and OLD_CREDITS.match(lines[i][0]):
            i += 1
        subtitle = []
        while (
            title
            and i + 1 < len(lines)
            and description(i)
            and short(i)
            and not re.search(r"[.!?:;”\"]$", lines[i][0].strip())
            and description(i + 1)
        ):
            subtitle.append(lines[i][0])
            i += 1
        if subtitle:
            title[-1] = f"{title[-1].rstrip()}: {' '.join(subtitle)}"
        body = []
        # The description runs to the next entry or section heading; a
        # "Visual Arts, continued" page heading can fall inside it.
        while i < len(lines) and not starts(i) and (not heading(i) or CONTINUED.fullmatch(lines[i][0])):
            if not (heading(i) or SUBHEAD.fullmatch(lines[i][0]) or OLD_CREDITS.match(lines[i][0])):
                body.append(lines[i][0])
            i += 1
        people = split_people(drop_name_notes("\n".join(names)), last_first=False)
        e = entry(people, text(advisor), text("\n".join(title)), text("\n".join(body)), page)
        if e:
            entries.append(e)
    return entries


def parse_old_program(doc: pymupdf.Document, year: int) -> list[dict]:
    """A 2012-2019 program's abstracts and creative works, in page order.
    A creative work also presented as a talk or poster (Susie Neilson's 2015
    documentary) is kept once, as the abstract."""
    entries = []
    for pages, layout in sorted(OLD_SECTIONS[year], key=lambda s: s[0].start):
        spans = program_line_spans(doc, pages)
        entries += parse_old_abstracts(spans) if layout == "abstracts" else parse_old_creative(spans, layout)
    seen = set()
    out = []
    for e in entries:
        key = (tuple(re.findall(r"\w+", e["title"].lower())), tuple((p["first"], p["last"]) for p in e["presenters"]))
        if key not in seen and (year, e["title"]) not in EXCLUDED:
            seen.add(key)
            out.append(e)
    return out


def parse_guide(doc: pymupdf.Document, last_first: bool) -> list[dict]:
    # Each block as (text, 0-based page index).
    blocks = [(b[4], page.number) for page in doc for b in page.get_text("blocks") if b[4].strip()]
    entries = []
    current: list[str] = []
    pages: list[int] = []
    for b, page in blocks:
        if not b.lstrip().startswith(GUIDE_END):
            current.append(b)
            pages.append(page)
            continue
        # Anchor the header on the advisor line so front matter before the
        # first entry is skipped. The advisor may share the presenter block or
        # sit in its own block right after it.
        start, end = 0, 1
        for j, c in enumerate(current):
            if "Faculty Advisor" in c:
                start = j - 1 if c.lstrip().startswith("Faculty Advisor") and j > 0 else j
                end = j + 1
                break
        header = "\n".join(current[start:end])
        advisor = None
        m = ADVISOR.search(header)
        if m:
            advisor = text(m.group(1))
            header = header[: m.start()]
        rest = current[end:]
        if rest:
            e = entry(split_people(header.strip(), last_first), advisor, text(rest[0]), text("\n".join(rest[1:])), pages[start])
            if e:
                entries.append(e)
        current = []
        pages = []
    return entries


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch cached PDFs")
    args = parser.parse_args()

    out = []
    for year in SOURCES:
        doc = pymupdf.open(fetch(year, args.refresh))
        if year in OLD_PROGRAM_YEARS:
            entries = parse_old_program(doc, year)
        elif year in PROGRAM_YEARS:
            entries = parse_program(doc)
        else:
            entries = parse_guide(doc, last_first=year in LAST_FIRST_YEARS)
        for n, e in enumerate(entries, 1):
            out.append({"id": f"expo-{year}-{n:03d}", "year": year, **e, "source": SOURCES[year]})
        print(f"{year}: {len(entries)} abstracts")
    for e in out:
        if e["advisor"]:
            e["advisor"] = affiliations(e["advisor"])

    path = DATA_DIR / "expo_abstracts.json"
    path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(out)} abstracts to {path}")


if __name__ == "__main__":
    main()

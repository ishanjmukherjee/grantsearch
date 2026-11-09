"""Undergraduate Research Symposium listings, 2003-2011, from the programs.

The Symposium was the Undergraduate Research Expo before 2012: the Provost's
office ran it from 2003 to 2010 and OUR in 2011, and the Expo program
archive starts at 2012. Its programs survive only in the Wayback Machine,
pinned in ARCHIVED and cached in data/raw/symposium/. No program was posted
for 2005, and the only capture of 2007's is truncated and does not open.

Each listing has the shape pipeline.parse_expo gives an Expo listing, with
"symposium-" ids. The programs come in three layouts:

- 2003: "Project #N", "Student Presenter(s):", "Faculty Sponsor(s):" in
  bold, then the description. 32 of the 184 descriptions open with a title
  in italics; the rest have none, so their title is None. Every 2003
  listing keeps its project number.
- 2004 and 2008-2011: presenters, an advisor line ("Faculty:"), the title,
  then the abstract. Presenters and titles are bold, except in 2010, which is
  set in one weight throughout; there the title is the lines after the
  advisor line that are set in from the left margin, as the abstract is not.
- 2006: a Word document of project descriptions, with presenters in capitals,
  then the title and the advisor line. Read from its textutil HTML
  conversion (data/raw/symposium/2006-descriptions.html), which keeps bold
  and italics. Names are restored to their case from the program's project
  index (2006-front.doc).

Entries are found by their advisor line, so the two ensemble recitals the
programs describe without one (2009's Apollo Saxophone Quartet, 2010's
Obsidian Brass Quintet, both mostly of other composers' music) are left out.

Used by pipeline.parse_expo, which writes the records.
"""

import html
import re
import subprocess
from collections import Counter
from pathlib import Path

import httpx
import pymupdf

from pipeline.parse_expo import RAW_DIR, split_people, text
from pipeline.records import first_match, words
from pipeline.scrape_surg import HEADERS

SYMPOSIUM_DIR = RAW_DIR / "symposium"
WAYBACK = "https://web.archive.org/web"
PROVOST = "http://www.northwestern.edu/provost/students"
OUR = "http://undergradresearch.northwestern.edu/sites/default/files"
# Saved file: (capture timestamp, original URL). Each was captured more than
# once where the Wayback Machine has it twice, with identical bytes.
ARCHIVED = {
    "2003-program.pdf": ("20030714165517", f"{PROVOST}/research_symposium/program.pdf"),
    "2004-program.pdf": ("20040610220629", f"{PROVOST}/research_symposium/program2004.pdf"),
    "2006-descriptions.doc": ("20060908205759", f"{PROVOST}/research_symposium/2006_Draft_Program_12.doc"),
    "2006-front.doc": ("20060908205811", f"{PROVOST}/research_symposium/2006_Front_Matter_22.doc"),
    "2008-front.pdf": ("20090115223155", f"{PROVOST}/research_symposium/FrontMatter2008.pdf"),
    "2008-abstracts.pdf": ("20090310191114", f"{PROVOST}/research_symposium/SymposiumAbstracts2008.pdf"),
    "2009-program.pdf": ("20100525211716", f"{PROVOST}/research-symposium/2009%20Program%20and%20Abstracts.pdf"),
    "2010-program.pdf": ("20100525211713", f"{PROVOST}/research-symposium/2010SymposiumFINAL.pdf"),
    "2011-program.pdf": ("20110720014306", f"{OUR}/2011%20Symposium%20Program.pdf"),
}
# The file each year's listings come from, and (for the PDFs) the 0-based
# pages of its descriptions.
PROGRAMS = {
    2003: ("2003-program.pdf", range(13, 100)),
    2004: ("2004-program.pdf", range(9, 45)),
    2006: ("2006-descriptions.doc", None),
    2008: ("2008-abstracts.pdf", range(0, 70)),
    2009: ("2009-program.pdf", range(12, 92)),
    2010: ("2010-program.pdf", range(20, 90)),
    2011: ("2011-program.pdf", range(21, 94)),
}
# Years whose header lines are not set in bold (see the module docstring).
ONE_WEIGHT = {2010}

BOLD = 16
ITALIC = 2
# The programs' running page headers ("Undergraduate Research Symposium, 11")
# and page numbers.
RUNNING_HEADER = re.compile(r"\s*(?:Undergraduate Research Symposium,\s*[\divxlc]+|\d{1,3})\s*")
# "Faculty:", also "Faculty :" (2010), "Faculty Sponsor:" and "Adviser:".
ADVISOR_LINE = re.compile(r"\s*(?:Faculty(?: Sponsors?| Advis[eo]rs?)?|Advis[eo]rs?)\s*:\s*(.*)", re.S)
PROJECT = re.compile(r"\s*Project #(\d+)\s*")
PRESENTERS_2003 = re.compile(r"\s*Student Presenters?:\s*(.*)", re.S)
SPONSOR_2003 = re.compile(r"\s*Faculty Sponsors?:\s*(.*)", re.S)
HEADING_SIZE = 13  # section headings are set larger than the 10-12pt text
# The line under a section heading.
SUBHEADING = re.compile(r"\s*(?:alphabetical by .*|in order of appearance)\s*", re.I)
# The label before a performance's cast, who are its presenters too (2008).
ENSEMBLE = re.compile(r"\s*Performing Ensemble:\s*")


def source(name: str) -> str:
    """A saved file's capture, served as the original bytes (Wayback's id_ form)."""
    ts, url = ARCHIVED[name]
    return f"{WAYBACK}/{ts}id_/{url}"


def fetch(name: str, refresh: bool = False) -> Path:
    path = SYMPOSIUM_DIR / name
    if refresh or not path.exists():
        resp = httpx.get(source(name), headers=HEADERS, follow_redirects=True, timeout=180)
        resp.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(resp.content)
    if path.suffix == ".doc" and (refresh or not path.with_suffix(".html").exists()):
        # macOS's textutil; the conversion is committed, so parsing needs no Word reader.
        subprocess.run(["textutil", "-convert", "html", "-output", str(path.with_suffix(".html")), str(path)], check=True)
    return path


def lines(doc: pymupdf.Document, pages: range) -> list[dict]:
    """The pages' text lines in order, as {text, page, x0, x1, bold, italic,
    size}; a line of only Wingdings (the ornament between entries) as
    {"separator": True}. Running headers and page numbers are dropped."""
    out = []
    for n in pages:
        page = doc[n]
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                if all("Wingdings" in s["font"] for s in spans):
                    out.append({"separator": True, "page": n})
                    continue
                spans = [s for s in spans if "Wingdings" not in s["font"]]
                t = "".join(s["text"] for s in line["spans"] if "Wingdings" not in s["font"])
                if RUNNING_HEADER.fullmatch(t):
                    continue
                out.append({
                    "text": t,
                    "page": n,
                    "x0": min(s["bbox"][0] for s in spans),
                    "x1": max(s["bbox"][2] for s in spans),
                    "bold": all(s["flags"] & BOLD or "Bold" in s["font"] for s in spans),
                    "italic": all(s["flags"] & ITALIC or "Italic" in s["font"] for s in spans),
                    "size": max(s["size"] for s in spans),
                })
    return out


def left_margin(ls: list[dict]) -> float:
    """The text column's left edge: the commonest left edge of the document's lines."""
    return Counter(round(l["x0"]) for l in ls if "text" in l).most_common(1)[0][0]


def parse_2003(ls: list[dict]) -> list[dict]:
    """The 2003 descriptions: Project #N, presenters, sponsor, description."""
    entries = []
    i = 0
    while i < len(ls):
        m = PROJECT.fullmatch(ls[i].get("text", ""))
        if not m:
            i += 1
            continue
        number, page = int(m.group(1)), ls[i]["page"]
        i += 1
        header = []
        while i < len(ls) and ls[i].get("bold") and not PROJECT.fullmatch(ls[i]["text"]):
            header.append(ls[i]["text"])
            i += 1
        header = " ".join(header)
        sponsor = SPONSOR_2003.search(header)
        names = PRESENTERS_2003.match(header[: sponsor.start()] if sponsor else header)
        title = []
        while i < len(ls) and ls[i].get("italic") and not ls[i].get("bold"):
            title.append(ls[i]["text"])
            i += 1
        body = []
        while i < len(ls) and not PROJECT.fullmatch(ls[i].get("text", "")):
            if "text" in ls[i]:
                body.append(ls[i]["text"])
            i += 1
        entries.append({
            "project": number,
            "presenters": split_people(text(names.group(1)), last_first=False) if names else [],
            "advisor": text(sponsor.group(1)) if sponsor else None,
            "title": text("\n".join(title)) or None,
            "abstract": text("\n".join(body)),
            "page": page + 1,
        })
    return entries


def parse_program(ls: list[dict], one_weight: bool) -> list[dict]:
    """The descriptions of 2004 and 2008-2011, anchored on each advisor line:

    - presenters: the bold or italic (twice in 2004) lines just above it,
      with any plain line set in from the margin between them, or in a year
      of one weight, every line back to the ornament between entries;
    - title: the lines after it while they are bold or italic or set in from
      the left margin, up to the abstract's first line: one at the margin, or
      any plain line after a bold or italic one (some 2004 abstracts open
      with an indent). In years with bold, the title is the last bold or italic run,
      and plain lines before it name other mentors (2004: "MMSS Thesis
      Seminar Faculty Supervisor: Joseph Ferrie") and are kept as credits;
      where no line after the advisor is bold or italic (2008, Pradhan), the
      title is the plain lines;
    - abstract: the lines from there to the next entry's first line, the
      ornament between entries or a section heading.
    """
    left = left_margin(ls)

    def text_line(k: int) -> bool:
        return 0 <= k < len(ls) and "text" in ls[k]

    def styled(k: int) -> bool:
        return not one_weight and (ls[k]["bold"] or ls[k]["italic"])

    anchors = [k for k in range(len(ls)) if text_line(k) and ADVISOR_LINE.match(ls[k]["text"])]
    spans = []  # (first line, advisor line, first abstract line)
    for k in anchors:
        first = k
        if one_weight:
            while text_line(first - 1):
                first -= 1
        else:
            # Name lines are bold or italic. A plain line set in from the
            # margin counts only below one of them (2008: "Performing
            # Ensemble: ..., / Nate Trinrud, ..."). No name line has a digit,
            # which stops the walk at references ending an abstract.
            j = first - 1
            while text_line(j) and ls[j]["size"] <= HEADING_SIZE and not re.search(r"\d", ls[j]["text"]) and not SUBHEADING.fullmatch(ls[j]["text"]):
                if styled(j):
                    first = j
                elif ls[j]["x0"] <= left + 1:
                    break
                j -= 1
        body = k + 1
        seen_styled = False
        while text_line(body) and not ADVISOR_LINE.match(ls[body]["text"]):
            if styled(body):
                seen_styled = True
            elif seen_styled or ls[body]["x0"] <= left + 1:
                # A plain line after the title, or one at the margin: the abstract.
                break
            body += 1
        spans.append((first, k, body))

    entries = []
    for n, (first, k, body) in enumerate(spans):
        stop = spans[n + 1][0] if n + 1 < len(spans) else len(ls)
        rest = ls[k + 1 : body]
        if one_weight or not any(styled(j) for j in range(k + 1, body)):
            title, credits = rest, []
        else:
            cut = len(rest)
            while cut > 0 and (rest[cut - 1]["bold"] or rest[cut - 1]["italic"]):
                cut -= 1
            title, credits = rest[cut:], rest[:cut]
        abstract = []
        for l in ls[body:stop]:
            if "separator" in l or l["size"] > HEADING_SIZE:
                break
            abstract.append(l["text"])
        entries.append({
            "presenters": split_people(ENSEMBLE.sub(", ", text("\n".join(l["text"] for l in ls[first:k]))), last_first=False),
            "advisor": text(ADVISOR_LINE.match(ls[k]["text"]).group(1)) or None,
            "credits": [text(l["text"]) for l in credits],
            "title": text("\n".join(l["text"] for l in title)),
            "abstract": text("\n".join(abstract)),
            "page": ls[first]["page"] + 1,
        })
    return entries


def paragraphs(path: Path) -> list[dict]:
    """A textutil HTML conversion's non-empty paragraphs, as {text, bold, italic}:
    bold or italic when every run of text in it is."""
    out = []
    for body in re.findall(r"<p[^>]*>(.*?)</p>", path.read_text(encoding="utf-8"), re.S):
        plain = html.unescape(re.sub(r"<[^>]+>", "", body)).strip()
        if not plain:
            continue
        runs = [r for r in re.split(r"(<[^>]+>)", body) if r.strip()]
        out.append({"text": plain, "bold": all_inside(runs, "b"), "italic": all_inside(runs, "i")})
    return out


def all_inside(runs: list[str], tag: str) -> bool:
    """Whether every run of text among a paragraph's tags and text is inside tag."""
    depth = 0
    for r in runs:
        if re.fullmatch(fr"<{tag}\b[^>]*>", r):
            depth += 1
        elif r == f"</{tag}>":
            depth -= 1
        elif not r.startswith("<") and html.unescape(r).strip() and depth == 0:
            return False
    return True


# A Word field code left before a name ("CONTACT _CON-40AC7A711 \\C \\S \\L ").
FIELD_CODE = re.compile(r"CONTACT _CON-\w+(?: \\\w)*\s*")
# A cross-reference to a joint entry listed under another presenter
# ("ANNE MIKELONIS—see CRYSTAL LEE").
SEE = re.compile(r"\s*—\s*see\s")


def capitals(s: str) -> bool:
    """Whether a paragraph is a presenters line: in capitals, but for "and"."""
    letters = [c for c in re.sub(r"\band\b", "", s) if c.isalpha()]
    return len(letters) > 3 and all(c.isupper() for c in letters)


ROMAN = {"II", "III", "IV"}  # name suffixes, kept in capitals


def recase(word: str, case: dict[str, str]) -> str:
    """A word of a name printed in capitals, in the case the guide prints it
    in ("MCGLOTHLIN" as "McGlothlin"), or else capitalized ("STEPHANIE",
    which the guide spells "Stefanie"). The program's spelling is kept."""
    if word.rstrip(",.") in ROMAN:
        return word
    return case.get(word.casefold()) or "-".join(part.capitalize() for part in word.split("-"))


# The draft's page header and footer where they fall inside a description:
# "Project Descrition PAGE 56", "PAGE 55 Project Description".
RUNNING_HEAD = re.compile(r"^(?:Project Descri\w*\s+PAGE\s+\d+|PAGE\s+\d+\s+Project Description)$")


def letter_heading(p: dict) -> bool:
    """Whether a paragraph heads the entries under a letter of the alphabet:
    the letter alone, in bold or after a Wingdings symbol ("\uf063B")."""
    t = re.sub(r"[\ue000-\uf8ff]", "", p["text"]).strip()
    return len(t) == 1 and t.isalpha() and (p["bold"] or t != p["text"])


def parse_2006(paras: list[dict], case: dict[str, str]) -> list[dict]:
    """The 2006 descriptions: presenters in capitals, the title in bold, the
    advisor line in italics, then the description. case maps each word of
    the guide's names, folded, to its case there (see recase)."""
    paras = [{**p, "text": FIELD_CODE.sub("", p["text"])} for p in paras if not SEE.search(p["text"])]
    entries = []
    anchors = [k for k, p in enumerate(paras) if ADVISOR_LINE.match(p["text"])]
    for n, k in enumerate(anchors):
        first = k - 1
        while first >= 0 and not capitals(paras[first]["text"]):
            first -= 1
        title = [p["text"] for p in paras[first + 1 : k] if p["bold"]]
        stop = anchors[n + 1] if n + 1 < len(anchors) else len(paras)
        body = []
        for p in paras[k + 1 : stop]:
            if capitals(p["text"]) or letter_heading(p):
                break  # the next entry's presenters, or a letter heading
            if not RUNNING_HEAD.search(p["text"]):
                body.append(p["text"])
        names = re.split(r"\s*(?:,\s*and\s+|,|&|\band\b)\s*", paras[first]["text"], flags=re.I)
        people = []
        for name in filter(None, names):
            people += split_people(" ".join(recase(w, case) for w in name.split()), last_first=False)
        entries.append({
            "presenters": people,
            "advisor": text(ADVISOR_LINE.match(paras[k]["text"]).group(1)) or None,
            "title": text("\n".join(title)),
            "abstract": text("\n".join(body)),
            "page": None,
        })
    return entries


def fold_name(name: str) -> str:
    return "".join(words(name))


# Each program's guide to presentations, which lists every presentation again
# by session: (file, 0-based pages). 2003 and 2004 have only a schedule of
# names; the guides of 2006, 2008 and 2009 give each presenter's major, and
# those of 2010 and 2011 each presentation's title.
GUIDES = {
    2006: ("2006-front.doc", None),
    2008: ("2008-front.pdf", range(6, 13)),
    2009: ("2009-program.pdf", range(6, 12)),
    2010: ("2010-program.pdf", range(10, 20)),
    2011: ("2011-program.pdf", range(11, 20)),
}
TITLED_GUIDES = {2010, 2011}
# Guides that star the presenters who held an Office of the Provost
# Undergraduate Research Grant (URG); 2006's does not.
STARRED_GUIDES = {2008, 2009, 2010, 2011}
GUIDE_NUMBER = re.compile(r"(?m)^\s*\d+\.\s*")
# A titled guide entry, numbered or not: presenters, a star for a URG
# recipient, an optional comma, and the title in quotes, which may wrap and
# ends a line, but for a genre in parentheses ("Caroline Guo,* "A Break ..."",
# "Tara Garcia Mathewson* “Living ...”", "Angela Mears “Motherland” (Non-Fiction Essays)").
GUIDE_TITLE = re.compile(r"(?m)^(?:\s*\d+\.)?\s*([A-Z][^\n“\"]*?)\s*,?\s*\*?\s*[“\"](.+?)[”\"](?:\s*\([^()\n]*\))?\s*$", re.S)


def guide_names(names: str) -> list[tuple[str, bool]]:
    """A guide entry's presenters, each with whether it is starred (a URG recipient)."""
    out = []
    for name in re.split(r"\s*(?:,\s*and\s+|,|&|\band\b|\bwith\b)\s*", names):
        if name.strip(" *"):
            out.append((text(name.replace("*", "")), "*" in name))
    return out


def guide(year: int) -> list[dict]:
    """A year's guide entries in order: {presenters: [(name, urg)], major, title}."""
    name, pages = GUIDES[year]
    if pages is None:
        chunks = [p["text"] for p in paragraphs(fetch(name).with_suffix(".html")) if GUIDE_NUMBER.match(p["text"])]
        chunks = [GUIDE_NUMBER.sub("", c, count=1) for c in chunks]
    else:
        whole = "\n".join(pymupdf.open(fetch(name))[n].get_text() for n in pages)
        if year in TITLED_GUIDES:
            return [
                {"presenters": guide_names(m.group(1)), "major": None, "title": text(m.group(2))}
                for m in GUIDE_TITLE.finditer(whole)
            ]
        chunks = GUIDE_NUMBER.split(whole)[1:]
    out = []
    for c in chunks:
        line = next(l for l in c.split("\n") if l.strip())
        people, _, major = line.rpartition(",")
        out.append({"presenters": guide_names(people), "major": text(major.replace("*", "")) or None, "title": None})
        # The star follows the major ("Classics*"): it marks the entry's presenters.
        if "*" in major:
            out[-1]["presenters"] = [(n, True) for n, _ in out[-1]["presenters"]]
    return out


def near(a: str, b: str) -> bool:
    """Whether two words differ by at most one letter inserted, dropped or changed."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    short, long = sorted((a, b), key=len)
    return any(long[:i] + long[i + 1 :] == short for i in range(len(long)))


def name_key(first: str, last: str) -> str:
    return fold_name(f"{first} {last}")


def listings(year: int) -> list[dict]:
    """A year's listings in program order. Credits printed with an entry
    (other mentors and co-researchers, 2004) end its abstract, so the names
    stay searchable. Where the year has a guide, each presenter it lists
    gets their major (2006, 2008, 2009) and, as urg, whether the guide
    stars them as a URG recipient (2008-2011)."""
    name, pages = PROGRAMS[year]
    path = fetch(name)
    if year == 2006:
        case = {w.casefold(): w for e in guide(2006) for n, _ in e["presenters"] for w in n.split()}
        entries = parse_2006(paragraphs(path.with_suffix(".html")), case)
    else:
        ls = lines(pymupdf.open(path), pages)
        entries = parse_2003(ls) if year == 2003 else parse_program(ls, year in ONE_WEIGHT)
    listed = {}
    for g in guide(year) if year in GUIDES else []:
        for n, urg in g["presenters"]:
            listed.setdefault(fold_name(n), {"name": n, "major": g["major"], "urg": urg})

    def in_guide(p: dict) -> dict | None:
        """The presenter's guide listing: by name, or failing that (the two
        spell some names differently: "Wes" and "Wesley", "Menchacha" and
        "Menchaca"), the only one with the same first word of the first name
        or a prefix of it, and a surname differing by at most one letter."""
        if found := listed.get(name_key(p["first"], p["last"])):
            return found
        first = words(p["first"])[:1]
        close = [
            g for g in listed.values()
            if first and first_match(first[0], words(g["name"])[0]) and near(fold_name(p["last"]), fold_name(g["name"].split()[-1]))
        ]
        return close[0] if len(close) == 1 else None

    out = []
    for e in entries:
        credits = e.pop("credits", [])
        if credits:
            e["abstract"] = text("\n".join([e["abstract"], *credits]))
        for p in e["presenters"]:
            # A presenter the guide does not list (cast members, or a name
            # it spells too differently) gets neither key.
            if g := in_guide(p):
                if year not in TITLED_GUIDES:
                    p["major"] = g["major"]
                if year in STARRED_GUIDES:
                    p["urg"] = g["urg"]
        out.append(e)
    return out

"""Expo 2020 listings, from the ForagerOne presentations in data/raw/forager/.

Expo 2020 was held online, so it has no program of abstracts; the program
guide (data/raw/expo/2020.pdf) lists only presenters and titles, by section.
Each ForagerOne presentation becomes one listing in the shape
pipeline.parse_expo gives every other year, plus what only the platform
records:

- title, abstract and presenters as the presentation gives them, cleaned
  like the programs' text. Some abstracts open with the submission header
  (presenter, advisor and title) or a "Description" label; that is dropped.
- page: the guide page that lists it, or None for the 12 presentations the
  guide leaves out. The guide is the listing's source.
- advisor: ForagerOne's mentor field is empty for every presentation, so the
  advisor is taken from the poster or abstract where it names one by label
  (ADVISORS), and is None otherwise.
- forager_id, format (poster, oral or exhibition), subjects (the listing's
  subject tags) and each presenter's major and class year.

One project printed in the guide was never posted (SUPPLEMENTS): its listing
has the guide's title and, as its abstract, the student's own abstract of
the project from another venue, which abstract_source names ({name, url}),
so that a result can say where the text is from.

Used by pipeline.parse_expo, which writes the records.
"""

import json
import re

import pymupdf

from pipeline.link_expo import words
from pipeline.parse_expo import PARTICLES, RAW_DIR, text

FORAGER_DIR = RAW_DIR / "forager"
SUPPLEMENTS = RAW_DIR / "expo2020_supplements.json"
# Not a student project: a video of quotes from students, posted by OUR.
EXCLUDED = {2289}
# Advisors named by label on the poster or slides (or, for 2054, 2140 and
# 2202, in the abstract's submission header), by presentation id, with the
# words that name them. Graduate mentors listed under their own label are
# left out; people listed together under one label are kept together.
ADVISORS = {
    2054: ("Jesse Rosenberg", "abstract header: Isabella Spinelli / Jesse Rosenberg / title"),
    2081: ("Chris Petersen", "Advisor: Chris Petersen"),
    2110: ("Jolie Matthews", "Primary advisor: Dr. Jolie Matthews; Reader: Dr. David Rapp"),
    2132: ("Lisa Del Torto", "Mentor: Dr. Lisa Del Torto"),
    2140: ("Mesmin Destin, Shirin Vossoughi", "Primary Advisor: Professor Mesmin Destin; my two advisors, Professor Mesmin Destin and Professor Shirin Vossoughi"),
    2196: ("Mark Hauser", "Thank you to my advisor professor Mark Hauser"),
    2202: ("Molly Losh", "Faculty Mentor: Molly Losh, Ph.D. / Graduate Student Mentor: Shivani Patel, M.A."),
    2207: ("Alexandria Volkening", "Research Advisor: Alexandria Volkening"),
    2209: ("Mitchell Barklage", "supervised by Dr. Mitchell Barklage of the Earth and Planetary Sciences Department"),
    2215: ("Mark Alznauer", "Professor Mark Alznauer, my thesis advisor"),
    2217: ("Jennifer Nash", "Advisor: Dr. Jennifer Nash"),
    2218: ("Katherine Berman, Julius Lucks", "under direction of Katherine Berman and Dr. Julius Lucks"),
    2223: ("Jennifer Tackett", "Primary Advisor: Jennifer Tackett, Second Reader: Dan McAdams"),
    2227: ("Lydia F. Emery", "My mentor, Dr. Lydia F. Emery"),
    2236: ("Peter Penzes", "Faculty Mentor: Dr. Peter Penzes, Co-mentor: Dr. Colleen Zaccard"),
    2243: ("Thomas V. O’Halloran", "Faculty Advisor: Dr. Thomas V. O’Halloran"),
    2244: ("Lilah Shapiro, Nitasha Tamar Sharma", "Advisor: Dr. Lilah Shapiro / Complementary Advisor: Dr. Nitasha Tamar Sharma"),
    2246: ("Sue Fox, Anan Yu, Richard I. Morimoto", "under the direction of Sue Fox, Anan Yu, and Richard I. Morimoto"),
    2247: ("Brian Hitsman", "Faculty Advisor: Dr. Brian Hitsman, Feinberg School of Medicine"),
    2250: ("Richard M. Pope, Qi-Quan Huang", "Faculty Advisors: Richard M. Pope, Qi-Quan Huang"),
    2252: ("Tina Grieco-Calub, Kristi Ward", "her mentors Dr. Tina Grieco-Calub and Kristi Ward"),
    2266: ("Michelle Molina", "Advised by Dr. Michelle Molina"),
    2268: ("Sue Fox, Anan Yu, Richard I. Morimoto", "Under the mentorship of Sue Fox, Dr. Anan Yu, and Dr. Richard I. Morimoto"),
    2270: ("Claudia Haase, Vijay Mittal", "PI: Dr. Claudia Haase ... PI: Dr. Vijay Mittal"),
    2273: ("Karl A. Scheidt", "Advisor Dr. Karl A. Scheidt, Dept of Chemistry, CMIDD / Mentor Meghan J. Orr, MSTP G2"),
    2274: ("Lilah Shapiro, Wendi Gardner", "Advisor: Lilah Shapiro / Secondary Advisor: Wendi Gardner"),
    2275: ("Cassandra Callmann", "Supervisor: Dr. Cassandra Callmann"),
}
# A guide entry: presenters, then the title in quotes, wrapping onto plain
# lines; in the Creative Arts Festival, presenters, a dash, the title (quoted
# or not) and the medium in parentheses, wrapping onto indented bold lines.
GUIDE_ENTRY = re.compile(r"(.+?),\s*[“\"](.+?)[”\"]?\s*")
CREATIVE_ENTRY = re.compile(r"(.+?)\s+–\s+[“\"]?(.+?)[”\"]?\s*\([^()]*\)\s*")
# The guide's sections, by the format of the presentations they list.
GUIDE_SECTIONS = {"Poster Presentations": "poster", "Oral Presentations": "oral", "Creative Arts Festival": "exhibition"}
ENTRY_X = 90  # entries start at the left margin; wrapped lines are indented
# A leading label in an abstract, and a label line of its submission header.
LEADING_LABEL = re.compile(r"\s*(?:Abstract|Description(?: and Artist[’']?s? Statement)?)\s*\n")
HEADER_LABEL = re.compile(r"(?:Faculty|Doctoral Student|Graduate Student) (?:Advisor|Mentor)s?:")
# Minimum title-word overlap at which a short opening paragraph of an
# abstract is its title, repeated.
MIN_MATCH = 0.5


def guide_entries(doc: pymupdf.Document) -> list[dict]:
    """The guide's entries in order: presenters (as printed), title, section
    (as a presentation format) and 1-based page."""
    entries = []
    section = None
    for page in doc:
        for block in page.get_text("dict")["blocks"]:
            for line in block.get("lines", []):
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                t = "".join(s["text"] for s in spans)
                if spans[0]["size"] > 13:
                    section = next((f for name, f in GUIDE_SECTIONS.items() if name in t), section)
                    continue
                if section and spans[0]["flags"] & 16 and line["bbox"][0] < ENTRY_X:
                    entries.append({"text": t, "section": section, "page": page.number + 1})
                elif section and entries:
                    entries[-1]["text"] += " " + t
    out = []
    for e in entries:
        m = (CREATIVE_ENTRY if e["section"] == "exhibition" else GUIDE_ENTRY).fullmatch(e["text"].strip())
        if not m:
            raise SystemExit(f"unparsed guide entry on page {e['page']}: {e['text']!r}")
        out.append({"presenters": text(m.group(1)), "title": text(m.group(2)), "section": e["section"], "page": e["page"]})
    return out


def overlap(a: str, b: str) -> float:
    x, y = set(words(a)), set(words(b))
    return len(x & y) / len(x | y) if x | y else 0.0


def letters(s: str) -> str:
    return "".join(words(s))


def names_surname(guide_names: str, last: str) -> bool:
    """Whether a guide entry's presenters include this surname: written alike
    letter for letter ("AlSaid" and "Al-Said"), or sharing a word of it that is
    not a particle ("Van Etten" and "Etten")."""
    parts = {w for w in words(last) if len(w) > 2 and w not in PARTICLES}
    return letters(last) in letters(guide_names) or bool(parts & set(words(guide_names)))


def guide_index(pres: dict, title: str, guide: list[dict]) -> int | None:
    """The index of the guide entry for a presentation: one naming one of its
    presenters' surnames, in the section of its format if any is there (two
    posters were listed with the creative arts); of several, the one whose
    title is closest. Students often retitled their projects between the
    guide and the platform."""
    found = [i for i, g in enumerate(guide) if any(names_surname(g["presenters"], p["lastName"]) for p in pres["presenters"])]
    same = [i for i in found if guide[i]["section"] == pres["presentationType"]]
    return max(same or found, key=lambda i: overlap(title, guide[i]["title"]), default=None)


def presenters(pres: dict) -> list[dict]:
    """The presenters as first and last names, each once, with major and class year."""
    out = []
    for p in pres["presenters"]:
        first, last = text(p["firstName"]), text(p["lastName"])
        # 2207 gives "Christopher Lee" "Lee", the full name in the first-name
        # field, and 2240 "Andrea" "E Gouvea", a middle initial in the last.
        if first.endswith(" " + last):
            first = first[: -len(last) - 1]
        if m := re.fullmatch(r"([A-Z]\.?) (.+)", last):
            first, last = f"{first} {m.group(1)}", m.group(2)
        person = {"first": first, "last": last, "major": text(p.get("major") or "") or None, "level": text(p.get("level") or "") or None}
        if all((q["first"], q["last"]) != (first, last) for q in out):
            out.append(person)
    return out


def abstract(pres: dict, people: list[dict]) -> str:
    """The abstract without a leading label or submission header, cleaned like the programs'."""
    a = pres["abstract"].replace("​", "")
    # Soft hyphens stand for hyphens ("well\xaddocumented", "one\xadon\xadone")
    # and double real ones ("well\xad-understood").
    a = re.sub(r"-?\xad-?\s*", "-", a)
    a = LEADING_LABEL.sub("", a, count=1)
    names = {f"{p['first']} {p['last']}" for p in people}
    paragraphs = [p for p in re.split(r"\n\s*\n", a.strip()) if p.strip()]
    while len(paragraphs) > 1 and (
        paragraphs[0].strip() in names
        or HEADER_LABEL.match(paragraphs[0].strip())
        or paragraphs[0].split("\n")[0].strip() in names
        or (len(paragraphs[0].split()) < 30 and overlap(paragraphs[0], pres["title"]) >= MIN_MATCH)
    ):
        paragraphs.pop(0)
    return text("\n\n".join(paragraphs))


def entries(doc: pymupdf.Document) -> list[dict]:
    """The Expo 2020 listings: guide entries in guide order, then the rest by id."""
    guide = guide_entries(doc)
    tags = {p["presentationId"]: [t["name"] for t in p["tags"] if t["type"] == "Subject"] for p in json.loads((FORAGER_DIR / "listing.json").read_text())}
    out, order = [], []
    for d in sorted(FORAGER_DIR.iterdir()):
        if not d.is_dir() or int(d.name) in EXCLUDED:
            continue
        pres = json.loads((d / "presentation.json").read_text())
        pid = pres["presentationId"]
        title = text(pres["title"])
        people = presenters(pres)
        i = guide_index(pres, title, guide)
        order.append(i)
        out.append({
            "presenters": people,
            "advisor": ADVISORS[pid][0] if pid in ADVISORS else None,
            "title": title,
            "abstract": abstract(pres, people),
            "page": guide[i]["page"] if i is not None else None,
            "forager_id": pid,
            "format": pres["presentationType"],
            "subjects": tags[pid],
        })
    for s in json.loads(SUPPLEMENTS.read_text())["entries"]:
        g = s["guide"]
        (own,) = [r for r in s["related"] if r["note"].startswith(f"{g['presenters'][0].split()[-1]}'s own")]
        first, last = g["presenters"][0].rsplit(" ", 1)
        (i,) = [i for i, e in enumerate(guide) if e["title"] == text(g["title"])]
        order.append(i)
        out.append({
            "presenters": [{"first": first, "last": last, "major": None, "level": None}],
            "advisor": None,
            "title": text(g["title"]),
            "abstract": text(own["abstract"]),
            "abstract_source": {"name": own["publication"], "url": own["source"]},
            "page": g["page"],
            "format": "poster" if g["section"].startswith("Poster") else "oral",
            "subjects": [],
        })
    used = [i for i in order if i is not None]
    if len(used) != len(set(used)):
        raise SystemExit("two presentations matched one guide entry")
    # Guide order, then the presentations the guide leaves out, by id.
    ranked = sorted(zip(order, out), key=lambda x: (x[0] is None, x[0] or 0, x[1].get("forager_id", 0)))
    return [e for _, e in ranked]

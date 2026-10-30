"""Merge the NURJ records of one piece of undergraduate research into a work.

NURJ publishes a piece of research in several places: a post on the site
(data/nurj.json), the papers, posters and slides attached to it
(data/document_texts.json), a paper in a print edition (data/print_papers.json),
and a short entry on one of the NURJ x CAURS pages. This gathers every record
of the same piece into one work and leaves out what is not Northwestern
undergraduate research: features, letters, interviews of faculty, site
templates and the CAURS work of other schools.

Records are one work when
- a document is attached to a post (the document's nurj_records, or
  DOC_POSTS where those miss or point to an index page), or
- their titles are the same once case, punctuation and accents are ignored, or
  nearly the same (TITLE_RATIO) and they share an author surname, or
- they are listed in SAME, pairs read and judged the same piece by hand.

Works on related topics by the same student (a 2020 Expo poster and a 2021 talk
with a new title) stay separate works; linking them is a later step, as for
SURG grants and Expo abstracts.

Writes data/nurj_works.json: works, each with its title, authors and advisors
(from the most formal record: print edition, then post, then CAURS entry), the
earliest year, and its records (sources) with the rule that joined each; and
the records left out, each with the reason.

Usage: uv run python -m pipeline.nurj_works [--candidates]
  --candidates prints the pairs of separate works whose texts are most alike,
  for checking by hand that no merge is missed (see SAME and DIFFERENT).
"""

import json
import math
import re
import sys
from collections import Counter
from difflib import SequenceMatcher

from pipeline.link_expo import surname_parts, words
from pipeline.scrape_surg import DATA_DIR

# Title similarity (difflib ratio of the folded titles) at which two records
# with a shared author surname are one work. "Irish Language Revitalization in
# the Republic of Ireland and Northern Ireland" and the CAURS entry "Language
# Revitalization in ..." score 0.94; distinct works by one student stay under 0.6.
TITLE_RATIO = 0.85

# Posts that are not undergraduate research.
EXCLUDE_POSTS = {
    "nurj-4190": "WordPress theme demo content (architecture news)",
    "nurj-4189": "WordPress theme demo content (architecture news)",
    "nurj-188": "WordPress theme demo content (a Mies van der Rohe speech)",
    "nurj-207": "WordPress theme demo content (architecture news)",
    "nurj-137": "post template",
    "nurj-1902": "post template",
    "nurj-394": "a student's reflection on another NURJ article",
    "nurj-401": "feature on running the CAURS conference",
    "nurj-408": "interview with a faculty member",
    "nurj-414": "feature profiling an alumnus's research",
    "nurj-422": "The Faces of Undergraduate Research profile",
    "nurj-429": "The Faces of Undergraduate Research profile",
    "nurj-459": "The Faces of Undergraduate Research profile",
    "nurj-467": "The Faces of Undergraduate Research profile",
    "nurj-475": "The Faces of Undergraduate Research profile",
    "nurj-2264": "1851 Project feature",
    "nurj-2269": "1851 Project feature",
    "nurj-2273": "1851 Project feature",
    "nurj-2283": "1851 Project interview with a faculty member",
    "nurj-3531": "interview with a faculty member",
    "nurj-6504": "staff-written features",
}
# Documents whose nurj_records miss their post, or name only an index page.
DOC_POSTS = {
    "scribd-1049619173": "nurj-7473",  # embedded by the post; listed on the News page
    "site-tony-luo-group-formatted-google-docs": "nurj-1971",  # the group's report
    "site-img-4924-heic-sophie-boorstein": "nurj-3700",  # her poster as an image
}
# Documents attached to a research post that are not that research.
EXCLUDE_DOCS = {
    "scribd-726986527": "the post's second embed is an interview with Dr. Andrew Miri, not the paper",
}
# Documents with no post that are research in their own right.
DOC_WORKS = {
    "site-emilyshteynbergexpoposter-emily-shteynberg": {
        "title": "Soviet Immigrants' Perspective on Mental Health and the Impact of Stigma",
        "authors": ["Emily Shteynberg"],
        "year": 2021,
    },
}
# Posts that name no author in a form scrape_nurj reads; the names are from the
# attached paper (or, for nurj-7458 and nurj-2358, the embed title and post body).
POST_PEOPLE = {
    "nurj-2358": (["Megan Lebowitz"], []),
    "nurj-7458": (["Victor Chen"], []),
    "nurj-7460": (["Aishani Das-Ghosh", "Nickolas M. Pingel", "Snežana Stanimirović"], []),
    "nurj-7465": (["Zora S. Warren"], ["Sarah B. Rodriguez"]),
    "nurj-7467": (["Asha S. Henry"], ["David Rapp"]),
    "nurj-7469": (["Samantha Hesekiel"], ["Alissa Levy Chung"]),
    "nurj-7471": (["Olivia Lauri"], ["Alissa Levy Chung"]),
    "nurj-7473": (["Kaimei Gescuk"], []),
}
# Pages whose entries are each a CAURS abstract ("Author: / School: / Major:");
# only the Northwestern ones are kept. The year is the symposium's.
CAURS_PAGES = {"nurj-page-1839": 2020, "nurj-page-5849": 2021}
# Index and feature pages whose attached documents are not Northwestern research.
EXCLUDE_PAGES = {
    "nurj-page-1861": "1851 Project features",
    "nurj-page-4508": "NURJ x EXPO page of CAURS presenters from Loyola, UIC and IIT",
    "nurj-page-4206": "News index page",
}
# Pairs of records judged one work by reading them, beyond the title rules.
SAME: list[tuple[str, str, str]] = []
# Pairs --candidates lists that were read and judged different works.
DIFFERENT = {
    frozenset(("nurj:nurj-3707", "nurj:nurj-3662")),  # Kee and Gentner: two students' posters from one lab
    frozenset(("nurj:nurj-1644", "nurj:nurj-3660")),  # Moy: a 2020 diet study, then a 2021 Cebu microbiome poster
    frozenset(("nurj:nurj-1270", "nurj:nurj-3818")),  # Sriram: 2020 hearing-loss poster, 2021 auditory neuron poster
    frozenset(("nurj:nurj-7130", "nurj:nurj-7136")),  # Chow: two different 2025 papers
}
# Print research items: CAURS-NURJ Special Edition papers are kept only when
# their notes name Northwestern as the institution.
CAURS_EDITION = "CAURS-NURJ Special Edition"


def volume_year(label: str) -> int:
    """The year a print edition came out: the end of its academic year."""
    if label == CAURS_EDITION:
        return 2015  # caurs_5.31.15
    return max(int(y) for y in re.findall(r"(?:19|20)\d\d", label))


def surnames(names: list[str]) -> set[str]:
    out = set()
    for name in names:
        for person in re.split(r",|\band\b|&", name):
            parts = words(person)
            parts = [p for p in parts if p not in {"phd", "md", "dr"}]
            if parts:
                out |= surname_parts(parts[-1])
    return out


def caurs_entries(page: dict, year: int) -> list[dict]:
    """The abstracts on a NURJ x CAURS page: a heading, then text blocks."""
    entries, current = [], None
    for b in page["blocks"]:
        if b["type"] == "heading":
            current = {"title": b["text"], "blocks": []}
            entries.append(current)
        elif current and b["type"] == "text" and b["text"] != "Click Here for More":
            current["blocks"].append(b["text"])
    out = []
    for n, e in enumerate(entries):
        first = e["blocks"][0].split("\n") if e["blocks"] else []
        fields = dict(line.split(": ", 1) for line in first if re.match(r"(Author|School|Major): ", line))
        out.append({
            "id": f"{page['id']}#{n}",
            "title": e["title"],
            "authors": [fields["Author"]] if "Author" in fields else [],
            "school": fields.get("School"),
            "major": fields.get("Major"),
            "year": year,
            "url": page["wp"]["link"],
            "text": "\n\n".join(e["blocks"]),
        })
    return out


def post_record(p: dict) -> dict:
    advisors = list(dict.fromkeys(lab["value"] for person in p["people"] for lab in person["labels"] if lab["label"] in ("Adviser", "Advisor", "Faculty Advisor", "Faculty Adviser")))
    authors = [person["name"] for person in p["people"]]
    if p["id"] in POST_PEOPLE:
        if authors:
            raise ValueError(f"{p['id']} now names its people; drop it from POST_PEOPLE")
        authors, advisors = POST_PEOPLE[p["id"]]
    return {"type": "post", "id": p["id"], "title": p["title"], "authors": authors, "advisors": advisors, "year": int(p["wp"]["date"][:4]), "url": p["wp"]["link"]}


def records() -> tuple[list[dict], list[dict]]:
    """Every NURJ record of undergraduate research, and those left out with why."""
    nurj = json.loads((DATA_DIR / "nurj.json").read_text())
    docs = json.loads((DATA_DIR / "document_texts.json").read_text())
    prints = json.loads((DATA_DIR / "print_papers.json").read_text())
    pages = {p["id"]: p for p in nurj["pages"]}
    keep, left = [], []

    posts = {}
    for p in nurj["posts"]:
        if p["id"] in EXCLUDE_POSTS:
            left.append({"type": "post", "id": p["id"], "title": p["title"], "reason": EXCLUDE_POSTS[p["id"]]})
        else:
            posts[p["id"]] = post_record(p)
    keep += posts.values()

    for d in docs:
        rec = {"type": "document", "id": d["id"], "title": d["nurj_title"] or d["label"], "format": d["format"], "url": d["source_url"], "words": len(d["text"].split())}
        targets = [DOC_POSTS[d["id"]]] if d["id"] in DOC_POSTS else [r for r in d["nurj_records"] if r in posts]
        if d["id"] in EXCLUDE_DOCS:
            left.append({**rec, "reason": EXCLUDE_DOCS[d["id"]]})
        elif d["id"] in DOC_WORKS:
            keep.append({**rec, **DOC_WORKS[d["id"]], "advisors": []})
        elif targets:
            keep.append({**rec, "posts": targets})
        else:
            why = [EXCLUDE_POSTS.get(r) or EXCLUDE_PAGES.get(r) for r in d["nurj_records"]]
            if not d["nurj_records"] or None in why:
                raise ValueError(f"document {d['id']} belongs to no post or known page: {d['nurj_records']}")
            left.append({**rec, "reason": "; ".join(dict.fromkeys(why))})

    for p in prints:
        rec = {"type": "print", "id": p["id"], "title": p["title"], "authors": p["authors"], "advisors": p["advisors"], "year": volume_year(p["volume"]), "volume": p["volume"], "pages": p["printed_pages"], "url": p["source"]}
        if p["kind"] != "research":
            left.append({**rec, "reason": f"print {p['kind']}"})
        elif p["volume"] == CAURS_EDITION and "Institution: Northwestern University" not in (p["notes"] or ""):
            left.append({**rec, "reason": "CAURS paper from another school"})
        else:
            keep.append(rec)

    for pid, year in CAURS_PAGES.items():
        for e in caurs_entries(pages[pid], year):
            rec = {"type": "caurs entry", "id": e["id"], "title": e["title"], "authors": e["authors"], "advisors": [], "year": e["year"], "school": e["school"], "url": e["url"]}
            if e["school"] == "Northwestern University":
                keep.append(rec)
            else:
                left.append({**rec, "reason": f"CAURS abstract from {e['school']}"})
    return keep, left


def title_key(title: str) -> str:
    return " ".join(words(title))


def merge(recs: list[dict]) -> list[list[tuple[dict, str]]]:
    """Group records into works; each record comes with the rule that joined it."""
    parent = {r["id"]: r["id"] for r in recs}
    joined_by = {}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b, why):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra
            joined_by.setdefault(b, why)

    by_id = {r["id"]: r for r in recs}
    for r in recs:
        for post in r.get("posts", []):
            union(post, r["id"], "document of the post")
    titled = [r for r in recs if r["type"] != "document"]
    for i, a in enumerate(titled):
        for b in titled[i + 1:]:
            ka, kb = title_key(a["title"]), title_key(b["title"])
            if ka == kb:
                union(a["id"], b["id"], "same title")
            elif surnames(a["authors"]) & surnames(b["authors"]) and SequenceMatcher(None, ka, kb).ratio() >= TITLE_RATIO:
                union(a["id"], b["id"], "near-identical title, shared author surname")
    for a, b, why in SAME:
        union(a, b, why)

    groups: dict[str, list[tuple[dict, str]]] = {}
    for r in recs:
        groups.setdefault(find(r["id"]), []).append((r, joined_by.get(r["id"], "")))
    return [g for g in groups.values() if any(r["type"] != "document" or r["id"] in DOC_WORKS for r, _ in g)]


RANK = {"print": 0, "post": 1, "caurs entry": 2, "document": 3}


def work(group: list[tuple[dict, str]]) -> dict:
    recs = sorted((r for r, _ in group), key=lambda r: (RANK[r["type"]], r["year"] if "year" in r else 0))
    lead = recs[0]
    authors = next((r["authors"] for r in recs if r.get("authors")), [])
    advisors = next((r["advisors"] for r in recs if r.get("advisors")), [])
    sources = []
    for r, why in sorted(group, key=lambda x: (RANK[x[0]["type"]], x[0]["id"])):
        s = {k: v for k, v in r.items() if k not in ("posts",)}
        s["joined_by"] = why or "lead record"
        sources.append(s)
    return {
        "id": f"nurj:{lead['id']}",
        "title": lead["title"],
        "authors": authors,
        "advisors": advisors,
        "year": min(r["year"] for r in recs if "year" in r),
        "sources": sources,
    }


def texts() -> dict[str, str]:
    """Each record's text, for --candidates."""
    nurj = json.loads((DATA_DIR / "nurj.json").read_text())
    out = {p["id"]: " ".join(b.get("text") or "" for b in p["blocks"] if b["type"] == "text") for p in nurj["posts"]}
    out |= {d["id"]: d["text"] for d in json.loads((DATA_DIR / "document_texts.json").read_text())}
    out |= {p["id"]: p["text"] for p in json.loads((DATA_DIR / "print_papers.json").read_text())}
    for pid, year in CAURS_PAGES.items():
        nurj_pages = {p["id"]: p for p in nurj["pages"]}
        out |= {e["id"]: e["text"] for e in caurs_entries(nurj_pages[pid], year)}
    return out


def candidates(works: list[dict], top: int = 40) -> None:
    """Print the pairs of separate works whose title and opening text (first 400
    words) are most alike by TF-IDF cosine, for reading by hand."""
    text = texts()
    docs = []
    for w in works:
        body = " ".join(" ".join(text.get(s["id"], "").split()[:400]) for s in w["sources"])
        docs.append(Counter(words(w["title"] + " " + w["title"] + " " + body)))
    df = Counter(t for d in docs for t in d)
    vecs = []
    for d in docs:
        v = {t: (1 + math.log(c)) * math.log(len(docs) / df[t]) for t, c in d.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
        vecs.append({t: x / norm for t, x in v.items()})
    pairs = []
    for i in range(len(works)):
        for j in range(i + 1, len(works)):
            a, b = vecs[i], vecs[j]
            if len(a) > len(b):
                a, b = b, a
            sim = sum(x * b.get(t, 0.0) for t, x in a.items())
            if frozenset((works[i]["id"], works[j]["id"])) not in DIFFERENT:
                pairs.append((sim, i, j))
    for sim, i, j in sorted(pairs, reverse=True)[:top]:
        a, b = works[i], works[j]
        shared = surnames(a["authors"]) & surnames(b["authors"])
        print(f"{sim:.2f} {'shared ' + ','.join(sorted(shared)) if shared else ''}\n  {a['id']} ({a['year']}) {a['title'][:90]} | {', '.join(a['authors'])[:40]}\n  {b['id']} ({b['year']}) {b['title'][:90]} | {', '.join(b['authors'])[:40]}")


def main() -> None:
    keep, left = records()
    works = sorted((work(g) for g in merge(keep)), key=lambda w: (w["year"], w["title"]))
    ids = [w["id"] for w in works]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate work ids")
    if "--candidates" in sys.argv:
        candidates(works)
        return
    out = DATA_DIR / "nurj_works.json"
    out.write_text(json.dumps({"works": works, "left_out": left}, indent=1, ensure_ascii=False) + "\n")
    kinds = Counter(tuple(sorted({s["type"] for s in w["sources"]})) for w in works)
    print(f"{len(works)} works from {len(keep)} records ({len(left)} left out) -> {out}")
    for k, n in kinds.most_common():
        print(f"  {n:4} {' + '.join(k)}")


if __name__ == "__main__":
    main()

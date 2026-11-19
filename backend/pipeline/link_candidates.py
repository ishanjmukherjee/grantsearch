"""Pair records that may be one piece of work, by student or by mentor.

Each pairing names the sources whose records are paired with whose (see
PAIRINGS): SURG grants with Expo and Symposium posters, senior theses with
grants, posters, NURJ papers and each other, NURJ papers with grants,
posters and each other, and Leopold fellowships with every other source and
each other. A pair is a candidate when
some student on one record and some student on the other may be one person
(see pipeline.records.same_person; for Leopold fellows, by any first name
they are printed with, see may_be_one), in any years: for grants and posters, a
window of one year before the grant to three after leaves out only 21 of 710
pairs, all different students with one name. A record is never paired with
itself, and pairs data/links.jsonl already judges, in either order, or
already joins into one project (see pipeline.projects), are skipped.

The "mentors" pairing pairs Leopold fellowships with each other by faculty
mentor instead: a fellowship's project is its mentor's, worked on by one
fellow after another, so the fellows of one project in different years are
usually different students. Two fellowships are a candidate when a mentor of
one may be a mentor of the other and their titles (or, without one, the
descriptions their entries give) share a word (see stems), or one names no
project at all.

A candidate whose titles have the same words (see pipeline.records.words) is
the same work, and is added to data/links.jsonl as a "same" link with high
confidence and method "title". The rest are written to --out, one pair per
line with both records in full, for judging by reading them; their verdicts
go into data/links.jsonl by hand.

Usage: uv run python -m pipeline.link_candidates {posters,theses,nurj,leopold,mentors} --out PATH [--dry-run]
"""

import argparse
import itertools
import json
from pathlib import Path

from pipeline import records
from pipeline.projects import LINKS, components, same_links

POSTER_SOURCES = ("expo", "symposium")
PAIRINGS = {
    "posters": (("surg",), POSTER_SOURCES),
    "theses": (("theses",), ("surg", "ay_urg", *POSTER_SOURCES, "nurj", "theses")),
    "nurj": (("nurj",), ("surg", "ay_urg", *POSTER_SOURCES, "nurj")),
    "leopold": (("leopold",), ("surg", "ay_urg", *POSTER_SOURCES, "theses", "nurj", "leopold")),
    "mentors": (("leopold",), ("leopold",)),
}
# Words too common in history project titles to suggest one project.
COMMON = set(
    "about across after all america american americans among and are before between but century culture early for from global her his history histories historical how into its life lives modern new northwestern not one other over than that the their them they this through two under united states toward towards urban was what when where who why with world".split()
)


def students(r: dict) -> list[dict]:
    return [p for p in r["people"] if p["role"] == "student"]


def mentors(r: dict) -> list[dict]:
    return [p for p in r["people"] if p["role"] == "advisor"]


def may_be_one(a: dict, b: dict) -> bool:
    """Whether two students may be one person (see
    pipeline.records.same_person) by any of the first names each is printed
    with: "Lien (Sam) H. Nguyen" is "Sam Nguyen" elsewhere, and "Pete
    (Pengyue) Wang" is "Pengyue (Pete) Wang"."""
    if not records.surname_parts(a["last"]) & records.surname_parts(b["last"]):
        return False
    return any(records.first_match(x, y) for x in records.tokens(a["first"]) for y in records.tokens(b["first"]))


def candidates(left: list[dict], right: list[dict], judged: set[frozenset], match=records.same_person) -> list[tuple[dict, dict]]:
    """Unjudged pairs of a left and a right record that share a student by
    match, each pair once, in id order."""
    by_surname: dict[str, list[dict]] = {}
    for b in right:
        for part in {s for p in students(b) for s in records.surname_parts(p["last"])}:
            by_surname.setdefault(part, []).append(b)
    seen: set[frozenset] = set()
    out = []
    for a in left:
        near = {b["id"]: b for p in students(a) for s in records.surname_parts(p["last"]) for b in by_surname.get(s, [])}
        for b in near.values():
            key = frozenset((a["id"], b["id"]))
            if b["id"] == a["id"] or key in judged or key in seen:
                continue
            if any(match(x, y) for x in students(a) for y in students(b)):
                seen.add(key)
                out.append((a, b))
    return sorted(out, key=lambda pair: (pair[0]["id"], pair[1]["id"]))


def project_text(r: dict) -> str:
    return r["title"] or r["extra"].get("description") or ""


def stems(r: dict) -> set[str]:
    """The first five letters of each word of three or more letters in a
    fellowship's title or description, leaving out COMMON words: enough to
    match "presidency" with "presidential" and "bisexual" with "bisexuality",
    and to keep "tax" and "war"."""
    return {w[:5] for w in records.words(project_text(r)) if len(w) >= 3 and w not in COMMON}


def mentor_candidates(fellowships: list[dict], judged: set[frozenset]) -> list[tuple[dict, dict]]:
    """Unjudged pairs of fellowships that share a mentor and a word of their
    titles, or of which one names no project, in id order."""
    out = []
    for a, b in itertools.combinations(sorted(fellowships, key=lambda r: r["id"]), 2):
        if frozenset((a["id"], b["id"])) in judged:
            continue
        if not any(records.same_person(x, y) for x in mentors(a) for y in mentors(b)):
            continue
        if not project_text(a) or not project_text(b) or stems(a) & stems(b):
            out.append((a, b))
    return out


def same_title(a: dict, b: dict) -> bool:
    return bool(a["title"] and b["title"]) and records.words(a["title"]) == records.words(b["title"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pairing", choices=PAIRINGS, help="which sources to pair")
    parser.add_argument("--out", type=Path, required=True, help="where to write the pairs left to judge")
    parser.add_argument("--dry-run", action="store_true", help="count, but write nothing")
    args = parser.parse_args()

    judged = {frozenset((link["a"], link["b"])) for link in map(json.loads, LINKS.open())}
    left, right = PAIRINGS[args.pairing]
    left_records, right_records = records.load(*left), records.load(*right)
    if args.pairing == "mentors":
        pairs = mentor_candidates(left_records, judged)
        reason = "Same title, and a faculty mentor of one is a faculty mentor of the other."
    else:
        pairs = candidates(left_records, right_records, judged, may_be_one if args.pairing == "leopold" else records.same_person)
        reason = "Same title, and a student of one is a student of the other."
    ids = [r["id"] for r in records.load(*records.SOURCES)]
    project = {i: n for n, group in enumerate(components(ids, same_links())) for i in group}
    pairs = [(a, b) for a, b in pairs if project[a["id"]] != project[b["id"]]]
    by_title = [(a, b) for a, b in pairs if same_title(a, b)]
    rest = [(a, b) for a, b in pairs if not same_title(a, b)]
    print(f"{len(pairs)} candidates: {len(by_title)} with the same title, {len(rest)} to judge")
    if args.dry_run:
        return
    with LINKS.open("a") as f:
        for a, b in by_title:
            f.write(json.dumps({"a": a["id"], "b": b["id"], "relation": "same", "confidence": "high", "method": "title", "reason": reason}, ensure_ascii=False) + "\n")
    with args.out.open("w") as f:
        for a, b in rest:
            f.write(json.dumps({"a": a, "b": b}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()

"""Pair records that may be one piece of work, by student name.

Each pairing names the sources whose records are paired with whose (see
PAIRINGS): SURG grants with Expo and Symposium posters, senior theses with
grants, posters, NURJ papers and each other, and NURJ papers with grants,
posters and each other. A pair is a candidate when
some student on one record and some student on the other may be one person
(see pipeline.records.same_person), in any years: for grants and posters, a
window of one year before the grant to three after leaves out only 21 of 710
pairs, all different students with one name. A record is never paired with
itself, and pairs data/links.jsonl already judges, in either order, are
skipped.

A candidate whose titles have the same words (see pipeline.records.words) is
the same work, and is added to data/links.jsonl as a "same" link with high
confidence and method "title". The rest are written to --out, one pair per
line with both records in full, for judging by reading them; their verdicts
go into data/links.jsonl by hand.

Usage: uv run python -m pipeline.link_candidates {posters,theses,nurj} --out PATH [--dry-run]
"""

import argparse
import json
from pathlib import Path

from pipeline import records
from pipeline.projects import LINKS

POSTER_SOURCES = ("expo", "symposium")
PAIRINGS = {
    "posters": (("surg",), POSTER_SOURCES),
    "theses": (("theses",), ("surg", "ay_urg", *POSTER_SOURCES, "nurj", "theses")),
    "nurj": (("nurj",), ("surg", "ay_urg", *POSTER_SOURCES, "nurj")),
}


def students(r: dict) -> list[dict]:
    return [p for p in r["people"] if p["role"] == "student"]


def candidates(left: list[dict], right: list[dict], judged: set[frozenset]) -> list[tuple[dict, dict]]:
    """Unjudged pairs of a left and a right record that share a student, each
    pair once, in id order."""
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
            if any(records.same_person(x, y) for x in students(a) for y in students(b)):
                seen.add(key)
                out.append((a, b))
    return sorted(out, key=lambda pair: (pair[0]["id"], pair[1]["id"]))


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
    pairs = candidates(records.load(*left), records.load(*right), judged)
    by_title = [(a, b) for a, b in pairs if same_title(a, b)]
    rest = [(a, b) for a, b in pairs if not same_title(a, b)]
    print(f"{len(pairs)} candidates: {len(by_title)} with the same title, {len(rest)} to judge")
    if args.dry_run:
        return
    with LINKS.open("a") as f:
        for a, b in by_title:
            f.write(json.dumps({"a": a["id"], "b": b["id"], "relation": "same", "confidence": "high", "method": "title", "reason": "Same title, and a student of one is a student of the other."}, ensure_ascii=False) + "\n")
    with args.out.open("w") as f:
        for a, b in rest:
            f.write(json.dumps({"a": a, "b": b}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()

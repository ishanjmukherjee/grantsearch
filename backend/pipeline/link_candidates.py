"""Pair SURG grants with Expo and Symposium posters by student name.

A pair is a candidate when some student on the grant and some presenter on
the poster may be one person (see pipeline.records.same_person), in any
years: a window of one year before the grant to three after leaves out only
21 of 710 pairs, all different students with one name. Pairs
data/links.jsonl already judges, in either order, are skipped.

A candidate whose titles have the same words (see pipeline.records.words) is
the same work, and is added to data/links.jsonl as a "same" link with high
confidence and method "title". The rest are written to --out, one pair per
line with both records in full, for judging by reading them; their verdicts
go into data/links.jsonl by hand.

Usage: uv run python -m pipeline.link_candidates --out PATH [--dry-run]
"""

import argparse
import json
from pathlib import Path

from pipeline import records
from pipeline.projects import LINKS

POSTER_SOURCES = ("expo", "symposium")


def students(r: dict) -> list[dict]:
    return [p for p in r["people"] if p["role"] == "student"]


def candidates(grants: list[dict], posters: list[dict], judged: set[frozenset]) -> list[tuple[dict, dict]]:
    """Unjudged (grant, poster) pairs that share a student, in id order."""
    by_surname: dict[str, list[dict]] = {}
    for p in posters:
        for part in {s for b in students(p) for s in records.surname_parts(b["last"])}:
            by_surname.setdefault(part, []).append(p)
    out = []
    for g in grants:
        near = {p["id"]: p for a in students(g) for s in records.surname_parts(a["last"]) for p in by_surname.get(s, [])}
        for p in near.values():
            if frozenset((g["id"], p["id"])) not in judged and any(records.same_person(a, b) for a in students(g) for b in students(p)):
                out.append((g, p))
    return sorted(out, key=lambda pair: (pair[0]["id"], pair[1]["id"]))


def same_title(g: dict, p: dict) -> bool:
    return bool(g["title"] and p["title"]) and records.words(g["title"]) == records.words(p["title"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True, help="where to write the pairs left to judge")
    parser.add_argument("--dry-run", action="store_true", help="count, but write nothing")
    args = parser.parse_args()

    judged = {frozenset((link["a"], link["b"])) for link in map(json.loads, LINKS.open())}
    pairs = candidates(records.load("surg"), records.load(*POSTER_SOURCES), judged)
    by_title = [(g, p) for g, p in pairs if same_title(g, p)]
    rest = [(g, p) for g, p in pairs if not same_title(g, p)]
    print(f"{len(pairs)} candidates: {len(by_title)} with the same title, {len(rest)} to judge")
    if args.dry_run:
        return
    with LINKS.open("a") as f:
        for g, p in by_title:
            f.write(json.dumps({"a": g["id"], "b": p["id"], "relation": "same", "confidence": "high", "method": "title", "reason": "Same title, and a student on the grant presents the poster."}, ensure_ascii=False) + "\n")
    with args.out.open("w") as f:
        for g, p in rest:
            f.write(json.dumps({"a": g, "b": p}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()

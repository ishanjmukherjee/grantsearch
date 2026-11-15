"""The disciplines each project is filed under, for filtering results.

Every project is read once and filed under one to three of the 37
disciplines in DISCIPLINES, the main one first (prompts/discipline.md): the
discipline whose questions and methods the work uses, then any other that
would claim it. The reader sees what a result shows of the project and what
its cards say of it; a card's own fields are a hint and no more.

Filing through the fields was tried first: each of the 1,903 field names the
cards use was judged once, and a project took the disciplines of its cards'
fields. On 300 projects that gave 2.29 disciplines a project where two
direct readers gave 1.73 and 1.77, and 24% of them were ones neither reader
gave ("statistics" on a political science thesis that runs regressions,
"biology education" putting a classroom study under Biology), while it left
out 3% of those both gave.

data/generated/disciplines.jsonl holds one line per filed project:

- id: the project's id.
- records: the ids of the records it was read as, sorted. A project is
  computed from the links on loading (see pipeline.projects), so its line
  stands only while it is still those records.
- disciplines: ids from DISCIPLINES, the main one first; empty for a project
  nothing says anything about (a bare title that evokes nothing).

A project is pending when it has no line, or its records are no longer its
line's. A pending project has no discipline, and a discipline filter leaves
it out. data/overrides.jsonl patches lines by id like any generated file's.

Judging: --batches writes the pending projects in batches, each as its
title, its sources (each record's kind and year, with an advisor's
department and a student's majors where the source prints them), its first
abstract, cut at ABSTRACT characters, and its cards' glosses and fields.

--merge reads the verdicts ({id, disciplines} per line, with an optional
note the reader left for whoever reads the run) and rewrites the file. A
project may be read more than once: it then takes each discipline that more
than half of its readers give, in the order of the first reader to give it,
and stays pending if that leaves none. Pass every reader's files to one
--merge.

Usage: uv run python -m pipeline.disciplines [--batches DIR [--size 150] [--all]] [--merge FILE ...]
Without options, prints how many projects each discipline holds, as any of
a project's disciplines and as its main one, and exits 1 if any project is
pending.
"""

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from pipeline.projects import DATA_DIR, GENERATED, OVERRIDES, load_projects
from pipeline.records import merge_patch

NAME = f"{GENERATED}/disciplines.jsonl"
BRIEF = DATA_DIR.parent / "prompts" / "discipline.md"
ABSTRACT = 1500

# (id, label, area), in the order the site lists them. The brief describes
# each one's scope under the same id.
DISCIPLINES = [
    ("biology", "Biology", "Life sciences"),
    ("neuroscience", "Neuroscience", "Life sciences"),
    ("medicine", "Medicine", "Health"),
    ("public-health", "Public health", "Health"),
    ("communication-disorders", "Communication sciences & disorders", "Health"),
    ("chemistry", "Chemistry", "Physical sciences & math"),
    ("physics-astronomy", "Physics & astronomy", "Physical sciences & math"),
    ("earth-environment", "Earth & environment", "Physical sciences & math"),
    ("math-statistics", "Math & statistics", "Physical sciences & math"),
    ("biomedical-engineering", "Biomedical engineering", "Engineering & computing"),
    ("materials-science", "Materials science", "Engineering & computing"),
    ("chemical-engineering", "Chemical engineering", "Engineering & computing"),
    ("engineering", "Mechanical, civil & electrical engineering", "Engineering & computing"),
    ("computer-science", "Computer science", "Engineering & computing"),
    ("psychology", "Psychology", "Social sciences"),
    ("cognitive-linguistics", "Cognitive science & linguistics", "Social sciences"),
    ("economics", "Economics", "Social sciences"),
    ("business-finance", "Business & finance", "Social sciences"),
    ("political-science", "Political science", "Social sciences"),
    ("sociology", "Sociology", "Social sciences"),
    ("anthropology", "Anthropology", "Social sciences"),
    ("education", "Education", "Social sciences"),
    ("law", "Law", "Social sciences"),
    ("public-policy", "Public policy", "Social sciences"),
    ("history", "History", "Humanities"),
    ("literature-languages", "Literature & languages", "Humanities"),
    ("philosophy", "Philosophy", "Humanities"),
    ("religion", "Religion", "Humanities"),
    ("gender-sexuality", "Gender & sexuality", "Humanities"),
    ("race-ethnicity", "Race & ethnicity", "Humanities"),
    ("area-studies", "Area & global studies", "Humanities"),
    ("art", "Art & art history", "Arts & media"),
    ("theatre-performance", "Theatre, dance & performance", "Arts & media"),
    ("music", "Music", "Arts & media"),
    ("film-media", "Film & media", "Arts & media"),
    ("creative-writing", "Creative writing", "Arts & media"),
    ("journalism-communication", "Journalism & communication", "Arts & media"),
]
IDS = [d[0] for d in DISCIPLINES]
KINDS = {"surg": "SURG grant", "ay_urg": "AY URG grant", "expo": "Expo poster", "symposium": "Symposium poster", "nurj": "NURJ paper"}


def record_ids(p: dict) -> list[str]:
    return sorted(r["id"] for r in p["records"])


def load() -> dict[str, dict]:
    """The filed projects' lines by id, with the overrides applied."""
    path = DATA_DIR / NAME
    table = {x["id"]: x for x in map(json.loads, path.open())} if path.exists() else {}
    for o in map(json.loads, OVERRIDES.open()):
        if o["file"] == NAME:
            table[o["id"]] = merge_patch(table.get(o["id"], {"id": o["id"]}), o["patch"])
    return table


def of(p: dict, table: dict[str, dict]) -> list[str]:
    """A project's disciplines, the main one first; none while it is pending."""
    line = table.get(p["id"])
    return line["disciplines"] if line and line["records"] == record_ids(p) else []


def pending(projects: list[dict], table: dict[str, dict]) -> list[dict]:
    return [p for p in projects if p["id"] not in table or table[p["id"]]["records"] != record_ids(p)]


def evidence(p: dict) -> dict:
    """What the reader is given of a project; see the module docstring."""

    def source(r: dict) -> str:
        what = f"{r['extra']['department']} thesis" if r["kind"] == "thesis" else KINDS[r["source"]]
        who = []
        for x in r["people"]:
            if x["role"] == "advisor" and x.get("department"):
                who.append(f"advisor in {x['department']}")
            majors = x.get("majors") or x.get("major")
            if x["role"] == "student" and majors:
                who.append(f"student majoring in {majors}")
        return f"{what} {r['year']}" + (f" ({'; '.join(who)})" if who else "")

    abstracts = [e["abstract"] for e in p["entries"]] + [r.get("abstract") for r in p["records"]]
    return {
        "id": p["id"],
        "title": p["title"] or p["made_title"],
        "sources": [source(r) for r in p["records"]],
        "abstract": next((a[:ABSTRACT] for a in abstracts if a), None),
        "glosses": [c["card"]["gloss"] for c in p["cards"]],
        "fields": list(dict.fromkeys(f for c in p["cards"] for f in c["card"]["fields"])),
    }


def merge(projects: list[dict], table: dict[str, dict], verdicts: list[dict]) -> tuple[dict[str, dict], list[str]]:
    """The table with the verdicts added, and the projects whose readers
    share no discipline; see the module docstring."""
    by_id = {p["id"]: p for p in projects}
    read: dict[str, list[list[str]]] = defaultdict(list)
    for v in verdicts:
        if not set(v) <= {"id", "disciplines", "note"} or v.get("id") not in by_id:
            raise SystemExit(f"{v.get('id')}: not a verdict on a project: {v}")
        chosen = v.get("disciplines")
        if not isinstance(chosen, list) or len(chosen) > 3 or len(set(chosen)) != len(chosen) or not set(chosen) <= set(IDS):
            raise SystemExit(f"{v['id']}: {chosen!r} is not a list of up to three distinct discipline ids")
        read[v["id"]].append(chosen)
    out = {p["id"]: table[p["id"]] for p in projects if p["id"] in table and table[p["id"]]["records"] == record_ids(by_id[p["id"]])}
    split = []
    for id, readers in read.items():
        votes = Counter(d for chosen in readers for d in chosen)
        kept = [d for d in dict.fromkeys(d for chosen in readers for d in chosen) if votes[d] * 2 > len(readers)]
        if not kept and any(readers):
            split.append(id)
            out.pop(id, None)
            continue
        out[id] = {"id": id, "records": record_ids(by_id[id]), "disciplines": kept}
    return {p["id"]: out[p["id"]] for p in projects if p["id"] in out}, split


def check_brief() -> None:
    """Refuse to run when the brief does not describe exactly DISCIPLINES."""
    described = re.findall(r"^- `([a-z-]+)` \(([^)]+)\)", BRIEF.read_text(), re.MULTILINE)
    if described != [(id, label) for id, label, _ in DISCIPLINES]:
        raise SystemExit(f"{BRIEF} does not list the disciplines as DISCIPLINES does")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batches", type=Path, help="write the pending projects, as the reader is given them, as batch files in this folder")
    ap.add_argument("--size", type=int, default=150, help="projects per batch")
    ap.add_argument("--all", action="store_true", help="with --batches or --merge: every project, filed or not")
    ap.add_argument("--merge", type=Path, nargs="+", help="verdict files to add to the filed projects")
    args = ap.parse_args()

    check_brief()
    # Every project with a card, a skip included: a project whose title gave
    # its card nothing to go on may still say enough to be filed.
    projects = load_projects()
    path = DATA_DIR / NAME
    table = {x["id"]: x for x in map(json.loads, path.open())} if path.exists() else {}

    if args.merge:
        verdicts = [json.loads(line) for f in args.merge for line in f.open() if line.strip()]
        table, split = merge(projects, {} if args.all else table, verdicts)
        path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in table.values()))
        print(f"wrote {len(table)} filed projects to {path}")
        if split:
            print(f"{len(split)} left pending, their readers sharing no discipline: {' '.join(split)}")

    waiting = projects if args.all and not args.merge else pending(projects, table)
    if args.batches:
        args.batches.mkdir(parents=True, exist_ok=True)
        lines = [evidence(p) for p in waiting]
        batches = -(-len(lines) // args.size)
        # Every batch takes projects from all through the list, so each
        # reader meets every source and decade.
        for n in range(batches):
            (args.batches / f"batch_{n + 1:02d}.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines[n::batches]))
        print(f"wrote {len(lines)} projects to {args.batches} in {batches} batches")
        return

    filed = load()
    held = Counter(d for p in projects for d in of(p, filed))
    main_of = Counter(ds[0] for p in projects if (ds := of(p, filed)))
    for id, label, area in DISCIPLINES:
        print(f"{held[id]:5d} {main_of[id]:5d}  {label} ({area})")
    print(f"{sum(not of(p, filed) for p in projects)} of {len(projects)} projects have no discipline, {len(waiting)} of them pending")
    if waiting:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

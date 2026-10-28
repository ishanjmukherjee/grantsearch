"""Name-search test set and report: does searching a person find their projects?

Every person named on a project is a candidate: students (grant awardees and
Expo presenters) and Expo advisors. Seeded random samples of them become
queries, each in the forms people type:

- full: "first last"
- last_first: "last first", as the 2025-2026 Expo guides print names
- nickname: a common short form of the first name ("chris luey"), for people
  whose first name has one in NICKNAMES
- typo: "first last" with one seeded edit to a surname of 5+ letters
- surname: "last" alone

A query's relevant projects are those naming someone who is likely the same
person (as in search.same_person: a shared surname part and first names one of
which is a prefix of the other), or, for a surname query, anyone with that
surname. A surname that is only particles ("Le", "Du") counts whole.
Students and advisors are matched among students and among advisors
respectively.

build writes the test set to data/eval/names.jsonl; run searches each query
and prints, per kind and form, hit@1, hit@5 (a relevant project in the top 1
or 5), MRR over the top 50, and R-precision (the share of the top |relevant|
results that are relevant, which matters when someone has several projects).
--no-pins runs search without putting name matches first, for comparison.

topics checks the other side: how often a topic search wrongly pins someone.
It runs people.People.pins on a seeded TOPIC_SHARE sample of the queries the
cards generated, which are written as searches for topics, and lists those
that pin. Card queries are also part of the text that keeps a one-word query
from pinning, so this mostly tests the rule for queries of several words.

Usage: uv run python -m eval_names build | run [--by surname|abstract] [--no-pins] | topics
"""

import argparse
import json
import random
import re
import unicodedata
from collections import defaultdict

from pipeline.link_expo import first_match, surname_parts, tokens
from pipeline.projects import load_projects
from pipeline.scrape_surg import DATA_DIR

OUT = DATA_DIR / "eval" / "names.jsonl"
SEED = 0
N_STUDENTS = 300
N_NICKNAMES = 100
N_TYPOS = 100
N_ADVISORS = 100
DEPTH = 50  # results fetched per query; a relevant project below this counts as missed
TOPIC_SHARE = 0.2

ADVISOR_SPLIT = re.compile(r"\s*[,;&]\s*(?:and\s+)?|\s+and\s+")
HONORIFICS = {"professor", "prof", "dr"}
AFFILIATION = re.compile(r"\b(?:university|college|laboratory|hospital|institute|school|office|center|lab)\b", re.I)
NICKNAMES = {
    "abigail": "abby", "alexander": "alex", "alexandra": "alex", "alexandria": "alex", "andrew": "andy",
    "anthony": "tony", "benjamin": "ben", "catherine": "cathy", "christina": "chris", "christine": "chris",
    "christopher": "chris", "daniel": "dan", "daniela": "dani", "danielle": "dani", "david": "dave",
    "edward": "ed", "elizabeth": "liz", "emily": "em", "gabriel": "gabe", "gabriella": "gabby",
    "isabel": "izzy", "isabella": "bella", "isabelle": "izzy", "jacob": "jake", "jacqueline": "jackie",
    "james": "jim", "jennifer": "jen", "jessica": "jess", "jonathan": "jon", "joseph": "joe",
    "joshua": "josh", "katherine": "kate", "kathryn": "kate", "kimberly": "kim", "madeline": "maddie",
    "madeleine": "maddie", "madison": "maddie", "margaret": "maggie", "matthew": "matt", "michael": "mike",
    "nathaniel": "nate", "nicholas": "nick", "nicole": "nikki", "olivia": "liv", "patrick": "pat",
    "rebecca": "becca", "richard": "rich", "robert": "rob", "samantha": "sam", "samuel": "sam",
    "sophia": "sophie", "stephanie": "steph", "steven": "steve", "stephen": "steve", "theodore": "theo",
    "thomas": "tom", "timothy": "tim", "victoria": "tori", "william": "will", "zachary": "zach",
}


def fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().casefold().strip()


def advisors(advisor: str | None) -> list[dict]:
    """An Expo advisor string as first/last names, skipping affiliations and
    single-word names."""
    out = []
    for name in ADVISOR_SPLIT.split(re.sub(r"[\[(][^\])]*[\])]", "", advisor or "")):
        t = [w for w in name.split() if w.rstrip(".").casefold() not in HONORIFICS]
        if len(t) >= 2 and not AFFILIATION.search(name):
            out.append({"first": t[0], "last": " ".join(t[1:])})
    return out


def people() -> dict[str, list[tuple[dict, str]]]:
    """Each kind ("student", "advisor") -> (name record, project id) per mention."""
    found = defaultdict(list)
    for p in load_projects():
        for x in p["grant"]["awardees"] if p["grant"] else []:
            found["student"].append((x, p["id"]))
        for e in p["expo"]:
            found["student"] += [(x, p["id"]) for x in e["presenters"]]
            found["advisor"] += [(x, p["id"]) for x in advisors(e["advisor"])]
    return found


def surname(last: str) -> set[str]:
    """Surname parts; the whole surname when it is only particles ("Le", "Du")."""
    return surname_parts(last) or set(tokens(last))


def likely_same(a: dict, b: dict) -> bool:
    """search.same_person, without importing search and its model, and with surname()."""
    return bool(surname(a["last"]) & surname(b["last"])) and first_match(a["first"], b["first"])


def typo(word: str, rng: random.Random) -> str:
    i = rng.randrange(len(word) - 1)
    edit = rng.choice(["delete", "swap", "substitute"])
    if edit == "delete":
        return word[:i] + word[i + 1 :]
    if edit == "swap":
        return word[:i] + word[i + 1] + word[i] + word[i + 2 :]
    return word[:i] + rng.choice([c for c in "abcdefghijklmnopqrstuvwxyz" if c != word[i]]) + word[i + 1 :]


def build() -> None:
    found = people()
    has_abstract = {p["id"] for p in load_projects() if p["expo"]}
    surname_people = defaultdict(set)  # surname part -> distinct full names, students and advisors alike
    for mentions in found.values():
        for x, _ in mentions:
            for part in surname(x["last"]):
                surname_people[part].add((fold(x["first"]), fold(x["last"])))

    rows = []
    for kind, n, seed in (("student", N_STUDENTS, SEED), ("advisor", N_ADVISORS, SEED + 1)):
        mentions = found[kind]
        distinct = sorted({(fold(x["first"]), fold(x["last"])): x for x, _ in mentions}.items())
        rng = random.Random(seed)

        def relevant(x: dict) -> list[str]:
            return sorted({pid for y, pid in mentions if likely_same(x, y)})

        def row(query: str, form: str, x: dict, rel: list[str]) -> dict:
            parts = surname(x["last"])
            shared = max((len(surname_people[s]) for s in parts), default=1)
            return {
                "query": query,
                "relevant": rel,
                "kind": kind,
                "form": form,
                "person": f"{x['first']} {x['last']}",
                "surname_shared_by": shared,
                "abstract": any(pid in has_abstract for pid in rel),
            }

        sample = rng.sample(distinct, n)
        for (first, last), x in sample:
            rel = relevant(x)
            rows.append(row(f"{first} {last}", "full", x, rel))
            if kind == "student":
                rows.append(row(f"{last} {first}", "last_first", x, rel))
            surname_rel = sorted({pid for y, pid in mentions if surname(y["last"]) & surname(x["last"])})
            rows.append(row(last, "surname", x, surname_rel))
        if kind == "student":
            nick = [(k, x) for k, x in distinct if k[0].split()[0] in NICKNAMES]
            for (first, last), x in rng.sample(nick, min(N_NICKNAMES, len(nick))):
                rows.append(row(f"{NICKNAMES[first.split()[0]]} {last}", "nickname", x, relevant(x)))
            long = [(k, x) for k, x in distinct if len(k[1]) >= 5 and " " not in k[1]]
            for (first, last), x in rng.sample(long, N_TYPOS):
                rows.append(row(f"{first} {typo(last, rng)}", "typo", x, relevant(x)))

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"{len(rows)} queries -> {OUT}")


def run(by: str | None, pins: bool) -> None:
    from search import Index

    index = Index()
    if not pins:
        index.people.pins = lambda query: ({}, False)
    rows = [json.loads(line) for line in OUT.open()]
    scores = defaultdict(list)
    for r in rows:
        ranked = [p["id"] for p in index.search(r["query"], n=DEPTH)[0]]
        rel = set(r["relevant"])
        first = next((i for i, pid in enumerate(ranked, 1) if pid in rel), None)
        k = len(rel)
        group = (r["kind"], r["form"])
        if by == "surname":
            group += ("unique surname" if r["surname_shared_by"] == 1 else "shared surname",)
        elif by == "abstract":
            group += ("has abstract" if r["abstract"] else "title only",)
        scores[group].append((first == 1, first is not None and first <= 5, 1 / first if first else 0.0, len(rel & set(ranked[:k])) / k))
        r["rank"] = first

    print(f"{'kind':8} {'form':11} {'group':15} {'n':>4} {'hit@1':>6} {'hit@5':>6} {'MRR':>6} {'R-prec':>6}")
    for group, s in sorted(scores.items()):
        cols = [sum(x[i] for x in s) / len(s) for i in range(4)]
        print(f"{group[0]:8} {group[1]:11} {group[2] if len(group) > 2 else '':15} {len(s):4} " + " ".join(f"{c:6.2f}" for c in cols))
    misses = DATA_DIR / "eval" / "names_ranks.jsonl"
    misses.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"per-query ranks -> {misses}")


def topics() -> None:
    from people import People

    projects = load_projects()
    people = People(projects)
    queries = sorted({q for p in projects if p["card"] for q in p["card"]["queries"]})
    sample = random.Random(SEED + 2).sample(queries, round(TOPIC_SHARE * len(queries)))
    fired = []
    for q in sample:
        pinned, _ = people.pins(q)
        if pinned:
            names = [m for m in people.match(q) if len(m["words"]) >= 2 or len(q.split()) == 1]
            fired.append({"query": q, "pinned": sorted(pinned), "matches": [{"person": " ".join(m["person"]["first"][:1] + [m["person"]["last"]]), "words": m["words"]} for m in names]})
    print(f"{len(fired)} of {len(sample)} topic queries pin someone ({len(fired) / len(sample):.2%}); sampled {TOPIC_SHARE:.0%} of {len(queries)}")
    out = DATA_DIR / "eval" / "topic_pins.jsonl"
    out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in fired))
    print(f"queries that pin -> {out}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("build", "run", "topics"))
    parser.add_argument("--by", choices=("surname", "abstract"), help="also split results by this")
    parser.add_argument("--no-pins", action="store_true", help="run search without putting name matches first")
    args = parser.parse_args()
    if args.command == "build":
        build()
    elif args.command == "run":
        run(args.by, not args.no_pins)
    else:
        topics()


if __name__ == "__main__":
    main()

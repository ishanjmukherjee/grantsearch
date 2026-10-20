"""Pair SURG grants with Expo abstracts by presenter name.

A pair is a candidate when some grant awardee and some Expo presenter share any
surname part and one first name is a prefix of the other (Alex / Alexander).
No year constraint. This is deliberately liberal: name matches include
different students and different projects by the same student, which a later
judging step sorts out. Writes data/expo_candidates.jsonl, one self-contained
pair per line with both sides' full text, as input for that step.
linked_abstracts() reads that step's verdicts back from
data/expo_judgments.jsonl.

A poster presented by several students may be listed once per presenter, and
expo_groups() gathers such listings: same year, and near-identical abstracts or
the same title and advisor. A poster is linked to grants as a whole.

Usage: uv run python -m pipeline.link_expo
"""

import json
import re
import unicodedata
from collections import defaultdict

from pipeline.parse_expo import PARTICLES
from pipeline.scrape_surg import DATA_DIR

MIN_PREFIX = 3  # "Al" should not match every Alexander and Alice
# Word-trigram Jaccard between two abstracts at which they are one poster's.
# Listings of one poster score 0.54 and up; distinct projects stay under 0.3.
MIN_OVERLAP = 0.5


def tokens(name: str) -> list[str]:
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z]+", name.casefold())


def surname_parts(last: str) -> set[str]:
    return {t for t in tokens(last) if t not in PARTICLES and len(t) > 1}


def first_match(a: str, b: str) -> bool:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    x, y = sorted((ta[0], tb[0]), key=len)
    return x == y or (len(x) >= MIN_PREFIX and y.startswith(x))


def words(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z0-9]+", s.casefold())


def trigrams(s: str) -> set[tuple[str, ...]]:
    w = words(s)
    return {tuple(w[i : i + 3]) for i in range(len(w) - 2)}


def expo_groups(abstracts: list[dict]) -> list[list[dict]]:
    """Every Expo listing in exactly one group of listings of the same poster, ordered by id."""
    parent = {e["id"]: e["id"] for e in abstracts}

    def find(x: str) -> str:
        while parent[x] != x:
            x = parent[x] = parent[parent[x]]
        return x

    by_year: dict[int, list[dict]] = defaultdict(list)
    for e in abstracts:
        by_year[e["year"]].append(e)
    for entries in by_year.values():
        grams = [trigrams(e["abstract"]) for e in entries]
        for i, a in enumerate(entries):
            for j in range(i):
                b = entries[j]
                same_listing = a["advisor"] and words(a["title"]) == words(b["title"]) and words(a["advisor"]) == words(b["advisor"] or "")
                union = grams[i] | grams[j]
                if same_listing or (union and len(grams[i] & grams[j]) / len(union) >= MIN_OVERLAP):
                    parent[find(a["id"])] = find(b["id"])

    groups: dict[str, list[dict]] = defaultdict(list)
    for e in sorted(abstracts, key=lambda e: e["id"]):
        groups[find(e["id"])].append(e)
    return list(groups.values())


def linked_abstracts() -> dict[str, list[dict]]:
    """Expo listings of posters judged the same project as a grant with high confidence, by grant id.

    A poster joins, whole, every grant that any of its listings was linked to,
    including listings the judging step did not pair with that grant.
    """
    abstracts = json.loads((DATA_DIR / "expo_abstracts.json").read_text())
    group_of = {e["id"]: g for g in expo_groups(abstracts) for e in g}
    linked: dict[str, dict[str, dict]] = defaultdict(dict)
    for line in (DATA_DIR / "expo_judgments.jsonl").open():
        j = json.loads(line)
        if j["verdict"] == "same" and j["confidence"] == "high":
            grant_id, expo_id = j["pair_id"].split("|")
            for e in group_of[expo_id]:
                linked[grant_id][e["id"]] = e
    return {g: [entries[k] for k in sorted(entries)] for g, entries in linked.items()}


def unlinked_groups(linked: dict[str, list[dict]]) -> list[list[dict]]:
    """The Expo posters not linked to any grant, as listing groups (see expo_groups)."""
    abstracts = json.loads((DATA_DIR / "expo_abstracts.json").read_text())
    taken = {e["id"] for entries in linked.values() for e in entries}
    groups = ([e for e in g if e["id"] not in taken] for g in expo_groups(abstracts))
    return [g for g in groups if g]


def main() -> None:
    grants = json.loads((DATA_DIR / "grants.json").read_text())
    abstracts = json.loads((DATA_DIR / "expo_abstracts.json").read_text())

    by_surname: dict[str, list[tuple[dict, dict]]] = defaultdict(list)
    for g in grants:
        for a in g["awardees"]:
            for part in surname_parts(a["last"]):
                by_surname[part].append((g, a))

    pairs: dict[tuple[str, str], dict] = {}
    for e in abstracts:
        for p in e["presenters"]:
            for part in surname_parts(p["last"]):
                for g, a in by_surname.get(part, []):
                    if not first_match(a["first"], p["first"]):
                        continue
                    pair = pairs.setdefault(
                        (g["id"], e["id"]),
                        {
                            "pair_id": f"{g['id']}|{e['id']}",
                            "matched_names": [],
                            "expo_minus_grant_years": e["year"] - g["year"],
                            "grant": {k: g[k] for k in ("id", "year", "title", "awardees")},
                            "expo": {k: e[k] for k in ("id", "year", "title", "presenters", "advisor", "abstract")},
                        },
                    )
                    name = f"{a['first']} {a['last']} = {p['first']} {p['last']}"
                    if name not in pair["matched_names"]:
                        pair["matched_names"].append(name)

    out = sorted(pairs.values(), key=lambda c: c["pair_id"])
    path = DATA_DIR / "expo_candidates.jsonl"
    path.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in out))
    print(f"{len(out)} candidate pairs -> {path}")


if __name__ == "__main__":
    main()

"""Pair SURG grants with Expo abstracts by presenter name.

A pair is a candidate when some grant awardee and some Expo presenter share any
surname part and one first name is a prefix of the other (Alex / Alexander).
No year constraint. This is deliberately liberal: name matches include
different students and different projects by the same student, which a later
judging step sorts out. Writes data/expo_candidates.jsonl, one self-contained
pair per line with both sides' full text, as input for that step.
linked_abstracts() reads that step's verdicts back from
data/expo_judgments.jsonl.

Usage: uv run python -m pipeline.link_expo
"""

import json
import re
import unicodedata
from collections import defaultdict

from pipeline.parse_expo import PARTICLES
from pipeline.scrape_surg import DATA_DIR

MIN_PREFIX = 3  # "Al" should not match every Alexander and Alice


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


def linked_abstracts() -> dict[str, list[dict]]:
    """Expo entries judged the same project as a grant with high confidence, by grant id."""
    abstracts = {e["id"]: e for e in json.loads((DATA_DIR / "expo_abstracts.json").read_text())}
    linked: dict[str, list[dict]] = {}
    for line in (DATA_DIR / "expo_judgments.jsonl").open():
        j = json.loads(line)
        if j["verdict"] == "same" and j["confidence"] == "high":
            grant_id, expo_id = j["pair_id"].split("|")
            linked.setdefault(grant_id, []).append(abstracts[expo_id])
    return linked


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

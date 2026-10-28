"""Give every grant and Expo listing a permanent 8-digit share number.

A project's page is /p/NUMBER, where NUMBER is its grant's or, for a poster
without a grant, its first listing's. Links to any listing of a project lead
to it, so a link survives a poster being linked to a grant later.

The ids grants and listings carry ("surg-2023-014") count up through each
year's page or program, so a re-scrape that adds or drops an entry shifts the
rest. Numbers are therefore kept in data/share_ids.jsonl, one {number, id,
key} row per entry ever numbered, where key is the entry's source, year,
normalized title and, for a listing, presenters. An entry keeps the number
of the row with its key, wherever its id has moved; failing that, of the row
with its id, if that row's key is otherwise unclaimed and its title nearly
the same (a corrected title). Otherwise it gets a new random number. Rows are
never removed or renumbered, so an old link either finds its entry or none.

Usage: uv run python -m pipeline.share_ids
"""

import json
import secrets

from pipeline.link_expo import trigrams, words
from pipeline.scrape_surg import DATA_DIR

SHARE_IDS = DATA_DIR / "share_ids.jsonl"
LOW, HIGH = 10_000_000, 99_999_999
# Title word-trigram Jaccard at which a changed title is the same entry's.
MIN_TITLE_SIM = 0.5


def entries() -> list[dict]:
    grants = json.loads((DATA_DIR / "grants.json").read_text())
    abstracts = json.loads((DATA_DIR / "expo_abstracts.json").read_text())
    return grants + abstracts


def key(e: dict) -> str:
    title = " ".join(words(e["title"]))
    if e["id"].startswith("surg-"):
        return f"surg|{e['year']}|{title}"
    presenters = sorted(" ".join(words(f"{p['first']} {p['last']}")) for p in e["presenters"])
    return f"expo|{e['year']}|{title}|{'; '.join(presenters)}"


def load_rows() -> list[dict]:
    return [json.loads(line) for line in SHARE_IDS.open()] if SHARE_IDS.exists() else []


def title_sim(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    return len(ta & tb) / len(ta | tb) if ta | tb else float(words(a) == words(b))


def main() -> None:
    rows = load_rows()
    by_key = {r["key"]: r for r in rows}
    by_id = {r["id"]: r for r in rows}
    current = entries()
    keys = {key(e) for e in current}

    claimed, kept, moved, renamed, new = set(), [], 0, 0, 0
    for e in current:
        k = key(e)
        row = by_key.get(k)
        if row is None and (old := by_id.get(e["id"])) and old["key"] not in keys and old["number"] not in claimed:
            if title_sim(old["key"].split("|")[2], e["title"]) >= MIN_TITLE_SIM:
                row = old
                renamed += 1
        if row is None:
            taken = {r["number"] for r in rows}
            number = next(n for n in iter(lambda: LOW + secrets.randbelow(HIGH - LOW + 1), None) if n not in taken)
            row = {"number": number}
            rows.append(row)
            new += 1
        elif row["id"] != e["id"] and row["key"] == k:
            moved += 1
        row.update(id=e["id"], key=k)
        claimed.add(row["number"])
        kept.append(row)

    # Rows whose entry is gone stay, so their numbers are never handed out again.
    orphans = [r for r in rows if r["number"] not in claimed]
    with SHARE_IDS.open("w") as f:
        for r in kept + orphans:
            f.write(json.dumps({"number": r["number"], "id": r["id"], "key": r["key"]}, ensure_ascii=False) + "\n")
    print(f"{len(kept)} entries: {new} new, {moved} moved, {renamed} retitled; {len(orphans)} numbers without an entry")


if __name__ == "__main__":
    main()

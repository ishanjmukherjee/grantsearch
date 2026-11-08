"""Give every record, and every listing of a poster, a permanent 8-digit share number.

A project's page is /p/NUMBER, where NUMBER is any of its records' or
listings'. Links to any of them lead to the project, so a link survives a
record being linked to another later.

The ids records and listings carry ("surg-2023-014") count up through each
year's page or program, so a re-scrape that adds or drops an entry shifts the
rest. Numbers are therefore kept in data/share_ids.jsonl, one {number, id,
key} row per entry ever numbered, where key is the entry's source, year,
normalized title and, but for a SURG grant, its students; the source is a
thesis's department, as a thesis can be on two departments' lists. A 2003 Symposium
listing, which has no title, is keyed by its project number instead. An entry
keeps the number of the row with its key, wherever its id has moved; failing
that, of the row with its id, if that row's key is otherwise unclaimed and
its title nearly the same or, but for a SURG grant, its students the same (a
corrected title). Otherwise it gets a new random
number. Rows are never removed or renumbered, so an old link either finds
its entry or none.

Usage: uv run python -m pipeline.share_ids
"""

import json
import re
import secrets

from pipeline import records
from pipeline.records import DATA_DIR, trigrams, words

SHARE_IDS = DATA_DIR / "share_ids.jsonl"
LOW, HIGH = 10_000_000, 99_999_999
# Title word-trigram Jaccard at which a changed title is the same entry's.
MIN_TITLE_SIM = 0.5


def entries() -> list[dict]:
    """Every record, or for a poster listed more than once every listing, as
    {id, source, year, title, students, project}."""
    out = []
    for r in records.load():
        project = r.get("extra", {}).get("project")
        if "listings" in r:
            out += [{"id": e["id"], "source": r["source"], "year": r["year"], "title": e["title"], "students": e["presenters"], "project": e.get("project")} for e in r["listings"]]
        else:
            students = [p for p in r["people"] if p["role"] == "student"]
            out.append({"id": r["id"], "source": r["source"], "year": r["year"], "title": r["title"], "students": students, "project": project})
    return out


def key(e: dict) -> str:
    title = " ".join(words(e["title"])) if e["title"] else f"project {e['project']}"
    if e["source"] == "surg":
        return f"surg|{e['year']}|{title}"
    students = sorted(" ".join(words(f"{p['first']} {p['last']}")) for p in e["students"])
    # The id's prefix, not the source: a thesis can be on two departments' lists.
    prefix = re.split(r"[-:]", e["id"])[0]
    return f"{prefix}|{e['year']}|{title}|{'; '.join(students)}"


def keys(current: list[dict]) -> list[str]:
    """Each entry's key, with "|2", "|3", ... after it for the second and later
    entries (in id order) with one key, such as one student's two listings of
    one title."""
    seen: dict[str, int] = {}
    out = []
    for e in current:
        k = key(e)
        seen[k] = seen.get(k, 0) + 1
        out.append(k if seen[k] == 1 else f"{k}|{seen[k]}")
    return out


def load_rows() -> list[dict]:
    return [json.loads(line) for line in SHARE_IDS.open()] if SHARE_IDS.exists() else []


def title_sim(a: str, b: str) -> float:
    ta, tb = trigrams(a), trigrams(b)
    return len(ta & tb) / len(ta | tb) if ta | tb else float(words(a) == words(b))


def main() -> None:
    rows = load_rows()
    by_key = {r["key"]: r for r in rows}
    by_id = {r["id"]: r for r in rows}
    current = sorted(entries(), key=lambda e: e["id"])
    current_keys = keys(current)
    taken_keys = set(current_keys)

    claimed, kept, moved, renamed, new = set(), [], 0, 0, 0
    for e, k in zip(current, current_keys):
        row = by_key.get(k)
        if row is None and (old := by_id.get(e["id"])) and old["key"] not in taken_keys and old["number"] not in claimed:
            # Its old row, if the title is nearly the same or the students are.
            same_students = e["source"] != "surg" and old["key"].split("|")[3:4] == k.split("|")[3:4]
            if same_students or (e["title"] and title_sim(old["key"].split("|")[2], e["title"]) >= MIN_TITLE_SIM):
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

"""The searchable projects, assembled from grants, Expo abstracts and cards.

Projects come in three disjoint sets: SURG grants with only a title, SURG
grants linked to Expo abstracts judged the same project with high confidence,
and Expo projects not linked to a grant. Each project is a dict:

- id, title: the grant's, or the Expo entry's when there is no grant
- grant: the grants.json record, or None
- expo: the linked or own expo_abstracts.json records (may be empty)
- card: the search card for the project, or None when the title-only card is a
  refusal
- body: the text the document vector is built from besides the card: the
  gloss for title-only grants, the abstracts (joined) otherwise; None with no
  card
"""

import json

from pipeline.link_expo import linked_abstracts
from pipeline.scrape_surg import DATA_DIR

INDEX_DIR = DATA_DIR / "index"
# The index is embedded with INDEX_MODEL; user queries with QUERY_MODEL, which
# shares its embedding space and is small enough to run on the server's CPU.
INDEX_MODEL = "voyage-4-large"
QUERY_MODEL = "voyageai/voyage-4-nano"
QUERY_MODEL_REVISION = "433ece5e27a1611e9360dd7134ecaaf79fb3681d"  # pinned: the model ships its own code
DIM = 2048


def load_jsonl(name: str) -> dict[str, dict]:
    return {c["id"]: c for c in map(json.loads, (DATA_DIR / name).open())}


def load_projects() -> list[dict]:
    grants = json.loads((DATA_DIR / "grants.json").read_text())
    expo = json.loads((DATA_DIR / "expo_abstracts.json").read_text())
    cards, abstract_cards, expo_cards = map(load_jsonl, ("cards.jsonl", "cards_abstract.jsonl", "cards_expo.jsonl"))
    linked = linked_abstracts()
    taken = {e["id"] for entries in linked.values() for e in entries}

    projects = []
    for g in grants:
        entries = linked.get(g["id"], [])
        if entries:
            card, body = abstract_cards[g["id"]], "\n\n".join(e["abstract"] for e in entries)
        elif cards[g["id"]]["status"] == "card":
            card, body = cards[g["id"]], cards[g["id"]]["gloss"]
        else:
            card, body = None, None
        projects.append({"id": g["id"], "title": g["title"], "grant": g, "expo": entries, "card": card, "body": body})
    for e in expo:
        if e["id"] not in taken:
            projects.append({"id": e["id"], "title": e["title"], "grant": None, "expo": [e], "card": expo_cards[e["id"]], "body": e["abstract"]})
    return projects


def doc_text(p: dict) -> str:
    """The text of a project's document vector: title + body + fields + concepts + acronym expansions."""
    card = p["card"]
    parts = [card["title"], p["body"]]
    if card["fields"]:
        parts.append("Fields: " + "; ".join(card["fields"]))
    if card["concepts"]:
        parts.append("Concepts: " + "; ".join(card["concepts"]))
    if card["acronyms"]:
        parts.append("; ".join(f"{k}: {v}" for k, v in card["acronyms"].items()))
    return "\n".join(parts)

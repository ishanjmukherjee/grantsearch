"""The searchable projects, assembled from grants, Expo abstracts and cards.

Projects come in three disjoint sets: SURG grants with only a title, SURG
grants linked to Expo abstracts judged the same project with high confidence,
and Expo posters not linked to a grant. A poster may have several listings,
one per presenter (see pipeline.link_expo.expo_groups). Each project is a dict:

- id, title: the grant's, or the poster's first listing's when there is no grant
- grant: the grants.json record, or None
- expo: the linked or own expo_abstracts.json records (may be empty), with
  formatting-only variants of an abstract folded into one (see fold)
- card: the search card for the project, or None when the title-only card is a
  refusal
- body: the text the document vector is built from besides the card: the
  gloss for title-only grants, the distinct abstracts (joined) otherwise;
  None with no card
- gloss: for projects with abstracts, a short topic-level description generated
  from them (data/glosses.jsonl); None otherwise. Title-only grants already
  have one as their body.
"""

import json

from pipeline.link_expo import linked_abstracts, unlinked_groups, words
from pipeline.scrape_surg import DATA_DIR

INDEX_DIR = DATA_DIR / "index"
# The index is embedded with INDEX_MODEL; user queries with QUERY_MODEL, which
# shares its embedding space and is small enough to run on the server's CPU.
INDEX_MODEL = "voyage-4-large"
QUERY_MODEL = "voyageai/voyage-4-nano"
QUERY_MODEL_REVISION = "433ece5e27a1611e9360dd7134ecaaf79fb3681d"  # pinned: the model ships its own code
DIM = 2048
# Hand edits to generated cards and glosses, kept apart from the generated
# files so regenerating those (make_cards --fresh) cannot erase them. Each line
# is {file, id, patch, reason}, the patch an RFC 7396 JSON merge patch.
OVERRIDES = "card_overrides.jsonl"


def merge_patch(target, patch):
    """RFC 7396: patch's keys replace target's, recursively; null deletes a key."""
    if not isinstance(patch, dict):
        return patch
    merged = dict(target) if isinstance(target, dict) else {}
    for k, v in patch.items():
        if v is None:
            merged.pop(k, None)
        else:
            merged[k] = merge_patch(merged.get(k), v)
    return merged


def load_jsonl(name: str) -> dict[str, dict]:
    """A generated file's records by id, with their overrides applied."""
    records = {c["id"]: c for c in map(json.loads, (DATA_DIR / name).open())}
    for o in map(json.loads, (DATA_DIR / OVERRIDES).open()):
        if o["file"] == name:
            records[o["id"]] = merge_patch(records[o["id"]], o["patch"])
    return records


def fold(entries: list[dict]) -> list[dict]:
    """The entries, with abstracts differing from an earlier one's only in
    formatting (spacing, punctuation, word order) replaced by that one's text.
    A poster's listings often carry one abstract extracted slightly differently."""
    first: dict[tuple[str, ...], str] = {}
    return [{**e, "abstract": first.setdefault(tuple(sorted(words(e["abstract"]))), e["abstract"])} for e in entries]


def abstracts(entries: list[dict]) -> str:
    """The entries' distinct abstracts, joined; a poster's listings often repeat one."""
    return "\n\n".join(dict.fromkeys(e["abstract"] for e in entries))


def load_projects() -> list[dict]:
    grants = json.loads((DATA_DIR / "grants.json").read_text())
    cards, abstract_cards, expo_cards, glosses = map(load_jsonl, ("cards.jsonl", "cards_abstract.jsonl", "cards_expo.jsonl", "glosses.jsonl"))
    linked = linked_abstracts()

    projects = []
    for g in grants:
        entries = fold(linked.get(g["id"], []))
        if entries:
            card, body = abstract_cards[g["id"]], abstracts(entries)
        elif cards[g["id"]]["status"] == "card":
            card, body = cards[g["id"]], cards[g["id"]]["gloss"]
        else:
            card, body = None, None
        gloss = glosses[g["id"]]["gloss"] if entries else None
        projects.append({"id": g["id"], "title": g["title"], "grant": g, "expo": entries, "card": card, "body": body, "gloss": gloss})
    for group in map(fold, unlinked_groups(linked)):
        first = group[0]
        projects.append({"id": first["id"], "title": first["title"], "grant": None, "expo": group, "card": expo_cards[first["id"]], "body": abstracts(group), "gloss": glosses[first["id"]]["gloss"]})
    return projects


def doc_text(p: dict) -> str:
    """The text of a project's document vector: title + body + fields + concepts + acronym expansions."""
    return card_text(p, p["body"])


def summary_text(p: dict) -> str | None:
    """The text of a project's summary vector, built like a title-only grant's
    document vector with the gloss as its body; None for projects without one.

    A full abstract is mostly specifics, which pull its vector away from broad,
    topic-level queries; the summary vector lets those queries find it."""
    return p["gloss"] and card_text(p, p["gloss"])


def card_text(p: dict, body: str) -> str:
    card = p["card"]
    parts = [card["title"], body]
    if card["fields"]:
        parts.append("Fields: " + "; ".join(card["fields"]))
    if card["concepts"]:
        parts.append("Concepts: " + "; ".join(card["concepts"]))
    if card["acronyms"]:
        parts.append("; ".join(f"{k}: {v}" for k, v in card["acronyms"].items()))
    return "\n".join(parts)

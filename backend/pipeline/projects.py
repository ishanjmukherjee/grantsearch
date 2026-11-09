"""Projects: the records that links judge one piece of work, with their cards.

A project is a connected group of records (see pipeline.records) under the
links in data/links.jsonl whose relation is "same" with high confidence; a
record no such link touches is a project alone. Projects are computed on
loading and never stored. Only projects with at least one generated card
(a SURG card's skip counts) are loaded: the rest have not been carded yet
and are not searchable.

Generated files keep their cards by the id of the record each was written
for, with data/overrides.jsonl applied on loading (see load_jsonl):

- generated/surg_cards.jsonl: every SURG grant's card, or a skip where
  nothing points to what the project is, written by reading the grant's
  record and its linked posters (prompts/surg_card.md). A card's gloss
  stands in for the abstract a grant without posters does not have.
- generated/poster_cards.jsonl: the card of every Expo or Symposium poster
  that no carded grant presents, written by reading the poster's record
  (prompts/poster_card.md). A poster whose program prints no title has a
  made_title, a plain description written from its abstract.

Each project is a dict:

- id: its head record's. The head is its first SURG grant by id or, without
  one, its first record by id.
- title: the head's title or, if the head prints none, the first of its
  other records' or listings' that does; None when none does.
- made_title: when title is None, its poster card's made_title, which the
  site shows as "Untitled Project: <made_title>"; otherwise None.
- records: its records, SURG grants first, each source's by id
- entries: its posters' listings, by id (see entries), their abstracts
  folded (see fold)
- cards: the cards that stand for it in the index, each {owner, card, body,
  gloss}. These are its grants' SURG cards that are not skips, and the poster
  cards of its posters that no such grant presents. body is the text the
  card's document vector is built from besides the card: the distinct
  abstracts its owner's card was written from (a grant's linked posters', a
  poster card's poster's), or, for a grant without posters, its card's gloss.
  gloss is the text for the summary vector: the card's gloss when its body
  is abstracts, otherwise None.

Index rows are keyed by the card's owner (see rows).
"""

import json

from pipeline.records import (
    DATA_DIR,
    SOURCES,
    advisors,
    fold_abstracts,
    load,
    merge_patch,
    similar,
    trigrams,
    words,
)

INDEX_DIR = DATA_DIR / "index"
# The index is embedded with INDEX_MODEL; user queries with QUERY_MODEL, which
# shares its embedding space and is small enough to run on the server's CPU.
INDEX_MODEL = "voyage-4-large"
QUERY_MODEL = "voyageai/voyage-4-nano"
QUERY_MODEL_REVISION = "433ece5e27a1611e9360dd7134ecaaf79fb3681d"  # pinned: the model ships its own code
DIM = 2048
GENERATED = "generated"
LINKS = DATA_DIR / "links.jsonl"
# Hand edits to generated files, kept apart from them so regenerating those
# cannot erase them. Each line is {file, id, patch, reason}: the file it
# patches (relative to data/), the record's id, an RFC 7396 JSON merge patch
# and why. load_jsonl applies the edits to generated files; pipeline.records
# applies those to records.
OVERRIDES = DATA_DIR / "overrides.jsonl"


def load_jsonl(name: str) -> dict[str, dict]:
    """A generated file's records by id, with their overrides applied."""
    records = {c["id"]: c for c in map(json.loads, (DATA_DIR / name).open())}
    for o in map(json.loads, OVERRIDES.open()):
        if o["file"] == name:
            records[o["id"]] = merge_patch(records[o["id"]], o["patch"])
    return records


def same_links() -> list[tuple[str, str]]:
    return [(link["a"], link["b"]) for link in map(json.loads, LINKS.open()) if link["relation"] == "same" and link["confidence"] == "high"]


def components(ids: list[str], links: list[tuple[str, str]]) -> list[list[str]]:
    """The ids in connected groups under the links, each group in id order."""
    parent = {i: i for i in ids}

    def find(x: str) -> str:
        while parent[x] != x:
            x = parent[x] = parent[parent[x]]
        return x

    for a, b in links:
        parent[find(a)] = find(b)
    groups: dict[str, list[str]] = {}
    for i in sorted(ids):
        groups.setdefault(find(i), []).append(i)
    return list(groups.values())


def unrole(person: dict) -> dict:
    return {k: v for k, v in person.items() if k != "role"}


def entries(records: list[dict]) -> list[dict]:
    """The listings of the posters among records, by id: a poster listed once
    per presenter has several. Each is {id, record, source, year, title,
    presenters, advisors, abstract, url, page, abstract_source}, presenters
    and advisors as {first, last, ...}."""
    out = []
    for r in records:
        if r["kind"] != "presentation":
            continue
        common = {"record": r["id"], "source": r["source"], "year": r["year"], "url": r["url"]}
        if "listings" in r:
            for e in r["listings"]:
                out.append({"id": e["id"], **common, "title": e["title"], "presenters": e["presenters"], "advisors": [unrole(a) for a in advisors(e["advisor"])], "abstract": e["abstract"], "page": e["page"], "abstract_source": e.get("abstract_source")})
        else:
            students = [unrole(p) for p in r["people"] if p["role"] == "student"]
            advisor_people = [unrole(p) for p in r["people"] if p["role"] == "advisor"]
            out.append({"id": r["id"], **common, "title": r["title"], "presenters": students, "advisors": advisor_people, "abstract": r["abstract"], "page": r["page"], "abstract_source": r.get("extra", {}).get("abstract_source")})
    return sorted(out, key=lambda e: e["id"])


def fold(listings: list[dict]) -> list[dict]:
    """The listings, with an abstract that differs from an earlier one's only in
    formatting (spacing, punctuation, word order), or that is a lightly edited
    version of an earlier listing's of the same poster (see records.similar),
    replaced by that one's text, so that it reads, and is shown, as the same
    abstract. A poster listed once per presenter can print a revised abstract
    under one of them."""
    first: dict[tuple[str, ...], str] = {}
    shown: list[tuple[str, set[tuple[str, ...]], str]] = []  # (record, trigrams, abstract)
    out = []
    for e in listings:
        text = first.setdefault(tuple(sorted(words(e["abstract"]))), e["abstract"])
        grams = trigrams(text)
        earlier = next((t for record, g, t in shown if record == e["record"] and similar(g, grams)), None)
        if earlier is None:
            shown.append((e["record"], grams, text))
        out.append({**e, "abstract": earlier or text})
    return out


def load_projects() -> list[dict]:
    """Every carded project, those headed by a grant first, each in head id order."""
    records = {r["id"]: r for r in load()}
    surg_cards, poster_cards = (load_jsonl(f"{GENERATED}/{name}.jsonl") for name in ("surg_cards", "poster_cards"))
    links = same_links()
    # A grant may be linked to two listings of one poster: one link each.
    linked: dict[str, set[str]] = {}
    for a, b in links:
        linked.setdefault(a, set()).add(b)
        linked.setdefault(b, set()).add(a)

    def order(r: dict) -> tuple:
        return (SOURCES.index(r["source"]), r["id"])

    projects = []
    for group in components(list(records), links):
        rs = sorted((records[i] for i in group), key=order)
        if not any(r["id"] in surg_cards or r["id"] in poster_cards for r in rs):
            continue
        cards = []
        # Posters a carded grant presents: that grant's card was written from them.
        presented = set()
        for r in rs:
            if (c := surg_cards.get(r["id"])) and c["status"] == "card":
                posters = [records[i] for i in sorted(linked.get(r["id"], ())) if records[i]["kind"] == "presentation"]
                presented |= {p["id"] for p in posters}
                body = fold_abstracts([e["abstract"] for e in entries(posters)]) if posters else None
                cards.append({"owner": r["id"], "card": c, "body": body or c["gloss"], "gloss": c["gloss"] if body else None})
        for r in rs:
            if (c := poster_cards.get(r["id"])) and r["id"] not in presented:
                body = fold_abstracts([e["abstract"] for e in entries([r])])
                cards.append({"owner": r["id"], "card": c, "body": body, "gloss": c["gloss"]})
        head = next((r for r in rs if r["kind"] == "grant"), rs[0])
        listed = fold(entries(rs))
        title = next((t for t in [head["title"], *(r["title"] for r in rs), *(e["title"] for e in listed)] if t), None)
        made_title = None if title else next((c["card"]["made_title"] for c in cards if c["card"].get("made_title")), None)
        projects.append({"id": head["id"], "title": title, "made_title": made_title, "records": rs, "entries": listed, "cards": cards})
    return sorted(projects, key=lambda p: order(records[p["id"]]))


def card_text(card: dict, body: str) -> str:
    """A card's title (its record's, or the made title of a poster that prints
    none), then body, fields, concepts and acronym expansions."""
    parts = [x for x in (card.get("title") or card.get("made_title"), body) if x]
    if card["fields"]:
        parts.append("Fields: " + "; ".join(card["fields"]))
    if card["concepts"]:
        parts.append("Concepts: " + "; ".join(card["concepts"]))
    if card["acronyms"]:
        parts.append("; ".join(f"{k}: {v}" for k, v in card["acronyms"].items()))
    return "\n".join(parts)


def rows(p: dict) -> list[tuple[str, str, str]]:
    """A project's index rows, (owner, kind, text) for each of its cards: a
    document row from the card and its body, a summary row built the same way
    with the gloss as body when there is one, and a row per generated query.

    A full abstract is mostly specifics, which pull its vector away from
    broad, topic-level queries; the summary row lets those queries find it."""
    out = []
    for c in p["cards"]:
        out.append((c["owner"], "doc", card_text(c["card"], c["body"])))
        if c["gloss"]:
            out.append((c["owner"], "summary", card_text(c["card"], c["gloss"])))
        out += [(c["owner"], "query", q) for q in c["card"]["queries"]]
    return out

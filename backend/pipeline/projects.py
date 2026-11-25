"""Projects: the records that links judge one piece of work, with their cards.

A project is a connected group of records (see pipeline.records) under the
links in data/links.jsonl whose relation is "same" with high confidence; a
record no such link touches is a project alone. Projects are computed on
loading and never stored. Only projects with at least one generated card
(a SURG, thesis, NURJ or Leopold card's skip counts) are loaded: the rest have not been carded yet
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
- generated/thesis_cards.jsonl: one card, or a skip, per thesis: all the
  thesis listings of one project (a thesis two departments list, or the
  MMSS library catalogues twice, is one thesis), kept under the first
  listing's id. Written by reading the listings, the thesis's paper where
  one is on file, and the project's other records (prompts/thesis_card.md).
- generated/nurj_cards.jsonl: one card, or a skip, per NURJ paper, written by
  reading every version NURJ published of it in full and the project's other
  records (prompts/nurj_card.md).
- generated/leopold_cards.jsonl: one card, or a skip, per faculty project
  with Leopold fellowships: all the fellowships of one project, over the
  years, kept under the first one's id. Written by reading every year's
  entry and the descriptions the faculty gave of the project
  (prompts/leopold_card.md).

Each project is a dict:

- id: its head record's. The head is its first SURG grant by id or, without
  one, its first record by id.
- title: the head's title or, if the head prints none, the first of its
  other records' or listings' that does; None when none does. A project of
  fellowships alone has its latest title instead (see fellowship_title).
- made_title: when title is None, its poster card's made_title, which the
  site shows as "Untitled Project: <made_title>"; otherwise None.
- records: its records, SURG grants first, each source's by id
- entries: its posters' listings, by id (see entries), their abstracts
  folded (see fold)
- cards: the cards that stand for it in the index, each {owner, card, body,
  gloss}. These are its grants' SURG cards that are not skips, and the poster
  cards of its posters that no such grant presents, and its thesis card that
  is not a skip, and its NURJ papers' cards that are not skips, and its
  fellowships' card that is not a skip. body is the text the card's document vector is built from
  besides the card: the distinct abstracts its owner's card was written from
  (a grant's linked posters', a poster card's poster's, a thesis card's
  listings', a NURJ card's paper's, a fellowship card's faculty
  descriptions), or, for a grant without posters or a thesis, paper or
  fellowship project without one, its card's gloss.
  gloss is the text for the summary vector: the card's gloss when its body
  is abstracts, otherwise None.

Index rows are keyed by the card's owner (see rows).
"""

import json
from collections import Counter

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
            parent[x] = parent[parent[x]]
            x = parent[x]
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
    presenters, advisors, abstract, url, page, abstract_source, forager_id},
    presenters and advisors as {first, last, ...}, and forager_id the
    ForagerOne poster's id, or None."""
    out = []
    for r in records:
        if r["kind"] != "presentation":
            continue
        common = {"record": r["id"], "source": r["source"], "year": r["year"], "url": r["url"]}
        if "listings" in r:
            for e in r["listings"]:
                out.append({"id": e["id"], **common, "title": e["title"], "presenters": e["presenters"], "advisors": [unrole(a) for a in advisors(e["advisor"])], "abstract": e["abstract"], "page": e["page"], "abstract_source": e.get("abstract_source"), "forager_id": e.get("forager_id")})
        else:
            students = [unrole(p) for p in r["people"] if p["role"] == "student"]
            advisor_people = [unrole(p) for p in r["people"] if p["role"] == "advisor"]
            out.append({"id": r["id"], **common, "title": r["title"], "presenters": students, "advisors": advisor_people, "abstract": r["abstract"], "page": r["page"], "abstract_source": r.get("extra", {}).get("abstract_source"), "forager_id": r.get("extra", {}).get("forager_id")})
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


def fellowship_title(fellowships: list[dict]) -> str | None:
    """The title of a project of fellowships: that of its latest year to
    print one, since a faculty project is retitled as it grows ("States of
    Exclusion" became "Absolution and Arms"). Of several that year, the one
    most of the project's fellowships print, then the first by id. A project
    no year gives a title has the latest description its entries give
    instead ("working with Professor Frommer on Czechs and Czechoslovakia in
    the German narrative of suffering"), its first letter a capital; None
    when no entry names a project."""
    titled = [r for r in fellowships if r["title"]]
    if not titled:
        described = [r["extra"]["description"] for r in sorted(fellowships, key=lambda r: (-r["year"], r["id"])) if r["extra"].get("description")]
        return described[0][0].upper() + described[0][1:] if described else None
    count = Counter(r["title"] for r in titled)
    latest = [r for r in titled if r["year"] == max(x["year"] for x in titled)]
    return min(latest, key=lambda r: (-count[r["title"]], r["id"]))["title"]


def load_projects() -> list[dict]:
    """Every carded project, those headed by a grant first, each in head id order."""
    records = {r["id"]: r for r in load()}
    surg_cards, poster_cards, thesis_cards, nurj_cards, leopold_cards = (load_jsonl(f"{GENERATED}/{name}.jsonl") for name in ("surg_cards", "poster_cards", "thesis_cards", "nurj_cards", "leopold_cards"))
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
        if not any(r["id"] in generated for r in rs for generated in (surg_cards, poster_cards, thesis_cards, nurj_cards, leopold_cards)):
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
        theses = [r for r in rs if r["kind"] == "thesis"]
        if theses and (c := thesis_cards.get(theses[0]["id"])) and c["status"] == "card":
            body = fold_abstracts([r["abstract"] for r in theses if r["abstract"]])
            cards.append({"owner": theses[0]["id"], "card": c, "body": body or c["gloss"], "gloss": c["gloss"] if body else None})
        for r in rs:
            if r["source"] == "nurj" and (c := nurj_cards.get(r["id"])) and c["status"] == "card":
                cards.append({"owner": r["id"], "card": c, "body": r["abstract"] or c["gloss"], "gloss": c["gloss"] if r["abstract"] else None})
        fellowships = [r for r in rs if r["kind"] == "fellowship"]
        if fellowships and (c := leopold_cards.get(fellowships[0]["id"])) and c["status"] == "card":
            body = fold_abstracts([r["abstract"] for r in fellowships])
            cards.append({"owner": fellowships[0]["id"], "card": c, "body": body or c["gloss"], "gloss": c["gloss"] if body else None})
        head = next((r for r in rs if r["kind"] == "grant"), rs[0])
        listed = fold(entries(rs))
        if head["kind"] == "fellowship":
            title = fellowship_title(fellowships)
        else:
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

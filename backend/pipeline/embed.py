"""Embed projects for dense retrieval with Qwen3-Embedding-4B.

Projects come in three disjoint sets: SURG grants with only a title, SURG
grants linked to Expo abstracts judged the same project with high confidence,
and Expo projects not linked to a grant. Each gets one document vector and one
vector per generated query on its card:

- Document: title + body + fields + concepts + acronym expansions, where the
  body is the gloss for title-only grants and the abstract (joined, if several)
  otherwise.
- Query: embedded with the same instruction as user queries, since they stand
  in for them.

Title-only grants whose card is a refusal get no vectors; they are found by
BM25 alone. Writes L2-normalized vectors to data/index/vectors.npy and, row
for row, {id, kind, text} to data/index/vectors.jsonl.

Usage: uv run python -m pipeline.embed
"""

import json

import numpy as np
from sentence_transformers import SentenceTransformer

from pipeline.link_expo import linked_abstracts
from pipeline.scrape_surg import DATA_DIR

MODEL = "Qwen/Qwen3-Embedding-4B"
QUERY_PROMPT = "Instruct: Given a search query, retrieve undergraduate research projects that match it\nQuery: "
INDEX_DIR = DATA_DIR / "index"
BATCH = 16


def card_text(card: dict, body: str) -> str:
    parts = [card["title"], body]
    if card["fields"]:
        parts.append("Fields: " + "; ".join(card["fields"]))
    if card["concepts"]:
        parts.append("Concepts: " + "; ".join(card["concepts"]))
    if card["acronyms"]:
        parts.append("; ".join(f"{k}: {v}" for k, v in card["acronyms"].items()))
    return "\n".join(parts)


def main() -> None:
    cards = [json.loads(line) for line in (DATA_DIR / "cards.jsonl").open()]
    abstract_cards = {c["id"]: c for c in map(json.loads, (DATA_DIR / "cards_abstract.jsonl").open())}
    expo_cards = {c["id"]: c for c in map(json.loads, (DATA_DIR / "cards_expo.jsonl").open())}
    linked = linked_abstracts()
    taken = {e["id"] for entries in linked.values() for e in entries}

    projects = []  # (id, card, body)
    for card in cards:
        if card["id"] in linked:
            body = "\n\n".join(e["abstract"] for e in linked[card["id"]])
            projects.append((card["id"], abstract_cards[card["id"]], body))
        elif card["status"] == "card":
            projects.append((card["id"], card, card["gloss"]))
    for e in json.loads((DATA_DIR / "expo_abstracts.json").read_text()):
        if e["id"] not in taken:
            projects.append((e["id"], expo_cards[e["id"]], e["abstract"]))

    docs = [(pid, card_text(card, body)) for pid, card, body in projects]  # (id, text)
    queries = [(pid, q) for pid, card, _ in projects for q in card["queries"]]

    model = SentenceTransformer(MODEL)
    model.max_seq_length = 2048
    doc_vecs = model.encode([t for _, t in docs], batch_size=BATCH, normalize_embeddings=True, show_progress_bar=True)
    query_vecs = model.encode(
        [t for _, t in queries], prompt=QUERY_PROMPT, batch_size=BATCH, normalize_embeddings=True, show_progress_bar=True
    )

    INDEX_DIR.mkdir(exist_ok=True)
    np.save(INDEX_DIR / "vectors.npy", np.vstack([doc_vecs, query_vecs]).astype(np.float32))
    with (INDEX_DIR / "vectors.jsonl").open("w") as f:
        for kind, rows in (("doc", docs), ("query", queries)):
            for pid, text in rows:
                f.write(json.dumps({"id": pid, "kind": kind, "text": text}) + "\n")
    print(f"{len(docs)} doc + {len(queries)} query vectors for {len(docs)} projects -> {INDEX_DIR}")


if __name__ == "__main__":
    main()

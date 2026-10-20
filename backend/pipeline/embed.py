"""Embed projects for dense retrieval with voyage-4-large.

Each project with a card (see pipeline.projects) gets one document vector and
one vector per generated query on its card:

- Document: pipeline.projects.doc_text, embedded as a document.
- Query: embedded as a query, like user queries, since they stand in for them.

User queries are embedded at search time with QUERY_MODEL, which shares
INDEX_MODEL's embedding space. Title-only grants whose card is a refusal get
no vectors; they are found by BM25 alone. Writes L2-normalized vectors as
float16 (small enough to commit) to data/index/vectors.npy and, row for row,
{id, kind, text} to data/index/vectors.jsonl. Rows whose (id, kind, text) is
already in the index keep their vector, so only new or changed rows are sent
to the API. Needs VOYAGE_API_KEY.

Usage: uv run --env-file ../.env python -m pipeline.embed
"""

import json
import os
import time

import httpx
import numpy as np

from pipeline.projects import DIM, INDEX_DIR, INDEX_MODEL, doc_text, load_projects

URL = "https://api.voyageai.com/v1/embeddings"
# Voyage caps a request at 1000 inputs and 120k tokens; ~4 chars per token.
BATCH_ITEMS = 1000
BATCH_CHARS = 200_000
RATE_LIMIT_WAIT = 20


def batches(texts: list[str]) -> list[list[str]]:
    out, size = [[]], 0
    for t in texts:
        if out[-1] and (len(out[-1]) == BATCH_ITEMS or size + len(t) > BATCH_CHARS):
            out.append([])
            size = 0
        out[-1].append(t)
        size += len(t)
    return out


def embed(client: httpx.Client, texts: list[str], input_type: str) -> np.ndarray:
    if not texts:
        return np.zeros((0, DIM), dtype=np.float32)
    vecs = []
    for batch in batches(texts):
        while (resp := client.post(URL, json={"model": INDEX_MODEL, "input": batch, "input_type": input_type, "output_dimension": DIM})).status_code == 429:
            time.sleep(RATE_LIMIT_WAIT)
        resp.raise_for_status()
        vecs += [d["embedding"] for d in sorted(resp.json()["data"], key=lambda d: d["index"])]
        print(f"{input_type}: {len(vecs)}/{len(texts)}", flush=True)
    v = np.array(vecs, dtype=np.float32)
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def main() -> None:
    projects = [p for p in load_projects() if p["card"]]
    docs = [(p["id"], doc_text(p)) for p in projects]  # (id, text)
    queries = [(p["id"], q) for p in projects for q in p["card"]["queries"]]

    known = {}  # (id, kind, text) -> vector already in the index
    if (INDEX_DIR / "vectors.npy").exists():
        rows = map(json.loads, (INDEX_DIR / "vectors.jsonl").open())
        known = {(r["id"], r["kind"], r["text"]): v for r, v in zip(rows, np.load(INDEX_DIR / "vectors.npy"))}

    vecs = {}
    with httpx.Client(headers={"Authorization": f"Bearer {os.environ['VOYAGE_API_KEY']}"}, timeout=120) as client:
        for kind, rows, input_type in (("doc", docs, "document"), ("query", queries, "query")):
            new = sorted({t for pid, t in rows if (pid, kind, t) not in known})
            print(f"{kind}: {len(rows) - len(new)} reused, {len(new)} to embed", flush=True)
            vecs[kind] = dict(zip(new, embed(client, new, input_type)))

    INDEX_DIR.mkdir(exist_ok=True)
    out = [known.get((pid, kind, t), vecs[kind].get(t)) for kind, rows in (("doc", docs), ("query", queries)) for pid, t in rows]
    np.save(INDEX_DIR / "vectors.npy", np.vstack(out).astype(np.float16))
    with (INDEX_DIR / "vectors.jsonl").open("w") as f:
        for kind, rows in (("doc", docs), ("query", queries)):
            for pid, text in rows:
                f.write(json.dumps({"id": pid, "kind": kind, "text": text}) + "\n")
    print(f"{len(docs)} doc + {len(queries)} query vectors for {len(docs)} projects -> {INDEX_DIR}")


if __name__ == "__main__":
    main()

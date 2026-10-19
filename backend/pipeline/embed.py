"""Embed projects for dense retrieval with voyage-4-large.

Each project with a card (see pipeline.projects) gets one document vector and
one vector per generated query on its card:

- Document: pipeline.projects.doc_text, embedded as a document.
- Query: embedded as a query, like user queries, since they stand in for them.

User queries are embedded at search time with QUERY_MODEL, which shares
INDEX_MODEL's embedding space. Title-only grants whose card is a refusal get
no vectors; they are found by BM25 alone. Writes L2-normalized vectors as
float16 (small enough to commit) to data/index/vectors.npy and, row for row,
{id, kind, text} to data/index/vectors.jsonl. Needs VOYAGE_API_KEY.

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

    with httpx.Client(headers={"Authorization": f"Bearer {os.environ['VOYAGE_API_KEY']}"}, timeout=120) as client:
        doc_vecs = embed(client, [t for _, t in docs], "document")
        query_vecs = embed(client, [t for _, t in queries], "query")

    INDEX_DIR.mkdir(exist_ok=True)
    np.save(INDEX_DIR / "vectors.npy", np.vstack([doc_vecs, query_vecs]).astype(np.float16))
    with (INDEX_DIR / "vectors.jsonl").open("w") as f:
        for kind, rows in (("doc", docs), ("query", queries)):
            for pid, text in rows:
                f.write(json.dumps({"id": pid, "kind": kind, "text": text}) + "\n")
    print(f"{len(docs)} doc + {len(queries)} query vectors for {len(docs)} projects -> {INDEX_DIR}")


if __name__ == "__main__":
    main()

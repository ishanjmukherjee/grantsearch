"""Embed projects for dense retrieval with voyage-4-large.

Each card that stands for a project (see pipeline.projects) gets one
document vector, one summary vector if its owner has a gloss, and one vector
per generated query, keyed by the card's owner (pipeline.projects.rows):

- Document and summary: embedded as documents.
- Query: embedded as a query, like user queries, since they stand in for them.

User queries are embedded at search time with QUERY_MODEL, which shares
INDEX_MODEL's embedding space. Title-only grants whose card is a refusal get
no vectors; they are found by BM25 alone. Writes L2-normalized vectors as
float16 (small enough to commit) to data/index/vectors.npy and, row for row,
{id, kind, text} to data/index/vectors.jsonl. Rows whose (id, kind, text) is
already in the index keep their vector, so only new or changed rows are sent
to the API. Needs VOYAGE_API_KEY, but for --check, which only counts the rows
that would be sent.

Usage: uv run --env-file ../.env python -m pipeline.embed [--check]
"""

import json
import os
import sys
import time

import httpx
import numpy as np

from pipeline.projects import DIM, INDEX_DIR, INDEX_MODEL, load_projects, rows

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
    all_rows = [row for p in load_projects() for row in rows(p)]
    docs, summaries, queries = ([(owner, t) for owner, k, t in all_rows if k == kind] for kind in ("doc", "summary", "query"))  # (owner, text)

    known = {}  # (id, kind, text) -> vector already in the index
    if (INDEX_DIR / "vectors.npy").exists():
        index_rows = map(json.loads, (INDEX_DIR / "vectors.jsonl").open())
        known = {(r["id"], r["kind"], r["text"]): v for r, v in zip(index_rows, np.load(INDEX_DIR / "vectors.npy"))}

    if "--check" in sys.argv:
        for kind, kind_rows in (("doc", docs), ("summary", summaries), ("query", queries)):
            new = {t for pid, t in kind_rows if (pid, kind, t) not in known}
            print(f"{kind}: {len(kind_rows) - len(new)} reused, {len(new)} to embed")
        return
    vecs = {}
    with httpx.Client(headers={"Authorization": f"Bearer {os.environ['VOYAGE_API_KEY']}"}, timeout=120) as client:
        for kind, kind_rows, input_type in (("doc", docs, "document"), ("summary", summaries, "document"), ("query", queries, "query")):
            new = sorted({t for pid, t in kind_rows if (pid, kind, t) not in known})
            print(f"{kind}: {len(kind_rows) - len(new)} reused, {len(new)} to embed", flush=True)
            vecs[kind] = dict(zip(new, embed(client, new, input_type)))

    INDEX_DIR.mkdir(exist_ok=True)
    kinds = (("doc", docs), ("summary", summaries), ("query", queries))
    out = [known.get((pid, kind, t), vecs[kind].get(t)) for kind, kind_rows in kinds for pid, t in kind_rows]
    np.save(INDEX_DIR / "vectors.npy", np.vstack(out).astype(np.float16))
    with (INDEX_DIR / "vectors.jsonl").open("w") as f:
        for kind, kind_rows in kinds:
            for pid, text in kind_rows:
                f.write(json.dumps({"id": pid, "kind": kind, "text": text}) + "\n")
    print(f"{len(docs)} doc + {len(summaries)} summary + {len(queries)} query vectors -> {INDEX_DIR}")


if __name__ == "__main__":
    main()

"""Hybrid search over projects: BM25 and dense retrieval fused with RRF.

- BM25 covers every project: title, people, advisors, abstracts, and the
  card's fields, concepts, acronyms and generated queries (not the gloss).
- Dense: the query is embedded on the CPU with QUERY_MODEL, which shares the
  index's embedding space, and a project scores
  max(W_DOC * doc_sim, W_QUERY * best generated-query sim). Projects whose
  title-only card is a refusal have no vectors and are found by BM25 alone.

Results carry only real data (titles, people, years, abstracts, source links);
cards only aid ranking.

Usage: uv run python -m search QUERY [--source surg|expo] [--years FROM TO] [-n 10]
"""

import argparse
import json

import bm25s
import numpy as np
import Stemmer
from sentence_transformers import SentenceTransformer

from pipeline.projects import DIM, INDEX_DIR, QUERY_MODEL, QUERY_MODEL_REVISION, doc_text, load_projects
from pipeline.scrape_surg import PAGES

W_DOC = 1.0
W_QUERY = 0.6  # query-query cosines run well above query-doc ones
RRF_K = 60

stemmer = Stemmer.Stemmer("english")


def tokenize(texts: list[str]) -> list[list[str]]:
    return bm25s.tokenize(texts, stopwords="en", stemmer=stemmer, return_ids=False, show_progress=False)


def names(people: list[dict]) -> list[str]:
    return [f"{p['first']} {p['last']}" for p in people]


def bm25_text(p: dict) -> str:
    parts = [p["title"]]
    if p["grant"]:
        parts += names(p["grant"]["awardees"])
    for e in p["expo"]:
        parts += [e["title"], e["advisor"] or "", e["abstract"], *names(e["presenters"])]
    if card := p["card"]:
        parts += card["fields"] + card["concepts"] + card["queries"]
        parts += [f"{k} {v}" for k, v in card["acronyms"].items()]
    return "\n".join(parts)


def years(p: dict) -> set[int]:
    return ({p["grant"]["year"]} if p["grant"] else set()) | {e["year"] for e in p["expo"]}


def public(p: dict) -> dict:
    """What a result shows: real data and source links, nothing from the card."""
    g = p["grant"]
    return {
        "id": p["id"],
        "title": p["title"],
        "grant": g and {"year": g["year"], "awardees": names(g["awardees"]), "url": PAGES[g["year"]]},
        "expo": [
            {
                "id": e["id"],
                "year": e["year"],
                "title": e["title"],
                "presenters": names(e["presenters"]),
                "advisor": e["advisor"],
                "abstract": e["abstract"],
                "url": e["source"],
            }
            for e in p["expo"]
        ],
    }


def rrf(scores: np.ndarray, floor: float) -> np.ndarray:
    """Reciprocal-rank credit for each project scoring above floor."""
    hits = np.flatnonzero(scores > floor)
    order = hits[np.argsort(-scores[hits], kind="stable")]
    credit = np.zeros(len(scores))
    credit[order] = 1 / (RRF_K + np.arange(1, len(order) + 1))
    return credit


class Index:
    def __init__(self) -> None:
        self.projects = load_projects()
        rows = [json.loads(line) for line in (INDEX_DIR / "vectors.jsonl").open()]
        expected = {(p["id"], "doc", doc_text(p)) for p in self.projects if p["card"]}
        expected |= {(p["id"], "query", q) for p in self.projects if p["card"] for q in p["card"]["queries"]}
        if {(r["id"], r["kind"], r["text"]) for r in rows} != expected:
            raise SystemExit(f"{INDEX_DIR} does not match the cards; rerun pipeline.embed")

        vecs = np.load(INDEX_DIR / "vectors.npy")
        self.vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
        position = {p["id"]: i for i, p in enumerate(self.projects)}
        self.row_project = np.array([position[r["id"]] for r in rows])
        self.row_is_doc = np.array([r["kind"] == "doc" for r in rows])
        self.has_vectors = np.array([p["card"] is not None for p in self.projects])

        self.bm25 = bm25s.BM25()
        self.bm25.index(bm25s.tokenize([bm25_text(p) for p in self.projects], stopwords="en", stemmer=stemmer, show_progress=False), show_progress=False)

        self.model = SentenceTransformer(QUERY_MODEL, revision=QUERY_MODEL_REVISION, trust_remote_code=True, truncate_dim=DIM, device="cpu")

    def embed(self, query: str) -> np.ndarray:
        return self.model.encode_query(query, normalize_embeddings=True)

    def dense_scores(self, query: str) -> np.ndarray:
        """Per-project dense score; -inf for projects without vectors."""
        sims = self.vecs @ self.embed(query)
        doc = np.full(len(self.projects), -np.inf)
        doc[self.row_project[self.row_is_doc]] = sims[self.row_is_doc]
        best_query = np.full(len(self.projects), -np.inf)
        np.maximum.at(best_query, self.row_project[~self.row_is_doc], sims[~self.row_is_doc])
        return np.maximum(W_DOC * doc, W_QUERY * best_query)

    def search(self, query: str, source: str | None = None, year_range: tuple[int, int] | None = None, n: int = 20) -> list[dict]:
        """The top n projects matching the filters."""
        keep = np.array([
            (source is None or (source == "surg" and p["grant"] is not None) or (source == "expo" and bool(p["expo"])))
            and (year_range is None or any(year_range[0] <= y <= year_range[1] for y in years(p)))
            for p in self.projects
        ])
        bm25 = np.where(keep, self.bm25.get_scores(tokenize([query])[0]), 0.0)
        dense = np.where(keep, self.dense_scores(query), -np.inf)
        fused = rrf(bm25, 0.0) + rrf(dense, -np.inf)
        # Projects without vectors stand in their BM25 rank for the dense one,
        # so a BM25-only match is not outranked for lack of vectors.
        fused[~self.has_vectors] *= 2
        top = [i for i in np.argsort(-fused, kind="stable")[:n] if fused[i] > 0]
        return [self.projects[i] for i in top]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("query")
    parser.add_argument("--source", choices=("surg", "expo"))
    parser.add_argument("--years", nargs=2, type=int, metavar=("FROM", "TO"))
    parser.add_argument("-n", type=int, default=10)
    args = parser.parse_args()

    results = Index().search(args.query, args.source, tuple(args.years) if args.years else None, args.n)
    for rank, p in enumerate(results, 1):
        r = public(p)
        tags = ([f"SURG {r['grant']['year']}"] if r["grant"] else []) + [f"Expo {e['year']}" for e in r["expo"]]
        print(f"{rank:2}. {r['title']}  [{', '.join(tags)}]")


if __name__ == "__main__":
    main()

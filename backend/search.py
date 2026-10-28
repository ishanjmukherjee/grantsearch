"""Hybrid search over projects: BM25 and dense retrieval fused with RRF.

- BM25 covers every project: title, people, advisors, abstracts, and the
  card's fields, concepts, acronyms and generated queries (not the gloss).
- Dense: the query is embedded on the CPU with QUERY_MODEL, which shares the
  index's embedding space, and a project scores
  max(W_DOC * best of its document and summary sims, W_QUERY * best
  generated-query sim). Projects whose title-only card is a refusal have no
  vectors and are found by BM25 alone.

The query model cannot read many acronyms, lowercase ones especially: it
splits "qpcr" into "q", "pc" and "r" and matches quantum physics. So before
embedding, each word of the query that is a known acronym gets its expansion
appended ("qpcr (qPCR, quantitative polymerase chain reaction)"); BM25 sees
the query as typed. The acronyms come from the cards the projects use, and a
key is expanded only when
- it is one word with at least two letters or digits,
- its expansions agree: those whose character trigrams have a Jaccard
  similarity of at least MERGE_SIM are taken as one spelled differently, and
  the most common such group must hold MIN_SHARE of the votes ("ad" is
  Alzheimer's disease on 16 of 21 cards; "er" is the endoplasmic reticulum on
  2 of 6 and the emergency room on 2, so it is not expanded), and
- when titles and abstracts write it, they nearly always do so in another
  casing than lowercase, not counting a capitalized word: at least
  MIN_CASED_SHARE of the time. Ordinary words that are also acronyms ("or",
  "stem", and "fish", which the abstracts write as FISH 4 times and as fish
  twice) stay as typed, as do keys the projects' own text never writes; real
  acronyms that also appear in lowercase clear it easily ("AD" 85 times,
  "ad" 3).

An empty query browses every project matching the filters in a fixed order.
SURG (2020-2024) and Expo (2021-2026) cover different years, so a single
newest-first list would open on two years of Expo projects alone. Instead,
grants (by grant year) and Expo projects without a grant (by latest Expo year)
are each sorted newest first, shuffled within a year by a hash of the id, and
merged in proportion to their sizes so both run out together. Filtered to one
source, browsing is newest first by that source's year.

A query that names someone puts that person's projects first, ahead of the
fused ranking, when people.People.pins is confident it is a name: most people
search their own name first, and the dense side cannot read names, so fusion
alone often ranks another student who shares a first name above them. Pinned
projects are ordered by how well the name matched, then, if the query has
other words ("han liu robotics"), by the fused ranking, or else most recent
first.

A project's similar projects are those whose document or summary vectors are
nearest any of its own; one without vectors uses a search for its title.

Results carry only real data (titles, people, years, abstracts, source links);
cards only aid ranking.

Usage: uv run python -m search QUERY [--source surg|expo] [--years FROM TO] [-n 10]
"""

import argparse
import hashlib
import itertools
import json
import re
import string
from collections import Counter, defaultdict

import bm25s
import numpy as np
import Stemmer
from sentence_transformers import SentenceTransformer

from pipeline.link_expo import first_match, surname_parts
from pipeline.projects import DIM, INDEX_DIR, QUERY_MODEL, QUERY_MODEL_REVISION, doc_text, load_projects, summary_text
from pipeline.scrape_surg import PAGES
from pipeline.share_ids import key, load_rows
from people import People

W_DOC = 1.0
W_QUERY = 0.6  # query-query cosines run well above query-doc ones
RRF_K = 60
# Low term-frequency saturation: containing a query word counts for more than
# repeating it, which the cards' generated queries and concepts do a lot.
BM25_K1 = 0.5
MERGE_SIM = 0.5
MIN_SHARE = 2 / 3
MIN_CASED_SHARE = 0.9

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
        parts += names(e["presenters"])
    # A poster's listings repeat its title, advisor and abstract; count each once.
    parts += dict.fromkeys(x for e in p["expo"] for x in (e["title"], e["advisor"] or "", e["abstract"]))
    if card := p["card"]:
        parts += card["fields"] + card["concepts"] + card["queries"]
        parts += [f"{k} {v}" for k, v in card["acronyms"].items()]
    return "\n".join(parts)


def years(p: dict) -> set[int]:
    return ({p["grant"]["year"]} if p["grant"] else set()) | {e["year"] for e in p["expo"]}


def browse_orders(projects: list[dict]) -> dict[str | None, list[int]]:
    """Project positions in browse order per source filter; see the module docstring."""
    def newest_first(keep, year) -> list[int]:
        ids = [i for i, p in enumerate(projects) if keep(p)]
        return sorted(ids, key=lambda i: (-year(projects[i]), hashlib.sha1(projects[i]["id"].encode()).hexdigest()))

    def expo_year(p: dict) -> int:
        return max(e["year"] for e in p["expo"])

    grants = newest_first(lambda p: p["grant"], lambda p: p["grant"]["year"])
    expo = newest_first(lambda p: not p["grant"], expo_year)
    order, g, e = [], 0, 0
    while g < len(grants) or e < len(expo):
        if e == len(expo) or (g < len(grants) and (g + 1) / len(grants) <= (e + 1) / len(expo)):
            order.append(grants[g])
            g += 1
        else:
            order.append(expo[e])
            e += 1
    return {None: order, "surg": grants, "expo": newest_first(lambda p: p["expo"], expo_year)}


def same_person(a: dict, b: dict) -> bool:
    """Whether two name records likely name one person: a shared surname part
    and first names one of which is a prefix of the other (Josh / Joshua)."""
    return bool(surname_parts(a["last"]) & surname_parts(b["last"])) and first_match(a["first"], b["first"])


def public(p: dict) -> dict:
    """What a result shows: real data and source links, nothing from the card.

    A presenter who is one of the grant's awardees is named as the grant names
    them, so that the card shows one person once."""
    g = p["grant"]
    awardees = g["awardees"] if g else []

    def presenter(x: dict) -> str:
        return next((f"{a['first']} {a['last']}" for a in awardees if same_person(a, x)), f"{x['first']} {x['last']}")

    return {
        "id": p["id"],
        "share": p["share"],
        "title": p["title"],
        "grant": g and {"year": g["year"], "awardees": names(g["awardees"]), "url": PAGES[g["year"]]},
        "expo": [
            {
                "id": e["id"],
                "year": e["year"],
                "title": e["title"],
                "presenters": [presenter(x) for x in e["presenters"]],
                "advisor": e["advisor"],
                "abstract": e["abstract"],
                "url": e["source"],
            }
            for e in p["expo"]
        ],
    }


def word_forms(word: str) -> list[str]:
    """A word as written, without surrounding brackets, quotes and sentence
    punctuation, and without any punctuation at its ends; tried in that order
    so that "cd8+", "U.S." and "qPCR." are all found."""
    return list(dict.fromkeys((word, word.strip(",;:!?\"'()[]"), word.strip(string.punctuation))))


def find_acronym(word: str, keys) -> str | None:
    return next((f for f in word_forms(word) if f.lower() in keys), None)


def trigrams(expansion: str) -> set[str]:
    """Character trigrams of an expansion, lowercased, with any space-led
    parenthetical dropped (not the parentheses of "poly(ethylene glycol)")
    and only letters and digits kept."""
    s = re.sub(r"[^a-z0-9]", "", re.sub(r" \([^()]*\)", "", expansion.lower()))
    return {s[i : i + 3] for i in range(len(s) - 2)} or {s}


def majority_expansion(votes: Counter) -> str | None:
    """The expansion of a key given each spelling's votes, if its spellings
    agree; see the module docstring. It is the most voted spelling in the
    winning group, the shortest on a tie."""
    spellings = list(votes)
    grams = [trigrams(s) for s in spellings]
    group = list(range(len(spellings)))

    def root(i: int) -> int:
        while group[i] != i:
            i = group[i]
        return i

    for i, j in itertools.combinations(range(len(spellings)), 2):
        if len(grams[i] & grams[j]) / len(grams[i] | grams[j]) >= MERGE_SIM:
            group[root(i)] = root(j)
    totals = Counter()
    for i, s in enumerate(spellings):
        totals[root(i)] += votes[s]
    best, n = totals.most_common(1)[0]
    if n < MIN_SHARE * votes.total():
        return None
    return max((s for i, s in enumerate(spellings) if root(i) == best), key=lambda s: (votes[s], -len(s)))


def acronym_expansions(projects: list[dict]) -> dict[str, tuple[str, str]]:
    """Lowercased acronym -> (its most common spelling, its expansion), for
    the acronyms the module docstring says to expand."""
    votes, spellings = defaultdict(Counter), defaultdict(Counter)
    for p in projects:
        for key, expansion in (p["card"]["acronyms"] if p["card"] else {}).items():
            if " " not in key and sum(c.isalnum() for c in key) >= 2:
                votes[key.lower()][expansion] += 1
                spellings[key.lower()][key] += 1

    lowercase, cased = Counter(), Counter()
    for p in projects:
        for text in dict.fromkeys([p["title"], *(x for e in p["expo"] for x in (e["title"], e["abstract"]))]):
            for word in text.split():
                if form := find_acronym(word, votes):
                    if form == form.lower():
                        lowercase[form] += 1
                    elif form != form.capitalize():
                        cased[form.lower()] += 1

    return {
        key: (spellings[key].most_common(1)[0][0], expansion)
        for key, v in votes.items()
        if cased[key] and cased[key] >= MIN_CASED_SHARE * (cased[key] + lowercase[key]) and (expansion := majority_expansion(v))
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
        expected |= {(p["id"], "summary", t) for p in self.projects if p["card"] and (t := summary_text(p))}
        expected |= {(p["id"], "query", q) for p in self.projects if p["card"] for q in p["card"]["queries"]}
        if {(r["id"], r["kind"], r["text"]) for r in rows} != expected:
            raise SystemExit(f"{INDEX_DIR} does not match the cards; rerun pipeline.embed")

        vecs = np.load(INDEX_DIR / "vectors.npy").astype(np.float32)
        self.vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
        self.position = {p["id"]: i for i, p in enumerate(self.projects)}
        self.row_project = np.array([self.position[r["id"]] for r in rows])
        self.row_is_doc = np.array([r["kind"] in ("doc", "summary") for r in rows])
        self.has_vectors = np.array([p["card"] is not None for p in self.projects])

        # A row is live when its id's entry still has its key; others are numbers
        # whose entry is gone (see pipeline.share_ids).
        entry_keys = {e["id"]: key(e) for p in self.projects for e in ([p["grant"]] if p["grant"] else []) + p["expo"]}
        share = {r["id"]: r["number"] for r in load_rows() if entry_keys.get(r["id"]) == r["key"]}
        if share.keys() != entry_keys.keys():
            raise SystemExit("data/share_ids.jsonl does not cover every entry; rerun pipeline.share_ids")
        self.by_number = {}
        for i, p in enumerate(self.projects):
            p["share"] = share[p["id"]]
            for e in p["expo"]:
                self.by_number.setdefault(share[e["id"]], i)
        # A project's own number wins over a listing it shares with another grant.
        self.by_number |= {p["share"]: i for i, p in enumerate(self.projects)}

        self.bm25 = bm25s.BM25(k1=BM25_K1)
        self.bm25.index(bm25s.tokenize([bm25_text(p) for p in self.projects], stopwords="en", stemmer=stemmer, show_progress=False), show_progress=False)

        self.browse_orders = browse_orders(self.projects)
        self.acronyms = acronym_expansions(self.projects)
        self.people = People(self.projects)

        self.model = SentenceTransformer(QUERY_MODEL, revision=QUERY_MODEL_REVISION, trust_remote_code=True, truncate_dim=DIM, device="cpu")

    def embed(self, query: str) -> np.ndarray:
        return self.model.encode_query(query, normalize_embeddings=True)

    def expand(self, query: str) -> str:
        """The query with the expansions of its acronyms appended, for the dense side."""
        found = dict.fromkeys(self.acronyms[form.lower()] for word in query.split() if (form := find_acronym(word, self.acronyms)))
        return f"{query} ({'; '.join(f'{spelling}, {expansion}' for spelling, expansion in found)})" if found else query

    def dense_scores(self, query: str) -> np.ndarray:
        """Per-project dense score; -inf for projects without vectors."""
        sims = self.vecs @ self.embed(query)
        doc = np.full(len(self.projects), -np.inf)
        np.maximum.at(doc, self.row_project[self.row_is_doc], sims[self.row_is_doc])
        best_query = np.full(len(self.projects), -np.inf)
        np.maximum.at(best_query, self.row_project[~self.row_is_doc], sims[~self.row_is_doc])
        return np.maximum(W_DOC * doc, W_QUERY * best_query)

    def project(self, number: int) -> dict | None:
        """The project a share number leads to, if any."""
        i = self.by_number.get(number)
        return None if i is None else self.projects[i]

    def similar(self, p: dict, n: int = 5) -> list[dict]:
        """The n projects most like p; see the module docstring."""
        i = self.position[p["id"]]
        if not self.has_vectors[i]:
            return [x for x in self.search(p["title"], n=n + 1)[0] if x is not p][:n]
        own = self.vecs[(self.row_project == i) & self.row_is_doc]
        sims = (self.vecs[self.row_is_doc] @ own.T).max(axis=1)
        best = np.full(len(self.projects), -np.inf)
        np.maximum.at(best, self.row_project[self.row_is_doc], sims)
        best[i] = -np.inf
        return [self.projects[j] for j in np.argsort(-best, kind="stable")[:n]]

    def search(self, query: str, source: str | None = None, year_range: tuple[int, int] | None = None, n: int = 20, offset: int = 0) -> tuple[list[dict], int]:
        """The n projects after the first offset matching the filters, ranked
        for the query, or in browse order when it is empty, and how many match
        in all."""
        keep = np.array([
            (source is None or (source == "surg" and p["grant"] is not None) or (source == "expo" and bool(p["expo"])))
            and (year_range is None or any(year_range[0] <= y <= year_range[1] for y in years(p)))
            for p in self.projects
        ])
        if not query.strip():
            return [self.projects[i] for i in self.browse_orders[source] if keep[i]][offset : offset + n], int(keep.sum())
        # The tokenizer drops stopwords and one-character words, which can
        # leave nothing to score ("a", "the"); the dense side still ranks.
        tokens = tokenize([query])[0]
        bm25 = np.where(keep, self.bm25.get_scores(tokens), 0.0) if tokens else np.zeros(len(self.projects))
        dense = np.where(keep, self.dense_scores(self.expand(query)), -np.inf)
        fused = rrf(bm25, 0.0) + rrf(dense, -np.inf)
        # Projects without vectors stand in their BM25 rank for the dense one,
        # so a BM25-only match is not outranked for lack of vectors.
        fused[~self.has_vectors] *= 2
        # A query that names someone puts their projects first (see
        # people.People.pins): by how well the name matched, then by the
        # ranking on any other words, or, for a name alone, most recent first.
        pins, more_words = self.people.pins(query)
        pinned = sorted(
            (i for i in map(self.position.get, pins) if keep[i]),
            key=lambda i: (-pins[self.projects[i]["id"]], 0 if more_words else -max(years(self.projects[i])), -fused[i]),
        )
        taken = set(pinned)
        ranked = pinned + [i for i in np.argsort(-fused, kind="stable") if fused[i] > 0 and i not in taken]
        return [self.projects[i] for i in ranked[offset : offset + n]], len(ranked)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("query")
    parser.add_argument("--source", choices=("surg", "expo"))
    parser.add_argument("--years", nargs=2, type=int, metavar=("FROM", "TO"))
    parser.add_argument("-n", type=int, default=10)
    args = parser.parse_args()

    results, _ = Index().search(args.query, args.source, tuple(args.years) if args.years else None, args.n)
    for rank, p in enumerate(results, 1):
        r = public(p)
        tags = ([f"SURG {r['grant']['year']}"] if r["grant"] else []) + [f"Expo {e['year']}" for e in r["expo"]]
        print(f"{rank:2}. {r['title']}  [{', '.join(tags)}]")


if __name__ == "__main__":
    main()

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
  the most common such group must hold MIN_SHARE of the votes ("pd" is
  Parkinson's disease on 9 of 10 cards; "ci" is a confidence interval on 4
  of 5 and a carbonyl index on 1, so it is not expanded, nor is "ad",
  Alzheimer's disease on 16 of 21 cards and atopic dermatitis on 4). A
  wrong expansion pulls the dense side toward another field ("ev uptake"
  toward extracellular vesicles) with nothing to tell the searcher why,
  while a missing one costs little: BM25 still matches the acronym as
  typed, and the searcher can type the expansion. So even one card in five
  or eight that means something else leaves a key as typed; and
- when titles and abstracts write it, they nearly always do so in another
  casing than lowercase, not counting a capitalized word without a digit
  ("Fish" but not "Nurr1" or "F1"): at least MIN_CASED_SHARE of the time.
  Ordinary words that are also acronyms ("or", "stem", and "fish", which the
  abstracts write as FISH 4 times and as fish twice) stay as typed, as do
  keys the projects' own text never writes; real acronyms that also appear in
  lowercase clear it easily ("AD" 85 times, "ad" 3). Writing it cased inside
  a longer word counts too ("SuperCDMS", "CRISPR-Cas9", "RBCs"); a lowercase
  piece ("co-culture") does not count against it.

An empty query browses every project matching the filters in a fixed order.
SURG (2020-2024) and Expo (2021-2026) cover different years, so a single
newest-first list would open on two years of Expo projects alone. Instead,
grants (by latest grant year) and Expo projects without a grant (by latest
Expo year) are each sorted newest first, shuffled within a year by a hash of the id, and
merged in proportion to their sizes so both run out together. Filtered to one
source, browsing is newest first by that source's year.

A query that names someone puts that person's projects first, ahead of the
fused ranking, when people.People.pins is confident it is a name: most people
search their own name first, and the dense side cannot read names, so fusion
alone often ranks another student who shares a first name above them. Pinned
projects are ordered by how well the name matched, then, if the query has
other words ("han liu robotics"), by the fused ranking, or else most recent
first.

Quoted phrases ("spectral geometry", or between curly quotes as phones type
them) keep only the projects that show each phrase: in the title, a name, an
advisor line, an Expo title or an abstract, as public() gives them, ignoring
case and runs of whitespace, and not inside a longer word at either end. The
rest is ranked as usual on the query with its quote marks dropped; a matching
project the ranking leaves out, as when the phrase is all stopwords, follows in
browse order. An unclosed quote is ignored, so a phrase being typed does not
empty the results before it is closed. The frontend finds and highlights the
phrases the same way.

A project's similar projects are those whose document or summary vectors are
nearest any of its own; one without vectors uses a search for its title, or
without one its first abstract, and has none if it has neither.

Results carry only real data (titles, people, years, abstracts, source links),
as the project's records (see public); cards only aid ranking. Index rows are
keyed by the record whose card they come from (see pipeline.projects.rows).

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

from people import People
from pipeline import share_ids
from pipeline.projects import (
    DIM,
    INDEX_DIR,
    QUERY_MODEL,
    QUERY_MODEL_REVISION,
    load_projects,
    rows,
)
from pipeline.records import same_person
from pipeline.scrape_surg import fold

W_DOC = 1.0
W_QUERY = 0.6  # query-query cosines run well above query-doc ones
RRF_K = 60
# Low term-frequency saturation: containing a query word counts for more than
# repeating it, which the cards' generated queries and concepts do a lot.
BM25_K1 = 0.5
MERGE_SIM = 0.5
MIN_SHARE = 0.9
MIN_CASED_SHARE = 0.9
QUOTE_MARKS = "\"\u201c\u201d"
QUOTED = re.compile(f"[{QUOTE_MARKS}]([^{QUOTE_MARKS}]*)[{QUOTE_MARKS}]")

stemmer = Stemmer.Stemmer("english")


def tokenize(texts: list[str]) -> list[list[str]]:
    return bm25s.tokenize([fold(t) for t in texts], stopwords="en", stemmer=stemmer, return_ids=False, show_progress=False)


def names(people: list[dict]) -> list[str]:
    return [f"{p['first']} {p['last']}" for p in people]


def advisor_name(a: dict) -> str:
    """An advisor as shown: their name, then any affiliation in parentheses."""
    name = f"{a['first']} {a['last']}".strip()
    return f"{name} ({a['affiliation']})" if a.get("affiliation") else name


def advisor_line(people: list[dict]) -> str:
    return ", ".join(advisor_name(a) for a in people)


def grants(p: dict) -> list[dict]:
    return [r for r in p["records"] if r["kind"] == "grant"]


def students(r: dict) -> list[dict]:
    return [x for x in r["people"] if x["role"] == "student"]


def bm25_text(p: dict) -> str:
    parts = [p["title"]]
    for g in grants(p):
        parts += names(students(g))
    for e in p["entries"]:
        parts += names(e["presenters"])
    for r in p["records"]:
        if r["kind"] in ("thesis", "paper"):
            parts += [r["title"], *names(students(r)), advisor_line([a for a in r["people"] if a["role"] == "advisor"]), r["abstract"]]
    # A poster's listings repeat its title, advisor and abstract; count each once.
    parts += dict.fromkeys(x for e in p["entries"] for x in (e["title"], advisor_line(e["advisors"]), e["abstract"]))
    for card in (c["card"] for c in p["cards"]):
        parts += card["fields"] + card["concepts"] + card["queries"]
        parts += [f"{k} {v}" for k, v in card["acronyms"].items()]
    return "\n".join(x for x in parts if x)


def years(p: dict) -> set[int]:
    return {r["year"] for r in p["records"]}


def browse_orders(projects: list[dict]) -> dict[str | None, list[int]]:
    """Project positions in browse order per source filter; see the module docstring."""
    def newest_first(keep, year) -> list[int]:
        ids = [i for i, p in enumerate(projects) if keep(p)]
        return sorted(ids, key=lambda i: (-year(projects[i]), hashlib.sha1(projects[i]["id"].encode()).hexdigest()))

    def grant_year(p: dict) -> int:
        return max(g["year"] for g in grants(p))

    def expo_year(p: dict) -> int:
        return max((e["year"] for e in p["entries"]), default=max(years(p)))

    granted = newest_first(lambda p: grants(p), grant_year)
    expo = newest_first(lambda p: not grants(p), expo_year)
    order, g, e = [], 0, 0
    while g < len(granted) or e < len(expo):
        if e == len(expo) or (g < len(granted) and (g + 1) / len(granted) <= (e + 1) / len(expo)):
            order.append(granted[g])
            g += 1
        else:
            order.append(expo[e])
            e += 1
    return {None: order, "surg": granted, "expo": newest_first(lambda p: p["entries"], expo_year)}


def public(p: dict) -> dict:
    """What a result shows: real data and source links, nothing from the card
    but made_title, a title written for a project whose sources print none,
    which is always shown as such ("Untitled Project: <made_title>").

    {id, share, title, made_title, records}: each record is {id, source, kind, year,
    title, url} with, for a grant, its students and advisors, and for a
    poster, its listings, each {id, title, presenters, advisors, abstract,
    url, page, abstract_source}, its url at the listing's page. A presenter who is
    one of a grant's awardees is named as the grant names them, so that the
    card shows one person once."""
    awardees = [a for g in grants(p) for a in students(g)]

    def presenter(x: dict) -> str:
        return next((f"{a['first']} {a['last']}" for a in awardees if same_person(a, x)), f"{x['first']} {x['last']}")

    def shown(r: dict) -> dict:
        out = {k: r[k] for k in ("id", "source", "kind", "year", "title", "url")}
        if r["kind"] == "grant":
            return out | {"students": names(students(r)), "advisors": [advisor_name(a) for a in r["people"] if a["role"] == "advisor"]}
        listings = [
            {
                "id": e["id"],
                "title": e["title"],
                "presenters": [presenter(x) for x in e["presenters"]],
                "advisors": [advisor_name(a) for a in e["advisors"]],
                "abstract": e["abstract"],
                "url": f"{e['url']}#page={e['page']}" if e["page"] else e["url"],
                "page": e["page"],
                "abstract_source": e["abstract_source"],
            }
            for e in p["entries"]
            if e["record"] == r["id"]
        ]
        return out | {"listings": listings}

    return {"id": p["id"], "share": p["share"], "title": p["title"], "made_title": p["made_title"], "records": [shown(r) for r in p["records"]]}


def phrases(query: str) -> list[re.Pattern]:
    """A pattern for each quoted phrase of a query; see the module docstring."""
    patterns = []
    for phrase in QUOTED.findall(query):
        if words := phrase.split():
            start = r"(?<!\w)" if re.match(r"\w", words[0]) else ""
            end = r"(?!\w)" if re.search(r"\w$", words[-1]) else ""
            patterns.append(re.compile(start + r"\s+".join(map(re.escape, words)) + end, re.IGNORECASE))
    return patterns


def shown_text(p: dict) -> list[str]:
    """The texts of a project that a result shows and quoted phrases must appear in."""
    r = public(p)
    texts = [r["title"]]
    for x in r["records"]:
        texts += x.get("students", [])
        for e in x.get("listings", []):
            texts += [e["title"], e["abstract"], ", ".join(e["advisors"]), *e["presenters"]]
    return [t for t in texts if t]


def word_forms(word: str) -> list[str]:
    """A word as written, without surrounding brackets, quotes and sentence
    punctuation, and without any punctuation at its ends; tried in that order
    so that "cd8+", "U.S." and "qPCR." are all found."""
    return list(dict.fromkeys((word, word.strip(",;:!?\"'()[]"), word.strip(string.punctuation))))


def word_parts(word: str) -> list[str]:
    """A word of a title or abstract and the acronyms it may write inside it:
    its pieces between hyphens and slashes ("TDP-43", "Keap1/Nrf2"), the
    capitalized runs after a lowercase letter ("SuperCDMS", "ipRGC"), and
    each of these without a plural s ("RBCs", "ipRGCs")."""
    pieces = [word, *re.split(r"[-/]", word)]
    pieces += [run for piece in pieces[1:] for run in re.split(r"(?<=[a-z])(?=[A-Z])", piece)]
    pieces += [m[1] for piece in pieces if (m := re.fullmatch(r"(.*[A-Z0-9])s[^A-Za-z0-9]*", piece))]
    return list(dict.fromkeys(p for p in pieces if p))


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
        for key, expansion in (x for c in p["cards"] for x in c["card"]["acronyms"].items()):
            if " " not in key and sum(c.isalnum() for c in key) >= 2:
                votes[key.lower()][expansion] += 1
                spellings[key.lower()][key] += 1

    lowercase, cased = Counter(), Counter()
    for p in projects:
        for text in filter(None, dict.fromkeys([p["title"], *(x for e in p["entries"] for x in (e["title"], e["abstract"]))])):
            for word in fold(text).split():
                if (form := find_acronym(word, votes)) and form == form.lower():
                    lowercase[form] += 1
                # A word's pieces show where it writes an acronym cased, but
                # a lowercase piece is a prefix ("co-culture"), not the acronym.
                for form in dict.fromkeys(f for part in word_parts(word) if (f := find_acronym(part, votes))):
                    if form != form.lower() and (form != form.capitalize() or any(c.isdigit() for c in form)):
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
    def __init__(self, strict: bool = True) -> None:
        """strict: refuse to start when the index's rows are not exactly the
        projects' (see pipeline.projects.rows); otherwise use its rows as
        they are, matched to projects by owner."""
        self.projects = load_projects()
        index_rows = [json.loads(line) for line in (INDEX_DIR / "vectors.jsonl").open()]
        expected = {row for p in self.projects for row in rows(p)}
        if strict and {(r["id"], r["kind"], r["text"]) for r in index_rows} != expected:
            raise SystemExit(f"{INDEX_DIR} does not match the cards; rerun pipeline.embed")

        vecs = np.load(INDEX_DIR / "vectors.npy").astype(np.float32)
        self.vecs = vecs / np.linalg.norm(vecs, axis=1, keepdims=True)
        self.position = {p["id"]: i for i, p in enumerate(self.projects)}
        owner = {c["owner"]: i for i, p in enumerate(self.projects) for c in p["cards"]}
        self.row_project = np.array([owner[r["id"]] for r in index_rows])
        self.row_is_doc = np.array([r["kind"] in ("doc", "summary") for r in index_rows])
        self.has_vectors = np.array([bool(p["cards"]) for p in self.projects])

        # Every record and listing of a project leads to it by its number. A
        # row is live when its id's entry still has its key; others are
        # numbers whose entry is gone (see pipeline.share_ids).
        current = sorted(share_ids.entries(), key=lambda e: e["id"])
        keys = dict(zip((e["id"] for e in current), share_ids.keys(current)))
        share = {r["id"]: r["number"] for r in share_ids.load_rows() if keys.get(r["id"]) == r["key"]}
        self.by_number = {}
        for i, p in enumerate(self.projects):
            for id in dict.fromkeys([r["id"] for r in p["records"]] + [e["id"] for e in p["entries"]]):
                if id not in share:
                    raise SystemExit("data/share_ids.jsonl does not cover every record; rerun pipeline.share_ids")
                self.by_number[share[id]] = i
            p["share"] = share[p["id"]]

        self.bm25 = bm25s.BM25(k1=BM25_K1)
        self.bm25.index(bm25s.tokenize([fold(bm25_text(p)) for p in self.projects], stopwords="en", stemmer=stemmer, show_progress=False), show_progress=False)

        self.browse_orders = browse_orders(self.projects)
        self.shown = [shown_text(p) for p in self.projects]
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
            query = p["title"] or next((e["abstract"] for e in p["entries"] if e["abstract"]), None)
            return [x for x in self.search(query, n=n + 1)[0] if x is not p][:n] if query else []
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
            (source is None or any(r["source"] == source for r in p["records"]))
            and (year_range is None or any(year_range[0] <= y <= year_range[1] for y in years(p)))
            for p in self.projects
        ])
        quoted = phrases(query)
        if quoted:
            keep &= np.array([all(any(q.search(t) for t in texts) for q in quoted) for texts in self.shown])
            query = re.sub(f"[{QUOTE_MARKS}]", " ", query)
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
        if quoted:
            taken |= set(ranked)
            ranked += [i for i in self.browse_orders[None] if keep[i] and i not in taken]
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
        tags = [f"{'SURG' if r['source'] == 'surg' else 'Expo'} {r['year']}" for r in p["records"]]
        print(f"{rank:2}. {p['title'] or '(untitled)'}  [{', '.join(tags)}]")


if __name__ == "__main__":
    main()

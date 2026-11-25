"""Topic-search checks: is a known project found, and what does a source take of broad searches?

Two reports, each made to be rerun when a source is added or ranking changes.
Neither is a measure of how good the ranking is: the known items are too few
and too easy for that (see README, "A proper eval set for ranking"). They
are floors, there to show a change that breaks something.

items: data/eval/known_items.jsonl holds hand-written queries, each with the
one project it was written for ({query, relevant: [record id], kind}). A
query is a topic search in a searcher's words, not the project's title, and
not one of the queries its card generated: those are embedded in the index,
so searching one finds its own row and tests nothing. The report gives, by
the source of the target, hit@1, hit@5, hit@10 and MRR over the top DEPTH,
and lists each query whose target is not first.

- The targets of the first 27 are SURG grants and Expo posters. 21 ("topic")
  were written from the projects; 6 ("reported") are searches that were
  reported as missing their project. Two more reported ones, "codewords"
  and "code words" for a study of a secret spoken language, were dropped: a
  one-word search that many projects on codes answer as fairly has no single
  target.
- 20 have Leopold fellowships' faculty projects as targets, written when the
  source was added, from the entries (titles and what the faculty wrote in
  offering the project), as a student who does not know the book would ask:
  "why doesn't america have a national sales tax" for Mehrotra's "The VAT
  Laggard". They were written by the same reader that checked the projects'
  cards, with the cards in view, so they are likely easier than a
  stranger's searches would be.
- --without SOURCE also counts the targets from other sources that some
  project of that source stands above. That is what adding the source cost
  the projects that were there before it: with --without leopold, 0 of the
  27 older targets when it went in.

broad: data/eval/broad.jsonl holds short searches, one or two words
({query, group}), of the kind that name a whole field rather than a project.
For each, the report counts the top TOP results by source (a project of two
sources under both), then gives each source's share of those results over
each group beside its share of all projects.

- The question is what a source takes of the first page when the query does
  not single anything out. Leopold fellowships are 131 of 7,557 projects
  (1.7%) but all in one department, and their cards are a professor's book
  described from its title, which reads much like a broad query. A source
  that takes most of the first page of "empire" pushes student work on
  empire off it.
- group is "history" for searches the history department's projects are fair
  results for, and "other" for fields they are not. The "other" group is the
  check with a right answer: a source confined to one field should take
  about nothing there. The "history" group has no right answer and is kept
  as a baseline: 1.8 of the top 10 on average when the source went in (7 of
  10 on "empire", 6 on "american history", 5 on "history"), and none of
  the top 10 of any "other" search.
- Nothing here fails a run. Whether faculty projects should stand ahead of
  student work on a broad search is a choice about the site, not a bug, and
  the numbers are there to make it with.

Usage: uv run python -m eval_topics items [--without SOURCE] | broad
"""

import argparse
import json
from collections import Counter, defaultdict

from pipeline.records import DATA_DIR

ITEMS = DATA_DIR / "eval" / "known_items.jsonl"
BROAD = DATA_DIR / "eval" / "broad.jsonl"
DEPTH = 100
TOP = 10


def items(without: str | None) -> None:
    from search import FILTERS, TAGS, Index

    index = Index()
    rows = [json.loads(line) for line in ITEMS.open()]
    # A target is a record or one of a poster's listings; a result is the target's when it holds it.
    project_of = {id: p["id"] for p in index.projects for id in [r["id"] for r in p["records"]] + [e["id"] for e in p["entries"]]}
    source_of = {r["id"]: r["source"] for p in index.projects for r in p["records"]} | {e["id"]: e["source"] for p in index.projects for e in p["entries"]}

    def of(p: dict) -> bool:
        return any(r["source"] in FILTERS[without] for r in p["records"])

    scores, misses, displaced = defaultdict(list), [], []
    for row in rows:
        ranked = index.search(row["query"], n=DEPTH)[0]
        targets = {project_of[x] for x in row["relevant"]}
        first = next((i for i, p in enumerate(ranked, 1) if p["id"] in targets), None)
        source = TAGS[source_of[row["relevant"][0]]]
        scores[source].append((first == 1, first is not None and first <= 5, first is not None and first <= 10, 1 / first if first else 0.0))
        if first != 1:
            misses.append((first, row["query"], ranked[0]["title"] or "untitled"))
        if without and source_of[row["relevant"][0]] not in FILTERS[without]:
            above = sum(of(p) for p in ranked[: (first or len(ranked) + 1) - 1])
            if above:
                displaced.append((above, first, row["query"]))

    print(f"{'target':10} {'n':>4} {'hit@1':>6} {'hit@5':>6} {'hit@10':>6} {'MRR':>6}")
    for source, s in sorted(scores.items()):
        print(f"{source:10} {len(s):4} " + " ".join(f"{sum(x[i] for x in s) / len(s):6.2f}" for i in range(4)))
    for first, query, top in sorted(misses, key=lambda m: m[0] or DEPTH + 1):
        print(f"  rank {first or f'>{DEPTH}'}: {query}  (first: {top[:60]})")
    if without:
        others = sum(1 for row in rows if source_of[row["relevant"][0]] not in FILTERS[without])
        print(f"{len(displaced)} of {others} targets from other sources have a {TAGS[FILTERS[without][0]]} project above them")
        for above, first, query in sorted(displaced, reverse=True):
            print(f"  {above} above, now rank {first or f'>{DEPTH}'}: {query}")


def broad() -> None:
    from search import FILTERS, Index

    index = Index()
    rows = [json.loads(line) for line in BROAD.open()]

    def sources(p: dict) -> set[str]:
        return {f for f, held in FILTERS.items() if any(r["source"] in held for r in p["records"])}

    share = Counter(f for p in index.projects for f in sources(p))
    taken: dict[str, Counter] = defaultdict(Counter)
    print(f"{'query':24} {'group':8} " + " ".join(f"{f:>8}" for f in FILTERS))
    for row in rows:
        counts = Counter(f for p in index.search(row["query"], n=TOP)[0] for f in sources(p))
        taken[row["group"]] += counts
        taken[row["group"]]["queries"] += 1
        print(f"{row['query']:24} {row['group']:8} " + " ".join(f"{counts[f]:8}" for f in FILTERS))
    print(f"\nshare of the top {TOP}, by group, beside each source's share of all {len(index.projects)} projects")
    for group, counts in sorted(taken.items()):
        print(f"{group:33} " + " ".join(f"{counts[f] / (TOP * counts['queries']):8.1%}" for f in FILTERS))
    print(f"{'all projects':33} " + " ".join(f"{share[f] / len(index.projects):8.1%}" for f in FILTERS))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("report", choices=("items", "broad"))
    parser.add_argument("--without", metavar="SOURCE", choices=("surg", "expo", "theses", "nurj", "leopold"), help="items: also count the targets a project of this source filter stands above")
    args = parser.parse_args()
    if args.report == "items":
        items(args.without)
    else:
        broad()


if __name__ == "__main__":
    main()

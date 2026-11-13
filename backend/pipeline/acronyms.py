"""The acronyms search expands in a query, each judged once for the whole site.

The query model cannot read many acronyms (see search), so search appends an
acronym's expansion to a query that contains it. Whatever one project means
by an acronym then reaches every query that contains those letters, so a key
is expanded only when someone typing it nearly always means that expansion.
A card cannot tell: it knows its own project, and "SEC" is the Super
Elongation Complex on the one card that defines it and the Securities and
Exchange Commission in the abstracts that write it. So the cards only
propose, and each key is judged apart from them, by reading what the cards
propose for it beside how the site's titles and abstracts write it
(prompts/acronym.md).

A key is a card acronym of one word with at least two letters or digits,
lowercased. data/generated/acronyms.jsonl holds one line per judged key:

- id: the key.
- spelling: how the cards most often write it ("qPCR").
- expansion: the proposed expansion search appends, or None to leave the
  key as typed.
- proposed: every expansion the cards proposed when it was judged.
- reason: why, in a few words.

A key is pending when it has no line, or when a card now proposes an
expansion its line was not judged against: a new source that means something
else by a key reopens it. Search reads only the file, so a pending key is
not expanded, which costs little: BM25 still matches the letters as typed.
data/overrides.jsonl patches lines by id like any generated file's, and a
patch for a key no card proposes adds it ("cdms", which the cards write only
inside "SuperCDMS").

Judging: --batches writes the pending keys in batches, each key with its
evidence:

- spellings, and proposed: each expansion with how many cards propose it and
  the titles and fields of up to three projects that do.
- written: how often titles and abstracts write the key in capitals or mixed
  case ("cased", counting inside a longer word too: "SuperCDMS",
  "CRISPR-Cas9", "RBCs"), as a capitalized word without a digit
  ("capitalized": "Mars"), and in lowercase.
- elsewhere: how many projects that do not propose the key write it cased,
  with up to four of those passages.
- as_word: up to two passages that write it capitalized or in lowercase.
- names: how many people in the records have it as a first or last name.

--merge reads the verdicts ({id, expansion, reason} per line), checks each
against what was proposed, and rewrites the file: verdicts still current are
kept, new ones added, and lines for keys no card proposes any more dropped.
A key may be judged more than once, and is then expanded only if every
verdict expands it (to the first verdict's expansion, should they pick
different spellings of it). Keys of up to three characters are judged twice:
two readers of one brief split on about one in ten of them (84 of 855 in
November 2026), nearly always over a rival meaning that one reader thought
of or weighed more. --max-length 3 writes their batches alone; write both
sets of batches before merging, since a merged key is no longer pending.

data/eval/acronyms.jsonl is a hand-written check on the result: queries with
the text search should embed for each ({query, expanded}), some that must
gain an expansion and some that must stay as typed.

Usage: uv run python -m pipeline.acronyms [--batches DIR [--size 150] [--max-length N] [--all]] [--merge FILE ...]
Without options, prints the pending keys and the eval queries search would
expand otherwise, and exits 1 if there are any of either.
"""

import argparse
import json
import re
import string
from collections import Counter, defaultdict
from pathlib import Path

from pipeline.projects import DATA_DIR, GENERATED, OVERRIDES, load_projects
from pipeline.records import merge_patch
from pipeline.scrape_surg import fold

NAME = f"{GENERATED}/acronyms.jsonl"
EVAL = DATA_DIR / "eval" / "acronyms.jsonl"
CONTEXT = 9  # words of a passage on each side of the key


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


def find(word: str, keys) -> str | None:
    """The form of a word that is one of the keys, if any."""
    return next((f for f in word_forms(word) if f.lower() in keys), None)


def load() -> dict[str, dict]:
    """The judged keys by id, with their overrides applied."""
    path = DATA_DIR / NAME
    table = {x["id"]: x for x in map(json.loads, path.open())} if path.exists() else {}
    for o in map(json.loads, OVERRIDES.open()):
        if o["file"] == NAME:
            table[o["id"]] = merge_patch(table.get(o["id"], {"id": o["id"]}), o["patch"])
    return table


def expansions() -> dict[str, tuple[str, str]]:
    """Key -> (its spelling, its expansion), for the keys search expands."""
    return {k: (x["spelling"], x["expansion"]) for k, x in load().items() if x["expansion"]}


def expand(query: str, expanded: dict[str, tuple[str, str]]) -> str:
    """The query with the expansions of its acronyms appended."""
    found = dict.fromkeys(expanded[form.lower()] for word in query.split() if (form := find(word, expanded)))
    return f"{query} ({'; '.join(f'{spelling}, {expansion}' for spelling, expansion in found)})" if found else query


def failures() -> list[str]:
    """The queries of data/eval/acronyms.jsonl that search would not expand as
    the file says."""
    expanded = expansions()
    return [f"{x['query']!r}: expected {x['expanded']!r}, got {got!r}" for x in map(json.loads, EVAL.open()) if (got := expand(x["query"], expanded)) != x["expanded"]]


def proposals(projects: list[dict]) -> dict[str, dict]:
    """Key -> what the cards propose for it: spellings and expansions, each
    with its number of cards, and for each expansion the positions of the
    projects whose cards propose it."""
    out: dict[str, dict] = {}
    for i, p in enumerate(projects):
        for key, expansion in (x for c in p["cards"] for x in c["card"]["acronyms"].items()):
            if " " not in key and sum(c.isalnum() for c in key) >= 2:
                x = out.setdefault(key.lower(), {"spellings": Counter(), "expansions": Counter(), "projects": defaultdict(list)})
                x["spellings"][key] += 1
                x["expansions"][expansion] += 1
                if i not in x["projects"][expansion]:
                    x["projects"][expansion].append(i)
    return out


def pending(proposed: dict[str, dict], table: dict[str, dict]) -> list[str]:
    """The keys to judge; see the module docstring."""
    return sorted(k for k, x in proposed.items() if k not in table or set(x["expansions"]) - set(table[k].get("proposed", [])))


def spelling(x: dict) -> str:
    return max(x["spellings"], key=lambda s: (x["spellings"][s], s))


def texts(p: dict) -> list[str]:
    """A project's titles and abstracts, each once."""
    return list(filter(None, dict.fromkeys(x for r in [p, *p["records"], *p["entries"]] for x in (r["title"], r.get("abstract")))))


def evidence(projects: list[dict], proposed: dict[str, dict], keys: list[str]) -> list[dict]:
    """What the judge reads for each key; see the module docstring."""
    wanted = set(keys)
    written = {k: Counter() for k in keys}
    elsewhere: dict[str, dict[int, str]] = {k: {} for k in keys}
    as_word: dict[str, dict[int, str]] = {k: {} for k in keys}
    names = Counter()
    for i, p in enumerate(projects):
        for person in (x for r in p["records"] for x in r["people"]):
            names.update({w for w in re.split(r"[\s-]+", fold(f"{person['first']} {person['last']}").lower()) if w in wanted})
        for text in texts(p):
            words = fold(text).split()
            for j, word in enumerate(words):
                passage = " ".join(words[max(0, j - CONTEXT) : j + CONTEXT + 1])
                if (form := find(word, wanted)) and (form == form.lower() or (form == form.capitalize() and not any(c.isdigit() for c in form))):
                    written[form.lower()]["lowercase" if form == form.lower() else "capitalized"] += 1
                    as_word[form.lower()].setdefault(i, passage)
                # A word's pieces show where it writes an acronym cased, but
                # a lowercase piece is a prefix ("co-culture"), not the acronym.
                for form in dict.fromkeys(f for part in word_parts(word) if (f := find(part, wanted))):
                    if form != form.lower() and (form != form.capitalize() or any(c.isdigit() for c in form)):
                        key = form.lower()
                        written[key]["cased"] += 1
                        if not any(i in owners for owners in proposed[key]["projects"].values()):
                            elsewhere[key].setdefault(i, passage)

    def spread(passages: dict[int, str], n: int) -> list[str]:
        found = list(passages.values())
        return [found[i * len(found) // n] for i in range(n)] if len(found) > n else found

    def describe(i: int) -> str:
        p = projects[i]
        fields = list(dict.fromkeys(f for c in p["cards"] for f in c["card"]["fields"]))
        return f"{p['title'] or p['made_title']} ({'; '.join(fields)})"

    out = []
    for k in keys:
        x = proposed[k]
        out.append(
            {
                "id": k,
                "spellings": dict(x["spellings"].most_common()),
                "proposed": [{"expansion": e, "cards": n, "projects": [describe(i) for i in x["projects"][e][:3]]} for e, n in x["expansions"].most_common()],
                "written": {kind: written[k][kind] for kind in ("cased", "capitalized", "lowercase")},
                "elsewhere": {"projects": len(elsewhere[k]), "passages": spread(elsewhere[k], 4)},
                "as_word": spread(as_word[k], 2),
                "names": names[k],
            }
        )
    return out


def merge(proposed: dict[str, dict], table: dict[str, dict], verdicts: list[dict]) -> dict[str, dict]:
    """The table with the verdicts added; see the module docstring."""
    waiting = set(pending(proposed, table))
    out = {k: x for k, x in table.items() if k in proposed and k not in waiting}
    judged: dict[str, list[dict]] = defaultdict(list)
    for v in verdicts:
        if set(v) != {"id", "expansion", "reason"} or v["id"] not in proposed:
            raise SystemExit(f"{v.get('id')}: not a verdict on a proposed key: {v}")
        if v["expansion"] is not None and v["expansion"] not in proposed[v["id"]]["expansions"]:
            raise SystemExit(f"{v['id']}: {v['expansion']!r} is not one of the proposed expansions {list(proposed[v['id']]['expansions'])}")
        if not isinstance(v["reason"], str) or not v["reason"].strip():
            raise SystemExit(f"{v['id']}: no reason")
        judged[v["id"]].append(v)
    for k, vs in judged.items():
        # The first verdict that leaves the key decides; otherwise the first.
        v = next((v for v in vs if v["expansion"] is None), vs[0])
        if v["expansion"] is not None and len({v["expansion"] for v in vs}) > 1:
            print(f"{k}: expanded as {' and as '.join(repr(v['expansion']) for v in vs)}; kept the first")
        out[k] = {"id": k, "spelling": spelling(proposed[k]), "expansion": v["expansion"], "proposed": sorted(proposed[k]["expansions"]), "reason": v["reason"].strip()}
    return dict(sorted(out.items()))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batches", type=Path, help="write the pending keys, with their evidence, as batch files in this folder")
    ap.add_argument("--size", type=int, default=150, help="keys per batch")
    ap.add_argument("--max-length", type=int, help="with --batches: only keys of at most this many characters")
    ap.add_argument("--all", action="store_true", help="with --batches: every proposed key, judged or not")
    ap.add_argument("--merge", type=Path, nargs="+", help="verdict files to add to the judged keys")
    args = ap.parse_args()

    projects = load_projects()
    proposed = proposals(projects)
    path = DATA_DIR / NAME
    table = {x["id"]: x for x in map(json.loads, path.open())} if path.exists() else {}

    if args.merge:
        verdicts = [json.loads(line) for f in args.merge for line in f.open() if line.strip()]
        table = merge(proposed, {} if args.all else table, verdicts)
        path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in table.values()))
        print(f"wrote {len(table)} judged keys to {path}, {sum(bool(x['expansion']) for x in table.values())} of them expanded")

    waiting = sorted(proposed) if args.all and not args.merge else pending(proposed, table)
    if args.batches:
        args.batches.mkdir(parents=True, exist_ok=True)
        lines = evidence(projects, proposed, [k for k in waiting if not args.max_length or len(k) <= args.max_length])
        for n, start in enumerate(range(0, len(lines), args.size), 1):
            (args.batches / f"batch_{n:02d}.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines[start : start + args.size]))
        print(f"wrote {len(lines)} keys to {args.batches} in batches of {args.size}")
        return
    print(f"{len(proposed)} proposed keys, {len(table)} judged, {len(waiting)} pending")
    if waiting:
        print(" ".join(waiting))
    failed = failures()
    if waiting or failed:
        raise SystemExit("\n".join(failed) or 1)


if __name__ == "__main__":
    main()

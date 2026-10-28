"""The people named on projects, and matching typed names against them.

Each person is a distinct name in one role, "student" (a grant awardee or Expo
presenter) or "advisor" (from an Expo listing's advisor line), with the
projects that name them. A name is stored only as its parts:

- first: given names, including a preferred name the source puts in
  parentheses ("Xinyuan (Joyce) Pu" has first names Xinyuan and Joyce)
- middle: any further given names and initials
- last: the surname as printed

Everything a searcher might type differently lives on the matching side,
built at startup and never stored: word order (a query's words are compared
with a person's name parts in any order), accents and case, apostrophes and
hyphens (O'Connor is "oconnor" and "connor"), nicknames (NICKNAMES_SOURCE, plus
first names one of which is a prefix of the other, as in pipeline.link_expo),
typos (edit distance, scaled to word length) and spelling by sound (Metaphone,
checked against spelling).

A person matches a query when some query word matches their surname; each
query word and each name part counts once, best matches first. Typo and sound
matches apply only to query words that no project's own text uses.

pins() decides when a query names someone confidently enough that search
should put their projects first. A missed name only falls back to the normal
ranking, while a wrong pin buries a topic search's results with nothing on
screen to say why, so the rules favor precision:

- Two or more query words match one person (one of them their surname): the
  query is a name, possibly with topic words added ("han liu robotics"). Any
  kind of match counts; a typo in a full name is still a name search.
- The query is one word that matches surnames, and no project's own text
  (titles, abstracts, cards, glosses, less the names of the project's own
  people) uses that word: there it names people, so "luey" pins and "rice" or
  "stone" do not. If the word is someone's exact
  surname, only exact matches pin, not names it is also a typo of.

Usage: uv run python -m people QUERY
"""

import argparse
import re
import unicodedata
from collections import defaultdict

import jellyfish
from nicknames import NickNamer

from pipeline.link_expo import MIN_PREFIX
from pipeline.parse_expo import PARTICLES, split_people

NICKNAMES_SOURCE = "nicknames (github.com/carltonnorthern/nicknames, Apache-2.0)"
HONORIFICS = {"dr", "prof", "professor"}
MIN_FUZZY = 4  # shorter words match only exactly: Li and Lu are different surnames
# How well a query word matches a name part, by the closest relation found.
EXACT = 1.0
NICKNAME = 0.9  # also a prefix: Chris / Christopher
TYPO = 0.75
SOUND = 0.6
# Metaphone codes are coarse (Katica and Queitoga are both KTK), so a sound
# match must also be this similar as spelled (Jaro-Winkler): Kaitlyn / Caitlin
# score 0.81, Stephen / Steven 0.89, Katica / Queitoga 0.51.
MIN_SOUND_SPELLING = 0.75


def fold(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().casefold()


def forms(word: str) -> list[str]:
    """The ways a name word can be typed: its letter runs ("o", "connor") and,
    when there are several, all of them joined ("oconnor")."""
    runs = re.findall(r"[a-z0-9]+", fold(word))
    return list(dict.fromkeys(runs + ["".join(runs)] if len(runs) > 1 else runs))


def query_words(query: str) -> list[str]:
    """A query's words, with apostrophes dropped so "o'brien" is "obrien"."""
    return re.findall(r"[a-z0-9]+", fold(re.sub("['\u2019]", "", query)))


def split_name(record: dict) -> dict:
    """A {first, last} record from the sources as first, middle and last names."""
    given = record["first"]
    preferred = re.findall(r"\(([^)]*)\)", given)
    words = [w for w in re.sub(r"\([^)]*\)", " ", given).split() if fold(w).strip(".") not in HONORIFICS]
    return {"first": words[:1] + [p.strip() for p in preferred if p.strip()], "middle": words[1:], "last": record["last"]}


def advisor_names(advisor: str | None) -> list[dict]:
    """The people on an Expo advisor line, without affiliations in parentheses."""
    return split_people(re.sub(r"\s*\([^)]*\)", "", advisor or ""), last_first=False)


class People:
    def __init__(self, projects: list[dict]) -> None:
        # Every word of every project's own text (titles, abstracts, cards,
        # glosses) except the names of that project's people: "Ann Bradlow
        # speech lab" on Bradlow's card names her, it does not use "bradlow"
        # as a word.
        self.text_words: set[str] = set()
        found: dict[tuple, dict] = {}
        for p in projects:
            mentions = [("student", x) for x in p["grant"]["awardees"]] if p["grant"] else []
            for e in p["expo"]:
                mentions += [("student", x) for x in e["presenters"]]
                mentions += [("advisor", x) for x in advisor_names(e["advisor"])]
            for role, x in mentions:
                key = (role, fold(x["first"]).strip(), fold(x["last"]).strip())
                person = found.setdefault(key, {**split_name(x), "role": role, "projects": []})
                if p["id"] not in person["projects"]:
                    person["projects"].append(p["id"])

            own_names = {f for _, x in mentions for word in f"{x['first']} {x['last']}".split() for f in forms(word)}
            texts = [p["title"], p.get("gloss") or "", *(x for e in p["expo"] for x in (e["title"], e["abstract"]))]
            if card := p["card"]:
                texts += [card.get("gloss", ""), *card["fields"], *card["concepts"], *card["queries"]]
                texts += [f"{k} {v}" for k, v in card["acronyms"].items()]
            for text in texts:
                self.text_words.update(w for w in query_words(text) if w not in own_names)
        self.people = list(found.values())

        # name word -> (person, which part) for every typable form of every part
        self.words: dict[str, set[tuple[int, str]]] = defaultdict(set)
        for i, person in enumerate(self.people):
            for kind in ("first", "middle", "last"):
                parts = [person["last"]] if kind == "last" else person[kind]
                for part in parts:
                    for word in part.split():
                        for f in forms(word):
                            self.words[f].add((i, kind))
        self.by_sound: dict[str, set[str]] = defaultdict(set)
        for w in self.words:
            if len(w) >= MIN_FUZZY:
                self.by_sound[jellyfish.metaphone(w)].add(w)
        self.namer = NickNamer()

    def typos(self, q: str) -> list[str]:
        """Name words a typo away from q: one edit for words under 8 letters, two from 8."""
        if len(q) < MIN_FUZZY:
            return []
        limit = 1 if len(q) < 8 else 2
        return [w for w in self.words if abs(len(w) - len(q)) <= limit and len(w) >= MIN_FUZZY and jellyfish.damerau_levenshtein_distance(q, w) <= limit]

    def word_matches(self, q: str) -> dict[str, float]:
        """Name words that query word q may be meant as, with how well each matches."""
        found = {q: EXACT} if q in self.words else {}

        def add(w: str, quality: float) -> None:
            if w in self.words and quality > found.get(w, 0):
                found[w] = quality

        for nickname in self.namer.nicknames_of(q) | self.namer.canonicals_of(q):
            add(nickname, NICKNAME)
        # The list spells a full name one way; the data may spell it another
        # ("maddie" -> Madeline, not Madeleine). Only full names: "will" ->
        # Bill -> Hill is no name for Will.
        for full in self.namer.canonicals_of(q):
            for w in self.typos(full):
                add(w, TYPO)
        if len(q) >= MIN_PREFIX:
            # pipeline.link_expo.first_match on words already folded and split
            for w in self.words:
                if w != q and len(w) >= MIN_PREFIX and (w.startswith(q) or q.startswith(w)):
                    add(w, NICKNAME)
        # A word the projects' own text uses is a word, not a misspelled name
        # ("than" is not a typo of Ethan, nor "arab" of Aran).
        if len(q) >= MIN_FUZZY and q not in self.text_words:
            for w in self.typos(q):
                add(w, TYPO)
            for w in self.by_sound.get(jellyfish.metaphone(q), ()):
                if jellyfish.jaro_winkler_similarity(q, w) >= MIN_SOUND_SPELLING:
                    add(w, SOUND)
        return found

    def match(self, query: str) -> list[dict]:
        """People a query names, best first: {person, score, words}, where words
        maps each query word that matched to (name word, its quality)."""
        # person -> every (quality, query word, part kind, name word) that
        # matches; nicknames and prefixes count only against given names
        options: dict[int, list[tuple[float, str, str, str]]] = defaultdict(list)
        for q in dict.fromkeys(query_words(query)):
            for w, quality in self.word_matches(q).items():
                for i, kind in self.words[w]:
                    if not (kind == "last" and quality == NICKNAME and w != q):
                        options[i].append((quality, q, kind, w))

        out = []
        for i, found in options.items():
            # Best matches first, each query word and each name part used
            # once: "hong kong" is not Hong twice.
            matched: dict[str, tuple[float, str, str]] = {}
            used = set()
            for quality, q, kind, w in sorted(found, reverse=True):
                if q not in matched and (kind, w) not in used:
                    matched[q] = (quality, kind, w)
                    used.add((kind, w))
            surname = [m for m in matched.values() if m[1] == "last" and (m[2] not in PARTICLES or self.only_particles(i))]
            if surname:
                out.append({"person": self.people[i], "score": sum(m[0] for m in matched.values()), "words": {q: (m[2], m[0]) for q, m in matched.items()}})
        return sorted(out, key=lambda m: -m["score"])

    def pins(self, query: str) -> tuple[dict[str, float], bool]:
        """The projects to put first for a query, by the module docstring's
        rules, each with the best score of a pinned person naming it; and
        whether the query has words beyond the pinned names."""
        words = query_words(query)
        matches = self.match(query)
        pinned = [m for m in matches if len(m["words"]) >= 2]
        if not pinned and len(words) == 1 and words[0] not in self.text_words:
            exact = [m for m in matches if m["words"][words[0]][1] == EXACT]
            pinned = exact or matches
        scores: dict[str, float] = {}
        for m in pinned:
            for pid in m["person"]["projects"]:
                scores[pid] = max(scores.get(pid, 0.0), m["score"])
        return scores, any(len(m["words"]) < len(words) for m in pinned)

    def only_particles(self, i: int) -> bool:
        """Whether a person's surname is nothing but particles ("Le", "Du")."""
        return all(fold(w) in PARTICLES for w in self.people[i]["last"].split())


def main() -> None:
    from pipeline.projects import load_projects

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("query")
    parser.add_argument("-n", type=int, default=10)
    args = parser.parse_args()
    people = People(load_projects())
    for m in people.match(args.query)[: args.n]:
        p = m["person"]
        name = " ".join(p["first"][:1] + p["middle"] + [p["last"]]) + (f" ({', '.join(p['first'][1:])})" if p["first"][1:] else "")
        print(f"{m['score']:.2f}  {name}  [{p['role']}]  { {q: w for q, (w, _) in m['words'].items()} }  {p['projects']}")
    print("pins:", people.pins(args.query))


if __name__ == "__main__":
    main()

"""The records every source is parsed into, all in one shape, and their files.

A record is one source's account of one piece of work: a SURG grant, an Expo
or Symposium poster, an honors thesis, a NURJ paper. Each source's parser
writes its records to data/records/<source>.jsonl (SOURCES), one per line,
sorted by id. The stages after parsing (linking, cards, embedding, search)
read these files and no parser's own output. A record holds only what its
source prints: anything generated, such as cards, glosses or the titles of
the 2003 Symposium's untitled projects, is kept apart, keyed by record id.

A record has these fields, always in this order:

- id: "<prefix>-YYYY-NNN" ("surg-2023-014", "expo-2024-001",
  "symposium-2009-001", "econ-2026-001"), or "nurj:<lead record>" for NURJ.
  Each parser keeps its ids stable across runs; cards, glosses, links and
  share numbers refer to them.
- source: the file it is in, one of SOURCES.
- kind: "grant", "presentation", "thesis" or "paper".
- year: the year of the grant, presentation or publication, or a thesis's
  graduating year.
- title: as printed, or None when the source prints none (the 2003
  Symposium's program, the 2010-11 October academic-year URG post). How an
  untitled record is shown is the frontend's choice.
- people: everyone the source names, students first, in the source's order.
  Each is {role, first, last, ...}: role is "student" (an awardee, presenter
  or author) or "advisor" (a faculty advisor, sponsor or thesis advisor).
  first holds every given name as printed, a preferred name in parentheses
  included ("Xinyuan (Joyce)"); it is "" for someone named by surname alone.
  Then whatever the source adds: a student's school, majors, major, level,
  notes or urg, an advisor's department or affiliation.
- abstract: the abstract or description, or None. A poster listed once per
  presenter has its distinct abstracts joined (see fold_listings).
- text: the work's full text, where the source has it and its parser reads
  it (the Computer Science theses so far), or None.
- url: where a visitor can check the record: the winners page, program or
  guide PDF, thesis page or PDF, or NURJ's own copy.
- page: the 1-based page of url the record starts on, or None.
- listings (Expo and Symposium, only for a poster listed more than once):
  each listing as the program prints it (see fold_listings).
- extra (only when the source has any): what only that source records, such
  as SURG's department headings or a thesis's department.

data/overrides.jsonl patches records as they are written (see write), so
rerunning a parser cannot erase a hand fix.
"""

import json
import re
import unicodedata

from pipeline.parse_expo import INSTITUTION
from pipeline.scrape_surg import DATA_DIR, PARTICLES, SUFFIXES, fold, split_name

RECORDS_DIR = DATA_DIR / "records"
SOURCES = ("surg", "ay_urg", "expo", "symposium", "theses", "nurj")
KINDS = ("grant", "presentation", "thesis", "paper")
ROLES = ("student", "advisor")
FIELDS = ("id", "source", "kind", "year", "title", "people", "abstract", "text", "url", "page", "listings", "extra")
REQUIRED = FIELDS[:10]
OVERRIDES = DATA_DIR / "overrides.jsonl"

# Word-trigram Jaccard between two abstracts at which they are one poster's.
# Listings of one poster score 0.54 and up; distinct projects stay under 0.3.
MIN_OVERLAP = 0.5
HONORIFIC = re.compile(r"^(?:dr|prof|professor)\.?\s+", re.I)
DEGREE = re.compile(r"^(?:ph\.?\s?d|m\.?d|j\.?d|m\.?s|m\.?a|m\.?b\.?a)\.?$", re.I)
# A doctorate written into a name, before or after it.
DEGREES = re.compile(r"(?:,\s*)?\b(?:Ph\.?\s?D|M\.D)\b\.?", re.I)
ADVISOR_SEPARATOR = re.compile(r"\s*(?:,\s*and\s+|,|;|\n|&|\band\b)\s*")


MIN_PREFIX = 3  # "Al" should not match every Alexander and Alice


def tokens(name: str) -> list[str]:
    name = unicodedata.normalize("NFKD", fold(name)).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z]+", name.casefold())


def surname_parts(last: str) -> set[str]:
    return {t for t in tokens(last) if t not in PARTICLES and t not in SUFFIXES and len(t) > 1}


def first_match(a: str, b: str) -> bool:
    """Whether two first names may be one person's: the same, or one a prefix
    of the other of at least MIN_PREFIX letters (Alex / Alexander)."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    x, y = sorted((ta[0], tb[0]), key=len)
    return x == y or (len(x) >= MIN_PREFIX and y.startswith(x))


def same_person(a: dict, b: dict) -> bool:
    """Whether two {first, last} likely name one person: a shared surname part
    and first names one of which is a prefix of the other (Josh / Joshua)."""
    return bool(surname_parts(a["last"]) & surname_parts(b["last"])) and first_match(a["first"], b["first"])


def words(s: str) -> list[str]:
    s = unicodedata.normalize("NFKD", fold(s)).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z0-9]+", s.casefold())


def trigrams(s: str) -> set[tuple[str, ...]]:
    w = words(s)
    return {tuple(w[i : i + 3]) for i in range(len(w) - 2)}


def record(id: str, source: str, kind: str, year: int, title: str | None, people: list[dict], abstract: str | None, url: str, page: int | None = None, listings: list[dict] | None = None, extra: dict | None = None, text: str | None = None) -> dict:
    """A record with its fields in order, leaving out empty listings and extra."""
    r = {"id": id, "source": source, "kind": kind, "year": year, "title": title, "people": people, "abstract": abstract, "text": text, "url": url, "page": page}
    if listings:
        r["listings"] = listings
    if extra := {k: v for k, v in (extra or {}).items() if v is not None}:
        r["extra"] = extra
    return r


def person(role: str, name: dict, **extras) -> dict:
    """{role, first, last, ...}: a source's {first, last, ...} with its role."""
    return {"role": role, **name, **{k: v for k, v in extras.items() if v is not None}}


def name_parts(name: str) -> dict | None:
    """One printed name as {first, last}, without "Dr.", "Professor" or a
    degree ("Steven Franconeri, PhD"); a surname alone has first "". None for
    a name that is only those, or an email address, which is not kept."""
    name = HONORIFIC.sub("", DEGREES.sub("", " ".join(name.split()))).strip(" ,")
    if not name or "@" in name:
        return None
    return {"first": "", "last": name} if len(name.split()) == 1 else split_name(name)


def advisors(line: str | None) -> list[dict]:
    """The advisors on an advisor line (see names)."""
    return names(line, "advisor")


def names(line: str | None, role: str) -> list[dict]:
    """The people a line of names names, as {role, first, last, affiliation?}.

    Lines name one or more people, separated by commas, semicolons, "and" or
    "&" ("Risa Brooks, Dacey, Ferrie"), each possibly followed by an
    affiliation in parentheses, as pipeline.parse_expo.affiliations writes
    them ("Joseph Contessa (Yale University)"). An item after a comma that
    names an institution ("Federal Reserve Bank of New York") is the previous
    person's affiliation, and a suffix ("Jr.", "II") or a degree ("MD") the
    end of the previous person's name.
    """
    if not line:
        return []
    # Separators inside parentheses belong to the affiliation.
    shielded = re.sub(r"\([^)]*\)", lambda m: m.group(0).replace(",", "\0").replace(";", "\1").replace("&", "\2").replace(" and ", " \3 "), line)
    out: list[dict] = []
    for part in ADVISOR_SEPARATOR.split(shielded):
        part = part.replace("\0", ",").replace("\1", ";").replace("\2", "&").replace(" \3 ", " and ").strip()
        if not part:
            continue
        m = re.fullmatch(r"(.*?)\s*\(([^)]*)\)", part, re.S)
        name, affiliation = (m.group(1), m.group(2).strip()) if m else (part, None)
        if out and not affiliation and INSTITUTION.search(name):
            out[-1].setdefault("affiliation", name)
            continue
        if out and name.lower().rstrip(".") in SUFFIXES:
            out[-1]["last"] += f" {name}"
            continue
        if out and DEGREE.match(name):
            if affiliation:
                out[-1].setdefault("affiliation", affiliation)
            continue
        if parts := name_parts(name):
            out.append(person(role, parts, affiliation=affiliation))
    return out


def fold_abstracts(abstracts: list[str]) -> str | None:
    """The distinct abstracts, joined; an abstract differing from an earlier
    one only in formatting (spacing, punctuation, word order) is dropped. A
    poster's listings often carry one abstract extracted slightly differently."""
    seen: dict[tuple[str, ...], str] = {}
    for a in abstracts:
        if a:
            seen.setdefault(tuple(sorted(words(a))), a)
    return "\n\n".join(dict.fromkeys(seen.values())) or None


def poster_groups(listings: list[dict]) -> list[list[dict]]:
    """Every listing in exactly one group of listings of the same poster,
    ordered by id: same year, and near-identical abstracts or the same title
    and advisor. A poster presented by several students may be listed once
    per presenter. Listings without titles (the 2003 Symposium's) are the
    same only by their abstracts."""
    parent = {e["id"]: e["id"] for e in listings}

    def find(x: str) -> str:
        while parent[x] != x:
            x = parent[x] = parent[parent[x]]
        return x

    by_year: dict[int, list[dict]] = {}
    for e in listings:
        by_year.setdefault(e["year"], []).append(e)
    for entries in by_year.values():
        grams = [trigrams(e["abstract"]) for e in entries]
        for i, a in enumerate(entries):
            for j in range(i):
                b = entries[j]
                same_listing = a["advisor"] and a["title"] and words(a["title"]) == words(b["title"] or "") and words(a["advisor"]) == words(b["advisor"] or "")
                union = grams[i] | grams[j]
                if same_listing or (union and len(grams[i] & grams[j]) / len(union) >= MIN_OVERLAP):
                    parent[find(a["id"])] = find(b["id"])

    groups: dict[str, list[dict]] = {}
    for e in sorted(listings, key=lambda e: e["id"]):
        groups.setdefault(find(e["id"]), []).append(e)
    return list(groups.values())


LISTING_EXTRAS = ("format", "subjects", "forager_id", "abstract_source", "project")


def fold_listings(source: str, listings: list[dict]) -> list[dict]:
    """Expo or Symposium listings ({id, year, presenters, advisor, title,
    abstract, page, source, ...}, as pipeline.parse_expo gives them) as one
    record per poster (see poster_groups).

    A poster's record takes its id, title, page, url and extras from its first
    listing; its people are every listing's presenters, then every listing's
    advisors, each once (by first given name and surname, as first printed); its abstract is the listings' distinct abstracts
    (see fold_abstracts). A poster listed more than once also keeps every
    listing, without year and source, under listings, which is how the next
    run keeps their ids (see expand_listings)."""
    out = []
    for group in poster_groups(listings):
        first = group[0]
        people: list[dict] = []
        seen = set()
        for role, found in [("student", p) for e in group for p in e["presenters"]] + [("advisor", a) for e in group for a in advisors(e["advisor"])]:
            # "Claudia M. Haase" on one listing is "Claudia Haase" on another.
            key = (role, tuple(words(found["first"])[:1]), tuple(words(found["last"])))
            if key not in seen:
                seen.add(key)
                people.append(found if role == "advisor" else person("student", found))
        out.append(record(
            first["id"], source, "presentation", first["year"], first["title"], people,
            fold_abstracts([e["abstract"] for e in group]), first["source"], first["page"],
            listings=[{k: v for k, v in e.items() if k not in ("year", "source")} for e in group] if len(group) > 1 else None,
            extra={k: first.get(k) for k in LISTING_EXTRAS},
        ))
    return out


def expand_listings(records: list[dict]) -> list[dict]:
    """The listings Expo or Symposium records were folded from, as
    {id, year, title, presenters, page}, for keeping their ids across runs."""
    out = []
    for r in records:
        if "listings" in r:
            out += [{**e, "year": r["year"]} for e in r["listings"]]
        else:
            presenters = [{k: v for k, v in p.items() if k != "role"} for p in r["people"] if p["role"] == "student"]
            out.append({"id": r["id"], "year": r["year"], "title": r["title"], "presenters": presenters, "page": r["page"]})
    return out


def merge_patch(target, patch):
    """RFC 7396: patch's keys replace target's, recursively; null deletes a key."""
    if not isinstance(patch, dict):
        return patch
    merged = dict(target) if isinstance(target, dict) else {}
    for k, v in patch.items():
        if v is None:
            merged.pop(k, None)
        else:
            merged[k] = merge_patch(merged.get(k), v)
    return merged


def check(r: dict, source: str) -> None:
    """Raise if a record is not in the shape the module docstring gives."""
    if list(r)[: len(REQUIRED)] != list(REQUIRED) or not set(r) <= set(FIELDS):
        raise ValueError(f"{r.get('id')}: fields {list(r)}")
    if r["source"] != source or r["kind"] not in KINDS:
        raise ValueError(f"{r['id']}: source {r['source']!r}, kind {r['kind']!r}")
    if r["text"] is not None and (not isinstance(r["text"], str) or not r["text"]):
        raise ValueError(f"{r['id']}: text {r['text']!r:.40}")
    if not isinstance(r["year"], int) or not isinstance(r["url"], str) or not r["url"]:
        raise ValueError(f"{r['id']}: year {r['year']!r}, url {r['url']!r}")
    if r["title"] is not None and (not isinstance(r["title"], str) or not r["title"].strip()):
        raise ValueError(f"{r['id']}: title {r['title']!r}")
    for p in r["people"]:
        if p.get("role") not in ROLES or not isinstance(p.get("first"), str) or not p.get("last"):
            raise ValueError(f"{r['id']}: person {p}")


def write(source: str, records: list[dict]) -> list[dict]:
    """Apply the overrides for data/records/<source>.jsonl, check every
    record and write them sorted by id. Returns the records written."""
    name = f"records/{source}.jsonl"
    by_id = {r["id"]: r for r in records}
    if len(by_id) != len(records):
        raise ValueError(f"{source}: duplicate ids")
    for o in map(json.loads, OVERRIDES.open()):
        if o["file"] == name:
            by_id[o["id"]] = merge_patch(by_id[o["id"]], o["patch"])
    out = [by_id[k] for k in sorted(by_id)]
    for r in out:
        check(r, source)
    RECORDS_DIR.mkdir(exist_ok=True)
    path = RECORDS_DIR / f"{source}.jsonl"
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out))
    print(f"wrote {len(out)} records to {path}")
    return out


def load(*sources: str) -> list[dict]:
    """The records of the given sources (all by default), in SOURCES order."""
    out = []
    for source in sources or SOURCES:
        path = RECORDS_DIR / f"{source}.jsonl"
        if path.exists():
            out += [json.loads(line) for line in path.open()]
    return out

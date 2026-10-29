"""Split the recovered NURJ print editions into papers.

The pages come from pipeline.scrape_issuu (data/issuu_pages.json), or, for a
volume whose captures have no text, from a transcription of its page scans,
one file per page, data/issuu_transcribed/<slug>/page_<n>.json holding
{"page": n, "blocks": [[line, ...], ...]}; page n is section n - 1, and
records from a transcription have transcribed set. Which
blocks of which pages make up each paper was read off the pages by hand and
is recorded per volume in data/issuu_articles/<slug>.json:

    {
      "slug": "nurj_v7_2011-2012",
      "running_heads": ["RESEARCH", "NORTHWESTERN UNDERGRADUATE RESEARCH JOURNAL"],
      "items": [
        {
          "kind": "research",           # research, feature, letter, front matter, back matter or other
          "title": "...",               # as printed
          "authors": ["..."],           # as printed
          "department": "..." | null,   # as printed in the contents or on the paper
          "advisors": ["..."],          # as printed, if the volume names them
          "printed_pages": "8-12" | null,
          "spans": [["7.0", "11.3"]],   # inclusive ranges of section.block, in reading order
          "notes": "..."                # anything a reader of the record should know
        }
      ]
    }

Block references are "<section>.<block>", the indices `show` prints. Running
heads are lines repeated as page furniture (headers, footers, the journal's
name); they are dropped when they are the first or last line of a block, as
are blocks of a lone page number.

Commands:

- show SLUG [FROM [TO]] [--brief]: print the volume's sections FROM..TO with
  each block's reference, for reading; --brief prints only each block's
  first two lines.
- check [SLUG ...]: validate the index files. Every block must belong to
  exactly one item or be page furniture, spans must be in order and in
  range, every running head must match some line, and every title, author,
  department and advisor must occur in the volume's text (ignoring case, spacing, punctuation and line-end hyphens).
- build: write data/issuu_papers.json, one record per item with its text.
  Within a block, lines are joined with spaces, and a word broken across a
  line end with a hyphen is rejoined when the volume also writes it unbroken.
  Blocks are joined into one paragraph when the first does not end a
  sentence and the next starts in lower case (a column or page break),
  with no space after a block of one capital letter that makes a word with
  the next block's first (a drop cap),
  otherwise into separate paragraphs.

Usage: uv run python -m pipeline.issuu_papers {show,check,build} ...
"""

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter

from pipeline.scrape_surg import DATA_DIR

INDEX_DIR = DATA_DIR / "issuu_articles"
TRANSCRIBED_DIR = DATA_DIR / "issuu_transcribed"
KINDS = {"research", "feature", "letter", "front matter", "back matter", "other"}
PAGE_NUMBER = re.compile(r"\s*\d{1,3}\s*")


def load_pages() -> dict[str, dict]:
    """The volumes' pages; a volume whose captures have no text uses its
    transcription from the archived page images, if there is one."""
    volumes = {v["slug"]: v for v in json.loads((DATA_DIR / "issuu_pages.json").read_text())["volumes"]}
    for folder in sorted(p for p in TRANSCRIBED_DIR.glob("*") if p.is_dir()):
        v = volumes[folder.name]
        if any(p["blocks"] for p in v["pages"]):
            continue
        pages = {t["page"]: t["blocks"] for t in (json.loads(f.read_text()) for f in folder.glob("page_*.json"))}
        last = max(len(v["scans"]), max(pages, default=0))
        volumes[folder.name] = v | {"pages": [{"section": n - 1, "blocks": pages.get(n, [])} for n in range(1, last + 1)], "transcribed": True}
    return volumes


def show(volume: dict, first: int, last: int, brief: bool = False) -> None:
    for page in volume["pages"][first : last + 1]:
        print(f"===== section {page['section']}")
        for b, lines in enumerate(page["blocks"]):
            if brief:
                more = f" ... (+{len(lines) - 2} lines)" if len(lines) > 2 else ""
                print(f"[{page['section']}.{b}] " + " / ".join(line[:100] for line in lines[:2]) + more)
            else:
                print(f"[{page['section']}.{b}] " + "\n        ".join(lines))


def ref(s: str) -> tuple[int, int]:
    m = re.fullmatch(r"(\d+)\.(\d+)", s)
    if not m:
        raise ValueError(f"bad block reference {s!r}")
    return int(m.group(1)), int(m.group(2))


def all_blocks(volume: dict) -> list[tuple[int, int]]:
    return [(p["section"], b) for p in volume["pages"] for b in range(len(p["blocks"]))]


def span_blocks(volume: dict, span: list[str]) -> list[tuple[int, int]]:
    order = all_blocks(volume)
    start, end = ref(span[0]), ref(span[1])
    if start not in order or end not in order:
        raise ValueError(f"span {span} is out of range")
    i, j = order.index(start), order.index(end)
    if i > j:
        raise ValueError(f"span {span} runs backwards")
    return order[i : j + 1]


def block(volume: dict, at: tuple[int, int]) -> list[str]:
    return volume["pages"][at[0]]["blocks"][at[1]]


def furniture_free(lines: list[str], heads: set[str]) -> list[str]:
    lines = list(lines)
    while lines and lines[0].strip() in heads:
        lines.pop(0)
    while lines and lines[-1].strip() in heads:
        lines.pop()
    if len(lines) == 1 and PAGE_NUMBER.fullmatch(lines[0]):
        return []
    return lines


def words(s: str) -> list[str]:
    s = re.sub(r"['\u2018\u2019\u02bc`\u00b4]", "", s)  # O'Brien, O\u2019Brien and OBrien alike
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"-\s*\n\s*", "", s)
    return re.findall(r"[a-z0-9]+", s.casefold())


def volume_text(volume: dict) -> str:
    return "\n".join(line for p in volume["pages"] for b in p["blocks"] for line in b)


def check(volume: dict, index: dict) -> list[str]:
    problems = []
    heads = set(index.get("running_heads", []))
    owner: dict[tuple[int, int], int] = {}
    for n, item in enumerate(index["items"]):
        where = f"item {n} ({(item.get('title') or '')[:40]!r})"
        if item.get("kind") not in KINDS:
            problems.append(f"{where}: kind {item.get('kind')!r} not one of {sorted(KINDS)}")
        for span in item.get("spans", []):
            try:
                blocks = span_blocks(volume, span)
            except ValueError as e:
                problems.append(f"{where}: {e}")
                continue
            for at in blocks:
                if at in owner:
                    problems.append(f"{where}: block {at[0]}.{at[1]} is also in item {owner[at]}")
                owner[at] = n
    for at in all_blocks(volume):
        if at not in owner and furniture_free(block(volume, at), heads):
            problems.append(f"block {at[0]}.{at[1]} belongs to no item: {' / '.join(block(volume, at))[:80]!r}")

    lines = {line.strip() for p in volume["pages"] for b in p["blocks"] for line in b}
    for head in heads - lines:
        problems.append(f"running head {head!r} matches no line")

    text = " ".join(words(volume_text(volume)))
    for n, item in enumerate(index["items"]):
        values = [item.get("title"), item.get("department"), *item.get("authors", []), *item.get("advisors", [])]
        for v in values:
            if v and " ".join(words(v)) not in text:
                problems.append(f"item {n}: {v!r} does not occur in the volume's text")
    return problems


def paragraphs(blocks: list[list[str]], vocabulary: set[str]) -> str:
    """The text of some blocks, as described in the module docstring."""

    def join_lines(lines: list[str]) -> str:
        out = ""
        for line in lines:
            line = line.strip()
            m = re.search(r"(\w+)-$", out)
            n = re.match(r"(\w+)", line)
            if m and n and (m.group(1) + n.group(1)).casefold() in vocabulary:
                out = out[:-1] + line
            elif re.fullmatch(r"[A-Z]", out) and n and (out + n.group(1)).casefold() in vocabulary:
                out += line  # a drop cap on its own line
            else:
                out = f"{out} {line}" if out else line
        return out

    paras: list[str] = []
    for b in blocks:
        t = join_lines(b)
        if not t:
            continue
        if paras and not re.search(r"[.!?:\"')\]]$", paras[-1]) and re.match(r"[a-z]", t):
            m = re.search(r"(\w+)-$", paras[-1])
            n = re.match(r"(\w+)", t)
            if m and n and (m.group(1) + n.group(1)).casefold() in vocabulary:
                paras[-1] = paras[-1][:-1] + t
            elif re.fullmatch(r"[A-Z]", paras[-1]) and n and (paras[-1] + n.group(1)).casefold() in vocabulary:
                paras[-1] += t  # a drop cap, set as its own block
            else:
                paras[-1] += " " + t
        else:
            paras.append(t)
    return "\n\n".join(paras)


def build(volumes: dict[str, dict]) -> list[dict]:
    papers = []
    for path in sorted(INDEX_DIR.glob("*.json")):
        index = json.loads(path.read_text())
        volume = volumes[index["slug"]]
        if problems := check(volume, index):
            raise SystemExit(f"{path}: {len(problems)} problems; run check")
        heads = set(index.get("running_heads", []))
        vocabulary = {w.casefold() for w in re.findall(r"\w+", volume_text(volume))}
        for n, item in enumerate(index["items"], 1):
            blocks = [furniture_free(block(volume, at), heads) for span in item["spans"] for at in span_blocks(volume, span)]
            sections = sorted({at[0] for span in item["spans"] for at in span_blocks(volume, span)})
            papers.append({
                "id": f"issuu-{volume['slug']}-{n:02d}",
                "volume": volume["label"],
                "slug": volume["slug"],
                **{k: item.get(k) for k in ("kind", "title", "authors", "department", "advisors", "printed_pages", "notes")},
                "sections": [sections[0], sections[-1]] if sections else None,
                "source": volume["capture_url"],
                "transcribed": volume.get("transcribed", False),
                "text": paragraphs(blocks, vocabulary),
            })
    return papers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("show")
    p.add_argument("slug")
    p.add_argument("first", nargs="?", type=int, default=0)
    p.add_argument("last", nargs="?", type=int)
    p.add_argument("--brief", action="store_true", help="only each block's first two lines")
    p = sub.add_parser("check")
    p.add_argument("slugs", nargs="*")
    sub.add_parser("build")
    args = parser.parse_args()

    volumes = load_pages()
    if args.command == "show":
        v = volumes[args.slug]
        show(v, args.first, len(v["pages"]) - 1 if args.last is None else args.last, args.brief)
    elif args.command == "check":
        paths = [INDEX_DIR / f"{s}.json" for s in args.slugs] or sorted(INDEX_DIR.glob("*.json"))
        bad = 0
        for path in paths:
            index = json.loads(path.read_text())
            problems = check(volumes[index["slug"]], index)
            bad += bool(problems)
            print(f"{path.name}: {len(index['items'])} items, {len(problems)} problems")
            for line in problems:
                print("  " + line)
        sys.exit(1 if bad else 0)
    else:
        papers = build(volumes)
        out = DATA_DIR / "issuu_papers.json"
        out.write_text(json.dumps(papers, indent=1, ensure_ascii=False) + "\n")
        kinds = Counter(p["kind"] for p in papers)
        print(f"{len(papers)} items ({', '.join(f'{v} {k}' for k, v in kinds.most_common())}) -> {out}")


if __name__ == "__main__":
    main()

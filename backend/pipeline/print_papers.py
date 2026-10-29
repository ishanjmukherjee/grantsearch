"""Turn the NURJ print editions and documents into papers.

Volumes are print editions recovered from Issuu (pipeline.scrape_issuu,
data/issuu_pages.json) and the print editions and per-post documents
downloaded as files (pipeline.extract_documents, data/document_pages.json):
per page (a section) the text blocks, each a list of lines.

Pages are also read from images where a volume's text does not reach:
data/transcribed/<slug>/page_<n>.json, holding {"page": n, "blocks":
[[line, ...], ...]}, is a transcription of page n (section n - 1) from its
image. It replaces a page that has no text, and on a page that has text it
adds the text only an image there shows; an empty list of blocks records that
the page was looked at. Its optional "replace", {"<block>": [line, ...]},
puts the page image's reading in place of a block whose text layer is
garbled (a font that maps its glyphs to the wrong characters). A page of a downloaded file must be transcribed if
it has no text, and looked at if images cover a twentieth of it or more.

A print edition is split into papers by hand: which blocks of which pages
make up each item was read off the pages and is recorded per volume in
data/print_articles/<slug>.json:

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
are blocks of nothing but page numbers.

Commands:

- show SLUG [FROM [TO]] [--brief]: print the volume's sections FROM..TO with
  each block's reference, for reading; --brief prints only each block's
  first two lines.
- render SLUG SECTION [--clip X0 Y0 X1 Y1]: write an image of a page (or of
  the part the fractions of its width and height give) to data/cache/render/
  and print its path, for reading.
- check [SLUG ...]: validate the index files and the documents' pages. Every
  block must belong to exactly one item or be page furniture, spans must be
  in order and in range, every running head must match some line, every
  title, author, department and advisor must occur in the volume's text
  (ignoring case, spacing, punctuation and line-end hyphens), and every page
  that must be transcribed or looked at must have its transcription file.
- build: write data/print_papers.json, one record per item of a print
  edition with its text, and data/document_texts.json, one record per
  document (a file attached to a NURJ post or Arch record) with its text.
  Within a block, lines are joined with spaces, and a word broken across a
  line end with a hyphen is rejoined when the volume also writes it unbroken.
  Blocks are joined into one paragraph when the first does not end a
  sentence and the next starts in lower case (a column or page break),
  with no space after a block of one capital letter that makes a word with
  the next block's first (a drop cap),
  otherwise into separate paragraphs.

Usage: uv run python -m pipeline.print_papers {show,render,check,build} ...
"""

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter

import pymupdf

from pipeline.scrape_surg import DATA_DIR

INDEX_DIR = DATA_DIR / "print_articles"
TRANSCRIBED_DIR = DATA_DIR / "transcribed"
RENDER_DIR = DATA_DIR / "cache" / "render"
KINDS = {"research", "feature", "letter", "front matter", "back matter", "other"}
PAGE_NUMBER = re.compile(r"\s*\d{1,3}\s*")
# A page of a downloaded file whose images cover this share of it must be
# looked at for text only the images show (a figure, screenshot or table set
# as a picture can hold text on any page, however much text it has).
LOOK_COVER = 0.05
RENDER_PIXELS = 2000  # the longer side of a rendered page


def load_pages() -> dict[str, dict]:
    """Every volume with its pages, transcriptions applied (see the module
    docstring); a volume lists the sections it has transcriptions for."""
    volumes = {v["slug"]: v | {"source": "issuu"} for v in json.loads((DATA_DIR / "issuu_pages.json").read_text())["volumes"]}
    volumes |= {v["slug"]: v | {"source": "file"} for v in json.loads((DATA_DIR / "document_pages.json").read_text())["volumes"]}
    for v in volumes.values():
        v["transcribed"] = []
        folder = TRANSCRIBED_DIR / v["slug"]
        if not folder.is_dir():
            continue
        found = {t["page"]: t for t in (json.loads(f.read_text()) for f in folder.glob("page_*.json"))}
        pages = {p["section"]: p for p in v["pages"]}
        for n in range(1, max(len(v.get("scans", [])), max(found, default=0), len(v["pages"])) + 1):
            pages.setdefault(n - 1, {"section": n - 1, "blocks": []})
        for n, t in sorted(found.items()):
            page = pages[n - 1]
            blocks = list(page["blocks"])
            for b, lines in t.get("replace", {}).items():
                if not 0 <= int(b) < len(blocks):
                    raise SystemExit(f"{folder}/page_{n}.json replaces block {b}, which page {n} does not have")
                blocks[int(b)] = lines
            page["blocks"] = blocks + t["blocks"]
            v["transcribed"].append(n - 1)
        v["pages"] = [pages[s] for s in sorted(pages)]
    return volumes


def chars(page: dict) -> int:
    return sum(len(line) for b in page["blocks"] for line in b)


def to_read(volume: dict) -> list[int]:
    """Sections of a downloaded file that must be transcribed or looked at."""
    if volume["source"] != "file":
        return []
    return [p["section"] for p in volume["pages"] if not p["blocks"] or p.get("image_cover", 0) >= LOOK_COVER]


def render(volume: dict, section: int, clip: list[float] | None) -> str:
    page = next(p for p in volume["pages"] if p["section"] == section)
    if volume["source"] == "issuu":
        path = DATA_DIR / volume["scans"][section]
    elif page.get("image"):
        path = DATA_DIR / page["image"]
    elif volume["format"] == "pdf":
        path = DATA_DIR / volume["files"][0]
    else:
        raise SystemExit(f"{volume['slug']} section {section} has no image to render")
    with pymupdf.open(path) as doc:
        p = doc[section if volume.get("format") == "pdf" else 0]
        rect = p.rect
        if clip:
            x0, y0, x1, y1 = clip
            rect = pymupdf.Rect(rect.x0 + x0 * rect.width, rect.y0 + y0 * rect.height, rect.x0 + x1 * rect.width, rect.y0 + y1 * rect.height)
        zoom = RENDER_PIXELS / max(rect.width, rect.height)
        pix = p.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=rect)
    out = RENDER_DIR / volume["slug"] / (f"s{section}" + ("-" + "-".join(f"{c:g}" for c in clip) if clip else "") + ".png")
    out.parent.mkdir(parents=True, exist_ok=True)
    pix.save(out)
    return str(out)


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
    if lines and all(PAGE_NUMBER.fullmatch(line) for line in lines):
        return []
    return lines


def words(s: str) -> list[str]:
    s = re.sub(r"['\u2018\u2019\u02bc`\u00b4]", "", s)  # O'Brien, O\u2019Brien and OBrien alike
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"-\s*\n\s*", "", s)
    return re.findall(r"[a-z0-9]+", s.casefold())


def volume_text(volume: dict) -> str:
    return "\n".join(line for p in volume["pages"] for b in p["blocks"] for line in b)


def check_reading(volume: dict) -> list[str]:
    return [
        f"section {s} (page {s + 1}) {'has no text' if not p['blocks'] else 'has text in images'}: add {TRANSCRIBED_DIR.relative_to(DATA_DIR)}/{volume['slug']}/page_{s + 1}.json"
        for s in to_read(volume)
        if s not in volume["transcribed"]
        for p in [volume["pages"][s]]
    ]


def check(volume: dict, index: dict) -> list[str]:
    problems = check_reading(volume)
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


def vocabulary(volume: dict) -> set[str]:
    return {w.casefold() for w in re.findall(r"\w+", volume_text(volume))}


def build_print(volumes: dict[str, dict]) -> list[dict]:
    """One record per item of each indexed print edition."""
    papers = []
    for path in sorted(INDEX_DIR.glob("*.json")):
        index = json.loads(path.read_text())
        volume = volumes[index["slug"]]
        if problems := check(volume, index):
            raise SystemExit(f"{path}: {len(problems)} problems; run check")
        heads = set(index.get("running_heads", []))
        words_seen = vocabulary(volume)
        for n, item in enumerate(index["items"], 1):
            blocks = [furniture_free(block(volume, at), heads) for span in item["spans"] for at in span_blocks(volume, span)]
            sections = sorted({at[0] for span in item["spans"] for at in span_blocks(volume, span)})
            papers.append({
                "id": f"issuu-{volume['slug']}-{n:02d}" if volume["source"] == "issuu" else f"{volume['slug']}-{n:02d}",
                "volume": volume["label"],
                "slug": volume["slug"],
                **{k: item.get(k) for k in ("kind", "title", "authors", "department", "advisors", "printed_pages", "notes")},
                "sections": [sections[0], sections[-1]] if sections else None,
                "source": volume["capture_url"] if volume["source"] == "issuu" else volume["source_url"],
                "transcribed": any(s in volume["transcribed"] for s in sections),
                "text": paragraphs(blocks, words_seen),
            })
    return papers


def build_documents(volumes: dict[str, dict]) -> list[dict]:
    """One record per document: its whole text, lone page numbers dropped."""
    docs = []
    for v in volumes.values():
        if v["source"] != "file" or v["kind"] != "document":
            continue
        if problems := check_reading(v):
            raise SystemExit(f"{v['slug']}: {len(problems)} problems; run check")
        blocks = [furniture_free(b, set()) for p in v["pages"] for b in p["blocks"]]
        docs.append({
            "id": v["slug"],
            "label": v["label"],
            **{k: v[k] for k in ("format", "files", "source_url", "scribd_id", "doi", "nurj_records", "nurj_title", "copies")},
            "pages": len(v["pages"]),
            "transcribed": v["transcribed"],
            "text": paragraphs(blocks, vocabulary(v)),
        })
    return docs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("show")
    p.add_argument("slug")
    p.add_argument("first", nargs="?", type=int, default=0)
    p.add_argument("last", nargs="?", type=int)
    p.add_argument("--brief", action="store_true", help="only each block's first two lines")
    p = sub.add_parser("render")
    p.add_argument("slug")
    p.add_argument("section", type=int)
    p.add_argument("--clip", nargs=4, type=float, metavar=("X0", "Y0", "X1", "Y1"), help="fractions of the page's width and height")
    p = sub.add_parser("check")
    p.add_argument("slugs", nargs="*")
    sub.add_parser("build")
    args = parser.parse_args()

    volumes = load_pages()
    if args.command == "show":
        v = volumes[args.slug]
        show(v, args.first, len(v["pages"]) - 1 if args.last is None else args.last, args.brief)
    elif args.command == "render":
        print(render(volumes[args.slug], args.section, args.clip))
    elif args.command == "check":
        indexed = {p.stem for p in INDEX_DIR.glob("*.json")}
        slugs = args.slugs or sorted(indexed) + sorted(s for s, v in volumes.items() if v["source"] == "file" and s not in indexed)
        bad = 0
        for slug in slugs:
            if slug in indexed:
                index = json.loads((INDEX_DIR / f"{slug}.json").read_text())
                problems = check(volumes[slug], index)
                label = f"{slug}: {len(index['items'])} items"
            else:
                problems = check_reading(volumes[slug])
                label = f"{slug}: document" if volumes[slug]["kind"] == "document" else f"{slug}: not indexed"
                if volumes[slug]["kind"] != "document":
                    problems.append(f"no index at {INDEX_DIR.relative_to(DATA_DIR)}/{slug}.json")
            bad += bool(problems)
            if problems or args.slugs:
                print(f"{label}, {len(problems)} problems")
                for line in problems:
                    print("  " + line)
        print(f"{len(slugs)} volumes checked, {bad} with problems")
        sys.exit(1 if bad else 0)
    else:
        for name, records in (("print_papers.json", build_print(volumes)), ("document_texts.json", build_documents(volumes))):
            out = DATA_DIR / name
            out.write_text(json.dumps(records, indent=1, ensure_ascii=False) + "\n")
            kinds = Counter(r.get("kind", r.get("format")) for r in records)
            print(f"{len(records)} records ({', '.join(f'{v} {k}' for k, v in kinds.most_common())}) -> {out}")


if __name__ == "__main__":
    main()

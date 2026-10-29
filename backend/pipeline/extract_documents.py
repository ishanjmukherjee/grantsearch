"""Extract the text of the NURJ documents downloaded as files, page by page.

The documents are:

- the four NURJ Paper print editions that exist only as PDFs downloaded from
  Scribd (2021-22 to 2024-25). The earlier ones are read from Issuu instead
  (pipeline.scrape_issuu); their Scribd PDFs are left out here.
- the papers, posters and slides attached to NURJ posts: files downloaded from
  Scribd and from Northwestern's Arch repository (listed in
  data/raw/nurj/manual_downloads.tsv), and the PDFs the NURJ site hosts
  (data/nurj.json). Scribd documents deleted since are kept only as what
  their embeds still serve: the text of each page (text.txt) and page images,
  which for these documents are blank placeholders. Embeds of documents made
  private are the same files as Arch downloads and are left out, as are audio
  and video files.

Each document becomes a volume in data/document_pages.json in the form
data/issuu_pages.json uses, which pipeline.print_papers reads: per page (a
section) its text blocks, each a list of lines.

- PDF: the text blocks PyMuPDF finds, in the file's order, with typographic
  ligatures (fi, fl, ff ...) written as their letters. Each section also
  records the share of its page that images cover, a hint that the page has
  text only an image shows.
- DOCX: one section; a block per paragraph and per table row (cells joined
  with " | "), then the footnotes and endnotes, each marked "[n]" as their
  references are. Headers, footers and images are not read.
- Embed: a section per page, its blocks the page's text split at blank
  lines; a page image that is not blank is kept for reading.
- Images (a PNG): one section per image, with no text.

Sections without text are listed in needs_reading. Files with identical bytes
are one volume listing every copy.

Usage: uv run python -m pipeline.extract_documents
"""

import csv
import hashlib
import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pymupdf

from pipeline.scrape_nurj import site_key
from pipeline.scrape_surg import DATA_DIR, LIGATURES

NURJ_DIR = DATA_DIR / "raw" / "nurj"
# Scribd id -> label of the print editions read from their PDFs.
PRINT_EDITIONS = {
    "850345046": "2021-2022 (Vol. 17)",
    "683622799": "2022-2023 (Vol. 18)",
    "813343543": "2023-2024 (Vol. 19)",
    "978781219": "2024-2025 (Vol. 20)",
}
# Print editions that Issuu covers (pipeline.scrape_issuu), not read here.
ISSUU_EDITIONS = {"496041514", "563079934", "998154888", "998155300", "998156382", "998156518", "998156745", "998156952", "998157373"}
MEDIA = {".mp4", ".mov", ".mp3"}
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def pdf_pages(path: Path) -> list[dict]:
    pages = []
    with pymupdf.open(path) as doc:
        for i, page in enumerate(doc):
            blocks = []
            for b in page.get_text("dict")["blocks"]:
                if b["type"] != 0:
                    continue
                lines = ["".join(s["text"] for s in line["spans"]).rstrip().translate(LIGATURES) for line in b["lines"]]
                if lines := [line for line in lines if line.strip()]:
                    blocks.append(lines)
            area = abs(page.rect)
            covered = sum(abs(pymupdf.Rect(im["bbox"]) & page.rect) for im in page.get_image_info())
            pages.append({"section": i, "blocks": blocks, "image_cover": round(min(covered / area, 1.0), 2) if area else 0.0})
    return pages


def docx_text(el) -> list[str]:
    """The lines of a paragraph-like element: runs' text, tabs, breaks and note references."""
    out = [""]
    for node in el.iter():
        tag = node.tag
        if tag == f"{W}t":
            out[-1] += node.text or ""
        elif tag == f"{W}tab":
            out[-1] += "\t"
        elif tag in (f"{W}br", f"{W}cr"):
            out.append("")
        elif tag in (f"{W}footnoteReference", f"{W}endnoteReference"):
            out[-1] += f"[{node.get(f'{W}id')}]"
    return [line.rstrip() for line in out if line.strip()]


def docx_pages(path: Path) -> list[dict]:
    blocks = []
    with zipfile.ZipFile(path) as z:
        body = ElementTree.fromstring(z.read("word/document.xml")).find(f"{W}body")
        for child in body:
            if child.tag == f"{W}p":
                if lines := docx_text(child):
                    blocks.append(lines)
            elif child.tag == f"{W}tbl":
                for row in child.iter(f"{W}tr"):
                    cells = [" ".join(docx_text(c)) for c in row.iter(f"{W}tc")]
                    if any(cells):
                        blocks.append([" | ".join(cells)])
        for part, tag in (("word/footnotes.xml", "footnote"), ("word/endnotes.xml", "endnote")):
            if part not in z.namelist():
                continue
            for note in ElementTree.fromstring(z.read(part)).iter(f"{W}{tag}"):
                if note.get(f"{W}type") in ("separator", "continuationSeparator", "continuationNotice"):
                    continue
                for p in note.iter(f"{W}p"):
                    if lines := docx_text(p):
                        blocks.append([f"[{note.get(f'{W}id')}] " + lines[0], *lines[1:]])
    return [{"section": 0, "blocks": blocks, "image_cover": 0.0}]


def image_pages(paths: list[Path]) -> list[dict]:
    return [{"section": i, "blocks": [], "image_cover": 1.0, "image": str(p.relative_to(DATA_DIR))} for i, p in enumerate(paths)]


def embed_text(path: Path) -> dict[int, list[list[str]]]:
    """The text an embed served, by page: blocks split at blank lines."""
    parts = re.split(r"^--- page (\d+) ---$", path.read_text(), flags=re.MULTILINE)
    pages = {}
    for n, body in zip(parts[1::2], parts[2::2]):
        blocks = [[line.rstrip() for line in chunk.splitlines() if line.strip()] for chunk in re.split(r"\n\s*\n", body)]
        pages[int(n)] = [b for b in blocks if b]
    return pages


def blank(path: Path) -> bool:
    """Whether an image is a single colour (Scribd serves white placeholders)."""
    pix = pymupdf.Pixmap(str(path))
    return len(set(pix.samples)) <= 1


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def documents() -> list[dict]:
    """Every document to extract, before merging identical files."""
    docs = []
    rows = list(csv.DictReader((NURJ_DIR / "manual_downloads.tsv").open(), delimiter="\t"))
    arch_count: dict[str, int] = {}
    for r in rows:
        path = NURJ_DIR / r["path"]
        ident = r["scribd_id_or_doi"]
        common = {"source_url": r["source_url"], "nurj_records": [r["nurj_record"]] if r["nurj_record"] else [], "nurj_title": r["nurj_title"] or None}
        if r["source"] == "scribd" and r["kind"] == "rendered embed; original private":
            continue  # the same files as Arch downloads
        if r["source"] == "scribd" and r["kind"] == "rendered embed; original deleted":
            source = json.loads((path / "source.json").read_text())
            folder = path / "images"
            found = {int(p.name.split("-")[0]): p for p in (folder.iterdir() if folder.exists() else []) if re.fullmatch(r"\d+-\w+\.(png|jpe?g)", p.name)}
            text = embed_text(path / "text.txt")
            pages = []
            for i in range(source["page_count"]):
                image = found.get(i + 1)
                usable = image is not None and not blank(image)
                pages.append({
                    "section": i,
                    "blocks": text.get(i + 1, []),
                    "image_cover": 1.0 if usable else 0.0,
                    "image": str(image.relative_to(DATA_DIR)) if usable else None,
                })
            docs.append({"slug": f"scribd-{ident}", "label": r["nurj_title"], "kind": "document", "format": "embed", "files": [str((path / "text.txt").relative_to(DATA_DIR))] + [str(p.relative_to(DATA_DIR)) for p in (found[n] for n in sorted(found))], "scribd_id": ident, "doi": None, **common, "pages": pages})
            continue
        if path.suffix.lower() in MEDIA or ident in ISSUU_EDITIONS:
            continue
        if r["source"] == "scribd":
            slug, kind, label = f"scribd-{ident}", "document", r["nurj_title"]
            if ident in PRINT_EDITIONS:
                kind, label = "print edition", PRINT_EDITIONS[ident]
            ids = {"scribd_id": ident, "doi": None}
        else:
            n = arch_count[ident] = arch_count.get(ident, 0) + 1
            slug = f"arch-{ident.split('/')[-1]}" + (f"-{n}" if n > 1 else "")
            kind, label, ids = "document", r["nurj_title"], {"scribd_id": None, "doi": ident}
        docs.append({"slug": slug, "label": label, "kind": kind, "format": path.suffix.lower().lstrip("."), "files": [str(path.relative_to(DATA_DIR))], **ids, **common, "pages": None})

    nurj = json.loads((DATA_DIR / "nurj.json").read_text())
    media_post = {m["source_url"]: m["post"] for m in nurj["media"]}
    titles = {r["wp"]["id"]: r["title"] for r in nurj["posts"] + nurj["pages"]}
    record_id = {r["wp"]["id"]: r["id"] for r in nurj["posts"] + nurj["pages"]}
    for url, rel in nurj["files"].items():
        linking = [r["id"] for r in nurj["posts"] + nurj["pages"] if any(site_key(u) == site_key(url) for b in r["blocks"] for u in [b.get("url")] + [x["url"] for x in b.get("links", [])] if u)]
        if (post := media_post.get(url)) and record_id.get(post) not in linking:
            linking.append(record_id[post])
        label = titles.get(media_post.get(url)) or Path(rel).stem
        docs.append({"slug": "site-" + slugify(Path(rel).stem), "label": label, "kind": "document", "format": "pdf", "files": [rel], "scribd_id": None, "doi": None, "source_url": url, "nurj_records": linking, "nurj_title": label, "pages": None})
    return docs


def main() -> None:
    by_hash: dict[str, dict] = {}
    volumes = []
    for d in documents():
        if d["pages"] is None:
            path = DATA_DIR / d["files"][0]
            digest = sha256(path)
            if digest in by_hash:
                same = by_hash[digest]
                same["copies"].append({k: d[k] for k in ("slug", "files", "source_url", "scribd_id", "doi")})
                same["nurj_records"] = list(dict.fromkeys(same["nurj_records"] + d["nurj_records"]))
                continue
            d["sha256"] = digest
            d["pages"] = {"pdf": pdf_pages, "docx": docx_pages, "png": lambda p: image_pages([p]), "jpg": lambda p: image_pages([p])}[d["format"]](path)
            by_hash[digest] = d
        d["copies"] = []
        volumes.append(d)
    for v in volumes:
        v["needs_reading"] = [p["section"] for p in v["pages"] if not p["blocks"]]
    slugs = [v["slug"] for v in volumes]
    if len(slugs) != len(set(slugs)):
        raise ValueError(f"duplicate slugs: {[s for s in slugs if slugs.count(s) > 1]}")
    out = DATA_DIR / "document_pages.json"
    out.write_text(json.dumps({"volumes": volumes}, indent=1, ensure_ascii=False) + "\n")
    kinds = {}
    for v in volumes:
        kinds[v["kind"], v["format"]] = kinds.get((v["kind"], v["format"]), 0) + 1
    print(f"{len(volumes)} volumes ({', '.join(f'{n} {k} {f}' for (k, f), n in sorted(kinds.items()))}), {sum(len(v['copies']) for v in volumes)} duplicate files merged, {sum(len(v['needs_reading']) for v in volumes)} pages without text -> {out}")


if __name__ == "__main__":
    main()

"""Make a PDF of every version of a NURJ paper that has pages, for hosting.

A NURJ paper's versions (the sources of its record in data/records/nurj.jsonl)
come from four kinds of file, and each becomes a PDF its own way:

- A paper in a print edition recovered from Issuu (pipeline.scrape_issuu):
  its pages, cut from the volume by the sections data/print_papers.json gives
  it. No PDF of these volumes survives, so each page is drawn again from the
  layer file Issuu's reader drew it from (layers/page_<section + 1>.bin), a
  protocol buffer holding the page's size, its background image, its fonts
  and a list of items in painting order:
    - field 4 and 5: the page's width and height in pixels;
    - field 10: a font, its field 1 a WOFF file;
    - field 11: the background image, its field 1 a JPEG of the page without
      its text (rules, colour, photographs and figures; for a scanned volume,
      the whole scan);
    - field 9: an item, its field 1 the background image's place, its field 2
      a run of text, or its field 3 a filled rectangle.
  A run of text has its string (1), font (2, an index into the page's fonts,
  0 when absent), size (3), colour as ARGB (4), a transform from the run's
  space to the page (5, six floats: a b c d e f, so that a point x y lands
  at a*x + c*y + e, b*x + d*y + f, with y down) and each character's x and y
  in the run's space (6 and 7). A rectangle has its colour (1) and x, y,
  width and height on the page (3). So a page is its background image with
  each character drawn over it in its own font, which keeps the text real
  text. A page with no layer file is its archived page image (images/) or
  scan (scans/) instead, and a page with neither is a page of its archived
  text, saying so.
- A paper in a print edition downloaded as a PDF (data/document_pages.json):
  its pages, copied from the edition.
- A document attached to a NURJ post or an Arch record (data/document_texts.json):
  a PDF is copied byte for byte; a Word file is converted with LibreOffice
  (soffice) when it is installed, and otherwise left out and reported; a
  Scribd embed, saved as one image per page, and a single image become a page
  per image. An embed saved as text alone has no pages and gets no PDF.
- A NURJ post or a NURJ x CAURS entry is a web page, not a file, and gets no PDF.

Fonts are embedded as Issuu served them. A font's OS/2 fsType can set the
restricted-licence bit together with a less restrictive one, and the
OpenType specification says the least restrictive bit then applies; MuPDF
refuses to embed such a font, so for those the restricted bit is cleared.
No font sets it alone.

Writes data/pdfs/nurj/<source id>.pdf and data/nurj_pdfs.jsonl, one line per
version: {source, work, file, pages, bytes, made} where made says how the
PDF was made, plus missing (the sections drawn from archived text) where
there are any. Versions that get no PDF are reported, with the reason. As a
check that a section is the page its layer file draws, every drawn page's
words are compared with the text the Issuu capture gives that section, and
pages that share less than half their words are reported.

Usage: uv run python -m pipeline.nurj_pdfs [--raw DIR] [ID ...]
  --raw: the folder of downloaded files (default data/raw), where the
  data files' raw/ paths point.
  ID: only make the PDFs of these sources.
"""

import argparse
import gzip
import hashlib
import io
import json
import re
import shutil
import struct
import subprocess
import tempfile
from collections import Counter, defaultdict
from pathlib import Path

import pymupdf
from fontTools.ttLib import TTFont

from pipeline.scrape_surg import DATA_DIR, RAW_DIR

OUT_DIR = DATA_DIR / "pdfs" / "nurj"
MANIFEST = DATA_DIR / "nurj_pdfs.jsonl"
PAGE_HEIGHT = 792  # points: Issuu pages are 1500 pixels tall, drawn 11 inches tall
OVERLAP = 0.5


def varint(b: bytes, i: int) -> tuple[int, int]:
    n = shift = 0
    while True:
        n |= (b[i] & 0x7F) << shift
        shift += 7
        i += 1
        if not b[i - 1] & 0x80:
            return n, i


def fields(b: bytes) -> list[tuple[int, int | bytes]]:
    """A protocol buffer message's fields, as (number, value) in order."""
    out, i = [], 0
    while i < len(b):
        key, i = varint(b, i)
        number, kind = key >> 3, key & 7
        if kind == 0:
            value, i = varint(b, i)
        elif kind == 1:
            value, i = b[i : i + 8], i + 8
        elif kind == 5:
            value, i = b[i : i + 4], i + 4
        elif kind == 2:
            n, i = varint(b, i)
            value, i = b[i : i + n], i + n
        else:
            raise ValueError(f"wire type {kind}")
        out.append((number, value))
    return out


def floats(b: bytes) -> tuple[float, ...]:
    return struct.unpack(f"<{len(b) // 4}f", b)


def argb(u: int) -> tuple[tuple[float, float, float], float]:
    return ((u >> 16 & 255) / 255, (u >> 8 & 255) / 255, (u & 255) / 255), (u >> 24 & 255) / 255


def woff_font(data: bytes) -> tuple[pymupdf.Font, bool]:
    """A WOFF font as a font MuPDF can embed, and whether it maps the private
    use characters U+F020-U+F0FF (a symbol font's encoding).

    Issuu's subsets mostly share a few names ("Medium"), and MuPDF writes fonts
    of the same name as one, so each is renamed after a hash of its file. A
    symbol font's glyphs are mapped from U+0020-U+00FF, the characters those
    stand for (as pipeline.scrape_issuu reads its text), instead of from the
    private use area, so that text drawn with them reads back as itself. On fsType, see the module docstring."""
    font = TTFont(io.BytesIO(data), recalcTimestamp=False)  # keep the output the same from run to run
    font.flavor = None
    if "OS/2" in font and font["OS/2"].fsType & 0x2 and font["OS/2"].fsType & 0xC:
        font["OS/2"].fsType &= ~0x2
    name = "F" + hashlib.sha1(data).hexdigest()[:12]
    for rec in font["name"].names:
        if rec.nameID in (1, 3, 4, 6):
            rec.string = name
    if "CFF " in font:
        font["CFF "].cff.fontNames = [name]
    symbol = False
    for table in font["cmap"].tables:
        if table.isUnicode():
            if any(0xF020 <= c <= 0xF0FF for c in table.cmap):
                symbol = True
                plain = {c: g for c, g in table.cmap.items() if not 0xF020 <= c <= 0xF0FF}
                table.cmap = plain | {c - 0xF000: g for c, g in table.cmap.items() if 0xF020 <= c <= 0xF0FF and c - 0xF000 not in plain}
    out = io.BytesIO()
    font.save(out)
    return pymupdf.Font(fontbuffer=out.getvalue()), symbol


def layer_page(doc: pymupdf.Document, data: bytes, stats: Counter) -> pymupdf.Page:
    """Draw a page from its Issuu layer file (see the module docstring)."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    top = defaultdict(list)
    for number, value in fields(data):
        top[number].append(value)
    width, height = top[4][0], top[5][0]
    s = PAGE_HEIGHT / height
    page = doc.new_page(width=width * s, height=height * s)
    fonts = [woff_font(dict(fields(f))[1]) for f in top[10]]
    background = dict(fields(top[11][0])).get(1) if top[11] else None
    for item in top[9]:
        for kind, value in fields(item):
            if kind == 1:
                if background:
                    page.insert_image(page.rect, stream=background)
            elif kind == 2:
                run = dict(fields(value))
                a, b, c, d, e, f = floats(run[5])
                xs, ys = floats(run.get(6, b"")), floats(run.get(7, b""))
                size = floats(run[3])[0] if 3 in run else 50.0
                color, opacity = argb(run.get(4, 0xFF000000))
                font, symbol = fonts[run.get(2, 0)]
                writer = pymupdf.TextWriter(page.rect, color=color, opacity=opacity)
                # Characters are placed unrotated from the run's origin, and a
                # rotated run is turned about that origin as a whole (morph
                # turns the other way from the layer's matrix, hence -b, -c).
                scale = (a * a + b * b) ** 0.5
                rotated = abs(b) > 1e-6 or abs(c) > 1e-6
                for i, ch in enumerate(run.get(1, b"").decode()):
                    if ch.isspace():
                        continue
                    x, y = (xs[i] if i < len(xs) else 0.0), (ys[i] if i < len(ys) else 0.0)
                    if symbol and 0xF020 <= ord(ch) <= 0xF0FF:
                        ch = chr(ord(ch) - 0xF000)
                    writer.append(((e + scale * x) * s, (f + scale * y) * s), ch, font=font, fontsize=size * scale * s)
                    stats["glyphs"] += 1
                morph = (pymupdf.Point(e * s, f * s), pymupdf.Matrix(a / scale, -b / scale, -c / scale, d / scale, 0, 0)) if rotated else None
                stats["rotated runs"] += rotated
                writer.write_text(page, morph=morph)
            elif kind == 3:
                shape = dict(fields(value))
                color, opacity = argb(shape.get(1, 0xFF000000))
                if 3 in shape:
                    x, y, w, h = floats(shape[3])[:4]
                    page.draw_rect(pymupdf.Rect(x * s, y * s, (x + w) * s, (y + h) * s), color=None, fill=color, fill_opacity=opacity)
                    stats["rectangles"] += 1
                else:
                    stats[f"shapes without a rectangle {sorted(shape)}"] += 1
            else:
                stats[f"items of kind {kind}"] += 1
    return page


def image_page(doc: pymupdf.Document, data: bytes) -> pymupdf.Page:
    pix = pymupdf.Pixmap(data)
    s = PAGE_HEIGHT / pix.h
    page = doc.new_page(width=pix.w * s, height=pix.h * s)
    page.insert_image(page.rect, stream=data)
    return page


def text_page(doc: pymupdf.Document, note: str, blocks: list[list[str]]) -> pymupdf.Page:
    page = doc.new_page(width=612, height=PAGE_HEIGHT)
    body = note + "\n\n" + "\n\n".join(" ".join(b) for b in blocks)
    size = 10.0
    while page.insert_textbox(page.rect + (54, 54, -54, -54), body, fontsize=size, fontname="helv") < 0:
        size -= 0.5  # a box the text overflows is left empty, so shrink it until it fits
    return page


def words(s: str) -> set[str]:
    return set(re.findall(r"[a-z]{3,}", s.lower()))


def issuu_pdf(item: dict, volume: dict, raw: Path, stats: Counter, report: list[str]) -> tuple[pymupdf.Document, str, list[int]]:
    """A print paper's pages from its Issuu volume (see the module docstring)."""
    doc, made, missing = pymupdf.open(), Counter(), []
    folder = raw / "issuu" / volume["slug"]
    sections = {p["section"]: p for p in volume["pages"]}
    for sec in item["sections"]:
        layer, image, scan = (folder / "layers" / f"page_{sec + 1}.bin", folder / "images" / f"page_{sec + 1}.jpg", folder / "scans" / f"page_{sec + 1}.jpg")
        if layer.exists():
            page = layer_page(doc, layer.read_bytes(), stats)
            made["layers"] += 1
            expected = words(" ".join(" ".join(b) for b in sections.get(sec, {}).get("blocks", [])))
            drawn = words(page.get_text())
            if len(expected) >= 20 and drawn and len(expected & drawn) / len(expected) < OVERLAP:
                report.append(f"{item['id']}: section {sec} shares {len(expected & drawn)}/{len(expected)} words with its capture text")
        elif image.exists() or scan.exists():
            image_page(doc, (image if image.exists() else scan).read_bytes())
            made["images"] += 1
        else:
            text_page(doc, f"Page {sec + 1} of this volume was not archived; its text, as Issuu's archived page gives it, follows.", sections.get(sec, {}).get("blocks", []))
            missing.append(sec)
    return doc, "issuu " + " and ".join(f"page {k}" for k in sorted(made)) if made else "issuu archived text", missing


def edition_pdf(item: dict, volume: dict, raw: Path) -> pymupdf.Document:
    """A print paper's pages from its edition's PDF."""
    doc = pymupdf.open()
    with pymupdf.open(raw / volume["files"][0].removeprefix("raw/")) as edition:
        for sec in item["sections"]:
            doc.insert_pdf(edition, from_page=sec, to_page=sec)
    return doc


def word_pdf(path: Path) -> bytes | None:
    """A Word file as PDF by LibreOffice, or None when it isn't installed."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(path)], check=True, capture_output=True, timeout=300)
        return next(Path(tmp).glob("*.pdf")).read_bytes()


def save(doc: pymupdf.Document, path: Path, title: str, authors: list[str], subject: str) -> None:
    doc.set_metadata({"title": title, "author": ", ".join(authors), "subject": subject, "creator": "", "producer": "", "creationDate": "", "modDate": ""})
    doc.xref_set_key(-1, "ID", "null")  # a converter's random file ID would change the file on every run
    doc.save(path, garbage=4, deflate=True, no_new_id=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--raw", type=Path, default=RAW_DIR)
    parser.add_argument("ids", nargs="*")
    args = parser.parse_args()
    works = [json.loads(line) for line in (DATA_DIR / "records" / "nurj.jsonl").open()]
    items = {p["id"]: p for p in json.loads((DATA_DIR / "print_papers.json").read_text())}
    issuu = {v["slug"]: v for v in json.loads((DATA_DIR / "issuu_pages.json").read_text())["volumes"]}
    editions = {v["slug"]: v for v in json.loads((DATA_DIR / "document_pages.json").read_text())["volumes"]}
    documents = {d["id"]: d for d in json.loads((DATA_DIR / "document_texts.json").read_text())}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    old = {r["source"]: r for r in map(json.loads, MANIFEST.open())} if MANIFEST.exists() else {}
    rows, skipped, report, stats = [], [], [], Counter()
    for w in works:
        names = [f"{p['first']} {p['last']}" for p in w["people"] if p["role"] == "student"]
        for src in w["extra"]["sources"]:
            sid = src["id"]
            if args.ids and sid not in args.ids:
                if sid in old:
                    rows.append(old[sid])
                continue
            out = OUT_DIR / f"{sid}.pdf"
            row = {"source": sid, "work": w["id"], "file": str(out.relative_to(DATA_DIR))}
            if src["type"] == "print":
                item = items[sid]
                subject = f"Northwestern Undergraduate Research Journal, {src['volume']}" + (f", pages {src['pages']}" if src.get("pages") else "")
                if item["slug"] in issuu:
                    doc, made, missing = issuu_pdf(item, issuu[item["slug"]], args.raw, stats, report)
                    row |= {"made": made} | ({"missing": missing} if missing else {})
                else:
                    doc = edition_pdf(item, editions[item["slug"]], args.raw)
                    row["made"] = "print edition pages"
                save(doc, out, w["title"], names, subject)
            elif src["type"] == "document":
                d = documents[sid]
                files = [args.raw / f.removeprefix("raw/") for f in d["files"]]
                if d["format"] == "pdf":
                    shutil.copyfile(files[0], out)
                    row["made"] = "file"
                elif d["format"] == "docx":
                    pdf = word_pdf(files[0])
                    if pdf is None:
                        skipped.append(f"{sid}: a Word file, and LibreOffice is not installed")
                        if sid in old:
                            rows.append(old[sid])
                        continue
                    save(pymupdf.open(stream=pdf, filetype="pdf"), out, w["title"], names, "Northwestern Undergraduate Research Journal")
                    row["made"] = "Word file by LibreOffice"
                else:
                    pictures = [f for f in files if f.suffix.lower() in (".jpg", ".jpeg", ".png")]
                    if not pictures:
                        skipped.append(f"{sid}: {d['format']} with no page images")
                        continue
                    doc = pymupdf.open()
                    for f in pictures:
                        image_page(doc, f.read_bytes())
                    save(doc, out, w["title"], names, "Northwestern Undergraduate Research Journal")
                    row["made"] = "page images"
            else:
                continue
            with pymupdf.open(out) as doc:
                row["pages"] = doc.page_count
            row["bytes"] = out.stat().st_size
            rows.append(row)
    rows.sort(key=lambda r: r["source"])
    MANIFEST.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    made = Counter(r["made"] for r in rows)
    print(f"{len(rows)} PDFs, {sum(r['bytes'] for r in rows) / 1e6:.0f} MB -> {OUT_DIR}")
    for k, n in made.most_common():
        print(f"  {n:4} {k}")
    print("drawn:", dict(stats))
    for line in skipped:
        print("no PDF:", line)
    for line in report:
        print("check:", line)


if __name__ == "__main__":
    main()

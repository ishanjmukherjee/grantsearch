"""Make a PDF of every version of a NURJ paper that has pages, for hosting.

A NURJ paper's versions (the sources of its record in data/records/nurj.jsonl)
come from four kinds of file, and each becomes a PDF its own way:

- A paper in a print edition recovered from Issuu (pipeline.scrape_issuu):
  its pages, cut from the volume: every section (page) data/print_papers.json
  gives it in pages. No PDF of these volumes survives, so each page is drawn again from the
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
version: {source, work, file, url, pages, bytes, made} where url is where
files.prowl.nu serves it (see pipeline.upload_files) and made says how the
PDF was made, plus missing (the sections drawn from archived text) where
there are any, and lead on the one PDF of each work that search links: the
version with the longest text, the one pipeline.nurj_works takes the work's
text from. Versions that get no PDF are reported, with the reason. As a
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

from pipeline.nurj_works import texts
from pipeline.scrape_surg import DATA_DIR, RAW_DIR
from pipeline.upload_files import PUBLIC, ROOT

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


def woff_font(data: bytes) -> tuple[pymupdf.Font, bool, str]:
    """A WOFF font as a font MuPDF can embed, whether it maps the private use
    characters U+F020-U+F0FF (a symbol font's encoding), and its new name.

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
    return pymupdf.Font(fontbuffer=out.getvalue()), symbol, name


def private(ch: str, symbol: bool) -> bool:
    """Whether a run's character is a private use code standing for a glyph,
    not text (a symbol font's U+F020-U+F0FF are handled by woff_font)."""
    return 0xE000 <= ord(ch) <= 0xF8FF and not (symbol and 0xF020 <= ord(ch) <= 0xF0FF)


def text_lines(path: Path) -> dict[int, list[tuple[str, float, float]]]:
    """Each page's lines of text from a volume's text_info.bin, the text Issuu
    extracted for search, by page number (section + 1): field 1 is a page, its
    field 1 the number, 3 its height in points, and each field 4 a line, with
    its string (1) and transform (3, six floats, the last two its origin). The
    origins are given here as fractions of the page's height."""
    data = path.read_bytes()
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    out = {}
    for number, value in fields(data):
        if number != 1:
            continue
        page = fields(value)
        head = dict(page)
        height = head.get(3) or 792
        out[head[1]] = [(line[1].decode(errors="replace"), floats(line[3])[4] / height, floats(line[3])[5] / height)
                        for line in (dict(fields(v)) for n, v in page if n == 4) if 1 in line and 3 in line]
    return out


def read_codes(text: str, symbol: bool, origin: tuple[float, float], lines: list[tuple[str, float, float]]) -> dict[str, str] | None:
    """What each private use code in a run stands for, read off the line of
    Issuu's text that it is: the run's other characters must match the line's,
    each code one to three of its characters (a ligature can stand for
    "ffi"), the same each time it occurs; of the lines that match, the one
    nearest the run's origin; failing that, the one place in the page's text
    it matches. None when there is none."""
    pattern, groups = [], {}
    for ch in text.strip():
        if private(ch, symbol):
            if ch in groups:
                pattern.append(f"(?P=g{groups[ch]})")
            else:
                groups[ch] = len(groups)
                pattern.append(f"(?P<g{groups[ch]}>\\S{{1,3}}?)")
        elif ch.isspace():
            pattern.append(r"\s*")
        else:
            pattern.append(re.escape(ch))
    regex = re.compile("".join(pattern))
    found = []
    for line, x, y in lines:
        if m := regex.fullmatch(line.strip()):
            found.append(((x - origin[0]) ** 2 + (y - origin[1]) ** 2, m))
    if not found:
        # A run and a line can split the page's text differently: look for the
        # run anywhere in the page's text, if it is there just once.
        page = " ".join(line.strip() for line, _, _ in lines)
        hits = list(re.finditer(regex.pattern.replace(r"\s*", r"\s+"), page)) if groups else []
        if len(hits) != 1:
            return None
        found = [(0.0, hits[0])]
    m = min(found, key=lambda f: f[0])[1]
    return {ch: m.group(f"g{i}") for ch, i in groups.items()}


def fix_text(doc: pymupdf.Document, codes: dict[str, dict[str, Counter]], report: list[str]) -> None:
    """Make text drawn with private use codes read back as what they stand for.

    A PDF's text comes from each font's ToUnicode map, glyph to characters,
    which MuPDF writes from the font's own cmap; where that gives a private use
    code that codes reads (font name to code to the readings of it), the map
    is rewritten to give its reading instead: the one found, or of readings
    that differ, the most common when it is found more than twice as often as
    any other. Readings that are themselves private use codes don't count."""
    for xref in range(1, doc.xref_length()):
        base = doc.xref_get_key(xref, "BaseFont")[1].lstrip("/")
        name = base.split("+")[-1][:13]
        if name not in codes or doc.xref_get_key(xref, "ToUnicode")[0] != "xref":
            continue
        reading = {}
        for code, votes in codes[name].items():
            ranked = [(r, n) for r, n in votes.most_common() if not any(0xE000 <= ord(c) <= 0xF8FF for c in r)]
            if not ranked:
                continue
            (best, n), *rest = ranked
            if rest and n <= 2 * rest[0][1]:
                report.append(f"{name}: U+{ord(code):04X} read as {dict(votes)}; left as it is")
                continue
            reading[code] = best
        cmap_xref = int(doc.xref_get_key(xref, "ToUnicode")[1].split()[0])
        cmap = doc.xref_stream(cmap_xref).decode()
        pairs = {}
        for block in re.findall(r"beginbfchar(.*?)endbfchar", cmap, re.S):
            for g, u in re.findall(r"<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>", block):
                pairs[int(g, 16)] = bytes.fromhex(u).decode("utf-16-be")
        for block in re.findall(r"beginbfrange(.*?)endbfrange", cmap, re.S):
            for a, b, u in re.findall(r"<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>\s*<([0-9a-fA-F]+)>", block):
                for k in range(int(b, 16) - int(a, 16) + 1):
                    pairs[int(a, 16) + k] = chr(int(u, 16) + k)
        if not any(v in reading for v in pairs.values()):
            continue
        pairs = {g: reading.get(v, v) for g, v in sorted(pairs.items())}
        items = list(pairs.items())
        body = "".join(
            f"{len(chunk)} beginbfchar\n" + "".join(f"<{g:04x}> <{v.encode('utf-16-be').hex()}>\n" for g, v in chunk) + "endbfchar\n"
            for chunk in (items[i : i + 100] for i in range(0, len(items), 100))
        )
        head = cmap[: cmap.index("endcodespacerange") + len("endcodespacerange\n")]
        doc.update_stream(cmap_xref, (head + body + "endcmap\nCMapName currentdict /CMap defineresource pop\nend\nend\n").encode())


def layer_page(doc: pymupdf.Document, data: bytes, stats: Counter, lines: list[tuple[str, float, float]], codes: dict[str, dict[str, Counter]]) -> pymupdf.Page:
    """Draw a page from its Issuu layer file (see the module docstring).

    Some fonts give characters private use codes in place of text, so that
    a run's string has codes where its letters should be. What they stand for
    is read off lines, the page's text as Issuu extracted it (see read_codes),
    into codes, by font, for fix_text to apply."""
    if data[:2] == b"\x1f\x8b":
        data = gzip.decompress(data)
    top = defaultdict(list)
    for number, value in fields(data):
        top[number].append(value)
    width, height = top[4][0], top[5][0]
    s = PAGE_HEIGHT / height
    page = doc.new_page(width=width * s, height=height * s)
    fonts = [woff_font(dict(fields(f))[1]) for f in top[10]]
    height_px = height
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
                font, symbol, name = fonts[run.get(2, 0)]
                text = run.get(1, b"").decode()
                if any(private(ch, symbol) for ch in text):
                    read = read_codes(text, symbol, (e / height_px, f / height_px), lines)
                    if read is None:
                        stats["runs with private use codes no line matches"] += 1
                    else:
                        stats["runs with private use codes read"] += 1
                        for code, chars in read.items():
                            codes.setdefault(name, {}).setdefault(code, Counter())[chars] += 1
                writer = pymupdf.TextWriter(page.rect, color=color, opacity=opacity)
                # Characters are placed unrotated from the run's origin, and a
                # rotated run is turned about that origin as a whole (morph
                # turns the other way from the layer's matrix, hence -b, -c).
                scale = (a * a + b * b) ** 0.5
                rotated = abs(b) > 1e-6 or abs(c) > 1e-6
                for i, ch in enumerate(text):
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
    info = folder / "layers" / "text_info.bin"
    lines = text_lines(info) if info.exists() else {}
    codes: dict[str, dict[str, Counter]] = {}
    drawn = []
    for sec in item["pages"]:
        layer, image, scan = (folder / "layers" / f"page_{sec + 1}.bin", folder / "images" / f"page_{sec + 1}.jpg", folder / "scans" / f"page_{sec + 1}.jpg")
        if layer.exists():
            layer_page(doc, layer.read_bytes(), stats, lines.get(sec + 1, []), codes)
            made["layers"] += 1
            drawn.append((doc.page_count - 1, sec))
        elif image.exists() or scan.exists():
            image_page(doc, (image if image.exists() else scan).read_bytes())
            made["images"] += 1
        else:
            text_page(doc, f"Page {sec + 1} of this volume was not archived; its text, as Issuu's archived page gives it, follows.", sections.get(sec, {}).get("blocks", []))
            missing.append(sec)
    fix_text(doc, codes, report)
    for i, sec in drawn:
        expected = words(" ".join(" ".join(b) for b in sections.get(sec, {}).get("blocks", [])))
        got = words(doc[i].get_text())
        if len(expected) >= 20 and got and len(expected & got) / len(expected) < OVERLAP:
            report.append(f"{item['id']}: section {sec} shares {len(expected & got)}/{len(expected)} words with its capture text")
    return doc, "issuu " + " and ".join(f"page {k}" for k in sorted(made)) if made else "issuu archived text", missing


def edition_pdf(item: dict, volume: dict, raw: Path) -> pymupdf.Document:
    """A print paper's pages from its edition's PDF."""
    doc = pymupdf.open()
    with pymupdf.open(raw / volume["files"][0].removeprefix("raw/")) as edition:
        for sec in item["pages"]:
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
    text = texts()
    by_work = defaultdict(list)
    for r in rows:
        r["url"] = PUBLIC + (DATA_DIR / r["file"]).relative_to(ROOT).as_posix()
        r.pop("lead", None)
        by_work[r["work"]].append(r)
    for group in by_work.values():
        max(group, key=lambda r: len(text.get(r["source"], "")))["lead"] = True
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

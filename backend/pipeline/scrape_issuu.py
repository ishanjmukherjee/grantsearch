"""Recover NURJ print editions from Issuu pages archived by the Wayback Machine.

NURJ published its print volumes on Issuu with downloads disabled, and
issuu.com now refuses requests, so no PDF of these volumes survives. What
does: every Issuu document page carried a block of the text Issuu had
extracted from the PDF, for search engines, with one <section> per page of
the document (separated by <hr>) and one <p> per text block on that page.
Older captures put it in a div with id robot-reader; captures of Issuu's
later design put the same sections straight in <main>.

For each volume this lists its captures with the Wayback CDX API, fetches
every successful one, and caches it under data/raw/issuu/<slug>/<timestamp>.html.
It also lists the volume's archived page images (image.isu.pub) and layer
files (layers.isu.pub), the files Issuu's reader draws pages from: per
volume a text_info.bin (its text with positions), and per page a
page_N.bin. These are protocol buffers, served gzipped. Every archived page
image and layer file is cached, under images/page_N.jpg and layers/. The page
layers of a scanned volume each wrap a JPEG of the scanned page (1158x1500
for NURJ's); for volumes whose captures have no text, their scans are written
to scans/page_N.jpg.

The CDX listings are cached too, under <slug>/cdx/, and only captures made
before CUTOFF are read from them, so a run reads the same captures whether
or not the Wayback Machine has archived more since; with everything cached,
a run makes no requests at all. Fetches the Wayback Machine refuses are
recorded in <slug>/missing.json and not retried. --refresh refetches the
listings, captures and files and retries the refusals.

Text is cleaned only where Issuu's extraction garbled it: characters of
symbol fonts that came out in the private use area (U+F020-U+F0FF stand for
U+0020-U+00FF), UTF-8 that was decoded as Windows-1252, which turns an
apostrophe into three accented characters, and HTML entities escaped more
than once.

Writes data/issuu_pages.json: per volume its slug, label, Issuu document id
and page count, the capture its pages are read from (fixed in VOLUMES; when
picked, it was the one with the most pages with text), every capture's
counts, the archived page images and layer files and the cached copies
of each, the cached text_info.bin and scans, and per page its text blocks,
each a list of lines.

Usage: uv run python -m pipeline.scrape_issuu [--refresh]
"""

import argparse
import gzip
import html
import json
import re
import time

import httpx
from bs4 import BeautifulSoup

from pipeline import download
from pipeline.scrape_nurj import text_of
from pipeline.scrape_surg import DATA_DIR, HEADERS, RAW_DIR

ISSUU_DIR = RAW_DIR / "issuu"
WAYBACK = "https://web.archive.org"
# Slug on issuu.com/nurj/docs/ -> (the edition, as the NURJ site labels it,
# the capture its pages are read from). The article indexes refer to blocks of
# that capture, and captures split text into blocks differently, so it is fixed.
VOLUMES = {
    "2003-2004": ("2003-2004", "20240808110322"),
    "2004-2005": ("2004-2005", "20250428232115"),
    "2005-2006": ("2005-2006", "20240529132628"),
    # Filed as 2008-2009 on Issuu and the NURJ site; the volume prints "Volume 4, May 2008".
    "2008-2009": ("May 2008", "20240422081132"),
    "2009-2010": ("2009-2010", "20241005171635"),
    "nurj_2010-11": ("2010-2011", "20240415000900"),
    "nurj_v7_2011-2012": ("2011-2012", "20240620091035"),
    "nurj_v8_2012-2013": ("2012-2013", "20240420115422"),
    "nurj_2013-2014": ("2013-2014", "20240423061551"),
    "nurj_master_3.31.15": ("2014-2015", "20240423185442"),
    "caurs_5.31.15": ("CAURS-NURJ Special Edition", "20220127142814"),
    "creative_116pg_r2": ("2015-2016 \"Best Senior Theses\"", "20240917054749"),
    "nurj_2016-2017": ("2016-2017", "20241004012353"),
    "nurj_2017-2018": ("2017-2018", "20201126044356"),
    "nurj_2018-19": ("2018-2019", "20240913125337"),
    "printvolume15": ("2019-2020", "20240920184219"),
    "print-16-for-online": ("2020-2021", "20240910085902"),
}
# Captures made from this day on are left out of the cached CDX listings: the
# day after data/issuu_pages.json was built from the captures then archived.
CUTOFF = "20261030"
DOCUMENT_ID = re.compile(r"\b(\d{12})-([0-9a-f]{32})\b")
WAIT = 1.5  # seconds between Wayback requests
# Runs of Windows-1252 characters that are really UTF-8 bytes.
MOJIBAKE = re.compile(r"[\u00c2-\u00f4][\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc\u2013\u2014\u2018-\u201e\u2020-\u2022\u2026\u2030\u2039\u203a\u20ac\u2122]{1,3}")


def get(client: httpx.Client, address: str, **params) -> httpx.Response:
    for attempt in range(5):
        try:
            resp = client.get(address, params=params or None)
            if resp.status_code < 500 and resp.status_code != 429:
                time.sleep(WAIT)
                return resp
        except httpx.TransportError:
            pass
        time.sleep(WAIT * 4 * (attempt + 1))
    raise RuntimeError(f"{address}: no response after 5 tries")


def cdx(slug: str, name: str, pattern: str, refresh: bool) -> list[dict]:
    """The successful captures of pattern made before CUTOFF, from the listing
    cached as <slug>/cdx/<name>.json."""
    params = {"fl": "timestamp,original,statuscode,mimetype,length", "filter": "statuscode:200"}
    if "*" in pattern:
        params["collapse"] = "urlkey"
    rows = download.cdx(ISSUU_DIR / slug / "cdx" / f"{name}.json", pattern, refresh, **params)
    return [r for r in rows if r["timestamp"] < CUTOFF]


def fetch_capture(client: httpx.Client, slug: str, ts: str, original: str, refresh: bool) -> str:
    path = ISSUU_DIR / slug / f"{ts}.html"
    if path.exists() and not refresh:
        return path.read_text()
    resp = get(client, f"{WAYBACK}/web/{ts}id_/{original}")
    resp.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(resp.text)
    return resp.text


def fetch_file(client: httpx.Client, ts: str, original: str, path, refresh: bool) -> bytes:
    if path.exists() and not refresh:
        return path.read_bytes()
    resp = get(client, f"{WAYBACK}/web/{ts}id_/{original}")
    resp.raise_for_status()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return resp.content


def fetch_kept(client: httpx.Client, c: dict, path, refresh: bool, missing: dict, jpeg_only: bool = False) -> bool:
    """Cache capture c at path, as fetch_file does, but record a refusal in
    missing (original -> status) instead of failing, and skip what missing
    holds already. Whether the file is cached."""
    if path.exists() and not refresh:
        return True
    if c["original"] in missing and not refresh:
        return False
    resp = get(client, f"{WAYBACK}/web/{c['timestamp']}id_/{c['original']}")
    if resp.status_code != 200 or (jpeg_only and not resp.content.startswith(b"\xff\xd8")):
        missing[c["original"]] = resp.status_code if resp.status_code != 200 else "not a JPEG"
        return False
    missing.pop(c["original"], None)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(resp.content)
    return True


def varint(b: bytes, i: int) -> tuple[int, int]:
    n = shift = 0
    while True:
        n |= (b[i] & 0x7F) << shift
        shift += 7
        i += 1
        if not b[i - 1] & 0x80:
            return n, i


def jpeg(message: bytes) -> bytes | None:
    """The first JPEG among the length-delimited fields of a protocol buffer
    message, searched depth first; None if it has none or does not parse."""
    i = 0
    try:
        while i < len(message):
            key, i = varint(message, i)
            kind = key & 7
            if kind == 0:
                _, i = varint(message, i)
            elif kind == 1:
                i += 8
            elif kind == 5:
                i += 4
            elif kind == 2:
                n, i = varint(message, i)
                payload = message[i : i + n]
                i += n
                if payload.startswith(b"\xff\xd8\xff"):
                    return payload
                if found := jpeg(payload):
                    return found
            else:
                return None
    except IndexError:
        return None
    return None


def fix_text(s: str) -> str:
    while (unescaped := html.unescape(s)) != s:  # some captures escape entities two or three times
        s = unescaped
    s = re.sub(r"[\uf020-\uf0ff]", lambda m: chr(ord(m.group()) - 0xF000), s)

    def utf8(m: re.Match) -> str:
        try:
            return m.group().encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return m.group()

    return MOJIBAKE.sub(utf8, s)


def pages(html: str) -> list[list[list[str]]]:
    """The document text of a capture: per page, its text blocks, each a list of lines."""
    soup = BeautifulSoup(html, "html.parser")
    box = soup.find(id="robot-reader")
    if box is None:
        # The later design: the container with the most <section> children.
        parents = [s.parent for s in soup.find_all("section")]
        box = max(set(parents), key=lambda p: len(p.find_all("section", recursive=False)), default=None)
    if box is None:
        return []
    out = []
    for section in box.find_all("section", recursive=False):
        blocks = [text_of([p]) for p in section.find_all("p")]
        out.append([fix_text(b).split("\n") for b in blocks if b.strip()])
    return out


def volume(client: httpx.Client, slug: str, label: str, capture: str, refresh: bool) -> dict:
    url = f"https://issuu.com/nurj/docs/{slug}"
    captures = [c for c in cdx(slug, "captures", f"issuu.com/nurj/docs/{slug}", refresh) if c["mimetype"] == "text/html"]
    parsed = []
    for c in captures:
        html = fetch_capture(client, slug, c["timestamp"], c["original"], refresh)
        text = pages(html)
        ids = DOCUMENT_ID.findall(html)
        count = re.search(r'"pageCount":(\d+)', html)
        parsed.append({
            "timestamp": c["timestamp"],
            "bytes": len(html.encode()),
            "document_id": "-".join(ids[0]) if ids else None,
            "page_count": int(count.group(1)) if count else None,
            "sections": len(text),
            "pages_with_text": sum(bool(p) for p in text),
            "chars": sum(len(line) for p in text for b in p for line in b),
            "pages": text,
        })
    best = next((p for p in parsed if p["timestamp"] == capture), None)
    if best is None:
        raise ValueError(f"{slug}: capture {capture} is not among its captures")
    doc = next((p["document_id"] for p in sorted(parsed, key=lambda p: p["timestamp"], reverse=True) if p["document_id"]), None)
    count = next((p["page_count"] for p in parsed if p["page_count"]), None)

    def page_no(c: dict) -> int:
        return int(re.search(r"page_(\d+)", c["original"]).group(1))

    images, layers = [], []
    if doc:
        images = sorted((c for c in cdx(slug, "images", f"image.isu.pub/{doc}/jpg/*", refresh) if re.search(r"/page_\d+\.jpg$", c["original"])), key=page_no)
        revision, publication = doc.split("-")
        layers = [c for c in cdx(slug, "layers", f"layers.isu.pub/{publication}/*", refresh) if f"/{revision}/" in c["original"]]
    missing_path = ISSUU_DIR / slug / "missing.json"
    missing = json.loads(missing_path.read_text()) if missing_path.exists() else {}
    image_files, layer_files = [], []
    for c in images:
        path = ISSUU_DIR / slug / "images" / f"page_{page_no(c)}.jpg"
        if fetch_kept(client, c, path, refresh, missing, jpeg_only=True):
            image_files.append(str(path.relative_to(DATA_DIR)))
    for c in layers:
        path = ISSUU_DIR / slug / "layers" / c["original"].rsplit("/", 1)[1]
        if fetch_kept(client, c, path, refresh, missing):
            layer_files.append(str(path.relative_to(DATA_DIR)))
    if missing:
        missing_path.write_text(json.dumps(dict(sorted(missing.items())), indent=1) + "\n")
    elif missing_path.exists():
        missing_path.unlink()
    text_info = None
    for c in layers:
        if c["original"].endswith("/text_info.bin"):
            text_info = ISSUU_DIR / slug / "layers" / "text_info.bin"
            fetch_file(client, c["timestamp"], c["original"], text_info, refresh)
    scans = []
    if not best["pages_with_text"]:
        for c in sorted((c for c in layers if re.search(r"/page_\d+\.bin$", c["original"])), key=page_no):
            layer = fetch_file(client, c["timestamp"], c["original"], ISSUU_DIR / slug / "layers" / f"page_{page_no(c)}.bin", refresh)
            scan = jpeg(gzip.decompress(layer) if layer[:2] == b"\x1f\x8b" else layer)
            if scan is None:
                raise ValueError(f"{c['original']}: no JPEG in the page layer")
            path = ISSUU_DIR / slug / "scans" / f"page_{page_no(c)}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(scan)
            scans.append(str(path.relative_to(DATA_DIR)))

    print(f"{slug}: {len(parsed)} captures, capture {best['timestamp']} with {best['pages_with_text']}/{count} pages of text, {len(images)} page images ({len(image_files)} cached), {len(layers)} layer files ({len(layer_files)} cached), {len(scans)} scans", flush=True)
    return {
        "slug": slug,
        "label": label,
        "url": url,
        "document_id": doc,
        "page_count": count,
        "capture": best["timestamp"],
        "capture_url": f"{WAYBACK}/web/{best['timestamp']}/{url}",
        "captures": [{k: v for k, v in p.items() if k != "pages"} for p in parsed],
        "page_images": [c["original"] for c in images],
        "layers": [c["original"] for c in layers],
        "text_info": text_info and str(text_info.relative_to(DATA_DIR)),
        "scans": scans,
        "page_image_files": image_files,
        "layer_files": layer_files,
        "pages": [{"section": i, "blocks": b} for i, b in enumerate(best["pages"])],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch cached captures and layers")
    args = parser.parse_args()
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=120) as client:
        volumes = [volume(client, slug, label, capture, args.refresh) for slug, (label, capture) in VOLUMES.items()]
    path = DATA_DIR / "issuu_pages.json"
    partial = path.with_suffix(".json.partial")
    partial.write_text(json.dumps({"volumes": volumes}, indent=1, ensure_ascii=False) + "\n")
    partial.replace(path)  # readers never see a half-written file
    print(f"{len(volumes)} volumes -> {path}")


if __name__ == "__main__":
    main()

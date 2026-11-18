"""Copy the ForagerOne posters of Expo listings into data/pdfs/expo/, for hosting.

An Expo listing from ForagerOne (Expo 2020's) or matched to its ForagerOne
poster (Expo 2022's), with its ForagerOne id in data/records/expo.jsonl (see
pipeline.parse_forager), has the poster's PDF, as pipeline.scrape_forager
saved and redacted it, where the presentation posted one. A visitor can no
longer open it on ForagerOne: Expo 2020's event has expired, and Expo 2022's
pages need a login. The PDF is copied byte for byte to
data/pdfs/expo/<year>/<ForagerOne id>.pdf, for pipeline.upload_files to send
to files.prowl.nu. The copies are left out of git (data/raw keeps the
originals) and of the deploy image.

Writes data/expo_pdfs.jsonl, one line per poster: {forager_id, listing,
year, kind, pages, file, url, bytes, sha256}, where url is where
files.prowl.nu serves the copy and kind is what the site calls it: "poster"
for one page, "slides" for several landscape pages, and "document" for
several portrait ones (Expo 2020's photographs of an artwork and selections
from a work of fiction). A presentation that posted no PDF, a video or a
creative work, has a line with only its ids and year, so that search can
tell a listing without a PDF from one this file has not caught up with.

Usage: uv run python -m pipeline.expo_pdfs
"""

import hashlib
import json
import shutil

import pymupdf

from pipeline.parse_forager import HOSTED
from pipeline.records import load
from pipeline.scrape_surg import DATA_DIR
from pipeline.upload_files import PUBLIC, ROOT

OUT_DIR = ROOT / "expo"
MANIFEST = DATA_DIR / "expo_pdfs.jsonl"


def kind(doc: pymupdf.Document) -> str:
    if doc.page_count == 1:
        return "poster"
    first = doc[0].rect
    return "slides" if first.width > first.height else "document"


def main() -> None:
    # Each listing with its ForagerOne id: a record's own, or each of its
    # listings' for a poster listed more than once.
    listings = []
    for r in load("expo"):
        if r["year"] not in HOSTED:
            continue
        for e in r.get("listings") or [{"id": r["id"], **r.get("extra", {})}]:
            if e.get("forager_id"):
                listings.append((e["id"], r["year"], e["forager_id"]))
    rows = []
    for listing, year, pid in listings:
        src, out = HOSTED[year] / str(pid) / "poster.pdf", OUT_DIR / str(year) / f"{pid}.pdf"
        if not src.exists():
            # A video or creative work with no PDF.
            rows.append({"forager_id": pid, "listing": listing, "year": year, "kind": None, "pages": None, "file": None, "url": None, "bytes": None, "sha256": None})
            continue
        data = src.read_bytes()
        if not data.startswith(b"%PDF"):
            raise SystemExit(f"{src} is not a PDF (a Git LFS pointer? run git lfs pull)")
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists() or out.read_bytes() != data:
            shutil.copyfile(src, out)
        doc = pymupdf.open(src)
        rows.append({
            "forager_id": pid,
            "listing": listing,
            "year": year,
            "kind": kind(doc),
            "pages": doc.page_count,
            "file": out.relative_to(DATA_DIR).as_posix(),
            "url": PUBLIC + out.relative_to(ROOT).as_posix(),
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        })
    kept = {r["file"] for r in rows}
    for old in OUT_DIR.glob("*/*.pdf"):
        if old.relative_to(DATA_DIR).as_posix() not in kept:
            old.unlink()
    rows.sort(key=lambda r: r["forager_id"])
    MANIFEST.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    hosted = [r for r in rows if r["file"]]
    print(f"wrote {len(hosted)} PDFs ({sum(r['bytes'] for r in hosted) / 1e6:.0f} MB) to {OUT_DIR}, and {len(rows)} listings to {MANIFEST}")


if __name__ == "__main__":
    main()

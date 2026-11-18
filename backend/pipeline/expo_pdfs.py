"""Copy the ForagerOne posters of Expo listings into data/pdfs/expo/, for hosting.

An Expo 2022 listing matched to its ForagerOne poster (extra.forager_id in
data/records/expo.jsonl; see pipeline.parse_forager) has the poster's PDF,
as pipeline.scrape_forager saved and redacted it, but nowhere a visitor can
open it: the event's pages need a login. The PDF is copied byte for byte to
data/pdfs/expo/<year>/<ForagerOne id>.pdf, for pipeline.upload_files to send
to files.prowl.nu. The copies are left out of git (data/raw keeps the
originals) and of the deploy image.

Writes data/expo_pdfs.jsonl, one line per poster: {forager_id, record, year,
pages, file, url, bytes, sha256}, where pages is the PDF's page count (a
presentation of several pages is slides, which the site names as such) and
url is where files.prowl.nu serves the copy.

Usage: uv run python -m pipeline.expo_pdfs
"""

import hashlib
import json
import shutil

import pymupdf

from pipeline.parse_forager import POSTED
from pipeline.scrape_surg import DATA_DIR
from pipeline.upload_files import PUBLIC, ROOT

OUT_DIR = ROOT / "expo"
MANIFEST = DATA_DIR / "expo_pdfs.jsonl"


def main() -> None:
    posters = [
        r
        for r in map(json.loads, (DATA_DIR / "records" / "expo.jsonl").open())
        if r["year"] in POSTED and r.get("extra", {}).get("forager_id")
    ]
    rows = []
    for r in posters:
        pid = r["extra"]["forager_id"]
        src, out = POSTED[r["year"]] / str(pid) / "poster.pdf", OUT_DIR / str(r["year"]) / f"{pid}.pdf"
        data = src.read_bytes()
        if not data.startswith(b"%PDF"):
            raise SystemExit(f"{src} is not a PDF (a Git LFS pointer? run git lfs pull)")
        out.parent.mkdir(parents=True, exist_ok=True)
        if not out.exists() or out.read_bytes() != data:
            shutil.copyfile(src, out)
        rows.append({
            "forager_id": pid,
            "record": r["id"],
            "year": r["year"],
            "pages": pymupdf.open(src).page_count,
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
    print(f"wrote {len(rows)} PDFs ({sum(r['bytes'] for r in rows) / 1e6:.0f} MB) to {OUT_DIR} and {MANIFEST}")


if __name__ == "__main__":
    main()

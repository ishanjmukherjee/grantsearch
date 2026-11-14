"""Copy every MMSS thesis paper the library has into data/pdfs/mmss/, for hosting.

An MMSS thesis whose paper the library has (extra.paper in
data/records/theses.jsonl) links its paper's file on SharePoint, which needs
a Northwestern login. That file is in the mmss-papers checkout (see
pipeline.parse_mmss_theses), and is copied byte for byte to
data/pdfs/mmss/<library item id>.pdf, for pipeline.upload_files to send to
files.prowl.nu. The item id names it because it is the library's own and
stays put when the thesis ids, numbered within each year, shift. The copies
are left out of git (the checkout keeps the originals) and of the deploy
image.

Theses without the paper get nothing: the library has only its placeholder
page for them, so they link the library, which has their catalog entry.

Writes data/mmss_pdfs.jsonl, one line per paper: {item, source, file, url,
bytes, sha256}, where source is the thesis's url (the paper on
SharePoint), which search matches it by, and url is where files.prowl.nu
serves the copy.

Usage: uv run python -m pipeline.mmss_pdfs
"""

import hashlib
import json
import shutil

from pipeline.parse_mmss_theses import checkout
from pipeline.scrape_surg import DATA_DIR
from pipeline.upload_files import PUBLIC, ROOT

OUT_DIR = ROOT / "mmss"
MANIFEST = DATA_DIR / "mmss_pdfs.jsonl"


def main() -> None:
    root = checkout()
    items = {r["url"]: r for r in json.loads((root / "records.json").read_text())}
    theses = [
        t
        for t in map(json.loads, (DATA_DIR / "records" / "theses.jsonl").open())
        if t["id"].startswith("mmss-") and t["extra"]["paper"]
    ]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for t in theses:
        item = items[t["url"]]
        if not item["has_document"]:
            raise SystemExit(f"{t['id']} links item {item['id']}, which has no paper")
        src, out = root / item["file"], OUT_DIR / f"{item['id']}.pdf"
        data = src.read_bytes()
        if not data.startswith(b"%PDF"):
            raise SystemExit(f"{src} is not a PDF (a Git LFS pointer? run git lfs pull in the checkout)")
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise SystemExit(f"{src} does not match its catalog checksum")
        if not out.exists() or out.read_bytes() != data:
            shutil.copyfile(src, out)
        rows.append({
            "item": item["id"],
            "source": t["url"],
            "file": out.relative_to(DATA_DIR).as_posix(),
            "url": PUBLIC + out.relative_to(ROOT).as_posix(),
            "bytes": len(data),
            "sha256": item["sha256"],
        })
    kept = {r["file"] for r in rows}
    for old in OUT_DIR.glob("*.pdf"):
        if old.relative_to(DATA_DIR).as_posix() not in kept:
            old.unlink()
    rows.sort(key=lambda r: r["item"])
    MANIFEST.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"wrote {len(rows)} PDFs ({sum(r['bytes'] for r in rows) / 1e6:.0f} MB) to {OUT_DIR} and {MANIFEST}")


if __name__ == "__main__":
    main()

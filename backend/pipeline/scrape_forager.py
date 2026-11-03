"""Scrape Expo 2020, held online on ForagerOne, into data/raw/forager/.

The 2020 Undergraduate Research and Arts Exposition was a ForagerOne
Symposium event (id 54). The event has expired, so its listing endpoints
refuse, but the platform's API still serves each presentation by id. The
event's 83 presentations lie between ids 2017 and 2312, among other schools'
events (ids 1000-3500 were checked); only event 54's are kept.

Each presentation gets a directory, data/raw/forager/<id>/, holding
presentation.json as the API serves it and the files it links to: the poster
or slides as poster.pdf (71 of them) and the platform's thumbnail of its
first page as thumbnail.jpg. The videos (64 voiceovers and 8 video
presentations) are on YouTube; their ids are in the JSON, and they are not
downloaded.

The API's routes for an event's listing, public comments and the event
itself now require a login, but the Wayback Machine captured some of what the
site's API served during the event, on 2020-05-28. ARCHIVED pins those
captures, read in their original form (Wayback's id_ form):
- listing.json, the event's full listing, which alone gives each
  presentation's subject tags (and confirms the 83);
- <id>/comments.json, the public comments on the two presentations whose
  comments were captured (2180 and 2207);
- institution.json, Northwestern's entry in the platform's institutions.

Email addresses are the one thing deliberately not kept:
- In the JSON, a key naming an email is removed with its value, and the run
  fails if an address is left anywhere else, so that a field the API adds
  cannot carry one in unnoticed.
- A poster that prints an address has it redacted: the text is removed from
  the PDF, and its box is painted over in the page's own colour there and in
  the thumbnail. redactions.json records each box (not the address).
Nothing else is dropped.

Run from backend/: uv run python pipeline/scrape_forager.py
"""

import argparse
import json
import re
import time
from collections import Counter
from pathlib import Path

import httpx
import pymupdf

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "forager"
API = "https://symposium-api-prod-ivu2siwqia-uc.a.run.app/api"
EVENT = 54
IDS = range(2017, 2313)
HEADERS = {"User-Agent": "grantsearch/0.1 (student research search tool)"}

WAYBACK = "https://web.archive.org/web"
# The API the site called in 2020, before it moved to the address above.
SITE_API = "https://symposium.foragerone.com/api"
# Saved path: (capture timestamp, route on SITE_API).
ARCHIVED = {
    "listing.json": ("20200528183743", "presentations?institutionCodeOrHash=northwestern&q="),
    "2180/comments.json": ("20200528174233", "comments?institutionCodeOrHash=northwestern&posterId=2180&hash=2180"),
    "2207/comments.json": ("20200528174347", "comments?institutionCodeOrHash=northwestern&posterId=2207&hash=2207"),
    "institution.json": ("20200528174228", "institutions"),
}

EMAIL_KEY = re.compile(r"e-?mail", re.I)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# The signed file URLs name the platform's Google service account
# ("...-compute@developer.gserviceaccount.com"), which is not a person's.
SERVICE_ACCOUNT = re.compile(r"[\w.-]+@[\w.-]*gserviceaccount\.com")
# Keys that name email domains the event accepted, not anyone's address.
NOT_ADDRESSES = {"validEmails"}
# Thumbnails are the first page rendered at 200 dpi.
THUMB_SCALE = 200 / 72


def strip_emails(value, dropped: set, path: str = ""):
    """value without any key that names an email; dropped collects their paths."""
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if EMAIL_KEY.search(k) and k not in NOT_ADDRESSES:
                dropped.add(re.sub(r"\[\d+\]", "[]", f"{path}.{k}"))
            else:
                out[k] = strip_emails(v, dropped, f"{path}.{k}")
        return out
    if isinstance(value, list):
        return [strip_emails(v, dropped, f"{path}[{i}]") for i, v in enumerate(value)]
    return value


def email_paths(value, path: str = "$") -> list[str]:
    """The paths of strings in value that still hold an email address."""
    if isinstance(value, dict):
        return [p for k, v in value.items() for p in email_paths(v, f"{path}.{k}")]
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in email_paths(v, f"{path}[{i}]")]
    if isinstance(value, str) and EMAIL.search(SERVICE_ACCOUNT.sub("", value.replace("%40", "@"))):
        return [path]
    return []


def get(client: httpx.Client, url: str) -> httpx.Response:
    for attempt in range(4):
        try:
            resp = client.get(url)
        except httpx.TransportError:
            if attempt == 3:
                raise
        else:
            if resp.status_code < 500 and resp.status_code != 429:
                return resp
        time.sleep(2 ** attempt)
    return resp


def save_json(path: Path, data, dropped: set) -> None:
    data = strip_emails(data, dropped)
    if left := email_paths(data):
        raise SystemExit(f"{path}: an email address is left at {left}")
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def fetch_archived(client: httpx.Client, dropped: set) -> None:
    """Save each ARCHIVED capture not saved yet."""
    for name, (ts, route) in ARCHIVED.items():
        path = OUT / name
        if path.exists():
            continue
        resp = get(client, f"{WAYBACK}/{ts}id_/{SITE_API}/{route}")
        resp.raise_for_status()
        data = resp.json()
        if name == "institution.json":
            (data,) = [i for i in data if i.get("institutionCode") == "northwestern"]
        save_json(path, data, dropped)
        time.sleep(2)


def background(page: pymupdf.Page, rect: pymupdf.Rect) -> tuple[int, int, int]:
    """The commonest colour in a thin ring around rect: the page's colour there."""
    ring = rect + (-3, -3, 3, 3)
    pix = page.get_pixmap(clip=ring, dpi=72, colorspace=pymupdf.csRGB, alpha=False)
    inner = pymupdf.Rect(rect.x0 - ring.x0, rect.y0 - ring.y0, rect.x1 - ring.x0, rect.y1 - ring.y0)
    colours = Counter(
        pix.pixel(x, y) for y in range(pix.height) for x in range(pix.width)
        if not inner.contains(pymupdf.Point(x + 0.5, y + 0.5))
    )
    return colours.most_common(1)[0][0]


def redact_pdf(d: Path) -> list[dict]:
    """Redact the email addresses poster.pdf prints; the boxes redacted."""
    pdf = d / "poster.pdf"
    doc = pymupdf.open(pdf)
    boxes = []
    for page in doc:
        found = set(EMAIL.findall(page.get_text()))
        rects = [r for addr in found for r in page.search_for(addr)]
        if found and not rects:
            raise SystemExit(f"{pdf}: page {page.number + 1} prints an address it cannot locate")
        for r in rects:
            colour = background(page, r)
            boxes.append({"page": page.number + 1, "rect": [round(v, 1) for v in r], "colour": colour})
            page.add_redact_annot(r, fill=[c / 255 for c in colour])
        if rects:
            page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                                  graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
    if not boxes:
        return []
    doc.save(pdf.with_suffix(".tmp"), garbage=3, deflate=True)
    pdf.with_suffix(".tmp").replace(pdf)
    left = [p.number + 1 for p in pymupdf.open(pdf) if EMAIL.search(p.get_text())]
    if left:
        raise SystemExit(f"{pdf}: addresses are left on pages {left}")
    return boxes


def paint_thumbnail(d: Path, boxes: list[dict]) -> None:
    """Paint over the page 1 boxes in thumbnail.jpg."""
    first = [b for b in boxes if b["page"] == 1]
    if not first:
        return
    thumb = d / "thumbnail.jpg"
    pix = pymupdf.Pixmap(thumb)
    for b in first:
        r = pymupdf.Rect(b["rect"]) * THUMB_SCALE
        pix.set_rect((r + (-2, -2, 2, 2)).irect, b["colour"])
    pix.save(thumb, output="jpg", jpg_quality=95)


def extension(resp: httpx.Response, url: str) -> str:
    suffix = Path(httpx.URL(url).path).suffix
    if suffix:
        return suffix
    kind = resp.headers.get("content-type", "").split(";")[0]
    return {"application/pdf": ".pdf", "image/jpeg": ".jpg", "image/png": ".png"}.get(kind, "")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--first", type=int, default=IDS.start, help="first id to try")
    ap.add_argument("--last", type=int, default=IDS.stop - 1, help="last id to try")
    args = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    log_path = OUT / "redactions.json"
    redactions = json.loads(log_path.read_text()) if log_path.exists() else {}
    dropped: set[str] = set()
    kept, other, missing = [], Counter(), {}
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=120) as client:
        for pid in range(args.first, args.last + 1):
            d = OUT / str(pid)
            if not d.exists():
                resp = get(client, f"{API}/presentations/{pid}")
                if resp.status_code != 200:
                    other[f"HTTP {resp.status_code}"] += 1
                    continue
                data = resp.json()
                if data.get("eventId") != EVENT:
                    other[f"event {data.get('eventId')}"] += 1
                    continue
                d.mkdir()
                save_json(d / "presentation.json", data, dropped)
                time.sleep(0.3)
            pres = json.loads((d / "presentation.json").read_text())
            kept.append(pid)

            fresh = set()
            for key, name in [("posterFileURL", "poster"), ("posterThumbnailImageURL", "thumbnail")]:
                url = pres.get(key)
                if not url or any(f.stem == name for f in d.iterdir()):
                    continue
                resp = get(client, url)
                if resp.status_code != 200:
                    missing.setdefault(pid, []).append(f"{key}: HTTP {resp.status_code}")
                    continue
                (d / f"{name}{extension(resp, url)}").write_bytes(resp.content)
                fresh.add(name)
                time.sleep(0.3)
            if "poster" in fresh and (d / "poster.pdf").exists():
                if boxes := redact_pdf(d):
                    redactions[str(pid)] = boxes
            if "thumbnail" in fresh and str(pid) in redactions:
                paint_thumbnail(d, redactions[str(pid)])

        fetch_archived(client, dropped)

    log_path.write_text(json.dumps(dict(sorted(redactions.items())), indent=1) + "\n")
    print(json.dumps({
        "kept": len(kept), "first": min(kept, default=None), "last": max(kept, default=None),
        "other": dict(other), "missing": missing, "dropped_keys": sorted(dropped),
        "redacted": {k: len(v) for k, v in redactions.items()},
    }, indent=1))


if __name__ == "__main__":
    main()

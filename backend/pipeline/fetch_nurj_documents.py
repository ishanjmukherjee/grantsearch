"""Download NURJ documents hosted off thenurj.com that pipeline.scrape_nurj leaves as links, into data/raw/nurj_extra/.

pipeline.scrape_nurj keeps documents on other hosts only as URLs. Its
Scribd and Arch documents are saved by hand under data/raw/nurj/ (listed in
manual_downloads.tsv). This saves the rest that can still be had:

- yumpu/: the two Yumpu magazines of 2021. yumpu.com answers scripts with
  HTTP 202 and an empty body (a bot check), so only the Wayback Machine's
  captures are used (YUMPU pins them).
  - NURJ Archives Special Edition (65759299, 44 pages, essays on Northwestern
    history from the University Archives): two captures. The 2022-09-25 one
    carries Yumpu's per-page text layer inline, with headings for 21 pages;
    the 2023-05-05 one, after a redesign, has almost no text.
  - NURJ x Yale: Intersections (65830578, 48 pages): never captured, under
    any slug of /document/view/ or /document/read/ (cdx/view_65830578.json,
    read_65830578.json).
  - Page images: no capture under img.yumpu.com/65759299/ or 65830578/
    (cdx/img_*.json).
- drive/: the 13 Google Drive files NURJ links (DRIVE). Each is tried as
  a download (uc?export=download), with its view page's status recorded, and
  looked up in the Wayback Machine (cdx/). attempts.json records what each
  answered. On 2026-11-08:
  - Saved: "Paper 2021 Submission Guidelines.pdf" (How to Submit), and the
    2024-06-21 capture of the preview page of the other How to Submit file,
    "NURJ Outreach Summer Info Session Recording.mp4" (the video itself was
    not captured).
  - Deleted (view and download answer 404) and never captured: the four
    2019-20 theses (Snyder, Ajith, Ogwumike, Dinegar), the Mahler piano
    quartet paper and the ChangEd marketing strategy.
  - Behind a Google sign-in (view answers 401, download serves the sign-in
    page, and each one's only capture is a 302 to it): the five Online Vol. 8
    SURG Tell-All embeds.

The 132 Scribd documents NURJ embeds or links are all in data/raw/nurj/
already, including every print edition's PDF. For 7 the original was deleted
from Scribd before it was saved (687589355, 699131583, 699134984, 725010524,
725010642, 725011072, 726986527); only their embeds' page text survives
there. scribd/cdx/<id>.json records that the Wayback Machine has no capture
of their document pages either.

Other fetch scripts save into nurj_extra/ too, so manifest.jsonl (see
pipeline.download) is reread just before it is written, and only this
script's parts (OWN) are replaced.

Usage: uv run python -m pipeline.fetch_nurj_documents [--refresh]
"""

import argparse
import json
import re

from pipeline.download import RAW, Manifest, cdx, get

SOURCE = "nurj_extra"
DIR = RAW / SOURCE
# Yumpu document id -> (slug, Wayback captures of its /document/view/ page).
YUMPU = {
    "65759299": ("nurj-archives-special-edition", ["20220925054454", "20230505152101"]),
    "65830578": ("nurj-x-yale-intersections", []),
}
# Drive file id -> what links it on thenurj.com.
DRIVE = {
    "1VVo0M5kw2Pxd-SXFfHApn0fIU4VcKts-": "nurj-976, Preschoolers' Creativity During STEM Play (Snyder thesis)",
    "1jpn4DfvDf7oLEXNSAjpP7HkCkclH8qKx": "nurj-985, Moroccan Female Entrepreneurship (Ajith thesis)",
    "1cjsJksNn3NhcASoucy9h77-KSb54wLQ8": "nurj-1003, Radical Redress: Black Birth Workers Respond to Maternal Mortality (Ogwumike thesis)",
    "1AgAHhJc2vPMl9M5Pi469U8WmsvCFtJ63": "nurj-1012, Type 2 Diabetes Care and Management (Dinegar thesis)",
    "1wXVlHBFe1lh-Vf45YZHlV9bBzDywSH5V": "nurj-1737, Completing Mahler's Piano Quartet",
    "1_rKCDGqlDGHvSozjK4c15Bewt1et8l7N": "nurj-3775, ChangEd Digital Marketing Strategy",
    "1d-BSg_rthT5PF8WP1C5xoQc7RDWv0DfN": "nurj-page-102, How to Submit",
    "1cUuD9FUnVnn15vS_VmjrtfWUQRd6-pvi": "nurj-page-102, How to Submit",
    "1ikDeM6ul3miCYuBY_KTZQoS3H6KIy5ah": "nurj-page-4661, Online Vol. 8 SURG Tell-All",
    "1ZpKL7tMjX8Yqz8Z0JBaaXX67xCdF0ugm": "nurj-page-4661, Online Vol. 8 SURG Tell-All",
    "1Cxrp42Fqakw9iglfEOHysgQdDB6Z2CvY": "nurj-page-4661, Online Vol. 8 SURG Tell-All",
    "17V_a5BTTqDVvtYldxoGgsezaxT2OX4gH": "nurj-page-4661, Online Vol. 8 SURG Tell-All",
    "1On4i3eVDafRL1R6P_DhB0qM5agaGMhDb": "nurj-page-4661, Online Vol. 8 SURG Tell-All",
}
SCRIBD_DELETED = ["687589355", "699131583", "699134984", "725010524", "725010642", "725011072", "726986527"]
# The parts of nurj_extra/ this script writes.
OWN = {"yumpu", "drive", "scribd"}
FILENAME = re.compile(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)"?')


def yumpu(manifest: Manifest, refresh: bool) -> None:
    d = DIR / "yumpu" / "cdx"
    for doc, (slug, captures) in YUMPU.items():
        for form in ("view", "read"):
            cdx(d / f"{form}_{doc}.json", f"yumpu.com/en/document/{form}/{doc}", refresh, matchType="prefix")
        cdx(d / f"img_{doc}.json", f"img.yumpu.com/{doc}/", refresh, matchType="prefix")
        for ts in captures:
            manifest.save_wayback(f"yumpu/{doc}/wayback_{ts}.html", ts,
                                  f"https://www.yumpu.com/en/document/view/{doc}/{slug}", refresh=refresh)


def drive(manifest: Manifest, refresh: bool) -> None:
    path = DIR / "drive" / "attempts.json"
    attempts = json.loads(path.read_text()) if path.exists() and not refresh else {}
    for fid, linked_from in DRIVE.items():
        if fid in attempts and (attempts[fid]["saved"] or not refresh):
            continue
        rows, unlisted = [], []
        for pattern in (f"drive.google.com/file/d/{fid}", f"drive.google.com/uc?id={fid}",
                        f"drive.google.com/uc?export=download&id={fid}", f"docs.google.com/uc?id={fid}"):
            name = re.sub(r"[^\w-]+", "_", pattern.split("/", 1)[1])
            try:
                rows += cdx(DIR / "drive" / "cdx" / f"{name}.json", pattern, refresh, matchType="prefix")
            except RuntimeError as e:
                print(e, flush=True)
                unlisted.append(pattern)
        view = get(f"https://drive.google.com/file/d/{fid}/view", tries=3)
        download = get(f"https://drive.google.com/uc?export=download&id={fid}", tries=3)
        saved = None
        if download is not None and download.status_code == 200 and "text/html" not in download.headers.get("content-type", ""):
            m = FILENAME.search(download.headers.get("content-disposition", ""))
            rel = f"drive/{fid}/{m.group(1) if m else fid}"
            (DIR / rel).parent.mkdir(parents=True, exist_ok=True)
            (DIR / rel).write_bytes(download.content)
            manifest.records[rel] = {"path": rel, "source_url": f"https://drive.google.com/file/d/{fid}/view",
                                     "capture_timestamp": None}
            saved = rel
        for r in rows:
            if saved is None and r["statuscode"] == "200":
                saved = manifest.save_wayback(f"drive/{fid}/wayback_{r['timestamp']}.html", r["timestamp"], r["original"])
                saved = saved and str(saved.relative_to(DIR))
        attempts[fid] = {
            "linked_from": linked_from,
            "view_status": view.status_code if view is not None else None,
            "download_status": download.status_code if download is not None else None,
            "wayback_captures": [(r["timestamp"], r["original"], r["statuscode"]) for r in rows],
            "saved": saved,
            "unlisted": unlisted,
        }
        print(fid, {k: v for k, v in attempts[fid].items() if k != "wayback_captures"}, len(rows), "captures", flush=True)
        if unlisted and not saved:
            del attempts[fid]  # the next run lists it again
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(attempts, indent=1, ensure_ascii=False) + "\n")


def scribd(refresh: bool) -> None:
    for doc in SCRIBD_DELETED:
        cdx(DIR / "scribd" / "cdx" / f"{doc}.json", f"scribd.com/document/{doc}", refresh, matchType="prefix")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="list the captures again and retry every file")
    args = parser.parse_args()
    manifest = Manifest(SOURCE)
    yumpu(manifest, args.refresh)
    drive(manifest, args.refresh)
    scribd(args.refresh)
    # Other fetch scripts write files under nurj_extra/ too: take their
    # records from the manifest as it is now and add this script's.
    merged = Manifest(SOURCE)
    merged.records.update({k: v for k, v in manifest.records.items() if k.split("/")[0] in OWN})
    merged.write()


if __name__ == "__main__":
    main()

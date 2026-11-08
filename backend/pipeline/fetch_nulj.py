"""Download what survives of the Northwestern Undergraduate Law Journal into data/raw/nulj/.

NULJ (thenulj.com, founded 2019) ran a forum of short posts and a yearly
journal. The Squarespace site answers 404 to scripts, so everything comes from
archives and the journal's flipbook hosts:

- commoncrawl/: Common Crawl's captures of the site, the main source of the
  forum's full text. Each crawl's CDX index listing is saved as
  cdx/cdx-<crawl>.jsonl (with cdx-<crawl>.status: HTTP status and row count),
  and each listed record as its own gzip member,
  warc/<crawl>/<NNNN>-<timestamp>.warc.gz, numbered in (urlkey, timestamp)
  order: exactly the bytes [offset, offset + length) of the crawl's WARC file,
  fetched with a Range request. CRAWLS are the two that hold the site:
  CC-MAIN-2026-39 (294 records, captured 2026-09-05 to 09-12: 287 answered
  200, 6 302 and 1 404) and CC-MAIN-2026-43 (17 records, 2026-10-07; 11 of
  their URLs are also in 2026-39, and both captures are kept). Between them
  they give 234 forum posts (/nuljforum/<slug>), the 9 Vol. 4 articles
  (/journal-articles/) and the 2026 staff page (/our-members, 20260905135644).
  Every other crawl in collinfo.json (Common Crawl's list of crawls) is
  checked too, into cdx-older/; none holds more than the site's robots.txt
  (answering 403), so their records are not fetched.
- wayback/: the Wayback Machine's captures of the site. cdx/wb-cdx-all-200.json
  lists every capture that answered 200 (235 across 69 URLs); the newest of
  each URL is saved, and every capture of /our-members (only 20240507044303
  and 20250602161033: the Wayback Machine has no 2026 staff page), 70
  captures in all, as files/<timestamp>__<url>.<ext>, in their original form.
  This holds 3 forum posts Common Crawl lacks: classaction,
  chicagos-criminalization-of-the-homeless and
  the-us-takes-last-place-the-problem-of-paid-parental-leave. The same query
  with every status (wb-cdx-all-statuses.json) and collapsed to each URL's
  oldest capture (wb-cdx-collapse-urlkey.json) is kept for reference.
- anyflip/: Vol. 3 (2022-23), a flipbook on AnyFlip. search_config.js holds
  the text of its 111 pages (textForPages) and config.js the book's settings,
  among them its pages' image files, saved as pages/page_NNN.webp.
- issuu/: the 2021-22 issue ("Volume 1 Issue 1", 220 pages), on Issuu as
  dor1668/nulj_2022_revised_final and an earlier revision,
  dor1668/journal_nulj_final. Issuu refuses scripts (image.isu.pub answers
  403, issuu.com 404), so pages/ holds the Wayback captures of each
  document's page, which give its revision id (REVISIONS), and images/<rev>/
  each page's image as archived: the capture that answered 200 is the one
  named page_N_thumb_small.jpg, while page_N.jpg and the large and medium
  thumbnails are revisits of the same bytes; despite its name it is the full
  page, 2117x2995 or 2312x2992. The revisions differ only in pages 1-7; the
  other 213 are byte-identical. cdx/ also keeps the (empty) listings of
  issuu.com/dor1668 and issuu.com/reesenulj.

Not found anywhere (checked November 2026):
- cakeshop, a January 2023 forum post, in neither archive.
- The Vol. 4 (2024-25) issue PDF. A Common Crawl copy of the site embeds it from
  static1.squarespace.com/static/5d3be400566fab00019cc8c4/t/6916c9c655b9ed1b39d2532f/1763101126427/NULJ_VOLUME_4_TO-PUBLISH-compressed.pdf
  (uploaded 2025-11-14). That address answers 404, the Wayback Machine has no
  capture of it, and the Common Crawl indexes of CC-MAIN-2026-39, 2026-34 and
  2026-04 list none (2026-43 and 2025-51 timed out).
- The 2020-21 issue, Issuu reesenulj/docs/journal_final_nulj_final, linked
  from /the-20202021-journal-1 and /journal: no Wayback capture of
  issuu.com/reesenulj, and Issuu answers 404.

data/raw/nulj/manifest.jsonl lists each file with the URL it stands for (for
an archived copy, the original URL) and its capture timestamp; a Common Crawl
record also gives its WARC file, offset and length.

Usage: uv run python -m pipeline.fetch_nulj [--refresh]
"""

import argparse
import gzip
import json
import re
import urllib.parse

from pipeline.download import RAW, WAYBACK, Manifest, cdx, get

SOURCE = "nulj"
OUT = RAW / SOURCE
CC_INDEX = "https://index.commoncrawl.org"
CC_DATA = "https://data.commoncrawl.org"
CRAWLS = ("CC-MAIN-2026-39", "CC-MAIN-2026-43")
SITE = "thenulj.com/*"
ANYFLIP = "https://online.anyflip.com/azfta/hjhb"
# Issuu document -> (Wayback capture of its page, revision id that page gives).
REVISIONS = {
    "nulj_2022_revised_final": ("20230227144029", "220602042350-e0db808cb0d8e55c268c6e9b2e223c6c"),
    "journal_nulj_final": ("20230303003355", "220531052300-fec9d943bdd77583108d6cf21a3b1b09"),
}
# File extension for a capture, by the MIME type the CDX listing gives.
EXT = {"text/html": ".html", "application/json": ".json", "application/rss+xml": ".xml",
       "text/xml": ".xml", "text/plain": ".txt", "application/javascript": ".js",
       "image/jpeg": ".jpg", "application/pdf": ".pdf"}


def listed(m: Manifest, rel: str, query: str) -> None:
    """Record the query a saved listing answers, unless it is recorded."""
    r = m.records.setdefault(rel, {"path": rel, "source_url": None, "capture_timestamp": None})
    r["source_url"] = r["source_url"] or query


def cc_query(crawl: str, extra: str = "") -> str:
    return f"{CC_INDEX}/{crawl}-index?url={SITE}&matchType=domain&output=json{extra}"


def cc_listing(m: Manifest, folder: str, crawl: str, refresh: bool) -> list[dict]:
    """A crawl's index rows for the site, saved as <folder>/cdx-<crawl>.jsonl."""
    rows_path = OUT / folder / f"cdx-{crawl}.jsonl"
    status_path = rows_path.with_suffix(".status")
    for p in (rows_path, status_path):
        listed(m, str(p.relative_to(OUT)), cc_query(crawl))
    if status_path.exists() and not refresh:
        return [json.loads(line) for line in rows_path.open()]
    rows, status, page = [], None, 0
    while True:
        resp = get(cc_query(crawl, f"&page={page}"), timeout=180)
        status = resp.status_code if resp is not None else None
        if status != 200:
            break  # 404: the crawl holds nothing of the site
        lines = [line for line in resp.text.splitlines() if line.strip()]
        rows += [json.loads(line) for line in lines]
        page += 1
        if len(lines) < 1000:  # the index pages at 1000 rows
            break
    if status not in (200, 404) or (status == 404 and page):
        raise SystemExit(f"{crawl}: index answered {status}; rerun later")
    rows_path.parent.mkdir(parents=True, exist_ok=True)
    rows_path.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    status_path.write_text(f"{status} {len(rows)}\n")
    return rows


def is_warc(length: int):
    return lambda body: len(body) == length and gzip.decompress(body)[:5] == b"WARC/"


def common_crawl(m: Manifest, refresh: bool) -> None:
    for crawl in CRAWLS:
        rows = sorted(cc_listing(m, "commoncrawl/cdx", crawl, refresh), key=lambda r: (r["urlkey"], r["timestamp"]))
        for i, r in enumerate(rows):
            offset, length = int(r["offset"]), int(r["length"])
            m.save(f"commoncrawl/warc/{crawl}/{i:04d}-{r['timestamp']}.warc.gz", f"{CC_DATA}/{r['filename']}",
                   source_url=r["url"], timestamp=r["timestamp"], refresh=refresh, ok=(206,),
                   headers={"Range": f"bytes={offset}-{offset + length - 1}"}, check=is_warc(length),
                   warc=r["filename"], offset=offset, length=length)
        print(f"{crawl}: {len(rows)} records")
    collinfo = m.save("commoncrawl/collinfo.json", f"{CC_INDEX}/collinfo.json", refresh=refresh)
    listed(m, "commoncrawl/collinfo.json", f"{CC_INDEX}/collinfo.json")
    older = [c["id"] for c in json.loads(collinfo.read_text()) if c["id"] not in CRAWLS]
    found = {c: len(cc_listing(m, "commoncrawl/cdx-older", c, refresh)) for c in older}
    print(f"{len(older)} other crawls: {sum(1 for n in found.values() if n)} list the site, {sum(found.values())} records, not fetched")


def wayback(m: Manifest, refresh: bool) -> None:
    def listing(name: str, **params) -> list[dict]:
        rel = f"wayback/cdx/{name}.json"
        query = f"{WAYBACK}/cdx/search/cdx?" + urllib.parse.urlencode({"url": SITE, **params})
        listed(m, rel, query)
        return cdx(OUT / rel, SITE, refresh=refresh, **params)

    captures = listing("wb-cdx-all-200", filter="statuscode:200")
    listing("wb-cdx-all-statuses")
    listing("wb-cdx-collapse-urlkey", filter="statuscode:200", collapse="urlkey")
    newest = {}
    for c in captures:
        if c["urlkey"] not in newest or c["timestamp"] > newest[c["urlkey"]]["timestamp"]:
            newest[c["urlkey"]] = c
    picked = {(c["urlkey"], c["timestamp"]): c for c in newest.values()}
    for c in captures:
        if c["urlkey"].split("?")[0] == "com,thenulj)/our-members":
            picked.setdefault((c["urlkey"], c["timestamp"]), c)
    saved = 0
    for _, c in sorted(picked.items()):
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", c["original"].split("://", 1)[-1])[:150]
        rel = f"wayback/files/{c['timestamp']}__{safe}{EXT.get(c['mimetype'], '.bin')}"
        saved += bool(m.save_wayback(rel, c["timestamp"], c["original"], refresh=refresh))
    print(f"wayback: {saved} of {len(picked)} captures saved")


def anyflip(m: Manifest, refresh: bool) -> None:
    for name in ("search_config.js", "config.js"):
        m.save(f"anyflip/{name}", f"{ANYFLIP}/mobile/javascript/{name}", refresh=refresh)
    config = (OUT / "anyflip/config.js").read_text()
    pages = json.loads(re.search(r"var htmlConfig = (\{.*?\});", config, re.S).group(1))["fliphtml5_pages"]
    saved = 0
    for n, page in enumerate(pages, 1):
        # Each page's image path is relative to mobile/: ../files/large/<hash>.webp.
        url = urllib.parse.urljoin(f"{ANYFLIP}/mobile/", page["n"][0])
        saved += bool(m.save(f"anyflip/pages/page_{n:03d}.webp", url, refresh=refresh,
                             check=lambda b: b[:4] == b"RIFF" and b[8:12] == b"WEBP"))
    print(f"anyflip: {saved} of {len(pages)} page images saved")


def issuu(m: Manifest, refresh: bool) -> None:
    for slug, (ts, rev) in REVISIONS.items():
        doc = f"https://issuu.com/dor1668/docs/{slug}"
        m.save_wayback(f"issuu/pages/{ts}__{slug}.html", ts, doc, refresh=refresh)
        rel = f"issuu/cdx/wb-cdx-image-{rev}.json"
        listed(m, rel, f"{WAYBACK}/cdx/search/cdx?url=image.isu.pub/{rev}/*")
        page = {}
        for c in cdx(OUT / rel, f"image.isu.pub/{rev}/*", refresh=refresh):
            n = re.search(r"/jpg/page_(\d+)(?:_thumb_\w+)?\.jpg$", c["original"])
            if n and c["statuscode"] == "200" and (int(n.group(1)) not in page or c["timestamp"] > page[int(n.group(1))]["timestamp"]):
                page[int(n.group(1))] = c
        saved = sum(bool(m.save_wayback(f"issuu/images/{rev}/page_{n:03d}.jpg", c["timestamp"], c["original"],
                                        refresh=refresh, check=lambda b: b[:2] == b"\xff\xd8"))
                    for n, c in sorted(page.items()))
        print(f"issuu {slug}: {saved} of {len(page)} page images saved")
    for name, url in [("issuu.com_dor1668", "issuu.com/dor1668"), ("issuu.com_dor1668__", "issuu.com/dor1668/*"),
                      ("issuu.com_reesenulj", "issuu.com/reesenulj"), ("issuu.com_reesenulj__", "issuu.com/reesenulj/*")]:
        rel = f"issuu/cdx/wb-cdx-{name}.json"
        listed(m, rel, f"{WAYBACK}/cdx/search/cdx?url={url}")
        cdx(OUT / rel, url, refresh=refresh)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch saved listings and files")
    args = parser.parse_args()
    m = Manifest(SOURCE)
    try:
        common_crawl(m, args.refresh)
        wayback(m, args.refresh)
        anyflip(m, args.refresh)
        issuu(m, args.refresh)
    finally:
        m.write()


if __name__ == "__main__":
    main()

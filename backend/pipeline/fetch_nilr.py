"""Download the Northwestern Interdisciplinary Law Review (NILR) site from the Wayback Machine into data/raw/nilr/.

NILR (nilr.org, ISSN 1945-2233) was the undergraduate-edited law journal of
2008-2015. Its site survives only in the Wayback Machine: a static site in
2011-2012 and a WordPress one by 2014. From 2021 the domain is parked or
someone else's (captures of 114-12,477 bytes), and 2013-07-19 is a 155-byte
stub.

The captures are chosen from two CDX listings, with one capture per URL:
- the whole domain (matchType=domain, collapse=urlkey, statuscode 200), the
  earliest 200 of each URL, keeping HTML pages and PDFs and dropping theme
  assets, wp-content, robots.txt and the like (SKIP);
- the home page (nilr.org/ and www.nilr.org/) once a year (collapse=timestamp:4),
  for the issue announcements.
The picks are pinned in captures.json ({rel, ts, original, mimetype}), so a
rerun saves the same captures without asking the Wayback Machine; --refresh
lists them again.

Saved, each as its raw (id_) capture:
- pages/<path>_<timestamp>.html: the static site's index, 2011, issues,
  about, submissions, subscriptions and contact pages (2011-2012), the
  WordPress site's (2014), with the tables of contents of Vols. 1-5
  (issues_volume-1-number-1-september-2008 ... issues_volume-5-number-1-spring-2012,
  all 2014-10-25), and the home page per year, 2011 and 2013-2026.
- articles/<name>.pdf: the 15 PDFs under nilr.org/articles/, from captures of
  2012-10-30: 2011AroldFriedman, 2011Godwin, 2011Jackson, 2011Spiropoulos,
  2011Tao, 2011TableofContents, 2012Baek, 2012Cox, 2012Delahunty, 2012Gee,
  2012Krishnamurthy, 2012Musa, 2012Zunker, 2012frontpage and
  2012letterfromtheeditors.

The 2011 PDFs' id_ requests often answer 404, or fall through to a 2023
HTML capture of the parked domain, and then serve the PDF on another try
(the if_, im_ and plain forms behave the same), so PDFs are tried up to
TRIES times. All six failed on 2026-11-06 and 07 and came through on
2026-11-08.

No Vol. 6 or 7 page or PDF is in the CDX listing. No issues/volume-8 page was
captured, and the 2015-2018 home pages name no volume, so the Vol. 8 no. 1
(Spring 2015) issue is not here.

Writes manifest.jsonl (see pipeline.download).

Usage: uv run python -m pipeline.fetch_nilr [--refresh]
"""

import argparse
import json
import re
import time

from pipeline.download import RAW, Manifest, cdx

SOURCE = "nilr"
CAPTURES = RAW / SOURCE / "captures.json"
# The Wayback Machine at times answers a PDF capture with 404, or with a later
# HTML capture of the same address, and serves it on another try.
TRIES = 6
SKIP = re.compile(r"wp-content|wp-includes|well-known|ads\.txt|xmlrpc|sitemap|cgi-sys|robots\.txt|"
                  r"/css/|/images/|/img-sys/|gtnjs|/10$", re.I)


def rel_path(original: str, ts: str) -> str:
    path = re.sub(r"^https?://(www\.)?nilr\.org(:80)?/?", "", original).strip("/") or "home"
    path = re.sub(r"[^A-Za-z0-9._-]+", "_", path)
    if "/articles/" in original:
        return f"articles/{path.removeprefix('articles_')}"
    return f"pages/{path}_{ts}.html"


def list_captures(refresh: bool) -> list[dict]:
    rows = cdx(RAW / SOURCE / "cdx" / "domain.json", "nilr.org", refresh,
               matchType="domain", collapse="urlkey", filter="statuscode:200")
    keep = [r for r in rows if r["mimetype"] in ("text/html", "application/pdf") and not SKIP.search(r["original"])]
    for host in ("nilr.org/", "www.nilr.org/"):
        name = host.strip("/").replace(".", "_")
        keep += [r for r in cdx(RAW / SOURCE / "cdx" / f"home_{name}.json", host, refresh,
                                filter="statuscode:200", collapse="timestamp:4")
                 if r["mimetype"] == "text/html"]
    out, seen = [], set()
    for r in keep:
        rel = rel_path(r["original"], r["timestamp"])
        if rel not in seen:
            seen.add(rel)
            out.append({"rel": rel, "ts": r["timestamp"], "original": r["original"], "mimetype": r["mimetype"]})
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="list the captures again and refetch them")
    args = parser.parse_args()

    if args.refresh or not CAPTURES.exists():
        CAPTURES.write_text(json.dumps(list_captures(args.refresh), indent=1) + "\n")
    captures = json.loads(CAPTURES.read_text())
    manifest = Manifest(SOURCE)
    failed = []
    for c in captures:
        pdf = c["mimetype"] == "application/pdf"
        check = (lambda b: b.startswith(b"%PDF")) if pdf else None
        for attempt in range(TRIES if pdf else 1):
            if manifest.save_wayback(c["rel"], c["ts"], c["original"], refresh=args.refresh, check=check):
                break
            time.sleep(10)
        else:
            failed.append(c["rel"])
    manifest.write()
    print(f"{len(captures)} captures, {len(failed)} not saved: {failed}")


if __name__ == "__main__":
    main()

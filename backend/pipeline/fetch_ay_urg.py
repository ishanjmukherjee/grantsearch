"""Download the academic-year URG winner pages and OUR's sample grant proposals into data/raw/ay_urg/.

Academic-year Undergraduate Research Grants were announced a cycle at a
time, 2006-07 to 2014-15, on pages that survive only in the Wayback
Machine (wayback/, raw captures). Each saved file is named for the academic
year it covers and the capture's timestamp:

- 2006-09: OUR's "previous winners" page, 2006-07 to 2008-09 on one page
  (the README's capture, 20140202045558).
- 2010-11 to 2013-14: the posts under urnu-news-and-events/. 2010-11 has
  all five cycles (October, with names but no titles, November to
  February); 2011-12 October, November and winter quarter; 2012-13 fall
  quarter and the 4th and 5th cycles, which also list Conference Travel
  Grants; 2013-14 fall quarter. The 4th and 5th cycle slugs come from a
  prefix listing of the congratulations-* posts (18 in all).
- 2013-14 winter quarter's post (congratulations-winter-quarter-academic-
  year-urg-winners, March 7, 2014) was never captured; it is in full in
  the news listing capture of 20140820084138, the one SURG 2014 is read
  from.
- 2014-15: fall-2014-winners and winter-2015-grant-winners (the README's
  captures), each followed by Conference Travel and Language Grants.
- extra_: the Conference Travel Grant winners post, not a URG list, and the
  Provost's URG awards index (last updated February 19, 2010), which stops
  at 2008-09.

Where the README links a capture it is saved; otherwise the earliest 200
capture. Every capture is pinned below. cdx/ keeps the listing each was
picked from. 2009-10 was never posted, and no list from 2015-16 on was
found anywhere.

sample-grant-proposals/ holds OUR's sample grant proposals page (live) and
every file it links: 41 PDFs, 10 named Upd-AYURG-*, 29 Upd-SURG-*,
Upd-Chemistry-PROTACs.pdf (its program unnamed) and a proposal-writing
guide. The README's estimate of "about 15 AYURG sample proposals" is high:
there are 10, or 11 with PROTACs. The files are read from the saved page,
so a rerun downloads the same set.

Fetched 2026-11-06. Nothing failed.

Usage: uv run python -m pipeline.fetch_ay_urg [--refresh]
"""

import argparse
import re
import urllib.parse

from pipeline.download import Manifest

SOURCE = "ay_urg"
OUR = "undergradresearch.northwestern.edu"
NEWS = f"http://{OUR}/urnu-news-and-events/"
SAMPLES = f"https://{OUR}/advising/sample-grant-proposals/"

# Saved name: (capture timestamp, URL as captured, CDX listing name).
ARCHIVED = {
    "2006-09_previous-winners-academic-year-urg": ("20140202045558", f"https://{OUR}/previous-winners-academic-year-urg"),
    "2010-11_new-academic-year-urg-winners": ("20140202013800", NEWS + "congratulations-new-academic-year-urg-winners"),
    "2010-11_november-urg-winners": ("20140202053243", NEWS + "congratulations-november-urg-winners"),
    "2010-11_december-urg-winners": ("20140202053325", NEWS + "congratulations-december-urg-winners"),
    "2010-11_january-urg-winners": ("20140202052850", NEWS + "congratulations-january-urg-winners"),
    "2010-11_february-urg-winners": ("20140202052933", NEWS + "congratulations-february-urg-winners"),
    "2011-12_october-urg-winners": ("20140202052655", NEWS + "congratulations-october-urg-winners"),
    "2011-12_november-urg-winners-0": ("20140202052737", NEWS + "congratulations-november-urg-winners-0"),
    "2011-12_recent-academic-year-urg-winners": ("20140202013109", NEWS + "congratulations-recent-academic-year-urg-winners"),
    "2012-13_fall-quarter-urg-winners": ("20130202073549", NEWS + "congratulations-fall-quarter-urg-winners"),
    "2012-13_4th-cycle": ("20140202013914", NEWS + "congratulations-4th-cycle-undergraduate-research-grant-winners-and-conference-t"),
    "2012-13_5th-cycle": ("20140202013657", NEWS + "congratulations-5th-cycle-undergraduate-research-grant-winners-and-conference-t"),
    "2013-14_fall-quarter": ("20140202004101", NEWS + "congratulations-fall-quarter-undergraduate-research-grant-winners-and-conferenc"),
    "2013-14_latest-news-page-1": ("20140820084138", NEWS + "latest-news?page=1"),
    "2014-15_fall-2014-winners": ("20141226004716", f"http://{OUR}:80/fall-2014-winners"),
    "2014-15_winter-2015-grant-winners": ("20150330024137", f"http://{OUR}/winter-2015-grant-winners"),
    "extra_conference-travel-grant-winners": ("20140202012508", NEWS + "congratulations-conference-travel-grant-winners"),
    "extra_provost-urg-awards-index": ("20100527150638", "http://www.northwestern.edu/undergrad-research/awards/index.htm"),
}
# The never-captured winter 2013-14 post is listed too, to record that its listing is empty.
NEVER_CAPTURED = {"2013-14_winter-quarter": NEWS + "congratulations-winter-quarter-academic-year-urg-winners"}
PREFIX_LISTING = ("congratulations-posts", f"{OUR}/urnu-news-and-events/congrat", {"matchType": "prefix", "filter": "statuscode:200", "collapse": "urlkey"})



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch the saved files (not the CDX listings)")
    args = parser.parse_args()
    m = Manifest(SOURCE)

    m.listing(*PREFIX_LISTING)
    for name, url in NEVER_CAPTURED.items():
        m.listing(name, url.split("://")[1], {"filter": "statuscode:200"})
    for name, (ts, url) in ARCHIVED.items():
        rows = m.listing(name, url.split("://")[1].replace(":80/", "/"), {"filter": "statuscode:200"})
        if ts not in {r["timestamp"] for r in rows}:
            print(f"note: {name}: pinned capture {ts} is not in its listing")
        m.save_wayback(f"wayback/{name}_{ts}.html", ts, url, refresh=args.refresh)

    page = m.save("sample-grant-proposals/page.html", SAMPLES, refresh=args.refresh)
    html = page.read_text(encoding="utf-8")
    links = sorted(set(re.findall(r'href="([^"]+\.(?:pdf|docx?|pptx?))"', html, re.I)))
    for link in links:
        link = urllib.parse.urljoin(SAMPLES, link.replace("&amp;", "&"))
        name = urllib.parse.unquote(link.rsplit("/", 1)[1])
        m.save(f"sample-grant-proposals/files/{name}", link, refresh=args.refresh)
    print(f"{len(links)} sample files linked")
    m.write()


if __name__ == "__main__":
    main()

"""Download the Leopold Fellows pages into data/raw/leopold/.

The Chabraja Center for Historical Studies pays undergraduates of any major,
Leopold Fellows, to work as research assistants on a faculty member's
history project. Its pages list the fellows each year since 2008-09, with
class, school, faculty mentor and project title, but no descriptions.
Returning fellows are marked with an asterisk, so many projects repeat
across years. The Library Leopold Fellows (new in 2026-27) are library
student employees rather than research assistants.

Saved (fetched 2026-11-06 and 07):

- live/main.html and live/previous.html: the current list and "previous
  Leopold fellows", live.
- wayback/main_<ts>.html (16) and wayback/previous_<ts>.html (8): one
  capture per year of each page since the Center moved them to
  /fellowships/leopold-fellows/ in 2015. The main page was captured both
  as .../leopold-fellows/ and .../leopold-fellows/index.html, so some years
  have one of each.
- wayback-pre2015/: the pages before that move, one capture per year:
  leopold.htm (2008-2013), /leopold-fellows/ and its index.html and
  previous-leopold-fellows.html (2014 and 2015), Leopoldresearch2009-2010.htm
  (2010 and 2012, the same bytes), two calls for applications, and
  documents/Leopoldfacultyprojects.doc, a Word file of faculty projects
  (2010 and 2012).
- cdx/: the Wayback listings these captures were picked from (200
  captures, one per year, collapse=timestamp:4), and the listing of the
  Center's domain the pre-2015 pages were found in.

Every capture is pinned below, so a rerun saves the same files whatever
the Wayback Machine has captured since. Nothing failed. The Wayback Machine
answered 429 to a browser-style User-Agent for a while, and served
everything at one request per 3 s with a plain one.

Usage: uv run python -m pipeline.fetch_leopold [--refresh]
"""

import argparse

from pipeline.download import Manifest

SOURCE = "leopold"
BASE = "https://historicalstudies.northwestern.edu/fellowships/leopold-fellows/"
OLD = "http://www.historicalstudies.northwestern.edu"
NEW_HTTP = "http://www.historicalstudies.northwestern.edu:80/fellowships/leopold-fellows/"
NEW_WWW = "https://www.historicalstudies.northwestern.edu/fellowships/leopold-fellows/"

LIVE = {
    "live/main.html": BASE,
    "live/previous.html": BASE + "previous-leopold-fellows.html",
}
# Saved path: (capture timestamp, URL as captured).
ARCHIVED = {
    **{f"wayback/main_{ts}.html": (ts, url) for ts, url in [
        ("20151028004402", NEW_HTTP),
        ("20160124032244", NEW_HTTP),
        ("20170307184431", NEW_HTTP),
        ("20180125111217", NEW_HTTP),
        ("20190415180006", NEW_WWW),
        ("20200707013552", NEW_WWW),
        ("20201124032333", BASE + "index.html"),
        ("20210706210601", BASE),
        ("20210707015521", BASE + "index.html"),
        ("20220705150029", BASE),
        ("20220705151238", BASE + "index.html"),
        ("20230529081414", BASE + "index.html"),
        ("20230531050116", BASE),
        ("20240223001159", BASE),
        ("20250118194348", BASE),
        ("20260201012931", BASE),
    ]},
    **{f"wayback/previous_{ts}.html": (ts, url + "previous-leopold-fellows.html") for ts, url in [
        ("20160416014337", NEW_HTTP),
        ("20170430130027", NEW_HTTP),
        ("20190415180007", NEW_WWW),
        ("20200706203711", NEW_WWW),
        ("20210707015552", BASE),
        ("20230529080126", BASE),
        ("20240222235004", BASE),
        ("20260201072842", BASE),
    ]},
    **{f"wayback-pre2015/old-{name}_{ts}.{ext}": (ts, OLD + path) for name, path, ext, ts in [
        ("leopold-htm", "/leopold.htm", "html", "20080820213955"),
        ("leopold-htm", "/leopold.htm", "html", "20100609010201"),
        ("leopold-htm", "/leopold.htm", "html", "20110720014523"),
        ("leopold-htm", ":80/leopold.htm", "html", "20120106235657"),
        ("leopold-htm", ":80/leopold.htm", "html", "20130411050120"),
        ("leopold-fellows", "/leopold-fellows/", "html", "20140205220220"),
        ("leopold-fellows", ":80/leopold-fellows/", "html", "20150227144501"),
        ("leopold-fellows-index", "/leopold-fellows/index.html", "html", "20140205221441"),
        ("previous-leopold-fellows", "/leopold-fellows/previous-leopold-fellows.html", "html", "20140205220132"),
        ("previous-leopold-fellows", ":80/leopold-fellows/previous-leopold-fellows.html", "html", "20150227133525"),
        ("Leopoldresearch2009-2010", "/Leopoldresearch2009-2010.htm", "html", "20100609032657"),
        ("Leopoldresearch2009-2010", "/Leopoldresearch2009-2010.htm", "html", "20120523152419"),
        ("CallfornewLF", "/CallfornewLF.htm", "html", "20100609015408"),
        ("LFCallforApplications", "/LFCallforApplications.htm", "html", "20120523152421"),
        ("Leopoldfacultyprojects", "/documents/Leopoldfacultyprojects.doc", "doc", "20100609020013"),
        ("Leopoldfacultyprojects", "/documents/Leopoldfacultyprojects.doc", "doc", "20120523152423"),
    ]},
}
YEARLY = {"filter": "statuscode:200", "collapse": "timestamp:4"}
H = "www.historicalstudies.northwestern.edu/"
# Saved name: (URL, CDX parameters).
LISTINGS = {
    "main": (BASE.split("://")[1], YEARLY),
    "main-index": (BASE.split("://")[1] + "index.html", YEARLY),
    "previous": (BASE.split("://")[1] + "previous-leopold-fellows.html", YEARLY),
    "domain-leopold-pre2015": ("historicalstudies.northwestern.edu", {
        "matchType": "domain", "to": "2014", "collapse": "urlkey",
        "filter": ["statuscode:200", "original:.*[Ll]eopold.*"]}),
    **{f"old-{name}": (H + path, YEARLY) for name, path in [
        ("leopold-htm", "leopold.htm"),
        ("leopold-fellows", "leopold-fellows/"),
        ("leopold-fellows-index", "leopold-fellows/index.html"),
        ("previous-leopold-fellows", "leopold-fellows/previous-leopold-fellows.html"),
        ("Leopoldresearch2009-2010", "Leopoldresearch2009-2010.htm"),
        ("CallfornewLF", "CallfornewLF.htm"),
        ("LFCallforApplications", "LFCallforApplications.htm"),
        ("Leopoldfacultyprojects", "documents/Leopoldfacultyprojects.doc"),
    ]},
}



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch the saved files (not the CDX listings)")
    args = parser.parse_args()
    m = Manifest(SOURCE)
    for name, (url, params) in LISTINGS.items():
        m.listing(name, url, params)
    for rel, url in LIVE.items():
        m.save(rel, url, refresh=args.refresh)
    for rel, (ts, url) in ARCHIVED.items():
        m.save_wayback(rel, ts, url, refresh=args.refresh)
    m.write()


if __name__ == "__main__":
    main()

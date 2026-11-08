"""Download the smaller department thesis and honors lists into data/raw/thesis_lists/.

These are the lists too small to have a scraper of their own yet, saved as
served (live, fetched 2026-11-06 and 07, but for one capture):

- sociology/past-senior-thesis.html: Sociology's past senior theses
  (about 35 titles, 2024-2026).
- biosci/recent-honors-recipients.html: Biological Sciences' recent honors
  recipients, with supervisors (about 20, 2024-25).
- buffett/awardees.html: the Buffett Institute's international senior
  thesis research grant awardees (19).
- mellon-mays/our-fellows.html: the Mellon Mays fellows, 85 bios that
  describe their thesis topics, all on one page.
- anthropology/: the theses index and the pages it links (past
  submissions, 2023 honors theses, thesis award winners), the spring 2026
  newsletter's awards page and the 2022 graduates news post, found from
  the index and by web search. pdfs/ holds the yearly lists the past
  submissions page links, which exist only for 2013-14, 2015, 2016 and
  2016-17 (later years are in the HTML pages), and the 2012-13 senior
  scholarship grant awards, found by web search and linked from no thesis
  page.
- sesp/: SESP's honors news posts, 2021-2026, found by reading the SESP news
  index of each year 2022-2026 (2020 and 2021 have no index page). The 2021
  post now answers 404, so it is the latest of its five Wayback captures
  (20260513065401); cdx/ keeps that listing.

Every PDF a saved page links whose address looks thesis-related (THESIS_LINK)
is downloaded, so the set follows from the saved pages. One link was
skipped as not a thesis list: SESP's 2024 convocation remarks
(anna-smith_2024-convocation-remarks.pdf). Nothing failed.

Usage: uv run python -m pipeline.fetch_thesis_lists [--refresh]
"""

import argparse
import html as htmllib
import re
import urllib.parse

from pipeline.download import Manifest

SOURCE = "thesis_lists"
ANTH = "https://anthropology.northwestern.edu/"
SESP = "https://sesp.northwestern.edu/news-events/sesp-news/"

PAGES = {
    "sociology/past-senior-thesis.html": "https://sociology.northwestern.edu/undergraduate/research-funding/past-senior-thesis.html",
    "biosci/recent-honors-recipients.html": "https://biosci.northwestern.edu/research/recent-honors-recipients.html",
    "buffett/awardees.html": "https://buffett.northwestern.edu/programs/undergraduate-opportunities/international-senior-thesis-research-grant/awardees.html",
    "mellon-mays/our-fellows.html": "https://www.northwestern.edu/fellowships/mellon-mays-fellowship/our-fellows/",
    "anthropology/theses-index.html": ANTH + "undergraduate/theses/",
    "anthropology/past-theses-submissions.html": ANTH + "undergraduate/theses/past-theses-submissions.html",
    "anthropology/2023-honors-theses.html": ANTH + "undergraduate/theses/2023-honors-theses.html",
    "anthropology/theses-award-winners.html": ANTH + "undergraduate/theses/theses-award-winners.html",
    "anthropology/newsletter-spring-26-awards-honors.html": ANTH + "about/newsletter/spring-26/awards-honors.html",
    "anthropology/news-2022-congratulations-to-our-2022-graduates.html": ANTH + "about/news/2022/congratulations-to-our-2022-graduates.html",
    "sesp/2022-meet-sesps-2022-senior-honors-students.html": SESP + "2022/meet-sesps-2022-senior-honors-students.html",
    "sesp/2023-sesp-faculty-recognize-honors-students.html": SESP + "2023/sesp-faculty-recognize-honors-students.html",
    "sesp/2024-meet-sesps-2024-honors-students.html": SESP + "2024/meet-sesps-2024-honors-students.html",
    "sesp/2024-undergraduate-honors-and-awards.html": SESP + "2024/2024-undergraduate-honors-and-awards.html",
    "sesp/2025-meet-the-2025-sesp-honors-students.html": SESP + "2025/meet-the-2025-sesp-honors-students.html",
    "sesp/2026-undergraduate-researchers-earn-senior-honors.html": SESP + "2026/undergraduate-researchers-earn-senior-honors.html",
}
EXTRA_FILES = {
    "anthropology/pdfs/SeniorScholarshipGrantAwards2012-2013.pdf": ANTH + "documents/undergraduate/SeniorScholarshipGrantAwards2012-2013.pdf",
}
SESP_2021 = SESP + "2021/honors-students-present-senior-thesis-projects.html"
SESP_2021_CAPTURE = "20260513065401"
THESIS_LINK = re.compile(r"thes|honor|capstone|senior|award|fellow", re.I)



def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch the saved files (not the CDX listings)")
    args = parser.parse_args()
    m = Manifest(SOURCE)
    for rel, url in PAGES.items():
        path = m.save(rel, url, refresh=args.refresh)
        if path is None:
            continue
        page = path.read_text(encoding="utf-8", errors="replace")
        for href in re.findall(r'href="([^"]+\.pdf)"', page, re.I):
            link = urllib.parse.quote(urllib.parse.urljoin(url, htmllib.unescape(href)), safe=":/%?=&")
            if not THESIS_LINK.search(link):
                continue
            name = urllib.parse.unquote(link.rsplit("/", 1)[1])
            m.save(f"{rel.split('/')[0]}/pdfs/{name}", link, refresh=args.refresh, check=lambda b: b.startswith(b"%PDF"))
    for rel, url in EXTRA_FILES.items():
        m.save(rel, url, refresh=args.refresh, check=lambda b: b.startswith(b"%PDF"))
    m.listing("sesp-2021", SESP_2021.split("://")[1], {"filter": "statuscode:200"})
    m.save_wayback(f"sesp/2021-honors-students-present-senior-thesis-projects_{SESP_2021_CAPTURE}.html",
                   SESP_2021_CAPTURE, SESP_2021, refresh=args.refresh)
    m.write()


if __name__ == "__main__":
    main()

"""Download OUR's student features, peer mentor profiles and Fletcher Award stories into data/raw/our_features/.

These are the public pages most likely to name a SURG holder's faculty
mentor, which OUR's winner lists from 2018 on leave out (fetched 2026-11-06
and 07):

- Student features, OUR's WordPress category 379 ("Student Feature"):
  api/ holds both pages of the category's posts from the WordPress API (154
  posts, 2021-08-30 to 2026-05-14) and the category record; posts/ holds
  each post's page as served, named <date>_<slug>.html. The posts are read
  from the saved API pages, so a rerun saves the same set. From late 2023
  on they give full names; about 12 name a mentor and 5 the SURG sponsor
  explicitly.
- Peer mentor profiles, about 30-40 SURG holders with the lab or professor
  they worked with: peer-mentors/profiles-live.html (the 2022-23 cohort),
  the profiles page's distinct captures from 2019 on (20210709175511, the
  2021-22 cohort the README links, and 20230708174759), and every distinct
  capture, 2017-2020, of the older peer-research-mentor-program page (43;
  there is none from 2021). Those average about 0.5 MB and many are
  near-duplicates, as their digests differ where the profiles may not.
- Fletcher Awards, for the best SURG projects of each summer and academic
  year, which name the faculty mentor. Found by web search, the OUR
  WordPress search API (saved as fletcher/our/api-search-fletcher-*.json)
  and a CDX listing of OUR's site:
  - news-northwestern/: Northwestern Now stories from 2014-06, 2014-12,
    2016-12 and 2023-01 (summer 2022, the README's link), live.
    news-northwestern-wayback/: 2012-11 and 2013-12, which now 404 live,
    from their latest captures.
  - our/: OUR's Fletcher awardees page, the 2015 and 2016 academic-year
    winner pages, AY-Fletcher-Awards-2020-21.pdf (the README's), the
    2021-22 and 2022-23 slides and images (all the Fletcher media in its
    library) and its student features page. our-wayback/: the old Drupal
    site's 2015 and 2016 winner pages and three posts on the award from its
    news section, captured in 2014.
  - other/: Weinberg news 2023-02, SESP news 2024, McCormick news 2014-06,
    the Provost's faculty newsletter 2025-12 (2025 mentors) and the Daily
    Northwestern's 2023 article.
  No story was found for summer 2015 or 2017-2021, nor for 2023-2025 beyond
  the Weinberg, SESP and Provost items, and no academic-year list for
  2017-18 to 2019-20 or after 2022-23.

Every capture is pinned below; cdx/ keeps the listings they were picked
from.

Usage: uv run python -m pipeline.fetch_our_features [--refresh]
"""

import argparse
import json
import re

from pipeline.download import Manifest

SOURCE = "our_features"
OUR = "https://undergradresearch.northwestern.edu"
HTTP = "http://undergradresearch.northwestern.edu"
HTTP80 = "http://undergradresearch.northwestern.edu:80"
HTTPS = OUR
POST = re.compile(r"https://undergradresearch\.northwestern\.edu/(\d{4})/(\d\d)/(\d\d)/([^/]+)/?$")

PROGRAM = "/our-grants-programs/peer-research-mentor-program"
PROFILES = "/resources/peer-mentors/profiles/"
# Capture timestamp and the scheme and port the page was captured under.
PROGRAM_CAPTURES = [
    ("20170512092535", HTTP80), ("20170601155736", HTTP), ("20170601175920", HTTPS),
    ("20170613192107", HTTP80), ("20170620182150", HTTP), ("20170629213533", HTTP80),
    ("20170814153856", HTTP80), ("20171014021825", HTTP80), ("20171113173346", HTTP80),
    ("20171221011926", HTTP80), ("20171222101745", HTTP80), ("20180221031144", HTTP80),
    ("20180423011054", HTTP80), ("20180623175834", HTTP80), ("20180823111940", HTTP80),
    ("20181023135255", HTTP80), ("20181109022722", HTTP), ("20181119182333", HTTP),
    ("20181121200222", HTTP), ("20190415164357", HTTP), ("20190415181049", HTTPS),
    ("20190505052334", HTTP80), ("20190506175958", HTTP80), ("20190702212632", HTTP),
    ("20190703003358", HTTPS), ("20190718233433", HTTP), ("20190718234403", HTTPS),
    ("20190720161833", HTTP80), ("20190825023317", HTTP), ("20191014050952", HTTP80),
    ("20191022033647", HTTP), ("20191022035148", HTTPS), ("20191207112148", HTTP),
    ("20191213083214", HTTP80), ("20200211134812", HTTP80), ("20200315101826", HTTP80),
    ("20200514141054", HTTP80), ("20200707012954", HTTP), ("20200708134224", HTTPS),
    ("20200711005059", HTTP), ("20200711115211", HTTPS), ("20200713204243", HTTP80),
    ("20200804194316", HTTP),
]
PROFILE_CAPTURES = ["20210709175511", "20230708174759"]

NEWS = "https://news.northwestern.edu/stories/"
FLETCHER_LIVE = {
    "news-northwestern/2014-06-outstanding-undergraduate-researcher-honored.html": NEWS + "2014/06/outstanding-undergraduate-researcher-honored",
    "news-northwestern/2014-12-undergraduates-honored-for-diverse-research.html": NEWS + "2014/12/undergraduates-honored-for-diverse-research",
    "news-northwestern/2016-12-outstanding-undergraduate-research-recognized.html": NEWS + "2016/12/outstanding-undergraduate-research-recognized-with-fletcher-awards",
    "news-northwestern/2023-01-budding-researchers-honored.html": NEWS + "2023/01/budding-researchers-honored-with-fletcher-awards",
    "our/fletcher-awardees.html": f"{OUR}/fletcher-awardees/",
    "our/academic-year-fletcher-award-winner-2015.html": f"{OUR}/featured-student-researchers/academic-year-fletcher-award-winner-2015/",
    "our/academic-year-fletcher-award-winners-2016.html": f"{OUR}/featured-student-researchers/academic-year-fletcher-award-winners-2016/",
    "our/AY-Fletcher-Awards-2020-21.pdf": f"{OUR}/files/2016/03/AY-Fletcher-Awards-2020-21.pdf",
    "our/AY-Fletcher-Awards-2021-22.pptx": f"{OUR}/files/2016/03/AY-Fletcher-Awards-2021-22.pptx",
    "our/AY-Fletcher-Awards-2021-22.jpg": f"{OUR}/files/2016/03/AY-Fletcher-Awards-2021-22.jpg",
    "our/AY-22-Fletcher-Awards.png": f"{OUR}/files/2022/05/AY-22-Fletcher-Awards.png",
    "our/AY-Fletcher-Awards-2022-23.pptx": f"{OUR}/files/2023/07/AY-Fletcher-Awards-2022-23.pptx",
    "our/student-features.html": f"{OUR}/student-features/",
    "our/api-search-fletcher-pages.json": f"{OUR}/wp-json/wp/v2/pages?search=fletcher&per_page=100",
    "our/api-search-fletcher-media.json": f"{OUR}/wp-json/wp/v2/media?search=fletcher&per_page=100",
    "our/api-search-fletcher-posts.json": f"{OUR}/wp-json/wp/v2/posts?search=fletcher&per_page=100",
    "other/weinberg-2023-02-three-weinberg-undergraduates.html": "https://news.weinberg.northwestern.edu/2023/02/03/three-weinberg-undergraduates-recognized-with-fletcher-awards/",
    "other/sesp-2024-haase-zhong-honored.html": "https://sesp.northwestern.edu/news-events/sesp-news/2024/haase-zhong-honored-at-fletcher-awards.html",
    "other/mccormick-2014-06-outstanding-undergraduate-researcher-honored.html": "https://mccormick.northwestern.edu/news/articles/2014/06/outstanding-undergraduate-researcher-honored.html",
    "other/provost-faculty-newsletter-2025-12.html": "https://www.northwestern.edu/provost/news/newsletters/faculty-2025-12.html",
    "other/dailynorthwestern-p270891.html": "https://dailynorthwestern.com/?p=270891",
}
# Saved path under fletcher/: (capture timestamp, URL as captured).
FLETCHER_ARCHIVED = {
    "news-northwestern-wayback/2012-11-best-of-the-best_20220416122914.html":
        ("20220416122914", NEWS + "2012/11/best-of-the-best-honored-for-outstanding-undergraduate-research/"),
    "news-northwestern-wayback/2013-12-fletcher-awards-honor-outstanding-undergraduate-research_20220416082340.html":
        ("20220416082340", NEWS + "2013/12/fletcher-awards-honor-outstanding-undergraduate-research/"),
    **{f"our-wayback/{slug.rsplit('/', 1)[-1]}_{ts}.html": (ts, f"{HTTP}/{slug}") for slug, ts in [
        ("academic-year-fletcher-award-winner-2015", "20150905134941"),
        ("academic-year-fletcher-award-winners-2016", "20160601175754"),
        ("urnu-news-and-events/fletcher-undergraduate-research-grant-awards", "20140202013201"),
        ("urnu-news-and-events/fletcher-urg-prize-winners-new-award", "20140202012923"),
        ("urnu-news-and-events/new-fletcher-urg-award-ceremony", "20140202014039"),
    ]},
}
# Saved name: (URL, CDX parameters), the listings the captures above were picked from.
DISTINCT = {"filter": "statuscode:200", "collapse": "digest"}
LISTINGS = {
    "peer-research-mentor-program": ("undergradresearch.northwestern.edu" + PROGRAM, {**DISTINCT, "from": "2017", "to": "2021"}),
    "peer-mentor-profiles": ("undergradresearch.northwestern.edu" + PROFILES, {**DISTINCT, "from": "2019", "to": "2026"}),
    "news-2012-11-best-of-the-best": ("news.northwestern.edu/stories/2012/11/best-of-the-best-honored-for-outstanding-undergraduate-research",
                                      {"matchType": "prefix", "filter": ["statuscode:200", "mimetype:text/html"]}),
    "news-2013-12-fletcher-awards": ("news.northwestern.edu/stories/2013/12/fletcher-awards-honor-outstanding-undergraduate-research",
                                     {"matchType": "prefix", "filter": ["statuscode:200", "mimetype:text/html"]}),
    "our-site-fletcher": ("undergradresearch.northwestern.edu", {
        "matchType": "domain", "collapse": "urlkey", "filter": ["statuscode:200", "original:.*[Ff]letcher.*"]}),
}



def features(m: Manifest, refresh: bool) -> None:
    posts, page = [], 1
    while True:
        saved = m.save(f"api/posts-cat379-p{page}.json",
                       f"{OUR}/wp-json/wp/v2/posts?categories=379&per_page=100&page={page}", refresh=refresh)
        data = json.loads(saved.read_text())
        posts += data
        if len(data) < 100:
            break
        page += 1
    m.save("api/category-379.json", f"{OUR}/wp-json/wp/v2/categories/379", refresh=refresh)
    for p in posts:
        d = POST.match(p["link"])
        name = f"{d.group(1)}-{d.group(2)}-{d.group(3)}_{d.group(4)}" if d else f"id{p['id']}"
        m.save(f"posts/{name}.html", p["link"], refresh=refresh)
    print(f"{len(posts)} student features")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch the saved files (not the CDX listings)")
    args = parser.parse_args()
    m = Manifest(SOURCE)
    for name, (url, params) in LISTINGS.items():
        m.listing(name, url, params)
    features(m, args.refresh)
    m.save("peer-mentors/profiles-live.html", OUR + PROFILES, refresh=args.refresh)
    for ts in PROFILE_CAPTURES:
        m.save_wayback(f"peer-mentors/profiles-wayback/{ts}.html", ts, OUR + PROFILES, refresh=args.refresh)
    for ts, base in PROGRAM_CAPTURES:
        m.save_wayback(f"peer-mentors/peer-research-mentor-program-wayback/{ts}.html", ts, base + PROGRAM,
                       refresh=args.refresh)
    for rel, url in FLETCHER_LIVE.items():
        m.save("fletcher/" + rel, url, refresh=args.refresh)
    for rel, (ts, url) in FLETCHER_ARCHIVED.items():
        m.save_wayback("fletcher/" + rel, ts, url, refresh=args.refresh)
    m.write()


if __name__ == "__main__":
    main()

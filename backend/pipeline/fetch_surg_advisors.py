"""Download the scattered pages that name SURG faculty sponsors into data/raw/surg_advisors/.

The SURG winner lists for 2018 on name no faculty sponsors, and only OUR's
application portal has them all. A few public pages name some (fetched
2026-11-06, live but for one capture):

- isen-2018-...: ISEN's 2018 post on the five SURGs it co-funded, from the
  README's Wayback capture (20180709212807).
- ng2-neurogenetics-feature-2023.html: Neurology's 2023 feature on the NG2
  neurogenetics SURGs (two).
- scheidt-group-news.html, haase-lab-congrats-to-uras-for-surg.html,
  kimchi-lab-team.html: lab pages that name their SURG students (the
  Scheidt group's news is one page).

dailynorthwestern/ holds every Daily Northwestern article that mentions a
SURG ("SURG" or "Summer Undergraduate Research Grant" in its text): 35,
2005-2026, fetched 2026-11-08. Some name a grantee's faculty sponsor or
mentor; others describe SURG projects, or the program itself (record
application numbers, the 2023 suspension of URAP, the 2026 cap on
applications per lab). They were found with the site's WordPress search
API, which matches substrings: every result of the searches "SURG" (1,939
posts, mostly surgery), "Summer Undergraduate Research Grant" (136),
"undergraduate research grant" (362) and "Office of Undergraduate Research
grant" (190), plus 1,400 of the 7,531 results for "URG", was read, and the
articles whose text mentions a SURG kept. search.json lists them. The 2023
Fletcher Awards article is also in our_features.

Usage: uv run python -m pipeline.fetch_surg_advisors [--refresh]
"""

import argparse
import json

from pipeline.download import Manifest

SOURCE = "surg_advisors"
DAILY = "https://dailynorthwestern.com/"

LIVE = {
    "ng2-neurogenetics-feature-2023.html": "https://www.neurology.northwestern.edu/about/news/2023/neurogenetics-ng2-feature-2023.html",
    "scheidt-group-news.html": "https://scheidtgroup.northwestern.edu/news/",
    "haase-lab-congrats-to-uras-for-surg.html": "https://haaselab.sesp.northwestern.edu/2024/04/18/congrats-to-uras-for-surg/",
    "kimchi-lab-team.html": "https://kimchilab.org/team/",
}
ISEN = ("20180709212807", "http://isen.northwestern.edu/summer-science-isen-funds-five-undergraduate-research-grants")
# The articles' paths on dailynorthwestern.com.
ARTICLES = [
    "2005/05/17/archive-manual/more-undergrads-seek-grants/",
    "2007/11/01/archive-manual/summer-grant-allows-senior-to-visit-4-continents/",
    "2010/11/02/campus/academic/record-number-of-northwestern-undergraduates-receive-research-grants/",
    "2012/04/25/campus/academic/summer-undergraduate-research-grants-increase-for-2012/",
    "2017/05/08/campus/in-focus-northwestern-students-grapple-with-challenges-of-finding-affordable-internship-experiences/",
    "2019/07/10/campus/qa-rachel-fimbianti-talks-research-on-imdb-ratings-and-female-stereotypes/",
    "2019/07/18/campus/qa-andrew-steiner-talks-research-on-billboard-hot-100-and-music-preferences/",
    "2019/07/28/campus/qa-stella-frentress-talks-research-on-urban-temples-in-bogota/",
    "2020/05/29/campus/1000-more-students-than-last-year-enroll-in-summer-classes-say-it-gives-needed-structure/",
    "2020/07/22/campus/weinberg-student-noah-rabinovitch-conducts-research-on-chicago-identities/",
    "2020/07/28/campus/communication-senior-riley-nelson-conducts-feminist-research-on-shakespeares-hamlet/",
    "2020/08/06/campus/mccormick-sophomore-saahir-ganti-agrawal-conducts-water-purification-research-on-nanofiltration-membranes/",
    "2021/02/09/ae/the-dolphin-show-to-produce-new-original-musical-change-my-mind/",
    "2021/07/13/campus/summer-undergraduate-research-continues-in-second-year-of-the-pandemic/",
    "2021/08/16/campus/need-to-know-a-guide-to-financial-support-and-saving-at-nu/",
    "2021/10/28/ae/firelight-festival-of-devised-work-bring-stories-of-joy-and-healing-to-campus-this-weekend/",
    "2021/11/01/top-stories/nu-declassified-when-surg-meets-showtunes/",
    "2021/11/15/audio/nu-declassified-exploring-engineering/",
    "2022/02/23/lateststories/nu-declassified-american-studies-small-cohorts-big-opportunities/",
    "2022/02/27/campus/navigating-undergraduate-summer-research-at-northwestern/",
    "2022/04/10/ae/students-petition-for-stuco-board-positions-gain-experience-and-community/",
    "2022/06/26/campus/nu-students-explore-academic-interests-through-summer-research-opportunities/",
    "2022/08/12/featured-stories/orientationissue/orientation-2022/navigating-northwesterns-financial-support-programs/",
    "2023/01/09/campus/fletcher-awards-granted-to-undergraduate-research-and-faculty-advisers/",
    "2023/04/03/campus/office-of-undergraduate-research-suspends-urap-due-to-rise-in-surg-applications/",
    "2023/07/05/lateststories/summer-research-funding-allows-students-to-investigate-cults-cape-cod-and-more/",
    "2023/11/12/lateststories/student-band-musecology-lived-and-breathed-upcoming-ep-this-summer/",
    "2024/06/27/lateststories/students-pursue-passions-and-policies-in-summer-research/",
    "2024/11/05/campus/as-many-students-apply-to-internships-others-explore-alternatives/",
    "2025/05/07/campus/northwestern-undergraduates-explore-research-through-grant-opportunities/",
    "2025/09/22/featured-stories/orientationissue/orientation-issue-2025/research-ready-your-guide-to-getting-involved/",
    "2026/04/29/lateststories/by-the-numbers-where-northwestern-undergraduates-find-research-funding/",
    "2026/07/01/campus/students-pursue-university-funded-independent-research-projects-over-summer/",
    "2026/08/12/campus/research-your-way-through-these-undergraduate-opportunities/",
    "2026/11/05/campus/nu-caps-undergraduate-research-grant-applications-per-lab-amid-record-demand/",
]


def article_name(path: str) -> str:
    """2023/04/03/campus/office-of-... -> 2023-04-03_office-of-....html"""
    parts = path.strip("/").split("/")
    return f"dailynorthwestern/{'-'.join(parts[:3])}_{parts[-1]}.html"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch the saved files")
    args = parser.parse_args()
    m = Manifest(SOURCE)
    for rel, url in LIVE.items():
        m.save(rel, url, refresh=args.refresh)
    ts, url = ISEN
    m.save_wayback(f"isen-2018-summer-science-isen-funds-five-undergraduate-research-grants_{ts}.html", ts, url,
                   refresh=args.refresh)
    for path in ARTICLES:
        m.save(article_name(path), DAILY + path, refresh=args.refresh)
    search = m.dir / "dailynorthwestern" / "search.json"
    if not search.exists():
        search.write_text(json.dumps({
            "api": DAILY + "wp-json/wp/v2/posts?search=<query>&per_page=100",
            "queries": ["SURG", "Summer Undergraduate Research Grant", "undergraduate research grant",
                        "Office of Undergraduate Research grant", "URG (1,400 of 7,531 results)"],
            "kept": "articles whose text matches \\bSURGs?\\b or 'Summer Undergraduate Research Grant'",
            "articles": [DAILY + p for p in ARTICLES],
        }, indent=1) + "\n")
    m.write()


if __name__ == "__main__":
    main()

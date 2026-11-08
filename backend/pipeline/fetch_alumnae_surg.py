"""Download the Alumnae of Northwestern's undergraduate research grant releases into data/raw/alumnae_surg/.

The Alumnae of Northwestern endow some of the Summer Undergraduate Research
Grants, and each spring announce that year's recipients in a press release
that gives, per grant, "Sponsor: name, rank, department". The winner lists
OUR posts for 2018-2024 name no sponsors, so these are one of the few public
sources of them.

Saved, all live from nualumnae.org and its file host s.nualumnae.org
(fetched 2026-11-06):

- <year>.pdf, 2018-2026: the release for each year. 2018-2024 are the PDFs
  the README links; 2025 and 2026 are linked from their news posts.
- alt/2020-news-page-link.pdf, alt/2023-news-page-link.pdf: the 2020 and
  2023 news posts link other revisions of the release than the README does
  (a May 2021 revision and a 2025 one, by their names); both versions are
  kept. The other news posts link the same PDFs as the README.
- news/<date>.html: the nine news posts, 2018-05-25 to 2026-06-01, found in
  the news list on the nualumnae.org home page. From 2019 on their titles
  give the number of grants: 13 in 2019 and 2020, 29 in 2021, 12 in 2022
  and 2023, 16 in 2024, 15 in 2025 and 2026.

That they are SURGs is the releases' own claim only from 2025 on (the
filenames say SURG); for earlier years, match the names to the SURG winner
lists to confirm.

Usage: uv run python -m pipeline.fetch_alumnae_surg [--refresh]
"""

import argparse

from pipeline.download import Manifest

SOURCE = "alumnae_surg"
FILES = "https://nualumnae.org/sites/default/files/announcements/"
S3 = "https://s.nualumnae.org/s3fs-public/announcements/"
NEWS = "https://nualumnae.org/news/"

RELEASES = {
    "2018.pdf": S3 + "NR%202018%20Undergrad%20Research%20Recipients%20website.pdf",
    "2019.pdf": S3 + "Alumnae%20NR%20for%202019%20Undergraduate%20Research%20Scholars%20-%20Recap9-16-2019handout.pdf",
    "2020.pdf": S3 + "NR%202020%20Undergrad%20Research%20Recips%20pj%20(3)mb.pdf",
    "2021.pdf": FILES + "NR%202021%20Undergrad%20Research%20Recips%20rev6-2024pj_1.pdf",
    "2022.pdf": S3 + "NR%202022%20Undergrad%20Research%20Recips%20UPDATED_0.pdf",
    "2023.pdf": FILES + "NR%202023%20Undergrad%20Research%20Recips%20rev6-2024pj_0.pdf",
    "2024.pdf": FILES + "NR%202024%20Undergrad%20Research%20Recips%20%282%29_0.pdf",
    "2025.pdf": "https://www.nualumnae.org/sites/default/files/announcements/NR%202025%20Undergraduate%20Research%20Grants%20SURG%20updatedpj.pdf",
    "2026.pdf": FILES + "NR%202026%20Undergraduate%20Research%20%20Grants%20SURG_2.pdf",
    "alt/2020-news-page-link.pdf": S3 + "Alumnae%202020%20URS%20NR%205-2020pjrev5-2021.pdf",
    "alt/2023-news-page-link.pdf": "https://www.nualumnae.org/sites/default/files/announcements/NR%202023%20Undergrad%20Research%20Recipspj2025.pdf",
}
POSTS = [
    "2018-05-25/alumnae-nu-announces-its-undergraduate-research-scholars-2018",
    "2019-05-14/thirteen-students-awarded-alumnae-undergraduate-research-grants",
    "2020-05-15/thirteen-students-awarded-2020-alumnae-undergraduate-research-grants",
    "2021-05-10/record-29-students-receive-alumnae-2021-undergraduate-research-grants-alumnaes",
    "2022-05-31/twelve-students-awarded-2022-alumnae-undergraduate-research-grants",
    "2023-04-27/twelve-students-awarded-2023-summer-undergraduate-research-grants-alumnaes",
    "2024-07-30/sixteen-students-awarded-alumnae-undergraduate-research-grants",
    "2025-06-24/fifteen-students-awarded-2025-alumnae-undergraduate-research-grants",
    "2026-06-01/fifteen-students-awarded-2026-alumnae-undergraduate-research-grants",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--refresh", action="store_true", help="refetch the saved files")
    args = parser.parse_args()
    m = Manifest(SOURCE)
    for rel, url in RELEASES.items():
        m.save(rel, url, refresh=args.refresh, check=lambda b: b.startswith(b"%PDF"))
    for post in POSTS:
        m.save(f"news/{post.split('/')[0]}.html", NEWS + post, refresh=args.refresh)
    m.write()


if __name__ == "__main__":
    main()

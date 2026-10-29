# Prowl

Search over Northwestern undergraduate research: SURG grants and Undergraduate Research Expo projects.

## Roadmap

- [x] Exact search with single or double quotes around a phrase.
- [ ] Filter results by a set of disciplines (multi-select).
- [ ] More data sources, largest first. Counts are estimates from sampling each source (October 2026), not full parses.
  - [ ] Expo programs 2012-2019: about 1,030 abstracts with presenter, faculty advisor and title, roughly as many as all of Expo 2021-2026.
    - The PDFs are linked from the [program archive](https://undergradresearch.northwestern.edu/share/expo/undergraduate-research-and-arts-exposition-program-archive/), 103-146 pages each.
    - Each entry is name, "Faculty:" or "Faculty Advisor:", title, abstract, close to the 2021-2023 programs `backend/pipeline/parse_expo.py` already reads.
  - [ ] SURG winners 2010-2019: about 1,560 titles with student, school, major and faculty sponsor (the 2020-2024 pages name no sponsor).
    - Only in the Wayback Machine, from the old OUR site: [2010](https://web.archive.org/web/20130202081244/http://undergradresearch.northwestern.edu/previous-winners-summer-urg), [2011](https://web.archive.org/web/20130202081222/http://undergradresearch.northwestern.edu/congratulations-2011-summer-urg-winners), [2012](https://web.archive.org/web/20130202081233/http://undergradresearch.northwestern.edu/urnu-news-and-events/2012-summer-urg-winners-announced), [2013](https://web.archive.org/web/20130509020124/http://undergradresearch.northwestern.edu/urnu-news-and-events/summer-undergraduate-research-grant-winners-2013-announced-congratulations), [2015](https://web.archive.org/web/20150905150816/http://undergradresearch.northwestern.edu/summer-2015-grant-winners), [2016](https://web.archive.org/web/20160601163758/http://undergradresearch.northwestern.edu/2016-summer-undergraduate-research-grant-winners), [2017](https://web.archive.org/web/2018/http://undergradresearch.northwestern.edu/2017-summer-undergraduate-research-grant-winners), [2018](https://web.archive.org/web/2018/http://undergradresearch.northwestern.edu/2018-summer-undergraduate-research-grant-winners), [2019](https://web.archive.org/web/2019/https://undergradresearch.northwestern.edu/2019-summer-undergraduate-research-grant-winners). Captures of the 2016 page from 2017 on show the 2017 list.
    - No 2014 list found. The 2025 and 2026 lists aren't published.
    - Together with the 2012-2019 Expo programs, this extends SURG <-> Expo linking back to 2012.
  - [ ] NURJ (Northwestern Undergraduate Research Journal). Scraped by `backend/pipeline/scrape_nurj.py` into `data/nurj.json`, with the print editions in `data/print_papers.json` and the attached documents in `data/document_texts.json`; not indexed yet.
    - About 330 distinct research works from 2003-2026 once posts, documents and print papers of the same title are merged. Only about 29 titles match indexed projects.
    - Leave out features and letters, and the CAURS-NURJ special edition's papers from other schools (its notes name Northwestern for 8 of 23).
    - Not downloaded: four 2019-20 theses whose posts show only a summary, on Google Drive ([Snyder](https://drive.google.com/file/d/1VVo0M5kw2Pxd-SXFfHApn0fIU4VcKts-/view), [Ajith](https://drive.google.com/file/d/1jpn4DfvDf7oLEXNSAjpP7HkCkclH8qKx/view), [Ogwumike](https://drive.google.com/file/d/1cjsJksNn3NhcASoucy9h77-KSb54wLQ8/view), [Dinegar](https://drive.google.com/file/d/1AgAHhJc2vPMl9M5Pi469U8WmsvCFtJ63/view)), and 41 YouTube presentation videos, useful only if transcribed.
  - [ ] Academic-year URG winners: about 430 titles with sponsor, Wayback only. 2006-07 to 2008-09 are on [one page](https://web.archive.org/web/20130202081211/http://undergradresearch.northwestern.edu/previous-winners-academic-year-urg); 2011-2015 are in monthly announcements (`urnu-news-and-events/congratulations-*-urg-winners`, `fall-2014-winners`, `winter-2015-grant-winners`).
  - [ ] Department honors thesis lists.
    - [ ] MMSS thesis library, the most promising: full-text thesis PDFs in a SharePoint folder that [mmss.wcas.northwestern.edu/thesis](https://mmss.wcas.northwestern.edu/thesis/) redirects to, downloadable with a Northwestern login.
    - [ ] [Economics](https://economics.northwestern.edu/undergraduate/major/undergraduate-economics-honors-senior-theses.html): about 300 student and title pairs, 2000-2026, one page. No advisors or abstracts.
    - [ ] [Political Science](https://polisci.northwestern.edu/undergraduate/honors/honors-theses.html): 163 theses with title, abstract and advisor, 2010-11 to 2025-26, one page.
    - [ ] Smaller lists: SESP honors news posts (about 50 with title, advisor and summary, 2022-2025), [Sociology](https://sociology.northwestern.edu/undergraduate/research-funding/past-senior-thesis.html) (about 35 titles, 2024-2026), [Biological Sciences](https://biosci.northwestern.edu/research/recent-honors-recipients.html) (about 20 with supervisor, 2024-25), [Buffett international senior thesis grants](https://buffett.northwestern.edu/programs/undergraduate-opportunities/international-senior-thesis-research-grant/awardees.html) (19), Anthropology (about 40 titles plus yearly PDFs), [Mellon Mays fellows](https://www.northwestern.edu/fellowships/mellon-mays-fellowship/our-fellows/) (85 bios describing thesis topics).
    - [ ] Email departments about their thesis archives, starting with Computer Science (Riesbeck). Psychology, Neuroscience, Chemistry, Physics and most others have no public list, and several say past theses are available from the director of undergraduate studies.
  - [ ] Nanoscape: The Journal for Undergraduate Research in Nanoscience, 2004-2011: 91 works in [Arch](https://doi.org/10.21985/N2MM8B). Published by the International Institute for Nanotechnology but open to undergraduates nationwide, so keep only Northwestern authors.
- [ ] Hyperlink advisors and faculty to their faculty pages.
- [ ] Deep-link Expo results to the abstract's page in the program PDF (`#page=N`). Today the link is the bare PDF URL; `backend/pipeline/parse_expo.py` would need to record each abstract's page number.
- [ ] Google OAuth accounts, so visitors can save cards to their profile.
- [ ] Let visitors upload papers or their own research done at Northwestern that is not indexed yet, reviewed before it is indexed.
- [ ] Google Analytics, plus careful logging of the queries visitors type in (decide what is stored, for how long, and disclose it on the site).
- [ ] A proper eval set for ranking.
  - Today there is only the name-search set (`data/eval/names.jsonl`, built and run by `backend/eval_names.py`) and the hand-written reranker queries below, where every target was already in the baseline top 5.
  - Cover topic, method, plain-language, negation and person queries, with graded relevance over several projects per query rather than a single target, including queries whose answers the current ranking misses.
  - Report standard metrics (e.g. nDCG@10, recall@k, hit@1) from one command, so ranking changes like the reranker or abstract bias are judged on it.
- [ ] A fast reranker that adds barely any latency (server p50 is about 49ms).
  - Tried on an M5 Pro CPU (4 threads), reranking the hybrid top-k over 21 negation and 27 general hand-written queries. Every target was already in the baseline top 5, so these queries only test reordering.
  - Best affordable option: `cross-encoder/ettin-reranker-32m-v1` on title + gloss (not the abstract), k=20, at +53ms p50 (the 17m model: +21ms). Neither clearly beat the baseline (32m did better on 7 negation queries and worse on 5).
  - Only the 400m and 1b Ettin models clearly won (1b moved negation hit@1 from 10 to 16), but they cost 0.9-2.4s. `mxbai-edge-colbert` costs about 2ms at query time but did not help. Full abstracts were worse and 4-5x slower than glosses.
  - A reranker can lift a target the baseline buries, but by matching wording, not knowledge. For "how do roundworms sense heat", "Temperature Sensation in C. alexandriana" (a title-only SURG grant) comes 7th in the hybrid ranking, behind C. elegans projects; every Ettin size from 17m to 1b reranks the top 50 so it comes 1st or 2nd, on titles or on card text. But the 150m and 1b models also put it 1st for fish, snakes, nematodes and plants, so they match "sense heat" to "Temperature Sensation" and ignore the organism. A reranker that reads only titles cannot know what a title does not say.
  - Next: a bigger eval, and a latency measurement on Railway.
- [ ] Bias ranking toward results with an abstract.
  - On "astronomy research i can do with public data", short title-only SURG cards with generic glosses held 5 of the dense top 7, ahead of abstract-backed Expo projects that fit better (Das-Ghosh's Local Bubble project came 13th, Clarendon's [OI] project 16th).
  - Against vague queries, abstract bodies are diluted by specifics (with voyage-4-nano, Das-Ghosh scored 0.422 on full text vs 0.479 on title + fields + concepts alone), while title-only glosses are field-level definitions. One candidate fix is a third vector per project built from title + fields + concepts.
  - BM25 length normalization also favours the ~33-token title-only cards.
- [ ] Spot check the LLM-judged SURG <-> Expo links.
  - `data/expo_judgments.jsonl` has one verdict per name-matched candidate pair; only same/high pairs are linked (181 when last counted, one of them, `surg-2024-230|expo-2025-213`, promoted by hand from same/low).
  - Check linked pairs for false merges, and same/low (27) and related (112) pairs for missed links like that one, which was missed because the grant title was vague.

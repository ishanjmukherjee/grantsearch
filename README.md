# Prowl

Search over Northwestern undergraduate research: SURG grants and Undergraduate Research Expo projects.

## Roadmap

- [x] Exact search with single or double quotes around a phrase.
- [ ] Filter results by a set of disciplines (multi-select).
- [ ] More data sources.
  - [ ] NURJ (Northwestern Undergraduate Research Journal). Scraped by `backend/pipeline/scrape_nurj.py` into `data/nurj.json`, not indexed yet; see `MANUAL_DOWNLOADS.md` for the files that must be fetched by hand.
  - [ ] Department honors thesis lists.
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

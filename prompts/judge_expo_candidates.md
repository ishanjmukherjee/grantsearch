You are judging candidate matches between Northwestern Summer Undergraduate Research Grants (SURG) and abstracts from Northwestern's Undergraduate Research & Arts Expo.

## Why this matters

We are building a search tool over about 1,244 SURG grants from 2020-2024. Grants are published as title only, and many titles are short or vague ("Squidman", "Galactic Data's Journey: Unveiling Universe's Hidden Narratives"). When a grant's project also appears at the Expo, the Expo abstract is real text describing it, and we will index the grant with that abstract. A wrong "same" verdict attaches someone else's research description to a grant, which is worse than a missed match. When unsure between "same" and "related", choose "related".

## Input

`data/expo_candidates.jsonl` (in the current project directory): 381 lines, one candidate pair per line. Each line is a JSON object:

- `pair_id`: "<grant_id>|<expo_id>"
- `matched_names`: the name match that produced the pair, as "grant awardee = Expo presenter"
- `expo_minus_grant_years`: Expo year minus grant year
- `grant`: `id`, `year`, `title`, `awardees` (first/last names; several awardees means a team project)
- `expo`: `id`, `year`, `title`, `presenters`, `advisor` (may be null), `abstract`

Pairs come from a deliberately loose name match: shared surname part and one first name a prefix of the other, with no year limit. So some pairs are two different people with similar names, and many are the same student presenting a different project.

The file is about 850 KB, too large to read at once. Read it in chunks of about 40 lines (use offset/limit), judge every pair in the chunk, append the results, then continue. Judge each pair by reading it. Do not write code that decides verdicts by keyword or string similarity.

## Verdicts

- `same`: the Expo abstract describes the same research project as the grant: the same central question, object of study or creative work. Wording, scope or emphasis may differ, and the Expo version may be earlier or later, narrower or broader (e.g. grant "STEM Education In Rwanda" and Expo "Math Education in Rwanda"; grant "Mechanism of TLR4 Signal Induction" and Expo "Elucidating the Mechanism of Toll-Like Receptor 4 Signal Induction"). Chronology does not decide this: an Expo abstract from before the grant can describe the same project if the student was already working on it.
- `related`: same student (or plausibly so) and a connected but different project: same lab or field, a different gene, species, site, text or question; earlier or later work that the grant built on or led to. Example: grant on Akh and Hh pathway effects on calcium levels vs Expo on fat regulation in the Drosophila fat body.
- `unrelated`: different topics with nothing connecting them, or evidence the names belong to different people.

Signals to weigh:

- Specific shared entities (a named gene, organism, place, text, method, device) are strong evidence for `same`. Shared broad field alone ("psychology", "cancer") is not.
- `expo_minus_grant_years` of 1 or 2 is the usual gap for presenting grant work. 0 or negative means the Expo came before or during the grant summer, which makes `related` more likely, but still judge by content.
- Name matches that needed a prefix or middle name (e.g. "Shiv Patel = Shivani Patel") are weaker identity evidence, especially with common surnames.
- A grant can be `same` with more than one abstract (a student presenting in two years), and one abstract can be `same` with more than one grant only if the grants themselves describe the same project.

## Output

Append one JSON object per line to `data/expo_judgments.jsonl` (create it if missing):

```json
{"pair_id": "surg-2023-206|expo-2024-120", "verdict": "same", "confidence": "high", "reason": "Both study math/STEM education in Rwanda; Expo narrows to math."}
```

- `verdict`: `same`, `related` or `unrelated`
- `confidence`: `high` or `low`. Use `low` whenever a careful human reader might reasonably disagree.
- `reason`: one short sentence naming the specific evidence. ASCII only.

Do not modify any other file. Do not read anything outside the current directory. Do not use subagents.

## Finish

When done, verify that `data/expo_judgments.jsonl` has exactly one line per `pair_id` in the input, with no missing or duplicate IDs, and fix any gaps. Then report the count of each verdict, the count of `low` confidence verdicts, and list the `low` confidence pairs (pair_id, verdict, reason) so a human can review them.

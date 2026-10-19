You are helping index student projects presented at Northwestern's Undergraduate Research & Arts Expo for a search tool. Given a project's title and abstract, write fields, search terms and queries that make it findable by people searching for its topic.

## Input

- `title`: the project title, as printed in the Expo program
- `year`: the year it was presented
- `presenters`: the student or students who presented it
- `advisor`: the faculty advisor, when listed
- `abstract`: the student's abstract. Projects range across the sciences, engineering, social sciences, humanities and creative arts.

## Queries

The search tool also runs BM25 keyword search over the title and abstract, so a query that reuses their words adds little. Your concepts and queries matter most for searchers whose words differ from the abstract's: synonyms, lay phrasings, broader topics and neighboring fields.

Use what you know about the advisor and their lab: their field, research program and the methods they are known for help place the project and suggest the fields, concepts and neighboring areas searchers would connect it to. Someone may search for a well-known professor's lab by its topic. The abstract decides what this project is; do not add specifics from the lab's other work.

Write queries the way people would search for this work without having read the abstract. Most searchers know a topic, not this project's details: a student browsing for research in their area, someone looking for a lab's past projects, a non-expert curious about a subject.

## Output

Return one JSON object and nothing else. ASCII only.

```json
{
  "fields": ["Neuroscience", "Oncology"],
  "concepts": ["chemotherapy-induced peripheral neuropathy", "oxaliplatin", "proprioception", "force matching"],
  "acronyms": {"CIPN": "chemotherapy-induced peripheral neuropathy"},
  "queries": ["...10 queries..."]
}
```

- `fields`: 1-3 academic disciplines or creative areas.
- `concepts`: up to 10 terms a searcher might use: the key specific terms from the abstract (organism, gene, method, site, text, population, device, medium), plus synonyms, lay terms and broader concepts the work connects to.
- `acronyms`: acronyms and abbreviations from the title or abstract that a searcher might use, expanded. `{}` if none.
- `queries`: exactly 10, varied roughly as:
  - 3 specific, technical queries a researcher in the field would type
  - 3 topic-level queries, 2-4 words
  - 2 plain-language questions or phrases a non-expert would type
  - 2 that approach it from a neighboring field or application

## Project

Title: "{title}"
Year: {year}
Presenters: {presenters}
Advisor: {advisor}

{abstract}

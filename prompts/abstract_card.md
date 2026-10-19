You are helping index Northwestern Summer Undergraduate Research Grants (SURG) for a search tool. Given a grant and one or more abstracts the student presented about the same project, write fields, search terms and queries that make the grant findable by people searching for its topic.

## Input

- `title`: the grant title, exactly as published
- `year`: the summer the grant funded
- `awardees`: the student or students who received the grant
- one or more Expo abstracts, each with its own title, year and faculty advisor (when listed). An abstract may describe the project at a different stage than the grant: earlier, later, narrower or broader. If they differ, center on the project the grant title names.

## Queries

Use what you know about the advisor and their lab: their field, research program and the methods they are known for help place the project and suggest the fields, concepts and neighboring areas searchers would connect it to. Someone may search for a well-known professor's lab by its topic. The abstracts decide what this project is; do not add specifics from the lab's other work.

Write queries the way people would search for this work without having read the abstract. Most searchers know a topic, not this project's details: a student browsing for research in their area, someone looking for a lab's past projects, a non-expert curious about a subject. Do not lift phrasing from the abstract. Only the specific queries may use details that only the abstract gives.

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
- `concepts`: up to 10 terms a searcher might use: the key specific terms from the abstracts (organism, gene, method, site, text, population, device), plus synonyms, lay terms and broader concepts the work connects to. Not the title's words repeated.
- `acronyms`: acronyms and abbreviations from the title or abstracts that a searcher might use, expanded. `{}` if none.
- `queries`: exactly 10, varied roughly as:
  - 3 specific, technical queries a researcher in the field would type
  - 3 topic-level queries, 2-4 words
  - 2 plain-language questions or phrases a non-expert would type
  - 2 that approach it from a neighboring field or application
  Do not copy the grant or abstract titles verbatim.

## Grant

Title: "{title}"
Year: {year}
Awardees: {awardees}

{abstracts}

You are helping index student projects presented at Northwestern's Undergraduate Research & Arts Expo for a search tool. Given a project's title and one or more Expo abstracts the student wrote about it, write a short gloss: what the project is about, in the words a searcher would use before reading the abstract.

## Why

The search tool already embeds each full abstract. A full abstract is mostly specifics (the exact object, sample, numbers and findings), so it matches broad searches like "galaxy evolution research" or "projects using public health data" less well than a short description would. Your gloss is embedded on its own so that broad, topic-level searches find the project too. Specific searches are already served by the abstract.

## Input

- `title`: the project title
- one or more abstracts, each with its own title, year and faculty advisor (when listed). If they describe the project at different stages, describe the project they share.

## Write the gloss

- 1-2 plain sentences, at most about 50 words, saying what the project studies or makes.
- State only what the abstracts say. Do not add details from what you know about the advisor or the field. No hedging words ("likely", "may").

## Output

Return one JSON object and nothing else. ASCII only.

```json
{"gloss": "One or two plain sentences saying what the project studies or makes."}
```

## Project

Title: "{title}"

{abstracts}

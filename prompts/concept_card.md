You are helping index Northwestern Summer Undergraduate Research Grants (SURG) for a search tool. Each grant is published as a title only. For one grant title, either write a concept card that makes the grant findable by people searching for its topic, or refuse because the title does not say what the project is about.

## Why refusing matters

Your card will be embedded and matched against search queries. A card built on a guess makes the grant show up for searches it has nothing to do with, and pushes down grants that actually match. A refused grant is still searchable by its title words, so refusing costs little. A wrong card is worse than no card. When unsure what the title means, refuse; when sure of little more than its field, write a thin card.

## Input

- `title`: the grant title, exactly as published
- `year`: the summer the grant funded
- `awardees`: the student or students who received the grant

## Decide: card or refuse

Write a card if a knowledgeable reader can tell, from the title alone, at least the field or subject area of the project. Match the card's depth to what the title gives you:

- A specific title (an object of study, question or creative work you can name) gets a full card.
- A title that reveals only a field or broad topic ("Galactic Data's Journey: Unveiling Universe's Hidden Narratives" is astronomy data, nothing more) gets a thin card: a gloss that does little more than restate the title plainly, the field, a few broad concepts, and a few topic-level queries. That is enough for a topic search to surface it. Do not pad a thin card with specifics to make it look full.

Refuse when:

- The title is a name, pun or metaphor with no literal subject and no recognizable allusion ("Squidman", "Echoes", "Project Lighthouse").
- The title has two or more plausible readings in different fields, and nothing in it decides between them.

Do not refuse just because the title is short or technical. "Mechanism of TLR4 Signal Induction" is short but says exactly what is studied.

Before calling a title ambiguous, use all of it: the method, organism or setting it names often rules readings out. In "Using CRISPRa to reduce DS symptoms", CRISPRa raises gene expression, which treats Dravet syndrome (too little SCN1A) and would not treat Down syndrome (too much chromosome 21 dosage), so DS is Dravet.

A card must add something the title's words do not already give a BM25 search engine: a recognizable topic, field idiom or concept a searcher would use. If the only card true under every reading just restates generic title words, refuse: title-word search already covers it.

## Read the title like an expert

Your value here is interpretation. Read each title the way a researcher in its field would, and say what the project is really about, even when that is not what the words literally say. Recognize allusions, field idioms and technical framings: "Hearing the Shape of a Clarinet" echoes "Can One Hear the Shape of a Drum?" and is about inverse spectral problems, recovering an instrument's bore geometry from its resonances, not about clarinet performance. A literal, surface reading that misses what an expert would see is a failure, just as a guess is.

Then expand that reading with domain knowledge: expand acronyms, give synonyms and lay terms, and name the fields, concepts and questions an expert would connect to it (TLR4 -> innate immunity, toll-like receptors, inflammation, LPS sensing).

The line is between interpreting the title and inventing the project. Interpretation (what the title means to someone who knows the field) is wanted. Invention (which organism, site, dataset, method or finding this particular student used, when the title does not point to one) is not. If a detail would be true of only some projects with this title, leave it out.

## Output

Return one JSON object and nothing else. ASCII only.

Card:

```json
{
  "status": "card",
  "gloss": "One or two plain sentences saying what the project studies or makes, as an expert would read the title.",
  "fields": ["Immunology", "Cell biology"],
  "concepts": ["toll-like receptor 4", "innate immune signaling", "lipopolysaccharide", "inflammation"],
  "acronyms": {"TLR4": "toll-like receptor 4"},
  "queries": ["...up to 10 queries..."]
}
```

Refusal:

```json
{
  "status": "refuse",
  "reason": "One short sentence: what is missing from the title."
}
```

Field rules:

- `gloss`: 1-2 sentences stating your expert reading, including what the title means when it differs from what it says. No hedging words ("likely", "may"). If you would need to hedge, the content is a guess: drop it, or refuse.
- `fields`: 1-3 academic disciplines or creative areas.
- `concepts`: up to 10 terms a searcher might use, including synonyms of the title's terms. Not the title's words repeated. A thin card may have only a few.
- `acronyms`: every acronym or abbreviation in the title, expanded. `{}` if none.
- `queries`: up to 10 search queries for which this grant would be a good result. Write only as many as the title supports; a thin card may have 2-4 topic-level queries. Never pad with near-duplicates or guesses. For a full card, vary them roughly as:
  - 3 specific, technical queries a researcher in the field would type
  - 3 topic-level queries, 2-4 words
  - 2 plain-language questions or phrases a non-expert would type
  - 2 that approach it from a neighboring field or application
  Do not copy the title verbatim. Every query must be one the project satisfies under your reading of the title, not one that fits only if a guess about its details is right.

## Examples

Title: "Mechanism of TLR4 Signal Induction" (2022)

```json
{"status": "card", "gloss": "Investigates how toll-like receptor 4 initiates signaling, the step by which this innate immune receptor detects a trigger and activates downstream pathways.", "fields": ["Immunology", "Cell biology"], "concepts": ["toll-like receptor 4", "innate immunity", "pattern recognition receptor", "lipopolysaccharide sensing", "receptor activation", "inflammatory signaling", "signal transduction"], "acronyms": {"TLR4": "toll-like receptor 4"}, "queries": ["TLR4 receptor activation mechanism", "how LPS binding triggers TLR4 signaling", "toll-like receptor signal transduction", "innate immune receptors", "TLR4 signaling", "inflammation signaling pathways", "how does the immune system detect bacteria", "what turns on inflammation in cells", "pattern recognition receptors in sepsis", "molecular basis of inflammatory disease"]}
```

Title: "Can one hear the shape of a clarinet?" (2023)

```json
{"status": "card", "gloss": "Studies the inverse spectral problem for a wind instrument: whether and how the geometry of a clarinet's bore can be recovered from its acoustic resonances, in the tradition of 'Can One Hear the Shape of a Drum?'.", "fields": ["Mathematics", "Acoustics", "Physics"], "concepts": ["inverse spectral problem", "spectral geometry", "isospectral shapes", "acoustic resonance", "bore profile reconstruction", "eigenvalue problems", "Webster horn equation", "musical acoustics"], "acronyms": {}, "queries": ["Kac drum problem applied to wind instruments", "reconstructing bore geometry from resonance frequencies", "spectral geometry of wind instruments", "can you hear the shape of a drum", "musical instrument acoustics", "inverse spectral problems", "can you tell an instrument's shape from its sound", "math behind how instruments sound", "isospectral domains", "acoustic inverse problems in nondestructive testing"]}
```

Title: "Squidman" (2021)

```json
{"status": "refuse", "reason": "A name with no literal subject; could be a creative work, a biology project or something else."}
```

Title: "Galactic Data's Journey: Unveiling Universe's Hidden Narratives" (2024)

```json
{"status": "card", "gloss": "A project working with astronomical data to learn about the universe.", "fields": ["Astronomy", "Astrophysics"], "concepts": ["astronomical data analysis", "astrophysics", "cosmology", "observational astronomy"], "acronyms": {}, "queries": ["astronomy data analysis", "astrophysics research", "analyzing data about the universe"]}
```

## Grant

Title: "{title}"
Year: {year}
Awardees: {awardees}

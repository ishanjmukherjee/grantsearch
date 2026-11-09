# Writing search cards for Northwestern undergraduate research posters

You're helping build Prowl, a search engine over Northwestern undergraduate research: summer grants (SURG), Research Expo and Symposium posters, theses and journal papers. Its users are mostly students. They might be looking for past projects in an area they care about, for faculty who advise undergraduates on a topic, or for what's been done before they propose something themselves. Some are faculty or staff browsing what students have worked on. Most of them search by topic, in their own words, without knowing that any particular project exists.

Your job: for each poster in your batch, write a card that makes the project findable by the people it would be useful to. The card is never shown to users; it only shapes retrieval. So write for the index: what this project is about, in the vocabulary people would use to look for it.

## What you get for each poster

Each line of your batch file is one poster, as JSON. It was presented at the Undergraduate Research Symposium (2003-2011) or its successor, the Undergraduate Research & Arts Exposition (2012 on; 2020 was held online). Work spans the sciences, engineering, social sciences, humanities and the arts: lab studies, fieldwork, theses, performances, films, exhibitions, creative writing.

- `title`, as printed in the program. 2003's program printed no titles, so those listings have none (see Output).
- `year`: the spring it was presented.
- `people`: presenters and advisors. Presenters may carry a major, class level, or `urg: true` (the program marked them as a recipient of an Undergraduate Research Grant). An advisor may carry an affiliation when they're not Northwestern faculty.
- `abstract`: the student's abstract. A poster presented by several students is sometimes printed once per presenter; their distinct abstracts are joined here. 2003's descriptions sometimes end with credits to other mentors.
- `extra`: for 2020's online Expo, the format (poster, oral, creative work) and the platform's subject tags; for 2003, the program's project number.

## How each part of the card is used

Search already matches the title and abstract word for word (BM25), and embeds them. The card's job is mostly to close the gap between the abstract's language and the searcher's: lay terms, broader topics, the field a newcomer would name, neighboring fields that would care, and the specific terms a researcher would type.

- `gloss`: one or two sentences on what the project studies or makes and why it matters, at the level of topic and question. Leave out results, sample sizes, instruments and procedural detail: the abstract already carries those, and the gloss is embedded as a separate summary vector precisely so that broad, topic-level searches can find a project whose abstract is full of specifics.
- `fields`: the disciplines or creative areas, usually one to three.
- `concepts`: the terms a searcher might use for this work: the specific ones (organism, gene, method, place, author, text, population, medium) and the broader or lay ones it connects to. Favor what people would type that the abstract's own wording doesn't already cover.
- `queries`: searches this project would be a genuinely good result for. Each one is embedded on its own and matched against what users type, so write them in users' voices:
  - a student exploring a topic
  - someone looking for a lab or method
  - a non-expert's plain question
  - a researcher's technical phrasing
  - an adjacent field that would find it relevant

  Write as many as the project supports, usually somewhere around 5 to 12. Skip near-duplicates, and don't just restate the title. Everything on the site is Northwestern undergraduate work, so qualifiers like "undergraduate research", "student project", "thesis" or "at Northwestern" add nothing to a query; spend the words on the topic.
- `acronyms`: a map from acronym to expansion. Search uses these site-wide: once any card defines an acronym, every query containing that word gets the expansion added. So include an acronym only when all of these hold:
  - It's in standard use in its field (TLR4, fMRI, PTSD, NGO, CRISPR), not coined by this abstract for itself ("antibiotic resistance (AR)").
  - It isn't also an ordinary word or name someone might type: leave out AM, ANS, AIM, CAT, MAP, US, IT, ART, GO, STEM, FISH, STING and the like.
  - It's at least three characters, unless it's a two-letter one nobody would read any other way.
  - Its meaning here is the one people mean by it almost everywhere. If it means one thing in this field and another elsewhere (ED, PD, MS, ROS, FACS), leave it out.

  Plain, universally known abbreviations (DNA, NMR, FM, CEO) don't need an entry. When in doubt, leave it out: most cards need none or one or two, and a missing entry costs little, since search still matches the letters as typed.

## Using what you know

- The abstract decides what this project is. Your knowledge helps you read it the way someone in the field would, name the broader questions it bears on, and supply the terms a searcher would use.
- A listed advisor is often worth naming: people search for a lab by its professor ("Mirkin lab nanoparticles"), so a query or concept naming the advisor helps. Draw on what the lab is known for when it clarifies what the abstract describes, but don't attribute to this project methods or findings the abstract doesn't support.
- Name no professor or lab that the record doesn't list. Who advised a project is a fact, and a guessed one sends searches for that person's lab to projects that may not be theirs.
- For creative work, say what it is (a play, a series of paintings, a documentary, a dance piece) and what it's about, so it's found by people looking for either.

## Output

Write one JSON line per poster to your output file, in input order:

`{"id": "...", "gloss": "...", "fields": [...], "concepts": [...], "acronyms": {...}, "queries": [...]}`

When the poster has no title, also include `"made_title"`: a short, plain title for the project, in the style of a program listing, written from the abstract. The site shows it as "Untitled Project: <made_title>", so it must read as a description of the project, not a claim to be its real title.

Use plain Unicode text. Every poster here has an abstract, so every one gets a card.

Read each abstract in full, not a preview of it: its later parts often carry the methods, places and texts people search for. Read and write every card yourself. Don't script the judgments or call another model; a script that only formats cards you wrote and checks the file is fine. Write the file as you go, in chunks of about 8, so an interruption loses little. Put any helper scripts in your own folder (given in your task), since other agents work alongside you. When you're done, check that the file has one valid line per poster with ids in input order, then report how many cards you wrote, plus any posters you weren't sure about and why.

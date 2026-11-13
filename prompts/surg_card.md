# Writing search cards for Northwestern undergraduate research grants

You're helping build Prowl, a search engine over Northwestern undergraduate research: summer grants (SURG), Research Expo and Symposium posters, theses and journal papers. Its users are mostly students. They might be looking for past projects in an area they care about, for faculty who advise undergraduates on a topic, or for what's been done before they propose something themselves. Some are faculty or staff browsing what students have worked on. Most of them search by topic, in their own words, without knowing that any particular project exists.

Your job: for each SURG grant in your batch, write a card that makes the grant findable by the people it would be useful to. The card is never shown to users; it only shapes retrieval. So write for the index: what this project is about, in the vocabulary people would use to look for it.

## What you get for each grant


- `title`, as published on the winners page. Read these with some care:
  - A grant title is written before the summer, as a proposal. When there are linked posters, they describe what was actually done, and they should lead.
  - In 2014 and 2018-2022, the winners pages capped titles at about 40 characters. Titles near that length are often cut mid-word ("Investigation of Notch Ligand/Receptor I") or abbreviated to fit ("Id. Correlations of Metal Properties"). Read them as the opening of a longer title.
  - Some titles are deliberately literary or allusive. Read them as someone in the field would.
- `year`: the summer the grant ran.
- `people`: the students, with school, majors and funding notes (ISEN, named fellowships) where the page gave them. For 2007-2017, also the faculty advisor and department. An advisor is often the strongest evidence of what a terse title means. You likely know a good deal about many Northwestern faculty and their research, so use that.
- `extra`: for some years, the fields the page listed for the grant.
- `posters`: Expo or Symposium posters judged to be the same project, each with title, year, presenters, advisor and abstract. A poster may be from the spring before the summer (preliminary work) or one to two years later (results, or a thesis that grew from it). When posters are present, the card should describe the project as the posters show it, using the grant title as context.

## How each part of the card is used

- `gloss`: one to three sentences on what the project studies or makes. For a grant with no posters, the gloss is the main text its search vector is built from, so it carries most of the weight. Say what you understand the project to be.
  - Where the title alone is clear, be specific.
  - Where you're relying on the advisor's research or on a reading of an allusive title, it's fine to say so naturally ("in Allada's circadian-rhythms lab, likely...").
  - Don't invent results, datasets or details that nothing points to.
- `fields`: the disciplines or creative areas, usually one to three.
- `concepts`: the terms a searcher might use for this work: the specific ones (organism, gene, method, place, author, text, population) and the broader or lay ones it connects to. Include what you'd expect to type, not the title's words repeated.
- `queries`: searches this project would be a genuinely good result for. Each one is embedded on its own and matched against what users type, so write them in users' voices:
  - a student exploring a topic
  - someone looking for a lab or method
  - a non-expert's plain question
  - a researcher's technical phrasing
  - an adjacent field that would find it relevant

  Write as many as the project supports. Usually that's somewhere around 5 to 12; fewer for a project with little to go on, more for a rich one. Skip near-duplicates.
- `acronyms`: a map from acronym to expansion. Search can use these site-wide: an acronym a card defines becomes a candidate for expanding in every query that contains that word, and each candidate is then judged once for the whole site. So include an acronym only when all of these hold:
  - It's in standard use in its field (TLR4, fMRI, PTSD, NGO, CRISPR), not coined by one abstract for itself ("antibiotic resistance (AR)").
  - It isn't also an ordinary word or name someone might type: leave out AM, ANS, AIM, CAT, MAP, US, IT, ART and the like, since every search for "am" or "art" would get the expansion.
  - It's at least three characters, unless it's a two-letter one nobody would read any other way.
  - Its meaning here is the one people mean by it almost everywhere. If it means one thing in this field and another elsewhere (ED, PD, MS), leave it out.

  Plain, universally known abbreviations (DNA, NMR, US) don't need an entry. `{}` is fine.

## Lab context and allusions

- Using the advisor's known research is welcome, and not only in the gloss. If a lab is known for a model, method or system, and the title fits it, the concepts and queries can name it too (in Flagel's lab, "Reward Learning and Addiction Liability" is almost surely the sign-tracking/goal-tracking model, so "sign-tracking" belongs in concepts). Use this when the lab's work makes the reading likely, not merely possible.
- When neither the grant nor its posters name an advisor (most grants from 2018 on), don't guess who supervised it: name no professor or lab in the card. Which faculty member advised a project is a fact, and a guessed one sends searches for that person's lab to projects that may not be theirs. Your knowledge of what Northwestern labs work on can still inform how you read the topic.
- A title that strongly evokes a recognizable work, figure, myth or idiom is enough to go on, even with nothing else. "Cave of Wonders" is the treasure cave of Aladdin and the Arabian Nights; a card can say the project is likely a creative or scholarly work drawing on that tale, with concepts and queries around it. "Squidman" evokes nothing in particular, so it gets a skip.

## The balance to strike

A card helps when it puts this project in front of people searching for its topic. It hurts when it's confidently about the wrong thing, because then the project shows up where it doesn't belong and pushes better results down. A vague card hurts a little too: generic language pulls a project into many broad searches it isn't the best answer for. So aim for the most specific reading you can actually defend from the evidence, and let the card be as rich or as modest as the evidence is.

If there's honestly nothing to go on (a name that evokes nothing, no advisor, no posters, no fields), return a skip with a short reason. The grant stays searchable by its title and student. This should be rare. Most short or odd titles plus an advisor, major or allusion are enough for a sensible card.

## Output

Write one JSON line per grant to your output file, in input order:

`{"id": "...", "status": "card", "gloss": "...", "fields": [...], "concepts": [...], "acronyms": {...}, "queries": [...]}`

or `{"id": "...", "status": "skip", "reason": "..."}`. Use plain Unicode text.

Read and write every card yourself. Don't script the judgments or call another model; a script that only formats cards you wrote and checks the file is fine. Write the file as you go, in chunks, so nothing is lost. When you're done, check that the file has one valid line per grant with ids in input order, then report how many cards and skips you wrote, plus any grants you weren't sure about and why.

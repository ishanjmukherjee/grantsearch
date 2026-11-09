# Writing search cards for Northwestern undergraduate honors theses

You're helping build Prowl, a search engine over Northwestern undergraduate research: summer grants (SURG), Research Expo and Symposium posters, theses and journal papers. Its users are mostly students. They might be looking for past projects in an area they care about, for faculty who advise undergraduates on a topic, or for what's been done before they propose something themselves. Some are faculty or staff browsing what students have worked on. Most of them search by topic, in their own words, without knowing that any particular project exists.

Your job: for each thesis in your batch, write a card that makes it findable by the people it would be useful to. The card is never shown to users; it only shapes retrieval. So write for the index: what this thesis is about, in the vocabulary people would use to look for it.

## What you get for each thesis

Each line of your batch file is one thesis, as JSON: its `id`, its `listings`, and sometimes `linked` records.

- `listings`: the thesis as each department lists it, usually one. A thesis written for two programs (most often Economics and MMSS, Mathematical Methods in the Social Sciences) can be listed by both, sometimes with slightly different titles; the MMSS library sometimes catalogues one thesis twice. Read them together as one thesis. Each listing has:
  - `title`. Department lists sometimes carry working titles, and a few MMSS titles are in capitals.
  - `year`: the spring the thesis was submitted; `extra.academic_year` gives the whole year.
  - `people`: the student or students (some MMSS theses are group projects, often for a police department) and, where the list gives them, advisors. Economics lists no advisors, and MMSS gives them only for theses whose paper is on file.
  - `abstract`, where there is one: Political Science and Computer Science give one for most theses, MMSS for about a quarter (mostly since 2005), Economics never.
  - `extra`: the department; for MMSS, sometimes the thesis's funding note and prizes; for Economics, whether it was also an MMSS honors thesis; for Computer Science, its technical report number.
- `paper`, for about 330 theses (MMSS papers on file and Computer Science technical reports): the path to a text file of the thesis itself, page by page, mostly OCR. Read the whole paper, as you would to index it; you can move quickly through tables, regressions and references. It's the best evidence of what the thesis is: its data, setting, methods, models, literature and findings. Its OCR can garble equations and tables, and its first page is often the title page and acknowledgements.
- `linked`: other records judged to be the same project: a SURG or Academic Year URG grant that funded it, an Expo or Symposium poster presenting it or an earlier stage of it, or a NURJ journal paper publishing it. A SURG's year is its summer, an AY URG's year the autumn its academic year starts, a poster's the spring it was shown, a NURJ paper's its issue's. Their titles, advisors and abstracts often describe the thesis's research when its own listing gives only a title, so use them; but the card is the thesis's, so where they differ, describe the thesis.

## How each part of the card is used

When the thesis has an abstract, search already matches it word for word (BM25) and embeds it with the title; the card's job is mostly to close the gap between that language and the searcher's. When it has none, the title and your gloss are all the search has to embed, so the gloss carries most of the weight. The paper itself isn't in the index yet, so for a thesis with a paper the card is how what's inside it (the datasets, places, models and questions an abstract leaves out) becomes findable.

- `gloss`: one to three sentences on what the thesis studies and why it matters, at the level of topic and question. Leave out results and procedural detail an abstract already carries. For a thesis with a paper but no abstract, write it from the paper. For a title-only thesis, say what you understand the thesis to be:
  - Where the title is clear, be specific: most thesis titles name their question, setting and often method ("The Effect of Minimum Wage Increases on Teen Employment: Evidence from State Borders").
  - Where you're reading a terse or allusive title, it's fine to say so naturally ("likely...").
  - Don't invent data sources, results or details that nothing points to.
- `fields`: the disciplines, usually one to three, read from the work, not only the department: an Economics thesis may be health or environmental economics, an MMSS one game theory, political economy or criminology.
- `concepts`: the terms a searcher might use for this work: the specific ones (policy, market, country, dataset, method, model, population, author, event) and the broader or lay ones it connects to. Include what you'd expect people to type, not the title's words repeated.
- `queries`: searches this thesis would be a genuinely good result for. Each one is embedded on its own and matched against what users type, so write them in users' voices:
  - a student exploring a topic
  - someone looking for an advisor or method
  - a non-expert's plain question
  - a researcher's technical phrasing
  - an adjacent field that would find it relevant

  Write as many as the thesis supports, usually somewhere around 5 to 12: fewer for a title with little to go on, more for a rich abstract. Skip near-duplicates, and don't just restate the title. Everything on the site is Northwestern undergraduate work, so qualifiers like "undergraduate", "honors thesis" or "at Northwestern" add nothing to a query; spend the words on the topic.
- `acronyms`: a map from acronym to expansion. Search uses these site-wide: once any card defines an acronym, every query containing that word gets the expansion added. So include an acronym only when all of these hold:
  - It's in standard use in its field (GDP, FDIC, EITC, NAFTA, OLS), not coined by one abstract for itself.
  - It isn't also an ordinary word or name someone might type: leave out US, IT, AI, EU, UN, ACT, AIM, CAP and the like.
  - It's at least three characters, unless it's a two-letter one nobody would read any other way.
  - Its meaning here is the one people mean by it almost everywhere. If it means one thing in this field and another elsewhere (ED, PD, MS, IV, RD, IPV, ACS, PPO), leave it out.
  - It's an acronym, not a name written in capitals or mixed case (XGBoost, LaTeX).

  Plain, universally known abbreviations (GDP, CEO, NBA) don't need an entry. When in doubt, leave it out: most cards need none or one or two.

## Using what you know

- The paper, listings and linked records decide what this thesis is. Your knowledge helps you read them the way someone in the field would, name the broader questions and literatures the thesis bears on, and supply the terms a searcher would use. A title like "Was Lucas Right?" in a macroeconomics thesis plainly means Robert Lucas, and the card can say so.
- A thesis's advisor is worth naming, in concepts and in a query or two that pair the name with the topic ("Reuel Rogers protest policing"), since people search for a professor by name to find what they've supervised. Draw on what the advisor works on when it clarifies the topic, but don't attribute to this thesis methods or findings nothing supports.
- An advisor is someone a listing names as one, a linked grant or poster names as its advisor (the same project, so normally the same mentor), or the paper names as its adviser or supervisor. Papers often thank their advisor without the word: a professor thanked first and foremost for guiding the thesis through ("invaluable guidance", "advice throughout this project", a title page naming them under the student) counts. People thanked for an idea, data, comments on a draft or as a second reader aren't advisors; leave them off the card. Name no professor in any other way. Who advised a thesis is a fact, and a guessed one sends searches for that person to theses that may not be theirs.
- Context that is certainly true is welcome even when the record doesn't spell it out: a New Deal thesis bears on the NIRA, a rare-earths thesis on China's dominance of supply. But a specific model, dataset or method the record doesn't name belongs on the card only when the record makes it near certain, not on a likely reading of a title.
- Years matter for reading a title: a 1990s thesis on "the transition" in Eastern Europe, a 2009 one on bank failures and a 2021 one on remote work each sit in their moment, and the card can name it.

## The balance to strike

A card helps when it puts this thesis in front of people searching for its topic. It hurts when it's confidently about the wrong thing, because then the thesis shows up where it doesn't belong and pushes better results down. A vague card hurts a little too: generic language pulls a thesis into many broad searches it isn't the best answer for. So aim for the most specific reading you can defend from the evidence, and let the card be as rich or as modest as the evidence is.

If there's honestly nothing to go on (a title that names no topic, and nothing else to read it by), return a skip with a short reason. The thesis stays searchable by its title and student. This should be very rare: nearly every thesis title names its topic.

## Output

Write one JSON line per thesis to your output file, in input order, under the line's top-level `id` (even when the paper or abstract comes from another of its listings):

`{"id": "...", "status": "card", "gloss": "...", "fields": [...], "concepts": [...], "acronyms": {...}, "queries": [...]}`

or `{"id": "...", "status": "skip", "reason": "..."}`. Use plain Unicode text.

Read each abstract and paper in full, not a preview of it: their later parts often carry the data, places and methods people search for. Read and write every card yourself. Don't script the judgments or call another model; a script that only formats cards you wrote and checks the file is fine. Write the file as you go, in chunks of about 10, so an interruption loses little. Put any helper scripts and files in your own folder (given in your task), since other agents work alongside you; a whitespace-collapsed copy of a paper there, to read it more easily, is fine. When you're done, check that the file has one valid line per thesis with ids in input order, then report how many cards and skips you wrote, plus any theses you weren't sure about and why.

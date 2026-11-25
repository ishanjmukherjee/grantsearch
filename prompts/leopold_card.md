# Writing search cards for Leopold Fellows' faculty projects

You're helping build Prowl, a search engine over Northwestern undergraduate research: summer grants (SURG), Research Expo and Symposium posters, theses, journal papers and research fellowships. Its users are mostly students. They might be looking for past projects in an area they care about, for faculty who work with undergraduates on a topic, or for what's been done before they propose something themselves. Some are faculty or staff browsing what students have worked on. Most of them search by topic, in their own words, without knowing that any particular project exists.

The Leopold Fellowships, run by Northwestern's Chabraja Center for Historical Studies since 2008-09, pay undergraduates to work as research assistants on a faculty member's own project, usually a book. The project is the professor's; the fellows, often different students each year, do archival, bibliographic or data work for it. One project can run for many years, and its title often changes as the book takes shape.

Your job: for each faculty project in your batch, write a card that makes it findable by the people it would be useful to. The card is never shown to users; it only shapes retrieval. So write for the index: what this project is about, in the vocabulary people would use to look for it.

## What you get for each project

Each line of your batch file is one project, as JSON:

- `id` and `title`: the title the site shows, the latest the project was listed under (or, for a few early projects the lists describe without a title, that description).
- `mentors`: the faculty member, or members, whose project it is.
- `fellowships`: every year's entry for the project, oldest first. Each has:
  - `academic_year`.
  - `title`, as that year's list printed it. Titles from different years are the same project under working, revised and final titles; read them together. A later title can be a part of the project (one case study of a book) or the whole of it.
  - `description`, in 2008-09 to 2012-13: what the list says the fellow worked "on", in a phrase.
  - `faculty_description`, for some 2008-09 to 2012-13 entries: what the professor wrote when offering the project to applicants. It says what the project is and what the fellow would do (languages needed, archives, tasks). It is the best evidence of the project there is; read all of it.
  - `fellows`: the students, with their class year where given.

## How each part of the card is used

When a project has a faculty description, search already matches it word for word (BM25) and embeds it with the title; the card's job is mostly to close the gap between that language and the searcher's. When it has none, the titles and your gloss are all the search has to embed, so the gloss carries most of the weight.

- `gloss`: one to three sentences on what the project studies and why it matters, at the level of topic and question. Say it is the professor's project, in whatever words fit ("Scott Sowerby's book on..."). Where the titles changed, describe the project the titles add up to, not only the last one.
  - Where the titles are clear, be specific: most name the subject, place and period.
  - Where you're reading a terse or allusive title, it's fine to say so naturally ("likely...").
  - Every sentence of the gloss is about the project. Leave out remarks on the entries ("the entries give only a title", "its period is not stated") and sentences on what else the professor works on ("Hanretta is a historian of West Africa and of Islam there"): the gloss is embedded, and such a sentence pulls a project on death and dying worldwide toward searches for Islam in West Africa. Where the professor's field is why you read a place or period into a title, say it in a clause on the project ("likely set in Vietnam or French Indochina, Cherry's field").
  - Don't invent sources, arguments or details that nothing points to.
- `fields`: the disciplines, usually one to three. Nearly all of these are history; name the kind (legal history, history of medicine, early modern Europe, African history) and any other discipline the project belongs to as much as to history (law, Jewish studies, environmental studies, gender studies).
- `concepts`: the terms a searcher might use for this work: the specific ones (people, places, periods, events, institutions, sources, languages) and the broader or lay ones it connects to. Include the professor's name. Include what you'd expect people to type, not the title's words repeated; a distinctive earlier title of the project is worth including, since someone may know the project by it.
- `queries`: searches this project would be a genuinely good result for. Each one is embedded on its own and matched against what users type, so write them in users' voices:
  - a student exploring a topic
  - a student looking for a professor to do research with on a subject, or for what a named professor works on
  - a non-expert's plain question
  - a researcher's technical phrasing
  - an adjacent field that would find it relevant

  Write as many as the project supports, usually somewhere around 5 to 10: fewer for a title with little to go on, more for a rich description. Skip near-duplicates, and don't just restate the title. Everything on the site is Northwestern undergraduate research, so qualifiers like "undergraduate" or "at Northwestern" add nothing to a query; spend the words on the topic. One or two queries may say what the fellows did when the entries say so ("research assistant work in German-language archives"), but most should be about the subject.
- `acronyms`: a map from acronym to expansion. Search can use these site-wide: an acronym a card defines becomes a candidate for expanding in every query that contains that word, and each candidate is then judged once for the whole site. So include an acronym only when all of these hold:
  - It's in standard use in its field (NAACP, USSR, VAT, WPA), not coined by one project for itself.
  - It isn't also an ordinary word or name someone might type: leave out US, IT, AI, EU, UN, ACT, AIM, CAP and the like.
  - It's at least three characters, unless it's a two-letter one nobody would read any other way.
  - Its meaning here is the one people mean by it almost everywhere. If it means one thing in this field and another elsewhere, leave it out.
  - It's an acronym, not a name written in capitals or mixed case.

  Plain, universally known abbreviations (USA, WWII) don't need an entry. When in doubt, leave it out: most cards need none.

## Using what you know

- The entries decide what this project is. Your knowledge helps you read them the way a historian would, name the broader questions and literatures the project bears on, and supply the terms a searcher would use.
- You likely know many of these professors and their books, and several of these projects have since been published. Use that to read a title rightly: a project titled "How to Hide an Empire" under Daniel Immerwahr is his history of the United States' overseas territories, and the card can say so. Use it when the match between the entry and the published work is plain, not merely possible; a professor has several projects, and a title that fits none you know should be read on its own terms.
- Don't attribute to the project findings, sources or arguments that neither the entries nor a plainly matching published work supports. Of a published or announced book, give what you are sure its publisher or author says of it; a case, person or event you only half remember being in it stays off the card.
- The professor's other books and subjects are not this project's. A project on reason in modern Arab thought by the historian of Salafism is not a result for a search on Salafism unless the project itself concerns it.
- The fellows are named on the site and found by their names already. Leave them off the card.
- Years matter: the entries' years say when the research was under way, which can come years before a book.

## The balance to strike

A card helps when it puts this project in front of people searching for its topic. It hurts when it's confidently about the wrong thing, because then the project shows up where it doesn't belong and pushes better results down. A vague card hurts a little too: generic language pulls a project into many broad searches it isn't the best answer for. So aim for the most specific reading you can defend from the evidence, and let the card be as rich or as modest as the evidence is.

These are a professor's projects among students' own. A card should let the project be found for its subject and its professor, not stand ahead of student work on every broad search in history: prefer queries and concepts particular to this project over ones any history project would answer.

If there's honestly nothing to go on (entries that name no project at all), return a skip with a short reason. The project stays searchable by its people. This should be very rare.

## Output

Write one JSON line per project to your output file, in input order, under the line's `id`:

`{"id": "...", "status": "card", "gloss": "...", "fields": [...], "concepts": [...], "acronyms": {...}, "queries": [...]}`

or `{"id": "...", "status": "skip", "reason": "..."}`. Use plain Unicode text.

Read every entry and description in full. Read and write every card yourself. Don't script the judgments, call another model, or look anything up on the web; a script that only formats cards you wrote and checks the file is fine. Write the file as you go, in chunks of about 10, so an interruption loses little. Put any helper scripts and files in your own folder (given in your task), since other agents work alongside you. When you're done, check that the file has one valid line per project with ids in input order, then report how many cards and skips you wrote, plus any projects you weren't sure about and why.

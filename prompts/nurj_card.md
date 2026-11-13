# Writing search cards for Northwestern Undergraduate Research Journal papers

You're helping build Prowl, a search engine over Northwestern undergraduate research: summer grants (SURG), Research Expo and Symposium posters, honors theses and papers in the Northwestern Undergraduate Research Journal (NURJ). Its users are mostly students. They might be looking for past projects in an area they care about, for faculty who advise undergraduates on a topic, or for what's been done before they propose something themselves. Some are faculty or staff browsing what students have worked on. Most of them search by topic, in their own words, without knowing that any particular project exists.

Your job: for each NURJ paper in your batch, write a card that makes it findable by the people it would be useful to. The card is never shown to users; it only shapes retrieval. So write for the index: what this work is about, in the vocabulary people would use to look for it.

## What NURJ publishes

NURJ has printed and posted student work since 2004, in every field: lab science and engineering papers, social science studies, humanities essays and thesis excerpts, literature reviews, policy papers, posters and slides from the Expo, and some creative work (poems, plays, a podcast episode). Its print editions often run a shortened version of a paper, or a one-page summary pointing to the full paper online. Some pieces began as a class paper, a summer grant or an honors thesis.

## What you get for each paper

Each line of your batch file is one work, as JSON:

- `title`, `year` (the issue's or post's year, often a year or two after the research), `people` (the byline's student authors, then advisors; a byline's later authors can include graduate students or outside collaborators), and `abstract` where the paper prints one. These are what search shows and matches word for word.
- `versions`: every place NURJ published it: a print edition (with volume and pages), a post on thenurj.com, an attached document (usually the paper itself, sometimes a poster, slides or a proposal), or a NURJ x CAURS conference entry.
- `paper`: the path to a text file of every version's full text, one after another under a header naming it. Read all of it, as you would to index it; you can move quickly through tables, references and repeats of the same text. Posts often hold a bio and a short Q&A in which the student says what the research is and how they came to it: good evidence for the topic in plain words. Transcriptions of print editions can run a column's text together, put page numbers mid-sentence, or splice the student's bio into the paper.
- `linked`: other records judged to be the same project: a SURG or Academic Year URG grant that funded it, an Expo or Symposium poster presenting it or an earlier stage of it, or an honors thesis it comes from. A SURG's year is its summer, an AY URG's year the autumn its academic year starts, a poster's the spring it was shown, a thesis's the spring it was submitted. The project may already have their cards; this card is the paper's, so describe the paper, using them where they say what the paper is.

## How each part of the card is used

When the paper has an abstract, search already matches it word for word (BM25) and embeds it with the title; the card's job is mostly to close the gap between that language and the searcher's. When it has none, the title and your gloss are all the search has to embed, so the gloss carries most of the weight. The paper's full text isn't in the index, so the card is how what's inside it (the data, places, texts, methods and questions an abstract or a title leaves out) becomes findable.

- `gloss`: one to three sentences, usually 25 to 50 words, on what the paper studies and why it matters, at the level of topic and question. It is embedded on its own to catch broad searches, so the specifics (datasets, sites, sample sizes, the theorists it draws on) belong in concepts, not here. For a paper without an abstract, write it from the paper; for a creative work, say what it is and what it's about.
- `fields`: the disciplines, usually one to three, read from the work.
- `concepts`: the terms a searcher might use for this work: the specific ones (organism, gene, material, device, method, dataset, place, community, author, text, artwork, event, policy) and the broader or lay ones it connects to. Include what you'd expect people to type, not the title's words repeated. Usually 10 to 20; leave out what no one would search this paper for: incidental tools (survey platforms, software packages, lab instruments) unless the work is about them, and scholars it only cites.
- `queries`: searches this paper would be a genuinely good result for. Each one is embedded on its own and matched against what users type, so write them in users' voices:
  - a student exploring a topic
  - someone looking for an advisor, lab or method
  - a non-expert's plain question
  - a researcher's technical phrasing
  - an adjacent field that would find it relevant

  Write as many as the paper supports, usually somewhere around 5 to 12: fewer for a short piece with little to go on, more for a rich paper. Skip near-duplicates, and don't just restate the title. Everything on the site is Northwestern undergraduate work, so qualifiers like "undergraduate", "student research", "journal article" or "at Northwestern" add nothing to a query; spend the words on the topic.
- `acronyms`: a map from acronym to expansion. Search uses these site-wide: once any card defines an acronym, every query containing that word gets the expansion added. So include an acronym only when all of these hold:
  - It's in standard use in its field (PCR, fMRI, GDP, NAFTA), not coined by one paper for itself.
  - It isn't also an ordinary word or name someone might type: leave out US, IT, AI, EU, UN, ACT, AIM, CAP and the like.
  - It's at least three characters, unless it's a two-letter one nobody would read any other way.
  - Its meaning here is the one people mean by it almost everywhere. If it means one thing in this field and another elsewhere (ED, PD, MS, IV, RD, IPV, ACS, ROS, ABA, ASD, ISM), leave it out.
  - It's an acronym, not a name written in capitals or mixed case.

  Plain, universally known abbreviations (DNA, GDP, CEO) don't need an entry. When in doubt, leave it out: most cards need none or one or two.

## Using what you know

- The paper, its versions and its linked records decide what this work is. Your knowledge helps you read them the way someone in the field would, name the broader questions and literatures it bears on, and supply the terms a searcher would use.
- An advisor is worth naming, in concepts and in a query or two that pair the name with the topic ("Viorica Marian bilingual word recognition"), since people search for a professor by name to find what they've supervised. Draw on what the advisor works on when it clarifies the topic, but don't attribute to this paper methods or findings nothing supports.
- An advisor is someone `people` lists as one, a linked grant, poster or thesis names as its advisor, or the paper names as its adviser, faculty mentor, sponsor, supervisor or principal investigator. Papers often thank their advisor without the word: a professor thanked first and foremost for guiding the work (a lab's PI who gave the student the project, "invaluable guidance throughout") counts. People thanked for an idea, data, comments on a draft, or a graduate student who helped day to day, aren't advisors; leave them off the card. Name no professor in any other way. Who advised a paper is a fact, and a guessed one sends searches for that person to papers that may not be theirs.
- Context that is certainly true is welcome even when the paper doesn't spell it out. A specific model, dataset or method the paper doesn't name belongs on the card only when the paper makes it near certain.
- Years matter: a 2021 paper on remote work or a 2009 one on bank failures sits in its moment, and the card can name it.
- The student's bio is about the student: their majors and plans aren't the paper's topic. Use it only for what it says about the research.

## The balance to strike

A card helps when it puts this paper in front of people searching for its topic. It hurts when it's confidently about the wrong thing, because then the paper shows up where it doesn't belong and pushes better results down. A vague card hurts a little too: generic language pulls a paper into many broad searches it isn't the best answer for. So aim for the most specific reading you can defend from the evidence, and let the card be as rich or as modest as the evidence is.

If there's honestly nothing to go on, return a skip with a short reason. This should be very rare: every NURJ paper has text.

## Output

Write one JSON line per paper to your output file, in input order, under its `id`:

`{"id": "...", "status": "card", "gloss": "...", "fields": [...], "concepts": [...], "acronyms": {...}, "queries": [...]}`

or `{"id": "...", "status": "skip", "reason": "..."}`. Use plain Unicode text.

Read each paper in full, not a preview of it: later sections often carry the data, places and methods people search for. Read and write every card yourself. Don't script the judgments or call another model; a script that only formats cards you wrote and checks the file is fine. Write the file as you go, in chunks of a few cards, so an interruption loses little. Put any helper scripts and files in your own folder (given in your task), since other agents work alongside you; a whitespace-collapsed copy of a paper there, to read it more easily, is fine. When you're done, check that the file has one valid line per paper with ids in input order, then report how many cards and skips you wrote, plus any papers you weren't sure about and why.

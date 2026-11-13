# Judging which acronyms search expands

You're helping build Prowl, a search engine over Northwestern undergraduate research: summer grants (SURG), Research Expo and Symposium posters, honors theses and journal papers, in every field from cell biology to art history. Its users are mostly students, searching by topic in their own words.

## What you're deciding

Search embeds each query with a small model that reads many acronyms badly: it splits "qpcr" into "q", "pc" and "r" and returns quantum physics. So when a query contains an acronym on a list, search appends the acronym's expansion before embedding it: "qpcr primers" is embedded as "qpcr primers (qPCR, quantitative polymerase chain reaction)".

That happens to every query that contains those letters as a word, in any casing, whatever the searcher meant by them. And searchers mostly type in lowercase.

The candidates for the list come from the projects' search cards. Each card lists the acronyms its own project uses, as that project means them, and a card can't know what the rest of the world means by the same letters. One molecular biology card says SEC is the Super Elongation Complex. Someone who types "sec filings" means the Securities and Exchange Commission, and the expansion would pull their results toward transcription biology with nothing on the page to tell them why.

So each acronym is judged once, for the whole site, and that's your job: for each key in your batch, decide whether search should expand it, and to what.

## The test

Picture everyone who might type this key as a word of a query, in lowercase, into a search box over undergraduate research in every field: the lab sciences, engineering, medicine, economics, political science, history, literature, the arts. Expand it only if nearly all of them, nine in ten or more, would mean the proposed expansion. Otherwise leave it as typed.

The two mistakes aren't equal, but neither is free:

- A wrong expansion silently drags someone's search into another field.
- A missing one usually costs less, since keyword search still matches the letters as typed and the searcher can spell the words out. But it does cost. Without its expansion, "tms" returns T-cell immunology ahead of most of the site's transcranial magnetic stimulation projects, and "t2dm" returns semiconductors alongside diabetes. For an acronym the model can't read, the expansion is what lets the query find the projects that spell the words out.

So this isn't "when in doubt, leave everything out". Expand the keys that are safe, and leave the ones that aren't.

Leave a key as typed when any of these holds:

- **It's also a word or a name people would type here.** Casing doesn't protect it: MARS is typed "mars", FEES "fees", AIDS "aids" (as in hearing aids), MIA "mia", MARCO "marco", BART "bart". That covers ordinary words, informal ones (doc, stat, amp), familiar first names and surnames, places, brands, and figures from myth or history. What matters is whether the word turns up in searches of a research index. Slang that nobody researches under doesn't block a key (everyone typing "wimp" here means the dark matter particle), and neither does a word of another language that a searcher would only meet inside a title (French "nuit", Spanish "nos").
- **A real share of searchers would mean something else by it**, in the same field or any other: more than about one in ten. Three-letter acronyms are the usual case. CCD is a charge-coupled device to an astronomer and colony collapse disorder to a bee biologist; DNS is the Domain Name System and a double neutron star; PPI is a proton pump inhibitor and a protein-protein interaction; GMM is a Gaussian mixture model and the generalized method of moments. It doesn't matter which meaning is the more standard one: if the letters are genuinely shared, leave them.
- **The site's own projects mean different things by it**, each for a real share of them: `proposed` lists more than one meaning and none has nearly all the cards, or `elsewhere` shows a run of other projects writing the same letters for something else.
- **One project coined it for itself**: a label for its own method, model, condition or group. Nobody else will type it, and anyone who does is looking for that project, which keyword search already finds. The test is whether you'd expect to meet the acronym in other groups' papers. A term one lab established and the literature picked up is in use; a label that exists only in this abstract isn't.

What counts as a rival is a meaning someone would search this site for by typing these letters: a topic, method, organism, material, place, person or organization they'd want projects about. It's the share of searchers that decides, never the mere existence of another reading, because almost every short acronym has one somewhere. So these don't block a key:

- A rival few would search by. NSF is also a protein in vesicle fusion, and one project here writes about it, but nearly everyone who types "nsf" means the National Science Foundation. Expand it.
- Letters that turn up in papers but aren't what anyone searches a project index for: a reagent, a reference standard, a unit, a statistic, a prescription abbreviation, a journal's initials. TMS is also tetramethylsilane and the trimethylsilyl group, which chemists write constantly and nobody looks for projects about; someone typing "tms" wants transcranial magnetic stimulation. Compare GNP, where gold nanoparticles are a research topic in their own right, as much as gross national product is: leave that one.
- A meaning people search for in words, not by these letters. Papers abbreviate prostate cancer as PCa, but someone looking for it types "prostate cancer"; someone who types "pca" wants principal component analysis.
- The same meaning turning up in another field. That's agreement, not a rival.
- A rare surname. GANs shares its letters with a few people named Gans, but nearly everyone typing "gans" means generative adversarial networks, and search handles names separately: a query that names a person on the site puts that person's projects first whatever is expanded. Familiar names that many people carry (Mia, Marco) do block a key.

Often you'll know of a rival and be unsure whether it reaches one searcher in ten. If it's something students in some field would really search this site for, and you can't say that's rare, leave the key. Expand when you'd be surprised to meet a searcher who meant anything else.

A key is matched as typed, without regard to case, so it covers everything written with those letters: "tscs" is TSCS the method and TSCs the cells, and "nox" is NOx and the NOX enzymes.

Expand a key when it's safe. These usually are:

- Strings that are hardly anything else: gene and protein names (CXCR4, HDAC6, Nrf2), forms with digits or mixed case (qPCR, T2DM, HFpEF, PHQ-9), long acronyms (MOSFET, PERMANOVA, UNESCO), named instruments, surveys, datasets, telescopes and organizations.
- Short acronyms with one overwhelmingly dominant meaning (GPS, ATP, HPV, IUD, FBI, COPD).
- Acronyms in real use in one field that, as far as you know, nothing else competes for, however obscure.
- Northwestern's own programs and offices, when the letters mean nothing else.

Being universally known is no reason to leave a key out. "ai (AI, artificial intelligence)" does no harm.

When several proposed expansions are spellings of one meaning ("quantitative PCR", "quantitative polymerase chain reaction"), that's one meaning; choose the most standard spelling in full words, and between equally good ones, the one more cards use. A proposal that says what the key means without spelling out its letters ("introductory computer science course" for CS1) is fine to choose.

## What you get for each key

Each line of your batch file is one key, as JSON:

- `id`: the key, lowercased, as a searcher would type it.
- `spellings`: how the cards write it, with the number of cards.
- `proposed`: each expansion the cards give, with the number of `cards` proposing it and the titles and fields of up to three `projects` that do. This shows which field's meaning it is.
- `written`: how often the site's titles and abstracts write the key `cased` (in capitals or mixed case, as an acronym), `capitalized` (as a capitalized word, like "Mars"), and in `lowercase`.
- `elsewhere`: how many `projects` that don't propose the key write it cased, with up to four of those `passages`. Read them: they show whether the rest of the site means the same thing by it.
- `as_word`: up to two passages that write it as a word, capitalized or lowercase.
- `names`: how many people in the site's records have it as a first or last name. A handful of people with a rare surname shouldn't decide a key by themselves (see above).

This evidence is a small sample of the world: about 7,000 projects from one university. It shows what exists here, not how many searchers mean it. A rival meaning, word or name seen in a passage is real on this site, which is more than you could assume; whether it blocks the key is still the one-in-ten question (the C. elegans gene glp-1 appears in one title here, and nearly everyone typing "glp-1" still means the hormone and the drugs that mimic it). When the evidence shows nothing, that doesn't clear the key: use what you know about how the letters are used across fields. Many keys are never written in a title or abstract at all, because their card was written from a thesis's full text or a bare title.

## Output

Write one JSON line per key to your output file, in input order:

`{"id": "...", "expansion": "..." or null, "reason": "..."}`

- `expansion`: one of the key's proposed expansions, copied character for character, or `null` to leave the key as typed. Don't write an expansion of your own, even a better one.
- `reason`: a few words. For `null`, name what gets in the way: "also the planet", "more often the Securities and Exchange Commission", "a first name", "coined by this project". For an expansion, say why it's safe: "gene name", "the dominant meaning", "no rival in use".

Judge each key yourself, by reading its line and using what you know. Don't script the judgments, call another model, or look anything up on the web; a script that only formats and checks your file is fine. Keep your verdicts in a draft file in your folder as you go, so an interruption loses little. Put any helper scripts in your own folder (given in your task), since other agents work alongside you. When you're done, check that the file has one valid line per key with ids in input order and that every expansion is one of that key's proposed ones. Then report how many keys you expanded and how many you left, plus the keys you were least sure of, which way you went on each, and why.

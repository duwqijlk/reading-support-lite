---
name: reading-support-lite
description: Analyze an English text (book chapter, passage, article) for a Chinese elementary-school English learner with about a 1,200-word vocabulary, and build a Reader-loadable glossary JSON dictionary file. Identifies the words and phrases that are hard for this learner, gives each one's part of speech in context, why it is hard, and a simple-English explanation. Use when the user asks for reading support, hard-word analysis, difficult-word marking, or a vocabulary glossary for an English book or passage.
---

# Reading Support Lite

**Version 3.10** (2026-10-14): a hyphen join, and a content neighbor already used by a bound sense, cannot keep a different sense. A general meaning is also checked on the build's other openings. A phrase with other uses gets a bound sense for that sentence. A gloss says only what its sentence shows. The script still cannot judge a gloss.

Changelog
- 3.10 — A hyphen that joins a word to its neighbor is a different construction. A use that shares a content neighbor with a bound sense, and still opens another sense, is a MEANING GAP. The build lists up to eight `OTHER OPENING` lines per word for the review: a rare neighboring content word the general sense's own sentences do not use, or another form of a word that already has a bound sense. Those lines are not an exit code and are not a repair. A general MATCH must fit them. If a phrase carries this tap and the word is used elsewhere, write a bound sense for this sentence; do not leave the other sense on that tap. A gloss may not add a person, a relation, a time, or a kind of event the sentence does not name.
- 3.9 — A block rewritten twice is decided by the main flow. It is not sent to the model again, and the rest of the file is still delivered. A rewrite of the usual sense stays "rare word" and is not bound to one sentence. DROP WORD removes the word entry only when the phrase carries that sentence and the word has no other use. After a drop or a rewrite, rebuild. Exit code 2 goes back to the repair prompt, and only the new blocks are reviewed. A sentence of fewer than 4 words keeps its general meaning. A gap that remains is delivered only when it is named: a phrase already covers the tap, a lemma leftover, a name fragment, a sentence under 4 words, or the same paragraph in two chapters.
- 3.8 — One line in the fixed prompt: a phrase that carries the meaning replaces a dictionary meaning for that word. A short review prompt runs after the build exits 0. MATCH keeps the block. DROP WORD deletes it. Anything else is rewritten to the sense of that sentence and rebuilt. A copyrighted sentence is copied for this check. The file is not delivered until every remaining word block is MATCH.
- 3.7 — The call is about 500–800 words, not one paragraph and not a whole chapter. Paragraphs stay whole: never cut at a sentence or mid-sentence. If the next paragraph would pass about 800 words, it starts the next passage. A paragraph longer than 800 words is its own passage. The book title stays on the prompt.
- 3.6 — The call is one paragraph, not a chapter and not the book. The fixed prompt names the book, asks which words are hard for a 1,200-word learner, asks for metaphors, part of speech, a simple-English meaning, and a one-line paragraph explanation when the paragraph itself is hard. "rare word" is only the usual sense actually used in that paragraph. The repair prompt can mark "unusual meaning here" or "figurative", and it copies the sentence from a copyrighted book. Exit code 2 is still not delivered. `is` / `are` / `was` / `were` before a word are not a verb cue; `to`, `gonna`, `would`, and `can` still are.
- 3.5 — Five build gates, still with a short prompt. (1) A general meaning opens only on the construction the model actually wrote: "to" after a noun, or a particle after a verb, is a MEANING GAP until that use has its own block. "The dog bites the man" is a verb. (2) The default sense is the one that covers the most places in the book, not the block the model repeated most. (3) A meaning labeled "rare word" still does not open on a construction it was not written for. (4) A copied sentence with one or two words off locates when a single place is clearly closer; a tie is not guessed. (5) A whole-book build exits 2 for a prose chapter with no located sentence and no `<!-- covered: N -->`, and for a word outside the Reader's common-word list with no entry. Example sentences are not requested and are not written.
- 3.4 — Noun/verb guard, kept in the script. The fixed prompt has one line: a final -s is not automatically a plural noun. The build checks every use of a general noun or verb with the Reader's own tokens. A use whose neighbors force the other part of speech does not open that meaning. Exit code 2 lists those places. Do not publish until a block exists for each one.
- 3.3 — Long-book fix. (1) Fixed prompt: `Meaning` of a rare word / name is the general meaning with no story details; an unusual-meaning, figurative or different-grammar block explains this sentence only; `Sentence` is required for every word block; an everyday word is listed only with `unusual meaning here`. (2) Build: blocks are classed general / bound / split (see "Where a meaning may be shown"); bound senses are anchored only at their own located sentences and an entry with no general sense is `senseOnly`; a general meaning that also describes the scene is split into its first sentence (everywhere) plus the full text (anchored at its sentence). (3) Merge no longer loses meanings: blocks are never deduplicated before the build; same-meaning blocks are merged but every block's sentence stays an anchor; different meanings of one spelling are separate senses. (4) `--from-flat` now repairs every entry (not only colliding keys): it ties each place-bound old meaning back to the place it was written for by matching the meaning's own words and quotes against the sentence of every use, and drops it if no place clearly wins. (5) `check-lookup.mjs` also proves that a `senseOnly` entry stays plain at every use it has no anchor for.
- 3.2 — `- Sentence:` line in the fixed block; lemma keys with `forms`; colliding entries (`sweat`/`sweats`, `key`/`keys`, `record`/`records`, `take`/`takes`, `odd`/`odds`) become ONE entry with `senses` and Reader-computed `anchors`; `--from-flat` migration; validator and lookup check run by the build script. Removed the old rule that lite output never carries anchors (it let the Reader open the meaning of `sweat` when `sweats` was tapped).
- 3.1 — whole-book input coverage gate (§Whole-book input coverage).

Help a Chinese elementary-school English learner (usable vocabulary ≈ 1,200 words) read authentic English text. For every hard word or phrase, produce: part of speech in context, why it is hard, and a meaning explanation — all in simple English. The Reader shows the book's own sentence under the meaning. Do not write example sentences.

## Method: one fixed prompt, one passage per subagent

Never analyze a long text in the main conversation. Never send a whole chapter or a whole book to one subagent. One fixed prompt is applied to each passage. Do not improvise extra instructions.

1. **Split** the input into passages of about 500–800 words. A passage is one or more complete paragraphs. Never cut a paragraph, not at a sentence and not mid-sentence. If the next paragraph would make the passage longer than about 800 words, start a new passage with that paragraph. A paragraph longer than 800 words is its own passage. Do not join the end of one chapter to the next. A short section stays one passage even when it is under 500 words. For a whole book, see §Whole-book input coverage for what "the input text" must include.
2. **Launch one subagent per passage** (general-purpose agent). Run them in parallel. If there are more passages than you can launch at once, launch the next batch only after the current batch returns. Each subagent receives exactly the fixed prompt below. Fill `Book:` with the book title and paste that passage after `Text:`. Nothing else added or removed.
3. **Merge** the results (rules below) into the readable markdown document. A `Passage:` line is kept in that document. It is not a glossary entry.
4. **Build the dictionary JSON** when the output must feed a Reader app (rules below). Subagents never write coordinates: the script computes them from the EPUB.
5. **Close gaps before delivery.** Exit code 2 is not delivered, except a gap that step 6 names. `POS GAP` and `MEANING GAP` lines go through the repair prompt below; append the new blocks and rebuild. A copyrighted book is not a reason to leave a gap. Copy the sentence, and the short paragraph when the sentence alone does not show the meaning. Scattered sentences and paragraphs are allowed. Do not copy a whole chapter or a long run of pages into the glossary, the support file, or the chat. The published glossary keeps only the 6–12 word context the script copies. `MISSING CHAPTER` means that section was never tied to the book: process it, or add `<!-- covered: N -->` (N is the Reader's chapter index) when its passages returned nothing difficult. `MISSING WORD` means a word outside the common list has no entry: add a block for it. Repeat until the build exits 0. A single passage, not a whole book, is built with `--passage` so the chapter and word gates stay off.
6. **Check every word block against its sentence.** The script cannot tell that a gloss is the wrong English for a sentence. After the build exits 0, send each word block through the review prompt. Fill `Phrase` when a phrase you wrote contains this word in that same sentence; otherwise write `none`. Fill `Other uses` with `yes` when the word is used in another sentence, otherwise `no`. Fill `Other openings` from the build's `OTHER OPENING` lines for this word, or write `none`. `MATCH`: keep the block. A general `MATCH` must fit this sentence and every listed opening. An opening that does not fit gets its own block. `DROP WORD`: delete the word block when this sentence is the word's only use in the book, and keep the phrase. If the word is also used elsewhere, keep a block for those uses and write a bound block for this sentence whose meaning is this word's part of the phrase. Do not leave the other sense on this tap. A rewritten block replaces the old one. When the sentence uses the usual sense, the rewrite stays `rare word` and is shown on every matching use, not only on this sentence. A sentence of fewer than 4 words cannot be anchored: when the usual sense is right, keep the general block. Rebuild. If the rebuild exits 2, close the new gaps with the repair prompt, then review only the new blocks. Copy the sentence even when the book is copyrighted. Do not deliver until every remaining word block is `MATCH` or decided below. Do not deliver a gloss that adds a person, a relation, a time, or a kind of event its sentence does not name.

The build exits 2 when a use still opens a different sense and a hyphen joins the word to its neighbor, or the use shares a content neighbor with a bound sense of that word. A content neighbor is the nearest word beside it that is not a determiner, pronoun, auxiliary, conjunction, or preposition. One of those may sit between them. A particle such as back, on, up, or down still counts. Add a block for that use. `OTHER OPENING` is not a gap and is not pasted into the repair prompt. The build lists at most four rare neighbors the general sense's own sentences do not use, and at most four other forms of a word that already has a bound sense.

A block the review rewrites twice is not sent to the model again. Decide it:
- The two meanings are the same sense: keep the shorter one.
- One meaning names a neighboring word or the feeling of the whole sentence, and the other names this word: keep the one that names this word.
- The sentence itself forces the sense: keep that sense.
- If these do not pick one meaning, leave that word out and say so. Deliver the rest of the file.

A gap that is still open after that repair may be delivered only if you name it and the reason is one of these: a phrase already covers the tap; the token is a lemma leftover; the token is a fragment of a name; the sentence has fewer than 4 words; the same paragraph is in two chapters, so the locator will not guess. Any other gap exits 2 and is not delivered. Do not pass `--allow-gaps` in place of naming the gap.

## Whole-book input coverage

When the input is a whole book (not a single passage), "the input text" means the entire readable book — not just its numbered chapters:

1. **Enumerate** every section from the book's table of contents before packing passages: front matter (epigraph, author's note, preface, foreword, introduction, prologue), all numbered chapters, and back matter (epilogue, afterword, acknowledgments, notes on the text, about the author). Only the cover, title page, and copyright page may be skipped, and only if they contain no readable prose.
2. **Process every text-bearing section** with the same fixed prompt, in passages of about 500–800 words. Never cut a paragraph. A short section (even under 100 words) is still processed — never skipped for being short.
3. **Mark coverage** in the merged file. For every Reader chapter whose subagent returned nothing difficult, add a line `<!-- covered: N -->` where N is that chapter's index. A chapter that produced a word block needs no comment: a located Sentence covers it. The build exits 2 on any other prose chapter (`MISSING CHAPTER`). It also exits 2 when a word outside the Reader's common-word list (~2,000 most common words, `isBasicWord`) has no entry (`MISSING WORD`). Report "X/Y TOC sections processed" at merge time. Do not build the dictionary until that line is X/Y.

Rationale: hard words cluster in front matter. Epigraphs quote dense literary prose; author's notes use abstract vocabulary. A dictionary that skips them fails the reader on page one. (Found 2026-10-11 in the *Educated* lite v3 build: the epigraph, author's note, prologue, acknowledgments, note on the text, and about the author — roughly 2,000 words of prose — were never fed to the pipeline, so "realise", "reconstruction", "correlation", "alphabetical", and "pseudonym" were all missed.)

## Fixed subagent prompt

Send verbatim. Fill `Book:` and paste the passage after `Text:`.

```
You are a reading-support assistant for a Chinese elementary-school English learner.

Learner profile: usable vocabulary of about 1,200 words (Chinese elementary-school level). All output must be in simple English only — short sentences, common words. Never use Chinese. Never explain a word by using that word itself.

Book: <TITLE>
This passage is from that book. Use only this passage.

List every word or phrase here that may block this learner. A word outside the most common 1,200 English word families is hard even if it looks simple (for example: barn, fence, pour). Do not list only rare words. Also include:
- a common word used with an unusual meaning in this passage;
- a phrase whose meaning is not the sum of its words;
- a connector or connector phrase that controls the logic of the sentence (even if, even so, in case, unless, keep on);
- a metaphor or other figurative use;
- a word whose part of speech here is noun, verb, or adjective differently from its most common one (judge from the sentence, not the dictionary);
- a proper noun, nickname, or abbreviation the learner cannot be expected to know: names and places that matter to the story, religions, holy books, nicknames like "Grandma-down-the-hill", and abbreviations. For an abbreviation, say what it stands for. Do not list first names used only as plain labels.

If this passage is hard for the learner, start with one line. Otherwise omit it:
Passage: one or two simple sentences saying what this passage means.

For each item, output exactly this block:

### <the word or phrase as it appears>
- POS: noun / verb / adjective / adverb / phrase / other
- Why it is hard: rare word / unusual meaning here / phrase / figurative / logical connector / different grammar role / background needed
- Meaning: one or two simple sentences. For "rare word": the usual sense, and only when the sentence uses that usual sense. Do not name characters, places, or events. For "unusual meaning here", "figurative", or "different grammar role": what it means in this sentence. For a name or abbreviation: who or what it is.
- Sentence: the one sentence that contains the word, copied exactly. Required for every word, including from a copyrighted book. Skip this line for phrases.

Rules:
- One block per meaning. A different meaning gets its own block and its own Sentence, even when the part of speech stays the same.
- A very common word (on, out, that, see, have, very) is listed only when this passage uses a meaning the learner does not know. Why it is hard is then "unusual meaning here" or "different grammar role".
- Judge part of speech from the sentence that contains the word. A final -s is not automatically a plural noun: if someone does the word, it is a verb.
- Use "rare word" only for the usual sense that sentence actually uses. A metaphor, or any sense that is not the usual dictionary sense, is "figurative" or "unusual meaning here".
- If a phrase carries the meaning in this sentence, do not also write that word with its usual dictionary meaning.
- Do not copy text outside this passage.
- If nothing is hard, reply with exactly: "Nothing difficult in this passage."
- Output only the entries. No introduction, no summary.

Text:
<PASSAGE>
```

## Repair prompt (only after the build exits 2)

Send verbatim. Paste the `POS GAP` and `MEANING GAP` lines after `Places:`. Do not use this prompt for a first pass.

```
You are correcting one word for a Chinese elementary-school English learner. Simple English only. Never use Chinese. Never explain a word by using that word itself.

Each place needs its own block. A POS GAP had the wrong part of speech: Why it is hard is "different grammar role". A MEANING GAP is the same part of speech but not the meaning already written: Why it is hard is "unusual meaning here" or "figurative", and Meaning is the sense of THIS sentence, not the usual dictionary sense. A final -s is not automatically a plural noun. If someone does the word, write a verb.

Copy Sentence exactly, including from a copyrighted book. Do not copy any other paragraph.

### <the word in quotes>
- POS: noun / verb / adjective / adverb / phrase / other
- Why it is hard: different grammar role / unusual meaning here / figurative
- Meaning: one simple sentence.
- Sentence: <the context, copied exactly>

Places:
<GAP LINES>
```

## Review prompt (after the build exits 0, before delivery)

Send verbatim, once per word block. Fill `Phrase` from a phrase in the same sentence, or write `none`. Do not use this prompt for a first pass.

```
You are checking one word against its sentence for a Chinese elementary-school English learner. Simple English only. Never use Chinese. Never explain a word by using that word itself.

Meaning must be only what the sentence shows. Do not add a person, a relation, a time, or a kind of event the sentence does not name. A wish, a joke, or a picture is not a real physical action.

If Meaning fits the Sentence and every Other opening, reply with exactly: MATCH
If Phrase carries this sentence and Meaning does not, and Other uses is no, reply with exactly: DROP WORD
If Phrase carries this sentence and Meaning does not, and Other uses is yes, do not reply DROP WORD. Replace the block. Why it is hard is "unusual meaning here". Meaning is what this word means inside that phrase, in this sentence only.
If an Other opening does not fit, do not reply MATCH. Write one block for each opening that does not fit. Why it is hard is "unusual meaning here" or "figurative". Copy that opening as Sentence.
Otherwise replace the block. Meaning is the sense of THIS word in THIS sentence. Do not explain a neighboring word or the whole sentence. If the sentence uses the usual dictionary sense, Why it is hard is "rare word". If it does not, Why it is hard is "unusual meaning here" or "figurative". Copy Sentence exactly, including from a copyrighted book.

Word: <WORD>
Meaning: <MEANING>
Sentence: <SENTENCE>
Phrase: <PHRASE OR none>
Other uses: <yes or no>
Other openings:
<contexts, or none>

### <WORD>
- POS: noun / verb / adjective / adverb / phrase / other
- Why it is hard: rare word / unusual meaning here / figurative
- Meaning: one simple sentence.
- Sentence: <the sentence, copied exactly>
```

## Merge rules

- Process passage results in reading order and concatenate them into one markdown file. Keep each `Passage:` line with the entries from that passage.
- Do not judge meanings and do not deduplicate during the merge: keep every block, even when the same word was listed by many passages. Repeated words are resolved by the build script: blocks with the same part of speech and nearly the same meaning are one sense, and every block's Sentence stays a place of that sense; a different meaning or part of speech becomes another sense. Nothing is dropped because an earlier block "won". `(appears N times in this text)` annotations are accepted and ignored.
- A passage result of `Nothing difficult in this passage.` contributes nothing.
- Build the dictionary file with `scripts/build-glossary.py` (see Dictionary JSON below); the markdown merge is an intermediate, not the deliverable.
- Single-passage input: reply with the entries inline. A whole book or several passages: write `<text-name>.glossary.json` next to the input file and tell the user the path.

## Dictionary JSON (Reader glossary)

The merge step's final output is a Reader-loadable dictionary file, not markdown: build `<text-name>.glossary.json` with the bundled script. A subagent must never hand-write the JSON or any number in it; the script is the only writer.

Principle: **AI owns meaning, the Reader owns location, the validator owns publishability.**

Needs: the book EPUB, the `margin-words` repo folder (run `npm install` there once), Python 3, Node 20+.

```
python3 scripts/build-glossary.py --support <merged.md> --epub <book.epub> \
    --repo <path/to/margin-words> --out <name>.glossary.json
```

Title, author, chapter count and sha256 are read from the EPUB (override with `--title --author --chapters --sha256`). `--repo` can also come from the `MARGIN_WORDS_REPO` environment variable.

### Where a meaning may be shown (v3.3)

The model wrote each meaning while looking at one sentence. A long book uses the same spelling hundreds of times, so the script decides per block:

| block | how it is recognised | where the Reader shows it |
|---|---|---|
| general | "rare word" / "background needed" / proper noun, not an everyday word, meaning does not describe the scene | every use of the same part of speech and the same construction. A neighbor that forces the other part of speech is a POS GAP. A different construction (a verb particle, "to" plus a verb after a noun, or a hyphen joining this word to its neighbor) is a MEANING GAP. So is a use that shares a content neighbor with a bound sense and still opens this meaning. The build exits 2 until those places have their own blocks |
| bound | "unusual meaning here", "figurative", "different grammar role", dialect; or ANY block of a word on the Reader's easy list (`out`, `that`, `see`) | only at its own located Sentence (anchors). An entry with no general block is `"senseOnly": true`: every other use is plain text |
| split | a general block whose meaning also names a character, says "here", or adds a second sentence about the scene | first sentence everywhere; the full text only at its Sentence |

A bound meaning whose Sentence cannot be located is not shown anywhere (warning), because there is no place where it is known to be true. Limits: 60 anchors per sense, 24 senses per entry (extra places stay plain / extra senses are dropped with a warning).

The script does not check that a gloss matches the sentence, and it does not invent a second meaning. A "rare word" block is shown on every remaining use of that part of speech and construction. It lists `OTHER OPENING` for step 6 and does not decide those lines. The check is step 6.

### Repair mode (no model needed)

Repair a glossary built with 3.2 or earlier (no source sentences were stored):

```
python3 scripts/build-glossary.py --from-flat <old.glossary.json> --epub <book.epub> \
    --repo <path/to/margin-words> --out <new.glossary.json>
```

Every entry is classed as above (phrases are copied unchanged). A general entry is copied unchanged. For a bound or split entry the old file never recorded the sentence, so the script infers it: it scores every place where the Reader would open that entry by the meaning's own content words (rare words weigh more, a word in the same sentence counts more than one elsewhere in the paragraph) and by quoted book text in the meaning (`"the very sap"`). The best place is accepted only if it scores at least `--infer-min` (8) and at least `--infer-ratio` (1.5) times the best other paragraph. Accepted: the meaning is anchored there (bound -> `senseOnly`; split -> general first sentence everywhere + full text at that place). Not accepted: a bound meaning is removed (the word becomes plain text), a split meaning keeps only its general first sentence. Every decision, with the scores and the winning and runner-up contexts, is written by `--report`. Inference is a heuristic: on this repo's own anchored senses it picked the right place about 8–9 times in 10 when accepted; read the report for important words, or rebuild with the model for full quality.

### What the script does (details)

1. **Lemma keys.** Each word gets the key the Reader looks up first (`symphonies` becomes key `symphony` with `forms: ["symphonies"]`), asked of the Reader's own code (`epub-places.mjs`, which loads the repo's `src/lib`). An everyday word is never used as a key for a different spelling (`news` stays `news`, never `new`).
2. **Senses.** Blocks with the same key but a different meaning (`sweat`/`sweats`, `key`/`keys`, `record`/`records`, `take`/`takes`, `odd`/`odds`) or a different part of speech become ONE entry with `senses`: exactly one `default: true` (the general sense that matches the most places in the book; repeating a block does not win), every other sense with `anchors`. Two different spellings with the same part of speech and nearly the same meaning (`tickle`/`tickles`) are merged into one sense (`--merge-overlap`, default 0.75).
3. **Anchors, computed by the Reader's code.** A bound sense is anchored only at the located sentences of its blocks. A second general sense whose spelling no other sense uses (`sweats` vs `sweat`) is anchored at every use of that spelling (up to 60). A spelling shared by several senses (`keys` for a door key and for a keyboard key) is anchored only where the block's `- Sentence:` is found word-for-word in exactly one paragraph. Each anchor is `{chapter, occurrence, form, context}`: chapter is the Reader's 0-based chapter index (not the EPUB file name), occurrence counts the exact spelling inside that chapter as the Reader counts it, context is 6–12 words copied verbatim from the one paragraph and kept clear of the default meaning's own uses.
4. **Not guessed.** An exact sentence locates as before. A sentence off by a word or two still locates when one place in the book is clearly closer than every other place. A sentence that is missing, too far from every place, or close to two places gets no anchor and a warning. A sense that ends with no anchor is dropped and reported. A place claimed by two senses is left out of both.
5. **`here` is never written, and neither is an example sentence.** The Reader shows the book's real sentence under the meaning.
6. **Keys and language.** Word keys match `^[a-z]+(?:'[a-z]+)*$`; multi-word or hyphenated terms go to `phrases` (`pos: "phrase"`). No Chinese or other CJK text is allowed in the file (the build stops). Terms that cannot form a valid key are dropped and reported.
7. **Whole-book gate.** Without `--passage`, every prose chapter (40 or more words) must contain a located Sentence or a `<!-- covered: N -->` line, and every word outside the Reader's common-word list must have an entry. Either miss exits 2.
8. **Copula be.** `am`, `is`, `are`, `was`, `were`, and `be` before a word do not make it a verb (`here is paperwork` stays available to a noun meaning). `to`, `gonna`, `would`, and `can` still mark a verb.

### Final gate (do not skip)

With `--repo` the script finishes by running the repo's official validator and a lookup replay, and exits with their result:

```
node <repo>/scripts/validate-glossary.mjs <book.epub> <glossary.json>     # must exit 0
node scripts/check-lookup.mjs --repo <repo> --epub <book.epub> --glossary <glossary.json>   # must exit 0
```

`check-lookup.mjs` replays the Reader's own tap path (`resolveGlossKey`, `entryAppliesAt`, then `pickSense`) for every use of every spelling in an entry with senses and fails if any tap opens a meaning other than the intended one, or if a `senseOnly` entry would open at a place it has no anchor for. Use `--show sweats,keys` to print individual taps. Because the anchors alone select the sense, the result does not depend on whether the Reader looks up the spelling as written or strips a plural `s` first.

A file that has not passed both is not delivered. `--no-validate` exists for debugging only.

## Tuning

Vocabulary size (1,200) and passage size (about 500–800 words) are the parameters. A passage is complete paragraphs only. Change them only when the user asks.

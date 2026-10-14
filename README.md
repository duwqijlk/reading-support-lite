# Reading Support Lite (v3.10)

v3.10: a hyphen join, and a content neighbor already used by a bound sense, cannot keep a different sense. The review also checks the build's other openings. A phrase with other uses gets a bound sense for that sentence. A gloss says only what its sentence shows. See SKILL.md.

A minimal reading-support skill for Chinese elementary-school English learners (usable vocabulary ≈ 1,200 words). It identifies the words and phrases that block comprehension in an English text and explains each one in simple English: part of speech in context, why it is hard, and the meaning as used in the text.

## How it works

One fixed prompt, one subagent per passage:

1. Pack complete paragraphs into passages of about 500–800 words. Never cut a paragraph. Do not send a whole chapter to one subagent.
2. Launch one subagent per passage with the fixed prompt in `SKILL.md`. Fill in the book title.
3. Merge results in reading order, keeping every block (no deduplication; the build script groups meanings and keeps every block's sentence).
4. Build `glossary.json`, then check each word block against its sentence with the review prompt in `SKILL.md`. A hyphen join or a shared content neighbor that still opens another sense is a gap. Check the build's other openings too. Drop the word entry when a phrase carries that sentence and the word has no other use; otherwise write a bound sense for that sentence. A usual sense stays a rare-word meaning. The main flow decides a block rewritten twice. Close any new gaps, then deliver.

```
python3 scripts/build-glossary.py --support <merged.md> --epub <book.epub> \
  --repo <path/to/margin-words> --out <name>.glossary.json
```

A single chapter or passage adds `--passage`. A whole book does not: the build then refuses a skipped chapter or a missing hard word.

The model only writes meanings (plus the verbatim sentence each word was found in). The script computes every chapter, occurrence and context by running the Reader's own numbering code over the EPUB, and it writes `senses` + `anchors` whenever one key has more than one meaning (`sweat` water vs `sweats` clothes). It finishes by running the repo's validator (must exit 0) and a replay of the Reader's tap lookup.

### Repair an existing (3.2 or older) glossary without the model

```
python3 scripts/build-glossary.py --from-flat <old.glossary.json> --epub <book.epub> \
  --repo <path/to/margin-words> --out <new.glossary.json>
```

The design stays minimal: one fixed prompt, one worker per passage, merge by concatenation. The process controls are whole-book input coverage (every TOC section processed, reported as X/Y), the Reader-computed anchors, a review of each word meaning against its sentence, a main-flow decision when that review rewrites the same block twice, and the validator plus lookup replay as publication gate.

## Install

Copy the `reading-support-lite/` folder into your skills directory (or install the packaged zip), then ask: "Analyze the hard words in this chapter for me."

## Parameters

- Learner vocabulary: 1,200 words
- Passage size: about 500–800 words, complete paragraphs only. A longer paragraph is its own passage.
- Build script: `--merge-overlap` (0.75) and `--same-spelling-overlap` (0.34) decide when two blocks are one sense

## Files

- `SKILL.md` — the skill
- `scripts/build-glossary.py` — builds the Reader `glossary.json` with lemma keys, `senses` and Reader-computed `anchors`; migration mode; runs the validator and the lookup check
- `scripts/epub-places.mjs` — locates words and sentences in the EPUB with the Reader's own code (the only source of chapter / occurrence / context)
- `scripts/check-lookup.mjs` — replays the Reader's tap lookup for every use of every multi-sense spelling
- `evals/evals.json` — regression cases (all validated against a real test run)
- `references/example-output.md` — one full example: input paragraph + actual output
- `references/example-educated-ch1.md` — real-book run on *Educated*, chapter 1
- `references/example-anchored-out-of-my-mind.md` — what the anchored entries and the validator / lookup output look like on a real book

## Relation to the full version

The original `reading-support` skill (V5.2, coverage-first architecture with Reader locators and an official validator) is kept unchanged in the parent folder for comparison. Use this lite version when you only need per-paragraph hard-word analysis without Reader integration.

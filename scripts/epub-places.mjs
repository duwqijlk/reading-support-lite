#!/usr/bin/env node
/**
 * epub-places.mjs - the Reader owns location.
 *
 * Finds places in an EPUB using the Reader's OWN code (src/lib/*.ts, loaded by the margin-words repo's
 * scripts/lib/app-modules.mjs), so chapter numbers, word counts and paragraph text are exactly what the
 * Reader and its validator use. No numbering rule is re-implemented here.
 *
 *   node epub-places.mjs --repo <margin-words repo> --epub <book.epub> --request req.json --out res.json
 *
 * request.json:
 *   { "lemmas":    ["sweats", ...],                         surface -> the key the Reader looks up first
 *     "all":       [{"id": "a1", "form": "sweats", "avoid": ["sweat"]}],   every use of that exact spelling
 *     "sentences": [{"id": "s1", "form": "sweats", "sentence": "<verbatim sentence from the book>", "avoid": []}],
 *     "places":    [{"id": "p1", "chapter": 3, "occurrence": 2, "form": "keys", "avoid": ["keys","key"]}],  re-cut one known place
 *     "entries":   {"out": ["outs"], ...},                 the glossary's keys and forms (needed by "infer")
 *     "infer":     [{"id": "i1", "key": "out", "cues": ["miraz","army"], "skip": [[61, "out", 3]], "avoid": [...]}],
 *     "uses":      ["bite", ...],   every place the Reader would open that lemma, with left/right tokens for grammar
 *     "coverage":  true }            chapter word counts and lemmas outside the common-word list
 *   "infer" (migration only) scores every place where the Reader's tap would open entry `key` by how many of the
 *   cue words (content words of an old meaning) its sentence and paragraph contain, weighted by rarity.
 *   "avoid" = spellings whose other uses the anchor's context window must not contain (see contextAround).
 *
 * result.json:
 *   { book: {title, author, sha256, chapters}, lemmas: {surface: {lemma, easy, attested}},
 *     all: {id: {count, anchors:[{chapter, occurrence, form, context, paragraph}], skipped}},
 *     sentences: {id: {status: ok|not_found|ambiguous|too_short|form_not_in_sentence|unaligned, note, anchors}},
 *     places: {id: anchor|null},
 *     infer: {id: {uses, best: {score, cues, anchors}, second: score}},
 *     warnings: [...] }
 *
 * An anchor is written only when the place is certain. A sentence that is not in the book, is in the book more
 * than once, or whose paragraph cannot be matched word-for-word to the Reader's own word list gets NO anchor.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { resolve, join } from "node:path";

const argv = process.argv.slice(2);
const opt = (name) => {
  const at = argv.indexOf(name);
  return at >= 0 ? argv[at + 1] : undefined;
};
const repo = opt("--repo");
const epubPath = opt("--epub");
const requestPath = opt("--request");
const outPath = opt("--out");
if (!repo || !epubPath || !requestPath || !outPath) {
  console.error("Usage: node epub-places.mjs --repo <margin-words repo> --epub book.epub --request req.json --out res.json");
  process.exit(2);
}

const modulePath = join(resolve(repo), "scripts", "lib", "app-modules.mjs");
let lib;
try {
  lib = await import(pathToFileURL(modulePath).href);
} catch (error) {
  console.error(`Cannot load the Reader code from ${modulePath}: ${error.message}\nRun \`npm install\` once in the repo folder.`);
  process.exit(2);
}
const { loadAppModules, readBook } = lib;
const { format, text, basic } = await loadAppModules();
const request = JSON.parse(readFileSync(requestPath, "utf8"));
const book = await readBook(epubPath);
const { createHash } = await import("node:crypto");

const WORD = new RegExp(format.WORD_PATTERN, "gu");
const wordsOf = (s) => [...s.matchAll(WORD)].map((m) => ({ w: m[0].toLowerCase(), start: m.index, end: m.index + m[0].length }));

const warnings = [];
// Per chapter, per block: the Reader's tokens (with the occurrence number of each) lined up with the block text.
const blocks = []; // {chapter, b, text, words, aligned, occ: number[]}
const allWords = new Set();
const formIndex = new Map(); // form -> [{blockRef, j}]  (aligned blocks) and unaligned count
const unalignedUses = new Map(); // form -> count of uses inside blocks that could not be lined up
const formCount = new Map(); // form -> total uses in the book (all chapters, aligned or not)
let unalignedBlocks = 0;
book.chapters.forEach((chapter, ci) => {
  const { tokens, blocks: texts } = chapter.index;
  const counts = new Map();
  const perBlock = new Map();
  for (const token of tokens) {
    const n = (counts.get(token.w) ?? 0) + 1;
    counts.set(token.w, n);
    allWords.add(token.w);
    formCount.set(token.w, (formCount.get(token.w) ?? 0) + 1);
    if (token.b < 0) {
      unalignedUses.set(token.w, (unalignedUses.get(token.w) ?? 0) + 1);
      continue;
    }
    if (!perBlock.has(token.b)) perBlock.set(token.b, []);
    perBlock.get(token.b).push({ w: token.w, occ: n });
  }
  texts.forEach((raw, b) => {
    const textBlock = String(raw).replace(/\s+/g, " ").trim();
    const mine = perBlock.get(b) ?? [];
    const words = wordsOf(textBlock);
    // The block text must give back exactly the Reader's tokens for this block, word for word.
    const aligned = words.length === mine.length && words.every((x, i) => x.w === mine[i].w);
    const ref = { chapter: ci, b, text: textBlock, words, aligned, occ: mine.map((x) => x.occ) };
    blocks.push(ref);
    if (!aligned) {
      unalignedBlocks += 1;
      for (const x of mine) unalignedUses.set(x.w, (unalignedUses.get(x.w) ?? 0) + 1);
    }
  });
});

// paragraph index of a block, as the Reader counts paragraphs (same matching `--find` uses)
const norm = (t) => t.replace(/\s+/g, " ").trim();
const paraIndex = new Map();
const paragraphOf = (ref) => {
  const key = `${ref.chapter}:${ref.b}`;
  if (!paraIndex.has(key)) paraIndex.set(key, book.chapters[ref.chapter].paragraphs.findIndex((p) => norm(p) === ref.text));
  return paraIndex.get(key);
};

for (const ref of blocks) {
  if (!ref.aligned) continue;
  ref.words.forEach((x, j) => {
    if (!formIndex.has(x.w)) formIndex.set(x.w, []);
    formIndex.get(x.w).push({ ref, j });
  });
}

/**
 * 6-12 words copied verbatim from the ONE paragraph, containing word j.
 * `avoid` lists spellings whose other uses in this paragraph the window must not contain: the Reader falls back
 * to "an anchor's context sits around the tapped word" when a use has no anchor of its own, so a context that
 * also covers an un-anchored use of the entry (the default meaning's spelling) would steal that tap.
 * The window shrinks to stay clear of them (it may then be shorter than 6 words; the validator only warns).
 */
function contextAround(ref, j, avoid) {
  const n = ref.words.length;
  let lo = 0;
  let hi = n - 1;
  if (avoid && avoid.size > 0) {
    for (let i = j - 1; i >= 0; i -= 1) if (avoid.has(ref.words[i].w)) { lo = i + 1; break; }
    for (let i = j + 1; i < n; i += 1) if (avoid.has(ref.words[i].w)) { hi = i - 1; break; }
  }
  let from = Math.max(lo, j - 4);
  let to = Math.min(hi, from + 9);
  from = Math.max(lo, to - 9);
  const cut = () => ref.text.slice(ref.words[from].start, ref.words[to].end);
  let ctx = cut();
  while (ctx.length > 300 && to - from > 0) {
    if (to > j) to -= 1;
    else from += 1;
    ctx = cut();
  }
  return ctx.length > 300 ? null : ctx;
}

const anchorFor = (ref, j, avoid) => {
  const context = contextAround(ref, j, avoid);
  if (!context) return null;
  return { chapter: ref.chapter, occurrence: ref.occ[j], form: ref.words[j].w, context, paragraph: paragraphOf(ref) };
};

const result = {
  book: {
    title: book.title,
    author: book.author,
    sha256: createHash("sha256").update(book.bytes).digest("hex"),
    chapters: book.chapters.length,
  },
  lemmas: {},
  all: {},
  sentences: {},
  places: {},
  infer: {},
  uses: {},
  warnings,
};

for (const surface of request.lemmas ?? []) {
  const lemma = text.lookupKey(surface);
  result.lemmas[surface] = { lemma, easy: text.isEasyKey(lemma), attested: allWords.has(lemma), count: formCount.get(surface) ?? 0 };
}

for (const task of request.all ?? []) {
  const avoid = new Set(task.avoid ?? []);
  const anchors = [];
  let skipped = unalignedUses.get(task.form) ?? 0;
  for (const { ref, j } of formIndex.get(task.form) ?? []) {
    const a = anchorFor(ref, j, avoid);
    if (a) anchors.push(a);
    else skipped += 1;
  }
  anchors.sort((a, b) => a.chapter - b.chapter || a.occurrence - b.occurrence);
  result.all[task.id] = { count: formCount.get(task.form) ?? 0, anchors, skipped };
}

// A copied sentence with one or two words off still locates, when one place is clearly closer than any other.
function dice(a, b) {
  const count = new Map();
  for (const w of a) count.set(w, (count.get(w) ?? 0) + 1);
  let inter = 0;
  const other = new Map();
  for (const w of b) other.set(w, (other.get(w) ?? 0) + 1);
  for (const [w, n] of count) inter += Math.min(n, other.get(w) ?? 0);
  return (2 * inter) / (a.length + b.length);
}
function windowAround(ref, j) {
  const boundary = (i) => {
    if (i <= 0) return true;
    return /[.!?]/.test(ref.text.slice(ref.words[i - 1].end, ref.words[i].start));
  };
  let a = j;
  let b = j;
  while (a > 0 && !boundary(a)) a -= 1;
  while (b < ref.words.length - 1 && !boundary(b + 1)) b += 1;
  return { start: a, end: b + 1 };
}
function closeSentence(want, form) {
  const existing = [];
  const seenWord = new Set();
  for (const w of want) {
    if (seenWord.has(w) || !formIndex.has(w)) continue;
    seenWord.add(w);
    existing.push(w);
  }
  if (existing.length < 4 || !formIndex.has(form)) return null;
  const rarest = existing.reduce((best, w) => (formIndex.get(w).length < formIndex.get(best).length ? w : best), existing[0]);
  const scored = [];
  const seenWindow = new Set();
  for (const { ref, j } of formIndex.get(rarest)) {
    const win = windowAround(ref, j);
    const key = `${ref.chapter}:${ref.b}:${win.start}`;
    if (seenWindow.has(key)) continue;
    seenWindow.add(key);
    const slice = ref.words.slice(win.start, win.end).map((x) => x.w);
    if (slice.length < 4 || Math.abs(slice.length - want.length) > 2) continue;
    if (!slice.includes(form)) continue;
    const score = dice(want, slice);
    if (score < 0.82) continue;
    scored.push({ ref, start: win.start, end: win.end, score });
  }
  scored.sort((a, b) => b.score - a.score);
  if (scored.length === 0) return null;
  if (scored.length > 1 && scored[0].score - scored[1].score < 0.05) return "ambiguous";
  return scored[0];
}

for (const task of request.sentences ?? []) {
  const avoid = new Set(task.avoid ?? []);
  const want = wordsOf(String(task.sentence ?? "")).map((x) => x.w);
  const fail = (status, note) => (result.sentences[task.id] = { status, note, anchors: [] });
  if (want.length < 4) {
    fail("too_short", "the sentence has fewer than 4 words");
    continue;
  }
  const rarest = want.reduce((best, w) => ((formIndex.get(w)?.length ?? 0) < (formIndex.get(best)?.length ?? 0) ? w : best), want[0]);
  const at = want.indexOf(rarest);
  const found = [];
  for (const { ref, j } of formIndex.get(rarest) ?? []) {
    const start = j - at;
    if (start < 0 || start + want.length > ref.words.length) continue;
    if (want.every((w, i) => ref.words[start + i].w === w)) found.push({ ref, start });
  }
  let close = false;
  if (found.length === 0) {
    const fuzzy = closeSentence(want, task.form);
    if (fuzzy === "ambiguous") {
      fail("ambiguous", "several places are close to this sentence; not guessed");
      continue;
    }
    if (!fuzzy) {
      fail("not_found", "the sentence is not in the book word for word (or is split across paragraphs)");
      continue;
    }
    found.push(fuzzy);
    close = true;
  }
  if (found.length > 1) {
    fail("ambiguous", `the sentence is in the book ${found.length} times`);
    continue;
  }
  const { ref, start } = found[0];
  const end = found[0].end ?? start + want.length;
  const anchors = [];
  for (let i = start; i < end; i += 1) {
    if (ref.words[i].w !== task.form) continue;
    const a = anchorFor(ref, i, avoid);
    if (a) anchors.push(a);
  }
  if (anchors.length === 0) fail("form_not_in_sentence", `"${task.form}" is not in the located sentence`);
  else result.sentences[task.id] = { status: "ok", note: close ? "close match" : "", anchors };
}

// ---- the glossary's key tables (as the Reader builds them), for "places" with a key and for "infer"
const keyMap = new Map(), formMap = new Map();
for (const [key, forms] of Object.entries(request.entries ?? {})) {
  if (!keyMap.has(key)) keyMap.set(key, key);
  for (const f of forms ?? []) if (!formMap.has(f)) formMap.set(f, key);
}
const resolved = new Map(); // spelling in the book -> key it opens
if (keyMap.size > 0) for (const form of formIndex.keys()) resolved.set(form, text.resolveGlossKey(form, keyMap, formMap));
const byKey = new Map();
for (const [f, k] of resolved) {
  if (!byKey.has(k)) byKey.set(k, []);
  byKey.get(k).push(f);
}
const spellingsOf = (key) => byKey.get(key) ?? [];

// ---- places: re-cut the context of one known place (chapter + occurrence of a spelling)
const placeIndex = new Map(); // "chapter|form|occ" -> {ref, j}
for (const [form, list] of formIndex) for (const { ref, j } of list) placeIndex.set(`${ref.chapter}|${form}|${ref.occ[j]}`, { ref, j });
for (const task of request.places ?? []) {
  const hit = placeIndex.get(`${task.chapter}|${String(task.form).toLowerCase()}|${task.occurrence}`);
  const avoid = new Set([...(task.avoid ?? []), ...(task.key ? spellingsOf(task.key) : [])]);
  result.places[task.id] = hit ? anchorFor(hit.ref, hit.j, avoid) : null;
}

// ---- infer (migration of files that never recorded where a meaning was written)
if ((request.infer ?? []).length > 0) {
  const usesOf = new Map(); // key -> [{ref, j}]
  for (const [form, list] of formIndex) {
    const key = resolved.get(form);
    if (!keyMap.has(key)) continue;
    if (!usesOf.has(key)) usesOf.set(key, []);
    usesOf.get(key).push(...list);
  }
  const stemOf = (w) => w.replace(/'s$/, "").replace(/(?:ies)$/, "y").replace(/(?:es|s|ed|ing)$/, "") || w;
  // rarity of a stem = how many aligned blocks hold it
  const df = new Map();
  for (const ref of blocks) {
    if (!ref.aligned) continue;
    ref.stems = new Set(ref.words.map((x) => stemOf(x.w)));
    for (const st of ref.stems) df.set(st, (df.get(st) ?? 0) + 1);
  }
  const nBlocks = blocks.filter((r) => r.aligned).length;
  const weight = (st) => Math.log(nBlocks / (1 + (df.get(st) ?? 0)));
  const sentenceStems = (ref, j) => {
    // the sentence around word j: from the last . ! ? before it to the next one after it
    const t = ref.text;
    let a = ref.words[j].start, b = ref.words[j].end;
    while (a > 0 && !/[.!?]/.test(t[a - 1])) a -= 1;
    while (b < t.length && !/[.!?]/.test(t[b])) b += 1;
    return new Set(ref.words.filter((x) => x.start >= a && x.end <= b).map((x) => stemOf(x.w)));
  };
  for (const task of request.infer) {
    const cues = [...new Set((task.cues ?? []).map((w) => stemOf(w.toLowerCase())))].filter((c) => df.has(c));
    const skip = new Set((task.skip ?? []).map(([c, f, o]) => `${c}|${f}|${o}`));
    const avoid = new Set(task.avoid ?? []);
    for (const form of spellingsOf(task.key)) avoid.add(form);
    // quoted bits of the old meaning ("the very sap", 'have' them): a use whose sentence holds one in order wins
    const quotes = (task.quotes ?? []).map((q) => wordsOf(q).map((x) => x.w)).filter((q) => q.length >= 2);
    const holds = (ref, j, q) => {
      const ws = ref.words.map((x) => x.w);
      for (let i = Math.max(0, j - 40); i <= Math.min(ws.length - q.length, j + 40); i += 1)
        if (q.every((w, k) => ws[i + k] === w) && Math.abs(i - j) <= 30) return true;
      return false;
    };
    const scored = [];
    for (const { ref, j } of usesOf.get(task.key) ?? []) {
      if (skip.has(`${ref.chapter}|${ref.words[j].w}|${ref.occ[j]}`)) continue;
      const sent = sentenceStems(ref, j);
      let score = 0;
      const hit = [];
      for (const c of cues) {
        if (sent.has(c)) { score += weight(c); hit.push(c); }
        else if (ref.stems.has(c)) { score += 0.3 * weight(c); hit.push(c); }
      }
      for (const q of quotes) if (holds(ref, j, q)) { score += 25; hit.push(`"${q.join(" ")}"`); }
      scored.push({ ref, j, score, hit });
    }
    scored.sort((x, y) => y.score - x.score);
    const best = scored[0];
    const out = { uses: scored.length, best: null, second: 0 };
    if (best && best.score > 0) {
      const tied = scored.filter((x) => x.ref === best.ref && x.score >= best.score - 1e-9);
      const other = scored.find((x) => x.ref !== best.ref);
      out.second = other ? other.score : 0;
      out.secondAt = other ? { chapter: other.ref.chapter, cues: other.hit, context: (anchorFor(other.ref, other.j, avoid) ?? {}).context } : null;
      out.best = {
        score: best.score,
        cues: best.hit,
        chapter: best.ref.chapter,
        anchors: tied.map((x) => anchorFor(x.ref, x.j, avoid)).filter(Boolean),
      };
    }
    result.infer[task.id] = out;
  }
}

// ---- uses: every place a lemma opens, with the Reader tokens beside it (v3.4 noun/verb guard)
function neighbors(ref, j) {
  const left = [];
  for (let i = Math.max(0, j - 4); i < j; i += 1) left.push(ref.words[i].w);
  const right = [];
  for (let i = j + 1; i <= Math.min(ref.words.length - 1, j + 3); i += 1) right.push(ref.words[i].w);
  // The characters between tokens. A bare "-" is a compound ("first-place"); a space is not.
  const before = j > 0 ? ref.text.slice(ref.words[j - 1].end, ref.words[j].start) : "";
  const after = j + 1 < ref.words.length ? ref.text.slice(ref.words[j].end, ref.words[j + 1].start) : "";
  return { left, right, before, after };
}
if ((request.uses ?? []).length > 0) {
  const want = new Set(request.uses);
  const byLemma = new Map();
  for (const [form, list] of formIndex) {
    const lemma = text.lookupKey(form);
    if (!want.has(lemma)) continue;
    if (!byLemma.has(lemma)) byLemma.set(lemma, []);
    for (const hit of list) byLemma.get(lemma).push(hit);
  }
  for (const lemma of request.uses) {
    const places = [];
    for (const { ref, j } of byLemma.get(lemma) ?? []) {
      const anchor = anchorFor(ref, j, new Set());
      if (!anchor) continue;
      const { left, right, before, after } = neighbors(ref, j);
      places.push({ chapter: anchor.chapter, occurrence: anchor.occurrence, form: anchor.form, context: anchor.context, left, right, before, after });
    }
    places.sort((a, b) => a.chapter - b.chapter || a.form.localeCompare(b.form) || a.occurrence - b.occurrence);
    result.uses[lemma] = places;
  }
}

if (unalignedBlocks > 0)
  warnings.push(`${unalignedBlocks} paragraph block(s) could not be lined up word-for-word with the Reader's word list; words inside them get no anchor.`);

if (request.coverage) {
  result.book.chapterList = book.chapters.map((chapter, index) => ({
    index,
    title: chapter.title,
    words: chapter.index.tokens.length,
  }));
  const hard = new Map();
  book.chapters.forEach((chapter, ci) => {
    for (const token of chapter.index.tokens) {
      const lemma = text.lookupKey(token.w);
      if (!/^[a-z]+(?:'[a-z]+)*$/.test(lemma) || lemma.length < 3) continue;
      if (text.isEasyKey(lemma) || basic.isBasicWord(lemma)) continue;
      const row = hard.get(lemma);
      if (row) row.count += 1;
      else hard.set(lemma, { count: 1, chapter: ci });
    }
  });
  result.book.hardWords = [...hard.entries()]
    .map(([lemma, row]) => ({ lemma, count: row.count, chapter: row.chapter }))
    .sort((a, b) => a.chapter - b.chapter || b.count - a.count || a.lemma.localeCompare(b.lemma));
}

writeFileSync(outPath, JSON.stringify(result));

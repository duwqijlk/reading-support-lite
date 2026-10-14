#!/usr/bin/env node
/**
 * check-lookup.mjs - does the Reader really open the intended meaning?
 *
 * Replays the Reader's own tap path (text.resolveGlossKey -> format.pickSense, from the margin-words repo's
 * src/lib via scripts/lib/app-modules.mjs) for EVERY use, in the book, of every spelling that belongs to an
 * entry with senses. The intended meaning of a use is the sense whose anchor names that place, else the
 * default sense. Any use where the Reader opens another meaning is a mismatch (exit code 1).
 * A `senseOnly` entry (v3.3) must open ONLY at its anchors: a use with no anchor of its own must stay plain
 * (format.entryAppliesAt false), and an anchored use must open that anchor's sense.
 *
 *   node check-lookup.mjs --repo <margin-words repo> --epub book.epub --glossary book.glossary.json
 *        [--show sweats,keys,tears]     print each tap of those spellings (chapter, occurrence, meaning shown)
 *
 * Run it with the repo checkout you will publish against. With an UNPATCHED Reader (one that strips a plural s
 * before it looks at the spelling), a passing run proves the anchors alone select the right meaning.
 */
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { resolve, join } from "node:path";

const argv = process.argv.slice(2);
const opt = (n) => (argv.indexOf(n) >= 0 ? argv[argv.indexOf(n) + 1] : undefined);
const repo = opt("--repo"), epub = opt("--epub"), gpath = opt("--glossary");
const show = new Set((opt("--show") ?? "").split(",").map((s) => s.trim()).filter(Boolean));
if (!repo || !epub || !gpath) {
  console.error("Usage: node check-lookup.mjs --repo <margin-words repo> --epub book.epub --glossary file.json [--show a,b]");
  process.exit(2);
}
const lib = await import(pathToFileURL(join(resolve(repo), "scripts", "lib", "app-modules.mjs")).href);
const { format, text } = await lib.loadAppModules();
const book = await lib.readBook(epub);
const checked = format.validateGlossary(readFileSync(gpath, "utf8"));
if (!checked.ok || !checked.file) {
  console.error("The glossary does not load:", checked.errors.join("; "));
  process.exit(1);
}
const file = format.forBook(checked.file, book.chapters.length);
const glossary = file.glossary;

// the Reader's own key tables (src/components/reader.tsx `marked`)
const keys = new Map(), forms = new Map();
for (const [key, gloss] of Object.entries(glossary)) {
  if (!keys.has(key)) keys.set(key, key);
  const straight = format.plainSurface(key);
  if (!keys.has(straight)) keys.set(straight, key);
  const bare = straight.replace(/\.+$/g, "");
  if (bare && !keys.has(bare)) keys.set(bare, key);
  for (const f of gloss.forms ?? []) {
    const name = format.plainSurface(f);
    if (name && !forms.has(name)) forms.set(name, key);
  }
}

// every spelling that belongs to an entry with senses
const watched = new Set();
for (const [key, gloss] of Object.entries(glossary)) {
  if (!gloss.senses || (gloss.senses.length < 2 && gloss.senseOnly !== true)) continue;
  watched.add(key);
  for (const f of gloss.forms ?? []) watched.add(f);
  for (const s of gloss.senses) for (const f of s.forms ?? []) watched.add(f);
  for (const s of gloss.senses) for (const a of s.anchors ?? []) if (a.form) watched.add(a.form);
}

for (const w of show) watched.add(w);
const WORD = new RegExp(format.WORD_PATTERN, "gu");
let taps = 0, bad = 0, entries = new Set(), plain = 0;
const bySurface = new Map();
book.chapters.forEach((chapter, ci) => {
  const counts = new Map();
  const perBlock = new Map();
  for (const t of chapter.index.tokens) {
    const n = (counts.get(t.w) ?? 0) + 1;
    counts.set(t.w, n);
    if (!perBlock.has(t.b)) perBlock.set(t.b, []);
    perBlock.get(t.b).push({ w: t.w, n });
  }
  chapter.index.blocks.forEach((raw, b) => {
    const paragraph = String(raw);
    const words = [...paragraph.matchAll(WORD)];
    const mine = perBlock.get(b) ?? [];
    if (words.length !== mine.length || !words.every((m, i) => m[0].toLowerCase() === mine[i].w)) return;
    words.forEach((m, i) => {
      const w = mine[i].w;
      if (!watched.has(w)) return;
      const surface = m[0];
      const tap = { chapter: ci, surface, occurrence: mine[i].n, paragraph, before: paragraph.slice(0, m.index) };
      const key = text.resolveGlossKey(surface, keys, forms);
      const gloss = glossary[key];
      if (!gloss) return;
      // intended sense: the one whose anchor names this exact place, else the default
      let want = gloss.senses?.findIndex((s) => (s.anchors ?? []).some((a) => a.chapter === ci && a.occurrence === mine[i].n && (a.form ?? key).toLowerCase() === w));
      const anchoredHere = want !== undefined && want >= 0;
      if (!anchoredHere) want = gloss.senses?.findIndex((s) => s.default) ?? -1;
      taps += 1;
      entries.add(key);
      if (gloss.senseOnly === true) {
        const applies = format.entryAppliesAt(key, gloss, tap);
        if (applies !== anchoredHere) {
          bad += 1;
          console.log(`MISMATCH chapter ${ci} "${surface}" #${mine[i].n} -> senseOnly entry "${key}" ${applies ? "opens at a place it has no anchor for" : "is not underlined at its own anchor"}`);
          return;
        }
        if (!applies) {
          plain += 1;
          if (show.has(w)) {
            if (!bySurface.has(w)) bySurface.set(w, []);
            bySurface.get(w).push(`  chapter ${ci}, "${surface}" #${mine[i].n}: senseOnly "${key}" -> not underlined (plain text)`);
          }
          return;
        }
      }
      const picked = format.pickSense(key, gloss, tap);
      const expect = want >= 0 ? gloss.senses[want].meaning : gloss.meaning;
      const ok = picked.meaning === expect;
      if (!ok) {
        bad += 1;
        console.log(`MISMATCH chapter ${ci} "${surface}" #${mine[i].n} -> entry "${key}" shows [${picked.via}] "${picked.meaning.slice(0, 60)}", wanted "${expect.slice(0, 60)}"`);
      }
      if (show.has(w)) {
        if (!bySurface.has(w)) bySurface.set(w, []);
        bySurface.get(w).push(`  chapter ${ci}, "${surface}" #${mine[i].n}: entry "${key}", via ${picked.via} -> ${picked.meaning.slice(0, 70)}${ok ? "" : "   <== WRONG"}`);
      }
    });
  });
});
for (const [w, lines] of bySurface) {
  console.log(`taps of "${w}":`);
  lines.forEach((l) => console.log(l));
}
console.log(`${taps} taps checked across ${entries.size} entries (${plain} senseOnly uses correctly left plain): ${bad === 0 ? "every tap opens the intended meaning" : `${bad} MISMATCH(ES)`}.`);
process.exit(bad === 0 ? 0 : 1);

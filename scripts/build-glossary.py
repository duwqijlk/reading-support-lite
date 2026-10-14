#!/usr/bin/env python3
"""Build a Reader glossary JSON (format v2) with senses and anchors.   Reading Support Lite v3.10

AI owns meaning, the Reader owns location, the validator owns publishability.
This script never lets a model (or itself) invent a coordinate: every chapter / occurrence / context
is computed by scripts/epub-places.mjs, which runs the Reader's OWN numbering code from the
margin-words repo over the EPUB. Anything that cannot be located with certainty gets no anchor.

Two ways to run it (both need the book EPUB and the margin-words repo folder):

  1. From the merged support markdown (normal lite run):
       python3 scripts/build-glossary.py --support merged.md --epub book.epub \
           --repo /path/to/margin-words --out book.glossary.json

  2. Migration of an existing flat glossary (no model needed):
       python3 scripts/build-glossary.py --from-flat old.glossary.json --epub book.epub \
           --repo /path/to/margin-words --out new.glossary.json

What it does
  * Key = the lemma the Reader looks up first (`symphonies` -> `symphony`, forms [symphonies]).
    (Not when that lemma is an everyday word, e.g. `news` is never turned into `new`.)
  * Entries that land on the same key but mean different things (sweat / sweats, key / keys,
    record / records, take / takes, odd / odds ...) become ONE entry with `senses`:
    exactly one `default: true`, every other sense carries `anchors`.
    The default is the general sense that covers the most places in the book, not the one with the most written blocks.
  * A spelling used by only one sense is anchored at EVERY use of that spelling (up to 60).
    A spelling shared by several senses is anchored only where the located verbatim
    `- Sentence:` of the support block pins it down.
  * `here` is never written: the Reader shows the book's real sentence under the meaning.
  * A sense that cannot be anchored is dropped and reported. Nothing is guessed.
  * With --repo the repo's official validator runs at the end: exit code 0 or the build fails.
  * v3.3: a meaning written for one place (unusual use, easy word, story-specific text) is anchored only at its
    own located Sentence; an entry without a general meaning is `senseOnly` (plain text everywhere else).
  * v3.4: a general noun meaning is not shown on a use the sentence grammar makes a verb, and a general verb
    meaning is not shown on a use the grammar makes a noun ("she bites" is not "a bite of food"). Those places
    stay plain until a block of the right part of speech is merged in. The build then exits 2.
  * v3.5: a general meaning is also withheld where the construction differs from the sentences the model wrote
    ("a bite to eat" is not "a bite of food"). The default sense is the one that matches the most places.
    A sentence a word or two off still locates when one place is clearly closer. A whole-book build exits 2
    when a prose chapter was never tied to the book, or a word outside the common list has no entry.
  * v3.6: copula be (am/is/are/was/were/be) before a word does not force a verb. to/gonna/would/can still do.
  * v3.8: this script still does not compare a gloss to its sentence. That check is the review prompt in SKILL.md.
  * v3.9: a sentence of fewer than 4 words is not anchored. The script does not decide a second review failure.
  * v3.10: a hyphen join is its own construction. A use that shares a content neighbor with a bound sense
    and still opens another sense is a MEANING GAP. OTHER OPENING lines are for the review, not an exit code.
  * Repair mode (--from-flat) classifies every entry the same way and infers the lost source place of a
    place-bound meaning from its own words; no clear winner -> the meaning is not shown.

Support-markdown block (lite v3.2+):
    ### <word or phrase as it appears>      [(appears N times in this text)]
    - POS: ...   - Why it is hard: ...   - Meaning: ...
    - Sentence: <the sentence of the text the word was found in, copied verbatim>
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WORD_TOKEN = re.compile(r"^[a-z]+(?:'[a-z]+)*$")
PHRASE_WORD = r"[a-z]+(?:['-]?[a-z]+)*"
PHRASE_KEY = re.compile(rf"^{PHRASE_WORD}(?:(?:,)? {PHRASE_WORD})+$")
HEADER_RE = re.compile(r"^###\s+(.+?)\s*$")
APPEARS_RE = re.compile(r"^(.*?)\s*\(appears (\d+) times? in this text\)\s*$")
FIELD_RE = re.compile(r"^-\s*(POS|Why it is hard|Example sentences|Meaning|Sentence)\s*:\s*(.+?)\s*$")
CJK_RE = re.compile(r"[\u3000-\u303f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uff00-\uffef]")
MAX_ANCHORS = 60
MAX_SENSES = 24

POS_WORD_MAP = {
    "proper noun": "proper noun",
    "proper noun (brand name)": "proper noun",
    "other (proper noun)": "proper noun",
    "other (nickname)": "proper noun",
    "abbreviation": "abbreviation",
    "other (abbreviation)": "abbreviation",
}

STOP = set("""a an the of to in on at for and or is are was were be it its that this with as by from not no
they them their he she his her you your i we our one who which when what do does did can will would so but if
than then there here very more most some any also into out up down about over only just like use used using
people person thing things""".split())


# ----------------------------------------------------------------------------- text helpers
def clean_token(tok):
    t = tok.lower().strip().strip("\"'“”‘’()[]").strip(".,!?;:\"'“”‘’()[]")
    t = t.replace(".", "").replace("/", " ")
    return re.sub(r"\s+", " ", t).strip()


def normalize(term):
    t = term.strip().strip("\"'“”‘’")
    t = t.replace("’", "'").replace("‘", "'")
    if re.search(r"[^\s]-[^\s]", t) and " " not in t:
        t = t.replace("-", " ")
    tokens = []
    for rt in t.split():
        tokens.extend(p for p in clean_token(rt).split(" ") if p)
    tokens = [x for x in tokens if x]
    if not tokens:
        return None, "empty after cleaning"
    if len(tokens) == 1:
        if WORD_TOKEN.match(tokens[0]):
            return "word", tokens[0]
        return None, f"bad word token {tokens[0]!r}"
    key = " ".join(tokens)
    if len(key) > 60:
        return None, "phrase key too long"
    if PHRASE_KEY.match(key):
        return "phrase", key
    return None, f"bad phrase key {key!r}"


def stem(w):
    if w.endswith("ies") and len(w) > 4:
        return w[:-3] + "y"
    if w.endswith("es") and len(w) > 4:
        return w[:-2]
    if w.endswith("s") and len(w) > 3:
        return w[:-1]
    return w


def content_words(text):
    return {stem(w) for w in re.findall(r"[a-z]+", (text or "").lower()) if w not in STOP}


def overlap(a, b):
    """Share of the shorter meaning's content words that the other meaning also has (0..1)."""
    A, B = content_words(a), content_words(b)
    return len(A & B) / max(1, min(len(A), len(B)))


def norm_pos(pos):
    p = (pos or "").strip().lower()
    return POS_WORD_MAP.get(p, p)


def pos_family(pos):
    """'noun' or 'verb' when the label is one of those, else '' (adjective, phrase, proper noun, ...)."""
    p = norm_pos(pos)
    if "verb" in p:
        return "verb"
    if "noun" in p:
        return "noun"
    return ""


# Reader tokens: WORD_PATTERN keeps an ASCII apostrophe inside a word and treats a curly
# apostrophe as a break, so "she'd" is "she" + "d" and "it's" is "it" + "s".
_PRONOUNS = {"i", "you", "we", "they", "he", "she", "it"}
_DETS = {"a", "an", "the", "this", "that", "these", "those", "my", "your", "his", "her", "its", "our", "their",
         "some", "any", "no", "every", "each", "another", "both"}
_MODS = {"huge", "big", "small", "little", "large", "quick", "single", "good", "bad", "deep", "tiny",
         "one", "two", "three", "four", "five", "many", "few", "several"}
# Copula be introduces a noun or adjective ("here is paperwork"). It does not mark a verb.
# been/being and the action auxiliaries still do ("gonna bite", "would bite", "been bitten").
_COPULA = {"am", "is", "are", "was", "were", "be"}
_AUX = {"been", "being", "do", "does", "did", "can", "could", "will",
        "would", "shall", "should", "may", "might", "must", "have", "has", "had", "gonna", "let"}
_CLITIC = {"d", "ll", "m", "re", "ve"}  # she'd / she'll / I'm / they're / I've, after the curly apostrophe splits
_NEXT_VERB = {"am", "is", "are", "was", "were", "be", "been", "can", "could", "will", "would", "shall", "should",
              "may", "might", "must", "have", "has", "had", "do", "does", "did", "seem", "seems"}


# A verb's own following particle ("bite on", "give up"). "of" after a noun is a partitive, not a new meaning.
_PARTICLE = {"to", "on", "off", "up", "down", "out", "in", "into", "onto", "over", "away", "back",
             "through", "around", "about", "for", "with", "at", "from", "by"}
_OBJECTS = _DETS | {"him", "me", "us", "them", "you"}


def grammar_role(left, right, form=""):
    """Part of speech the words NEXT TO this one force, or '' when the local grammar is not decisive.

    `left` and `right` are the Reader's own lowercase tokens (4 before, 3 after). `form` is the
    word itself. Confident only: "she bites her fingernails" and "the dog bites the man" are verbs,
    "took a huge bite" is a noun. "here is paperwork" is not forced to a verb. Anything less clear
    stays '' so a real plural noun is not stripped.
    """
    prev = left[-1] if left else ""
    prev2 = left[-2] if len(left) > 1 else ""
    nxt = right[0] if right else ""
    if nxt in _NEXT_VERB:
        return "noun"  # "bites are", "bites can" — the word is the subject
    if prev in _DETS:
        return "noun"  # "a bite", "the bites"
    if prev in _MODS and prev2 in _DETS:
        return "noun"  # "a huge bite"
    if nxt == "of" and prev not in _PRONOUNS and prev not in _AUX and prev not in _CLITIC:
        return "noun"  # "bite of his steak"
    if prev in _PRONOUNS:
        return "verb"  # "she bites"
    if prev in _CLITIC and prev2 in _PRONOUNS:
        return "verb"  # "he'd bite" tokenised as he + d
    if prev == "not" and (prev2 in _AUX or prev2 in _PRONOUNS or prev2 in _CLITIC):
        return "verb"  # "did not bite"
    if prev in _AUX or prev == "to":
        return "verb"  # "gonna bite", "to bite", "would bite". Copula be is not in _AUX.
    if _noun_subject_verb(left, right, form):
        return "verb"  # "the dog bites the man"
    return ""


def _noun_subject_verb(left, right, form):
    """Determiner + noun subject + this -s form + an object. "The door handles broke" is not forced."""
    f = (form or "").lower()
    if len(f) <= 3 or not f.endswith("s") or f.endswith("ss"):
        return False
    nxt = right[0] if right else ""
    if nxt not in _OBJECTS:
        return False
    prev = left[-1] if left else ""
    if not prev or prev in _DETS or prev in _MODS or prev in _AUX or prev in _COPULA or prev in _PRONOUNS or prev in _CLITIC:
        return False
    i = len(left) - 2
    while i >= 0 and left[i] in _MODS:
        i -= 1
    return i >= 0 and left[i] in _DETS


# A compound is glued by one of these and nothing else. A space on either side is a separate word.
_HYPHEN = {"-", "\u2010", "\u2011", "\u2013"}
# Immediate neighbors that do not make a collocation. Particles such as "back" are kept: they do.
_NEIGHBOR_STOP = _DETS | _PRONOUNS | _COPULA | _AUX | _CLITIC | {
    "and", "or", "but", "if", "as", "so", "not", "of", "nor", "than", "then",
    "at", "from", "by", "into", "onto", "over", "away", "through", "around", "about",
    "for", "with", "in", "to",
}


def construction(right, family, left=None, before="", after=""):
    """How this use is built, when that changes the meaning. '' is the bare use.

    A hyphen joins this word to its neighbor ("first-place" is not "place"). The frame names
    that neighbor. A verb particle does ("bite on" is not "bite the apple"). After a noun, only
    "to" + a verb does ("a bite to eat" is not "a bite of food"). "sweat on his face" stays bare.
    """
    left = left or []
    glued = []
    if before in _HYPHEN and left:
        glued.append(left[-1] + "-")
    if after in _HYPHEN and right:
        glued.append("-" + right[0])
    if glued:
        return "".join(glued)
    nxt = right[0] if right else ""
    nxt2 = right[1] if len(right) > 1 else ""
    if family == "verb" and nxt in _PARTICLE:
        return nxt
    if family == "noun" and nxt == "to" and nxt2 and nxt2 not in _DETS and nxt2 not in _AUX and nxt2 not in _COPULA:
        return "to"
    return ""


def use_frame(use, fam):
    if not use:
        return ""
    return construction(use.get("right") or [], fam, use.get("left") or [], use.get("before") or "", use.get("after") or "")


def _nearest_content(side):
    """Nearest content word, skipping one determiner, pronoun, auxiliary, conjunction, or preposition.

    A particle such as back, on, up, or down is content. "of applause" yields applause.
    Two function words in a row stop the search.
    """
    if not side:
        return ""
    if side[0] not in _NEIGHBOR_STOP:
        return side[0]
    if len(side) > 1 and side[1] not in _NEIGHBOR_STOP:
        return side[1]
    return ""


def content_neighbors(left, right):
    """Content word on each side of this use. Either side may be absent."""
    prev = _nearest_content(list(reversed(left)))
    nxt = _nearest_content(list(right))
    return [tok for tok in (prev, nxt) if tok]


def _place_id(place):
    return (place["chapter"], place["form"], place["occurrence"])


def same_neighbor_uses(bound_uses, uses, taken):
    """Uses that share a content neighbor with a bound sense and are not already anchored.

    `taken` holds (chapter, form, occurrence). A bound sense on one form does not stay there
    while another form beside the same word opens a different sense.
    """
    keys = set()
    for place in bound_uses:
        keys.update(content_neighbors(place.get("left") or [], place.get("right") or []))
    if not keys:
        return []
    out = []
    for place in uses:
        if _place_id(place) in taken:
            continue
        if keys.intersection(content_neighbors(place.get("left") or [], place.get("right") or [])):
            out.append(place)
    return out


def select_openings(attested_uses, bound_uses, uses, taken, limit=8):
    """Samples for the review. Not a build failure.

    Up to four rare neighboring content words the general sense's own sentences do not use,
    then up to four other forms of a word that already has a bound sense. The rest are not listed.
    """
    known = set()
    attested_ids = set()
    for place in attested_uses:
        attested_ids.add(_place_id(place))
        known.update(content_neighbors(place.get("left") or [], place.get("right") or []))
    bound_forms = {place.get("form") for place in bound_uses if place.get("form")}
    novel_counts = {}
    novel, forms = {}, {}
    for place in uses:
        pid = _place_id(place)
        if pid in taken or pid in attested_ids:
            continue
        fresh = [tok for tok in content_neighbors(place.get("left") or [], place.get("right") or []) if tok not in known]
        for tok in fresh:
            novel_counts[tok] = novel_counts.get(tok, 0) + 1
            novel.setdefault(tok, place)
        if bound_forms and place.get("form") not in bound_forms:
            forms.setdefault(place.get("form"), place)
    novel_picks = [novel[tok] for tok in sorted(novel, key=lambda tok: (novel_counts[tok], tok))][:4]
    form_picks = [forms[form] for form in sorted(forms)][:4]
    out, seen = [], set()
    for place in novel_picks + form_picks:
        pid = _place_id(place)
        if pid in seen:
            continue
        seen.add(pid)
        out.append(place)
        if len(out) >= limit:
            break
    return out


def pick_default(rows):
    """Index of the general sense to show wherever no other sense is pinned.

    Prefer the sense that can open on the most book uses (its part of speech and its construction),
    then the sense pinned to the most places. The number of times the model wrote the block is not a vote.
    `rows` items are {cover, located, base}.
    """
    return min(range(len(rows)), key=lambda i: (
        -rows[i]["cover"],
        -rows[i]["located"],
        0 if rows[i]["base"] else 1,
        i,
    ))


def classify_use(key, role, frame, family, attested, taken):
    """Where one book use goes, given the general sense's part of speech and the constructions it attested.

    `attested` is None when none of that sense's sentences could be located: do not invent a meaning gap.
    """
    if key in taken:
        return "taken"
    if role and role != family:
        return "pos"
    if attested is not None and frame not in attested:
        return "meaning"
    return "same"


PROSE_WORDS = 40
COVERED_RE = re.compile(r"<!--\s*covered:\s*(\d+)\s*-->")


def covered_marks(path):
    return {int(n) for n in COVERED_RE.findall(open(path, encoding="utf-8").read())}


def missing_chapters(chapter_list, covered, marks):
    """Prose chapters the support file never tied to the book and did not mark covered."""
    missing = []
    for ch in chapter_list or []:
        if ch.get("words", 0) < PROSE_WORDS:
            continue
        n = ch["index"]
        if n in covered or n in marks:
            continue
        missing.append(ch)
    return missing


def glossary_keys(glossary):
    keys = set(glossary)
    for entry in glossary.values():
        keys.update(entry.get("forms") or [])
        for sense in entry.get("senses") or []:
            keys.update(sense.get("forms") or [])
    return keys


def missing_hard_words(hard_words, keys, skip_chapters):
    """Lemmas outside the common-word list, in a chapter that was otherwise processed, with no entry."""
    return [h for h in hard_words or [] if h["lemma"] not in keys and h["chapter"] not in skip_chapters]


def parse_support(path):
    entries, cur = [], None
    for line in open(path, encoding="utf-8"):
        s = line.strip()
        if not s or s.startswith("# ") and not s.startswith("### "):
            continue
        mh = HEADER_RE.match(s)
        if mh:
            if cur:
                entries.append(cur)
            h = mh.group(1)
            ma = APPEARS_RE.match(h)
            term = ma.group(1).strip() if ma else h.strip()
            cur = {"term": term, "pos": "", "why_hard": "", "examples": [], "meaning": "", "sentence": ""}
            continue
        mf = FIELD_RE.match(s)
        if mf and cur is not None:
            k, v = mf.group(1), mf.group(2)
            if k == "POS":
                cur["pos"] = v
            elif k == "Why it is hard":
                cur["why_hard"] = v[:400]
            elif k == "Example sentences":
                cur["examples"] = [x.strip() for x in re.split(r"(?<=[.!?])\s+", v) if x.strip()]
            elif k == "Meaning":
                cur["meaning"] = v[:600]
            elif k == "Sentence":
                cur["sentence"] = v.strip().strip("\"“”").strip()
    if cur:
        entries.append(cur)
    return [e for e in entries if e["term"] and e["meaning"]]


# ----------------------------------------------------------------------------- the Reader (node helper)
class Reader:
    def __init__(self, node, repo, epub):
        self.node, self.repo, self.epub = node, repo, epub
        self.helper = os.path.join(HERE, "epub-places.mjs")
        self.book = None

    def ask(self, request):
        with tempfile.TemporaryDirectory() as tmp:
            req, res = os.path.join(tmp, "req.json"), os.path.join(tmp, "res.json")
            json.dump(dict(request, coverage=True), open(req, "w", encoding="utf-8"))
            p = subprocess.run(
                [self.node, self.helper, "--repo", self.repo, "--epub", self.epub, "--request", req, "--out", res],
                capture_output=True, text=True,
            )
            if p.returncode != 0:
                sys.exit(f"epub-places.mjs failed (exit {p.returncode}):\n{p.stderr or p.stdout}")
            out = json.load(open(res, encoding="utf-8"))
        self.book = out["book"]
        return out


# ----------------------------------------------------------------------------- where may a meaning be shown?
# v3.3. A meaning written for one sentence must not be shown at other places where the word means something else.
#   general block : "rare word" / "background needed" / proper noun, on a word that is not on the Reader's easy list,
#                   with a meaning that does not talk about the story -> may be shown at every use of its spelling.
#   bound block   : "unusual meaning here", "figurative", "logical connector", "different grammar role", dialect ...,
#                   or any block of an easy word (out, that, see, have) -> shown ONLY at its own located Sentence.
#   A general block whose meaning ALSO talks about the story (a name, "here", a quote, a second sentence about the
#   scene) is split: its first clean sentence is the general meaning, the full text is a bound sense at that place.
BOUND_WHY = re.compile(r"unusual|not the usual|figurative|grammar|dialect|idiom|slang|different (?:meaning|role|part|use)", re.I)
SENT_SPLIT = re.compile(r"(?<=[.!?])[\"”’)]*\s+(?=[\"“(]?[A-Z])")
NOT_NAMES = {"I", "English", "OK"}


def sentences_of(text):
    return [x.strip() for x in SENT_SPLIT.split((text or "").strip()) if x.strip()]


def story_signal(sentence):
    """Does this sentence of a meaning talk about one place in the story (a name, 'here', a quote)?"""
    if re.search(r"\bhere\b|\bin this (?:story|book|text|sentence|passage|part|line|chapter)\b", sentence, re.I):
        return True
    words = re.findall(r"[A-Za-z][A-Za-z'’]*", re.sub(r"[\"“][^\"”]*[\"”]", " ", sentence))  # a quoted gloss is not a name
    for i, w in enumerate(words):
        if i > 0 and w[0].isupper() and w.rstrip("'’s") not in NOT_NAMES and w not in NOT_NAMES:
            return True
        if i == 0 and re.match(r"^[A-Z][a-z]+['’]s$", w):
            return True
    return False


def classify(block, easy):
    """-> ('general', None) | ('bound', reason) | ('split', general_meaning)"""
    why = block.get("why_hard", "")
    if block.get("force_general"):
        return "general", None
    if easy:
        return "bound", "easy word: only hard where it was listed"
    if BOUND_WHY.search(why):
        return "bound", f"why-hard: {why[:40]}"
    if norm_pos(block.get("pos")) in ("proper noun", "abbreviation") or re.search(r"proper noun|nickname|abbreviation|\bname\b|background", why, re.I):
        return "general", None  # a name means the same person or place all through the book
    sents = sentences_of(block["meaning"])
    if not sents:
        return "bound", "empty meaning"
    if len(sents) == 1 and not story_signal(sents[0]):
        return "general", None
    clean = []
    for x in sents:
        if story_signal(x):
            break
        clean.append(x)
        break  # the first sentence is the general meaning; later ones were written about the scene
    if not clean:
        return "bound", "meaning is about the story"
    return "split", " ".join(clean)


# ----------------------------------------------------------------------------- senses
class Sense:
    def __init__(self, block):
        self.blocks = [block]
        self.surfaces = [block["surface"]]

    def add(self, block):
        self.blocks.append(block)
        if block["surface"] not in self.surfaces:
            self.surfaces.append(block["surface"])

    @property
    def first(self):
        return self.blocks[0]


def same_sense(block, sense, a, strict=False):
    pos = norm_pos(block["pos"])
    best = 0.0
    for m in sense.blocks:
        if norm_pos(m["pos"]) != pos:
            continue
        ov = overlap(block["meaning"], m["meaning"])
        limit = a.merge_overlap if (strict or m["surface"] != block["surface"]) else a.same_spelling_overlap
        if ov >= limit:
            return True, ov
        best = max(best, ov)
    return False, best


def group_senses(blocks, a, log, strict=False):
    """Blocks with the same POS and (nearly) the same meaning are one sense. Every block keeps its own Sentence,
    so merging never loses a place: a bound sense is anchored at the Sentence of EVERY block merged into it."""
    senses = []
    for b in blocks:
        for s in senses:
            ok, ov = same_sense(b, s, a, strict)
            if ok:
                s.add(b)
                if b["surface"] != s.first["surface"]:
                    log.append(f"merged '{b['surface']}' into '{s.first['surface']}' (same meaning, overlap {ov:.2f})")
                break
        else:
            senses.append(Sense(b))
    return senses


def place_key(anchor):
    return (anchor["chapter"], anchor["form"], anchor["occurrence"])


def clean_anchor(a):
    return {"chapter": a["chapter"], "occurrence": a["occurrence"], "form": a["form"], "context": a["context"]}


def build_entries(groups, reader, a, stats, warnings, decisions, gaps):
    """groups: {lemma: [block, ...]} -> {key: entry}. Meaning comes from the blocks; every place from the Reader."""
    plans = {}
    for lemma, blocks in groups.items():
        easy = bool(_LEMMA.get(lemma, {}).get("easy"))
        gen, bound, log = [], [], []
        for b in blocks:
            kind, extra = classify(b, easy)
            if kind == "general":
                gen.append(b)
            elif kind == "bound":
                bound.append(dict(b, reason=extra))
            else:  # split: general first sentence everywhere, the full scene text only at its own Sentence
                gen.append(dict(b, meaning=extra, split_from=b["meaning"]))
                bound.append(dict(b, reason="meaning also describes the scene"))
        gsenses = group_senses(gen, a, log)
        bsenses = group_senses(bound, a, log, strict=True)
        plans[lemma] = [gsenses, bsenses, log]

    def sid(lemma, b):
        return f"s:{lemma}:{b['surface']}:{b['order']}"

    sent_t, use_lemmas = [], []
    for lemma, (gs, bs, _) in plans.items():
        surfaces = sorted({b["surface"] for b in groups[lemma]})
        for s in gs + bs:
            for b in s.blocks:
                if b.get("sentence"):
                    sent_t.append({"id": sid(lemma, b), "form": b["surface"], "sentence": b["sentence"], "avoid": surfaces})
        if gs:
            use_lemmas.append(lemma)
    placed = reader.ask({"sentences": sent_t, "uses": use_lemmas}) if (sent_t or use_lemmas) else {"all": {}, "sentences": {}, "uses": {}, "warnings": []}
    warnings.extend(f"reader: {w}" for w in placed.get("warnings", []))
    hit = set()
    for row in placed.get("sentences", {}).values():
        if row.get("status") == "ok":
            for an in row.get("anchors") or []:
                hit.add(an["chapter"])

    use_at = {}
    for lemma in use_lemmas:
        for p in placed.get("uses", {}).get(lemma, []):
            use_at[(lemma, p["chapter"], p["form"], p["occurrence"])] = p

    def sense_place(lemma, sense):
        """Located places of this sense's own sentences, and the constructions those places use."""
        frames, places = set(), []
        for b in sense.blocks:
            row = placed.get("sentences", {}).get(sid(lemma, b))
            if not row or row.get("status") != "ok":
                continue
            for an in row.get("anchors") or []:
                places.append(an)
                use = use_at.get((lemma, an["chapter"], an["form"], an["occurrence"]))
                fam = pos_family(b["pos"])
                frames.add(use_frame(use, fam))
        return frames, places

    for lemma, (gs, bs, log) in plans.items():
        if len(gs) < 2:
            continue
        uses = placed.get("uses", {}).get(lemma, [])
        rows = []
        for s in gs:
            fam = pos_family(s.first["pos"])
            frames, places = sense_place(lemma, s)
            cover = 0
            if places:
                for p in uses:
                    role = grammar_role(p.get("left") or [], p.get("right") or [], p.get("form") or "")
                    if fam and role and role != fam:
                        continue
                    if use_frame(p, fam) in frames:
                        cover += 1
            rows.append({
                "cover": cover,
                "located": len({place_key(x) for x in places}),
                "base": lemma in s.surfaces,
            })
        gs.insert(0, gs.pop(pick_default(rows)))
        plans[lemma] = [gs, bs, log]

    all_t = {}
    for lemma, (gs, _bs, _) in plans.items():
        if len(gs) < 2:
            continue
        g_users = {}
        for s in gs:
            for sf in s.surfaces:
                g_users.setdefault(sf, []).append(s)
        default_sf = set(gs[0].surfaces)
        for s in gs[1:]:
            for sf in s.surfaces:
                if len(g_users[sf]) == 1 and sf not in default_sf:
                    all_t[f"all:{sf}"] = {"id": f"all:{sf}", "form": sf, "avoid": sorted(default_sf | {x for x, w in g_users.items() if len(w) > 1})}
    if all_t:
        extra = reader.ask({"all": list(all_t.values())})
        placed["all"] = extra.get("all", {})
        warnings.extend(f"reader: {w}" for w in extra.get("warnings", []))
    else:
        placed.setdefault("all", {})

    def located(lemma, key, s, unique_ok):
        anchors = []
        for sf in s.surfaces:
            r = placed["all"].get(f"all:{sf}") if unique_ok else None
            if r:
                anchors += r["anchors"]
                if r["skipped"]:
                    warnings.append(f"{key}: {r['skipped']} use(s) of '{sf}' sit in text the Reader cannot line up; not anchored")
                continue
            for b in s.blocks:
                if b["surface"] != sf:
                    continue
                if not b.get("sentence"):
                    warnings.append(f"{key}: a block for '{sf}' has no '- Sentence:'; that meaning is not anchored")
                    continue
                r = placed["sentences"].get(sid(lemma, b), {"status": "not_found", "anchors": [], "note": ""})
                if r["status"] != "ok":
                    warnings.append(f"{key}: sentence for '{sf}' not located ({r['status']}: {r.get('note', '')}); no anchor written")
                    continue
                anchors += r["anchors"]
        seen = {}
        for an in anchors:
            seen.setdefault(place_key(an), an)
        return sorted(seen.values(), key=lambda x: (x["chapter"], x["occurrence"]))

    out = {}
    for lemma, blocks in groups.items():
        gs, bs, log = plans[lemma]
        surfaces = dedupe([b["surface"] for b in blocks])
        if lemma in surfaces or (_LEMMA.get(lemma, {}).get("attested") and not _LEMMA.get(lemma, {}).get("easy")):
            key = lemma
        else:
            key = surfaces[0]
        decision = {"key": key, "lemma": lemma, "merged": log, "senses": []}
        decisions.append(decision)
        # bound senses first: their places are exact and win over an "every use of this spelling" anchor
        cand, taken = [], set()
        for s in bs:
            anchors = [x for x in located(lemma, key, s, False) if place_key(x) not in taken]
            taken |= {place_key(x) for x in anchors}
            cand.append((s, anchors, "bound"))
        for s in gs[1:]:
            anchors = [x for x in located(lemma, key, s, True) if place_key(x) not in taken]
            taken |= {place_key(x) for x in anchors}
            cand.append((s, anchors, "general, other meaning"))
        kept = []
        for s, anchors, role in cand:
            if not anchors:
                warnings.append(f"{key}: meaning '{s.first['meaning'][:50]}...' could not be located in the book; it is not shown anywhere")
                decision["senses"].append({"surfaces": s.surfaces, "role": f"dropped ({role})", "anchors": 0})
                continue
            if len(anchors) > MAX_ANCHORS:
                warnings.append(f"{key}: {len(anchors) - MAX_ANCHORS} place(s) over the {MAX_ANCHORS}-anchor limit are not anchored")
                anchors = anchors[:MAX_ANCHORS]
            kept.append((s, anchors, role))
        limit = MAX_SENSES - (1 if gs else 0)
        if len(kept) > limit:
            warnings.append(f"{key}: more than {MAX_SENSES} senses; {len(kept) - limit} dropped")
            kept = kept[:limit]
        # A general meaning opens only on uses of its part of speech and its construction.
        # A hyphen join is a different construction. A bound sense's content neighbor does not
        # stay open on another sense. "she bites" is not "a mouthful". "a bite to eat" is not "a bite of food".
        restricted = None
        uses = placed.get("uses", {}).get(lemma, [])
        if gs and uses:
            fam = pos_family(gs[0].first["pos"])
            frames, pinned = sense_place(lemma, gs[0])
            attested = frames if pinned else None
            covered = {place_key(x) for _, anchors, _ in kept for x in anchors}

            def full_places(sense):
                found = []
                for an in sense_place(lemma, sense)[1]:
                    use = use_at.get((lemma, an["chapter"], an["form"], an["occurrence"]))
                    if use:
                        found.append(use)
                return found

            bound_uses = []
            for sense in bs:
                bound_uses.extend(full_places(sense))
            attested_uses = full_places(gs[0])
            same, pos_gap, meaning_gap = [], [], []
            if fam in ("noun", "verb"):
                for p in uses:
                    pk = (p["chapter"], p["form"], p["occurrence"])
                    role = grammar_role(p.get("left") or [], p.get("right") or [], p.get("form") or "")
                    kind = classify_use(pk, role, use_frame(p, fam), fam, attested, covered)
                    if kind == "pos":
                        pos_gap.append(p)
                    elif kind == "meaning":
                        meaning_gap.append(p)
                    elif kind == "same":
                        same.append(p)
            else:
                for p in uses:
                    pk = (p["chapter"], p["form"], p["occurrence"])
                    if pk in covered:
                        continue
                    frame = use_frame(p, fam)
                    if attested is not None and "-" in frame and frame not in attested:
                        meaning_gap.append(p)
                    else:
                        same.append(p)
            neighbor_gaps = same_neighbor_uses(bound_uses, same, set())
            if neighbor_gaps:
                skip = {_place_id(p) for p in neighbor_gaps}
                same = [p for p in same if _place_id(p) not in skip]
                meaning_gap.extend(neighbor_gaps)
            for p in select_openings(attested_uses, bound_uses, same, set()):
                neigh = ", ".join(content_neighbors(p.get("left") or [], p.get("right") or [])) or "none"
                warnings.append(f"OTHER OPENING {key}: chapter {p['chapter']} {p['form']!r} next to {neigh}: {p['context']}")
            if (fam in ("noun", "verb") and (pos_gap or meaning_gap)) or meaning_gap:
                restricted = same[:MAX_ANCHORS]
                if len(same) > MAX_ANCHORS:
                    warnings.append(f"{key}: {len(same) - MAX_ANCHORS} matching place(s) over the {MAX_ANCHORS}-anchor limit are not anchored")

                def gap_note(label, places, text):
                    samples = "; ".join(f"chapter {p['chapter']} {p['form']!r}: {p['context']}" for p in places[:8])
                    warnings.append(f"{label} {key}: {text} {samples}")
                    gaps.append({"key": key, "kind": "pos" if label == "POS GAP" else "meaning", "family": fam, "places": [
                        {"chapter": p["chapter"], "form": p["form"], "occurrence": p["occurrence"], "context": p["context"]} for p in places
                    ]})

                if pos_gap:
                    other = "noun" if fam == "verb" else "verb"
                    gap_note("POS GAP", pos_gap, f"the {fam} meaning is not shown at {len(pos_gap)} {other} use(s). Add a block for each.")
                    decision["posGap"] = len(pos_gap)
                if meaning_gap:
                    shown = fam or "word"
                    gap_note("MEANING GAP", meaning_gap, f"the {shown} meaning is not shown at {len(meaning_gap)} use(s) with a different construction or the same content neighbor as a bound sense. Add a block for each.")
                    decision["meaningGap"] = len(meaning_gap)
        if gs and not kept and restricted is None:
            out[key] = make_entry(key, gs[0], [sf for sf in surfaces if sf != key])
            stats["single"] += 1
            decision["senses"].insert(0, {"surfaces": gs[0].surfaces, "role": "only (shown at every use)", "anchors": 0})
            continue
        if not gs and not kept:
            stats["dropped"] += 1
            decision["role"] = "dropped: no meaning could be tied to a place in the book"
            continue
        if gs and restricted is not None:
            entry = make_entry(key, gs[0], [sf for sf in surfaces if sf != key])
            entry["senseOnly"] = True
            entry["senses"] = []
            if restricted:
                entry["senses"].append(make_sense(gs[0], default=True, anchors=[clean_anchor(x) for x in restricted]))
                stats["anchors"] += len(restricted)
            decision["senses"].insert(0, {"surfaces": gs[0].surfaces, "role": "shown only where the part of speech and the construction match", "anchors": len(restricted)})
            stats["sense_only"] += 1
            if not restricted and not kept:
                stats["dropped"] += 1
                decision["role"] = "dropped: the meaning's part of speech never occurs in the book"
                continue
        elif gs:
            entry = make_entry(key, gs[0], [sf for sf in surfaces if sf != key])
            entry["senses"] = [make_sense(gs[0], default=True)]
            decision["senses"].insert(0, {"surfaces": gs[0].surfaces, "role": "default (shown where no anchor applies)", "anchors": 0})
            stats["multi"] += 1
        else:
            first = kept[0][0]
            entry = make_entry(key, first, [sf for sf in surfaces if sf != key])
            entry["senseOnly"] = True
            entry["senses"] = []
            stats["sense_only"] += 1
        for s, anchors, role in kept:
            entry["senses"].append(make_sense(s, anchors=[clean_anchor(x) for x in anchors]))
            stats["anchors"] += len(anchors)
            decision["senses"].append({"surfaces": s.surfaces, "role": role, "anchors": len(anchors)})
        out[key] = entry
    return out, hit


def dedupe(items):
    seen, out = set(), []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


_LEMMA = {}


def pos_label(p):
    return POS_WORD_MAP.get((p or "").strip().lower(), (p or "").strip() or "other")


def make_entry(key, sense, forms):
    b = sense.first
    e = {"pos": pos_label(b["pos"]), "meaning": b["meaning"], "whyHard": b.get("why_hard", "")}
    if not e["whyHard"]:
        e.pop("whyHard")
    forms = dedupe([f for f in forms if f != key])
    if forms:
        e["forms"] = forms
    return e


def make_sense(sense, default=False, anchors=None):
    b = sense.first
    s = {"pos": pos_label(b["pos"]), "meaning": b["meaning"]}
    if b.get("why_hard"):
        s["whyHard"] = b["why_hard"]
    if default:
        s["default"] = True
    if anchors is not None:
        s["anchors"] = anchors
        if not default:
            s["forms"] = list(sense.surfaces)
    elif not default:
        s["forms"] = list(sense.surfaces)
        s["anchors"] = []
    return s


# ----------------------------------------------------------------------------- repair mode (v3.3)
def cue_words(text, own):
    words = re.findall(r"[a-z]+", (text or "").lower())
    return sorted({w for w in words if len(w) >= 3 and w not in STOP and stem(w) not in own and w not in own})


def repair_glossary(flat, reader, a, stats, warnings, decisions, gaps):
    """Old files never recorded which sentence a meaning was written for. Each entry whose meaning is bound to one
    place (classify) is tied back to that place by matching the meaning's own words against the sentence and
    paragraph of every use of the word (epub-places.mjs "infer"). Accepted only when one place clearly wins."""
    words = flat["glossary"]
    entries_req = {}
    for k, e in words.items():
        fs = list(e.get("forms", []))
        for s in e.get("senses", []) or []:
            fs += s.get("forms", [])
        entries_req[k] = dedupe(fs)
    res = reader.ask({"lemmas": list(words)})
    plan, infer = {}, []
    for k, e in words.items():
        easy = bool(res["lemmas"][k]["easy"])
        senses = e.get("senses") or []
        if senses:
            di = next((i for i, s in enumerate(senses) if s.get("default")), None)
            if di is None:
                continue
            src = senses[di]
            block = {"surface": k, "pos": src.get("pos", e.get("pos", "")), "meaning": src.get("meaning", ""), "why_hard": src.get("whyHard", e.get("whyHard", ""))}
        else:
            di, block = None, {"surface": k, "pos": e.get("pos", ""), "meaning": e.get("meaning", ""), "why_hard": e.get("whyHard", "")}
        kind, extra = classify(block, easy)
        if kind == "general":
            continue
        own = {k, stem(k)} | set(entries_req[k]) | {stem(f) for f in entries_req[k]}
        scene = block["meaning"] if kind == "bound" else " ".join(sentences_of(block["meaning"])[1:]) or block["meaning"]
        quoted = " ".join(re.findall(r"[\"“‘']([^\"”’']{3,})[\"”’']", block["why_hard"]))
        skip = [[x["chapter"], x.get("form", k), x["occurrence"]] for s in senses for x in s.get("anchors", []) if "occurrence" in x]
        plan[k] = {"kind": kind, "general": extra if kind == "split" else None, "reason": extra if kind == "bound" else "meaning also describes the scene",
                   "di": di, "block": block, "easy": easy}
        quotes = [q for q in re.findall(r"[\"“‘']([^\"”’‘“]{3,80}?)[\"”’']", block["meaning"] + " " + block["why_hard"]) if " " in q.strip() and own & set(re.findall(r"[a-z']+", q.lower()))]
        infer.append({"id": k, "key": k, "cues": cue_words(scene + " " + quoted, own), "quotes": quotes, "skip": skip})
    ans = reader.ask({"entries": entries_req, "infer": infer})["infer"] if infer else {}
    # contexts of anchors kept in an entry that becomes senseOnly are re-cut clear of every other use of the word
    out, recut = {}, []
    for k, e in words.items():
        if k not in plan:
            out[k] = e
            stats["kept"] += 1
            continue
        p, r = plan[k], ans.get(k, {})
        b = r.get("best")
        ok = bool(b) and b["score"] >= a.infer_min and b["score"] >= a.infer_ratio * r.get("second", 0) and b["anchors"]
        d = {"key": k, "was": "senses" if p["di"] is not None else "flat", "kind": p["kind"], "reason": p["reason"],
             "uses": r.get("uses", 0), "score": round(b["score"], 2) if b else 0, "second": round(r.get("second", 0), 2),
             "cues": b["cues"] if b else [], "best_at": [b["chapter"], b["anchors"][0]["context"] if b["anchors"] else ""] if b else None, "second_at": r.get("secondAt"), "placed": [[x["chapter"], x["occurrence"], x["context"]] for x in b["anchors"]] if ok else []}
        decisions.append(d)
        blk = p["block"]
        new_sense = None
        if ok:
            new_sense = {"pos": blk["pos"] or e.get("pos", "other"), "meaning": blk["meaning"]}
            if blk["why_hard"]:
                new_sense["whyHard"] = blk["why_hard"]
            new_sense["anchors"] = [clean_anchor(x) for x in b["anchors"]][:MAX_ANCHORS]
            stats["anchors"] += len(new_sense["anchors"])
        senses = [dict(s) for s in (e.get("senses") or [])]
        if p["di"] is not None:
            senses.pop(p["di"])
        ne = {kk: vv for kk, vv in e.items() if kk not in ("senses", "senseOnly")}
        if p["kind"] == "split":
            # general first sentence stays the default everywhere; the scene text opens only where it was written
            ne["meaning"] = p["general"]
            base = {"pos": blk["pos"] or e.get("pos", "other"), "meaning": p["general"], "default": True}
            if blk["why_hard"]:
                base["whyHard"] = blk["why_hard"]
            rest = senses + ([new_sense] if new_sense else [])
            if rest:
                ne["senses"] = [base] + rest
                stats["multi"] += 1
            else:
                stats["trimmed"] += 1
            d["result"] = "general first sentence everywhere" + (" + scene meaning anchored" if new_sense else " (scene text removed: place not found)")
            out[k] = ne
            continue
        # bound: shown only where it was written -> senseOnly
        rest = ([new_sense] if new_sense else []) + senses
        if not rest:
            stats["dropped"] += 1
            d["result"] = "dropped: place not found, and this meaning must not be shown at other places"
            continue
        ne["senseOnly"] = True
        ne["senses"] = rest
        ne["meaning"], ne["pos"] = rest[0]["meaning"], rest[0].get("pos", ne.get("pos", "other"))
        if rest[0].get("whyHard"):
            ne["whyHard"] = rest[0]["whyHard"]
        for si, s in enumerate(rest):
            if s is new_sense:
                continue
            for ai, x in enumerate(s.get("anchors", [])):
                if "occurrence" in x:
                    recut.append({"id": f"{k}|{si}|{ai}", "key": k, "chapter": x["chapter"], "occurrence": x["occurrence"], "form": x.get("form", k)})
        stats["sense_only"] += 1
        d["result"] = "senseOnly: shown only at its anchor(s)" if new_sense else "senseOnly: old default meaning removed (place not found); other anchored meanings kept"
        out[k] = ne
    if recut:
        got = reader.ask({"entries": entries_req, "places": recut})["places"]
        for t in recut:
            k, si, ai = t["id"].split("|")
            an = got.get(t["id"])
            if an:
                out[k]["senses"][int(si)]["anchors"][int(ai)]["context"] = an["context"]
    # flat entries that the Reader looks up under one key (sweat / sweats): one entry, the other spelling anchored
    lem = {k: res["lemmas"][k]["lemma"] for k in out if k in res["lemmas"]}
    for k, v in res["lemmas"].items():
        _LEMMA[v["lemma"]] = {"attested": v["attested"], "easy": v["easy"]}
    by = {}
    for k, e in out.items():
        if k in lem and not e.get("senses"):
            by.setdefault(lem[k], []).append(k)
    groups, order = {}, 0
    for lm, ks in by.items():
        if len(ks) < 2 or (lm in out and out[lm].get("senses") and lm not in ks):
            continue
        groups[lm] = []
        for k in sorted(ks, key=lambda k: (k != lm, k)):
            e = out[k]
            order += 1
            groups[lm].append({"surface": k, "pos": e.get("pos", ""), "meaning": e.get("meaning", ""), "why_hard": e.get("whyHard", ""),
                               "sentence": "", "order": order, "force_general": True})
    if groups:
        sub = []
        changed, _hit = build_entries(groups, reader, a, stats, warnings, sub, gaps)
        decisions.extend(dict(d, result="colliding spellings joined into one entry") for d in sub)
        for lm, bl in groups.items():
            for b in bl:
                out.pop(b["surface"], None)
        out.update(changed)
    return out


# ----------------------------------------------------------------------------- modes
def blocks_from_support(path, dropped, phrases):
    blocks = []
    for order, e in enumerate(parse_support(path)):
        kind, key = normalize(e["term"])
        if kind is None:
            dropped.append((e["term"], key))
            continue
        if kind == "phrase":
            if key in phrases:
                continue
            phrases[key] = {"pos": "phrase", "meaning": e["meaning"]}
            continue
        blocks.append({"surface": key, "pos": e["pos"], "meaning": e["meaning"], "why_hard": e["why_hard"],
                       "sentence": e["sentence"], "order": order})
    return blocks


def run_validator(a, out_path):
    script = os.path.join(a.repo, "scripts", "validate-glossary.mjs")
    cmd = [a.node, script, a.epub, out_path] + ([] if a.show_warnings else ["--quiet"])
    p = subprocess.run(cmd, capture_output=True, text=True, cwd=a.repo)
    print(f"\n$ node scripts/validate-glossary.mjs <book.epub> {os.path.basename(out_path)}" + ("" if a.show_warnings else " --quiet"))
    print((p.stdout + p.stderr).rstrip())
    print(f"validator exit code: {p.returncode}")
    return p.returncode


def run_lookup_check(a, out_path):
    script = os.path.join(HERE, "check-lookup.mjs")
    p = subprocess.run([a.node, script, "--repo", a.repo, "--epub", a.epub, "--glossary", out_path], capture_output=True, text=True)
    print("\n$ node scripts/check-lookup.mjs  (the Reader's own tap path, every use of every multi-sense spelling)")
    print((p.stdout + p.stderr).rstrip())
    return p.returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--support", help="merged support markdown (### blocks)")
    src.add_argument("--from-flat", help="existing flat glossary JSON to upgrade (migration mode)")
    ap.add_argument("--epub", required=True, help="the book EPUB")
    ap.add_argument("--repo", default=os.environ.get("MARGIN_WORDS_REPO"), help="margin-words repo folder (or env MARGIN_WORDS_REPO)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title")
    ap.add_argument("--author")
    ap.add_argument("--chapters", type=int, help="default: counted from the EPUB by the Reader")
    ap.add_argument("--sha256", help="default: sha256 of the EPUB")
    ap.add_argument("--node", default=os.environ.get("NODE", "node"), help="node binary (20 or newer)")
    ap.add_argument("--report", help="write the decisions (merged / default / anchored / dropped) as JSON")
    ap.add_argument("--merge-overlap", type=float, default=0.75, help="two different spellings (sweat/sweats) with the same POS and at least this meaning overlap are ONE sense")
    ap.add_argument("--same-spelling-overlap", type=float, default=0.34, help="the same spelling and POS with at least this overlap is one sense (lower = a new sense)")
    ap.add_argument("--infer-min", type=float, default=8.0, help="repair mode: least cue score for tying an old meaning to a place")
    ap.add_argument("--infer-ratio", type=float, default=1.5, help="repair mode: the best place must beat the next place by this factor")
    ap.add_argument("--no-validate", action="store_true", help="skip the repo validator (not for publishing)")
    ap.add_argument("--allow-pos-gap", action="store_true", help="do not refuse a noun/verb mismatch (not for publishing)")
    ap.add_argument("--allow-gaps", action="store_true", help="do not refuse any coverage gap (not for publishing)")
    ap.add_argument("--passage", action="store_true", help="this support file is one passage, not the whole book: skip the chapter and hard-word gates")
    ap.add_argument("--show-warnings", action="store_true", help="show the validator's warnings too")
    a = ap.parse_args()
    if not a.repo or not os.path.isfile(os.path.join(a.repo, "scripts", "validate-glossary.mjs")):
        sys.exit("--repo must be the margin-words repo folder (the one with scripts/validate-glossary.mjs). Run `npm install` there once.")
    a.repo = os.path.abspath(a.repo)
    a.epub, a.out = os.path.abspath(a.epub), os.path.abspath(a.out)
    for name in ("support", "from_flat", "report"):
        if getattr(a, name):
            setattr(a, name, os.path.abspath(getattr(a, name)))
    reader = Reader(a.node, a.repo, a.epub)
    warnings, decisions, gaps = [], [], []
    stats = {"single": 0, "multi": 0, "sense_only": 0, "anchors": 0, "dropped": 0, "kept": 0, "trimmed": 0}
    dropped, phrases = [], {}
    header = {}
    hit = set()

    if a.support:
        blocks = blocks_from_support(a.support, dropped, phrases)
        if not blocks:
            sys.exit("no word blocks found in the support file")
        surfaces = sorted({b["surface"] for b in blocks})
        res = reader.ask({"lemmas": surfaces})
        lem = {s: v["lemma"] for s, v in res["lemmas"].items()}
        for v in res["lemmas"].values():
            _LEMMA[v["lemma"]] = {"attested": v["attested"], "easy": v["easy"]}
        groups = {}
        for b in blocks:
            groups.setdefault(lem[b["surface"]], []).append(b)
        glossary, hit = build_entries(groups, reader, a, stats, warnings, decisions, gaps)
        passthrough = 0
    else:
        flat = json.load(open(a.from_flat, encoding="utf-8"))
        header = {k: v for k, v in flat.items() if k not in ("glossary", "phrases")}
        phrases = dict(flat.get("phrases", {}))
        glossary = repair_glossary(flat, reader, a, stats, warnings, decisions, gaps)
        passthrough = stats["kept"]

    book = reader.book
    out = dict(header)
    out["version"] = 2
    out["title"] = a.title or header.get("title") or book["title"]
    out["author"] = a.author or header.get("author") or book["author"]
    out["chapters"] = a.chapters or book["chapters"]
    out["sha256"] = a.sha256 or header.get("sha256") or book["sha256"]
    out.setdefault("language", "en")
    out["glossary"] = glossary
    out["phrases"] = phrases
    # key + language checks (the validator checks again; failing early gives a clearer message)
    bad = [k for k in glossary if not WORD_TOKEN.match(k)]
    if bad:
        sys.exit(f"invalid word keys: {bad[:10]}")
    text = json.dumps(out, ensure_ascii=False, indent=1)
    if CJK_RE.search(text):
        sys.exit("Chinese or other CJK text found in the glossary; the glossary must be English only")
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(text)

    n_words = len(glossary)
    senses_n = sum(len(e.get("senses", [])) for e in glossary.values())
    print(f"wrote {a.out}: {n_words} words, {len(phrases)} phrases")
    print(f"  entries with senses: {sum(1 for e in glossary.values() if e.get('senses'))} ({senses_n} senses), senseOnly entries: {sum(1 for e in glossary.values() if e.get('senseOnly'))}")
    print(f"  this run: new anchors {stats['anchors']}, new default+anchored entries {stats['multi']}, new senseOnly {stats['sense_only']}, dropped {stats['dropped']}, trimmed to the general sentence {stats['trimmed']}")
    if a.from_flat:
        print(f"  repair: {passthrough} entries copied unchanged (their meaning is general)")
    if dropped:
        print(f"  dropped terms (no valid key): {len(dropped)}")
        for term, reason in dropped:
            print(f"    DROP {term!r}: {reason}")
    chapter_gaps, word_gaps = [], []
    if a.support and not a.passage:
        chapter_gaps = missing_chapters(book.get("chapterList"), hit, covered_marks(a.support))
        skip = {ch["index"] for ch in chapter_gaps}
        word_gaps = missing_hard_words(book.get("hardWords"), glossary_keys(glossary), skip)
        for ch in chapter_gaps:
            warnings.append(f"MISSING CHAPTER {ch['index']} {ch['title']!r} ({ch['words']} words): no support sentence located here")
        by_chapter = {}
        for h in word_gaps:
            by_chapter.setdefault(h["chapter"], []).append(h)
        for ci, rows in by_chapter.items():
            shown = ", ".join(f"{h['lemma']} ({h['count']})" for h in rows[:12])
            more = f" and {len(rows) - 12} more" if len(rows) > 12 else ""
            warnings.append(f"MISSING WORD chapter {ci}: {shown}{more}")
    pos_gaps = [g for g in gaps if g.get("kind", "pos") == "pos"]
    meaning_gaps = [g for g in gaps if g.get("kind") == "meaning"]
    print(f"  warnings: {len(warnings)}")
    for w in warnings:
        print(f"    WARN {w}")
    if a.report:
        json.dump({
            "stats": stats, "decisions": decisions, "warnings": warnings,
            "posGaps": pos_gaps, "meaningGaps": meaning_gaps,
            "missingChapters": chapter_gaps, "missingWords": word_gaps,
        }, open(a.report, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

    def gate_lines():
        lines = []
        if pos_gaps and not (a.allow_pos_gap or a.allow_gaps):
            lines.append(f"POS GAP: {len(pos_gaps)} word(s) are used as both a noun and a verb. Add a block for each place above.")
        if meaning_gaps and not a.allow_gaps:
            lines.append(f"MEANING GAP: {len(meaning_gaps)} word(s) are used with a different construction or the same content neighbor as a bound sense. Add a block for each place above.")
        if chapter_gaps and not a.allow_gaps:
            lines.append(f"MISSING CHAPTER: {len(chapter_gaps)} section(s) were not tied to the book. Process each one, or add <!-- covered: N --> when that section had nothing difficult.")
        if word_gaps and not a.allow_gaps:
            lines.append(f"MISSING WORD: {len(word_gaps)} word(s) are outside the common list and have no entry. Add a block for each.")
        return lines

    refused = gate_lines()
    if a.no_validate:
        print("validator skipped (--no-validate): do not publish this file")
        if refused:
            print("")
            for line in refused:
                print(line)
            print("This file is not ready to publish.")
            return 2
        return 0
    code = run_validator(a, a.out)
    if code != 0:
        return code
    code = run_lookup_check(a, a.out)
    if code != 0:
        return code
    if refused:
        print("")
        for line in refused:
            print(line)
        print("This file is not ready to publish.")
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

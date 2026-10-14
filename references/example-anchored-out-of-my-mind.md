# Example: anchored entries on a real book (Out of My Mind, Sharon M. Draper)

Real run of `scripts/build-glossary.py --from-flat` (migration mode) on the published flat glossary (2,445 words) and the book's EPUB, Reader repo checked out at `main` (the Reader that strips a plural `s` before it looks at the spelling). 2026-10-12.

## The bug this fixes

The flat glossary had two top-level entries, `sweat` (water from the skin) and `sweats` (soft clothes). The Reader looks up `sweats` as `sweat` first, so tapping `sweats` in chapter 5 showed the water meaning.

## The migrated entry

```json
"sweat": {
  "pos": "noun",
  "meaning": "It is the water that comes out of the skin. People get it when hot or nervous.",
  "forms": ["sweats"],
  "senses": [
    { "pos": "noun", "meaning": "It is the water that comes out of the skin. ...", "default": true },
    { "pos": "noun", "meaning": "Sweats are soft loose clothes for sports. ...", "forms": ["sweats"],
      "anchors": [
        { "chapter": 5,  "occurrence": 1, "form": "sweats", "context": "clothes—he always wears sweats—and sit him back in" },
        { "chapter": 13, "occurrence": 1, "form": "sweats", "context": "cute jeans and no sweats. Rose hasn’t said anything" },
        { "chapter": 30, "occurrence": 1, "form": "sweats", "context": "changed into thick gray sweats, was standing there at the" },
        { "chapter": 31, "occurrence": 1, "form": "sweats", "context": "clothes into warm, dry sweats, she switched the radio to" } ] }
  ]
}
```

Chapter 5 is the Reader's chapter index (0 = Acknowledgments), not an EPUB file name. The numbers come from the Reader's own code, not from the model.

## Gate output

```
validator exit code: 0
OK: 2303 words, 224 extra meanings, 307 anchors, ... (307 anchors and 0 notes checked against 35 chapters of the book).

1395 taps checked across 112 entries: every tap opens the intended meaning.
```

Tap replay for `sweats` (every use in the book):

```
chapter 5,  "sweats" #1: entry "sweat", via anchor -> Sweats are soft loose clothes for sports. ...
chapter 13, "sweats" #1: entry "sweat", via anchor -> Sweats are soft loose clothes for sports. ...
chapter 30, "sweats" #1: entry "sweat", via anchor -> Sweats are soft loose clothes for sports. ...
chapter 31, "sweats" #1: entry "sweat", via anchor -> Sweats are soft loose clothes for sports. ...
```

## Lite support block (v3.2) the build script reads

```
### sweats
- POS: noun
- Why it is hard: unusual meaning here
- Meaning: Soft, loose clothes (a top and pants) that people wear to relax or to play sports.
- Sentence: Dad, who had changed into thick gray sweats, was standing there at the front door, grinning, my denim book bag in his hand.
```

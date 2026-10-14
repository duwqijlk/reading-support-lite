"""Grammar, construction, default-sense, and coverage checks for Reading Support Lite v3.10. No EPUB and no network."""
import importlib.util
import pathlib
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("build_glossary", HERE / "build-glossary.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class GrammarRoleTest(unittest.TestCase):
    def role(self, left, right, form=""):
        return mod.grammar_role(left.split(), right.split(), form)

    def test_she_bites_her_fingernails_is_a_verb(self):
        # Out of My Mind, the sentence the noun gloss was wrongly opened on.
        self.assertEqual(self.role("sometimes i know she", "her fingernails and"), "verb")

    def test_a_bite_and_a_huge_bite_are_nouns(self):
        self.assertEqual(self.role("candy and took a", ""), "noun")
        self.assertEqual(self.role("connor took a huge", "of his steak"), "noun")

    def test_a_bite_to_eat_is_a_noun(self):
        self.assertEqual(self.role("you to get a", "to eat and"), "noun")

    def test_gonna_bite_and_hed_bite_are_verbs(self):
        # Curly apostrophes split: it's -> it + s, he'd -> he + d.
        self.assertEqual(self.role("and it s gonna", "your silly old"), "verb")
        self.assertEqual(self.role("i knew he d", "on that one"), "verb")
        self.assertEqual(self.role("she would", "the apple", "bite"), "verb")
        self.assertEqual(self.role("she can", "now", "bite"), "verb")

    def test_copula_be_does_not_force_a_verb(self):
        # "Here is paperwork" is a noun complement. "She is running" is not forced to a noun.
        self.assertNotEqual(self.role("here is", "for your parents", "paperwork"), "verb")
        self.assertEqual(self.role("here is", "for your parents", "paperwork"), "")
        self.assertNotEqual(self.role("here are", "on the desk", "forms"), "verb")
        self.assertEqual(self.role("she is", "home now", "running"), "")
        self.assertNotEqual(self.role("here is not", "for you", "paperwork"), "verb")
        self.assertEqual(self.role("she did not", "it", "bite"), "verb")

    def test_plural_noun_subject_stays_a_noun(self):
        self.assertEqual(self.role("the mosquito", "are painful", "bites"), "noun")
        self.assertEqual(self.role("several deep", "", "bites"), "")  # no determiner before the modifier: not forced

    def test_the_dog_bites_the_man_is_a_verb(self):
        self.assertEqual(self.role("the dog", "the man", "bites"), "verb")
        self.assertEqual(self.role("his little sister", "her nails", "bites"), "verb")
        # No object article, so the grammar does not force a verb. A plural noun stays possible.
        self.assertEqual(self.role("the door", "broke yesterday", "handles"), "")

    def test_a_bite_to_eat_is_a_different_construction_from_a_bite_of_food(self):
        self.assertEqual(mod.construction("of his steak".split(), "noun"), "")
        self.assertEqual(mod.construction("to eat and".split(), "noun"), "to")
        self.assertEqual(mod.construction("to the door".split(), "noun"), "")
        self.assertEqual(mod.construction("on that one".split(), "verb"), "on")
        self.assertEqual(mod.construction("on his face".split(), "noun"), "")
        self.assertEqual(mod.construction("your silly old".split(), "verb"), "")

    def test_a_hyphen_join_is_its_own_construction_and_a_space_is_not(self):
        # "first-place": the gap before "place" is exactly "-". "second place" has a space.
        self.assertEqual(mod.construction(["teams"], "verb", ["the", "first"], "-", ""), "first-")
        self.assertEqual(mod.construction(["challenging"], "adjective", ["an"], "", "-"), "-challenging")
        self.assertEqual(mod.construction(["word"], "", ["extra"], "-", "-"), "extra--word")
        self.assertEqual(mod.construction(["place"], "noun", ["second"], " ", ""), "")
        self.assertEqual(mod.construction(["on", "that"], "verb", ["she"], " ", ""), "on")
        self.assertEqual(mod.classify_use((1, "place", 1), "", "first-", "verb", {""}, set()), "meaning")
        self.assertEqual(mod.classify_use((1, "place", 1), "", "first-", "verb", {"first-"}, set()), "same")

    def test_a_bound_sense_neighbor_covers_another_form_and_a_new_neighbor_is_only_a_sample(self):
        bound = [{"chapter": 1, "form": "roll", "occurrence": 1, "left": ["i"], "right": ["back", "down"]}]
        uses = [
            {"chapter": 1, "form": "rolled", "occurrence": 1, "left": ["i"], "right": ["back", "to"]},
            {"chapter": 1, "form": "rolled", "occurrence": 2, "left": ["i"], "right": ["slowly", "to"]},
            {"chapter": 2, "form": "place", "occurrence": 1, "left": ["second"], "right": ["team"]},
            {"chapter": 2, "form": "place", "occurrence": 2, "left": ["my"], "right": ["at"]},
        ]
        taken = {(1, "roll", 1)}
        hit = mod.same_neighbor_uses(bound, uses, taken)
        self.assertEqual([(p["form"], p["occurrence"]) for p in hit], [("rolled", 1)])
        # One function word may sit between the word and its content neighbor.
        applause = [{"chapter": 5, "form": "round", "occurrence": 1, "left": ["a"], "right": ["of", "applause"]}]
        more = [
            {"chapter": 5, "form": "round", "occurrence": 2, "left": ["a"], "right": ["of", "applause"]},
            {"chapter": 5, "form": "round", "occurrence": 3, "left": ["a"], "right": ["of", "the"]},
        ]
        again = mod.same_neighbor_uses(applause, more, set())
        self.assertEqual([p["occurrence"] for p in again], [2])
        # The general sense was written beside "slowly". "back" is already a gap, not a sample.
        # "down" is a new neighbor. "rolling" is another form of a word that has a bound sense.
        attested = [{"chapter": 1, "form": "rolled", "occurrence": 2, "left": ["i"], "right": ["slowly", "to"]}]
        opening_uses = [
            {"chapter": 1, "form": "rolled", "occurrence": 2, "left": ["i"], "right": ["slowly", "to"]},
            {"chapter": 3, "form": "rolling", "occurrence": 1, "left": ["kept"], "right": ["down"]},
            {"chapter": 4, "form": "positive", "occurrence": 1, "left": ["almost"], "right": ["it"]},
            {"chapter": 4, "form": "positive", "occurrence": 2, "left": ["a"], "right": ["feeling"]},
        ]
        samples = mod.select_openings(attested, bound, opening_uses, {(1, "rolled", 2)})
        ids = [(p["chapter"], p["form"], p["occurrence"]) for p in samples]
        self.assertEqual(ids, [(4, "positive", 1), (3, "rolling", 1), (4, "positive", 2)])

    def test_default_is_the_sense_that_covers_more_places_not_more_blocks(self):
        # The first sense was written many times and covers 1 place. The second covers 6.
        self.assertEqual(mod.pick_default([
            {"cover": 1, "located": 1, "base": True},
            {"cover": 6, "located": 2, "base": True},
        ]), 1)
        # Same cover: the sense pinned to more places wins, not the one listed first.
        self.assertEqual(mod.pick_default([
            {"cover": 4, "located": 1, "base": True},
            {"cover": 4, "located": 5, "base": True},
        ]), 1)

    def test_a_different_construction_is_a_meaning_gap_and_the_other_part_of_speech_is_a_pos_gap(self):
        self.assertEqual(mod.classify_use((1, "bite", 1), "noun", "to", "noun", {""}, set()), "meaning")
        self.assertEqual(mod.classify_use((1, "bite", 1), "verb", "", "noun", {""}, set()), "pos")
        self.assertEqual(mod.classify_use((1, "bite", 1), "noun", "", "noun", {""}, set()), "same")
        self.assertEqual(mod.classify_use((1, "bite", 1), "noun", "to", "noun", None, set()), "same")
        self.assertEqual(mod.classify_use((1, "bite", 1), "noun", "to", "noun", {""}, {(1, "bite", 1)}), "taken")

    def test_a_skipped_chapter_and_a_skipped_hard_word_are_reported(self):
        chapters = [{"index": 0, "title": "One", "words": 80}, {"index": 1, "title": "Two", "words": 10}]
        self.assertEqual([c["index"] for c in mod.missing_chapters(chapters, set(), set())], [0])
        self.assertEqual(mod.missing_chapters(chapters, {0}, set()), [])
        self.assertEqual(mod.missing_chapters(chapters, set(), {0}), [])
        words = [{"lemma": "wheelchair", "count": 3, "chapter": 0}, {"lemma": "barn", "count": 1, "chapter": 2}]
        self.assertEqual([w["lemma"] for w in mod.missing_hard_words(words, {"barn"}, set())], ["wheelchair"])
        self.assertEqual(mod.missing_hard_words(words, set(), {0}), [words[1]])

    def test_fixed_prompt_stays_a_rule_not_an_example_list(self):
        text = (HERE.parent / "SKILL.md").read_text(encoding="utf-8")
        start = text.index("## Fixed subagent prompt")
        end = text.index("## Repair prompt")
        prompt = text[start:end]
        fence = prompt.index("```\n") + 4
        body = prompt[fence:prompt.index("```", fence)]
        self.assertIn("final -s is not automatically a plural noun", body)
        self.assertIn("unusual meaning here", body)
        self.assertIn("This passage is from that book", body)
        self.assertIn("copyrighted book", body)
        self.assertIn("usual dictionary sense", body)
        self.assertIn("do not also write that word with its usual dictionary meaning", body)
        self.assertIn("Passage:", body)
        self.assertNotIn("Example sentences", body)
        self.assertNotIn("fingernails", body)
        self.assertLess(len(body), 3500)
        repair = text[end:text.index("## Merge rules")]
        self.assertNotIn("Example sentences", repair)
        self.assertIn("unusual meaning here", repair)
        self.assertIn("copyrighted book", repair)
        self.assertIn("MEANING GAP", text)
        self.assertIn("MISSING CHAPTER", text)
        self.assertIn("MISSING WORD", text)
        self.assertIn("copyrighted book is not a reason to leave a gap", text)
        self.assertIn("Never cut a paragraph", text)
        self.assertIn("500–800 words", text)
        self.assertIn("## Review prompt", text)
        self.assertIn("DROP WORD", text)
        self.assertIn("reply with exactly: MATCH", text)
        self.assertIn('Why it is hard is "rare word"', text)
        self.assertIn("rewrites twice is not sent to the model again", text)
        self.assertIn("leave that word out and say so", text)
        self.assertIn("review only the new blocks", text)
        self.assertIn("fewer than 4 words", text)
        self.assertIn("lemma leftover", text)
        self.assertIn("Do not pass `--allow-gaps` in place of naming the gap", text)
        self.assertIn("OTHER OPENING", text)
        self.assertIn("content neighbor", text)
        self.assertIn("Do not add a person", text)
        self.assertIn("this word's part of the phrase", text)
        self.assertIn("Other openings:", text)
        self.assertIn("what this word means inside that phrase", text)
        self.assertLess(len(body), 3500)

    def test_a_paragraph_line_is_not_a_glossary_entry(self):
        path = pathlib.Path(tempfile.gettempdir()) / "reading-support-para-parse.md"
        path.write_text(
            "Passage: She is happy.\n\n"
            "### barn\n- POS: noun\n- Why it is hard: rare word\n"
            "- Meaning: A farm building.\n- Sentence: The barn is red.\n",
            encoding="utf-8",
        )
        try:
            entries = mod.parse_support(str(path))
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual([e["term"] for e in entries], ["barn"])


if __name__ == "__main__":
    unittest.main()

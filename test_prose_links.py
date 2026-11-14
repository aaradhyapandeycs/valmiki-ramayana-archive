import unittest

from prose_links import pair_units, prepare_links, sanskrit_numbers


class VerseSourceLinks(unittest.TestCase):
    def setUp(self):
        self.witness = {
            "book": 1, "sarga": 1, "status": "numbering_verified",
            "source_url": "https://valmikiramayan.net/utf8/baala/sarga1/balasans1.htm",
            "source_sha256": "a" * 64,
            "verses": [
                {"number": n, "sanskrit": f"रामः ।। 1-1-{n}", "source_anchor": f"Verse{n}"}
                for n in range(1, 5)
            ],
        }
        self.source = {key: self.witness[key] for key in ("source_url", "source_sha256")}
        self.source.update(status="checked", issues=[{"reason": "source_issue", "ordinal": 3}], groups=[])

    def add_group(self, fragment, refs, verses):
        self.source["groups"].append({
            "refs": refs, "verse_numbers": verses, "fragment": fragment,
            "basis": "printed_translation_reference", "paragraph_sha256": "b" * 64,
        })

    def test_overlapping_partial_groups_are_placed_once_at_their_start(self):
        self.add_group("Verse1", ["1-1-1b", "1-1-2a"], [1, 2])
        self.add_group("Verse2", ["1-1-2b–1-1-3a"], [2, 3])
        groups, issues = prepare_links(self.witness, {}, self.source)
        self.assertEqual([["verse-1", "verse-2"], ["verse-2", "verse-3"]],
                         [group["units"] for group in groups])
        self.assertEqual(1, issues["source_issue"])
        html = pair_units([(f"verse-{n}", f"source{n}") for n in range(1, 5)], groups)
        self.assertEqual(2, html.count('class="verse-translation"'))
        self.assertIn('data-source-refs="1-1-1b 1-1-2a"', html)
        self.assertLess(html.index("source2"), html.index('data-source-refs="1-1-2b'))
        self.assertLess(html.index('data-source-refs="1-1-2b'), html.index("source3"))

    def test_contiguous_group_uses_one_shared_block(self):
        self.add_group("Verse3", ["1-1-1–1-1-3"], [1, 2, 3])
        groups, _ = prepare_links(self.witness, {}, self.source)
        html = pair_units([(f"verse-{n}", f"source{n}") for n in range(1, 5)], groups)
        self.assertEqual(1, html.count('class="verse-pair"'))
        self.assertIn("source1source2source3</div>", html)
        self.assertLess(html.index("Verse3"), html.index("source4"))

    def test_duplicated_reference_is_unresolved_even_under_another_anchor(self):
        self.add_group("Verse1", ["1-1-1"], [1])
        self.add_group("Verse2", ["1-1-1"], [1])
        groups, issues = prepare_links(self.witness, {}, self.source)
        self.assertEqual([], groups)
        self.assertEqual(2, issues["duplicate_reference_group"])

    def test_missing_local_reference_is_explicit(self):
        self.add_group("Verse3", ["1-1-3–1-1-5"], [3, 4, 5])
        groups, issues = prepare_links(self.witness, {}, self.source)
        self.assertEqual([], groups)
        self.assertEqual(1, issues["missing_local_reference"])

    def test_scope_does_not_fallback_to_number_or_source_anchor(self):
        self.witness["status"] = "source_blocks_verified"
        self.witness["verses"][0]["sanskrit"] = "रामः ।। 1-2-1"
        self.add_group("Verse1", ["1-1-1"], [1])
        groups, issues = prepare_links(self.witness, {}, self.source)
        self.assertEqual([], groups)
        self.assertEqual(set(), sanskrit_numbers(self.witness, self.witness["verses"][0]["sanskrit"]))
        self.assertEqual(1, issues["missing_local_reference"])


if __name__ == "__main__":
    unittest.main()

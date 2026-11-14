from hashlib import sha256
import json
import unittest

from collect_prose_links import link_metadata, parse, parse_reference_label


def fake_page(units):
    return parse(f"<html><body>{units}</body></html>".encode())


class ProseLinkMetadata(unittest.TestCase):
    def test_exact_full_partial_group_with_distinct_source_evidence(self):
        found, missing, count = link_metadata(fake_page("""
<p class="verloc"><a name="Verse18"></a></p>
<p class="SanSloka">प्रथमः | द्वितीयः || १-१-१८<br>तृतीयः |</p>
<p class="pratipada">18, 19a. gloss should remain absent</p>
<p class="tat">Prose should remain absent. [1-1-18, 19a]</p>
<p class="comment">Comment should remain absent. [1-1-18, 19a]</p>
"""), 1, 1)
        self.assertEqual(1, count)
        self.assertEqual([], missing)
        self.assertEqual(["1-1-18", "1-1-19a"], found[0]["refs"])
        self.assertEqual([18, 19], found[0]["verse_numbers"])
        self.assertEqual(["1-1-18"], found[0]["source_sanskrit_refs"])
        self.assertEqual("Verse18", found[0]["fragment"])
        self.assertEqual(sha256("Prose should remain absent. [1-1-18, 19a]".encode()).hexdigest(),
                         found[0]["paragraph_sha256"])
        self.assertNotIn("should remain absent", json.dumps(found))

    def test_exact_contiguous_range_and_compact_parts(self):
        self.assertEqual((["3-1-9–3-1-10a"], {9, 10}), parse_reference_label("3-1-9-10a", 3, 1))
        self.assertEqual((["3-1-20b", "3-1-20c"], {20}), parse_reference_label("3-1-20b,c", 3, 1))
        self.assertEqual((["3-1-10", "3-1-11a"], {10, 11}), parse_reference_label("3-1-10. 11a", 3, 1))
        self.assertEqual((["5-1-5", "5-1-6", "5-1-7"], {5, 6, 7}),
                         parse_reference_label("5-1-5; 6; 7", 5, 1))

    def test_extra_full_verse_cannot_be_inferred_from_unnumbered_half(self):
        found, missing, _ = link_metadata(fake_page("""
<a name="Verse18"></a>
<p class="SanSloka">प्रथमः | द्वितीयः || १-१-१८<br>तृतीयः |</p>
<p class="tat">Grouped English. [1-1-18, 19]</p>
"""), 1, 1)
        self.assertEqual([], found)
        self.assertEqual("printed_reference_disagrees_with_unit", missing[0]["reason"])

    def test_reject_invalid_book_and_group_order(self):
        for label, expected in [("3-1-3", "wrong_chapter_reference"),
                                ("4-1-29b, 20, 21a", "unordered_or_overlapping_reference")]:
            with self.subTest(label=label), self.assertRaisesRegex(ValueError, expected):
                parse_reference_label(label, 4, 1)

    def test_fallback_requires_unambiguous_sanskrit_boundaries(self):
        found, missing, count = link_metadata(fake_page("""
<a name="Verse1"></a>
<p class="SanSloka">प्रथमः | द्वितीयः || ६-१-१</p>
<p class="tat">First statement.</p>
<a name="Verse2"></a>
<p class="SanSloka">तृतीयः | चतुर्थः || ६-१-२<br>प्रथमः |</p>
<p class="tat">A complete unit and part of the next.</p>
<a name="Verse3"></a>
<p class="SanSloka">द्वितीयः || ६-१-३</p>
<p class="tat">The other part.</p>
<a name="Verse4"></a>
<p class="SanSloka">प्रथमः | द्वितीयः || ६-१-४</p>
<p class="tat">Statement A.</p>
<p class="tat">Statement B.</p>
"""), 6, 1)
        self.assertEqual(5, count)
        self.assertEqual(["6-1-1"], found[0]["refs"])
        self.assertEqual("anchored_sanskrit_reference", found[0]["basis"])
        self.assertEqual(["unlabelled_partial_boundary", "unlabelled_partial_boundary",
                          "no_unambiguous_translation_reference", "no_unambiguous_translation_reference"],
                         [i["reason"] for i in missing])

    def test_reject_duplicate_anchors_and_opening_prose(self):
        found, missing, count = link_metadata(fake_page("""
<p class="tat">Introduction</p>
<a name="Verse1"></a>
<p class="SanSloka">प्रथमः | द्वितीयः || ६-१-१</p>
<p class="tat">Prose one [6-1-1]</p>
<a name="Verse1"></a>
<p class="SanSloka">तृतीयः | चतुर्थः || ६-१-२</p>
<p class="tat">Prose two [6-1-2]</p>
"""), 6, 1)
        self.assertEqual([], found)
        self.assertEqual(3, count)
        self.assertEqual(["no_verse_anchor", "duplicated_verse_anchor", "duplicated_verse_anchor"],
                         [i["reason"] for i in missing])


if __name__ == "__main__":
    unittest.main()

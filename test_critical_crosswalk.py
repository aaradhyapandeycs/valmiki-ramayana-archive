import unittest

from map_critical_translations import ArchiveText, Match, Unit, exact_text, map_book, nonconflicting, orthographic_text


SANSKRIT_1 = "तपःस्वाध्यायनिरतं तपस्वी वाग्विदां वरम् । नारदं परिपप्रच्छ वाल्मीकिर्मुनिपुङ्गवम् ॥"
SANSKRIT_2 = "को न्वस्मिन् साम्प्रतं लोके गुणवान् कश्च वीर्यवान् । धर्मज्ञश्च कृतज्ञश्च सत्यवाक्यो दृढव्रतः ॥"
SANSKRIT_3 = "चारित्रेण च को युक्तः सर्वभूतेषु को हितः । विद्वान् कः कः समर्थश्च कश्चैकप्रियदर्शनः ॥"


def row(verse, sanskrit, *, dutt=None, kind="1:1", english="Text"):
    return {
        "id": f"VRCE-1-1-{verse}", "kanda": 1, "kandaId": "bala", "sarga": 1, "verse": verse,
        "sanskrit": sanskrit, "english": english,
        "alignment": {"type": kind, "duttRefs": [f"DUTT-1-1-{dutt or verse}"]},
    }


class TestCriticalCrosswalk(unittest.TestCase):
    def test_formatting_only_includes_locator_but_no_word_substitution(self):
        locator = SANSKRIT_2.replace("।", "|") + " १-१-२"
        self.assertEqual(exact_text(SANSKRIT_2), exact_text(locator))
        self.assertNotEqual(exact_text(SANSKRIT_2.replace("वीर्यवान्", "तेजस्वी")), exact_text(locator))
        self.assertEqual("", exact_text(SANSKRIT_2 + " damaged"))
        self.assertEqual("", exact_text(SANSKRIT_2 + " 4532"))
        self.assertEqual(exact_text(SANSKRIT_2), exact_text(SANSKRIT_2 + " ४५४२", fused_locator=True))

    def test_nasal_candidates_are_kept_out_of_exact_matches(self):
        units = [Unit(1, "verse-1", SANSKRIT_1)]
        source = [row(1, SANSKRIT_1.replace("पुङ्ग", "पुंग"))]
        chapters, orthographic, gaps, _, counts = map_book(units, source, 1, "baala")
        self.assertFalse(chapters)
        self.assertEqual("orthographic_nasal", orthographic["baala/1"][0]["method"])
        self.assertEqual(["verse-1"], gaps["baala/1"])
        self.assertEqual(1, counts["orthographic_candidate_verses"])
        self.assertNotEqual(orthographic_text("हनुमान् पश्यति"), orthographic_text("हनुमां पश्यति".replace("प", "य")))

    def test_shared_source_group_matches_as_one_contiguous_entry(self):
        units = [Unit(1, "verse-1", SANSKRIT_1), Unit(1, "verse-2", SANSKRIT_2)]
        source = [row(1, SANSKRIT_1, dutt=1, kind="grouped"),
                  row(2, SANSKRIT_2, dutt=1, kind="grouped")]
        chapters, _, _, _, counts = map_book(units, source, 1, "baala")
        self.assertEqual(1, counts["matched_source_passages"])
        self.assertEqual(["verse-1", "verse-2"], chapters["baala/1"][0]["units"])
        self.assertEqual([source[0]["id"], source[1]["id"]], chapters["baala/1"][0]["refs"])
        self.assertNotIn("english", chapters["baala/1"][0])

    def test_split_archive_verse_spans_two_units_and_reports_partial(self):
        first, second = SANSKRIT_2.split("।", 1)
        units = [Unit(1, "block-3", SANSKRIT_1 + " " + first),
                 Unit(1, "block-4", second)]
        chapters, _, _, _, _ = map_book(units, [row(2, SANSKRIT_2)], 1, "baala")
        hit = chapters["baala/1"][0]
        self.assertEqual(["block-3", "block-4"], hit["units"])
        self.assertTrue(hit["partially_covers_archive_unit"])

    def test_repeated_formulas_and_contradictory_order_are_rejected(self):
        repeated = ArchiveText([Unit(1, "verse-1", SANSKRIT_1), Unit(2, "verse-1", SANSKRIT_1)], 1)
        self.assertEqual(("repeated", None), repeated.find(exact_text(SANSKRIT_1), "formatting"))
        units = [Unit(1, "verse-1", SANSKRIT_2), Unit(1, "verse-2", SANSKRIT_1),
                 Unit(1, "verse-3", SANSKRIT_3)]
        chapters, _, _, _, counts = map_book(units, [row(1, SANSKRIT_1), row(2, SANSKRIT_2), row(3, SANSKRIT_3)], 1, "baala")
        self.assertEqual(2, counts["conflicts_with_reading_order"])
        self.assertEqual(["VRCE-1-1-3"], chapters["baala/1"][0]["refs"])

    def test_approximate_group_never_lands_inline(self):
        units = [Unit(1, "verse-1", SANSKRIT_1), Unit(1, "verse-2", SANSKRIT_2)]
        source = [row(1, SANSKRIT_1, dutt=1, kind="approximate"), row(2, SANSKRIT_2, dutt=1, kind="grouped")]
        chapters, _, _, ranges, _ = map_book(units, source, 1, "baala")
        self.assertFalse(chapters)
        self.assertEqual(["source_approximate", "source_approximate"], [entry["reason"] for entry in ranges["1"]])

    def test_nonconflict_allows_touching_spans(self):
        hits = [Match(0, 0, 0, 5, True, "formatting"), Match(0, 0, 5, 12, True, "formatting")]
        self.assertEqual({0, 1}, nonconflicting(hits))


if __name__ == "__main__":
    unittest.main()

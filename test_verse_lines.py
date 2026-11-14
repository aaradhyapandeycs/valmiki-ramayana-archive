import unittest

from transliterate_iast import transliterate
from verse_lines import corresponding_breaks, line_break_offsets, line_segments, render_lines, reviewed_verse_breaks


class VerseRows(unittest.TestCase):
    def check(self, text, want):
        actual = list(line_segments(text))
        self.assertEqual(want, [row for row, _ in actual])
        self.assertEqual(text, "".join(row + sep for row, sep in actual))

    def test_bala_1_2(self):
        first = "को न्वस्मिन् साम्प्रतं लोके गुणवान् कश्च वीर्यवान् |"
        last = "धर्मज्ञश्च कृतज्ञश्च सत्यवाक्यो दृढव्रतः\n|| १-१-२"
        self.check(first + "\n" + last, [first, last])

    def test_both_punctuation_styles(self):
        self.check("पहिली\n।\nदूसरी\n॥\n १-१-५", ["पहिली\n।", "दूसरी\n॥\n १-१-५"])
        self.check("first\n|\nsecond ||\n1-1-5–7", ["first\n|", "second ||\n1-1-5–7"])

    def test_genuinely_multiline_verse(self):
        self.check("first |\nsecond |\nthird |\nfourth || 1-1-2",
                   ["first |", "second |", "third |", "fourth || 1-1-2"])

    def test_appendix_blank_lines_and_headings(self):
        self.check("heading\n\n1. namo -\nfirst |\nsecond || 1-1-2",
                   ["heading", "", "1. namo -", "first |", "second || 1-1-2"])

    def test_exact_break_map_for_roman(self):
        source = "धीः |\nएतत्\nशिवम्\n|| १-१-२"
        roman = "dhīḥ |\netat\nśivam\n|| 1-1-2"
        offsets = [source.index("\n")]
        self.assertEqual([roman.index("\n")], corresponding_breaks(source, roman, offsets))
        self.assertEqual(2, render_lines(roman, corresponding_breaks(source, roman, offsets)).count("<span"))

    def test_reviewed_fused_half_verses_preserve_both_exact_texts(self):
        source = "अमी पवन विक्षिप्ता विनन्दन्ती इव पादपाः |षट्पदैः अनुकूजद्भिः वनेषु मधु गन्धिषु || ४-१-१८"
        roman = transliterate(source)
        offsets = reviewed_verse_breaks(source, [], 4, 1, 18)
        self.assertEqual([source.index("|ष") + 1], offsets)
        self.assertEqual(2, render_lines(source, offsets).count("<span"))
        for text, cuts in ((source, offsets), (roman, corresponding_breaks(source, roman, offsets))):
            rows = list(line_segments(text, cuts))
            self.assertEqual(text, "".join(row + separator for row, separator in rows))
        self.assertEqual([], reviewed_verse_breaks(source, [], 4, 1, 19))
        with self.assertRaises(ValueError):
            reviewed_verse_breaks(source + " ", [], 4, 1, 18)


if __name__ == "__main__":
    unittest.main()

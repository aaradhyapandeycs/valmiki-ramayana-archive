import unittest

from verse_lines import corresponding_breaks, line_break_offsets, line_segments, render_lines


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


if __name__ == "__main__":
    unittest.main()

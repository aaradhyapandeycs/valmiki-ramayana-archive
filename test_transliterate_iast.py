"""Checks for exact Sanskrit IAST and visibly unsupported source characters."""
import unicodedata
import unittest

from transliterate_iast import transliterate


class IastTests(unittest.TestCase):
    def test_opening_verse(self):
        source = (
            "तपःस्वाध्यायनिरतं तपस्वी वाग्विदां वरम् |\n"
            "नारदं परिपप्रच्छ वाल्मीकिर्मुनिपुङ्गवम् || १-१-१"
        )
        self.assertEqual(
            transliterate(source),
            "tapaḥsvādhyāyanirataṃ tapasvī vāgvidāṃ varam |\n"
            "nāradaṃ paripapraccha vālmīkirmunipuṅgavam || 1-1-1",
        )

    def test_standard_letters_and_signs(self):
        cases = {
            "ज्ञ त्व क्‍ष श्र ऋ ॠ ऌ ॡ कृ कॄ कॢ कॣ कँ ॐ ॥":
                "jña tva kṣa śra ṛ ṝ ḷ ḹ kṛ kṝ kḷ kḹ kam̐ oṃ ||",
            "गच्छता मातुलकुलं भरतेन तदाऽनघः": "gacchatā mātulakulaṃ bharatena tadā'naghaḥ",
            "अ।\nआ॥": "a|\nā||",
        }
        for source, target in cases.items():
            with self.subTest(source=source):
                text = transliterate(source)
                self.assertEqual(text, target)
                self.assertTrue(unicodedata.is_normalized("NFC", text))

    def test_damaged_source_is_not_guessed(self):
        for text in ("्", "क़", "का्", "क‍ष", "ततो��रामः", "रामB", "ततो&अम्प्;अभ्यवकि", "क^त्र"):
            with self.subTest(text=text):
                self.assertIsNone(transliterate(text))


    def test_dependent_mark_requires_a_vowel(self):
        self.assertIsNone(transliterate("एवमुक्तो ंऽशुमान् सम्यक्सगरेण महात्मना"))
        self.assertIsNone(transliterate("ः राम"))
        self.assertIsNone(transliterate("राम् ँ"))
        self.assertEqual(transliterate("अंशुमान् रामः चँद्र"), "aṃśumān rāmaḥ cam̐dra")
        self.assertEqual(transliterate("रामां स्वयम्"), "rāmāṃ svayam")


if __name__ == "__main__":
    unittest.main()

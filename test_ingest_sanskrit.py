"""Regression tests for malformed source markup and reviewed glyph exceptions."""
import unittest

from ingest_sanskrit import SlokaPane, decode_irregular, decode_verses, glyph_exception


class SanskritIngestionTest(unittest.TestCase):
    def test_audio_controls_do_not_consume_the_verse_anchor(self):
        markup = '''
          <p class="verloc"><a name="Verse1"></a></p>
          <p class="SanSloka"><audio><source src="verse.mp3"/></audio></p>
          <p class="SanSloka">ततः स रामः |<br/>सत्यं वदति वै || १-१-१</p>
          <p class="EngTrans">This fragment is excluded.</p>
        '''
        verses, status, issues, _ = decode_verses(markup.encode(), 1, 1)
        self.assertEqual(status, "numbering_verified", issues)
        self.assertEqual(len(verses), 1)
        self.assertEqual(verses[0]["source_anchor"], "Verse1")

    def test_bala_heading_disambiguates_titleless_fourteenth_chapter(self):
        markup = '''
          <h3>Book I : Bala Kanda</h3><h3>Chapter [Sarga] 14</h3>
          <p class="verloc"><a name="Verse1"></a></p>
          <p class="SanSloka">ततः स रामः |<br/>सत्यं वदति वै || १-१४-१</p>
          <p class="SanSloka">Or</p>
          <p class="SanSloka">इति श्रीरामायणे चतुर्दशः सर्गः</p>
        '''
        pane = SlokaPane()
        pane.feed(markup)
        pane.close()
        verses, status, _, colophon = decode_irregular(pane, 1, 14)
        self.assertEqual(status, "source_blocks_verified")
        self.assertEqual(len(verses), 1)
        self.assertIn("चतुर्दशः", colophon)
        self.assertEqual(decode_irregular(pane, 1, 15)[1], "needs_review")

    def test_wrong_locator_or_extra_english_rejects_glyph_exception(self):
        verse = "ततः स रामः Bवदति वै || २-१२-११०"
        self.assertEqual(glyph_exception(verse, 2, 12, "Verse110"),
                         {"token": "B", "printed_verses": [110]})
        self.assertIsNone(glyph_exception(verse, 2, 12, "Verse109"))
        self.assertIsNone(glyph_exception(verse, 2, 13, "Verse110"))
        self.assertIsNone(glyph_exception(verse + " unexpected text", 2, 12, "Verse110"))
        self.assertIsNone(glyph_exception(verse.replace("B", "BB"), 2, 12, "Verse110"))
        self.assertIsNone(glyph_exception(verse.replace("B", "Bα"), 2, 12, "Verse110"))
        self.assertIsNone(glyph_exception(verse.replace("११०", "१०९"), 2, 12, "Verse110"))


if __name__ == "__main__":
    unittest.main()

"""Devanagari to IAST for the displayed Sanskrit witness.

This generates a new display mode from the source Devanagari. It does not
transcribe, compare, or replace the source site's separate Roman edition.
Candrabindu uses m with a combining candrabindu (U+0310). The avagraha uses
an apostrophe, and the daṇḍa and double daṇḍa use one and two vertical bars.
"""
import unicodedata

VOWELS = dict(zip("अआइईउऊऋॠऌॡएऐओऔ",
                  ("a", "ā", "i", "ī", "u", "ū", "ṛ", "ṝ", "ḷ", "ḹ", "e", "ai", "o", "au")))
MATRAS = dict(zip("ािीुूृॄॢॣेैोौ",
                  ("ā", "i", "ī", "u", "ū", "ṛ", "ṝ", "ḷ", "ḹ", "e", "ai", "o", "au")))
CONSONANTS = dict(zip("कखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसहळ",
                       ("k", "kh", "g", "gh", "ṅ", "c", "ch", "j", "jh", "ñ", "ṭ", "ṭh",
                        "ḍ", "ḍh", "ṇ", "t", "th", "d", "dh", "n", "p", "ph", "b", "bh",
                        "m", "y", "r", "l", "v", "ś", "ṣ", "s", "h", "ḻ")))
SIGNS = {"ं": "ṃ", "ः": "ḥ", "ँ": "m̐", "ऽ": "'", "ॐ": "oṃ", "।": "|", "॥": "||"}
DIGITS = dict(zip("०१२३४५६७८९", "0123456789"))
DEPENDENT_SIGNS = {"ं", "ः", "ँ"}
VOWEL_ENDINGS = VOWELS.keys() | MATRAS.keys() | CONSONANTS.keys()
JOINERS = {"\u200c", "\u200d"}
PUNCTUATION = frozenset("0123456789 |-.–—,!?()[]:;'’‘“”\"…")


def transliterate(text):
    """Return generated IAST or None if the source uses an unhandled sign."""
    result = []
    pending_vowel = False
    previous = ""
    for char in unicodedata.normalize("NFC", text):
        if char in JOINERS:
            if previous != "्":
                return None
            continue
        if char in DEPENDENT_SIGNS and previous not in VOWEL_ENDINGS:
            return None
        previous = char
        if char in MATRAS or char == "्":
            if not pending_vowel:
                return None
            result.append(MATRAS.get(char, ""))
            pending_vowel = False
            continue
        if pending_vowel:
            result.append("a")
            pending_vowel = False
        if char in CONSONANTS:
            result.append(CONSONANTS[char])
            pending_vowel = True
        elif char in VOWELS:
            result.append(VOWELS[char])
        elif char in SIGNS:
            result.append(SIGNS[char])
        elif char in DIGITS:
            result.append(DIGITS[char])
        elif char.isspace() or char in PUNCTUATION:
            result.append(char)
        else:
            return None
    if pending_vowel:
        result.append("a")
    return unicodedata.normalize("NFC", "".join(result))

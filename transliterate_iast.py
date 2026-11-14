"""Devanagari to IAST for the displayed Sanskrit witness.

This generates a new display mode from the source Devanagari. It does not
transcribe, compare, or replace the source site's separate Roman edition.
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


def transliterate(text):
    """Return generated IAST or None if the source uses an unhandled sign."""
    result = []
    pending_vowel = False
    for char in unicodedata.normalize("NFC", text):
        if char in {"\u200c", "\u200d"}:
            continue
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
        elif char.isspace() or unicodedata.category(char)[0] in {"P", "N", "S"}:
            result.append(char)
        else:
            return None
    if pending_vowel:
        result.append("a")
    return "".join(result)

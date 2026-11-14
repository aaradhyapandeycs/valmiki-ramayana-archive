"""Reviewed noncanonical reference conventions in exact primary HTML snapshots."""

import re


# Keys are canonical book and chapter. Values are the consistently printed
# source prefix, number of consecutive verses, and matching raw HTML SHA-256.
# Chapter identity is corroborated by the frame index and source page heading.
REVIEWED_COORDINATES = {
    (3, 16): ((4, 16), 43, "b6a6917203577037b5c0b20374b21a5bc0d711ce0849485fdc54bdbf58233887"),
    (3, 28): ((4, 28), 33, "a77167287723bc8049107b13d6ffb562bee984598f859b5073d088dfa3987203"),
    (3, 39): ((4, 39), 25, "e0dfc2229cd1c3227e5b62af4861f0c50d53f4bacfadaa114e53c651ba6adaeb"),
    (3, 66): ((4, 66), 21, "09bc021ba5ef233cf77e462e3d918614695110e925f2626aeaf39f66708768d1"),
    (6, 87): ((87, 6), 30, "64a5592fb9bd8b3d8df7457219c6864d28b346208c37e5ea8cd61514aceafd02"),
    (6, 88): ((88, 6), 79, "eb5829c90faa84cd8b2f3b2c39e1c42130d2c609c44900f1783e8a31327a5708"),
    (6, 89): ((89, 6), 54, "742115d7eb98ba01cf37469253b82c2cec54edf045abd60a9442de821d5d396b"),
    (6, 90): ((90, 6), 97, "98c958d85e72d3f02a16727818a7606101462e6f748dbee2bf2b728bf4b8b7fc"),
    (6, 91): ((91, 6), 28, "41bcf316ba1ddb26cefed7b3fb81f3849925485bd12d0f5707aea1318a7b8ee4"),
    (6, 92): ((92, 6), 68, "a15d559b706fc4eb858acb48b0dc790e2bffa82a0b28750e0f38641867a98f14"),
    (6, 94): ((94, 6), 41, "89fb2bfbf4fb828a956f812ed3ff66c06cd8c54a6b850426f9c3a310f2c793da"),
}

DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
COORDINATES = re.compile(
    r"(?<![\d-])([0-9]{1,3})\s*[-–]\s*([0-9]{1,3})\s*[-–]\s*([0-9]{1,3})"
    r"(?:\s*[-–]\s*([0-9]{1,3}))?(?![\d-])"
)


def printed_coordinates(book, chapter, source_sha256):
    review = REVIEWED_COORDINATES.get((book, chapter))
    return review[0] if review and source_sha256 == review[2] else None


def verify_uniform_coordinates(book, chapter, source_sha256, passages):
    """Require a unique consecutive set of verse numbers in the reviewed witness."""
    coordinates = printed_coordinates(book, chapter, source_sha256)
    if coordinates is None:
        return None
    count = REVIEWED_COORDINATES[book, chapter][1]
    expected_next = 1
    for passage in passages:
        for match in COORDINATES.finditer(passage.translate(DIGITS)):
            first, second, start = (int(value) for value in match.groups()[:3])
            end = int(match[4] or start)
            if (first, second) != coordinates or start != expected_next or not start <= end <= count:
                raise ValueError(f"Alternate source verse numbering no longer uniform at {book}.{chapter}")
            expected_next = end + 1
    if expected_next != count + 1:
        raise ValueError(f"Incomplete alternate source verse numbering at {book}.{chapter}")
    return coordinates

#!/usr/bin/env python3
"""Prepare a separate M. N. Dutt edition from pinned UTF-8 transcriptions."""
import argparse
import gzip
import hashlib
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
SOURCES = {
    57265: "369a99e2515fa3938782a5f8d14cbadade9aae5caa70d5c5cebf3251425b3c3c",
    57826: "424b6a12c6e8b3d0f91af75f146c2b58f6fff9d10bd187377b84a330a39987be",
    60188: "b1d58598046b19ecb0eb18192e0b18fe03ce3b4ce900ce1b76828e7c1c6fa62d",
}
# The exact input snapshots are pinned above. Offsets refer to their zero-based lines.
BOOKS = (
    ("baala", "Bāla", 57265, 548, 5915, 77),
    ("ayodhya", "Ayodhyā", 57265, 5915, 15809, 119),
    ("aranya", "Araṇya", 57826, 295, 5878, 76),
    ("kish", "Kiṣkindhā", 57826, 5883, 11407, 67),
    ("sundara", "Sundara", 57826, 11412, 18254, 68),
    ("yuddha", "Yuddha", 60188, 212, 13720, 130),
)
HEAD = re.compile(r"^SECTI[O0]N ([IVXLCDMN]+)\.?(?:\[\d+\]|[⁰¹²³⁴⁵⁶⁷⁸⁹]+)?$", re.I)

# The transcription joins four section openings to their preceding chapter
# without a heading. Match the exact first line before restoring the boundary.
INSERT = {
    57265: {
        3682: (43, "When that god of gods had gone away, Bhagiratha, O Rāma, pressing the"),
        15764: (119, "Having heard this grand story, Anasuyā cognizant of righteousness,"),
    },
    57826: {
        18199: (68, "Whereupon, O foremost of men, out of thy love and adoring me for thy"),
    },
    60188: {
        7279: (70, "And seeing Narāntaka slain, the foremost of Nairitas—including the"),
    },
}
RENUMBER = {
    57265: {3010: "32", 5579: "73"},
    57826: {4323: "56a", 4403: "56b"},
    60188: {2338: "26", 7718: "72", 9351: "87"},
}


def source_lines(data, ebook, sha):
    normalized = data.decode("utf-8-sig").replace("\r\n", "\n")
    body, end, _ = normalized.partition("*** END OF THIS PROJECT GUTENBERG EBOOK")
    body = body.strip()
    if not end or hashlib.sha256(body.encode()).hexdigest() != sha:
        raise ValueError(f"Source snapshot changed for ebook {ebook}")
    return body.splitlines()


def download(ebook):
    url = f"https://www.gutenberg.org/files/{ebook}/{ebook}-0.txt"
    request = Request(url, headers={"User-Agent": "Valmiki archive build (Dutt edition)"})
    with urlopen(request, timeout=40) as response:
        data = response.read(2_000_001)
    if len(data) > 2_000_000:
        raise ValueError(f"Unexpectedly large response for ebook {ebook}")
    return data


def number(romans):
    v = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    digits = [v[c] for c in romans.upper()]
    return str(sum(-n if n < nxt else n for n, nxt in zip(digits, digits[1:] + [0])))


def section_ranges(lines, book):
    slug, _, ebook, start, end, expected = book
    positions = []
    for line_number in range(start + 1, end):
        line = lines[line_number]
        m = HEAD.fullmatch(line.strip())
        insert = INSERT.get(ebook, {}).get(line_number)
        revised = RENUMBER.get(ebook, {}).get(line_number)
        if insert is not None:
            n, first_line = insert
            if line != first_line:
                raise ValueError(f"Changed section marker at {ebook}:{line_number}")
            positions.append((str(n), line_number, line_number, None))
        elif m:
            identifier = revised or number(m.group(1))
            positions.append((identifier, line_number, line_number + 1, line.strip()))
    want = [str(n) for n in range(1, expected + 1)]
    if slug == "aranya":
        want = want[:55] + ["56a", "56b"] + want[56:-1]
    if [position[0] for position in positions] != want:
        raise ValueError(f"Unexpected sequence for {slug}: {[p[0] for p in positions]}")
    for pos, nxt in zip(positions, positions[1:] + [(None, end, None, None)]):
        identifier, heading_line, body_start, printed_heading = pos
        body = "\n".join(lines[body_start:nxt[1]]).strip()
        if len(body) < 120 or "PROJECT GUTENBERG" in body.upper():
            raise ValueError(f"Invalid section text: {slug}/{identifier}")
        yield {
            "id": identifier,
            "printed_heading": printed_heading,
            "text": body,
            "source_line": heading_line + 1,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "archive")
    parser.add_argument("--output", type=Path, default=ROOT / "dutt-corpus")
    parser.add_argument("--download", action="store_true", help="fetch the three pinned volumes")
    args = parser.parse_args()
    sources = {
        ebook: source_lines(
            download(ebook) if args.download else (args.input / f"{ebook}.txt").read_bytes(),
            ebook, sha,
        )
        for ebook, sha in SOURCES.items()
    }
    args.output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=args.output) as staging:
        output_files = []
        for book in BOOKS:
            slug, title, ebook, _, _, _ = book
            sections = list(section_ranges(sources[ebook], book))
            result = {
                "edition": "Manmatha Nath Dutt, 1891–1893",
                "book": title,
                "source": f"https://www.gutenberg.org/ebooks/{ebook}",
                "sections": sections,
            }
            data = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode()
            output_file = Path(staging) / f"{slug}.json.gz"
            output_file.write_bytes(gzip.compress(data, mtime=0))
            output_files.append(output_file)
            print(f"{title}: {len(sections)} sections")
        for output_file in output_files:
            output_file.replace(args.output / output_file.name)


if __name__ == "__main__":
    main()

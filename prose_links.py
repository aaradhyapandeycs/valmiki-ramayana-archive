"""Match source-verified English translation links to the Sanskrit reader."""

from collections import Counter, defaultdict
import hashlib
from html import escape
import re

from prose_coordinates import printed_coordinates, verify_uniform_coordinates


REF = re.compile(r"([1-6])-([1-9][0-9]{0,2})-([1-9][0-9]{0,2})([a-d]?)")
SANSKRIT_REF = re.compile(
    r"(?<![\d-])([0-9]{1,3})\s*[-–]\s*([0-9]{1,3})\s*[-–]\s*([0-9]{1,3})"
    r"(?:\s*[-–]\s*([0-9]{1,3}))?(?![\d-])"
)
DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
FUSED_LOCATORS = re.compile(r"(?<=[|।॥])\s*454([0-9]{1,3})(?![0-9])")
ANCHOR = re.compile(r"Verse[0-9]+", re.I)
DIGEST = re.compile(r"[a-f0-9]{64}")
FORMAT_SPACE = re.compile(r"[\t\r\n\f \u00a0]+")

TRANSLATORS = {
    1: "Desiraju Hanumanta Rao",
    2: "K. M. K. Murthy",
    3: "Desiraju Hanumanta Rao",
    4: "Desiraju Hanumanta Rao",
    5: "K. M. K. Murthy, with Sundara contributions credited to Durga Naaga Devi and Vaasudeva Kishore",
    6: "K. M. K. Murthy",
}


def sanskrit_numbers(record, text):
    """Use printed kāṇḍa, sarga, and verse locators, never local block ordinals."""
    book, chapter = record["book"], record["sarga"]
    expected = printed_coordinates(book, chapter, record["source_sha256"]) or (book, chapter)
    ascii_text = text.translate(DIGITS)
    numbers = set()
    for match in SANSKRIT_REF.finditer(ascii_text):
        first, second, start = (int(value) for value in match.groups()[:3])
        end = int(match[4] or start)
        if (first, second) == expected and 0 < start <= end <= start + 75:
            numbers.update(range(start, end + 1))
    if not numbers and (book, chapter) == (4, 54):
        numbers.update(int(match[1]) for match in FUSED_LOCATORS.finditer(ascii_text))
    return numbers


def local_units(record, additions):
    verse_anchor = "verse" if record["status"] == "numbering_verified" else "block"
    sections = [(f"source-paragraph-{item['source_paragraph']}", item["sanskrit"], None)
                for item in additions.get("before", ()) if item["kind"] == "Source verse passage"]
    sections.extend((f"{verse_anchor}-{verse.get('last_number', verse['number'])}",
                     verse["sanskrit"], verse.get("source_anchor"))
                    for verse in record["verses"])
    sections.extend((f"source-paragraph-{item['source_paragraph']}", item["sanskrit"], None)
                    for item in additions.get("after", ()) if item["kind"] == "Source verse passage")
    verify_uniform_coordinates(record["book"], record["sarga"], record["source_sha256"],
                               (text for _, text, _ in sections))
    return [
        (anchor, sanskrit_numbers(record, text), fragment,
         hashlib.sha256(FORMAT_SPACE.sub(" ", text).strip().encode("utf-8")).hexdigest())
        for anchor, text, fragment in sections
    ]


def prepare_links(record, additions, source):
    """Link each original group only when every endpoint has a unique local unit."""
    if source["source_url"] != record["source_url"]:
        raise ValueError("English links use a different source pane than the Sanskrit record")
    if not DIGEST.fullmatch(source["source_sha256"]):
        raise ValueError("English link evidence has no source SHA-256")
    if source["source_sha256"] != record["source_sha256"]:
        raise ValueError("English links use a different source response than the Sanskrit record")

    units = local_units(record, additions)
    by_number = defaultdict(list)
    for position, unit in enumerate(units):
        for number in unit[1]:
            by_number[number].append(position)

    issues = Counter(row["reason"] for row in source.get("issues", ()))
    if source.get("status") not in {"checked", "no_confirmed_group"}:
        issues[f'source_{source["status"]}'] += 1
    groups = []
    seen_references = Counter(tuple(group["refs"]) for group in source["groups"])
    for group in source["groups"]:
        fragment, refs, numbers = group.get("fragment"), group["refs"], group["verse_numbers"]
        endpoints = [REF.fullmatch(endpoint.strip())
                     for ref in refs for endpoint in ref.split("–")]
        if (not isinstance(fragment, str) or not ANCHOR.fullmatch(fragment) or not refs or not numbers
                or not all(ref and tuple(map(int, ref.groups()[:2])) == (record["book"], record["sarga"])
                           for ref in endpoints)
                or sorted(set(numbers)) != numbers
                or not all(isinstance(n, int) and 1 <= n <= 999 for n in numbers)
                or not DIGEST.fullmatch(group["paragraph_sha256"])):
            raise ValueError(f"Invalid English translation locator: {record['book']}.{record['sarga']}")
        covered = set()
        for label in refs:
            limits = label.split("–")
            if len(limits) > 2:
                raise ValueError(f"Invalid verse range: {label}")
            start, end = (int(REF.fullmatch(endpoint)[3]) for endpoint in (limits[0], limits[-1]))
            covered.update(range(start, end + 1))
        if covered != set(numbers):
            raise ValueError(f"Inconsistent verse list: {refs}")
        signature = tuple(refs)
        if seen_references[signature] > 1:
            issues["duplicate_reference_group"] += 1
            continue
        candidates = [by_number[number] for number in numbers]
        if any(not positions for positions in candidates):
            issues["missing_local_reference"] += 1
            continue
        if any(len(positions) != 1 for positions in candidates):
            issues["ambiguous_local_reference"] += 1
            continue
        positions = sorted({positions[0] for positions in candidates})
        if positions != list(range(positions[0], positions[-1] + 1)):
            issues["noncontiguous_local_reference"] += 1
            continue
        # In ordinal source-block chapters, the printed ending of one verse can
        # be followed by the first half of the next. A shared source paragraph
        # proves placement when available. Otherwise a conflicting known source
        # fragment makes the local association uncertain.
        if record["status"] == "source_blocks_verified":
            witnesses = group.get("source_sanskrit_sha256", [])
            has_matching_paragraph = any(units[position][3] in witnesses for position in positions)
            if not has_matching_paragraph and units[positions[-1]][2] != fragment:
                issues["unconfirmed_irregular_block"] += 1
                continue
        groups.append({
            "href": source["source_url"] + "#" + fragment,
            "refs": refs,
            "basis": group["basis"],
            "units": [units[index][0] for index in positions],
        })
    return groups, issues


def translation_panel(groups):
    from critical_reader import inline_panel

    if not groups:
        return ""
    links = []
    translations = []
    chapter_link = ""
    unavailable = any("row" not in group and "dutt_text" not in group for group in groups)
    for group in groups:
        if "row" in group:
            translations.append(inline_panel(group))
            continue
        if "dutt_text" in group:
            labels = ", ".join(group["refs"])
            reference = (group["refs"][0] + "–" + group["refs"][-1].rsplit("-", 1)[1]
                         if len(group["refs"]) > 1 else labels)
            translations.append(
                f'<div class="dutt-inline" data-dutt-refs="{escape(" ".join(group["refs"]), quote=True)}" '
                f'data-dutt-units="{escape(" ".join(group["units"]), quote=True)}">'
                f'<p class="dutt-english-text">{escape(group["dutt_text"])}</p>'
                f'<p class="critical-refs"><a href="{escape(group["href"], quote=True)}" rel="external">'
                f'{escape(group["translator"])} · {escape(reference)} ↗</a> · Historical spelling</p></div>'
            )
            continue
        if "chapter_href" in group:
            chapter_link = (f'<p><a href="{escape(group["chapter_href"], quote=True)}" '
                            'rel="external">Open the original chapter ↗</a></p>')
            continue
        labels = ", ".join(group["refs"])
        url = escape(group["href"], quote=True)
        refs = escape(" ".join(group["refs"]), quote=True)
        basis = escape(group["basis"], quote=True)
        caption = "Source passage" if group["basis"] == "anchored_sanskrit_reference" else "English at ValmikiRamayan.net"
        links.append(f'<li><a href="{url}" rel="external" data-source-refs="{refs}" '
                     f'data-prose-basis="{basis}">{escape(labels)} · {caption} ↗</a></li>')
    original_links = f'<ul role="list">{"".join(links)}</ul>' if links else ""
    label = "English translation unavailable here" if unavailable and not translations else "English translation"
    return ('<div class="verse-translation" lang="en">'
            f'<p class="verse-translation-label">{label}</p>'
            f'{"".join(translations)}{original_links}{chapter_link}</div>')


def pair_units(units, groups):
    """Keep each link once alongside its exact contiguous set of reader blocks."""
    positions = {anchor: index for index, (anchor, _) in enumerate(units)}
    at = defaultdict(list)
    for group in groups:
        at[positions[group["units"][0]]].append(group)

    html = []
    position = 0
    while position < len(units):
        _, text = units[position]
        starts = at.get(position)
        if not starts:
            html.append(text)
            position += 1
            continue
        end = max(positions[group["units"][-1]] for group in starts)
        # A second partial passage can begin within the current passage.
        # Keep the whole run associated, while placing each link at its start.
        nested_starts = [index for index in range(position + 1, end + 1) if index in at]
        if not nested_starts:
            source = "".join(entry for _, entry in units[position:end + 1])
            html.append(paired(source, starts))
            position = end + 1
            continue
        tracks = []
        cursor = position
        while cursor <= end:
            _, source = units[cursor]
            links = at.get(cursor, ())
            tracks.append(paired(source, links) if links else source)
            if links:
                end = max(end, *(positions[group["units"][-1]] for group in links))
            cursor += 1
        html.append(f'<div class="verse-connected-group">{"".join(tracks)}</div>')
        position = cursor
    return "".join(html)


def paired(source, groups):
    return (f'<div class="verse-pair"><div class="verse-pair-source">{source}</div>'
            f'{translation_panel(groups)}</div>')

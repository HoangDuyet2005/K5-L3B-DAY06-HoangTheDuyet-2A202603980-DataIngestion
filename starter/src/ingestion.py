"""Read the manifest-selected PDF pages and normalize them with page/section traceability."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .models import DocumentPage

# pypdf prints many font-encoding warnings for this PDF; extraction is checked via the manifest.
logging.getLogger("pypdf").setLevel(logging.ERROR)

_HEADER_KEY = "poverty,prosperity,andplanetreport2024"  # running header on even pages, spaces removed
_NUMERIC_LINE = re.compile(r"^[\s\d.,%$/()+\-–—−]*$")  # axis ticks, chart values
_SENTENCE_END = re.compile(r"[.?!:;\"”’)]\d{0,2}$")  # allows trailing footnote digits ("poor.5")
_MARKER = re.compile(r"^(FIGURE B?O\.\d|MAP O\.\d|BOX O\.\d|Sources?:|Note:)")
_FIGURE_START = re.compile(r"^(FIGURE B?O\.\d|MAP O\.\d)")
_SOURCE_NOTE = re.compile(r"^(Sources?:|Note:)")
_BOX_START = re.compile(r"^BOX O\.\d")
_INVISIBLE = dict.fromkeys(map(ord, "­​‌‍﻿"), None)
_YET_ARTIFACT = re.compile(r"\bY et\b")


def load_manifest(path: Path) -> dict[str, Any]:
    """Return the single document entry of data/manifest.json."""
    manifest = json.loads(path.read_text(encoding="utf-8"))
    documents = manifest.get("documents", [])
    if len(documents) != 1:
        raise SystemExit(f"Expected exactly one document in {path}, found {len(documents)}.")
    return documents[0]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _unicode_clean(text: str) -> str:
    return unicodedata.normalize("NFKC", text).translate(_INVISIBLE).replace(" ", " ")


def canonical_for_match(text: str) -> str:
    """Normalization used only to compare evidence quotes with chunk text.

    Applies the same Unicode cleanup as ingestion, collapses whitespace (line breaks included)
    and removes a space after a hyphen before a lowercase letter (line-end hyphen joins).
    """
    text = _YET_ARTIFACT.sub("Yet", _unicode_clean(text))
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"-\s+(?=[a-z])", "-", text)


def _join_lines(lines: list[str]) -> str:
    out = lines[0]
    for line in lines[1:]:
        if out.endswith("-") and line[:1].islower():
            out += line  # keep the hyphen: "lower-" + "middle-income"
        else:
            out += " " + line
    return out


def _build_paragraphs(lines: list[str]) -> list[list[str]]:
    """Group lines into paragraphs (no font information is used).

    A line that is short relative to its neighbours ends a paragraph unless the next line
    continues it in lowercase; a sentence-final line followed by a short line starts a new
    block (headings); FIGURE/MAP/BOX/Source/Note lines always start a new block.
    """
    def is_short(i: int) -> bool:
        window = lines[max(0, i - 3): i + 4]
        return len(lines[i]) < 0.8 * max(len(w) for w in window)

    paragraphs: list[list[str]] = [[lines[0]]]
    for i in range(len(lines) - 1):
        current, nxt = lines[i], lines[i + 1]
        ends = bool(_SENTENCE_END.search(current))
        continues_lower = nxt[:1].islower() and not ends
        boundary = (
            _MARKER.match(nxt) is not None
            or (is_short(i) and not continues_lower)
            or (ends and is_short(i + 1) and not nxt[:1].islower())
        )
        if boundary:
            paragraphs.append([nxt])
        else:
            paragraphs[-1].append(nxt)
    return paragraphs


def strip_figure_blocks(paragraphs: list[list[str]]) -> tuple[list[list[str]], list[dict[str, Any]]]:
    """Remove figure/map blocks: from a FIGURE/MAP paragraph through its Source/Note paragraphs.

    Works on paragraphs as lists of lines. Heuristic (no layout information): after the last
    Source/Note paragraph, following paragraphs that start in lowercase are treated as Note
    continuations and removed too. A block without Source/Note stops at a BOX or another
    FIGURE/MAP marker, otherwise it runs to the end of the segment (recorded as
    ended_with_source_note=False for review). BOX prose is kept.
    """
    kept: list[list[str]] = []
    removed: list[dict[str, Any]] = []
    i = 0
    while i < len(paragraphs):
        if not _FIGURE_START.match(paragraphs[i][0]):
            kept.append(paragraphs[i])
            i += 1
            continue
        start, seen_source = i, False
        i += 1
        while i < len(paragraphs):
            first = paragraphs[i][0]
            if _SOURCE_NOTE.match(first):
                seen_source = True
            elif seen_source:
                if not first[:1].islower():
                    break
            elif _BOX_START.match(first) or _FIGURE_START.match(first):
                break
            i += 1
        block = [_join_lines(p) for p in paragraphs[start:i]]
        removed.append({"marker": block[0][:60], "paragraphs": len(block), "chars": sum(len(b) for b in block),
                        "ended_with_source_note": seen_source, "text": "\n\n".join(block)})
    return kept, removed


def normalize_text(text: str, printed_page: int | None = None,
                   strip_header: bool = False) -> tuple[str, dict[str, int], list[dict[str, Any]]]:
    """Normalize Unicode/whitespace, rebuild paragraphs and remove figure/map blocks.

    - NFKC, invisible characters removed, NBSP -> space, "Y et" extraction artifact -> "Yet".
    - Optionally strips the printed page number and running header at the top of a page.
    - Drops lines made only of numbers/symbols (chart axes and values).
    - Paragraphs are built twice (see _build_paragraphs): first to find and remove
      figure/map blocks (returned for audit), then again from the remaining body lines.
    Returns the text (paragraphs joined by "\\n\\n"), counters, and the removed blocks.
    """
    stats: Counter = Counter()
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in _unicode_clean(text).split("\n")]
    if strip_header:
        removed = 0
        while lines and removed < 3:
            first = lines[0]
            key = re.sub(r"\s", "", first).lower()
            if not first:
                lines.pop(0)
            elif (printed_page is not None and first == str(printed_page)) or key in (_HEADER_KEY, "overview"):
                lines.pop(0)
                removed += 1
                stats["header_lines_removed"] += 1
            else:
                break
    kept = []
    for line in lines:
        if not line:
            continue
        if _NUMERIC_LINE.match(line):
            stats["numeric_lines_dropped"] += 1
            continue
        fixed, n = _YET_ARTIFACT.subn("Yet", line)
        stats["yet_artifacts_fixed"] += n
        kept.append(fixed)
    if not kept:
        return "", dict(stats), []
    # Pass 1: paragraphs only to locate and remove figure/map blocks.
    body_paragraphs, removed = strip_figure_blocks(_build_paragraphs(kept))
    body_lines = [line for paragraph in body_paragraphs for line in paragraph]
    if not body_lines:
        return "", dict(stats), removed
    # Pass 2: rebuild paragraphs from body lines only, so figure-note line widths
    # do not make body lines look "short" (false paragraph breaks).
    body = [_join_lines(p) for p in _build_paragraphs(body_lines)]
    stats["paragraphs"] = len(body)
    stats["figure_blocks_removed"] = len(removed)
    stats["figure_chars_removed"] = sum(r["chars"] for r in removed)
    stats["figure_blocks_without_source_note"] = sum(not r["ended_with_source_note"] for r in removed)
    return "\n\n".join(body), dict(stats), removed


def _split_segments(raw: str, row: dict[str, Any], report: dict[str, Any]) -> list[tuple[str, str]]:
    """Return (section, raw_text) segments; mixed pages are cut at the heading anchor."""
    if row["section"] is not None:
        return [(row["section"], raw)]
    spans = row["section_spans"]
    cuts = [0]
    for span in spans[1:]:
        anchor = span["starts_with"]
        if raw.count(anchor) != 1:
            raise SystemExit(f"PDF {row['pdf_page']}: heading anchor {anchor!r} found {raw.count(anchor)} times; "
                             "cannot split sections safely.")
        index = raw.find(anchor)
        if index <= cuts[-1]:
            raise SystemExit(f"PDF {row['pdf_page']}: heading anchor {anchor!r} is out of order.")
        cuts.append(index)
        report["section_splits"].append({"pdf_page": row["pdf_page"], "anchor": anchor, "offset": index,
                                         "manifest_char_start": span["char_start"],
                                         "offset_matches_manifest": index == span["char_start"]})
    cuts.append(len(raw))
    return [(spans[k]["section"], raw[cuts[k]:cuts[k + 1]]) for k in range(len(spans))]


def load_pdf(path: Path, manifest_doc: dict[str, Any]) -> tuple[list[DocumentPage], dict[str, Any]]:
    """Extract manifest pages marked counted_as_text_content=true as section segments.

    Each returned DocumentPage is one (page, section) segment: page = PDF page number,
    metadata carries printed_page, section, segment_index and character counts.
    """
    local = manifest_doc["local_file"]
    actual_hash = sha256_file(path)
    if actual_hash != local["sha256"]:
        raise SystemExit(f"CORPUS_PDF sha256 {actual_hash} != manifest {local['sha256']}; wrong or changed file.")
    reader = PdfReader(str(path))
    if len(reader.pages) != local["total_pdf_pages"]:
        raise SystemExit(f"PDF has {len(reader.pages)} pages; manifest says {local['total_pdf_pages']}.")

    report: dict[str, Any] = {"sha256": actual_hash, "pages_loaded": 0, "segments": 0, "empty_pages": [],
                              "printed_page_mismatches": [], "section_splits": [], "skipped_not_counted": [],
                              "normalization": Counter(), "figure_blocks_removed": []}
    segments: list[DocumentPage] = []
    for row in manifest_doc["pages"]:
        if not row.get("counted_as_text_content", False):
            report["skipped_not_counted"].append(row["pdf_page"])
            continue
        pdf_page, printed = row["pdf_page"], row["printed_page"]
        raw = unicodedata.normalize("NFC", reader.pages[pdf_page - 1].extract_text() or "")
        if not raw.strip():
            report["empty_pages"].append(pdf_page)
            continue
        first_line = next((line.strip() for line in raw.split("\n") if line.strip()), "")
        if first_line != str(printed):
            report["printed_page_mismatches"].append({"pdf_page": pdf_page, "first_line": first_line})
        report["pages_loaded"] += 1
        parts = _split_segments(raw, row, report)
        for index, (section, part) in enumerate(parts):
            text, stats, removed = normalize_text(part, printed, strip_header=(index == 0))
            report["normalization"].update(stats)
            report["figure_blocks_removed"].extend(
                {"pdf_page": pdf_page, "segment_index": index, **block} for block in removed)
            if not text:
                report["empty_pages"].append({"pdf_page": pdf_page, "segment_index": index})
                continue
            segments.append(DocumentPage(
                document_id=manifest_doc["source_id"],
                source=local["filename"],
                page=pdf_page,
                text=text,
                metadata={"printed_page": printed, "section": section, "segment_index": index,
                          "segment_count": len(parts), "source_url": manifest_doc["source_path_or_url"],
                          "raw_char_count": len(part), "normalized_char_count": len(text)},
            ))
    report["segments"] = len(segments)
    report["normalization"] = dict(report["normalization"])
    return segments, report

"""Fixed-size (A) and paragraph/heading-aware (B) chunking within one page segment.

Chunks never cross a page or a section segment, so every chunk has exactly one
pdf_page, printed_page and section. chunk.text == page.text[char_start:char_end].
"""
from __future__ import annotations

import re

from .ingestion import _SENTENCE_END
from .models import Chunk, DocumentPage

_SENTENCE_SPLIT = re.compile(r"(?<=[.?!])\s+(?=[A-Z“\"(\[])")


def _make_chunk(page: DocumentPage, strategy: str, index: int, start: int, end: int,
                extra: dict | None = None) -> Chunk | None:
    text = page.text
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    if start >= end:
        return None
    seg = page.metadata["segment_index"]
    meta = {
        "printed_page": page.metadata["printed_page"],
        "section": page.metadata["section"],
        "segment_index": seg,
        "source_url": page.metadata.get("source_url"),
        "char_start": start,
        "char_end": end,
        "chunk_index": index,
        "strategy": strategy,
        **(extra or {}),
    }
    chunk_id = f"{strategy}:{page.document_id}:p{page.page:03d}s{seg}:c{index:03d}"
    return Chunk(chunk_id, page.document_id, page.source, page.page, text[start:end], meta)


def fixed_size(page: DocumentPage, size: int, overlap: int, strategy: str = "A") -> list[Chunk]:
    """Character windows of `size` with `overlap`, restarted on every page segment."""
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError(f"invalid size/overlap: {size}/{overlap}")
    step, n = size - overlap, len(page.text)
    chunks: list[Chunk] = []
    start = 0
    while start < n:
        end = min(start + size, n)
        chunk = _make_chunk(page, strategy, len(chunks), start, end, {"size": size, "overlap": overlap})
        if chunk:
            chunks.append(chunk)
        if end == n:
            break
        start += step
    return chunks


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    spans, pos = [], 0
    for part in text.split("\n\n"):
        if part.strip():
            spans.append((pos, pos + len(part)))
        pos += len(part) + 2
    return spans


def _split_long(text: str, start: int, end: int, max_size: int) -> list[tuple[int, int]]:
    """Split one oversized paragraph into sentence units; hard-split overlong sentences at spaces.

    Units are returned ungrouped so by_paragraph can merge them with a preceding heading.
    """
    bounds = [start] + [start + m.end() for m in _SENTENCE_SPLIT.finditer(text[start:end])] + [end]
    sentences = [(bounds[k], bounds[k + 1]) for k in range(len(bounds) - 1) if bounds[k] < bounds[k + 1]]
    pieces: list[tuple[int, int]] = []
    for s, e in sentences:
        while e - s > max_size:  # single sentence longer than max_size
            cut = text.rfind(" ", s, s + max_size)
            cut = cut if cut > s else s + max_size
            pieces.append((s, cut))
            s = cut
        pieces.append((s, e))
    return pieces


def _is_heading(text: str) -> bool:
    stripped = text.strip()
    return len(stripped) < 160 and not _SENTENCE_END.search(stripped)


def by_paragraph(page: DocumentPage, max_size: int, strategy: str = "B") -> list[Chunk]:
    """Group consecutive paragraphs up to max_size characters.

    Oversized paragraphs are split into sentence units that are then grouped like paragraphs.
    Heading-like units left at the end of a full chunk (including consecutive headings such as
    "BOX O.2" + box title) move to the next chunk so they stay with the text they introduce.
    """
    if max_size <= 0:
        raise ValueError("max_size must be positive")
    text = page.text
    spans = _paragraph_spans(text)
    heading = [_is_heading(text[s:e]) for s, e in spans]
    units: list[tuple[int, int]] = []
    for k, (s, e) in enumerate(spans):
        first_heading = k
        while first_heading > 0 and heading[first_heading - 1]:
            first_heading -= 1
        # Split into sentences when the paragraph is too long on its own, or when the
        # headings right before it could not fit in the same chunk otherwise.
        headings_wont_fit = first_heading < k and e - spans[first_heading][0] > max_size
        if e - s > max_size or (headings_wont_fit and not heading[k]):
            units.extend(_split_long(text, s, e, max_size))
        else:
            units.append((s, e))
    groups: list[list[tuple[int, int]]] = []
    current: list[tuple[int, int]] = []
    for unit in units:
        if current and unit[1] - current[0][0] > max_size:
            carry: list[tuple[int, int]] = []
            while current and _is_heading(text[current[-1][0]:current[-1][1]]):
                carry.insert(0, current.pop())
            if current:
                groups.append(current)
            current = carry
            if current and unit[1] - current[0][0] > max_size:
                groups.append(current)
                current = []
        current.append(unit)
    if current:
        groups.append(current)
    chunks: list[Chunk] = []
    for group in groups:
        chunk = _make_chunk(page, strategy, len(chunks), group[0][0], group[-1][1],
                            {"max_size": max_size, "paragraph_units": len(group)})
        if chunk:
            chunks.append(chunk)
    return chunks

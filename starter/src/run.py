"""Day 06 pipeline entry point.

Run from starter/:
  python -m src.run inspect             # PDF -> segments -> A/B chunks + diagnostics (no model, no DB)
  python -m src.run ingest              # inspect + embed changed chunks + upsert into pgvector
  python -m src.run ingest --force-reembed
  python -m src.run retrieve --split dev                     # select the strategy on dev
  python -m src.run retrieve --split test --selected-strategy B --criteria "..."   # only after selection is fixed
Outputs go to <repo>/results/<command>_<run_id>/ (RESULTS_DIR overrides).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import platform
import statistics
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .chunking import by_paragraph, fixed_size
from .config import (EXPECTED_DIMENSIONS, FILTERABLE_FIELDS, INDEXED_STRATEGIES, MODEL_ID, STRATEGIES, TOP_K,
                     Settings, load_settings)
from .evaluation import evaluate_query, metrics_markdown, summarize
from .ingestion import canonical_for_match, load_manifest, load_pdf, sha256_file
from .models import Chunk, DocumentPage

MIN_CONTENT_PAGES = 30
COHERENCE_POSITIONS = 10


# ---------------------------------------------------------------- helpers
def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _out_dir(settings: Settings, command: str) -> tuple[str, Path]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = settings.results_dir / f"{command}_{run_id}"
    path.mkdir(parents=True, exist_ok=False)
    return run_id, path


def _write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


def _write_csv(path: Path, header: list[str], rows: list[list[Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _describe(values: list[int]) -> dict[str, Any]:
    if not values:
        return {"count": 0}
    ordered = sorted(values)

    def pct(q: float) -> int:
        return ordered[int(round(q * (len(ordered) - 1)))]

    return {"count": len(ordered), "total": sum(ordered), "min": ordered[0], "p10": pct(0.10),
            "median": statistics.median(ordered), "mean": round(statistics.fmean(ordered), 1),
            "p90": pct(0.90), "max": ordered[-1]}


def _safe_db(url: str | None) -> str | None:
    if not url:
        return None
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.hostname}:{parts.port}{parts.path}"  # no credentials


def load_benchmark(path: Path, manifest_doc: dict[str, Any]) -> list[dict[str, Any]]:
    """Load questions and enforce the BENCHMARK.md minimums before any retrieval."""
    questions = json.loads(path.read_text(encoding="utf-8"))["questions"]
    splits = Counter(q["split"] for q in questions)
    filtered = [q for q in questions if q.get("filter")]
    counted = {r["pdf_page"] for r in manifest_doc["pages"] if r.get("counted_as_text_content")}
    problems = []
    if len(questions) < 20:
        problems.append(f"{len(questions)} questions < 20")
    if splits["dev"] < 15 or splits["test"] < 5:
        problems.append(f"split {dict(splits)} below 15 dev / 5 test")
    if len(filtered) < 3 or not any(q["split"] == "test" for q in filtered):
        problems.append("need >=3 filter questions with >=1 in test")
    if len({q["id"] for q in questions}) != len(questions):
        problems.append("duplicate question ids")
    for q in questions:
        for key in (q.get("filter") or {}):
            if key not in FILTERABLE_FIELDS:
                problems.append(f"{q['id']}: filter key {key!r} not supported")
        if q["gold_page"] not in counted:
            problems.append(f"{q['id']}: gold page {q['gold_page']} not a counted content page")
    if problems:
        raise SystemExit("Benchmark validation failed: " + "; ".join(problems))
    return questions


def build_chunks(segments: list[DocumentPage]) -> dict[str, list[Chunk]]:
    a, b = STRATEGIES["A"], STRATEGIES["B"]
    chunks = {"A": [], "B": []}
    for segment in segments:
        chunks["A"].extend(fixed_size(segment, a["size"], a["overlap"], strategy="A"))
        chunks["B"].extend(by_paragraph(segment, b["max_size"], strategy="B"))
    for strategy, items in chunks.items():
        ids = [c.chunk_id for c in items]
        if len(ids) != len(set(ids)):
            raise SystemExit(f"Duplicate chunk IDs produced for strategy {strategy}.")
    return chunks


def evidence_diagnostics(questions: list[dict[str, Any]], segments: list[DocumentPage],
                         chunks: dict[str, list[Chunk]]) -> list[dict[str, Any]]:
    """Is each evidence quote still present after normalization, and inside one chunk per strategy?

    The normalization check runs for every question (GUIDE §2: evidence must exist after normalization).
    Per-strategy chunk containment is computed for dev only, so tuning the chunkers never looks at
    test outcomes (RULES: no tuning on test). Test rows get status "not_checked_test_split".
    """
    rows = []
    for q in questions:
        quote = canonical_for_match(q["evidence_quote"])
        page_segments = [s for s in segments if s.page == q["gold_page"]]
        in_segment = [s.metadata["segment_index"] for s in page_segments if quote in canonical_for_match(s.text)]
        row = {"question_id": q["id"], "split": q["split"], "gold_page": q["gold_page"],
               "question_section": q["section"], "evidence_in_normalized_page": bool(in_segment),
               "segment_sections": [s.metadata["section"] for s in page_segments
                                    if s.metadata["segment_index"] in in_segment]}
        for strategy, items in chunks.items():
            if q["split"] != "dev":
                row[f"{strategy}_chunks_containing_evidence"] = None
                row[f"{strategy}_status"] = "not_checked_test_split"
                continue
            containing = [c for c in items if c.page == q["gold_page"] and quote in canonical_for_match(c.text)]
            row[f"{strategy}_chunks_containing_evidence"] = [c.chunk_id for c in containing]
            row[f"{strategy}_status"] = ("ok" if containing else
                                         "evidence_split_across_chunks" if in_segment else
                                         "evidence_not_in_normalized_text")
        row["section_matches_segment"] = all(sec == q["section"] for sec in row["segment_sections"]) \
            if row["segment_sections"] else None
        rows.append(row)
    return rows


def chunk_stats(chunks: dict[str, list[Chunk]]) -> dict[str, Any]:
    return {strategy: {"chunks": len(items), "chars": _describe([len(c.text) for c in items]),
                       "by_section": dict(Counter(c.metadata["section"] for c in items))}
            for strategy, items in chunks.items()}


def coherence_template(segments: list[DocumentPage], chunks: dict[str, list[Chunk]], path: Path) -> None:
    """Fixed positions chosen before any score: middle of the first segment of the first 10 pages."""
    firsts = sorted((s for s in segments if s.metadata["segment_index"] == 0), key=lambda s: s.page)
    rows = []
    for number, segment in enumerate(firsts[:COHERENCE_POSITIONS], start=1):
        position = len(segment.text) // 2
        for strategy in ("A", "B", "C"):
            pool = [c for c in chunks[STRATEGIES[strategy]["index"]]
                    if c.page == segment.page and c.metadata["segment_index"] == 0]
            covering = [c for c in pool if c.metadata["char_start"] <= position < c.metadata["char_end"]] or \
                [c for c in pool if c.metadata["char_end"] > position][:1]
            chunk = min(covering, key=lambda c: c.metadata["chunk_index"]) if covering else None
            rows.append([f"pos{number:02d}", strategy, segment.page, segment.metadata["printed_page"], position,
                         chunk.chunk_id if chunk else "", chunk.text if chunk else "",
                         "same chunk as B" if strategy == "C" else "", "", ""])
    _write_csv(path, ["position_id", "strategy", "pdf_page", "printed_page", "position_char", "chunk_id",
                      "chunk_text", "note", "label_0_1_2", "reason"], rows)


def _content_hash(chunk: Chunk, embed_info: dict[str, Any]) -> str:
    payload = {"model": embed_info["model_id"], "revision": embed_info["revision"], "dtype": embed_info["dtype"],
               "document_prompt": embed_info["document_prompt"], "text": chunk.text,
               "metadata": {k: chunk.metadata[k] for k in ("printed_page", "section", "segment_index",
                                                           "char_start", "char_end")}}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def _base_metadata(settings: Settings, run_id: str, command: str, manifest_doc: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": run_id, "command": command, "started_at": _now(),
        "python": sys.version.split()[0], "platform": platform.platform(),
        "corpus": {"source_id": manifest_doc["source_id"], "file": manifest_doc["local_file"]["filename"],
                   "expected_sha256": manifest_doc["local_file"]["sha256"]},
        "manifest_sha256": sha256_file(settings.manifest_path),
        "benchmark_sha256": sha256_file(settings.benchmark_path),
        "strategies": STRATEGIES, "top_k": TOP_K, "database": _safe_db(settings.database_url),
        "cost": {"usd": 0.0, "note": "local model inference and local PostgreSQL; no paid API"},
    }


def _prepare(settings: Settings, command: str):
    manifest_doc = load_manifest(settings.manifest_path)
    questions = load_benchmark(settings.benchmark_path, manifest_doc)
    run_id, out = _out_dir(settings, command)
    meta = _base_metadata(settings, run_id, command, manifest_doc)
    return manifest_doc, questions, run_id, out, meta


def _load_and_chunk(settings: Settings, manifest_doc, questions, out: Path, meta: dict[str, Any]):
    timings = {}
    t0 = time.perf_counter()
    segments, extract_report = load_pdf(settings.require_pdf(), manifest_doc)
    timings["extract_normalize_s"] = round(time.perf_counter() - t0, 3)
    if extract_report["pages_loaded"] < MIN_CONTENT_PAGES:
        raise SystemExit(f"Only {extract_report['pages_loaded']} content pages loaded (< {MIN_CONTENT_PAGES}).")
    t0 = time.perf_counter()
    chunks = build_chunks(segments)
    timings["chunking_s"] = round(time.perf_counter() - t0, 3)
    diagnostics = evidence_diagnostics(questions, segments, chunks)
    figure_blocks = extract_report.pop("figure_blocks_removed")
    _write_jsonl(out / "figure_blocks_removed.jsonl", figure_blocks)  # audit what left the corpus
    extract_report["figure_blocks_removed_count"] = len(figure_blocks)
    _write_jsonl(out / "segments.jsonl", [{"document_id": s.document_id, "source": s.source, "pdf_page": s.page,
                                           "text": s.text, **s.metadata} for s in segments])
    for strategy, items in chunks.items():
        _write_jsonl(out / f"chunks_{strategy}.jsonl", [{"chunk_id": c.chunk_id, "document_id": c.document_id,
                                                         "source": c.source, "pdf_page": c.page, "text": c.text,
                                                         **c.metadata} for c in items])
    _write_jsonl(out / "evidence_diagnostics.jsonl", diagnostics)
    coherence_template(segments, chunks, out / "coherence_labels_template.csv")
    meta.update({"extraction": extract_report, "chunk_stats": chunk_stats(chunks), "timings": timings,
                 "evidence_diagnostics_summary": {
                     s: dict(Counter(d[f"{s}_status"] for d in diagnostics)) for s in chunks}})
    return segments, chunks


# ---------------------------------------------------------------- commands
def cmd_inspect(settings: Settings) -> Path:
    manifest_doc, questions, run_id, out, meta = _prepare(settings, "inspect")
    _load_and_chunk(settings, manifest_doc, questions, out, meta)
    meta["finished_at"] = _now()
    _write_json(out / "run_metadata.json", meta)
    return out


def cmd_ingest(settings: Settings, force_reembed: bool) -> Path:
    from .embeddings import EmbeddingGemmaEmbedder
    from .store import PgVectorStore

    database_url = settings.require_database()
    manifest_doc, questions, run_id, out, meta = _prepare(settings, "ingest")
    total_start = time.perf_counter()
    _, chunks = _load_and_chunk(settings, manifest_doc, questions, out, meta)

    t0 = time.perf_counter()
    embedder = EmbeddingGemmaEmbedder(settings)
    meta["timings"]["model_load_s"] = round(time.perf_counter() - t0, 3)
    info = embedder.info()
    meta["embedding"] = info
    store = PgVectorStore(database_url, embedder.dimensions)
    try:
        store.create_schema()
        meta["pgvector_version"] = store.pgvector_version()
        meta["index"] = {"search": "exact (sequential scan, no ANN index)", "distance": "cosine (<=>)"}
        document_id = manifest_doc["source_id"]
        per_strategy = {}
        for strategy in INDEXED_STRATEGIES:
            items = chunks[strategy]
            hashes = {c.chunk_id: _content_hash(c, info) for c in items}
            existing = store.existing_hashes(strategy, document_id)
            changed = [c for c in items if force_reembed or existing.get(c.chunk_id) != hashes[c.chunk_id]]
            t0 = time.perf_counter()
            vectors = embedder.embed_documents([c.text for c in changed])
            embed_s = time.perf_counter() - t0
            t0 = time.perf_counter()
            result = store.sync(strategy, document_id, [c.chunk_id for c in items], changed, vectors,
                                hashes, MODEL_ID)
            write_s = time.perf_counter() - t0
            tokens = embedder.count_tokens([c.text for c in items])
            max_len = info["max_seq_length"]
            per_strategy[strategy] = {
                "chunks": len(items), "embedded": len(changed), "reused_unchanged": len(items) - len(changed),
                **result, "embed_s": round(embed_s, 3), "db_write_s": round(write_s, 3),
                "tokens_with_prompt": _describe(tokens),
                "chunks_over_max_seq_length": sum(t > max_len for t in tokens) if max_len else None,
            }
        meta["ingest"] = per_strategy
        meta["store_counts_after"] = store.counts()
    finally:
        store.close()
    meta["timings"]["total_ingest_s"] = round(time.perf_counter() - total_start, 3)
    meta["finished_at"] = _now()
    _write_json(out / "run_metadata.json", meta)
    return out


def _fingerprint(meta: dict[str, Any]) -> str:
    """What must be identical between the dev run used for selection and the test run."""
    keys = {"strategies": meta["strategies"], "top_k": meta["top_k"], "model": MODEL_ID,
            "manifest_sha256": meta["manifest_sha256"], "benchmark_sha256": meta["benchmark_sha256"]}
    return hashlib.sha256(json.dumps(keys, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _previous_runs(settings: Settings, prefix: str) -> list[dict[str, Any]]:
    runs = []
    for path in sorted(settings.results_dir.glob(f"{prefix}_*/run_metadata.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        runs.append({"run_id": data.get("run_id"), "fingerprint": data.get("config_fingerprint"),
                     "selected_strategy": data.get("selection", {}).get("selected_strategy")})
    return runs


def cmd_retrieve(settings: Settings, split: str, selected: str | None, criteria: str | None) -> Path:
    """Dev first (selection), then test once the strategy and criteria are fixed (README/RUBRIC)."""
    from .embeddings import EmbeddingGemmaEmbedder
    from .store import PgVectorStore

    database_url = settings.require_database()
    if split == "test" and (not selected or not criteria):
        raise SystemExit("Test run needs --selected-strategy and --criteria, fixed from dev results first.")
    manifest_doc, all_questions, run_id, out, meta = _prepare(settings, f"retrieve_{split}")
    questions = [q for q in all_questions if q["split"] == split]
    meta["split"] = split
    meta["config_fingerprint"] = _fingerprint(meta)
    if split == "test":
        dev_runs = [r for r in _previous_runs(settings, "retrieve_dev") if r["fingerprint"] == meta["config_fingerprint"]]
        if not dev_runs:
            raise SystemExit("No dev retrieval run with the same configuration; run `retrieve --split dev` first.")
        earlier_tests = _previous_runs(settings, "retrieve_test")
        meta["selection"] = {"selected_strategy": selected, "criteria": criteria,
                             "dev_run_ids": [r["run_id"] for r in dev_runs],
                             "earlier_test_runs": earlier_tests}
        if earlier_tests:
            print(f"WARNING: test was already run {len(earlier_tests)} time(s); recorded in run_metadata.json. "
                  "Per RULES.md, a re-run after changes is not an independent test.")
    t0 = time.perf_counter()
    embedder = EmbeddingGemmaEmbedder(settings)
    meta["timings"] = {"model_load_s": round(time.perf_counter() - t0, 3)}
    meta["embedding"] = embedder.info()
    store = PgVectorStore(database_url, embedder.dimensions)
    traces = []
    try:
        store.create_schema()
        meta["pgvector_version"] = store.pgvector_version()
        counts = store.counts()
        meta["store_counts"] = counts
        for index in INDEXED_STRATEGIES:
            rows = [c for c in counts if c["strategy"] == index]
            if not rows:
                raise SystemExit(f"No stored chunks for strategy {index}; run `python -m src.run ingest` first.")
            if any(c["embedding_model"] != MODEL_ID for c in rows):
                raise SystemExit(f"Stored chunks for {index} use another model: {rows}")
        t0 = time.perf_counter()
        for q in questions:
            query_vector = embedder.embed_query(q["question"])  # question text only; no gold, no filter
            for strategy, cfg in STRATEGIES.items():
                filters = q["filter"] if cfg["use_filter"] and q.get("filter") else None
                hits = store.search(cfg["index"], query_vector, TOP_K, filters)
                traces.append(evaluate_query(q, hits, strategy, cfg["index"], filters))
        meta["timings"]["retrieval_s"] = round(time.perf_counter() - t0, 3)
    finally:
        store.close()
    summary = summarize(traces)
    _write_jsonl(out / "traces.jsonl", traces)
    _write_json(out / "metrics.json", summary)
    (out / "metrics.md").write_text(
        f"# Automatic retrieval metrics ({run_id})\n\nModel `{MODEL_ID}`, {EXPECTED_DIMENSIONS}-d, top-{TOP_K}, "
        "exact cosine search. Hit = gold source + PDF page + full evidence quote inside the chunk. "
        "Human coherence / metadata / grounding labels are separate (see *_template.csv).\n\n"
        + metrics_markdown(summary), encoding="utf-8")
    meta["finished_at"] = _now()
    _write_json(out / "run_metadata.json", meta)
    if split != "test":
        return out
    test = traces
    _write_csv(out / "metadata_labels_template.csv",
               ["strategy", "question_id", "rank", "chunk_id", "source", "pdf_page", "printed_page", "section",
                "question_filter", "complete_and_correct_yes_no", "error_note"],
               [[t["strategy"], t["question_id"], h["rank"], h["chunk_id"], h["source"], h["pdf_page"],
                 h["printed_page"], h["section"], json.dumps(t["question_filter"]), "", ""]
                for t in test for h in t["hits"]])
    _write_csv(out / "grounding_labels_template.csv",
               ["strategy", "question_id", "question", "expected_answer", "top3_chunk_ids", "top3_texts",
                "label_0_1_2", "reason"],
               [[t["strategy"], t["question_id"], t["question"], t["expected_answer"],
                 " | ".join(h["chunk_id"] for h in t["hits"]),
                 "\n---\n".join(h["text"] for h in t["hits"]), "", ""] for t in test])
    return out


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m src.run", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("inspect", help="extract, normalize and chunk only (no model, no database)")
    ingest = sub.add_parser("ingest", help="embed and upsert chunks for strategies A and B")
    ingest.add_argument("--force-reembed", action="store_true", help="re-embed even unchanged chunks")
    retrieve = sub.add_parser("retrieve", help="run top-3 retrieval for A/B/C on one split and compute metrics")
    retrieve.add_argument("--split", choices=("dev", "test"), required=True)
    retrieve.add_argument("--selected-strategy", choices=tuple(STRATEGIES), help="required for --split test")
    retrieve.add_argument("--criteria", help="selection criteria fixed before test (required for --split test)")
    args = parser.parse_args()
    settings = load_settings()
    if args.command == "inspect":
        out = cmd_inspect(settings)
    elif args.command == "ingest":
        out = cmd_ingest(settings, args.force_reembed)
    else:
        out = cmd_retrieve(settings, args.split, args.selected_strategy, args.criteria)
    print(f"Done. Outputs: {out}")


if __name__ == "__main__":
    main()

"""Automatic retrieval metrics and per-query traces.

Only Hit@1 / Evidence Hit@3 (and diagnostics) are computed here. Human labels for
coherence, metadata usefulness and grounding are never inferred from string matching;
run.py only writes blank templates for them.
"""
from __future__ import annotations

from typing import Any

from .ingestion import canonical_for_match

SPLITS = ("dev", "test")


def gold_candidates(question: dict[str, Any]) -> list[dict[str, Any]]:
    """Main gold evidence plus any documented alternatives (`alternative_evidence` list)."""
    main = {"gold_source_id": question["gold_source_id"], "gold_page": question["gold_page"],
            "evidence_quote": question["evidence_quote"]}
    return [main] + list(question.get("alternative_evidence") or [])


def is_evidence_hit(hit: dict[str, Any], candidate: dict[str, Any]) -> bool:
    """Gold source and PDF page match, and the chunk contains the whole evidence quote."""
    return (hit["document_id"] == candidate["gold_source_id"]
            and hit["pdf_page"] == candidate["gold_page"]
            and canonical_for_match(candidate["evidence_quote"]) in canonical_for_match(hit["text"]))


def evaluate_query(question: dict[str, Any], hits: list[dict[str, Any]], strategy: str,
                   index: str, filters: dict[str, Any] | None) -> dict[str, Any]:
    candidates = gold_candidates(question)
    ranked = []
    for rank, hit in enumerate(hits, start=1):
        matched = [i for i, c in enumerate(candidates) if is_evidence_hit(hit, c)]
        page_match = any(hit["document_id"] == c["gold_source_id"] and hit["pdf_page"] == c["gold_page"]
                         for c in candidates)
        ranked.append({**hit, "rank": rank, "evidence_hit": bool(matched),
                       "matched_candidates": matched, "gold_page_match": page_match})
    question_filter = question.get("filter")
    filter_compliant = None
    if question_filter:
        filter_compliant = all(all(h.get(k) == v for k, v in question_filter.items()) for h in ranked)
    return {
        "strategy": strategy,
        "index": index,
        "question_id": question["id"],
        "split": question["split"],
        "type": question.get("type"),
        "question": question["question"],
        "expected_answer": question["expected_answer"],
        "gold": candidates,
        "section": question.get("section"),
        "question_filter": question_filter,
        "filter_applied": filters,
        "n_hits": len(ranked),
        "hits": ranked,
        "hit_at_1": bool(ranked) and ranked[0]["evidence_hit"],
        "evidence_hit_at_3": any(h["evidence_hit"] for h in ranked[:3]),
        "page_hit_at_3": any(h["gold_page_match"] for h in ranked[:3]),
        "filter_compliant_top3": filter_compliant,
    }


def _ratio(n: int, total: int) -> dict[str, Any]:
    return {"n": n, "N": total, "rate": (n / total) if total else None}


def summarize(traces: list[dict[str, Any]]) -> dict[str, Any]:
    """Hit@1 and Evidence Hit@3 per strategy and split, reported as n/N."""
    summary: dict[str, Any] = {}
    for strategy in sorted({t["strategy"] for t in traces}):
        summary[strategy] = {}
        for split in SPLITS:
            rows = [t for t in traces if t["strategy"] == strategy and t["split"] == split]
            if not rows:
                continue  # dev and test are run separately
            filtered = [t for t in rows if t["question_filter"]]
            summary[strategy][split] = {
                "questions": len(rows),
                "hit_at_1": _ratio(sum(t["hit_at_1"] for t in rows), len(rows)),
                "evidence_hit_at_3": _ratio(sum(t["evidence_hit_at_3"] for t in rows), len(rows)),
                "page_hit_at_3_diagnostic": _ratio(sum(t["page_hit_at_3"] for t in rows), len(rows)),
                "filter_compliance_top3": (_ratio(sum(bool(t["filter_compliant_top3"]) for t in filtered),
                                                  len(filtered)) if filtered else "N/A"),
            }
    return summary


def metrics_markdown(summary: dict[str, Any]) -> str:
    def fmt(cell: Any) -> str:
        return "N/A" if cell == "N/A" else f"{cell['n']}/{cell['N']}"

    lines = ["| Strategy | Split | Hit@1 | Evidence Hit@3 | Page Hit@3 (diagnostic) | Filter compliance top-3 |",
             "|---|---|---|---|---|---|"]
    for strategy, by_split in summary.items():
        for split, m in by_split.items():
            lines.append(f"| {strategy} | {split} | {fmt(m['hit_at_1'])} | {fmt(m['evidence_hit_at_3'])} | "
                         f"{fmt(m['page_hit_at_3_diagnostic'])} | {fmt(m['filter_compliance_top3'])} |")
    return "\n".join(lines) + "\n"

"""Summarize the manual audit labels in results/labels/ (coherence, metadata, grounding).

Usage (from the repo root):
  starter/.venv/Scripts/python.exe -I starter/scripts/summarize_labels.py results/labels
Writes results/labels/labels_summary.json and prints a Markdown table.
"""
import csv
import json
import sys
from pathlib import Path

folder = Path(sys.argv[1] if len(sys.argv) > 1 else "results/labels")


def load(name: str) -> list[dict]:
    with open(folder / name, encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def scale(rows: list[dict], strategy: str) -> dict:
    labels = [int(r["label_0_1_2"]) for r in rows if r["strategy"] == strategy and r["label_0_1_2"] != ""]
    return {"n": len(labels), "count_0": labels.count(0), "count_1": labels.count(1), "count_2": labels.count(2),
            "mean_of_2": round(sum(labels) / len(labels), 2) if labels else None}


coherence, metadata, grounding = load("coherence_labels.csv"), load("metadata_labels.csv"), load("grounding_labels.csv")
summary = {}
for s in ("A", "B", "C"):
    meta_rows = [r for r in metadata if r["strategy"] == s]
    filter_qs = {}
    for r in meta_rows:
        qf = json.loads(r["question_filter"]) if r["question_filter"] not in ("", "null") else None
        if qf:
            filter_qs.setdefault(r["question_id"], []).append(r["section"] == qf["section"])
    summary[s] = {
        "coherence": scale(coherence, s),
        "metadata_complete_correct": f"{sum(r['complete_and_correct_yes_no'] == 'yes' for r in meta_rows)}/{len(meta_rows)}",
        "filter_compliance_top3": f"{sum(all(v) for v in filter_qs.values())}/{len(filter_qs)}" if filter_qs else "N/A",
        "grounding": scale(grounding, s),
    }
reviewed = sum(1 for rows in (coherence, metadata, grounding) for r in rows if r.get("author_review", "").strip())
summary["rows_reviewed_by_author"] = f"{reviewed}/{len(coherence) + len(metadata) + len(grounding)}"
(folder / "labels_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

print("| Strategy | Coherence trung bình /2 (n) | Metadata đủ và đúng (n/N) | Filter tuân thủ (n/N) | Grounding 0/1/2 và trung bình /2 |")
print("|---|---|---|---|---|")
for s in ("A", "B", "C"):
    c, g = summary[s]["coherence"], summary[s]["grounding"]
    print(f"| {s} | {c['mean_of_2']} ({c['n']}) | {summary[s]['metadata_complete_correct']} | "
          f"{summary[s]['filter_compliance_top3']} | {g['count_0']}/{g['count_1']}/{g['count_2']}, {g['mean_of_2']} |")
print("Rows reviewed by author:", summary["rows_reviewed_by_author"])

"""Independent check of top-3 metadata on the test run against the raw PDF and the manifest.

Uses raw pypdf text (not the pipeline's normalize_text) and compares alphanumeric-only strings,
so whitespace / hyphenation / header removal do not matter.

Usage (from the repo root; run with -I so nothing in the current folder shadows the stdlib):
  starter/.venv/Scripts/python.exe -I starter/scripts/verify_metadata.py "<CORPUS_PDF>" data/manifest.json \
      results/retrieve_test_<run_id>/traces.jsonl results/labels/metadata_check.json

It supports the metadata labels in results/labels/metadata_labels.csv; the labels themselves were
reviewed by the author (see labeled_by / author_review columns).
"""
import json
import re
import sys
import unicodedata

from pypdf import PdfReader

pdf_path, manifest_path, traces_path = sys.argv[1:4]
manifest = json.load(open(manifest_path, encoding="utf-8"))
manifest = manifest["documents"][0] if "documents" in manifest else manifest
pages = {p["pdf_page"]: p for p in manifest["pages"]}
filename = manifest["local_file"]["filename"]
reader = PdfReader(pdf_path)


def alnum(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).lower()
    return re.sub(r"[^0-9a-z]", "", s)


raw_cache = {}


def raw_page(n: int) -> str:
    if n not in raw_cache:
        raw_cache[n] = reader.pages[n - 1].extract_text() or ""
    return raw_cache[n]


def windows_found(chunk: str, page_text: str, size: int = 30) -> float:
    c, p = alnum(chunk), alnum(page_text)
    if len(c) <= size:
        return 1.0 if c in p else 0.0
    starts = range(0, len(c) - size + 1, size)
    found = sum(1 for i in starts if c[i:i + size] in p)
    return found / len(starts)


out = []
for line in open(traces_path, encoding="utf-8"):
    r = json.loads(line)
    for h in r["hits"]:
        pdf_page = int(h["pdf_page"])
        man = pages.get(pdf_page)
        problems = []
        for field in ("source", "pdf_page", "printed_page", "section", "document_id"):
            if h.get(field) in (None, "", "None"):
                problems.append(f"missing {field}")
        if h["source"] != filename:
            problems.append("source != manifest filename")
        if man is None or not man.get("counted_as_text_content"):
            problems.append("pdf_page not a counted manifest page")
        else:
            if int(h["printed_page"]) != man["printed_page"]:
                problems.append(f"printed_page {h['printed_page']} != manifest {man['printed_page']}")
            if man.get("section") is not None:
                if h["section"] != man["section"]:
                    problems.append(f"section {h['section']} != manifest {man['section']}")
            else:
                # mixed page: decide by where the chunk text sits relative to the span anchor
                anchor = next(s["starts_with"] for s in man["section_spans"] if "starts_with" in s)
                raw = alnum(raw_page(pdf_page))
                pos_anchor = raw.find(alnum(anchor))
                pos_chunk = raw.find(alnum(h["text"])[:40])
                expected = man["section_spans"][1]["section"] if pos_chunk >= pos_anchor else man["section_spans"][0]["section"]
                if pos_anchor < 0 or pos_chunk < 0:
                    problems.append("could not locate chunk/anchor on mixed page")
                elif h["section"] != expected:
                    problems.append(f"section {h['section']} != span {expected}")
        frac = windows_found(h["text"], raw_page(pdf_page))
        if frac < 0.95:
            problems.append(f"only {frac:.0%} of chunk text found on PDF page {pdf_page}")
        out.append({"strategy": r["strategy"], "question_id": r["question_id"], "rank": int(h["rank"]),
                    "chunk_id": h["chunk_id"], "text_found_on_page": round(frac, 3),
                    "question_filter": r["question_filter"], "section": h["section"], "problems": problems})

json.dump(out, open(sys.argv[4], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
bad = [o for o in out if o["problems"]]
print("checked", len(out), "records; with problems:", len(bad))
for o in out:
    print(o["strategy"], o["question_id"], o["rank"], o["chunk_id"], o["text_found_on_page"], o["problems"])

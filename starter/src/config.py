"""Explicit, fixed experiment configuration plus environment settings.

Everything that defines a strategy lives here so A/B/C differ only where intended.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

STARTER_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = STARTER_DIR.parent
load_dotenv(STARTER_DIR / ".env")

# Fixed embedding model for every strategy (do not change between A/B/C).
MODEL_ID = "google/embeddinggemma-2"
EXPECTED_DIMENSIONS = 768
# Prompt names documented on the model card for Sentence Transformers `prompt_name`.
QUERY_PROMPT_NAME = "SearchQuery"
DOCUMENT_PROMPT_NAME = "Document"
ALLOWED_DTYPES = ("float32", "bfloat16")  # model card: do not use float16

TOP_K = 3
TABLE_NAME = "day6_chunks"

# Strategy definitions. C reuses the B index (identical chunks and vectors) and only adds
# a section filter for questions whose benchmark entry has a non-null `filter`.
STRATEGIES: dict[str, dict] = {
    "A": {"chunking": "fixed_size", "size": 500, "overlap": 50, "index": "A", "use_filter": False},
    "B": {"chunking": "by_paragraph", "max_size": 800, "index": "B", "use_filter": False},
    "C": {"chunking": "by_paragraph", "max_size": 800, "index": "B", "use_filter": True},
}
INDEXED_STRATEGIES = ("A", "B")  # strategies that own stored chunks
FILTERABLE_FIELDS = {"section": "section", "document_id": "document_id"}  # filter key -> column


@dataclass(frozen=True)
class Settings:
    database_url: str | None
    corpus_pdf: Path | None
    manifest_path: Path
    benchmark_path: Path
    results_dir: Path
    device: str | None
    dtype: str
    batch_size: int
    revision: str | None

    def require_database(self) -> str:
        if not self.database_url:
            raise SystemExit("DATABASE_URL missing: copy starter/.env.example to starter/.env and fill it.")
        return self.database_url

    def require_pdf(self) -> Path:
        if not self.corpus_pdf:
            raise SystemExit("CORPUS_PDF missing: set it in starter/.env to the local PDF path.")
        if not self.corpus_pdf.is_file():
            raise SystemExit(f"CORPUS_PDF does not point to a file: {self.corpus_pdf}")
        return self.corpus_pdf


def _optional(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def load_settings() -> Settings:
    configured_model = _optional("EMBEDDING_MODEL")
    if configured_model and configured_model != MODEL_ID:
        raise SystemExit(f"EMBEDDING_MODEL={configured_model!r} but this lab is fixed to {MODEL_ID!r}.")
    dtype = (_optional("EMBEDDING_DTYPE") or "float32").lower()
    if dtype not in ALLOWED_DTYPES:
        raise SystemExit(f"EMBEDDING_DTYPE={dtype!r} not allowed; use one of {ALLOWED_DTYPES} (float16 is unsupported).")
    pdf = _optional("CORPUS_PDF")
    return Settings(
        database_url=_optional("DATABASE_URL"),
        corpus_pdf=Path(pdf).expanduser() if pdf else None,
        manifest_path=Path(_optional("MANIFEST_PATH") or REPO_DIR / "data" / "manifest.json"),
        benchmark_path=Path(_optional("BENCHMARK_PATH") or REPO_DIR / "benchmark" / "questions.json"),
        results_dir=Path(_optional("RESULTS_DIR") or REPO_DIR / "results"),  # SUBMISSION.md: results/ at repo root
        device=_optional("EMBEDDING_DEVICE"),
        dtype=dtype,
        batch_size=int(_optional("EMBEDDING_BATCH_SIZE") or 8),
        revision=_optional("EMBEDDING_REVISION"),
    )

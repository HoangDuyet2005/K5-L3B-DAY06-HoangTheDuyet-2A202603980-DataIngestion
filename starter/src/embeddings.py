"""Local embeddings with google/embeddinggemma-2 via Sentence Transformers.

Query and document vectors use the prompt names documented on the model card
("SearchQuery" and "Document"). Failures raise; there is no mock/random fallback.
"""
from __future__ import annotations

import importlib.metadata
from typing import Any, Protocol

import numpy as np

from .config import DOCUMENT_PROMPT_NAME, EXPECTED_DIMENSIONS, MODEL_ID, QUERY_PROMPT_NAME, Settings


class Embedder(Protocol):
    model_name: str
    dimensions: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in the same order."""
        ...

    def embed_query(self, question: str) -> list[float]:
        """Return a query vector compatible with the stored document vectors."""
        ...


def package_versions() -> dict[str, str | None]:
    versions = {}
    for name in ("sentence-transformers", "transformers", "torch", "torchvision", "pillow", "huggingface-hub",
                 "numpy", "psycopg", "pypdf", "python-dotenv"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


class EmbeddingGemmaEmbedder:
    """Loads the model once; validates prompts, dimensions and finite, unit-norm outputs."""

    def __init__(self, settings: Settings) -> None:
        import torch
        from sentence_transformers import SentenceTransformer

        requested = {"float32": torch.float32, "bfloat16": torch.bfloat16}[settings.dtype]
        # Load weights in the configured dtype explicitly; without this the model loads in
        # its config default (bfloat16), which would not match the recorded configuration.
        kwargs: dict[str, Any] = {"model_kwargs": {"dtype": requested}}
        if settings.device:
            kwargs["device"] = settings.device
        if settings.revision:
            kwargs["revision"] = settings.revision
        self.model = SentenceTransformer(MODEL_ID, **kwargs)
        actual = next(self.model.parameters()).dtype
        if actual != requested:
            raise RuntimeError(f"Model weights loaded as {actual}, but EMBEDDING_DTYPE={settings.dtype}.")
        self.model_name = MODEL_ID
        self.revision = settings.revision
        self.dtype = str(actual).replace("torch.", "")
        self.batch_size = settings.batch_size

        prompts = dict(getattr(self.model, "prompts", None) or {})
        missing = [name for name in (QUERY_PROMPT_NAME, DOCUMENT_PROMPT_NAME) if name not in prompts]
        if missing:
            raise RuntimeError(f"{MODEL_ID} prompts {sorted(prompts)} do not include {missing}; "
                               "check the model card before changing the prompt configuration.")
        self.query_prompt = prompts[QUERY_PROMPT_NAME]
        self.document_prompt = prompts[DOCUMENT_PROMPT_NAME]

        get_dim = getattr(self.model, "get_embedding_dimension", None) or \
            getattr(self.model, "get_sentence_embedding_dimension")
        reported = get_dim()
        probe = self._encode(["dimension probe"], DOCUMENT_PROMPT_NAME)
        if reported != EXPECTED_DIMENSIONS or probe.shape[1] != EXPECTED_DIMENSIONS:
            raise RuntimeError(f"Expected {EXPECTED_DIMENSIONS} dimensions; model reports {reported}, "
                               f"probe vector has {probe.shape[1]}.")
        self.dimensions = int(probe.shape[1])

    def _encode(self, texts: list[str], prompt_name: str) -> np.ndarray:
        tensor = self.model.encode(texts, prompt_name=prompt_name, batch_size=self.batch_size,
                                   normalize_embeddings=True, convert_to_tensor=True, show_progress_bar=False)
        array = tensor.float().cpu().numpy()
        if array.ndim != 2 or array.shape[0] != len(texts):
            raise RuntimeError(f"Unexpected embedding shape {array.shape} for {len(texts)} texts.")
        if not np.isfinite(array).all():
            raise RuntimeError("Embedding contains NaN/inf; check dtype (float16 is unsupported).")
        norms = np.linalg.norm(array, axis=1)
        if not np.allclose(norms, 1.0, atol=1e-2):
            raise RuntimeError(f"Embeddings are not unit-normalized (norm range {norms.min():.4f}-{norms.max():.4f}).")
        return array

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        return self._encode(texts, DOCUMENT_PROMPT_NAME).tolist()

    def embed_query(self, question: str) -> list[float]:
        return self._encode([question], QUERY_PROMPT_NAME)[0].tolist()

    def count_tokens(self, texts: list[str]) -> list[int]:
        """Token count of each document text including the document prompt."""
        tokenizer = self.model.tokenizer
        return [len(tokenizer(self.document_prompt + text)["input_ids"]) for text in texts]

    def info(self) -> dict[str, Any]:
        return {
            "model_id": self.model_name,
            "revision": self.revision or "unpinned (latest at download time)",
            "dimensions": self.dimensions,
            "expected_dimensions": EXPECTED_DIMENSIONS,
            "device": str(self.model.device),
            "dtype": self.dtype,
            "normalize_embeddings": True,
            "query_prompt_name": QUERY_PROMPT_NAME,
            "query_prompt": self.query_prompt,
            "document_prompt_name": DOCUMENT_PROMPT_NAME,
            "document_prompt": self.document_prompt,
            "max_seq_length": getattr(self.model, "max_seq_length", None),
            "batch_size": self.batch_size,
            "packages": package_versions(),
        }

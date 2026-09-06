"""
Optional embeddings retrieval over a committed numpy file, brute-force cosine.

Off by default. It exists to be measured against the hybrid mode in the
retrieval evaluation, and each query costs one embedding call, which is why
it is not the default on a free-tier key.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from dubizzle_assistant.config import get_settings


class RetrievalUnavailableError(RuntimeError):
    """The requested retrieval mode cannot run here, for example no embeddings file or no embedder."""


_cache: dict[str, Any] = {}


def available(path: Path | None = None) -> bool:
    p = path or get_settings().embeddings_path
    return p.exists() and p.with_suffix(".ids.json").exists()


def load(path: Path | None = None) -> tuple[list[str], np.ndarray]:
    p = path or get_settings().embeddings_path
    key = str(p)
    if key not in _cache:
        ids = json.loads(p.with_suffix(".ids.json").read_text(encoding="utf-8"))
        matrix = np.load(p)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        matrix = matrix / np.where(norms == 0, 1, norms)
        _cache[key] = (ids, matrix)
    return _cache[key]


def rank_by_similarity(
    query_text: str, embedder: Callable[[str], list[float]] | None, path: Path | None = None
) -> dict[str, float]:
    if embedder is None:
        raise RetrievalUnavailableError(
            "embeddings mode needs an embedder; the LLM layer provides one"
        )
    ids, matrix = load(path)
    q = np.asarray(embedder(query_text), dtype=np.float32)
    q = q / (np.linalg.norm(q) or 1.0)
    sims = matrix @ q
    return {i: float(s) for i, s in zip(ids, sims, strict=True)}


def save(ids: list[str], vectors: list[list[float]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.save(path, np.asarray(vectors, dtype=np.float32))
    path.with_suffix(".ids.json").write_text(json.dumps(ids), encoding="utf-8")
    _cache.pop(str(path), None)

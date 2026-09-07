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


def _sidecars(p: Path) -> tuple[Path, Path]:
    return p.with_suffix(".ids.json"), p.with_suffix(".meta.json")


def available(
    path: Path | None = None, *, model: str | None = None, ids: list[str] | None = None
) -> tuple[bool, str]:
    """Whether the stored matrix can answer for this model and this inventory.

    Existence alone is not enough. A matrix built by another model scores every listing
    against the wrong geometry, and one built before the inventory changed scores the new
    ids at zero, and both look like a working search returning bad results.
    """
    p = path or get_settings().embeddings_path
    ids_path, meta_path = _sidecars(p)
    if not p.exists() or not ids_path.exists():
        return False, f"no embeddings file at {p.name}; run scripts/build_embeddings.py"
    if not meta_path.exists():
        return False, f"{meta_path.name} is missing; rebuild with scripts/build_embeddings.py"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    stored_model = meta.get("model")
    if model is not None and stored_model != model:
        return False, (
            f"the embeddings were built with {stored_model} and the configured model is {model}; "
            "rebuild with scripts/build_embeddings.py"
        )
    if ids is not None:
        stored = set(json.loads(ids_path.read_text(encoding="utf-8")))
        if stored != set(ids):
            missing = len(set(ids) - stored)
            return False, (
                f"the embeddings cover {len(stored)} listings and the inventory has {len(ids)}, "
                f"{missing} of them unembedded; rebuild with scripts/build_embeddings.py"
            )
    return True, "ok"


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
    # A query from a different model is the likely mismatch, and numpy would rather broadcast
    # some shapes into a silent wrong answer than refuse them.
    if q.shape[0] != matrix.shape[1]:
        raise RetrievalUnavailableError(
            f"the query embedding has {q.shape[0]} dimensions and the stored matrix has "
            f"{matrix.shape[1]}; rebuild with scripts/build_embeddings.py"
        )
    q = q / (np.linalg.norm(q) or 1.0)
    sims = matrix @ q
    return {i: float(s) for i, s in zip(ids, sims, strict=True)}


def save(ids: list[str], vectors: list[list[float]], path: Path, *, model: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    arr = np.asarray(vectors, dtype=np.float32)
    np.save(path, arr)
    ids_path, meta_path = _sidecars(path)
    ids_path.write_text(json.dumps(ids), encoding="utf-8")
    meta_path.write_text(
        json.dumps({"model": model, "dim": int(arr.shape[1]), "count": len(ids)}, indent=1),
        encoding="utf-8",
    )
    _cache.pop(str(path), None)

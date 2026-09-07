"""A stored matrix only answers for the model and the inventory it was built from."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from dubizzle_assistant.services import embeddings

GEMINI = "gemini/gemini-embedding-001"


def _write(tmp_path: Path, model: str, ids: list[str], dim: int = 4) -> Path:
    path = tmp_path / "e.npy"
    vectors = [[float(i + 1)] * dim for i in range(len(ids))]
    embeddings.save(ids, vectors, path, model=model)
    return path


def test_available_rejects_a_stale_matrix(tmp_path: Path) -> None:
    path = _write(tmp_path, GEMINI, ["C-001", "C-002"])
    assert embeddings.available(path, model=GEMINI, ids=["C-001", "C-002"]) == (True, "ok")

    ok, reason = embeddings.available(path, model="openai/nomic", ids=["C-001", "C-002"])
    assert not ok and GEMINI in reason and "openai/nomic" in reason

    ok, reason = embeddings.available(path, model=GEMINI, ids=["C-001", "C-003"])
    assert not ok and "unembedded" in reason

    ok, reason = embeddings.available(tmp_path / "missing.npy", model=GEMINI, ids=[])
    assert not ok and "scripts/build_embeddings.py" in reason


def test_available_needs_the_meta_sidecar(tmp_path: Path) -> None:
    # A matrix built before the sidecar existed cannot prove which model made it.
    path = _write(tmp_path, GEMINI, ["C-001"])
    path.with_suffix(".meta.json").unlink()
    ok, reason = embeddings.available(path, model=GEMINI, ids=["C-001"])
    assert not ok and "meta.json" in reason


def test_a_query_of_the_wrong_width_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, GEMINI, ["C-001", "C-002"], dim=4)
    ranked = embeddings.rank_by_similarity("hi", lambda _t: [1.0, 0.0, 0.0, 0.0], path)
    assert set(ranked) == {"C-001", "C-002"}
    with pytest.raises(embeddings.RetrievalUnavailableError, match="3 dimensions"):
        embeddings.rank_by_similarity("hi", lambda _t: [1.0, 0.0, 0.0], path)


def test_save_records_the_model_and_the_shape(tmp_path: Path) -> None:
    path = _write(tmp_path, GEMINI, ["C-001", "C-002", "C-003"], dim=8)
    meta = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))
    assert meta == {"model": GEMINI, "dim": 8, "count": 3}
    assert np.load(path).shape == (3, 8)

"""Retrieval accuracy on the golden set. Expected ids come from the inventory file, not from hand."""

from __future__ import annotations

import pytest

from dubizzle_assistant.golden import CASES, score


@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_golden(client, listings, case):
    params = {k: v for k, v in case.args.items() if v is not None}
    params["limit"] = case.k
    r = client.get("/inventory/search", params=params)
    assert r.status_code == 200, r.text
    result = score(case, r.json(), listings)
    assert result["passed"], result

"""
Run the golden set under each retrieval mode and write the comparison table.

Expected ids come from the inventory file at run time. The table is the
evidence behind the choice of hybrid retrieval: the same queries, the same
expected cars, four ways of finding them.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dubizzle_assistant.golden import CASES, score
from dubizzle_assistant.services import inventory as inv
from dubizzle_assistant.services.explain import filters_from_args

MODES = ("structured", "fts", "hybrid", "embeddings")


NOT_APPLICABLE = "not applicable"
# The Honda and the Velar anchor the hand-written checks; another dataset will not have them.
_ANCHOR_IDS = ("R-078", "C-003")


def applicability(case: Any, by_id: dict[str, dict[str, Any]]) -> str | None:
    """Why a case cannot be scored on this inventory, or None when it can."""
    if not any(case.expected(r) for r in by_id.values()):
        return f"{NOT_APPLICABLE}: no listing here matches the expectation"
    if case.check is not None and not all(i in by_id for i in _ANCHOR_IDS):
        return f"{NOT_APPLICABLE}: check written for the assignment dataset"
    return None


def run_mode(
    conn: sqlite3.Connection, by_id: dict[str, dict[str, Any]], mode: str, embedder: Any = None
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case in CASES:
        why = applicability(case, by_id)
        if why:
            rows.append({"name": case.name, "mode": mode, "passed": None, "note": why})
            continue
        filters, steps = filters_from_args({k: v for k, v in case.args.items() if v is not None})
        try:
            result = inv.search(
                conn, filters, mode=mode, limit=case.k, embedder=embedder, normalization=steps
            ).as_dict()
        except inv.RetrievalUnavailableError as e:
            rows.append({"name": case.name, "mode": mode, "passed": None, "note": str(e)})
            continue
        rows.append({**score(case, result, by_id), "mode": mode})
    return rows


def evaluate(
    conn: sqlite3.Connection,
    inventory_path: Path,
    modes: tuple[str, ...] = MODES,
    embedder: Any = None,
) -> dict[str, Any]:
    data = json.loads(inventory_path.read_text(encoding="utf-8"))
    by_id = {r["id"]: r for r in data["listings"]}
    results = {m: run_mode(conn, by_id, m, embedder) for m in modes}
    summary = {}
    for m, rows in results.items():
        scored = [r for r in rows if r.get("passed") is not None]
        summary[m] = {
            "cases": len(scored),
            "passed": sum(1 for r in scored if r["passed"]),
            "mean_precision_at_k": round(sum(r["precision_at_k"] for r in scored) / len(scored), 3)
            if scored
            else None,
            "mean_recall": round(
                sum(r["recall"] for r in scored if r["recall"] is not None)
                / max(1, sum(1 for r in scored if r["recall"] is not None)),
                3,
            )
            if scored
            else None,
            "not_applicable": sum(
                1 for r in rows if r.get("passed") is None and NOT_APPLICABLE in str(r.get("note"))
            ),
            "unavailable": next(
                (
                    r["note"]
                    for r in rows
                    if r.get("passed") is None and NOT_APPLICABLE not in str(r.get("note"))
                ),
                None,
            ),
        }
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "summary": summary,
        "results": results,
    }


def render(report: dict[str, Any]) -> str:
    lines = [
        "# Retrieval evaluation",
        "",
        f"Generated {report['generated_at']}. Expected ids are computed from `data/inventory.json` for each query, never typed by hand.",
        "",
    ]
    lines += [
        "## Per mode",
        "",
        "| mode | cases | passed | n/a | mean precision@k | mean recall | note |",
        "|---|---|---|---|---|---|---|",
    ]
    for m, s in report["summary"].items():
        lines.append(
            f"| {m} | {s['cases']} | {s['passed']} | {s.get('not_applicable', 0)} | {s['mean_precision_at_k']} | {s['mean_recall']} | {s['unavailable'] or ''} |"
        )
    lines += ["", "## Per query", ""]
    modes = list(report["results"])
    lines.append("| query | " + " | ".join(modes) + " | expected | note |")
    lines.append("|---|" + "---|" * len(modes) + "---|---|")
    by_name: dict[str, dict[str, dict[str, Any]]] = {}
    for m, rows in report["results"].items():
        for r in rows:
            by_name.setdefault(r["name"], {})[m] = r
    for name, per_mode in by_name.items():
        cells = []
        for m in modes:
            r = per_mode.get(m)
            if not r or r.get("passed") is None:
                cells.append("n/a")
            else:
                flag = "pass" if r["passed"] else "FAIL"
                cells.append(
                    f"{flag} p@k {r['precision_at_k']}"
                    + (f" r {r['recall']}" if r.get("recall") is not None else "")
                    + (f" rank {r['first_hit_rank']}" if r.get("first_hit_rank") else "")
                )
        any_row = next(iter(per_mode.values()))
        lines.append(
            f"| {name} | "
            + " | ".join(cells)
            + f" | {any_row.get('expected', '')} | {any_row.get('note', '')} |"
        )
    lines.append("")
    lines.append(
        "Precision at k is over the shown page. Recall compares the full match count with the expected set. A pass also honours each case's extra check, for example that the relaxation ladder ran or the priced car ranks first."
    )
    return "\n".join(lines) + "\n"

"""CLI: wipe local state (database, CSVs, outbox) so the two rubric scenarios run from a clean slate."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dubizzle_assistant.config import get_settings  # noqa: E402


def main() -> int:
    s = get_settings()
    removed = []
    for p in (
        s.db_path,
        Path(str(s.db_path) + "-wal"),
        Path(str(s.db_path) + "-shm"),
        s.leads_csv,
        s.bookings_csv,
    ):
        if p.exists():
            p.unlink()
            removed.append(str(p))
    if s.outbox_dir.exists():
        shutil.rmtree(s.outbox_dir)
        removed.append(str(s.outbox_dir))
    print("removed:\n  " + "\n  ".join(removed) if removed else "nothing to remove")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

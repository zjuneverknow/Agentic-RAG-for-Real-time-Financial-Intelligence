from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def backfill(db_path: Path) -> int:
    conn = sqlite3.connect(db_path)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(chunks)").fetchall()}
    if "announcement_category" not in columns:
        conn.execute("ALTER TABLE chunks ADD COLUMN announcement_category TEXT")
    if "announcement_tags" not in columns:
        conn.execute("ALTER TABLE chunks ADD COLUMN announcement_tags TEXT")
    conn.execute(
        """
        UPDATE chunks
        SET announcement_category = (
                SELECT a.announcement_category
                FROM announcements a
                WHERE chunks.source_id = chunks.code || '_' || a.announcement_id
            ),
            announcement_tags = (
                SELECT a.announcement_tags
                FROM announcements a
                WHERE chunks.source_id = chunks.code || '_' || a.announcement_id
            )
        WHERE doc_type='announcement'
        """
    )
    updated = conn.total_changes
    conn.commit()
    conn.close()
    print(f"Backfilled chunk announcement categories: {updated}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill announcement category fields on existing chunks.")
    parser.add_argument("--db", default="data/metadata.sqlite")
    args = parser.parse_args()
    return backfill(Path(args.db))


if __name__ == "__main__":
    raise SystemExit(main())

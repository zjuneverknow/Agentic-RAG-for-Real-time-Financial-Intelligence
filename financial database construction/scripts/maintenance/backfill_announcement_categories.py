from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from collection.download_announcements import classify_announcement, init_db, matched_keywords


def backfill(db_path: Path) -> int:
    conn = init_db(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT code, announcement_id, title
        FROM announcements
        WHERE title IS NOT NULL AND title <> ''
        """
    ).fetchall()

    updated = 0
    for row in rows:
        category, tags, category_keywords = classify_announcement(row["title"])
        keywords = sorted(set(matched_keywords(row["title"]) + category_keywords))
        conn.execute(
            """
            UPDATE announcements
            SET announcement_category=?,
                announcement_tags=?,
                matched_keywords=?
            WHERE code=? AND announcement_id=?
            """,
            (
                category,
                ",".join(tags),
                ",".join(keywords),
                row["code"],
                row["announcement_id"],
            ),
        )
        updated += 1
    conn.commit()
    conn.close()
    print(f"Backfilled announcement categories: {updated}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill announcement categories for existing metadata.")
    parser.add_argument("--db", default="data/metadata.sqlite")
    args = parser.parse_args()
    return backfill(Path(args.db))


if __name__ == "__main__":
    raise SystemExit(main())

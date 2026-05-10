from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from common.rag_finance import extract_metric_terms, infer_statement_type


def ensure_columns(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(chunks)").fetchall()}
    migrations = {
        "statement_type": "ALTER TABLE chunks ADD COLUMN statement_type TEXT",
        "metric_terms": "ALTER TABLE chunks ADD COLUMN metric_terms TEXT",
    }
    for column, statement in migrations.items():
        if column not in columns:
            conn.execute(statement)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_statement_type ON chunks(statement_type)")
    conn.commit()


def backfill_finance_metadata(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT chunk_id, section, COALESCE(raw_text, text, embed_text, '') AS body
        FROM chunks
        WHERE statement_type IS NULL OR statement_type = '' OR metric_terms IS NULL OR metric_terms = ''
        """
    ).fetchall()
    updates = []
    for chunk_id, section, body in rows:
        updates.append((infer_statement_type(section, body), extract_metric_terms(body, section), chunk_id))
    conn.executemany(
        "UPDATE chunks SET statement_type=?, metric_terms=? WHERE chunk_id=?",
        updates,
    )
    conn.commit()
    return len(updates)


def rebuild_fts(conn: sqlite3.Connection) -> int:
    conn.execute("DROP TABLE IF EXISTS chunks_fts")
    conn.execute(
        """
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            chunk_id UNINDEXED,
            search_text,
            tokenize='unicode61'
        )
        """
    )
    rows = conn.execute(
        """
        SELECT
            chunk_id,
            COALESCE(company, '') || ' ' ||
            COALESCE(code, '') || ' ' ||
            COALESCE(title, '') || ' ' ||
            COALESCE(section, '') || ' ' ||
            COALESCE(statement_type, '') || ' ' ||
            COALESCE(metric_terms, '') || ' ' ||
            COALESCE(raw_text, display_text, text, embed_text, '') AS search_text
        FROM chunks
        """
    ).fetchall()
    conn.executemany("INSERT INTO chunks_fts(chunk_id, search_text) VALUES (?, ?)", rows)
    conn.commit()
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backfill finance retrieval metadata and rebuild SQLite FTS.")
    parser.add_argument("--db", default="data/metadata.sqlite")
    parser.add_argument("--skip-fts", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    ensure_columns(conn)
    updated = backfill_finance_metadata(conn)
    print(f"Backfilled finance metadata rows: {updated}")
    if not args.skip_fts:
        indexed = rebuild_fts(conn)
        print(f"Rebuilt chunks_fts rows: {indexed}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

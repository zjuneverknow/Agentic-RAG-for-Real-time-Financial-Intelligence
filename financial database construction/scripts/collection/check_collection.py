from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize report collection quality from metadata.sqlite.")
    parser.add_argument("--db", default="data/metadata.sqlite")
    args = parser.parse_args()

    db_path = Path(args.db)
    if not db_path.exists():
        parser.error(f"Database not found: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT download_status, COUNT(*) AS n
        FROM reports
        GROUP BY download_status
        ORDER BY download_status
        """
    ).fetchall()
    print("Status summary")
    for row in rows:
        print(f"  {row['download_status']}: {row['n']}")

    missing_meta = conn.execute(
        """
        SELECT COUNT(*) AS n
        FROM reports
        WHERE (code='' OR year IS NULL OR report_type='' OR source_url='')
          AND download_status IN ('downloaded', 'found')
        """
    ).fetchone()["n"]
    print(f"Missing critical metadata: {missing_meta}")

    downloaded = conn.execute(
        """
        SELECT code, company, industry, year, report_type, title, pdf_path, file_size
        FROM reports
        WHERE download_status='downloaded'
        ORDER BY code, year, report_type
        """
    ).fetchall()
    bad_files = []
    for row in downloaded:
        pdf_path = Path(row["pdf_path"] or "")
        if not pdf_path.exists() or (row["file_size"] or 0) < 100_000:
            bad_files.append(row)

    print(f"Downloaded reports: {len(downloaded)}")
    print(f"Suspicious/missing PDF files: {len(bad_files)}")
    for row in bad_files[:20]:
        print(f"  {row['code']} {row['year']} {row['report_type']} {row['pdf_path']}")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

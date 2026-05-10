from __future__ import annotations

import argparse
import re
import sqlite3
from pathlib import Path


METRIC_ALIASES = {
    "营业收入": ["营业收入"],
    "归母净利润": ["归属于上市公司股东的净利润", "归母净利润"],
    "扣非归母净利润": ["归属于上市公司股东的扣除非经常性损益的净利润", "扣非归母净利润"],
    "经营现金流": ["经营活动产生的现金流量净额"],
    "研发投入": ["研发投入", "研发费用"],
    "基本每股收益": ["基本每股收益"],
    "加权平均净资产收益率": ["加权平均净资产收益率"],
    "资产总额": ["资产总额", "总资产"],
    "负债总额": ["负债总额", "总负债"],
    "货币资金": ["货币资金"],
    "应收账款": ["应收账款"],
    "存货": ["存货"],
}

VALUE_PATTERN = re.compile(r"[-+]?\d{1,3}(?:,\d{3})*(?:\.\d+)?%?|[-+]?\d+(?:\.\d+)?%?")
UNIT_PATTERN = re.compile(r"单位[:：]\s*([人民币]*元|万元|亿元|千元|股|%)")


def init_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS financial_facts (
            fact_id TEXT PRIMARY KEY,
            chunk_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            code TEXT NOT NULL,
            company TEXT,
            industry TEXT,
            year INTEGER,
            report_type TEXT,
            publish_date TEXT,
            metric_name TEXT NOT NULL,
            metric_alias TEXT NOT NULL,
            metric_value TEXT,
            unit TEXT,
            raw_line TEXT NOT NULL,
            section TEXT,
            page_start INTEGER,
            page_end INTEGER,
            source_pdf TEXT,
            source_url TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_financial_facts_code_year ON financial_facts(code, year)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_financial_facts_metric ON financial_facts(metric_name)")
    conn.commit()


def normalize_value(value: str) -> str:
    return value.replace(",", "").strip()


def detect_unit(text: str) -> str:
    match = UNIT_PATTERN.search(text)
    return match.group(1) if match else ""


def iter_candidate_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    merged: list[str] = []
    for line in lines:
        if len(line) <= 4:
            continue
        merged.append(line)
    return merged


def extract_facts_from_chunk(row: sqlite3.Row) -> list[tuple[str, str, str, str, str]]:
    text = row["raw_text"] or row["display_text"] or row["text"] or ""
    unit = detect_unit(text)
    facts: list[tuple[str, str, str, str, str]] = []
    for line in iter_candidate_lines(text):
        for metric_name, aliases in METRIC_ALIASES.items():
            for alias in aliases:
                if alias not in line:
                    continue
                values = [normalize_value(value) for value in VALUE_PATTERN.findall(line)]
                value = values[0] if values else ""
                if not value and metric_name not in ("加权平均净资产收益率",):
                    continue
                facts.append((metric_name, alias, value, unit, line))
                break
    return facts


def build_facts(db_path: Path, rebuild: bool) -> int:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    init_table(conn)
    if rebuild:
        conn.execute("DELETE FROM financial_facts")
        conn.commit()

    chunks = conn.execute(
        """
        SELECT *
        FROM chunks
        WHERE doc_type='report'
          AND chunk_type IN ('financial_statement', 'table_like')
        ORDER BY code, year, report_type, page_start, chunk_index
        """
    ).fetchall()

    inserted = 0
    skipped = 0
    for row in chunks:
        for fact_index, (metric_name, alias, value, unit, raw_line) in enumerate(extract_facts_from_chunk(row), start=1):
            fact_id = f"{row['chunk_id']}_{fact_index:03d}_{metric_name}"
            try:
                conn.execute(
                    """
                    INSERT INTO financial_facts (
                        fact_id, chunk_id, source_id, code, company, industry, year,
                        report_type, publish_date, metric_name, metric_alias,
                        metric_value, unit, raw_line, section, page_start, page_end,
                        source_pdf, source_url
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        fact_id,
                        row["chunk_id"],
                        row["source_id"],
                        row["code"],
                        row["company"],
                        row["industry"],
                        row["year"],
                        row["report_type"],
                        row["publish_date"],
                        metric_name,
                        alias,
                        value,
                        unit,
                        raw_line[:2000],
                        row["section"],
                        row["page_start"],
                        row["page_end"],
                        row["source_pdf"],
                        row["source_url"],
                    ),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                skipped += 1
    conn.commit()
    conn.close()
    print(f"Inserted financial facts: {inserted}; skipped: {skipped}", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract first-pass structured financial facts from table-like chunks.")
    parser.add_argument("--db", default="data/metadata.sqlite")
    parser.add_argument("--rebuild", action="store_true")
    args = parser.parse_args()
    return build_facts(Path(args.db), args.rebuild)


if __name__ == "__main__":
    raise SystemExit(main())

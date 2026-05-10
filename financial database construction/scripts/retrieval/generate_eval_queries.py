from __future__ import annotations

import argparse
import json
import random
import sqlite3
from pathlib import Path


STATEMENT_NAMES = {
    "balance_sheet": "资产负债表",
    "income_statement": "利润表",
    "cash_flow": "现金流量表",
    "equity_statement": "所有者权益变动表",
}


def load_metric_rows(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            chunk_id,
            code,
            company,
            industry,
            year,
            report_type,
            doc_type,
            chunk_type,
            section,
            statement_type,
            metric_terms,
            title
        FROM chunks
        WHERE doc_type='report'
          AND chunk_type='financial_statement'
          AND metric_terms IS NOT NULL
          AND metric_terms <> ''
          AND code IS NOT NULL
          AND year IS NOT NULL
          AND report_type IS NOT NULL
        ORDER BY code, year, report_type, chunk_index
        """
    ).fetchall()


def choose_metric_terms(metric_terms: str, max_terms: int, rng: random.Random) -> list[str]:
    terms = [term.strip() for term in metric_terms.split() if term.strip()]
    terms = [term for term in terms if term not in {"利润表", "资产负债表", "现金流量表", "所有者权益变动表"}]
    if not terms:
        return []
    rng.shuffle(terms)
    return terms[: rng.randint(1, min(max_terms, len(terms)))]


def question_for(row: sqlite3.Row, terms: list[str], rng: random.Random) -> str:
    company = row["company"] or row["code"]
    year = row["year"]
    report_type = row["report_type"]
    section = row["section"] or STATEMENT_NAMES.get(row["statement_type"], "")
    metric_text = "、".join(terms)
    templates = [
        "{company} {year} {report_type} {metric_text}是多少？",
        "查询{company}{year}{report_type}报告中的{metric_text}",
        "{company}在{year}{report_type}的{metric_text}情况",
        "根据{company}{year}{report_type}{section}，{metric_text}是多少？",
    ]
    return rng.choice(templates).format(
        company=company,
        year=year,
        report_type=report_type,
        section=section,
        metric_text=metric_text,
    )


def find_positive_contexts(conn: sqlite3.Connection, row: sqlite3.Row, terms: list[str]) -> list[str]:
    clauses = [
        "code = ?",
        "year = ?",
        "report_type = ?",
        "doc_type = ?",
        "chunk_type = ?",
    ]
    params = [row["code"], row["year"], row["report_type"], row["doc_type"], row["chunk_type"]]
    if row["statement_type"]:
        clauses.append("statement_type = ?")
        params.append(row["statement_type"])
    metric_clauses = []
    for term in terms:
        metric_clauses.append("(metric_terms LIKE ? OR COALESCE(raw_text, text, embed_text, '') LIKE ?)")
        params.extend([f"%{term}%", f"%{term}%"])
    where = " AND ".join(clauses)
    metric_where = " OR ".join(metric_clauses)
    rows = conn.execute(
        f"""
        SELECT chunk_id
        FROM chunks
        WHERE {where}
          AND ({metric_where})
        ORDER BY source_id, chunk_index
        """,
        params,
    ).fetchall()
    return [item["chunk_id"] for item in rows]


def build_case(conn: sqlite3.Connection, row: sqlite3.Row, rng: random.Random, max_terms: int) -> dict | None:
    terms = choose_metric_terms(row["metric_terms"], max_terms, rng)
    if not terms:
        return None
    positive_contexts = find_positive_contexts(conn, row, terms)
    if row["chunk_id"] not in positive_contexts:
        positive_contexts.insert(0, row["chunk_id"])
    filters = {
        "code": row["code"],
        "year": int(row["year"]),
        "report_type": row["report_type"],
        "doc_type": row["doc_type"],
        "chunk_type": row["chunk_type"],
    }
    if row["statement_type"]:
        filters["statement_type"] = row["statement_type"]
    return {
        "question": question_for(row, terms, rng),
        "gold_answer": "",
        "positive_contexts": positive_contexts,
        "seed_context": row["chunk_id"],
        "metadata_filter": filters,
        "expected_section": row["section"] or "",
        "expected_statement_type": row["statement_type"] or "",
        "metric_terms": terms,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate finance retrieval eval queries from chunk metadata.")
    parser.add_argument("--db", default="data/metadata.sqlite")
    parser.add_argument("--out", default="config/eval_queries_1000.jsonl")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-terms", type=int, default=2)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    rows = load_metric_rows(conn)
    if not rows:
        raise SystemExit("No metric-bearing financial_statement chunks found. Run scripts/indexing/prepare_retrieval_metadata.py first.")

    rng.shuffle(rows)
    cases = []
    seen_questions = set()
    attempts = 0
    while len(cases) < args.count and attempts < args.count * 20:
        attempts += 1
        row = rows[attempts % len(rows)]
        case = build_case(conn, row, rng, args.max_terms)
        if not case:
            continue
        key = (case["question"], tuple(case["positive_contexts"]))
        if key in seen_questions:
            continue
        seen_questions.add(key)
        cases.append(case)

    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(json.dumps(case, ensure_ascii=False) for case in cases) + "\n", encoding="utf-8")
    print(f"Generated eval cases: {len(cases)}")
    print(f"Output: {output}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

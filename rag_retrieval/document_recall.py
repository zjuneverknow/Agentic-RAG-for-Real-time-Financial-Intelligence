from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class DocumentCandidate:
    source_pdf: str
    source_url: str
    code: str
    company: str
    year: int
    report_type: str
    doc_type: str
    title: str
    publish_date: str
    source_type: str
    chunk_count: int
    score: float


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _where_from_query(query: Dict[str, Any]) -> tuple[str, list[Any]]:
    entities = query.get("entities") or {}
    time_range = query.get("time_range") or {}
    clauses = ["source_pdf IS NOT NULL", "source_pdf != ''"]
    params: list[Any] = []
    code = entities.get("code") or query.get("code")
    year = entities.get("year") or time_range.get("year")
    period = entities.get("period") or time_range.get("period")
    company = entities.get("company") or query.get("company")
    if code:
        clauses.append("code = ?")
        params.append(code)
    elif company:
        clauses.append("company LIKE ?")
        params.append(f"%{company}%")
    if year:
        clauses.append("year = ?")
        params.append(int(year))
    if period:
        clauses.append("report_type = ?")
        params.append(period)
    return " AND ".join(clauses), params


def recall_documents(db_path: str, query: Dict[str, Any], limit: int = 8) -> List[DocumentCandidate]:
    conn = _connect(db_path)
    try:
        where, params = _where_from_query(query)
        sql = f"""
            SELECT
                source_pdf,
                MAX(source_url) AS source_url,
                MAX(code) AS code,
                MAX(company) AS company,
                MAX(year) AS year,
                MAX(report_type) AS report_type,
                MAX(doc_type) AS doc_type,
                MAX(title) AS title,
                MAX(publish_date) AS publish_date,
                MAX(source_type) AS source_type,
                COUNT(*) AS chunk_count,
                MAX(source_authority_score) AS authority
            FROM chunks
            WHERE {where}
            GROUP BY source_pdf
            ORDER BY authority DESC, publish_date DESC, chunk_count DESC
            LIMIT ?
        """
        rows = conn.execute(sql, [*params, limit]).fetchall()
        if not rows and params:
            rows = conn.execute(
                """
                SELECT source_pdf, MAX(source_url) AS source_url, MAX(code) AS code, MAX(company) AS company,
                       MAX(year) AS year, MAX(report_type) AS report_type, MAX(doc_type) AS doc_type,
                       MAX(title) AS title, MAX(publish_date) AS publish_date, MAX(source_type) AS source_type,
                       COUNT(*) AS chunk_count, MAX(source_authority_score) AS authority
                FROM chunks
                WHERE source_pdf IS NOT NULL AND source_pdf != ''
                GROUP BY source_pdf
                ORDER BY authority DESC, publish_date DESC, chunk_count DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        docs = []
        for rank, row in enumerate(rows, start=1):
            authority = float(row["authority"] or 1.0)
            docs.append(DocumentCandidate(
                source_pdf=row["source_pdf"] or "",
                source_url=row["source_url"] or "",
                code=row["code"] or "",
                company=row["company"] or "",
                year=int(row["year"] or 0),
                report_type=row["report_type"] or "",
                doc_type=row["doc_type"] or "",
                title=row["title"] or Path(row["source_pdf"] or "").name,
                publish_date=row["publish_date"] or "",
                source_type=row["source_type"] or "",
                chunk_count=int(row["chunk_count"] or 0),
                score=authority + 1.0 / rank,
            ))
        return docs
    finally:
        conn.close()
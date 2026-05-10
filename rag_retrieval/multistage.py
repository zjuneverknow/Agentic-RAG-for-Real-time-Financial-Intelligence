from __future__ import annotations

import os
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List

from langchain_core.documents import Document

from nodes.evidence.evidence_utils import document_to_evidence
from rag_retrieval.document_recall import DocumentCandidate, recall_documents

FIN_DB_ROOT = Path(os.getenv("FIN_DB_ROOT", Path(__file__).resolve().parents[1] / "financial database construction"))
FIN_DB_SCRIPTS = FIN_DB_ROOT / "scripts"
if str(FIN_DB_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(FIN_DB_SCRIPTS))

from common.rag_finance import build_query_plan, finance_rule_score  # noqa: E402
from retrieval.search_milvus import ensure_fts, fts_query_text  # noqa: E402


@dataclass
class MultiStageResult:
    documents: List[Document]
    evidence: List[Dict[str, Any]]
    document_candidates: List[DocumentCandidate]
    trace: Dict[str, Any]


def _db_path() -> str:
    return os.getenv("MILVUS_SQLITE_DB", str(FIN_DB_ROOT / "data" / "metadata.sqlite"))


def _sub_queries(query: Dict[str, Any]) -> List[Dict[str, Any]]:
    subs = list(query.get("sub_questions") or [])
    if not subs:
        subs = [{"question": query.get("active_question") or query.get("original_question") or "", "focus": "main", "type": "single"}]
    return subs


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _metric_filter_sql(focus: str) -> tuple[str, list[Any]]:
    if not focus or focus in {"main", "comparison"}:
        return "", []
    return " AND (metric_terms LIKE ? OR display_text LIKE ? OR text LIKE ?) ", [f"%{focus}%", f"%{focus}%", f"%{focus}%"]


def _statement_prior(focus: str, row: sqlite3.Row) -> float:
    statement_type = row["statement_type"] or ""
    text = (row["display_text"] or row["text"] or "")[:1000]
    if focus in {"钀ヤ笟鏀跺叆", "鍑€鍒╂鼎", "褰掓瘝鍑€鍒╂鼎"} and statement_type == "income_statement":
        return 0.35
    if focus and focus in text:
        return 0.3
    return 0.0


def _chunk_to_doc(row: sqlite3.Row, score: float, sub_question: Dict[str, Any], doc_score: float) -> Document:
    metadata = {
        "source": row["source_pdf"] or row["source_url"] or "SQLite FTS",
        "url": row["source_url"] or "",
        "retrieval_source": "MultiStage SQLite+FTS",
        "chunk_id": row["chunk_id"],
        "code": row["code"] or "",
        "company": row["company"] or "",
        "industry": row["industry"] or "",
        "year": row["year"] or 0,
        "report_type": row["report_type"] or "",
        "doc_type": row["doc_type"] or "",
        "chunk_type": row["chunk_type"] or "",
        "section": row["section"] or "",
        "statement_type": row["statement_type"] or "",
        "metric_terms": row["metric_terms"] or "",
        "page_start": row["page_start"] or 0,
        "page_end": row["page_end"] or 0,
        "hybrid_score": round(score, 4),
        "doc_score": round(doc_score, 4),
        "sub_question": sub_question.get("question", ""),
        "sub_focus": sub_question.get("focus", ""),
        "source_type": row["source_type"] or "",
    }
    return Document(page_content=row["display_text"] or row["text"] or "", metadata=metadata)


def _fts_chunks(conn: sqlite3.Connection, docs: List[DocumentCandidate], sub_question: Dict[str, Any], per_sub_k: int) -> List[Document]:
    if not docs or not ensure_fts(conn):
        return []
    query_text = sub_question.get("question") or sub_question.get("focus") or ""
    focus = sub_question.get("focus") or ""
    source_pdfs = [doc.source_pdf for doc in docs if doc.source_pdf]
    placeholders = ",".join("?" for _ in source_pdfs)
    metric_sql, metric_params = _metric_filter_sql(focus)
    sql = f"""
        SELECT c.*, bm25(chunks_fts) AS bm25_score
        FROM chunks_fts
        JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
        WHERE chunks_fts MATCH ?
          AND c.source_pdf IN ({placeholders})
          {metric_sql}
        ORDER BY bm25_score
        LIMIT ?
    """
    params: list[Any] = [fts_query_text(query_text), *source_pdfs, *metric_params, max(per_sub_k * 4, 20)]
    try:
        rows = conn.execute(sql, params).fetchall()
    except sqlite3.OperationalError:
        rows = []
    if not rows and focus:
        like = f"%{focus}%"
        rows = conn.execute(
            f"""
            SELECT c.*, 0.0 AS bm25_score
            FROM chunks c
            WHERE c.source_pdf IN ({placeholders})
              AND (c.metric_terms LIKE ? OR c.display_text LIKE ? OR c.text LIKE ?)
            LIMIT ?
            """,
            [*source_pdfs, like, like, like, max(per_sub_k * 4, 20)],
        ).fetchall()
    doc_score = {doc.source_pdf: doc.score for doc in docs}
    ranked = []
    for rank, row in enumerate(rows, start=1):
        bm25_component = 1.0 / rank
        score = bm25_component + _statement_prior(focus, row) + doc_score.get(row["source_pdf"], 0.0) * 0.1
        ranked.append((score, row))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [_chunk_to_doc(row, score, sub_question, doc_score.get(row["source_pdf"], 0.0)) for score, row in ranked[:per_sub_k]]


def _dedupe_documents(docs: Iterable[Document]) -> List[Document]:
    seen = set()
    out = []
    for doc in docs:
        key = doc.metadata.get("chunk_id") or (doc.page_content[:200], doc.metadata.get("source"))
        if key in seen:
            continue
        seen.add(key)
        out.append(doc)
    return out


def multistage_retrieve(state: Dict[str, Any]) -> MultiStageResult:
    query = state.get("query") or {}
    db_path = _db_path()
    doc_limit = int(os.getenv("MULTISTAGE_DOC_TOP_K", "8"))
    per_sub_k = int(os.getenv("MULTISTAGE_CHUNK_PER_SUB_K", "6"))
    docs = recall_documents(db_path, query, limit=doc_limit)
    conn = _connect(db_path)
    all_chunks: List[Document] = []
    try:
        for sub in _sub_queries(query):
            all_chunks.extend(_fts_chunks(conn, docs, sub, per_sub_k))
    finally:
        conn.close()
    selected_docs = _dedupe_documents(all_chunks)
    evidence = [
        document_to_evidence(doc, source_type="milvus", source_name="MultiStage Retrieval", default_score=doc.metadata.get("hybrid_score", 0.0))
        for doc in selected_docs
    ]
    return MultiStageResult(
        documents=selected_docs,
        evidence=evidence,
        document_candidates=docs,
        trace={
            "doc_candidates": len(docs),
            "chunk_candidates": len(selected_docs),
            "sub_queries": len(_sub_queries(query)),
        },
    )

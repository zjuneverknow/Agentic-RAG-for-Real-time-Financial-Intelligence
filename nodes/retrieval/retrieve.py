from __future__ import annotations

import os
import re
import sys
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Tuple

import numpy as np
from langchain_core.documents import Document

from nodes.evidence.evidence_utils import document_to_evidence, extend_evidence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FIN_DB_ROOT = Path(os.getenv("FIN_DB_ROOT", PROJECT_ROOT / "financial database construction"))
FIN_DB_SCRIPTS = FIN_DB_ROOT / "scripts"
if str(FIN_DB_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(FIN_DB_SCRIPTS))

from common.rag_finance import build_query_plan  # noqa: E402
from retrieval.search_milvus import (  # noqa: E402
    merge_candidates,
    milvus_candidates,
    score_candidates,
    select_candidates,
    sqlite_candidates,
)

A_SHARE_CODE_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")


def _search_args(question: str, code: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        db=os.getenv("MILVUS_SQLITE_DB", str(FIN_DB_ROOT / "data" / "metadata.sqlite")),
        host=os.getenv("MILVUS_HOST", "127.0.0.1"),
        port=os.getenv("MILVUS_PORT", "19530"),
        collection=os.getenv("MILVUS_COLLECTION", "a_share_chunks"),
        model=os.getenv("MILVUS_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
        top_k=int(os.getenv("TOP_K", "6")),
        candidate_k=int(os.getenv("MILVUS_CANDIDATE_K", "50")),
        code=code or None,
        industry=None,
        year=None,
        report_type=None,
        doc_type=None,
        announcement_category=None,
        chunk_type=None,
        section=None,
        statement_type="",
        per_source_limit=int(os.getenv("MILVUS_PER_SOURCE_LIMIT", "0")),
        adjacent_window=int(os.getenv("MILVUS_ADJACENT_WINDOW", "1")),
        no_hybrid=(os.getenv("MILVUS_NO_HYBRID", "0").strip().lower() in {"1", "true", "yes", "on"}),
        no_query_rewrite=(os.getenv("MILVUS_NO_QUERY_REWRITE", "0").strip().lower() in {"1", "true", "yes", "on"}),
        dense_weight=float(os.getenv("MILVUS_DENSE_WEIGHT", "1.0")),
        bm25_weight=float(os.getenv("MILVUS_BM25_WEIGHT", "1.0")),
        rrf_k=int(os.getenv("MILVUS_RRF_K", "60")),
        finance_rule_weight=float(os.getenv("MILVUS_FINANCE_RULE_WEIGHT", "1.0")),
        freshness_weight=float(os.getenv("MILVUS_FRESHNESS_WEIGHT", "0.15")),
        half_life_days=float(os.getenv("MILVUS_HALF_LIFE_DAYS", "180.0")),
        authority_weight=float(os.getenv("MILVUS_AUTHORITY_WEIGHT", "0.05")),
        ef=int(os.getenv("MILVUS_EF", "64")),
        query=question,
        as_of_date="",
    )


def _extract_a_share_code(question: str, symbol: str = "") -> str:
    if symbol and symbol.isdigit() and len(symbol) == 6:
        return symbol
    match = A_SHARE_CODE_PATTERN.search(question or "")
    return match.group(1) if match else ""


@lru_cache(maxsize=1)
def _model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(os.getenv("MILVUS_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"))


@lru_cache(maxsize=8)
def _collection(host: str, port: str, collection_name: str):
    from pymilvus import Collection, connections

    connections.connect(alias="default", host=host, port=port)
    collection = Collection(collection_name)
    collection.load()
    return collection


@lru_cache(maxsize=1)
def _finnhub_helpers():
    from nodes.retrieval.source_api import resolve_symbol

    return resolve_symbol


def _candidate_text(candidate) -> str:
    return candidate.entity.get("display_text") or candidate.entity.get("text") or ""


def _to_document(candidate) -> Document:
    entity = candidate.entity
    metadata = {
        "source": entity.get("source_pdf") or entity.get("source_url") or "Milvus",
        "url": entity.get("source_url") or "",
        "retrieval_source": "Milvus Hybrid",
        "chunk_id": candidate.chunk_id,
        "code": entity.get("code") or "",
        "company": entity.get("company") or "",
        "industry": entity.get("industry") or "",
        "year": entity.get("year") or 0,
        "report_type": entity.get("report_type") or "",
        "doc_type": entity.get("doc_type") or "",
        "chunk_type": entity.get("chunk_type") or "",
        "section": entity.get("section") or "",
        "statement_type": entity.get("statement_type") or "",
        "metric_terms": entity.get("metric_terms") or "",
        "page_start": entity.get("page_start") or 0,
        "page_end": entity.get("page_end") or 0,
        "dense_score": round(candidate.dense_score, 4),
        "sparse_score": round(candidate.sparse_score, 4),
        "hybrid_score": round(candidate.final, 4),
    }
    return Document(page_content=_candidate_text(candidate), metadata=metadata)


def _milvus_hybrid_search(question: str, code: str = "") -> Tuple[List[Document], float]:
    import sqlite3
    from datetime import date

    args = _search_args(question, code)
    query_plan = build_query_plan(question, enabled=not args.no_query_rewrite)
    embedding = _model().encode([query_plan.retrieval_query], normalize_embeddings=True)
    collection = _collection(args.host, args.port, args.collection)

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        dense = milvus_candidates(collection, np.asarray(embedding, dtype="float32").tolist(), args)
        sparse = {} if args.no_hybrid else sqlite_candidates(conn, args, query_plan.retrieval_query)
        candidates = merge_candidates(dense, sparse)
        for candidate in candidates:
            row = conn.execute("SELECT * FROM chunks WHERE chunk_id=?", (candidate.chunk_id,)).fetchone()
            if row:
                candidate.entity.update(dict(row))
        ranked = score_candidates(candidates, args, date.today(), query_plan)
        selected = select_candidates(ranked, args)
    finally:
        conn.close()

    docs = [_to_document(candidate) for candidate in selected]
    top_score = selected[0].final if selected else 0.0
    return docs, top_score


def milvus_node(state):
    question = state.get("active_question") or state["question"]
    symbol = (state.get("symbol") or "").upper()
    code = _extract_a_share_code(question, symbol)

    if not code and symbol:
        code = ""
    elif not code and not symbol:
        try:
            symbol = _finnhub_helpers()(question)
        except Exception:
            symbol = ""
        code = _extract_a_share_code(question, symbol)

    retrieval_path = list(state.get("retrieval_path", []))
    retrieval_path.append("milvus")

    try:
        docs, top_score = _milvus_hybrid_search(question, code)
    except Exception as exc:
        docs, top_score = [], 0.0
        failures = list(state.get("retrieval_failures", []))
        failures.append(f"milvus: {exc}")
    else:
        failures = list(state.get("retrieval_failures", []))

    success = bool(docs)
    evidence = [
        document_to_evidence(
            doc,
            source_type="milvus",
            source_name="Milvus Hybrid",
            default_score=doc.metadata.get("hybrid_score", 0.0) if doc.metadata else 0.0,
        )
        for doc in docs
    ]
    evidence_candidates = extend_evidence(state, evidence)
    return {
        "documents": docs,
        "evidence_candidates": evidence_candidates,
        "symbol": symbol or code,
        "web_search": "No" if success else "Yes",
        "active_question": question,
        "last_action": "milvus",
        "status": "success" if success else "fallback",
        "retrieval_source": "Milvus Hybrid",
        "retrieval_score": top_score,
        "retrieval_path": retrieval_path,
        "retrieval_failures": failures,
        "retrieval": {
            "evidence_candidates": evidence_candidates,
            "retrieval_source": "Milvus Hybrid",
            "retrieval_score": top_score,
            "retrieval_path": retrieval_path,
            "retrieval_failures": failures,
        },
    }


# Backward-compatible alias while the graph is being migrated.
pinecone_node = milvus_node

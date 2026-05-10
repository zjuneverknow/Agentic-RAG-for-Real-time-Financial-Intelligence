from __future__ import annotations

import argparse
import math
import sqlite3
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

import numpy as np

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from common.rag_finance import build_query_plan, finance_rule_score, rrf_score


BASE_OUTPUT_FIELDS = [
    "chunk_id",
    "code",
    "company",
    "industry",
    "year",
    "report_type",
    "doc_type",
    "chunk_type",
    "announcement_category",
    "announcement_tags",
    "section",
    "statement_type",
    "metric_terms",
    "title",
    "publish_date",
    "source_type",
    "source_authority_score",
    "page_start",
    "page_end",
    "text",
    "display_text",
    "source_pdf",
    "source_url",
]


@dataclass
class Candidate:
    chunk_id: str
    entity: dict[str, Any]
    dense_score: float = 0.0
    sparse_score: float = 0.0
    dense_rank: int | None = None
    sparse_rank: int | None = None
    final: float = 0.0
    sources: set[str] = field(default_factory=set)

    def get(self, key: str, default: Any = "") -> Any:
        return self.entity.get(key, default)


def build_expr(args: argparse.Namespace) -> str:
    parts: list[str] = []
    if args.code:
        parts.append(f'code == "{args.code}"')
    if args.industry:
        parts.append(f'industry == "{args.industry}"')
    if args.year:
        parts.append(f"year == {args.year}")
    if args.report_type:
        parts.append(f'report_type == "{args.report_type}"')
    if args.doc_type:
        parts.append(f'doc_type == "{args.doc_type}"')
    if args.announcement_category:
        parts.append(f'announcement_category == "{args.announcement_category}"')
    if args.chunk_type:
        parts.append(f'chunk_type == "{args.chunk_type}"')
    if args.section:
        parts.append(f'section == "{args.section}"')
    if args.statement_type:
        parts.append(f'statement_type == "{args.statement_type}"')
    return " and ".join(parts)


def sql_filter(args: argparse.Namespace) -> tuple[str, list[Any]]:
    clauses = []
    params: list[Any] = []
    for column, value in [
        ("code", args.code),
        ("industry", args.industry),
        ("year", args.year),
        ("report_type", args.report_type),
        ("doc_type", args.doc_type),
        ("announcement_category", args.announcement_category),
        ("chunk_type", args.chunk_type),
        ("section", args.section),
        ("statement_type", args.statement_type),
    ]:
        if value is not None and value != "":
            clauses.append(f"c.{column} = ?")
            params.append(value)
    return (" AND ".join(clauses), params)


def parse_date(value: object) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(text[:10], fmt).date()
        except ValueError:
            continue
    return None


def freshness_multiplier(entity: dict[str, Any]) -> float:
    doc_type = entity.get("doc_type") or ""
    report_type = entity.get("report_type") or ""
    if doc_type == "announcement":
        return 1.0
    if report_type in ("q1", "q3", "semiannual"):
        return 0.65
    if report_type == "annual":
        return 0.35
    return 0.5


def freshness_score(entity: dict[str, Any], args: argparse.Namespace, as_of: date) -> float:
    publish_date = parse_date(entity.get("publish_date"))
    if not publish_date or not args.freshness_weight:
        return 0.0
    age_days = max(0, (as_of - publish_date).days)
    return math.exp(-age_days / max(1.0, args.half_life_days)) * freshness_multiplier(entity)


def effective_per_source_limit(args: argparse.Namespace) -> int:
    if args.per_source_limit > 0:
        return args.per_source_limit
    if args.code and args.year and args.report_type:
        return max(args.top_k, 8)
    return 2


def collection_fields(collection) -> list[str]:
    return [field.name for field in collection.schema.fields]


def milvus_candidates(collection, embedding: list[list[float]], args: argparse.Namespace) -> dict[str, Candidate]:
    available = set(collection_fields(collection))
    output_fields = [field for field in BASE_OUTPUT_FIELDS if field in available]
    limit = max(args.top_k * max(1, effective_per_source_limit(args)) * 4, args.candidate_k)
    results = collection.search(
        data=embedding,
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {"ef": max(args.ef, limit + 8)}},
        limit=limit,
        expr=build_expr(args) or None,
        output_fields=output_fields,
    )
    candidates: dict[str, Candidate] = {}
    for rank, hit in enumerate(results[0], start=1):
        entity = {field: hit.entity.get(field) for field in output_fields}
        chunk_id = str(entity.get("chunk_id") or "")
        if not chunk_id:
            continue
        candidates[chunk_id] = Candidate(
            chunk_id=chunk_id,
            entity=entity,
            dense_score=float(hit.score),
            dense_rank=rank,
            sources={"dense"},
        )
    return candidates


def ensure_fts(conn: sqlite3.Connection) -> bool:
    exists = conn.execute("SELECT name FROM sqlite_master WHERE name='chunks_fts'").fetchone()
    return bool(exists)


def fts_query_text(query: str) -> str:
    tokens = [token for token in query.replace('"', " ").split() if token.strip()]
    return " OR ".join(tokens[:24]) if tokens else query


def sqlite_candidates(conn: sqlite3.Connection, args: argparse.Namespace, query: str) -> dict[str, Candidate]:
    if not ensure_fts(conn):
        return {}
    where, params = sql_filter(args)
    sql = """
        SELECT c.*, bm25(chunks_fts) AS bm25_score
        FROM chunks_fts
        JOIN chunks c ON c.chunk_id = chunks_fts.chunk_id
        WHERE chunks_fts MATCH ?
    """
    sql_params: list[Any] = [fts_query_text(query)]
    if where:
        sql += f" AND {where}"
        sql_params.extend(params)
    sql += " ORDER BY bm25_score LIMIT ?"
    sql_params.append(max(args.candidate_k, args.top_k * 6))

    rows = conn.execute(sql, sql_params).fetchall()
    candidates = {}
    for rank, row in enumerate(rows, start=1):
        entity = dict(row)
        chunk_id = str(entity.get("chunk_id") or "")
        if not chunk_id:
            continue
        candidates[chunk_id] = Candidate(
            chunk_id=chunk_id,
            entity=entity,
            sparse_score=1.0 / (1.0 + rank),
            sparse_rank=rank,
            sources={"sparse"},
        )
    return candidates


def merge_candidates(*candidate_sets: dict[str, Candidate]) -> list[Candidate]:
    merged: dict[str, Candidate] = {}
    for candidate_set in candidate_sets:
        for chunk_id, candidate in candidate_set.items():
            if chunk_id not in merged:
                merged[chunk_id] = candidate
                continue
            existing = merged[chunk_id]
            existing.entity.update({k: v for k, v in candidate.entity.items() if v not in (None, "")})
            existing.dense_score = max(existing.dense_score, candidate.dense_score)
            existing.sparse_score = max(existing.sparse_score, candidate.sparse_score)
            existing.dense_rank = existing.dense_rank or candidate.dense_rank
            existing.sparse_rank = existing.sparse_rank or candidate.sparse_rank
            existing.sources.update(candidate.sources)
    return list(merged.values())


def score_candidates(candidates: list[Candidate], args: argparse.Namespace, as_of: date, query_plan) -> list[Candidate]:
    for candidate in candidates:
        entity = candidate.entity
        text = entity.get("display_text") or entity.get("text") or ""
        authority = float(entity.get("source_authority_score") or 1.0)
        dense_rrf = rrf_score(candidate.dense_rank, args.rrf_k) if candidate.dense_rank else 0.0
        sparse_rrf = rrf_score(candidate.sparse_rank, args.rrf_k) if candidate.sparse_rank else 0.0
        hybrid_score = args.dense_weight * dense_rrf + args.bm25_weight * sparse_rrf
        candidate.final = (
            candidate.dense_score
            + hybrid_score
            + args.freshness_weight * freshness_score(entity, args, as_of)
            + args.authority_weight * authority
            + args.finance_rule_weight * finance_rule_score(query_plan, entity.get, text)
        )
    return sorted(candidates, key=lambda item: item.final, reverse=True)


def hydrate_from_sqlite(conn: sqlite3.Connection, candidate: Candidate) -> Candidate:
    row = conn.execute("SELECT * FROM chunks WHERE chunk_id=?", (candidate.chunk_id,)).fetchone()
    if row:
        candidate.entity.update(dict(row))
    return candidate


def expand_adjacent(conn: sqlite3.Connection, candidate: Candidate, window: int) -> str:
    if window <= 0:
        return candidate.entity.get("display_text") or candidate.entity.get("text") or ""
    row = conn.execute(
        "SELECT source_id, section, chunk_index FROM chunks WHERE chunk_id=?",
        (candidate.chunk_id,),
    ).fetchone()
    if not row:
        return candidate.entity.get("display_text") or candidate.entity.get("text") or ""
    rows = conn.execute(
        """
        SELECT display_text, text, chunk_id
        FROM chunks
        WHERE source_id=?
          AND COALESCE(section, '') = COALESCE(?, '')
          AND chunk_index BETWEEN ? AND ?
        ORDER BY chunk_index
        """,
        (row["source_id"], row["section"], row["chunk_index"] - window, row["chunk_index"] + window),
    ).fetchall()
    parts = []
    for adjacent in rows:
        marker = "[matched]" if adjacent["chunk_id"] == candidate.chunk_id else "[adjacent]"
        parts.append(f"{marker} {adjacent['display_text'] or adjacent['text'] or ''}")
    return "\n\n".join(parts)


def select_candidates(candidates: list[Candidate], args: argparse.Namespace) -> list[Candidate]:
    selected: list[Candidate] = []
    source_counts: dict[str, int] = {}
    limit = effective_per_source_limit(args)
    for candidate in candidates:
        source = candidate.entity.get("source_pdf") or candidate.entity.get("source_id") or ""
        if limit and source_counts.get(source, 0) >= limit:
            continue
        source_counts[source] = source_counts.get(source, 0) + 1
        selected.append(candidate)
        if len(selected) >= args.top_k:
            break
    return selected


def print_candidate(rank: int, candidate: Candidate, text: str) -> None:
    entity = candidate.entity
    page = entity.get("page_start") if entity.get("page_start") == entity.get("page_end") else f"{entity.get('page_start')}-{entity.get('page_end')}"
    print(
        f"\n#{rank} dense={candidate.dense_score:.4f} sparse={candidate.sparse_score:.4f} "
        f"final={candidate.final:.4f} source={'+'.join(sorted(candidate.sources))} chunk={candidate.chunk_id}"
    )
    print(
        f"{entity.get('code')} {entity.get('company')} {entity.get('year')} {entity.get('report_type')} "
        f"{entity.get('doc_type')} type={entity.get('chunk_type')} statement={entity.get('statement_type')} page={page}"
    )
    print(f"category={entity.get('announcement_category')} tags={entity.get('announcement_tags')}")
    print(f"section={entity.get('section')}")
    print(f"metrics={entity.get('metric_terms')}")
    print(f"publish_date={entity.get('publish_date')} source_type={entity.get('source_type')} authority={entity.get('source_authority_score')}")
    print(f"title={entity.get('title')}")
    print(f"source_pdf={entity.get('source_pdf')}")
    if entity.get("source_url"):
        print(f"source_url={entity.get('source_url')}")
    print(text[:2048].replace("\n", " "))


def main() -> int:
    parser = argparse.ArgumentParser(description="Search the Milvus A-share collection.")
    parser.add_argument("query")
    parser.add_argument("--db", default="data/metadata.sqlite")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="19530")
    parser.add_argument("--collection", default="a_share_chunks")
    parser.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument("--code")
    parser.add_argument("--industry")
    parser.add_argument("--year", type=int)
    parser.add_argument("--report-type")
    parser.add_argument("--doc-type")
    parser.add_argument("--announcement-category")
    parser.add_argument("--chunk-type")
    parser.add_argument("--section")
    parser.add_argument("--statement-type", choices=["", "balance_sheet", "income_statement", "cash_flow", "equity_statement"], default="")
    parser.add_argument("--per-source-limit", type=int, default=0, help="0 means auto: relaxed for exact report filters.")
    parser.add_argument("--adjacent-window", type=int, default=1)
    parser.add_argument("--no-hybrid", action="store_true")
    parser.add_argument("--no-query-rewrite", action="store_true")
    parser.add_argument("--dense-weight", type=float, default=1.0)
    parser.add_argument("--bm25-weight", type=float, default=1.0)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--finance-rule-weight", type=float, default=1.0)
    parser.add_argument("--freshness-weight", type=float, default=0.15)
    parser.add_argument("--half-life-days", type=float, default=180.0)
    parser.add_argument("--authority-weight", type=float, default=0.05)
    parser.add_argument("--as-of-date", default="")
    parser.add_argument("--ef", type=int, default=64)
    args = parser.parse_args()

    from pymilvus import Collection, connections
    from sentence_transformers import SentenceTransformer

    query_plan = build_query_plan(args.query, enabled=not args.no_query_rewrite)
    if query_plan.retrieval_query != args.query:
        print(f"retrieval_query={query_plan.retrieval_query}")

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    connections.connect(alias="default", host=args.host, port=args.port)
    collection = Collection(args.collection)
    collection.load()

    model = SentenceTransformer(args.model)
    embedding = model.encode([query_plan.retrieval_query], normalize_embeddings=True)
    dense = milvus_candidates(collection, np.asarray(embedding, dtype="float32").tolist(), args)
    sparse = {} if args.no_hybrid else sqlite_candidates(conn, args, query_plan.retrieval_query)

    candidates = merge_candidates(dense, sparse)
    for candidate in candidates:
        hydrate_from_sqlite(conn, candidate)
    as_of = parse_date(args.as_of_date) or date.today()
    ranked = score_candidates(candidates, args, as_of, query_plan)
    selected = select_candidates(ranked, args)

    for rank, candidate in enumerate(selected, start=1):
        text = expand_adjacent(conn, candidate, args.adjacent_window)
        print_candidate(rank, candidate, text)

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from common.rag_finance import build_query_plan
from retrieval.search_milvus import (
    merge_candidates,
    milvus_candidates,
    score_candidates,
    select_candidates,
    sqlite_candidates,
)


@dataclass
class EvalResult:
    question: str
    expected: list[str]
    found: list[str]
    rr: float
    hit_1: bool
    hit_k: bool
    expected_statement_type: str
    top_statement_type: str


def load_cases(path: Path) -> list[dict]:
    cases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            cases.append(json.loads(line))
    return cases


def reciprocal_rank(found: list[str], positives: set[str]) -> float:
    for index, chunk_id in enumerate(found, start=1):
        if chunk_id in positives:
            return 1.0 / index
    return 0.0


def hydrate_from_sqlite(conn: sqlite3.Connection, candidates) -> None:
    for candidate in candidates:
        row = conn.execute("SELECT * FROM chunks WHERE chunk_id=?", (candidate.chunk_id,)).fetchone()
        if row:
            candidate.entity.update(dict(row))


def case_args(base: argparse.Namespace, filters: dict[str, Any]) -> SimpleNamespace:
    values = vars(base).copy()
    option_defaults = {
        "code": None,
        "industry": None,
        "year": None,
        "report_type": None,
        "doc_type": None,
        "announcement_category": None,
        "chunk_type": None,
        "section": None,
        "statement_type": "",
    }
    values.update(option_defaults)
    for key, value in filters.items():
        values[key] = value
    return SimpleNamespace(**values)


def retrieve_one(conn, collection, embedding: list[float], args, query_plan) -> list:
    dense = milvus_candidates(collection, [embedding], args)
    sparse = {} if args.no_hybrid else sqlite_candidates(conn, args, query_plan.retrieval_query)
    candidates = merge_candidates(dense, sparse)
    hydrate_from_sqlite(conn, candidates)
    ranked = score_candidates(candidates, args, date.today(), query_plan)
    return select_candidates(ranked, args)


def evaluate_case(conn, collection, embedding: list[float], case: dict, args, query_plan) -> EvalResult:
    local_args = case_args(args, case.get("metadata_filter", {}))
    selected = retrieve_one(conn, collection, embedding, local_args, query_plan)
    found = [candidate.chunk_id for candidate in selected]
    positives = set(case.get("positive_contexts", []))
    rr = reciprocal_rank(found, positives)
    top_statement_type = selected[0].entity.get("statement_type", "") if selected else ""
    return EvalResult(
        question=case["question"],
        expected=sorted(positives),
        found=found[: args.top_k],
        rr=rr,
        hit_1=bool(found[:1] and found[0] in positives),
        hit_k=bool(positives.intersection(found[: args.top_k])),
        expected_statement_type=case.get("expected_statement_type", ""),
        top_statement_type=top_statement_type,
    )


def print_summary(results: list[EvalResult], top_k: int) -> None:
    total = max(1, len(results))
    hit_1 = sum(result.hit_1 for result in results) / total
    hit_k = sum(result.hit_k for result in results) / total
    mrr = sum(result.rr for result in results) / total
    statement_cases = [result for result in results if result.expected_statement_type]
    statement_acc = (
        sum(result.top_statement_type == result.expected_statement_type for result in statement_cases) / len(statement_cases)
        if statement_cases
        else 0.0
    )
    print("\nSummary")
    print(f"  cases={len(results)}")
    print(f"  Hit@1={hit_1:.3f}")
    print(f"  Hit@{top_k}={hit_k:.3f}")
    print(f"  MRR={mrr:.3f}")
    print(f"  statement_type@1={statement_acc:.3f}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate retrieval Hit@k and MRR on a JSONL eval set.")
    parser.add_argument("--eval-file", default="config/eval_queries.jsonl")
    parser.add_argument("--db", default="data/metadata.sqlite")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="19530")
    parser.add_argument("--collection", default="a_share_chunks")
    parser.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=50)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--per-source-limit", type=int, default=0)
    parser.add_argument("--no-hybrid", action="store_true")
    parser.add_argument("--no-query-rewrite", action="store_true")
    parser.add_argument("--dense-weight", type=float, default=1.0)
    parser.add_argument("--bm25-weight", type=float, default=1.0)
    parser.add_argument("--rrf-k", type=int, default=60)
    parser.add_argument("--finance-rule-weight", type=float, default=1.0)
    parser.add_argument("--freshness-weight", type=float, default=0.15)
    parser.add_argument("--half-life-days", type=float, default=180.0)
    parser.add_argument("--authority-weight", type=float, default=0.05)
    parser.add_argument("--ef", type=int, default=64)
    parser.add_argument("--show-failures", type=int, default=20)
    parser.add_argument("--progress-every", type=int, default=100)
    args = parser.parse_args()

    cases = load_cases(Path(args.eval_file))
    if args.limit:
        cases = cases[: args.limit]

    from pymilvus import Collection, connections
    from sentence_transformers import SentenceTransformer

    query_plans = [build_query_plan(case["question"], enabled=not args.no_query_rewrite) for case in cases]

    print(f"Loading embedding model: {args.model}")
    model = SentenceTransformer(args.model)
    embeddings = model.encode(
        [plan.retrieval_query for plan in query_plans],
        batch_size=64,
        normalize_embeddings=True,
        show_progress_bar=True,
    )

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    connections.connect(alias="default", host=args.host, port=args.port)
    collection = Collection(args.collection)
    collection.load()

    results: list[EvalResult] = []
    failures: list[EvalResult] = []
    for index, (case, embedding, query_plan) in enumerate(zip(cases, np.asarray(embeddings, dtype="float32").tolist(), query_plans), start=1):
        result = evaluate_case(conn, collection, embedding, case, args, query_plan)
        results.append(result)
        if not result.hit_k:
            failures.append(result)
        if args.progress_every and index % args.progress_every == 0:
            print(f"evaluated {index}/{len(cases)}")

    print_summary(results, args.top_k)
    if failures:
        print(f"\nFailures shown: {min(args.show_failures, len(failures))}/{len(failures)}")
        for failure in failures[: args.show_failures]:
            print(f"FAIL question={failure.question}")
            print(f"  expected={failure.expected} found={failure.found} rr={failure.rr:.3f}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Iterable

import numpy as np

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from common.rag_finance import extract_metric_terms, infer_statement_type


def iter_unindexed_chunks(conn: sqlite3.Connection, collection_name: str, model_name: str, limit: int) -> Iterable[sqlite3.Row]:
    query = """
        SELECT c.*
        FROM chunks c
        LEFT JOIN vector_index_records v
          ON c.chunk_id = v.chunk_id AND v.collection_name = ? AND v.model_name = ?
        WHERE v.chunk_id IS NULL
        ORDER BY c.code, c.year, c.report_type, c.chunk_index
    """
    if limit:
        query += " LIMIT ?"
        yield from conn.execute(query, (collection_name, model_name, limit))
    else:
        yield from conn.execute(query, (collection_name, model_name))


def init_index_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS vector_index_records (
            collection_name TEXT NOT NULL,
            chunk_id TEXT NOT NULL,
            model_name TEXT NOT NULL,
            indexed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (collection_name, chunk_id)
        )
        """
    )
    conn.commit()


def connect_milvus(args: argparse.Namespace):
    from pymilvus import connections

    connections.connect(alias="default", host=args.host, port=args.port)


def create_collection(collection_name: str, dim: int, reset: bool):
    from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, utility

    if reset and utility.has_collection(collection_name):
        utility.drop_collection(collection_name)
    if utility.has_collection(collection_name):
        collection = Collection(collection_name)
        collection.load()
        return collection

    fields = [
        FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, is_primary=True, max_length=160),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=8192),
        FieldSchema(name="display_text", dtype=DataType.VARCHAR, max_length=8192),
        FieldSchema(name="doc_type", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="chunk_type", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="code", dtype=DataType.VARCHAR, max_length=16),
        FieldSchema(name="company", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="industry", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="year", dtype=DataType.INT64),
        FieldSchema(name="report_type", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="title", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="publish_date", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="source_type", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="source_authority_score", dtype=DataType.FLOAT),
        FieldSchema(name="announcement_category", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="announcement_tags", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="section", dtype=DataType.VARCHAR, max_length=256),
        FieldSchema(name="statement_type", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="metric_terms", dtype=DataType.VARCHAR, max_length=1024),
        FieldSchema(name="section_level", dtype=DataType.INT64),
        FieldSchema(name="page_start", dtype=DataType.INT64),
        FieldSchema(name="page_end", dtype=DataType.INT64),
        FieldSchema(name="source_pdf", dtype=DataType.VARCHAR, max_length=1024),
        FieldSchema(name="source_url", dtype=DataType.VARCHAR, max_length=1024),
    ]
    schema = CollectionSchema(fields=fields, description="A-share report and announcement chunks")
    collection = Collection(collection_name, schema)
    collection.create_index(
        field_name="embedding",
        index_params={"metric_type": "COSINE", "index_type": "HNSW", "params": {"M": 16, "efConstruction": 200}},
    )
    for field_name in [
        "code",
        "industry",
        "year",
        "report_type",
        "doc_type",
        "chunk_type",
        "publish_date",
        "source_type",
        "announcement_category",
        "section",
        "statement_type",
    ]:
        collection.create_index(field_name=field_name)
    collection.load()
    return collection


def clean_varchar(value: object, max_len: int) -> str:
    text = str(value or "")
    return text[:max_len]


def row_value(row: sqlite3.Row, key: str, default: object = "") -> object:
    return row[key] if key in row.keys() else default


def build_rows(chunks: list[sqlite3.Row], embeddings: np.ndarray) -> list[list[object]]:
    return [
        [row["chunk_id"] for row in chunks],
        embeddings.astype("float32").tolist(),
        [clean_varchar(row["embed_text"] or row["text"], 8192) for row in chunks],
        [clean_varchar(row["display_text"] or row["text"], 8192) for row in chunks],
        [clean_varchar(row["doc_type"], 32) for row in chunks],
        [clean_varchar(row["chunk_type"], 64) for row in chunks],
        [clean_varchar(row["code"], 16) for row in chunks],
        [clean_varchar(row["company"], 128) for row in chunks],
        [clean_varchar(row["industry"], 64) for row in chunks],
        [int(row["year"] or 0) for row in chunks],
        [clean_varchar(row["report_type"], 32) for row in chunks],
        [clean_varchar(row["title"], 512) for row in chunks],
        [clean_varchar(row["publish_date"], 32) for row in chunks],
        [clean_varchar(row["source_type"], 64) for row in chunks],
        [float(row["source_authority_score"] if row["source_authority_score"] is not None else 1.0) for row in chunks],
        [clean_varchar(row["announcement_category"], 64) for row in chunks],
        [clean_varchar(row["announcement_tags"], 256) for row in chunks],
        [clean_varchar(row["section"], 256) for row in chunks],
        [clean_varchar(row_value(row, "statement_type") or infer_statement_type(row["section"], row["embed_text"] or row["text"]), 32) for row in chunks],
        [clean_varchar(row_value(row, "metric_terms") or extract_metric_terms(row["embed_text"] or row["text"], row["section"]), 1024) for row in chunks],
        [int(row["section_level"] or 0) for row in chunks],
        [int(row["page_start"] or 0) for row in chunks],
        [int(row["page_end"] or 0) for row in chunks],
        [clean_varchar(row["source_pdf"], 1024) for row in chunks],
        [clean_varchar(row["source_url"], 1024) for row in chunks],
    ]


def mark_indexed(conn: sqlite3.Connection, collection_name: str, model_name: str, chunks: list[sqlite3.Row]) -> None:
    conn.executemany(
        """
        INSERT OR REPLACE INTO vector_index_records (collection_name, chunk_id, model_name)
        VALUES (?, ?, ?)
        """,
        [(collection_name, row["chunk_id"], model_name) for row in chunks],
    )
    conn.commit()


def build_index(args: argparse.Namespace) -> int:
    from sentence_transformers import SentenceTransformer

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    init_index_table(conn)

    if args.reset_index_records:
        conn.execute("DELETE FROM vector_index_records WHERE collection_name=?", (args.collection,))
        conn.commit()

    print(f"Loading embedding model: {args.model}", flush=True)
    model = SentenceTransformer(args.model)
    dim = model.get_sentence_embedding_dimension()

    connect_milvus(args)
    collection = create_collection(args.collection, dim, args.reset_collection)

    chunks = list(iter_unindexed_chunks(conn, args.collection, args.model, args.limit))
    print(f"Chunks to index: {len(chunks)}", flush=True)
    inserted = 0
    for start in range(0, len(chunks), args.batch_size):
        batch = chunks[start : start + args.batch_size]
        texts = [row["embed_text"] or row["text"] for row in batch]
        embeddings = model.encode(texts, batch_size=args.encode_batch_size, normalize_embeddings=True, show_progress_bar=False)
        collection.insert(build_rows(batch, np.asarray(embeddings)))
        mark_indexed(conn, args.collection, args.model, batch)
        inserted += len(batch)
        print(f"  indexed {inserted}/{len(chunks)}", flush=True)

    if inserted:
        collection.flush()
        collection.load()
    print(f"Indexed chunks: {inserted}", flush=True)
    conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Embed SQLite chunks and insert them into Milvus.")
    parser.add_argument("--db", default="data/metadata.sqlite")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default="19530")
    parser.add_argument("--collection", default="a_share_chunks")
    parser.add_argument("--model", default="BAAI/bge-small-zh-v1.5")
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--encode-batch-size", type=int, default=32)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--reset-collection", action="store_true")
    parser.add_argument("--reset-index-records", action="store_true")
    return parser


def main() -> int:
    return build_index(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())

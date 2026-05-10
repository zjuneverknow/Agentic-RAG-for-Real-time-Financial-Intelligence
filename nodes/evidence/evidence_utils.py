from __future__ import annotations

from typing import Any, Dict, List, Optional

from langchain_core.documents import Document


def document_to_evidence(
    doc: Document,
    *,
    source_type: str,
    source_name: str,
    default_score: float = 0.0,
) -> Dict[str, Any]:
    metadata = dict(doc.metadata or {})
    citation = metadata.get("source") or metadata.get("url") or source_name
    as_of_date = metadata.get("timestamp") or metadata.get("updated_at") or metadata.get("created_at") or ""

    scores: Dict[str, float] = {}
    if "dense_score" in metadata:
        scores["dense"] = float(metadata["dense_score"])
    if "sparse_score" in metadata:
        scores["sparse"] = float(metadata["sparse_score"])
    if "hybrid_score" in metadata:
        scores["hybrid"] = float(metadata["hybrid_score"])
    if not scores and default_score:
        scores["final"] = float(default_score)

    return {
        "source_type": source_type,
        "source_name": source_name,
        "content": doc.page_content,
        "metadata": metadata,
        "scores": scores,
        "as_of_date": as_of_date,
        "citation": citation,
    }


def extend_evidence(
    state: Dict[str, Any],
    new_items: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    current = list(state.get("evidence_candidates", []))
    current.extend(new_items)
    return current


def evidence_to_document(item: Dict[str, Any]) -> Document:
    metadata = dict(item.get("metadata") or {})
    if item.get("citation") and "source" not in metadata:
        metadata["source"] = item["citation"]
    return Document(page_content=item.get("content", ""), metadata=metadata)


def selected_evidence_to_documents(items: Optional[List[Dict[str, Any]]]) -> List[Document]:
    return [evidence_to_document(item) for item in (items or []) if item.get("content")]

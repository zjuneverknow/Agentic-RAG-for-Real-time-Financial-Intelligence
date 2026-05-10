from chains.grader_chain import build_retrieval_grader, grade_document
from nodes.evidence.evidence_utils import evidence_to_document, selected_evidence_to_documents


def selector_node(state):
    question = state.get("active_question") or state["question"]
    evidence_candidates = list(state.get("evidence_candidates", []))

    if not evidence_candidates:
        documents = state.get("documents", [])
        evidence_candidates = [
            {
                "source_type": "milvus",
                "source_name": doc.metadata.get("retrieval_source", "Retrieved Document"),
                "content": doc.page_content,
                "metadata": dict(doc.metadata or {}),
                "scores": {},
                "as_of_date": "",
                "citation": doc.metadata.get("source", "Retrieved Document"),
            }
            for doc in documents
        ]

    if not evidence_candidates:
        return {
            "selected_evidence": [],
            "documents": [],
            "web_search": "Yes",
            "status": "fallback",
            "control": {
                **(state.get("control") or {}),
                "last_action": "selector",
            },
        }

    grader = build_retrieval_grader()
    selected_evidence = []

    for item in evidence_candidates:
        decision = grade_document(grader, question, item.get("content", ""))
        if decision == "yes":
            selected_evidence.append(item)

    selected_docs = selected_evidence_to_documents(selected_evidence)
    web_search = "Yes" if not selected_evidence else "No"

    return {
        "selected_evidence": selected_evidence,
        "documents": selected_docs,
        "web_search": web_search,
        "active_question": question,
        "status": "success" if selected_evidence else "fallback",
        "retrieval": {
            **(state.get("retrieval") or {}),
            "selected_evidence": selected_evidence,
        },
        "control": {
            **(state.get("control") or {}),
            "last_action": "selector",
        },
        "last_action": "selector",
    }

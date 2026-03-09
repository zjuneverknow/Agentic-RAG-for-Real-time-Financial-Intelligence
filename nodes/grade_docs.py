from chains.grader_chain import build_retrieval_grader, grade_document


def grade_documents_node(state):
    question = state.get("active_question") or state["question"]
    documents = state.get("documents", [])

    if not documents:
        return {"documents": [], "web_search": "Yes"}

    grader = build_retrieval_grader()
    filtered_docs = []

    for doc in documents:
        decision = grade_document(grader, question, doc.page_content)
        if decision == "yes":
            filtered_docs.append(doc)

    # Avoid eager web-search escalation. Retrieve node handles Finnhub fallback first.
    web_search = "Yes" if not filtered_docs else "No"
    return {"documents": filtered_docs, "web_search": web_search, "active_question": question}

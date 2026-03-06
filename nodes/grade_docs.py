from chains.grader_chain import build_retrieval_grader, grade_document


def grade_documents_node(state):
    question = state["question"]
    documents = state.get("documents", [])

    grader = build_retrieval_grader()
    filtered_docs = []
    web_search = "No"

    for doc in documents:
        decision = grade_document(grader, question, doc.page_content)
        if decision == "yes":
            filtered_docs.append(doc)
        else:
            web_search = "Yes"

    if not filtered_docs:
        web_search = "Yes"

    return {"documents": filtered_docs, "web_search": web_search}

import os
import re

from chains.router_chain import build_router_chain

A_SHARE_CODE_PATTERN = re.compile(r"(?<!\d)(\d{6})(?!\d)")
A_SHARE_TERMS = (
    "\u4e00\u5b63\u5ea6",
    "\u534a\u5e74\u5ea6",
    "\u4e09\u5b63\u5ea6",
    "\u5e74\u62a5",
    "\u5b63\u62a5",
    "\u8d22\u62a5",
    "\u516c\u544a",
    "\u8425\u4e1a\u6536\u5165",
    "\u51c0\u5229\u6da6",
    "\u5f52\u6bcd",
    "\u8d44\u4ea7\u8d1f\u503a\u8868",
    "\u5229\u6da6\u8868",
    "\u73b0\u91d1\u6d41\u91cf\u8868",
)


def _prefer_milvus_for_local_filings(question: str) -> tuple[bool, str]:
    text = question or ""
    code_match = A_SHARE_CODE_PATTERN.search(text)
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in text)
    has_filing_term = any(term in text for term in A_SHARE_TERMS)
    if code_match:
        return True, code_match.group(1)
    if has_cjk and has_filing_term:
        return True, ""
    return False, ""


def planner_node(state):
    question = state.get("active_question") or state.get("original_question") or state["question"]
    chain = build_router_chain()
    result = chain.invoke({"question": question})

    symbol = (result.symbol or "").strip().upper()
    company_name = (result.company_name or "").strip()
    secondary_sources = list(dict.fromkeys(result.secondary_sources or []))
    datasource = result.primary_source

    prefer_milvus, a_share_code = _prefer_milvus_for_local_filings(question)
    if prefer_milvus:
        datasource = "milvus"
        symbol = a_share_code
        secondary_sources = [source for source in secondary_sources if source != "source_api"]

    flag = (os.getenv("DEBUG_ROUTING") or "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        print(
            (
                "[planner] "
                f"intent={result.intent} primary={datasource} secondary={secondary_sources} "
                f"symbol={symbol!r} fresh={result.requires_freshness} expand={result.needs_query_expansion} "
                f"multi={result.needs_multi_source} question={question!r}"
            ),
            flush=True,
        )

    query_state = {
        "original_question": state.get("original_question") or state.get("question", question),
        "active_question": question,
        "intent": result.intent,
        "entities": {"company_name": company_name} if company_name else {},
        "symbol": symbol,
        "requires_freshness": result.requires_freshness,
    }
    plan_state = {
        "primary_source": datasource,
        "secondary_sources": secondary_sources,
        "needs_query_expansion": result.needs_query_expansion,
        "needs_multi_source": result.needs_multi_source,
        "next_action": "generate" if datasource == "direct_chat" else datasource,
    }
    control_state = {
        "last_action": "planner",
    }

    return {
        "original_question": query_state["original_question"],
        "active_question": question,
        "intent": result.intent,
        "entities": query_state["entities"],
        "symbol": symbol,
        "requires_freshness": result.requires_freshness,
        "primary_source": datasource,
        "secondary_sources": secondary_sources,
        "needs_query_expansion": result.needs_query_expansion,
        "needs_multi_source": result.needs_multi_source,
        "datasource": datasource,
        "next_step": plan_state["next_action"],
        "query": query_state,
        "plan": plan_state,
        "control": control_state,
        "last_action": "planner",
    }


def router_node(state):
    return planner_node(state)

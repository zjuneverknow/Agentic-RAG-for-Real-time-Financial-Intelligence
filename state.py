from typing import Any, Dict, List, Literal, TypedDict

from langchain_core.documents import Document


SourceName = Literal["source_api", "milvus", "web_search", "direct_chat"]
IntentName = Literal["fact", "summary", "compare", "reasoning", "chat"]
ReasoningMode = Literal["rag_plus", "cot_rag", "hoprag", "trace", "rare"]
ControlStatus = Literal["success", "fallback", "failed"]


class TraceEvent(TypedDict, total=False):
    step: str
    input: Dict[str, Any]
    output_summary: Dict[str, Any]
    status: str
    latency_ms: int
    failure_reason: str
    timestamp: str


class QueryState(TypedDict, total=False):
    original_question: str
    active_question: str
    rewritten_question: str
    intent: IntentName
    entities: Dict[str, Any]
    symbol: str
    code: str
    company: str
    metrics: List[str]
    market_metrics: List[str]
    entity: Dict[str, Any]
    time_range: Dict[str, str]
    requires_freshness: bool
    evidence_needs: List[Dict[str, Any]]


class ToolPlanItem(TypedDict, total=False):
    tool: str
    source: SourceName
    purpose: str
    args: Dict[str, Any]
    optional: bool


class AnswerContract(TypedDict, total=False):
    must_answer: List[str]
    must_include: List[str]
    citation_required: bool
    freshness_required: bool
    numeric_check_required: bool


class PlanState(TypedDict, total=False):
    primary_source: SourceName
    secondary_sources: List[SourceName]
    tool_plan: List[ToolPlanItem]
    reasoning_mode: ReasoningMode
    answer_contract: AnswerContract
    needs_query_expansion: bool
    needs_multi_source: bool
    next_action: str
    evidence_needs: List[Dict[str, Any]]


class EvidenceItem(TypedDict, total=False):
    source_type: Literal["finnhub", "milvus", "web", "memory"]
    source_name: str
    source_url: str
    content: str
    metadata: Dict[str, Any]
    scores: Dict[str, float]
    as_of_date: str
    retrieved_at: str
    citation: str
    company: str
    code: str
    symbol: str
    metric_name: str
    metric_value: Any
    unit: str
    period: str
    statement_type: str
    confidence: float
    freshness_score: float
    authority_score: float


class EvidenceFact(TypedDict, total=False):
    metric: str
    value: str
    unit: str
    period: str
    citation: str
    source_url: str
    chunk_id: str
    confidence: float


class RetrievalState(TypedDict, total=False):
    evidence_candidates: List[EvidenceItem]
    selected_evidence: List[EvidenceItem]
    evidence_facts: List[EvidenceFact]
    retrieval_path: List[str]
    retrieval_failures: List[str]
    retrieval_source: str
    retrieval_score: float


class ContextState(TypedDict, total=False):
    context_text: str
    context_documents: List[Document]
    token_budget: int
    token_estimate: int
    dropped_items: List[Dict[str, Any]]


class AnswerState(TypedDict, total=False):
    draft_answer: str
    final_answer: str
    citations: List[str]
    confidence: float
    verification: Dict[str, Any]


class ControlState(TypedDict, total=False):
    status: ControlStatus
    retry_count: int
    rewrite_count: int
    failure_reason: str
    last_action: str
    run_id: str


class GraphState(TypedDict, total=False):
    # Legacy compatibility fields
    question: str
    active_question: str
    rewritten_question: str
    symbol: str
    datasource: SourceName
    next_step: Literal["source_api", "milvus", "web_search", "generate"]
    generation: str
    web_search: Literal["Yes", "No"]
    api_failed: bool
    documents: List[Document]
    retry_count: int
    rewrite_count: int
    retrieval_path: List[str]
    last_action: str
    status: ControlStatus
    retrieval_source: str
    retrieval_score: float

    # V2 grouped state
    query: QueryState
    plan: PlanState
    retrieval: RetrievalState
    context: ContextState
    answer: AnswerState
    control: ControlState
    trace_events: List[TraceEvent]
    run_id: str

    # V2 flattened convenience fields
    original_question: str
    intent: IntentName
    entities: Dict[str, Any]
    code: str
    company: str
    metrics: List[str]
    market_metrics: List[str]
    entity: Dict[str, Any]
    time_range: Dict[str, str]
    requires_freshness: bool
    primary_source: SourceName
    secondary_sources: List[SourceName]
    tool_plan: List[ToolPlanItem]
    evidence_needs: List[Dict[str, Any]]
    reasoning_mode: ReasoningMode
    answer_contract: AnswerContract
    needs_query_expansion: bool
    needs_multi_source: bool
    evidence_candidates: List[EvidenceItem]
    selected_evidence: List[EvidenceItem]
    evidence_facts: List[EvidenceFact]
    retrieval_failures: List[str]
    context_text: str
    context_documents: List[Document]
    token_budget: int
    token_estimate: int
    dropped_items: List[Dict[str, Any]]
    draft_answer: str
    final_answer: str
    citations: List[str]
    confidence: float
    verification: Dict[str, Any]
    failure_reason: str

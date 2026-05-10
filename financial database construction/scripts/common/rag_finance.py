from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


STATEMENT_LABELS = {
    "balance_sheet": "资产负债表",
    "income_statement": "利润表",
    "cash_flow": "现金流量表",
    "equity_statement": "所有者权益变动表",
}

STATEMENT_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "income_statement",
        (
            "利润表",
            "营业收入",
            "营业总收入",
            "营业成本",
            "营业利润",
            "利润总额",
            "净利润",
            "归属于母公司",
            "归属于上市公司股东",
            "少数股东损益",
            "每股收益",
            "研发费用",
            "销售费用",
            "管理费用",
            "财务费用",
        ),
    ),
    (
        "balance_sheet",
        (
            "资产负债表",
            "流动资产",
            "非流动资产",
            "货币资金",
            "应收账款",
            "存货",
            "资产总计",
            "流动负债",
            "非流动负债",
            "负债合计",
            "所有者权益",
            "期末余额",
            "期初余额",
        ),
    ),
    (
        "cash_flow",
        (
            "现金流量表",
            "经营活动产生的现金流量",
            "投资活动产生的现金流量",
            "筹资活动产生的现金流量",
            "现金及现金等价物",
            "现金流量净额",
            "销售商品、提供劳务收到的现金",
        ),
    ),
    (
        "equity_statement",
        (
            "所有者权益变动表",
            "股本",
            "资本公积",
            "盈余公积",
            "未分配利润",
            "所有者权益变动",
        ),
    ),
]

METRIC_TERMS: tuple[str, ...] = (
    "营业收入",
    "营业总收入",
    "营业成本",
    "营业总成本",
    "研发费用",
    "销售费用",
    "管理费用",
    "财务费用",
    "营业利润",
    "利润总额",
    "净利润",
    "归属于母公司所有者的净利润",
    "归属于上市公司股东的净利润",
    "扣除非经常性损益后的净利润",
    "少数股东损益",
    "基本每股收益",
    "稀释每股收益",
    "货币资金",
    "交易性金融资产",
    "应收票据",
    "应收账款",
    "应收款项融资",
    "预付款项",
    "存货",
    "流动资产合计",
    "资产总计",
    "短期借款",
    "应付票据",
    "应付账款",
    "合同负债",
    "流动负债合计",
    "负债合计",
    "所有者权益合计",
    "经营活动产生的现金流量净额",
    "投资活动产生的现金流量净额",
    "筹资活动产生的现金流量净额",
    "现金及现金等价物净增加额",
)

QUERY_EXPANSIONS = {
    "归母净利润": "归属于母公司所有者的净利润 归属于上市公司股东的净利润",
    "归母": "归属于母公司所有者 归属于上市公司股东",
    "营收": "营业收入 营业总收入",
    "收入": "营业收入 营业总收入",
    "净利": "净利润 归属于母公司所有者的净利润",
    "扣非": "扣除非经常性损益后的净利润",
    "每股收益": "基本每股收益 稀释每股收益",
    "现金流": "现金流量 经营活动产生的现金流量净额",
}


@dataclass(frozen=True)
class QueryPlan:
    original_query: str
    retrieval_query: str
    statement_hints: tuple[str, ...]
    metric_hints: tuple[str, ...]


def normalize_spaces(text: object) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def unique_join(values: Iterable[str], sep: str = " ") -> str:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = value.strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return sep.join(result)


def infer_statement_type(section: object, text: object = "") -> str:
    haystack = normalize_spaces(f"{section or ''}\n{text or ''}")
    section_text = normalize_spaces(section)
    for statement_type, keywords in STATEMENT_RULES:
        if any(keyword in section_text for keyword in keywords):
            return statement_type
    best_type = ""
    best_hits = 0
    for statement_type, keywords in STATEMENT_RULES:
        hits = sum(1 for keyword in keywords if keyword in haystack)
        if hits > best_hits:
            best_type = statement_type
            best_hits = hits
    return best_type if best_hits >= 2 else ""


def extract_metric_terms(text: object, section: object = "") -> str:
    haystack = normalize_spaces(f"{section or ''}\n{text or ''}")
    terms = [term for term in METRIC_TERMS if normalize_spaces(term) in haystack]
    statement_type = infer_statement_type(section, text)
    if statement_type:
        terms.insert(0, STATEMENT_LABELS[statement_type])
    return unique_join(terms)


def build_query_plan(query: str, enabled: bool = True) -> QueryPlan:
    expanded = [query]
    compact_query = normalize_spaces(query)
    for keyword, expansion in QUERY_EXPANSIONS.items():
        if keyword in compact_query:
            expanded.append(expansion)

    retrieval_query = unique_join(expanded)
    statement_hints = []
    for statement_type, keywords in STATEMENT_RULES:
        if any(keyword in compact_query for keyword in keywords):
            statement_hints.append(statement_type)

    metric_hints = [term for term in METRIC_TERMS if normalize_spaces(term) in compact_query]
    if not enabled:
        retrieval_query = query
    return QueryPlan(
        original_query=query,
        retrieval_query=retrieval_query,
        statement_hints=tuple(statement_hints),
        metric_hints=tuple(metric_hints),
    )


def finance_rule_score(query_plan: QueryPlan, entity_get, text: object = "") -> float:
    section = entity_get("section") or ""
    statement_type = entity_get("statement_type") or infer_statement_type(section, text)
    metric_terms = str(entity_get("metric_terms") or extract_metric_terms(text, section))
    score = 0.0

    if query_plan.statement_hints:
        if statement_type in query_plan.statement_hints:
            score += 0.18
        elif statement_type:
            score -= 0.05

    compact_text = normalize_spaces(f"{section} {metric_terms} {text}")
    compact_query = normalize_spaces(query_plan.retrieval_query)
    overlap = 0
    for term in METRIC_TERMS:
        compact_term = normalize_spaces(term)
        if compact_term in compact_query and compact_term in compact_text:
            overlap += 1
    score += min(0.18, overlap * 0.04)
    return score


def rrf_score(rank: int, k: int = 60) -> float:
    return 1.0 / (k + max(1, rank))

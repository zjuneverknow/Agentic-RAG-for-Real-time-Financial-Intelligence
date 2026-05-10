# Skill Authoring Guide

这份文档用于指导其他 agent 或开发者为本项目编写可维护、可触发、可复用的 Skill。是给构建 Skill 的人和 agent 使用的设计规范。

## 1. Skill 的目标

Skill 的作用不是把所有知识塞进一个超长 prompt，而是把特定能力拆成可触发、可按需加载、可验证的操作手册。

一个好的 Skill 应该满足：

- 触发条件清楚：agent 能从 description 判断什么时候使用。
- 职责单一：一个 Skill 只解决一类问题。
- 操作具体：正文里给流程、命令、输出格式和避坑点。
- 细节分层：常用流程放 `SKILL.md`，长文档放 `references/`，确定性操作放 `scripts/`，模板资源放 `assets/`。
- 可交付：其他 agent 读完后能稳定复现同样的工作方式。

## 2. 推荐目录结构

```text
my-skill/
├── SKILL.md
├── scripts/
│   ├── validate.py
│   └── build_index.py
├── references/
│   ├── source-routing-guide.md
│   └── few-shot-examples.md
└── assets/
    └── config-template.json
```

其中只有 `SKILL.md` 是必须的，其余目录按需添加。

## 3. 三层上下文设计

Skill 应按三层组织信息：

```text
L1: YAML metadata
    常驻或预扫描信息，通常 100 tokens 左右。
    agent 用它判断是否触发 Skill。

L2: SKILL.md body
    触发后读取的操作手册。
    建议少于 500 行，少于 5K tokens。

L3: references / scripts / assets
    仅在需要细节、脚本或模板时读取。
    不要默认把所有参考文档一次性塞进上下文。
```

核心原则：先让 agent 通过 L1 正确触发，再通过 L2 正确执行，最后按需读取 L3。

## 4. SKILL.md 格式

每个 `SKILL.md` 必须包含 YAML frontmatter 和 Markdown 正文。

```markdown
---
name: financial-query-understanding
description: >
  Use when the finance agent needs to classify a financial question,
  resolve entities such as stocks, ETFs, indices, crypto assets, or
  macro topics, and route the query to the correct data source. Do NOT
  use when the task is only to format a final answer.
allowed-tools: Read
---

# Financial Query Understanding

## Goal

Convert the user question into a structured query plan.

## Workflow

1. Detect language, market, and asset class.
2. Resolve entity identifiers.
3. Classify intent.
4. Route to source candidates.
5. Return strict JSON.

## Output

```json
{
  "intent": "fact | summary | comparison | valuation | risk | macro | unknown",
  "entity": {},
  "metrics": [],
  "source_candidates": []
}
```

## Gotchas

- Do not assume every Chinese company mention is an A-share.
- Do not map "纳斯达克100" to Nasdaq Composite.
- Do not invent tickers when the entity is ambiguous.
```

## 5. 如何写好 description

`description` 是最重要的触发入口。它决定 agent 是否会加载这个 Skill。

推荐模板：

```text
Use when [触发条件/关键词] to [目标行动] by [核心操作] while [重要限制].
Do NOT use when [负面触发条件].
```

差的例子：

```yaml
description: 金融分析
```

问题：太宽泛，agent 不知道何时触发，也不知道边界。

好的例子：

```yaml
description: >
  Use when users ask for valuation analysis of a listed company,
  including PE, PB, EV/EBITDA, growth, profitability, and peer comparison.
  The skill guides evidence requirements, valuation logic, and uncertainty
  disclosure. Do NOT use for simple one-number factual lookup.
```

## 6. 职责拆分原则

不要写一个巨大的万能 Skill。超过 500 行时，通常应该拆分。

不推荐：

```text
financial-agent/
  SKILL.md  # query understanding + retrieval + valuation + news + risk + answer generation
```

推荐：

```text
skills/
  financial-query-understanding/
  financial-source-routing/
  financial-fact-retrieval/
  financial-news-analysis/
  financial-valuation-reasoning/
  financial-risk-disclosure/
  financial-answer-contract/
```

每个 Skill 只负责一个明确阶段。

## 7. scripts 的使用原则

需要稳定、确定性执行的任务应写成脚本。

适合放进 `scripts/`：

- 校验 JSON schema。
- 批量检查 Skill frontmatter。
- 生成 few-shot 测试集。
- 检查引用文件是否存在。
- 对比实际输出和期望输出。

不适合放脚本：

- 需要复杂判断的金融推理。
- 需要结合上下文写作的分析。
- 需要根据用户意图灵活选择路径的任务。

示例：

```text
financial-query-understanding/
├── SKILL.md
├── scripts/
│   └── validate_output.py
└── references/
    └── few-shot-examples.md
```

`scripts/validate_output.py` 可以固定检查：

```text
- JSON 是否可解析
- 必填字段是否存在
- intent 是否属于枚举
- source_candidates 是否为空
- ambiguous 情况是否有 clarification_needed
```

## 8. references 的使用原则

`references/` 用来存放长文档、案例库和领域规则。它们不应默认进入上下文。

适合放入 `references/`：

- 金融实体映射规则。
- source routing 详细说明。
- Finnhub / Milvus / Web Search 的边界。
- 财报科目同义词表。
- few-shot examples。
- 输出 JSON schema 的完整说明。

不适合放入 `SKILL.md` 正文的大段内容，都应该拆到 `references/`。

## 9. assets 的使用原则

`assets/` 用来存放模板、配置或静态资源。

适合放入 `assets/`：

- JSON schema 模板。
- YAML 配置模板。
- prompt 模板。
- routing policy 模板。
- evaluation case 模板。

示例：

```json
{
  "intent": "{{INTENT}}",
  "entity": {
    "display_name": "{{DISPLAY_NAME}}",
    "identifiers": {
      "symbol": "{{SYMBOL}}",
      "market": "{{MARKET}}"
    }
  },
  "source_candidates": ["{{SOURCE}}"]
}
```

## 10. Gotchas 是必须项

每个 Skill 都应有 `Gotchas` 部分。它用于写 agent 容易犯的错误。

示例：

```markdown
## Gotchas

- Do not invent missing financial data.
- Do not treat market commentary as audited financial facts.
- Do not use Milvus filings for real-time market prices.
- Do not use Finnhub market metrics for Chinese filing table extraction.
- Do not collapse "Nasdaq", "Nasdaq 100", and "Nasdaq Inc." into one entity.
- Do not answer valuation forecasts as certainty; separate facts, assumptions, and scenarios.
```

Gotchas 的 ROI 很高。它能显著减少 agent 的误触发、误路由和幻觉。

## 11. Finance Agent Skill 建议拆分

本项目建议优先建设以下 Skill。

### 11.1 financial-query-understanding

用途：理解用户问题，生成结构化查询计划。

包含：

- 语言识别。
- 市场识别。
- 资产类别识别。
- 实体解析。
- ticker / code / exchange / market 标准化。
- intent 分类。
- ambiguity detection。
- query rewrite。

不要包含：

- 实际检索。
- 最终答案生成。
- 估值推理。

### 11.2 financial-source-routing

用途：根据意图和实体决定数据源。

包含：

- Milvus filings 适用范围。
- Finnhub market data 适用范围。
- Web search 适用范围。
- 未来 SEC / news cache / sentiment source 适配规则。
- 多源召回优先级。

不要包含：

- 具体回答语言。
- 复杂估值逻辑。

### 11.3 financial-fact-retrieval

用途：规定事实检索的证据要求。

包含：

- 财报科目检索规则。
- 年份、季度、报告类型约束。
- statement_type / metric_terms / chunk_type 使用规则。
- 多 positive context 的评估思想。
- 相邻 chunk 合并规则。

不要包含：

- 新闻观点判断。
- 未来股价预测。

### 11.4 financial-news-analysis

用途：处理消息面、新闻摘要、事件影响。

包含：

- 新闻事件分类。
- source freshness。
- 权威性排序。
- 事件对公司、行业、市场的影响路径。
- 噪音过滤。

不要包含：

- 审计级财报数字抽取。

### 11.5 financial-valuation-reasoning

用途：处理估值、股价展望、情景推理。

包含：

- PE / PB / PS / EV/EBITDA。
- 增长、利润率、现金流。
- 同业比较。
- 多情景推理。
- 风险和不确定性披露。

不要包含：

- 给出确定性买卖建议。
- 编造目标价。

### 11.6 financial-answer-contract

用途：约束最终答案。

包含：

- 必须引用来源。
- 区分事实、解释、假设。
- 缺证据时拒绝或降级回答。
- 数字和单位一致性。
- 时间戳和数据口径说明。

不要包含：

- 检索实现细节。

## 12. 推荐输出格式

每个 Skill 应明确输出格式。

例如 query understanding Skill：

```json
{
  "intent": "valuation",
  "language": "zh",
  "entity": {
    "display_name": "苹果公司",
    "company": "Apple Inc.",
    "identifiers": {
      "symbol": "AAPL",
      "market": "US",
      "exchange": "NASDAQ"
    }
  },
  "metrics": ["pe", "forward_pe"],
  "source_candidates": ["finnhub_market"],
  "ambiguity": {
    "is_ambiguous": false,
    "clarification_needed": false
  }
}
```

例如 answer contract Skill：

```text
结论：
证据：
关键数字：
假设：
风险：
资料来源：
```

## 13. 写 Skill 前的调研流程

创建新 Skill 前，建议先完成：

1. 明确该 Skill 所在链路阶段。
2. 收集 5 到 10 个真实用户问题。
3. 标注正常、边缘、不适用案例。
4. 明确输入和输出。
5. 写 description。
6. 写 Gotchas。
7. 再写 workflow。
8. 将长规则拆到 references。
9. 将可验证逻辑写成 scripts。
10. 用至少 3 个真实场景测试。

## 14. Skill 自查清单

写完后检查：

- [ ] 是否有 `SKILL.md`？
- [ ] 是否有 YAML frontmatter？
- [ ] `name` 是否全小写加连字符？
- [ ] `description` 是否说明触发条件、目标行动和边界？
- [ ] 是否有负面触发说明？
- [ ] 是否少于 500 行？
- [ ] 是否每个 Skill 只做一件事？
- [ ] 是否有清晰 workflow？
- [ ] 是否有输出格式？
- [ ] 是否有 Gotchas？
- [ ] 长规则是否放入 `references/`？
- [ ] 确定性任务是否放入 `scripts/`？
- [ ] 模板是否放入 `assets/`？
- [ ] 是否至少覆盖正常、边缘、不适用三个测试场景？
- [ ] 是否避免要求 agent 假设外部工具已安装？

## 15. 对本项目的特别约定

本项目中有两类 skill 相关目录：

```text
skills_for_design_project/
```

用于给开发协作 agent 阅读，例如本文件、RAG 架构设计、pipeline 打磨方案等。

```text
skills/
```

用于 finance agent 运行时读取。这里放的是业务能力 Skill，例如 query understanding、source routing、valuation reasoning。

不要把开发协作文档直接放进 `skills/`，否则 finance agent 可能误触发。

## 16. 最小可用模板

创建新 Skill 时可以从这个模板开始：

```markdown
---
name: example-skill
description: >
  Use when [trigger condition] to [target action] by [core method].
  Do NOT use when [negative condition].
allowed-tools: Read
---

# Example Skill

## Goal

Describe the single capability this Skill provides.

## When To Use

- Use when ...
- Do not use when ...

## Inputs

- `question`: user question
- `context`: available state or evidence

## Workflow

1. Step one.
2. Step two.
3. Step three.

## Output Format

```json
{
  "field": "value"
}
```

## Quality Checks

- Check ...
- Verify ...

## Gotchas

- Do not ...
- Avoid ...
- If uncertain, ...
```


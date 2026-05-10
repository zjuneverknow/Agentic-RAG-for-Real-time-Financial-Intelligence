# Skill：RAG 系统优化能力

## 1. Skill 定位

RAG 优化不是简单地把文档切块、向量化、检索、塞给大模型，而是围绕一个核心目标：

> 在有限成本和有限延迟下，让系统稳定召回正确上下文，并让 LLM 基于可靠证据生成可控答案。

因此，一个完整的 RAG 优化 Skill 应该覆盖以下几个层次：

1. 数据准备优化
2. 文本分块优化
3. Embedding 与索引优化
4. 检索优化
5. 查询理解与查询重写
6. 上下文组织与生成控制
7. 评估与迭代
8. Agentic RAG 与动态路由

---

## 2. 数据准备优化

### 2.1 核心目标

数据准备的目标是将不同来源、不同格式的原始资料转化为统一、干净、可检索、可追溯的标准文档格式。

RAG 系统的上限很大程度上由数据质量决定。如果原始文档解析错误、结构丢失、表格混乱、标题缺失，那么后续 Embedding、检索和生成都会受到影响。

### 2.2 常见文档解析工具

根据文档类型选择合适解析器：

| 场景                           | 推荐工具                      | 说明                 |
| ------------------------------ | ----------------------------- | -------------------- |
| 普通 txt / markdown            | TextLoader / DirectoryLoader  | 简单高效             |
| PDF 技术文档 / 论文            | PyMuPDF4LLM / Marker / MinerU | 适合 PDF 转 Markdown |
| Word / HTML / PDF 混合文档     | Unstructured                  | 多格式统一解析       |
| 法律合同 / 学术论文 / 复杂 PDF | LlamaParse / Docling          | 结构识别能力更强     |
| 网页 / 在线文档                | FireCrawlLoader               | 适合动态内容抓取     |

数据加载本质上是将非结构化数据转为统一标准格式，你的笔记中也强调了这一点:contentReference[oaicite:1]{index=1}。

### 2.3 优化要点

- 保留标题层级、页码、章节、来源 URL、发布时间等 metadata。
- 表格、公式、代码块不要粗暴转成普通文本。
- 对重复文档、过期文档、低质量 OCR 文档进行清洗。
- 对金融、法律、医疗等领域数据，要特别保留时间戳、版本号、来源可信度。
- 对动态数据源，建立增量更新机制，而不是每次全量重建索引。

---

## 3. 文本分块优化

### 3.1 为什么分块重要

文本分块是 RAG 的第一道关键算法环节。

块太大，会导致：

- 一个向量承载过多语义点，语义被稀释；
- LLM 上下文冗余，容易大海捞针；
- 召回结果相关性下降。

块太小，会导致：

- 信息不完整；
- 上下文断裂；
- LLM 无法理解因果关系、定义关系和跨段落逻辑。

你的笔记中也提到，Embedding 模型和 LLM 都有上下文窗口限制，而且块越长语义越容易稀释:contentReference[oaicite:2]{index=2}。

### 3.2 常见分块方法

#### 方法一：固定长度 / 段落分块

代表方法：优点：

- 实现简单；
- 速度快；
- 成本低。

缺点：

- 容易切断语义；
- 对结构复杂文档效果一般。

适用场景：

- 普通文本；
- 简单 FAQ；
- 低成本原型系统。

------

#### 方法二：递归字符分块

代表方法：

```python
RecursiveCharacterTextSplitter
```

核心逻辑：

按照分隔符优先级递归切分：

```python
["\n\n", "\n", " ", ""]
```

优点：

- 尽量保留段落和句子完整性；
- 比固定长度分块更稳健；
- 是多数 RAG baseline 的首选方案。

适用场景：

- 通用文档；
- 技术文档；
- 中英文混合文档。

------

#### 方法三：语义分块

代表方法：

```python
SemanticChunker
```

核心思想：

> 在语义主题发生明显变化的位置切分。

基本流程：

1. 将文本拆成句子；
2. 对句子及其上下文做 Embedding；
3. 计算相邻句子的语义距离；
4. 找出语义跳跃较大的断点；
5. 合并成语义连续的文本块。

语义分块适合：

- 长文章；
- 法律 / 医疗 / 金融报告；
- 主题变化明显的文档。

缺点：

- 需要额外 Embedding 成本；
- 参数调试更复杂；
- 不一定适合实时系统。

------

#### 方法四：结构化分块

适合 Markdown、HTML、LaTeX、财报、合同、论文等有明显结构的文档。

代表方法：

```python
MarkdownHeaderTextSplitter
Unstructured by_title
LlamaIndex NodeParser
```

核心思路：

> 优先按照标题、章节、列表、表格、页面结构进行切分。

优点：

- 保留文档结构；
- metadata 更丰富；
- 适合后续元数据过滤和分层检索。

你的笔记中提到，MarkdownHeaderTextSplitter 可以利用标题层级分块，并把多级标题注入 metadata。

### 3.3 实战推荐策略

一般不要只使用一种分块方式，而是组合使用：

```text
文档结构解析
    ↓
按标题 / 章节进行一级切分
    ↓
对过长章节做递归分块
    ↓
对关键长文档尝试语义分块
    ↓
保留 metadata
```

推荐 baseline：

```python
RecursiveCharacterTextSplitter(
    chunk_size=500~1000,
    chunk_overlap=50~150
)
```

对于金融研报 / 财报：

```text
按章节切分 > 按段落切分 > 按句子细分 > metadata 注入
```

关键 metadata 包括：

```json
{
  "source": "annual_report_2023.pdf",
  "company": "Tencent",
  "year": 2023,
  "quarter": "Q4",
  "section": "Risk Factors",
  "page": 32,
  "timestamp": "2024-03-20"
}
```

------

## 4. Embedding 与索引优化

### 4.1 Embedding 的作用

在 RAG 中，Embedding 的核心作用是：

> 将用户问题和知识库文本块映射到同一个向量空间中，用于相似度计算和内容召回。

你的笔记中也明确写到，RAG 中 embedding 是为了相似度计算和内容召回服务，Embedding 质量会显著影响召回准确性。

### 4.2 Embedding 模型选择维度

选择 Embedding 模型时，不应该只看榜单分数，而应该综合考虑：

| 维度            | 说明                             |
| --------------- | -------------------------------- |
| Retrieval 表现  | RAG 应重点看检索任务得分         |
| 语言支持        | 中文 / 英文 / 多语言             |
| 领域适配        | 金融、法律、医疗、代码等专业语义 |
| 向量维度        | 影响存储成本和检索速度           |
| 最大 token 长度 | 影响 chunk_size 设计             |
| 推理速度        | 影响在线延迟                     |
| 部署成本        | API 成本或自部署显存成本         |
| 是否支持 hybrid | 如 dense + sparse / multi-vector |

### 4.3 不要只依赖公开榜单

公开榜单只能作为初筛。真正的项目中应该构建私有评测集：

```text
问题 q
标准相关文档块 d+
干扰文档块 d-
标准答案 answer
```

然后比较不同 Embedding 模型在自己业务数据上的表现。

核心指标：

```text
Recall@k
MRR
nDCG
Hit Rate
Context Precision
Context Recall
```

### 4.4 向量数据库选择

常见选择：

| 向量数据库 | 特点                          | 适用场景             |
| ---------- | ----------------------------- | -------------------- |
| Pinecone   | 托管服务，易部署，生产稳定    | 企业项目、快速上线   |
| Milvus     | 开源、高性能、支持大规模      | 自部署、大规模向量库 |
| Qdrant     | Rust 实现，性能好，过滤能力强 | 中小规模、高并发     |
| Weaviate   | GraphQL、多模态生态           | 多模态和快速开发     |
| Chroma     | 轻量简单                      | 原型验证、本地 demo  |
| FAISS      | 高性能向量检索库              | 本地实验、自定义系统 |

向量数据库的核心能力包括高效相似性搜索、高维数据管理、metadata 过滤和可扩展服务能力，这些也是你原笔记中总结的重点。

------

## 5. 索引优化

### 5.1 小块索引，大块生成

一个很重要的 RAG 优化思想是：

> 为检索精确性而索引小块，为生成完整性而提供大块上下文。

你的笔记中在 LlamaIndex 上下文扩展部分也提到：索引时使用单句节点，检索时精准定位，再用 metadata 中的上下文窗口替换原节点内容。

流程：

```text
索引阶段：
句子 / 小段落作为向量节点
每个节点保存前后若干句上下文

检索阶段：
对小节点做相似度搜索

后处理阶段：
将命中节点替换为上下文窗口

生成阶段：
把扩展后的上下文交给 LLM
```

优势：

- 检索更精准；
- 生成上下文更完整；
- 减少“命中一句但缺上下文”的问题。

### 5.2 结构化索引

结构化索引的核心是：

> 在向量索引之外，为每个 chunk 附加可过滤的 metadata。

例如：

```json
{
  "document_type": "财报",
  "company": "阿里巴巴",
  "year": 2024,
  "quarter": "Q2",
  "section": "Management Discussion",
  "language": "zh",
  "source": "annual_report.pdf"
}
```

查询时可以先过滤再向量检索：

```text
document_type == "财报"
AND year == 2024
AND company == "阿里巴巴"
```

再执行语义检索：

```text
“AI 云业务增长原因”
```

这样可以缩小搜索空间，提高准确率和速度。

### 5.3 分层索引 / 路由索引

对于复杂知识库，可以建立两级索引：

```text
一级：摘要索引，用于路由
二级：内容索引，用于问答
```

示例：

```text
用户问题：
“2023 年 Q2 腾讯云业务表现如何？”

第一步：
在摘要索引中判断应该查 “腾讯 / 2023 / Q2 / 财报”

第二步：
带 metadata filter 到内容索引中检索相关 chunk
```

这种方法适合：

- 多公司金融知识库；
- 多表格 Excel；
- 多产品文档；
- 多业务线知识库；
- Agentic RAG 数据源路由。

------

## 6. 检索优化

### 6.1 Dense Retrieval

Dense Retrieval 使用 Embedding 向量做语义召回。

优点：

- 能理解同义表达；
- 适合语义问题；
- 对自然语言问答友好。

缺点：

- 对关键词、数字、专有名词可能不敏感；
- 对拼写错误、代码符号、罕见实体表现不稳定；
- 可解释性较弱。

------

### 6.2 Sparse Retrieval

Sparse Retrieval 使用词法匹配。

代表算法：

```text
TF-IDF
BM25
SPLADE
```

BM25 的优势：

- 对关键词、实体、数字敏感；
- 可解释性强；
- 适合精确匹配。

缺点：

- 不理解语义；
- 对同义词和隐含表达效果差。

------

### 6.3 Hybrid Search

Hybrid Search 结合：

```text
Dense Retrieval：语义召回
Sparse Retrieval：关键词召回
```

你的笔记中将混合检索定义为结合稀疏向量和密集向量优势的搜索技术。

适合场景：

- 金融问答；
- 法律条文；
- 技术文档；
- 代码检索；
- 含大量专有名词、数字、缩写的场景。

### 6.4 RRF 融合

RRF，即 Reciprocal Rank Fusion，核心思想是：

> 不直接比较不同检索器的原始分数，而是融合它们的排名。

公式：

```text
RRFScore(d) = Σ 1 / (rank_i(d) + c)
```

优点：

- 不依赖不同检索器的分数尺度；
- 比线性加权更稳健；
- 适合 BM25 + Vector Search 融合。

你的笔记中也提到，RRF 不关心原始得分，只关心文档在各自结果集中的排名。

### 6.5 Rerank 重排序

第一阶段检索通常追求高召回：

```text
top_k = 20 ~ 100
```

第二阶段 rerank 追求高精度：

```text
Cross-Encoder / BGE-Reranker / LLM Reranker
```

典型流程：

```text
用户问题
   ↓
Hybrid Search 召回 top 50
   ↓
Reranker 重排 top 5
   ↓
上下文压缩
   ↓
LLM 生成答案
```

Rerank 能显著改善：

- 召回内容顺序不准；
- top1 相关性不稳定；
- dense 检索误召回；
- 多 chunk 之间相关性难判断。

------

## 7. 查询理解与查询改写

### 7.1 为什么需要查询优化

用户问题往往存在以下问题：

- 太短；
- 指代不明；
- 口语化；
- 缺少关键词；
- 混合多个子问题；
- 需要结构化过滤；
- 和文档表达方式不一致。

因此，RAG 不应该直接拿原始 query 去检索，而应该先做 query understanding。

------

### 7.2 Query Rewrite

用 LLM 将用户问题改写为更适合检索的形式。

示例：

```text
原问题：
“这个公司最近云业务怎么样？”

改写：
“该公司最近一个季度云计算业务收入、增长率、利润率、管理层展望”
```

适合：

- 用户表达模糊；
- 文档语言更正式；
- 需要补充检索关键词。

------

### 7.3 Multi-Query

将一个问题生成多个不同视角的检索 query。

示例：

```text
原问题：
“腾讯 AI 和云业务的增长逻辑是什么？”

子查询：
1. 腾讯 AI 业务布局
2. 腾讯云收入增长原因
3. 腾讯管理层对 AI 和云业务的展望
4. 腾讯资本开支与 AI 基础设施投入
```

优势：

- 提高召回率；
- 覆盖不同表达；
- 适合复杂分析型问题。

------

### 7.4 Query Decomposition

将复杂问题拆成多个子问题。

示例：

```text
原问题：
“比较阿里和腾讯在 AI 云业务上的竞争优势。”

拆解：
1. 阿里云 AI 业务表现如何？
2. 腾讯云 AI 业务表现如何？
3. 两家公司云收入结构有什么差异？
4. 两家公司 AI 投入和客户生态有什么差异？
5. 谁的竞争优势更强？
```

适合：

- 多实体比较；
- 多跳推理；
- 金融分析；
- 报告生成。

------

### 7.5 HyDE

HyDE 的流程是：

```text
用户问题
   ↓
LLM 生成一个假设性答案文档
   ↓
对假设性文档做 Embedding
   ↓
用该向量检索真实文档
```

你的笔记中也写到，HyDE 不是直接向量化原始查询，而是先生成一个假设性文档，再用它去检索真实文档。

适合：

- 用户问题很短；
- 原始 query 信息不足；
- 文档与问题表达差异较大。

风险：

- 假设文档可能引入错误方向；
- 对事实敏感领域要谨慎使用；
- 最终答案必须基于真实检索文档，而不是 HyDE 生成内容。

------

### 7.6 Self-Query Retriever

Self-Query Retriever 的核心是：

> 让 LLM 从自然语言问题中提取语义查询和 metadata filter。

示例：

```text
用户问题：
“查一下 2023 年 Q2 阿里财报里关于 AI 云业务的表述”

解析结果：
query = "AI 云业务 表现 管理层讨论"
filter = {
  "company": "阿里巴巴",
  "year": 2023,
  "quarter": "Q2",
  "document_type": "财报"
}
```

你的笔记中也提到，自查询检索器会把自然语言查询分解为 query string 和 metadata filter，再发送给向量数据库执行查询。

------

## 8. 上下文组织与生成优化

### 8.1 Context Packing

检索到多个 chunk 后，不应该直接全部拼接，而应该进行上下文组织：

```text
去重
排序
合并相邻 chunk
压缩无关内容
保留来源
控制 token 长度
```

推荐上下文格式：

```text
[Source 1]
title: xxx
date: xxx
section: xxx
content: xxx

[Source 2]
title: xxx
date: xxx
section: xxx
content: xxx
```

### 8.2 引用与可追溯性

RAG 生成时应要求模型：

- 优先基于检索上下文回答；
- 不知道就说不知道；
- 给出引用来源；
- 不把推测说成事实；
- 区分“原文事实”和“模型分析”。

适合金融 RAG 的回答结构：

```text
结论：
证据：
分析：
风险：
不确定性：
来源：
```

### 8.3 格式化输出

对于需要前端展示、API 调用、结构化分析的系统，应该使用结构化输出。

可以用：

```python
JsonOutputParser
PydanticOutputParser
Function Calling
```

你的笔记中提到，LangChain 的 OutputParsers 可以将 LLM 输出解析为字符串、JSON 或 Pydantic 对象。

示例：

```python
from pydantic import BaseModel, Field
from typing import List

class RAGAnswer(BaseModel):
    answer: str = Field(description="最终回答")
    evidence: List[str] = Field(description="引用证据")
    uncertainty: str = Field(description="不确定性说明")
    follow_up: List[str] = Field(description="建议继续查询的问题")
```

------

## 9. 评估与迭代

### 9.1 为什么 RAG 必须评估

RAG 优化不能只靠主观感觉，而要有评估闭环。

常见问题：

```text
召回不到
召回到了但排序靠后
召回内容太长
上下文冲突
LLM 没用检索内容
LLM 幻觉
答案格式不可控
延迟过高
成本过高
```

### 9.2 检索侧指标

| 指标        | 含义                       |
| ----------- | -------------------------- |
| Recall@k    | 正确文档是否出现在 top-k   |
| Precision@k | top-k 中有多少是相关的     |
| MRR         | 第一个正确文档排名是否靠前 |
| nDCG        | 排序质量                   |
| Hit Rate    | 是否命中至少一个相关文档   |

### 9.3 生成侧指标

| 指标              | 含义                       |
| ----------------- | -------------------------- |
| Faithfulness      | 答案是否忠实于上下文       |
| Answer Relevance  | 答案是否回答了问题         |
| Context Precision | 检索上下文是否精确         |
| Context Recall    | 上下文是否覆盖答案所需信息 |
| Citation Accuracy | 引用是否对应真实依据       |

### 9.4 评估集构建

推荐构建如下结构：

```json
{
  "question": "2023 年 Q2 腾讯云业务增长原因是什么？",
  "gold_answer": "...",
  "positive_contexts": ["chunk_id_1", "chunk_id_2"],
  "negative_contexts": ["chunk_id_9"],
  "metadata_filter": {
    "company": "Tencent",
    "year": 2023,
    "quarter": "Q2"
  }
}
```

### 9.5 迭代顺序

建议按以下顺序优化：

```text
1. 检查数据解析质量
2. 调整 chunk_size / overlap
3. 更换或微调 Embedding
4. 加入 metadata filter
5. 加入 Hybrid Search
6. 加入 Reranker
7. 加入 Query Rewrite / Multi-Query
8. 优化 Context Packing
9. 优化 Prompt 和结构化输出
10. 建立自动评估集
```

不要一开始就上 Agentic RAG。先把基础 RAG 的检索质量做扎实。

------

## 10. Agentic RAG 优化

### 10.1 普通 RAG 的局限

普通 RAG 通常是固定流程：

```text
query → retrieve → generate
```

问题是：

- 不会判断是否需要检索；
- 不会选择数据源；
- 不会多轮补充检索；
- 不会判断检索结果是否足够；
- 不会在向量库、数据库、API、网页之间动态切换。

### 10.2 Agentic RAG 的核心

Agentic RAG 的核心是：

> 把 RAG 从固定 pipeline 升级为可决策、可路由、可反思、可调用工具的动态工作流。

典型节点：

```text
Query Classifier
Query Rewriter
Retriever Router
Vector Retriever
BM25 Retriever
SQL / API Tool
Web Search Tool
Reranker
Context Evaluator
Answer Generator
Verifier
Memory Writer
```

### 10.3 金融 RAG 示例架构

```text
用户问题
   ↓
意图识别
   ↓
是否需要实时数据？
   ├── 是：调用 Finnhub / 财经 API
   └── 否：查询向量知识库
   ↓
是否需要企业私有知识？
   ├── 是：检索 Pinecone 私有库
   └── 否：公开数据源
   ↓
Hybrid Search + Rerank
   ↓
上下文充足性判断
   ├── 充足：生成答案
   └── 不足：改写查询 / fallback 到 API / Web
   ↓
生成带引用、风险提示、时间戳的分析
   ↓
必要时写回向量库
```

### 10.4 动态路由策略

可以基于以下特征路由：

| 特征                             | 路由                         |
| -------------------------------- | ---------------------------- |
| 问题包含“最新、今天、实时、股价” | 实时 API                     |
| 问题包含“根据报告、财报、研报”   | 向量知识库                   |
| 问题包含具体结构化条件           | metadata filter / SQL        |
| 问题复杂、多实体比较             | query decomposition          |
| 问题简单常识                     | 直接回答或低成本模型         |
| 检索得分低                       | query rewrite / web fallback |

------


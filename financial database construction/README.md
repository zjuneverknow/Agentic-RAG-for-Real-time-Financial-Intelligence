# A-Share Insight RAG

This repository builds a local A-share official disclosure RAG data pipeline.

Current scope:

- Download official CNINFO reports and high-value announcements.
- Parse PDFs into finance-aware chunks.
- Extract first-pass financial facts.
- Build a Milvus vector index.
- Search with metadata filters, temporal rerank, and source authority scoring.

## Current Status

Data collection is already implemented.

- Target industries: 互联网, 人工智能, 半导体, 新能源.
- Company list: `config/sample_companies.csv`.
- Report range: 2023-2026.
- Main report types: annual, q1, semiannual, q3.
- Recent high-value announcements are categorized by rule.
- Old 白酒 data was removed earlier.

Parser work is now optimized for speed:

- Default parser mode is `auto`.
- `auto` tries OpenDataLoader first, then falls back to Marker if the parsed text is too short.
- OpenDataLoader is much faster and is now the recommended full-dataset parser.
- Marker remains available for high-quality repair parsing.

The important chunking bug has been addressed:

- `重要事项` no longer merges with `财务报表`.
- `合并资产负债表`, `合并利润表`, and `合并现金流量表` become `financial_statement` chunks.
- Page ranges are preserved.

## Environment Notes

Use `uv`.

```powershell
uv sync
```

Torch is configured for CUDA:

```text
torch==2.7.1+cu118
torchvision==0.22.1
torchaudio==2.7.1
marker-pdf>=1.10.2,<2.0.0
opendataloader-pdf>=2.4.2
```

OpenDataLoader requires Java. In this workspace Java was installed at:

```text
E:\Java\temurin-21-jre
```

If Java is not found, set it in the current PowerShell session:

```powershell
$env:JAVA_HOME = "E:\Java\temurin-21-jre"
$env:Path = "E:\Java\temurin-21-jre\bin;" + $env:Path
java -version
```

To set it permanently:

```powershell
[Environment]::SetEnvironmentVariable("JAVA_HOME", "E:\Java\temurin-21-jre", "User")
[Environment]::SetEnvironmentVariable("Path", "E:\Java\temurin-21-jre\bin;" + [Environment]::GetEnvironmentVariable("Path", "User"), "User")
```

Then reopen PowerShell.

## Data Collection

Download annual reports:

```powershell
uv run python scripts/collection/download_reports.py --companies config/sample_companies.csv --years 2023-2025 --report-types annual --out-dir data --db data/metadata.sqlite
```

Download recent periodic reports:

```powershell
uv run python scripts/collection/download_reports.py --companies config/sample_companies.csv --years 2025-2026 --report-types q1,semiannual,q3 --out-dir data --db data/metadata.sqlite
```

Download recent high-value announcements:

```powershell
uv run python scripts/collection/download_announcements.py --companies config/sample_companies.csv --start-date 2025-01-01 --end-date 2026-05-05 --out-dir data --db data/metadata.sqlite
```

Backfill announcement categories if needed:

```powershell
uv run python scripts/maintenance/backfill_announcement_categories.py --db data/metadata.sqlite
uv run python scripts/maintenance/backfill_chunk_announcement_categories.py --db data/metadata.sqlite
```

Check downloaded data:

```powershell
uv run python scripts/collection/check_collection.py --db data/metadata.sqlite
```

## PDF Parsing And Chunking

Recommended full run:

```powershell
uv run python scripts/processing/build_chunks.py --db data/metadata.sqlite --doc-type all --rebuild --parser auto --java-home E:\Java\temurin-21-jre --model-cache-dir data/model_cache/datalab --temp-dir data/tmp
```

Fastest full run, OpenDataLoader only:

```powershell
uv run python scripts/processing/build_chunks.py --db data/metadata.sqlite --doc-type all --rebuild --parser opendataloader --java-home E:\Java\temurin-21-jre --temp-dir data/tmp
```

Marker-only high-quality repair mode:

```powershell
uv run python scripts/processing/build_chunks.py --db data/metadata.sqlite --doc-type report --limit 1 --rebuild --parser marker --model-cache-dir data/model_cache/datalab --temp-dir data/tmp
```

Useful parser options:

- `--parser auto`: OpenDataLoader first, Marker fallback.
- `--parser opendataloader`: fastest mode.
- `--parser marker`: high-quality but slow.
- `--max-pages 80`: only parse the first 80 pages of each PDF.
- `--force-parse`: ignore cached parsed output.
- `--no-ocr-fallback`: disable Marker OCR fallback.
- `--disable-ocr-first-pass`: default; Marker first pass skips OCR.

Chunk types currently used:

- `announcement_event`
- `section_text`
- `table_like`
- `financial_statement`
- `management_discussion`
- `risk_item`
- `business_overview`
- `image_reference`
- `other_text`

Important metadata fields in `chunks`:

- `doc_type`
- `chunk_type`
- `code`
- `company`
- `industry`
- `year`
- `report_type`
- `publish_date`
- `source_type`
- `source_authority_score`
- `announcement_category`
- `announcement_tags`
- `section`
- `section_level`
- `page_start`
- `page_end`
- `source_pdf`
- `source_url`

## Financial Facts

Build the first-pass structured financial facts table:

```powershell
uv run python scripts/processing/build_financial_facts.py --db data/metadata.sqlite --rebuild
```

This extracts simple metrics from `financial_statement` and `table_like` chunks, including:

- 营业收入
- 归母净利润
- 扣非归母净利润
- 经营现金流
- 研发投入
- 基本每股收益
- 加权平均净资产收益率
- 资产总额
- 负债总额
- 货币资金
- 应收账款
- 存货

This is still a first-pass extractor, not a final audited facts engine.

## Milvus

Start Milvus:

```powershell
docker compose -f docker-compose.milvus.yml up -d
```

Rebuild the vector index:

```powershell
uv run python scripts/indexing/build_milvus_index.py --db data/metadata.sqlite --collection a_share_chunks --reset-collection --reset-index-records
```

The index stores `embed_text`, `display_text`, and metadata fields used for filtering.

## Search

Announcement search:

```powershell
uv run python scripts/retrieval/search_milvus.py "中芯国际最近有什么并购重组事项" --industry 半导体 --doc-type announcement --announcement-category merger_reorg
```

Financial statement search:

```powershell
uv run python scripts/retrieval/search_milvus.py "宁德时代2026年一季度货币资金是多少" --code 300750 --year 2026 --report-type q1 --chunk-type financial_statement
```

Search supports these filters:

- `--code`
- `--industry`
- `--year`
- `--report-type`
- `--doc-type`
- `--announcement-category`
- `--chunk-type`
- `--section`

Search also includes simple post-retrieval scoring:

```text
final_score = semantic_score
            + freshness_weight * freshness_score
            + authority_weight * source_authority_score
```

Relevant options:

- `--freshness-weight`
- `--half-life-days`
- `--authority-weight`
- `--as-of-date`
- `--per-source-limit`

## Recommended End-To-End Run

```powershell
uv run python scripts/processing/build_chunks.py --db data/metadata.sqlite --doc-type all --rebuild --parser opendataloader --java-home E:\Java\temurin-21-jre --temp-dir data/tmp
uv run python scripts/processing/build_financial_facts.py --db data/metadata.sqlite --rebuild
uv run python scripts/indexing/build_milvus_index.py --db data/metadata.sqlite --collection a_share_chunks --reset-collection --reset-index-records
```

Then test:

```powershell
uv run python scripts/retrieval/search_milvus.py "宁德时代2026年一季度货币资金是多少" --code 300750 --year 2026 --report-type q1 --chunk-type financial_statement
```

## Handoff Notes For Next Agent

Recent important changes:

- OpenDataLoader was integrated into `scripts/processing/build_chunks.py`.
- Default parser mode is now `auto`.
- `--parser opendataloader` is recommended for full-dataset builds.
- Marker is still available but too slow for all 119 PDFs.
- Java path may need to be set with `--java-home E:\Java\temurin-21-jre`.
- Subprocess output decoding was fixed with UTF-8 plus replacement to avoid Windows GBK errors.
- Marker and OpenDataLoader mojibake text is repaired in normalization.
- `financial_statement` chunk boundaries were tested on 宁德时代 2026Q1.

Known caveats:

- OpenDataLoader is much faster, but some continued balance-sheet chunks may still inherit generic `财务报表` in edge cases.
- Image extraction is wired through OpenDataLoader options, but image understanding/captioning is not yet implemented.
- Financial facts extraction is heuristic and should be treated as a starter layer.
- For high-stakes numerical QA, use retrieved chunks as evidence and eventually build a stronger `financial_facts` extractor from JSON table cells.

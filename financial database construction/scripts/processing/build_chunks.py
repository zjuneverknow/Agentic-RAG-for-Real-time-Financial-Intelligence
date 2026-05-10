from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from common.rag_finance import extract_metric_terms, infer_statement_type

_MARKER_MODELS = None


REPORT_SECTION_KEYWORDS = [
    "公司业务概要",
    "管理层讨论与分析",
    "经营情况讨论与分析",
    "主要会计数据和财务指标",
    "风险因素",
    "重要事项",
    "募集资金使用情况",
    "股份变动及股东情况",
    "环境与社会责任",
    "财务报告",
    "财务报表",
    "合并资产负债表",
    "母公司资产负债表",
    "合并利润表",
    "母公司利润表",
    "合并现金流量表",
    "母公司现金流量表",
    "所有者权益变动表",
    "合并所有者权益变动表",
    "母公司所有者权益变动表",
    "研发投入",
]

FINANCIAL_TABLE_KEYWORDS = [
    "营业收入",
    "净利润",
    "归属于上市公司股东",
    "经营活动产生的现金流量净额",
    "基本每股收益",
    "加权平均净资产收益率",
    "研发投入",
    "资产总额",
    "负债总额",
    "所有者权益",
    "单位：元",
    "单位:元",
    "单位：万元",
    "单位:万元",
    "单位：亿元",
    "单位:亿元",
]

ANNOUNCEMENT_NOISE_PATTERNS = [
    r"证券代码[:：].*",
    r"证券简称[:：].*",
    r"公告编号[:：].*",
    r"A股代码[:：].*",
    r"A股简称[:：].*",
    r"港股代码[:：].*",
    r"港股简称[:：].*",
    r"本公司董事会及全体董事保证本公告内容不存在任何虚假记载、误导性陈述或者重大遗漏.*",
    r"特此公告[。.]?",
    r".*董事会\s*$",
    r"\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日\s*$",
]

PAGE_NO_PATTERN = re.compile(r"^\s*\d{1,4}\s*$")
TOC_LINE_PATTERN = re.compile(r".{2,}[.．。·]{3,}\s*\d{1,4}\s*$")
REPORT_HEADER_PATTERN = re.compile(r".{0,40}(年度报告|半年度报告|季度报告)全文\s*$")
IMAGE_MARKDOWN_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
MOJIBAKE_MARKERS = set("ÃÂÄÅÆÇÈÉÑÖÜàáâãäåæçèéêëìíîïðñòóôõöùúûüĀāĂăĄąŒœŠšŽž€™€œ€�")
SECTION_PREFIX_PATTERN = re.compile(
    r"^\s*((第[一二三四五六七八九十百\d]+[章节])|([一二三四五六七八九十\d]+[、.．])|（[一二三四五六七八九十\d]+）|\([一二三四五六七八九十\d]+\))\s*(.+?)\s*$"
)


@dataclass
class TextBlock:
    text: str
    page_start: int
    page_end: int
    section: str
    section_level: int
    block_type: str


def init_chunks_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            source_id TEXT NOT NULL,
            doc_type TEXT NOT NULL,
            code TEXT NOT NULL,
            company TEXT,
            industry TEXT,
            year INTEGER,
            report_type TEXT,
            title TEXT,
            publish_date TEXT,
            source_type TEXT,
            source_authority_score REAL,
            announcement_category TEXT,
            announcement_tags TEXT,
            section TEXT,
            section_level INTEGER,
            statement_type TEXT,
            metric_terms TEXT,
            chunk_type TEXT NOT NULL,
            page_start INTEGER,
            page_end INTEGER,
            chunk_index INTEGER NOT NULL,
            text TEXT NOT NULL,
            raw_text TEXT,
            embed_text TEXT,
            display_text TEXT,
            text_hash TEXT NOT NULL,
            char_count INTEGER NOT NULL,
            token_estimate INTEGER,
            source_pdf TEXT NOT NULL,
            source_url TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(source_id, text_hash)
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(chunks)").fetchall()}
    migrations = {
        "announcement_category": "ALTER TABLE chunks ADD COLUMN announcement_category TEXT",
        "announcement_tags": "ALTER TABLE chunks ADD COLUMN announcement_tags TEXT",
        "section_level": "ALTER TABLE chunks ADD COLUMN section_level INTEGER",
        "raw_text": "ALTER TABLE chunks ADD COLUMN raw_text TEXT",
        "embed_text": "ALTER TABLE chunks ADD COLUMN embed_text TEXT",
        "display_text": "ALTER TABLE chunks ADD COLUMN display_text TEXT",
        "token_estimate": "ALTER TABLE chunks ADD COLUMN token_estimate INTEGER",
        "source_type": "ALTER TABLE chunks ADD COLUMN source_type TEXT",
        "source_authority_score": "ALTER TABLE chunks ADD COLUMN source_authority_score REAL",
        "statement_type": "ALTER TABLE chunks ADD COLUMN statement_type TEXT",
        "metric_terms": "ALTER TABLE chunks ADD COLUMN metric_terms TEXT",
    }
    for column, statement in migrations.items():
        if column not in columns:
            conn.execute(statement)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_code_year ON chunks(code, year)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_doc_type ON chunks(doc_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_industry ON chunks(industry)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_report_type ON chunks(report_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_chunk_type ON chunks(chunk_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_section ON chunks(section)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_statement_type ON chunks(statement_type)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_announcement_category ON chunks(announcement_category)")
    conn.commit()


def iter_sources(conn: sqlite3.Connection, include_reports: bool, include_announcements: bool) -> Iterable[sqlite3.Row]:
    if include_reports:
        yield from conn.execute(
            """
            SELECT
                'report' AS doc_type,
                code,
                company,
                industry,
                year,
                report_type,
                title,
                publish_date,
                'cninfo' AS source_type,
                1.0 AS source_authority_score,
                '' AS announcement_category,
                '' AS announcement_tags,
                source_url,
                pdf_path,
                code || '_' || year || '_' || report_type AS source_id
            FROM reports
            WHERE download_status='downloaded' AND pdf_path IS NOT NULL AND pdf_path <> ''
            ORDER BY code, year, report_type
            """
        )
    if include_announcements:
        yield from conn.execute(
            """
            SELECT
                'announcement' AS doc_type,
                code,
                company,
                industry,
                CAST(substr(publish_date, 1, 4) AS INTEGER) AS year,
                'announcement' AS report_type,
                title,
                publish_date,
                'cninfo' AS source_type,
                1.0 AS source_authority_score,
                announcement_category,
                announcement_tags,
                source_url,
                pdf_path,
                code || '_' || announcement_id AS source_id
            FROM announcements
            WHERE download_status='downloaded' AND pdf_path IS NOT NULL AND pdf_path <> ''
            ORDER BY code, publish_date, announcement_id
            """
        )


def extract_pages(source: sqlite3.Row, args: argparse.Namespace) -> list[tuple[int, str]]:
    if args.parser in ("opendataloader", "auto"):
        pages = extract_pages_with_opendataloader(source, args)
        if pages and total_text_len(pages) >= args.min_parser_chars:
            return pages
        if args.parser == "opendataloader":
            return pages

    if args.parser in ("marker", "auto"):
        pages = extract_pages_with_marker(source, args, force_ocr=False)
        if pages and total_text_len(pages) >= args.min_parser_chars:
            return pages
        if args.ocr_fallback:
            pages = extract_pages_with_marker(source, args, force_ocr=True)
            if pages and total_text_len(pages) >= args.min_parser_chars:
                return pages
        return pages

    return []


def parser_env(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    env["DEBUG"] = "false"
    env.setdefault("TORCH_DEVICE", args.torch_device)
    model_cache_dir = Path(args.model_cache_dir)
    model_cache_dir.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(args.temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    env.setdefault("MODEL_CACHE_DIR", str(model_cache_dir.resolve()))
    env.setdefault("TMP", str(temp_dir.resolve()))
    env.setdefault("TEMP", str(temp_dir.resolve()))

    java_home = args.java_home.strip()
    if not java_home:
        default_java = Path("E:/Java/temurin-21-jre")
        if default_java.exists():
            java_home = str(default_java)
    if java_home:
        java_bin = str((Path(java_home) / "bin").resolve())
        env["JAVA_HOME"] = str(Path(java_home).resolve())
        env["PATH"] = java_bin + os.pathsep + env.get("PATH", "")
    return env


def extract_pages_with_opendataloader(source: sqlite3.Row, args: argparse.Namespace) -> list[tuple[int, str]]:
    pdf_path = Path(source["pdf_path"])
    parse_dir = Path(args.parsed_dir) / "opendataloader" / safe_path_part(source["source_id"])
    parse_dir.mkdir(parents=True, exist_ok=True)
    cache_md = parse_dir / "document.md"
    cache_json = parse_dir / "document.json"
    if cache_json.exists() and not args.force_parse:
        return opendataloader_json_to_pages(json.loads(cache_json.read_text(encoding="utf-8", errors="ignore")))
    if cache_md.exists() and not args.force_parse:
        return marker_markdown_to_pages(cache_md.read_text(encoding="utf-8", errors="ignore"))

    opendataloader = Path(sys.executable).with_name("opendataloader-pdf.exe")
    opendataloader_cmd = str(opendataloader) if opendataloader.exists() else "opendataloader-pdf"
    cmd = [
        opendataloader_cmd,
        str(pdf_path),
        "--output-dir",
        str(parse_dir),
        "--format",
        "markdown,json",
        "--threads",
        str(args.opendataloader_threads),
    ]
    if args.max_pages > 0:
        cmd.extend(["--pages", f"1-{args.max_pages}"])
    if args.opendataloader_extract_images:
        cmd.extend(["--image-output", "external", "--image-dir", "images"])
    completed = subprocess.run(
        cmd,
        cwd=Path.cwd(),
        env=parser_env(args),
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=args.parser_timeout,
        check=False,
    )
    if completed.returncode != 0:
        message = (completed.stderr or completed.stdout or "").strip().splitlines()
        print(f"  opendataloader parse failed: {message[-1] if message else completed.returncode}", flush=True)
        return []

    json_files = sorted(parse_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    md_files = sorted(parse_dir.glob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    if json_files:
        raw_json = json_files[0].read_text(encoding="utf-8", errors="ignore")
        cache_json.write_text(raw_json, encoding="utf-8")
        if md_files:
            cache_md.write_text(md_files[0].read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        return opendataloader_json_to_pages(json.loads(raw_json))
    if md_files:
        text = md_files[0].read_text(encoding="utf-8", errors="ignore")
        cache_md.write_text(text, encoding="utf-8")
        return marker_markdown_to_pages(text)
    return []


def extract_pages_with_marker(source: sqlite3.Row, args: argparse.Namespace, force_ocr: bool) -> list[tuple[int, str]]:
    pdf_path = Path(source["pdf_path"])
    parse_dir = Path(args.parsed_dir) / ("marker_ocr" if force_ocr else "marker") / safe_path_part(source["source_id"])
    parse_dir.mkdir(parents=True, exist_ok=True)
    cache_file = parse_dir / "document.md"
    if cache_file.exists() and not args.force_parse:
        return marker_markdown_to_pages(cache_file.read_text(encoding="utf-8", errors="ignore"))

    env = parser_env(args)
    marker_single = Path(sys.executable).with_name("marker_single.exe")
    marker_single_cmd = str(marker_single) if marker_single.exists() else "marker_single"
    commands = [
        {
            "name": "marker-new-cli",
            "cmd": [
                marker_single_cmd,
                str(pdf_path),
                "--output_format",
                "markdown",
                "--MarkdownRenderer_paginate_output",
                "--output_dir",
                str(parse_dir),
                "--disable_multiprocessing",
                "--disable_tqdm",
                "--layout_batch_size",
                str(args.marker_batch_size),
                "--detection_batch_size",
                str(args.marker_batch_size),
                "--recognition_batch_size",
                str(args.marker_batch_size),
                "--table_rec_batch_size",
                str(args.marker_batch_size),
            ],
            "force_ocr_flag": "--PdfProvider_force_ocr",
            "ocr_env": None,
        },
    ]
    completed = None
    last_message = ""
    for command in commands:
        cmd = list(command["cmd"])
        run_env = env.copy()
        if args.max_pages > 0:
            cmd.extend(["--page_range", f"0-{args.max_pages - 1}"])
        if not force_ocr and args.disable_ocr_first_pass:
            cmd.append("--disable_ocr")
        if force_ocr and command["force_ocr_flag"]:
            cmd.append(str(command["force_ocr_flag"]))
        if force_ocr and command["ocr_env"]:
            run_env[str(command["ocr_env"])] = "true"
        try:
            completed = subprocess.run(
                cmd,
                cwd=Path.cwd(),
                env=run_env,
                text=True,
                encoding="utf-8",
                errors="replace",
                capture_output=True,
                timeout=args.parser_timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            last_message = str(exc)
            continue
        md_files = list(parse_dir.rglob("*.md"))
        if completed.returncode == 0 and md_files:
            break
        if completed.returncode == 0:
            last_message = f"{command['name']} produced no markdown output"
            continue
        message = (completed.stderr or completed.stdout or "").strip().splitlines()
        last_message = message[-1] if message else str(completed.returncode)
    if completed is None or completed.returncode != 0:
        print(f"  marker {'ocr ' if force_ocr else ''}parse failed: {last_message}", flush=True)
        return []

    md_files = sorted(parse_dir.rglob("*.md"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not md_files:
        return []
    text = md_files[0].read_text(encoding="utf-8", errors="ignore")
    cache_file.write_text(text, encoding="utf-8")
    return marker_markdown_to_pages(text)


def extract_pages_with_marker_python_api(pdf_path: Path, parse_dir: Path, args: argparse.Namespace, force_ocr: bool) -> list[tuple[int, str]]:
    global _MARKER_MODELS
    try:
        os.environ["DEBUG"] = "false"
        os.environ.setdefault("TORCH_DEVICE", args.torch_device)
        if force_ocr:
            os.environ["OCR_ALL_PAGES"] = "true"
        from marker.convert import convert_single_pdf
        from marker.models import load_all_models

        if _MARKER_MODELS is None:
            _MARKER_MODELS = load_all_models()
        markdown, images, _metadata = convert_single_pdf(
            str(pdf_path),
            _MARKER_MODELS,
            batch_multiplier=args.marker_batch_multiplier,
            ocr_all_pages=force_ocr,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  marker python {'ocr ' if force_ocr else ''}parse failed: {exc}", flush=True)
        return []

    markdown = normalize_text(markdown or "")
    if not markdown:
        return []
    image_dir = parse_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    for name, image in (images or {}).items():
        try:
            image_path = image_dir / safe_path_part(str(name))
            if not image_path.suffix:
                image_path = image_path.with_suffix(".png")
            image.save(image_path)
        except Exception as exc:  # noqa: BLE001
            print(f"  marker image save failed: {name}: {exc}", flush=True)
    cache_file = parse_dir / "document.md"
    cache_file.write_text(markdown, encoding="utf-8")
    return marker_markdown_to_pages(markdown)


def marker_markdown_to_pages(markdown: str) -> list[tuple[int, str]]:
    markdown = normalize_text(markdown)
    if not markdown:
        return []
    page_pattern = re.compile(r"\n\s*(?:\{(\d{1,5})\}|(\d{1,5}))\s*-{20,}\s*\n")
    matches = list(page_pattern.finditer("\n" + markdown + "\n"))
    if not matches:
        return [(1, markdown)]
    pages: list[tuple[int, str]] = []
    padded = "\n" + markdown + "\n"
    for index, match in enumerate(matches):
        page_no = int(match.group(1) or match.group(2)) + 1
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(padded)
        text = normalize_text(padded[start:end])
        if text:
            pages.append((page_no, text))
    return pages or [(1, markdown)]


def opendataloader_json_to_pages(data: object) -> list[tuple[int, str]]:
    page_parts: dict[int, list[str]] = {}

    def append(page_no: int, text: str) -> None:
        text = normalize_text(text)
        if text:
            page_parts.setdefault(page_no, []).append(text)

    def node_content(node: dict) -> str:
        content = node.get("content")
        if isinstance(content, str):
            return normalize_text(content)
        kids = node.get("kids")
        if isinstance(kids, list):
            return normalize_text(" ".join(node_content(kid) for kid in kids if isinstance(kid, dict)))
        return ""

    def table_to_markdown(node: dict) -> str:
        rows = node.get("rows")
        if not isinstance(rows, list):
            return ""
        table_rows: list[list[str]] = []
        max_cols = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            cells = row.get("cells")
            if not isinstance(cells, list):
                continue
            values = [node_content(cell).replace("\n", " ").strip() for cell in cells if isinstance(cell, dict)]
            if values:
                table_rows.append(values)
                max_cols = max(max_cols, len(values))
        if not table_rows or max_cols == 0:
            return ""
        normalized_rows = [row + [""] * (max_cols - len(row)) for row in table_rows]
        lines = ["| " + " | ".join(row) + " |" for row in normalized_rows]
        lines.insert(1, "| " + " | ".join(["---"] * max_cols) + " |")
        return "\n".join(lines)

    def walk(node: object) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return

        node_type = str(node.get("type") or "").lower()
        page_no = int(node.get("page number") or node.get("page") or 1)
        if node_type == "table":
            append(page_no, table_to_markdown(node))
            return
        if node_type == "heading":
            level = int(node.get("heading level") or 2)
            level = min(max(level, 1), 6)
            append(page_no, f"{'#' * level} {node_content(node)}")
            return
        if node_type in {"paragraph", "list item", "caption", "text block"}:
            append(page_no, node_content(node))
            return
        if node_type in {"header", "footer", "table row", "table cell"}:
            return

        for key in ("kids", "children", "content"):
            child = node.get(key)
            if isinstance(child, (list, dict)):
                walk(child)

    walk(data)
    return [(page_no, "\n\n".join(parts)) for page_no, parts in sorted(page_parts.items()) if parts]


def total_text_len(pages: list[tuple[int, str]]) -> int:
    return sum(len(text) for _, text in pages)


def safe_path_part(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", value).strip("_")


def normalize_text(text: str) -> str:
    text = repair_mojibake(text)
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def repair_mojibake(text: str) -> str:
    if not text:
        return text
    marker_count = sum(1 for char in text if char in MOJIBAKE_MARKERS)
    if marker_count / max(1, len(text)) < 0.02:
        return text

    def cjk_count(value: str) -> int:
        return sum(1 for char in value if "\u4e00" <= char <= "\u9fff")

    best = text
    best_cjk = cjk_count(text)
    for encoding in ("latin1", "cp1252"):
        try:
            candidate = text.encode(encoding, errors="ignore").decode("utf-8", errors="ignore")
        except UnicodeError:
            continue
        candidate_cjk = cjk_count(candidate)
        if candidate_cjk > best_cjk:
            best = candidate
            best_cjk = candidate_cjk
    return best


def clean_lines(text: str, *, announcement: bool) -> list[str]:
    lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or PAGE_NO_PATTERN.match(line):
            continue
        if TOC_LINE_PATTERN.match(line) or REPORT_HEADER_PATTERN.match(line):
            continue
        if announcement and any(re.match(pattern, line) for pattern in ANNOUNCEMENT_NOISE_PATTERNS):
            continue
        lines.append(line)
    return lines


def clean_for_embedding(text: str, *, announcement: bool) -> str:
    lines = clean_lines(text, announcement=announcement)
    return normalize_text("\n".join(lines))


def clean_markdown_heading(line: str) -> str:
    line = normalize_text(line)
    line = re.sub(r"^\{\d+\}-+\s*", "", line)
    line = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
    line = re.sub(r"^\s*[-*+]\s+", "", line)
    line = re.sub(r"</?br\s*/?>", "", line, flags=re.IGNORECASE)
    line = re.sub(r"[*_`]+", "", line)
    line = re.sub(r"\s+", " ", line)
    return line.strip()


def display_text(text: str) -> str:
    return normalize_text(text)


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 2)


def detect_section(line: str) -> tuple[str, int] | None:
    stripped = clean_markdown_heading(line)
    for keyword in REPORT_SECTION_KEYWORDS:
        if keyword in stripped and len(stripped) <= 40 and (
            stripped == keyword
            or stripped.startswith("第")
            or re.match(r"^[一二三四五六七八九十]+、", stripped)
            or re.match(r"^\d+[、.．]", stripped)
            or re.match(r"^（[一二三四五六七八九十\d]+）", stripped)
            or re.match(r"^\([一二三四五六七八九十\d]+\)", stripped)
        ):
            level = 1 if stripped.startswith("第") else 2
            return keyword, level
    match = SECTION_PREFIX_PATTERN.match(stripped)
    if match and len(stripped) <= 50:
        title = match.group(match.lastindex).strip() if match.lastindex else stripped
        for keyword in REPORT_SECTION_KEYWORDS:
            if title == keyword or title.startswith(keyword) or keyword in title:
                return keyword, 2
    return None


def is_table_like(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    numeric_lines = sum(1 for line in lines if re.search(r"\d", line) and re.search(r"[%元万亿,，.]", line))
    keyword_hits = sum(1 for keyword in FINANCIAL_TABLE_KEYWORDS if keyword in text)
    aligned_lines = sum(1 for line in lines if re.search(r"\S+\s{2,}\S+", line))
    has_unit = bool(re.search(r"单位[:：]\s*(元|万元|亿元|股|%|人民币)", text))
    return (keyword_hits >= 2 and numeric_lines >= 2) or (has_unit and numeric_lines >= 2) or aligned_lines >= 5


def infer_chunk_type(doc_type: str, section: str, body: str, block_type: str) -> str:
    if doc_type == "announcement":
        return "announcement_event"
    if block_type == "image_reference":
        return "image_reference"
    financial_sections = ["资产负债表", "利润表", "现金流量表", "所有者权益变动表", "财务报表"]
    if block_type == "table_like" or is_table_like(body):
        if any(keyword in section for keyword in financial_sections):
            return "financial_statement"
        return "table_like"
    if "管理层讨论" in section or "经营情况讨论" in section:
        return "management_discussion"
    if "风险因素" in section:
        return "risk_item"
    if "公司业务概要" in section:
        return "business_overview"
    if any(keyword in section for keyword in financial_sections):
        return "financial_statement"
    if section:
        return "section_text"
    return "other_text"


def infer_financial_statement_section(section: str, body: str) -> str:
    if section and section != "财务报表":
        return section
    candidates = [
        ("合并资产负债表", ["货币资金", "流动资产", "非流动资产", "负债合计", "所有者权益", "负债和所有者权益总计"]),
        ("合并利润表", ["营业总收入", "营业利润", "净利润", "每股收益"]),
        ("合并现金流量表", ["经营活动产生的现金流量", "投资活动产生的现金流量", "筹资活动产生的现金流量"]),
        ("所有者权益变动表", ["所有者权益变动", "本期增减变动金额"]),
    ]
    for name, keywords in candidates:
        if name in body or sum(1 for keyword in keywords if keyword in body) >= 2:
            return name
    return section


def metadata_header(source: sqlite3.Row, section: str, chunk_type: str, page_start: int, page_end: int) -> str:
    statement_type = infer_statement_type(section)
    rows = [
        f"公司：{source['company'] or source['code']}",
        f"代码：{source['code']}",
        f"行业：{source['industry'] or '未知'}",
        f"文档类型：{source['doc_type']}",
        f"报告类型：{source['report_type'] or ''}",
        f"年份：{source['year'] or ''}",
        f"发布日期：{source['publish_date'] or ''}",
        f"来源类型：{source['source_type'] or 'cninfo'}",
        f"标题：{source['title'] or ''}",
        f"章节：{section or ''}",
        f"块类型：{chunk_type}",
        f"公告类别：{source['announcement_category'] or ''}",
        f"页码：{page_start}" if page_start == page_end else f"页码：{page_start}-{page_end}",
    ]
    rows.append(f"statement_type: {statement_type}")
    return "\n".join(rows)


def build_announcement_blocks(source: sqlite3.Row, pages: list[tuple[int, str]], chunk_size: int, overlap: int, max_chunks: int) -> list[TextBlock]:
    full_raw = "\n\n".join(text for _, text in pages)
    full_clean = clean_for_embedding(full_raw, announcement=True)
    if not full_clean:
        return []
    parts = split_by_size(full_clean, chunk_size, overlap, max_chunks=max_chunks)
    page_start = pages[0][0]
    page_end = pages[-1][0]
    return [
        TextBlock(
            text=part,
            page_start=page_start,
            page_end=page_end,
            section=source["announcement_category"] or "公告",
            section_level=1,
            block_type="announcement_event",
        )
        for part in parts
        if len(part) >= 60
    ]


def build_report_blocks(pages: list[tuple[int, str]]) -> list[TextBlock]:
    blocks: list[TextBlock] = []
    current_section = ""
    current_level = 0
    for page_no, page_text in pages:
        lines = clean_lines(page_text, announcement=False)
        paragraph_lines: list[str] = []

        def flush() -> None:
            nonlocal paragraph_lines
            if not paragraph_lines:
                return
            text = normalize_text("\n".join(paragraph_lines))
            paragraph_lines = []
            if len(text) < 30:
                return
            block_type = "table_like" if is_table_like(text) else "paragraph"
            blocks.append(
                TextBlock(
                    text=text,
                    page_start=page_no,
                    page_end=page_no,
                    section=current_section,
                    section_level=current_level,
                    block_type=block_type,
                )
            )

        for line in lines:
            image_match = IMAGE_MARKDOWN_PATTERN.search(line)
            if image_match:
                flush()
                blocks.append(
                    TextBlock(
                        text=f"图片引用：{image_match.group(1)}",
                        page_start=page_no,
                        page_end=page_no,
                        section=current_section,
                        section_level=current_level,
                        block_type="image_reference",
                    )
                )
                continue
            detected = detect_section(line)
            if detected:
                flush()
                current_section, current_level = detected
                blocks.append(
                    TextBlock(
                        text=line,
                        page_start=page_no,
                        page_end=page_no,
                        section=current_section,
                        section_level=current_level,
                        block_type="heading",
                    )
                )
                continue
            if looks_like_paragraph_break(line, paragraph_lines):
                flush()
            paragraph_lines.append(line)
        flush()
    return blocks


def looks_like_paragraph_break(line: str, current_lines: list[str]) -> bool:
    if not current_lines:
        return False
    previous = current_lines[-1]
    if previous.endswith(("。", "；", "！", "？", ".", ";", ":", "：")):
        return True
    if len(current_lines) >= 8:
        return True
    if is_table_like("\n".join(current_lines)) != is_table_like(line):
        return True
    return False


def split_by_size(text: str, chunk_size: int, overlap: int, max_chunks: int = 0) -> list[str]:
    paragraphs = [paragraph.strip() for paragraph in re.split(r"\n\s*\n", text) if paragraph.strip()]
    if not paragraphs:
        paragraphs = [text]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if not current:
            current = paragraph
        elif len(current) + len(paragraph) + 2 <= chunk_size:
            current = f"{current}\n\n{paragraph}"
        else:
            chunks.extend(split_long_text(current, chunk_size, overlap))
            current = paragraph
        if max_chunks and len(chunks) >= max_chunks:
            break
    if current and (not max_chunks or len(chunks) < max_chunks):
        chunks.extend(split_long_text(current, chunk_size, overlap))
    if max_chunks:
        chunks = chunks[:max_chunks]
    return [chunk for chunk in chunks if chunk.strip()]


def split_long_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            boundary = max(text.rfind("。", start, end), text.rfind("；", start, end), text.rfind("\n", start, end))
            if boundary > start + int(chunk_size * 0.55):
                end = boundary + 1
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(0, end - overlap)
    return chunks


def merge_report_blocks(source: sqlite3.Row, blocks: list[TextBlock], chunk_size: int, overlap: int) -> list[TextBlock]:
    chunks: list[TextBlock] = []
    current_text = ""
    current_section = ""
    current_level = 0
    current_type = ""
    page_start = 0
    page_end = 0

    def flush() -> None:
        nonlocal current_text, current_section, current_level, current_type, page_start, page_end
        if not current_text.strip():
            return
        base_section = current_section
        if current_type == "financial_statement":
            base_section = infer_financial_statement_section(current_section, current_text)
        for part in split_by_size(current_text, chunk_size, overlap):
            if len(part) >= 60:
                chunks.append(
                    TextBlock(
                        text=part,
                        page_start=page_start,
                        page_end=page_end,
                        section=base_section,
                        section_level=current_level,
                        block_type=current_type,
                    )
                )
        current_text = ""
        current_section = ""
        current_level = 0
        current_type = ""
        page_start = 0
        page_end = 0

    for block in blocks:
        if block.block_type == "heading":
            flush()
            continue
        if block.block_type == "image_reference":
            flush()
            chunks.append(block)
            continue
        chunk_type = infer_chunk_type(source["doc_type"], block.section, block.text, block.block_type)
        same_bucket = (
            current_text
            and block.section == current_section
            and chunk_type == current_type
            and len(current_text) + len(block.text) + 2 <= chunk_size
        )
        if not same_bucket:
            flush()
            current_section = block.section
            current_level = block.section_level
            current_type = chunk_type
            page_start = block.page_start
        current_text = block.text if not current_text else f"{current_text}\n\n{block.text}"
        page_end = block.page_end
    flush()
    return chunks


def insert_chunk(conn: sqlite3.Connection, source: sqlite3.Row, index: int, block: TextBlock) -> bool:
    chunk_type = infer_chunk_type(source["doc_type"], block.section, block.text, block.block_type)
    raw_text = block.text
    embed_body = clean_for_embedding(block.text, announcement=source["doc_type"] == "announcement")
    if len(embed_body) < 40 and block.block_type != "image_reference":
        return False
    statement_type = infer_statement_type(block.section, embed_body)
    metric_terms = extract_metric_terms(embed_body, block.section)
    finance_header = ""
    if statement_type or metric_terms:
        finance_header = f"statement_type: {statement_type}\nmetric_terms: {metric_terms}\n"
        embed_body = f"{finance_header}\n{embed_body}"
    embed_text = f"{metadata_header(source, block.section, chunk_type, block.page_start, block.page_end)}\n\n{embed_body}"
    shown_text = f"{metadata_header(source, block.section, chunk_type, block.page_start, block.page_end)}\n\n{display_text(block.text)}"
    text_hash = hashlib.sha256(embed_text.encode("utf-8")).hexdigest()
    chunk_id = f"{source['source_id']}_{index:06d}"
    try:
        conn.execute(
            """
            INSERT INTO chunks (
                chunk_id, source_id, doc_type, code, company, industry, year,
                report_type, title, publish_date, announcement_category,
                announcement_tags, source_type, source_authority_score,
                section, section_level, statement_type, metric_terms, chunk_type,
                page_start, page_end, chunk_index, text, raw_text, embed_text,
                display_text, text_hash, char_count, token_estimate,
                source_pdf, source_url
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chunk_id,
                source["source_id"],
                source["doc_type"],
                source["code"],
                source["company"],
                source["industry"],
                source["year"],
                source["report_type"],
                source["title"],
                source["publish_date"],
                source["announcement_category"],
                source["announcement_tags"],
                source["source_type"],
                source["source_authority_score"],
                block.section,
                block.section_level,
                statement_type,
                metric_terms,
                chunk_type,
                block.page_start,
                block.page_end,
                index,
                embed_text,
                raw_text,
                embed_text,
                shown_text,
                text_hash,
                len(embed_text),
                estimate_tokens(embed_text),
                source["pdf_path"],
                source["source_url"],
            ),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def clear_existing_chunks(conn: sqlite3.Connection, doc_type: str) -> None:
    has_vector_records = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='vector_index_records'"
    ).fetchone()
    if doc_type == "all":
        conn.execute("DELETE FROM chunks")
        if has_vector_records:
            conn.execute("DELETE FROM vector_index_records")
    else:
        if has_vector_records:
            conn.execute("DELETE FROM vector_index_records WHERE chunk_id IN (SELECT chunk_id FROM chunks WHERE doc_type=?)", (doc_type,))
        conn.execute("DELETE FROM chunks WHERE doc_type=?", (doc_type,))
    conn.commit()


def build_chunks(args: argparse.Namespace) -> int:
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    init_chunks_table(conn)
    if args.rebuild:
        clear_existing_chunks(conn, args.doc_type)

    include_reports = args.doc_type in ("all", "report")
    include_announcements = args.doc_type in ("all", "announcement")
    sources = list(iter_sources(conn, include_reports, include_announcements))
    if args.limit:
        sources = sources[: args.limit]

    inserted = 0
    skipped = 0
    failed = 0
    for source_no, source in enumerate(sources, start=1):
        pdf_path = Path(source["pdf_path"])
        print(f"[{source_no}/{len(sources)}] {source['source_id']} {pdf_path}", flush=True)
        if not pdf_path.exists():
            print("  missing pdf", flush=True)
            failed += 1
            continue
        try:
            pages = extract_pages(source, args)
        except Exception as exc:  # noqa: BLE001
            print(f"  parse error: {exc}", flush=True)
            failed += 1
            continue
        if source["doc_type"] == "announcement":
            blocks = build_announcement_blocks(source, pages, args.announcement_chunk_size, args.overlap, args.max_announcement_chunks)
        else:
            raw_blocks = build_report_blocks(pages)
            blocks = merge_report_blocks(source, raw_blocks, args.report_chunk_size, args.overlap)
        local_inserted = 0
        for index, block in enumerate(blocks, start=1):
            if insert_chunk(conn, source, index, block):
                inserted += 1
                local_inserted += 1
            else:
                skipped += 1
        conn.commit()
        print(f"  pages={len(pages)} chunks={len(blocks)} inserted={local_inserted}", flush=True)

    print(f"Inserted chunks: {inserted}; skipped duplicates/short: {skipped}; failed PDFs: {failed}", flush=True)
    conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build finance-aware chunks from downloaded PDFs.")
    parser.add_argument("--db", default="data/metadata.sqlite")
    parser.add_argument("--doc-type", choices=["all", "report", "announcement"], default="all")
    parser.add_argument("--report-chunk-size", type=int, default=1400)
    parser.add_argument("--announcement-chunk-size", type=int, default=2600)
    parser.add_argument("--overlap", type=int, default=180)
    parser.add_argument("--max-announcement-chunks", type=int, default=5)
    parser.add_argument("--parser", choices=["auto", "opendataloader", "marker"], default="auto")
    parser.add_argument("--parsed-dir", default="data/parsed")
    parser.add_argument("--force-parse", action="store_true")
    parser.add_argument("--ocr-fallback", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--min-parser-chars", type=int, default=500)
    parser.add_argument("--parser-timeout", type=int, default=900)
    parser.add_argument("--torch-device", default="cuda")
    parser.add_argument("--model-cache-dir", default="data/model_cache/datalab")
    parser.add_argument("--temp-dir", default="data/tmp")
    parser.add_argument("--java-home", default="")
    parser.add_argument("--disable-ocr-first-pass", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-pages", type=int, default=0)
    parser.add_argument("--opendataloader-threads", type=int, default=4)
    parser.add_argument("--opendataloader-extract-images", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--marker-batch-size", type=int, default=1)
    parser.add_argument("--marker-batch-multiplier", type=int, default=1)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--rebuild", action="store_true")
    return parser


def main() -> int:
    return build_chunks(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())

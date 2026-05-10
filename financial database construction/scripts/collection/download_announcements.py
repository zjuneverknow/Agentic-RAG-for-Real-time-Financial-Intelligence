from __future__ import annotations

import argparse
import hashlib
import json
import random
import re
import sqlite3
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError

SCRIPTS_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from collection.download_reports import (
    CNINFO_QUERY_URL,
    CNINFO_STATIC_BASE,
    Company,
    clean_title,
    download_bytes,
    format_publish_date,
    load_companies,
    request_json,
    resolve_company_org_id,
    safe_filename,
)


HIGH_VALUE_KEYWORDS = [
    "业绩预告",
    "业绩快报",
    "投资者关系活动记录",
    "调研活动",
    "重大合同",
    "中标",
    "项目进展",
    "对外投资",
    "回购",
    "增持",
    "减持",
    "权益变动",
    "并购",
    "重组",
    "发行股份购买资产",
    "购买资产",
    "定增",
    "向特定对象发行",
    "股权激励",
    "员工持股",
    "募集资金",
    "风险提示",
    "诉讼",
    "仲裁",
    "订单",
    "合作协议",
]

EXCLUDE_ANNOUNCEMENT_PATTERN = re.compile(
    r"(摘要|英文|港股公告|H股公告|海外监管|更正|修订|补充|取消|已取消|问询函|回复|法律意见书|独立董事|核查意见|鉴证报告|专项核查)"
)

ANNOUNCEMENT_CATEGORY_RULES = [
    (
        "merger_reorg",
        [
            r"并购重组",
            r"重大资产重组",
            r"发行股份购买资产",
            r"购买资产",
            r"资产收购",
            r"资产出售",
            r"吸收合并",
            r"重组",
            r"并购",
        ],
    ),
    ("performance", [r"业绩预告", r"业绩快报"]),
    ("major_contract", [r"重大合同", r"中标", r"订单", r"合作协议"]),
    ("buyback", [r"回购"]),
    ("equity_incentive", [r"股权激励", r"限制性股票", r"股票期权", r"员工持股", r"激励计划"]),
    ("fundraising", [r"募集资金", r"定增", r"向特定对象发行", r"非公开发行", r"可转换公司债券", r"发行可转债"]),
    ("holding_change", [r"增持", r"减持", r"权益变动", r"持股.*变动"]),
    ("litigation_risk", [r"诉讼", r"仲裁", r"风险提示"]),
    ("investment_project", [r"对外投资", r"项目进展", r"投资项目"]),
    ("investor_relations", [r"投资者关系活动记录", r"调研活动", r"业绩说明会"]),
]


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS announcements (
            code TEXT NOT NULL,
            company TEXT,
            industry TEXT,
            title TEXT NOT NULL,
            publish_date TEXT,
            source_url TEXT NOT NULL,
            pdf_path TEXT,
            file_sha256 TEXT,
            file_size INTEGER,
            announcement_id TEXT,
            announcement_category TEXT,
            announcement_tags TEXT,
            matched_keywords TEXT,
            download_status TEXT NOT NULL,
            error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (code, announcement_id)
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(announcements)").fetchall()}
    if "announcement_category" not in columns:
        conn.execute("ALTER TABLE announcements ADD COLUMN announcement_category TEXT")
    if "announcement_tags" not in columns:
        conn.execute("ALTER TABLE announcements ADD COLUMN announcement_tags TEXT")
    conn.commit()
    return conn


def query_announcements(company: Company, start_date: str, end_date: str, page_size: int = 50, max_pages: int = 8) -> list[dict]:
    stock = f"{company.code},{company.org_id}" if company.org_id else ""
    announcements: list[dict] = []
    for page in range(1, max_pages + 1):
        payload = {
            "pageNum": str(page),
            "pageSize": str(page_size),
            "column": "szse",
            "tabName": "fulltext",
            "plate": "",
            "stock": stock,
            "searchkey": "" if stock else company.code,
            "secid": "",
            "category": "",
            "trade": "",
            "seDate": f"{start_date}~{end_date}",
            "sortName": "time",
            "sortType": "desc",
            "isHLtitle": "true",
        }
        data = request_json(CNINFO_QUERY_URL, payload)
        page_items = data.get("announcements") or []
        announcements.extend(page_items)
        if len(page_items) < page_size:
            break
    return announcements


def matched_keywords(title: str) -> list[str]:
    return [keyword for keyword in HIGH_VALUE_KEYWORDS if keyword in title]


def classify_announcement(title: str) -> tuple[str, list[str], list[str]]:
    tags: list[str] = []
    matched_patterns: list[str] = []
    primary_category = ""
    for category, patterns in ANNOUNCEMENT_CATEGORY_RULES:
        category_hits = [pattern for pattern in patterns if re.search(pattern, title)]
        if category_hits:
            tags.append(category)
            matched_patterns.extend(category_hits)
            if not primary_category:
                primary_category = category
    if not primary_category:
        primary_category = "other_high_value"
    if not tags:
        tags = [primary_category]
    return primary_category, tags, matched_patterns


def is_high_value(item: dict, company: Company) -> tuple[bool, list[str]]:
    code = str(item.get("secCode") or "").strip().zfill(6)
    title = clean_title(str(item.get("announcementTitle") or ""))
    adjunct_url = str(item.get("adjunctUrl") or "").strip()
    if code != company.code or not title or not adjunct_url:
        return False, []
    if EXCLUDE_ANNOUNCEMENT_PATTERN.search(title):
        return False, []
    _, _, category_keywords = classify_announcement(title)
    keywords = sorted(set(matched_keywords(title) + category_keywords))
    return bool(keywords), keywords


def upsert_announcement(
    conn: sqlite3.Connection,
    company: Company,
    item: dict,
    status: str,
    keywords: list[str],
    **extra: object,
) -> None:
    title = clean_title(str(item.get("announcementTitle") or ""))
    announcement_category, announcement_tags, category_keywords = classify_announcement(title)
    keywords = sorted(set(keywords + category_keywords))
    adjunct_url = str(item.get("adjunctUrl") or "").strip()
    announcement_id = str(item.get("announcementId") or "")
    source_url = CNINFO_STATIC_BASE + adjunct_url
    conn.execute(
        """
        INSERT INTO announcements (
            code, company, industry, title, publish_date, source_url, pdf_path,
            file_sha256, file_size, announcement_id, announcement_category,
            announcement_tags, matched_keywords, download_status, error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(code, announcement_id) DO UPDATE SET
            company=excluded.company,
            industry=excluded.industry,
            title=excluded.title,
            publish_date=excluded.publish_date,
            source_url=excluded.source_url,
            pdf_path=excluded.pdf_path,
            file_sha256=excluded.file_sha256,
            file_size=excluded.file_size,
            announcement_category=excluded.announcement_category,
            announcement_tags=excluded.announcement_tags,
            matched_keywords=excluded.matched_keywords,
            download_status=excluded.download_status,
            error=excluded.error,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            company.code,
            company.company or str(item.get("secName") or "").replace(" ", ""),
            company.industry,
            title,
            format_publish_date(item.get("announcementTime") or item.get("announcementDate")),
            source_url,
            extra.get("pdf_path"),
            extra.get("file_sha256"),
            extra.get("file_size"),
            announcement_id,
            announcement_category,
            ",".join(announcement_tags),
            ",".join(keywords),
            status,
            extra.get("error"),
        ),
    )
    conn.commit()


def save_pdf(out_dir: Path, company: Company, item: dict, content: bytes) -> tuple[Path, str]:
    title = clean_title(str(item.get("announcementTitle") or ""))
    publish_date = format_publish_date(item.get("announcementTime") or item.get("announcementDate")) or "unknown_date"
    company_dir = out_dir / "announcements" / company.code
    company_dir.mkdir(parents=True, exist_ok=True)
    path = company_dir / f"{publish_date}_{safe_filename(title)}.pdf"
    path.write_bytes(content)
    return path, hashlib.sha256(content).hexdigest()


def append_manifest(out_dir: Path, row: dict[str, object]) -> None:
    manifest = out_dir / "announcements_manifest.jsonl"
    with manifest.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def collect(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    conn = init_db(Path(args.db))
    companies = [resolve_company_org_id(company) for company in load_companies(Path(args.companies))]

    total_downloaded = 0
    total_matched = 0
    for index, company in enumerate(companies, start=1):
        print(f"[{index}/{len(companies)}] {company.code} {company.company} announcements", flush=True)
        try:
            items = query_announcements(company, args.start_date, args.end_date, args.page_size, args.max_pages)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            print(f"  query error: {exc}", flush=True)
            continue

        matched = [(item, keywords) for item in items if (keywords := is_high_value(item, company)[1])]
        total_matched += len(matched)
        print(f"  matched high-value announcements: {len(matched)}", flush=True)

        for item, keywords in matched:
            title = clean_title(str(item.get("announcementTitle") or ""))
            category, tags, _ = classify_announcement(title)
            source_url = CNINFO_STATIC_BASE + str(item.get("adjunctUrl") or "").strip()
            try:
                if args.dry_run:
                    print(f"  found: [{category}] {title}", flush=True)
                    upsert_announcement(conn, company, item, "found", keywords)
                else:
                    content = download_bytes(source_url)
                    pdf_path, sha256 = save_pdf(out_dir, company, item, content)
                    upsert_announcement(
                        conn,
                        company,
                        item,
                        "downloaded",
                        keywords,
                        pdf_path=str(pdf_path),
                        file_sha256=sha256,
                        file_size=len(content),
                    )
                    append_manifest(
                        out_dir,
                        {
                            "code": company.code,
                            "company": company.company,
                            "industry": company.industry,
                            "title": title,
                            "publish_date": format_publish_date(item.get("announcementTime") or item.get("announcementDate")),
                            "source_url": source_url,
                            "pdf_path": str(pdf_path),
                            "file_sha256": sha256,
                            "file_size": len(content),
                            "matched_keywords": keywords,
                            "announcement_category": category,
                            "announcement_tags": tags,
                        },
                    )
                    total_downloaded += 1
                    print(f"  downloaded: [{category}] {pdf_path}", flush=True)
            except (HTTPError, URLError, TimeoutError, OSError) as exc:
                print(f"  error: {title}: {exc}", flush=True)
                upsert_announcement(conn, company, item, "error", keywords, error=repr(exc))
            time.sleep(args.sleep + random.random() * args.jitter)

    conn.close()
    print(f"Matched: {total_matched}; downloaded this run: {total_downloaded}", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download recent high-value A-share announcements from CNINFO.")
    parser.add_argument("--companies", default="config/sample_companies.csv")
    parser.add_argument("--start-date", default="2025-01-01")
    parser.add_argument("--end-date", default="2026-05-05")
    parser.add_argument("--out-dir", default="data")
    parser.add_argument("--db", default="data/metadata.sqlite")
    parser.add_argument("--page-size", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=8)
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--jitter", type=float, default=0.3)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    return collect(build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())

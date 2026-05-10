from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


CNINFO_QUERY_URL = "https://www.cninfo.com.cn/new/hisAnnouncement/query"
CNINFO_STATIC_BASE = "https://static.cninfo.com.cn/"

REPORT_CATEGORIES = {
    "annual": "category_ndbg_szsh",
    "semiannual": "category_bndbg_szsh",
    "q1": "category_yjdbg_szsh",
    "q3": "category_sjdbg_szsh",
}

REPORT_TITLE_PATTERNS = {
    "annual": re.compile(r"(年度报告|年报)(全文)?$"),
    "semiannual": re.compile(r"(半年度报告|半年报)(全文)?$"),
    "q1": re.compile(r"(第一季度报告|一季度报告)(全文)?$"),
    "q3": re.compile(r"(第三季度报告|三季度报告)(全文)?$"),
}

EXCLUDE_TITLE_PATTERN = re.compile(
    r"(摘要|英文|港股公告|H股公告|海外监管|取消|更正|修订|补充|已取消|公告编号|意见|说明|问询函|回复)"
)


@dataclass(frozen=True)
class Company:
    code: str
    company: str = ""
    industry: str = ""
    org_id: str = ""


@dataclass(frozen=True)
class ReportCandidate:
    code: str
    company: str
    industry: str
    year: int
    report_type: str
    title: str
    publish_date: str
    adjunct_url: str
    announcement_id: str
    source_url: str


def request_json(url: str, data: dict[str, str], timeout: int = 30) -> dict:
    encoded = urlencode(data).encode("utf-8")
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Origin": "https://www.cninfo.com.cn",
        "Referer": "https://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
    }
    req = Request(url, data=encoded, headers=headers, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_bytes(url: str, timeout: int = 60) -> bytes:
    headers = {
        "Referer": "https://www.cninfo.com.cn/",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
    }
    req = Request(url, headers=headers, method="GET")
    with urlopen(req, timeout=timeout) as resp:
        return resp.read()


def init_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS reports (
            code TEXT NOT NULL,
            company TEXT,
            industry TEXT,
            year INTEGER NOT NULL,
            report_type TEXT NOT NULL,
            title TEXT NOT NULL,
            publish_date TEXT,
            source_url TEXT NOT NULL,
            pdf_path TEXT,
            file_sha256 TEXT,
            file_size INTEGER,
            announcement_id TEXT,
            download_status TEXT NOT NULL,
            error TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (code, year, report_type)
        )
        """
    )
    columns = {row[1] for row in conn.execute("PRAGMA table_info(reports)").fetchall()}
    if "industry" not in columns:
        conn.execute("ALTER TABLE reports ADD COLUMN industry TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS download_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            year INTEGER NOT NULL,
            report_type TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


def upsert_report(conn: sqlite3.Connection, report: ReportCandidate, status: str, **extra: object) -> None:
    conn.execute(
        """
        INSERT INTO reports (
            code, company, industry, year, report_type, title, publish_date, source_url,
            pdf_path, file_sha256, file_size, announcement_id, download_status, error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(code, year, report_type) DO UPDATE SET
            company=excluded.company,
            industry=excluded.industry,
            title=excluded.title,
            publish_date=excluded.publish_date,
            source_url=excluded.source_url,
            pdf_path=excluded.pdf_path,
            file_sha256=excluded.file_sha256,
            file_size=excluded.file_size,
            announcement_id=excluded.announcement_id,
            download_status=excluded.download_status,
            error=excluded.error,
            updated_at=CURRENT_TIMESTAMP
        """,
        (
            report.code,
            report.company,
            report.industry,
            report.year,
            report.report_type,
            report.title,
            report.publish_date,
            report.source_url,
            extra.get("pdf_path"),
            extra.get("file_sha256"),
            extra.get("file_size"),
            report.announcement_id,
            status,
            extra.get("error"),
        ),
    )
    conn.execute(
        """
        INSERT INTO download_events (code, year, report_type, status, message)
        VALUES (?, ?, ?, ?, ?)
        """,
        (report.code, report.year, report.report_type, status, str(extra.get("error") or "")),
    )
    conn.commit()


def load_companies(path: Path) -> list[Company]:
    companies: list[Company] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            code = (row.get("code") or "").strip().zfill(6)
            if not code:
                continue
            companies.append(
                Company(
                    code=code,
                    company=(row.get("company") or "").strip(),
                    industry=(row.get("industry") or "").strip(),
                    org_id=(row.get("org_id") or "").strip(),
                )
            )
    return companies


def parse_years(raw: str) -> list[int]:
    years: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start, end = [int(x) for x in part.split("-", 1)]
            years.extend(range(start, end + 1))
        else:
            years.append(int(part))
    return sorted(set(years))


def query_cninfo(company: Company, year: int, report_type: str, page_size: int = 30) -> list[dict]:
    category = REPORT_CATEGORIES[report_type]
    query_year = year + 1 if report_type == "annual" else year
    start = f"{query_year}-01-01"
    end = f"{query_year}-12-31"
    stock = f"{company.code},{company.org_id}" if company.org_id else ""
    payload = {
        "pageNum": "1",
        "pageSize": str(page_size),
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": stock,
        "searchkey": "" if stock else company.code,
        "secid": "",
        "category": category,
        "trade": "",
        "seDate": f"{start}~{end}",
        "sortName": "time",
        "sortType": "desc",
        "isHLtitle": "true",
    }
    data = request_json(CNINFO_QUERY_URL, payload)
    return data.get("announcements") or []


def resolve_company_org_id(company: Company) -> Company:
    if company.org_id:
        return company
    payload = {
        "pageNum": "1",
        "pageSize": "1",
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": "",
        "searchkey": company.code,
        "secid": "",
        "category": "",
        "trade": "",
        "seDate": "",
        "sortName": "time",
        "sortType": "desc",
        "isHLtitle": "true",
    }
    data = request_json(CNINFO_QUERY_URL, payload)
    for item in data.get("announcements") or []:
        code = str(item.get("secCode") or "").strip().zfill(6)
        org_id = str(item.get("orgId") or "").strip()
        if code == company.code and org_id:
            return Company(
                code=company.code,
                company=company.company or str(item.get("secName") or "").replace(" ", ""),
                industry=company.industry,
                org_id=org_id,
            )
    return company


def clean_title(title: str) -> str:
    return re.sub(r"<[^>]+>", "", title or "").strip()


def format_publish_date(raw: object) -> str:
    if isinstance(raw, int):
        return datetime.fromtimestamp(raw / 1000).strftime("%Y-%m-%d")
    text = str(raw or "")
    if text.isdigit():
        return datetime.fromtimestamp(int(text) / 1000).strftime("%Y-%m-%d")
    return text


def candidate_from_item(item: dict, company: Company, year: int, report_type: str) -> ReportCandidate | None:
    code = str(item.get("secCode") or "").strip().zfill(6)
    title = clean_title(str(item.get("announcementTitle") or ""))
    adjunct_url = str(item.get("adjunctUrl") or "").strip()
    if code != company.code or not title or not adjunct_url:
        return None
    if EXCLUDE_TITLE_PATTERN.search(title):
        return None
    if not REPORT_TITLE_PATTERNS[report_type].search(title):
        return None

    source_url = CNINFO_STATIC_BASE + adjunct_url
    return ReportCandidate(
        code=code,
        company=company.company or str(item.get("secName") or ""),
        industry=company.industry,
        year=year,
        report_type=report_type,
        title=title,
        publish_date=format_publish_date(item.get("announcementTime") or item.get("announcementDate")),
        adjunct_url=adjunct_url,
        announcement_id=str(item.get("announcementId") or ""),
        source_url=source_url,
    )


def choose_best_candidate(items: Iterable[dict], company: Company, year: int, report_type: str) -> ReportCandidate | None:
    candidates = [
        candidate
        for item in items
        if (candidate := candidate_from_item(item, company, year, report_type)) is not None
    ]
    if not candidates:
        return None
    return sorted(candidates, key=lambda x: x.publish_date, reverse=True)[0]


def safe_filename(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", text).strip("_")


def write_manifest(out_dir: Path, row: dict[str, object]) -> None:
    manifest = out_dir / "manifest.jsonl"
    with manifest.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def save_report_pdf(out_dir: Path, report: ReportCandidate, content: bytes) -> tuple[Path, str]:
    company_dir = out_dir / "raw" / report.code
    company_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{report.year}_{report.report_type}_{safe_filename(report.title)}.pdf"
    path = company_dir / filename
    path.write_bytes(content)
    sha256 = hashlib.sha256(content).hexdigest()
    return path, sha256


def collect_reports(args: argparse.Namespace) -> int:
    companies = load_companies(Path(args.companies))
    years = parse_years(args.years)
    report_types = [x.strip() for x in args.report_types.split(",") if x.strip()]
    out_dir = Path(args.out_dir)
    conn = init_db(Path(args.db))

    total = len(companies) * len(years) * len(report_types)
    done = 0
    for company in companies:
        company = resolve_company_org_id(company)
        for year in years:
            for report_type in report_types:
                done += 1
                print(f"[{done}/{total}] {company.code} {year} {report_type}", flush=True)
                try:
                    items = query_cninfo(company, year, report_type)
                    report = choose_best_candidate(items, company, year, report_type)
                    if report is None:
                        print("  not found", flush=True)
                        placeholder = ReportCandidate(
                            code=company.code,
                            company=company.company,
                            industry=company.industry,
                            year=year,
                            report_type=report_type,
                            title="",
                            publish_date="",
                            adjunct_url="",
                            announcement_id="",
                            source_url="",
                        )
                        upsert_report(conn, placeholder, "not_found", error="No matching report title")
                        continue
                    if args.dry_run:
                        print(f"  found: {report.title} {report.source_url}", flush=True)
                        upsert_report(conn, report, "found")
                    else:
                        content = download_bytes(report.source_url)
                        pdf_path, sha256 = save_report_pdf(out_dir, report, content)
                        upsert_report(
                            conn,
                            report,
                            "downloaded",
                            pdf_path=str(pdf_path),
                            file_sha256=sha256,
                            file_size=len(content),
                        )
                        write_manifest(
                            out_dir,
                            {
                                "code": report.code,
                                "company": report.company,
                                "industry": report.industry,
                                "year": report.year,
                                "report_type": report.report_type,
                                "title": report.title,
                                "publish_date": report.publish_date,
                                "source_url": report.source_url,
                                "pdf_path": str(pdf_path),
                                "file_sha256": sha256,
                                "file_size": len(content),
                            },
                        )
                        print(f"  downloaded: {pdf_path}", flush=True)
                except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                    print(f"  error: {exc}", flush=True)
                    placeholder = ReportCandidate(
                        code=company.code,
                        company=company.company,
                        industry=company.industry,
                        year=year,
                        report_type=report_type,
                        title="",
                        publish_date="",
                        adjunct_url="",
                        announcement_id="",
                        source_url="",
                    )
                    upsert_report(conn, placeholder, "error", error=repr(exc))
                time.sleep(args.sleep + random.random() * args.jitter)
    conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download A-share annual/semiannual reports from CNINFO.")
    parser.add_argument("--companies", default="config/sample_companies.csv", help="CSV with columns: code,company,industry")
    parser.add_argument("--years", default="2023-2026", help="Years, e.g. 2023-2026 or 2023,2024,2025")
    parser.add_argument("--report-types", default="annual", help="Comma separated: annual,semiannual,q1,q3")
    parser.add_argument("--out-dir", default="data", help="Output data directory")
    parser.add_argument("--db", default="data/metadata.sqlite", help="SQLite metadata database path")
    parser.add_argument("--sleep", type=float, default=1.0, help="Base delay between requests")
    parser.add_argument("--jitter", type=float, default=0.8, help="Random extra delay between requests")
    parser.add_argument("--dry-run", action="store_true", help="Query metadata without downloading PDFs")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    invalid_types = set(args.report_types.split(",")) - set(REPORT_CATEGORIES)
    if invalid_types:
        parser.error(f"Unsupported report type(s): {', '.join(sorted(invalid_types))}")
    return collect_reports(args)


if __name__ == "__main__":
    raise SystemExit(main())

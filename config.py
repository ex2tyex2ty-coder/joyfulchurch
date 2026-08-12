from __future__ import annotations

from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
SOURCE_DIR = DATA_DIR / "source"
GOOGLE_SHEETS_CACHE_DIR = DATA_DIR / "google_sheets"
BACKUP_DIR = DATA_DIR / "backups"
DB_PATH = DATA_DIR / "joyful_worship_ops.db"
IMPORT_REPORT_PATH = DATA_DIR / "import_report.json"
GOOGLE_CALENDAR_CREDENTIALS_PATH = DATA_DIR / "google_calendar_credentials.json"
GOOGLE_CALENDAR_TOKEN_PATH = DATA_DIR / "google_calendar_token.json"
REVIEW_BOARD_SPREADSHEET_ID = "1GX6xFwqvGXrD-ipKXReO67ITQas1bRXKGvAEV2o7d50"

GOOGLE_SHEETS = (
    {
        "label": "예배팀 매뉴얼",
        "spreadsheet_id": "1gpcKvCpnteuxDTmswYfqC2v_IW129693bfPIfxQoXxk",
        "file_name": "2025 예배팀 매뉴얼.xlsx",
    },
    {
        "label": "예배인원·엔지니어 라인업",
        "spreadsheet_id": "1KyRr5kfrG7BcADeu4mVQrTiq09HZUaC60RzS7Be_WhE",
        "file_name": "2025 예배팀 엔지니어 라인업.xlsx",
    },
)

APP_TITLE = "JOYFUL WORSHIP OPS"
APP_VERSION = "2026.08.12-r11"

STATUS_CURRENT = "CURRENT"
STATUS_ARCHIVED = "ARCHIVED"
STATUS_SUPERSEDED = "SUPERSEDED"

QUALITY_VERIFIED = "Verified"
QUALITY_IMPORTED = "Imported"
QUALITY_NEEDS_REVIEW = "Needs Review"
QUALITY_UNKNOWN = "Unknown"


def ensure_directories() -> None:
    for directory in (DATA_DIR, SOURCE_DIR, GOOGLE_SHEETS_CACHE_DIR, BACKUP_DIR):
        directory.mkdir(parents=True, exist_ok=True)

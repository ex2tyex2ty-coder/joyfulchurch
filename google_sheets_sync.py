from __future__ import annotations

import os
import tempfile
import urllib.request
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from config import DB_PATH, GOOGLE_SHEETS, GOOGLE_SHEETS_CACHE_DIR, ensure_directories
from db import set_app_meta
from migration import migrate, workbook_role


def _download_xlsx(
    spreadsheet_id: str,
    destination: Path,
    timeout: int = 120,
    service_account_info: dict[str, Any] | None = None,
) -> None:
    if service_account_info:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload

        credentials = Credentials.from_service_account_info(
            service_account_info,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )
        drive = build("drive", "v3", credentials=credentials, cache_discovery=False)
        request = drive.files().export_media(
            fileId=spreadsheet_id,
            mimeType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        with destination.open("wb") as handle:
            downloader = MediaIoBaseDownload(handle, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return

    url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export?format=xlsx"
    request = urllib.request.Request(url, headers={"User-Agent": "JOYFUL-WORSHIP-OPS/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response, destination.open("wb") as handle:
        if response.status != 200:
            raise RuntimeError(f"Google Sheets 응답 오류: HTTP {response.status}")
        while chunk := response.read(1024 * 1024):
            handle.write(chunk)


def _validate_workbook(path: Path) -> dict[str, Any]:
    if not zipfile.is_zipfile(path):
        raise RuntimeError("받은 파일이 올바른 Excel 문서가 아닙니다. 공유 권한을 확인하세요.")
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        role = workbook_role(workbook.sheetnames)
        if role == "UNKNOWN":
            raise RuntimeError("기존 자료와 다른 시트 구조입니다. 시트 이름을 확인하세요.")
        return {"role": role, "sheets": list(workbook.sheetnames), "bytes": path.stat().st_size}
    finally:
        workbook.close()


def sync_google_sheets(
    db_path: Path = DB_PATH,
    service_account_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Download the configured public Sheets as read-only XLSX files and merge them."""
    ensure_directories()
    downloaded: list[dict[str, Any]] = []
    staged: list[tuple[Path, Path]] = []
    try:
        for sheet in GOOGLE_SHEETS:
            fd, temp_name = tempfile.mkstemp(prefix="joyful_sheet_", suffix=".xlsx", dir=GOOGLE_SHEETS_CACHE_DIR)
            os.close(fd)
            temp_path = Path(temp_name)
            final_path = GOOGLE_SHEETS_CACHE_DIR / sheet["file_name"]
            _download_xlsx(sheet["spreadsheet_id"], temp_path, service_account_info=service_account_info)
            details = _validate_workbook(temp_path)
            downloaded.append({"label": sheet["label"], "file": sheet["file_name"], **details})
            staged.append((temp_path, final_path))

        # Publish the cache only after every workbook has downloaded and validated.
        for temp_path, final_path in staged:
            os.replace(temp_path, final_path)

        report = migrate(source_dir=GOOGLE_SHEETS_CACHE_DIR, db_path=db_path, reset=False)
        synced_at = datetime.now().isoformat(timespec="seconds")
        set_app_meta("last_google_sheets_sync_at", synced_at, db_path)
        set_app_meta("last_google_sheets_sync_status", "SUCCESS", db_path)
        return {"synced_at": synced_at, "downloaded": downloaded, "report": report}
    except Exception as exc:
        set_app_meta("last_google_sheets_sync_status", f"ERROR: {exc}", db_path)
        raise
    finally:
        for temp_path, _ in staged:
            temp_path.unlink(missing_ok=True)

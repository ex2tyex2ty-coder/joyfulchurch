from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from config import DB_PATH, GOOGLE_CALENDAR_CREDENTIALS_PATH, GOOGLE_CALENDAR_TOKEN_PATH
from db import transaction


READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"


def _event_date(value: dict[str, Any] | None) -> str:
    if not value:
        return ""
    raw = value.get("date") or value.get("dateTime") or ""
    return raw[:10]


def store_google_events(
    calendar_id: str,
    items: list[dict[str, Any]],
    path: Path | str = DB_PATH,
) -> int:
    saved = 0
    with transaction(path) as conn:
        for item in items:
            external_id = item.get("id")
            title = item.get("summary") or "제목 없는 일정"
            start_date = _event_date(item.get("start"))
            status = (item.get("status") or "confirmed").upper()
            if external_id and status == "CANCELLED" and not start_date:
                result = conn.execute(
                    "UPDATE church_calendar_events SET status='CANCELLED',archived_at=CURRENT_TIMESTAMP,synced_at=CURRENT_TIMESTAMP "
                    "WHERE external_id=?",
                    (external_id,),
                )
                saved += result.rowcount
                continue
            if not external_id or not start_date:
                continue
            archived_at = datetime.now().isoformat(timespec="seconds") if status == "CANCELLED" else None
            conn.execute(
                "INSERT INTO church_calendar_events("
                "external_id,calendar_id,title,start_date,end_date,description,location,html_link,source_updated_at,status,archived_at"
                ") VALUES(?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(external_id) DO UPDATE SET "
                "calendar_id=excluded.calendar_id,title=excluded.title,start_date=excluded.start_date,end_date=excluded.end_date,"
                "description=excluded.description,location=excluded.location,html_link=excluded.html_link,"
                "source_updated_at=excluded.source_updated_at,synced_at=CURRENT_TIMESTAMP,status=excluded.status,archived_at=excluded.archived_at",
                (
                    external_id,
                    calendar_id,
                    title,
                    start_date,
                    _event_date(item.get("end")) or None,
                    item.get("description"),
                    item.get("location"),
                    item.get("htmlLink"),
                    item.get("updated"),
                    status,
                    archived_at,
                ),
            )
            saved += 1
    return saved


def sync_google_calendar(
    calendar_id: str,
    credentials_path: Path = GOOGLE_CALENDAR_CREDENTIALS_PATH,
    token_path: Path = GOOGLE_CALENDAR_TOKEN_PATH,
    db_path: Path | str = DB_PATH,
    days_ahead: int = 370,
) -> dict[str, Any]:
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise RuntimeError("Google Calendar 연동 패키지가 설치되지 않았습니다. requirements.txt를 설치하세요.") from exc

    if not credentials_path.exists():
        raise FileNotFoundError("Google OAuth 클라이언트 JSON 파일이 없습니다.")

    credentials = None
    if token_path.exists():
        credentials = Credentials.from_authorized_user_file(str(token_path), [READONLY_SCOPE])
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), [READONLY_SCOPE])
            credentials = flow.run_local_server(port=0)
        token_path.write_text(credentials.to_json(), encoding="utf-8")

    service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
    time_min = datetime.now(timezone.utc)
    time_max = time_min + timedelta(days=days_ahead)
    items: list[dict[str, Any]] = []
    page_token = None
    calendar_title = calendar_id
    while True:
        response = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            showDeleted=True,
            maxResults=250,
            pageToken=page_token,
        ).execute()
        calendar_title = response.get("summary") or calendar_title
        items.extend(response.get("items", []))
        page_token = response.get("nextPageToken")
        if not page_token:
            break

    saved = store_google_events(calendar_id, items, db_path)
    return {"calendar": calendar_title, "received": len(items), "saved": saved}

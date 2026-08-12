from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
ITEM_SHEET = "게시글"
COMMENT_SHEET = "댓글"
AUDIT_SHEET = "변경이력"

ITEM_HEADERS = [
    "item_id", "title", "description", "status", "created_by", "updated_by",
    "created_at", "updated_at", "confirmed_at", "archived_at",
]
COMMENT_HEADERS = [
    "comment_id", "review_item_id", "parent_comment_id", "author", "body",
    "status_change", "created_at", "archived_at",
]
AUDIT_HEADERS = [
    "log_id", "entity_type", "entity_id", "action", "author", "before_status",
    "after_status", "details", "created_at",
]
VALID_STATUSES = {"REVIEW_REQUIRED", "IN_PROGRESS", "CONFIRMED"}
STATUS_ORDER = {"REVIEW_REQUIRED": 0, "IN_PROGRESS": 1, "CONFIRMED": 2}


class ReviewBoardConnectionError(RuntimeError):
    """Raised when the durable Google Sheets board cannot be read or written."""


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="seconds")


def _records(headers: list[str], values: list[list[Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for raw in values:
        padded = list(raw) + [""] * max(0, len(headers) - len(raw))
        record = {header: padded[index] for index, header in enumerate(headers)}
        if any(str(value).strip() for value in record.values()):
            records.append(record)
    return records


def build_snapshot(
    item_values: list[list[Any]],
    comment_values: list[list[Any]],
    show_confirmed: bool = False,
    limit: int = 30,
) -> dict[str, Any]:
    """Build the visible board from append-safe Sheet rows.

    Comment status changes are replayed so a successfully appended comment remains
    authoritative even if the convenience update to the item row was interrupted.
    """
    items = _records(ITEM_HEADERS, item_values)
    comments = _records(COMMENT_HEADERS, comment_values)
    active_items = {
        str(item["item_id"]): dict(item)
        for item in items
        if str(item.get("item_id", "")).strip() and not str(item.get("archived_at", "")).strip()
    }
    grouped_comments: dict[str, list[dict[str, Any]]] = {item_id: [] for item_id in active_items}
    for comment in sorted(comments, key=lambda value: (str(value.get("created_at", "")), str(value.get("comment_id", "")))):
        item_id = str(comment.get("review_item_id", ""))
        if item_id not in active_items or str(comment.get("archived_at", "")).strip():
            continue
        grouped_comments[item_id].append(comment)
        status = str(comment.get("status_change", ""))
        if status in VALID_STATUSES:
            active_items[item_id]["status"] = status
            active_items[item_id]["updated_by"] = comment.get("author", "")
            active_items[item_id]["updated_at"] = comment.get("created_at", "")
            active_items[item_id]["confirmed_at"] = comment.get("created_at", "") if status == "CONFIRMED" else ""

    counts = {status: 0 for status in VALID_STATUSES}
    for item in active_items.values():
        status = str(item.get("status", "REVIEW_REQUIRED"))
        if status not in VALID_STATUSES:
            status = "REVIEW_REQUIRED"
            item["status"] = status
        counts[status] += 1
        item["id"] = str(item["item_id"])
        item["comment_count"] = len(grouped_comments.get(str(item["item_id"]), []))

    visible = [
        item for item in active_items.values()
        if show_confirmed or item.get("status") != "CONFIRMED"
    ]
    visible.sort(
        key=lambda item: (
            STATUS_ORDER.get(str(item.get("status")), 9),
            str(item.get("updated_at") or item.get("created_at") or ""),
            str(item.get("item_id") or ""),
        )
    )
    # Keep status groups ordered while showing the newest entry first in each group.
    ordered: list[dict[str, Any]] = []
    for status in ("REVIEW_REQUIRED", "IN_PROGRESS", "CONFIRMED"):
        group = [item for item in visible if item.get("status") == status]
        group.sort(key=lambda item: (str(item.get("updated_at", "")), str(item.get("item_id", ""))), reverse=True)
        ordered.extend(group)

    return {
        "counts": counts,
        "items": ordered[:limit],
        "comments": grouped_comments,
        "raw_items": items,
        "raw_comments": comments,
    }


class GoogleReviewBoardStore:
    def __init__(self, spreadsheet_id: str, service_account_info: dict[str, Any]):
        try:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise ReviewBoardConnectionError("Google Sheets 연결 패키지가 설치되지 않았습니다.") from exc

        try:
            credentials = Credentials.from_service_account_info(
                service_account_info,
                scopes=[SHEETS_SCOPE],
            )
            self.service = build("sheets", "v4", credentials=credentials, cache_discovery=False)
        except Exception as exc:
            raise ReviewBoardConnectionError("게시판용 서비스 계정 정보를 확인할 수 없습니다.") from exc
        self.spreadsheet_id = spreadsheet_id
        self._lock = threading.RLock()
        self.ensure_schema()

    def _execute(self, request: Any) -> dict[str, Any]:
        try:
            with self._lock:
                return request.execute()
        except Exception as exc:
            raise ReviewBoardConnectionError(f"게시판 Google Sheets 연결 오류: {exc}") from exc

    def ensure_schema(self) -> None:
        metadata = self._execute(
            self.service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id,
                fields="sheets.properties(sheetId,title)",
            )
        )
        properties = [sheet.get("properties", {}) for sheet in metadata.get("sheets", [])]
        title_to_id = {str(item.get("title")): item.get("sheetId") for item in properties}
        requests: list[dict[str, Any]] = []

        if ITEM_SHEET not in title_to_id and "Sheet1" in title_to_id:
            sheet_id = title_to_id.pop("Sheet1")
            requests.append({
                "updateSheetProperties": {
                    "properties": {"sheetId": sheet_id, "title": ITEM_SHEET, "gridProperties": {"frozenRowCount": 1}},
                    "fields": "title,gridProperties.frozenRowCount",
                }
            })
            title_to_id[ITEM_SHEET] = sheet_id

        for title in (ITEM_SHEET, COMMENT_SHEET, AUDIT_SHEET):
            if title not in title_to_id:
                requests.append({
                    "addSheet": {"properties": {"title": title, "gridProperties": {"frozenRowCount": 1}}}
                })
        if requests:
            self._execute(
                self.service.spreadsheets().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"requests": requests},
                )
            )

        header_specs = [
            (ITEM_SHEET, ITEM_HEADERS),
            (COMMENT_SHEET, COMMENT_HEADERS),
            (AUDIT_SHEET, AUDIT_HEADERS),
        ]
        ranges = [f"'{title}'!1:1" for title, _ in header_specs]
        result = self._execute(
            self.service.spreadsheets().values().batchGet(
                spreadsheetId=self.spreadsheet_id,
                ranges=ranges,
            )
        )
        existing_ranges = result.get("valueRanges", [])
        updates: list[dict[str, Any]] = []
        for index, (title, headers) in enumerate(header_specs):
            existing = existing_ranges[index].get("values", []) if index < len(existing_ranges) else []
            existing_header = existing[0][: len(headers)] if existing else []
            if existing_header and existing_header != headers:
                raise ReviewBoardConnectionError(f"'{title}' 시트의 첫 행이 예상 구조와 다릅니다. 덮어쓰지 않았습니다.")
            if not existing_header:
                updates.append({"range": f"'{title}'!A1", "values": [headers]})
        if updates:
            self._execute(
                self.service.spreadsheets().values().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"valueInputOption": "RAW", "data": updates},
                )
            )

    def _raw_values(self) -> tuple[list[list[Any]], list[list[Any]]]:
        result = self._execute(
            self.service.spreadsheets().values().batchGet(
                spreadsheetId=self.spreadsheet_id,
                ranges=[f"'{ITEM_SHEET}'!A2:J", f"'{COMMENT_SHEET}'!A2:H"],
            )
        )
        value_ranges = result.get("valueRanges", [])
        item_values = value_ranges[0].get("values", []) if len(value_ranges) > 0 else []
        comment_values = value_ranges[1].get("values", []) if len(value_ranges) > 1 else []
        return item_values, comment_values

    def snapshot(self, show_confirmed: bool = False, limit: int = 30) -> dict[str, Any]:
        item_values, comment_values = self._raw_values()
        return build_snapshot(item_values, comment_values, show_confirmed=show_confirmed, limit=limit)

    def export_json(self) -> bytes:
        snapshot = self.snapshot(show_confirmed=True, limit=1_000_000)
        payload = {
            "exported_at": _now(),
            "spreadsheet_id": self.spreadsheet_id,
            "items": snapshot["raw_items"],
            "comments": snapshot["raw_comments"],
        }
        return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    def _append(self, sheet_name: str, row: list[Any]) -> None:
        self._execute(
            self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{sheet_name}'!A:A",
                valueInputOption="RAW",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            )
        )

    def _audit(
        self,
        entity_type: str,
        entity_id: str,
        action: str,
        author: str,
        before_status: str = "",
        after_status: str = "",
        details: str = "",
    ) -> None:
        self._append(
            AUDIT_SHEET,
            [uuid.uuid4().hex, entity_type, entity_id, action, author, before_status, after_status, details, _now()],
        )

    def create_item(self, title: str, description: str, created_by: str) -> str:
        title = title.strip()
        description = description.strip()
        created_by = created_by.strip()
        if not title or not created_by:
            raise ValueError("제목과 작성자를 입력하세요.")
        item_id = uuid.uuid4().hex
        created_at = _now()
        self._append(
            ITEM_SHEET,
            [
                item_id, title[:200], description[:4000], "REVIEW_REQUIRED", created_by[:80],
                created_by[:80], created_at, created_at, "", "",
            ],
        )
        try:
            self._audit("review_item", item_id, "CREATE", created_by[:80], after_status="REVIEW_REQUIRED", details=title[:500])
        except ReviewBoardConnectionError:
            # The primary append is authoritative; an audit failure must not create a duplicate item on retry.
            pass
        return item_id

    def add_comment(
        self,
        review_item_id: str,
        author: str,
        body: str,
        status_change: str | None = None,
        parent_comment_id: str | None = None,
    ) -> str:
        author = author.strip()
        body = body.strip()
        if not author or not body:
            raise ValueError("작성자와 댓글을 입력하세요.")
        if status_change is not None and status_change not in VALID_STATUSES:
            raise ValueError("올바르지 않은 상태입니다.")

        item_values, comment_values = self._raw_values()
        snapshot = build_snapshot(item_values, comment_values, show_confirmed=True, limit=1_000_000)
        item = next((value for value in snapshot["items"] if str(value["id"]) == str(review_item_id)), None)
        if not item:
            raise ValueError("확인항목을 찾을 수 없습니다.")

        comment_id = uuid.uuid4().hex
        created_at = _now()
        self._append(
            COMMENT_SHEET,
            [comment_id, str(review_item_id), parent_comment_id or "", author[:80], body[:4000], status_change or "", created_at, ""],
        )

        # Keep the human-readable item row current. The snapshot still replays the
        # appended comment, so an interrupted row update cannot lose the status change.
        item_row = next(
            (index for index, raw in enumerate(item_values, start=2) if raw and str(raw[0]) == str(review_item_id)),
            None,
        )
        if item_row is not None:
            confirmed_at = created_at if status_change == "CONFIRMED" else ""
            current_status = status_change or str(item.get("status") or "REVIEW_REQUIRED")
            try:
                self._execute(
                    self.service.spreadsheets().values().batchUpdate(
                        spreadsheetId=self.spreadsheet_id,
                        body={
                            "valueInputOption": "RAW",
                            "data": [
                                {"range": f"'{ITEM_SHEET}'!D{item_row}", "values": [[current_status]]},
                                {"range": f"'{ITEM_SHEET}'!F{item_row}:I{item_row}", "values": [[author[:80], item.get("created_at", ""), created_at, confirmed_at]]},
                            ],
                        },
                    )
                )
            except ReviewBoardConnectionError:
                pass
        try:
            self._audit(
                "review_item", str(review_item_id), "COMMENT", author[:80],
                before_status=str(item.get("status", "")),
                after_status=status_change or str(item.get("status", "")),
                details=body[:500],
            )
        except ReviewBoardConnectionError:
            pass
        return comment_id

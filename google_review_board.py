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
    "category", "priority", "owner", "due_date",
]
COMMENT_HEADERS = [
    "comment_id", "review_item_id", "parent_comment_id", "author", "body",
    "status_change", "created_at", "archived_at",
]
AUDIT_HEADERS = [
    "log_id", "entity_type", "entity_id", "action", "author", "before_status",
    "after_status", "details", "created_at",
]
BACKUP_SCHEMA_VERSION = 1
VALID_STATUSES = {"REVIEW_REQUIRED", "IN_PROGRESS", "CONFIRMED"}
STATUS_ORDER = {"REVIEW_REQUIRED": 0, "IN_PROGRESS": 1, "CONFIRMED": 2}
VALID_PRIORITIES = {"NORMAL", "HIGH", "URGENT"}


class ReviewBoardConnectionError(RuntimeError):
    """Raised when the durable Google Sheets board cannot be read or written."""


def _now() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).isoformat(timespec="microseconds")


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
    seen_comment_ids: set[str] = set()
    for comment in sorted(comments, key=lambda value: (str(value.get("created_at", "")), str(value.get("comment_id", "")))):
        comment_id = str(comment.get("comment_id", "")).strip()
        if comment_id:
            if comment_id in seen_comment_ids:
                continue
            seen_comment_ids.add(comment_id)
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
        if str(item.get("priority", "")) not in VALID_PRIORITIES:
            item["priority"] = "NORMAL"
        if not str(item.get("category", "")).strip():
            item["category"] = "기타"

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


def _find_item_row(item_values: list[list[Any]], review_item_id: str) -> int | None:
    """Return the 1-based Sheets row for an item identifier."""
    return next(
        (
            index
            for index, raw in enumerate(item_values, start=2)
            if raw and str(raw[0]).strip() == str(review_item_id).strip()
        ),
        None,
    )


def filter_review_items(
    items: list[dict[str, Any]],
    status_filter: str = "OPEN",
    category: str = "전체",
    term: str = "",
) -> list[dict[str, Any]]:
    """Filter board items without changing the source snapshot."""
    search_terms = term.casefold().split()
    filtered: list[dict[str, Any]] = []
    for item in items:
        status = str(item.get("status", "REVIEW_REQUIRED"))
        if status_filter == "OPEN" and status == "CONFIRMED":
            continue
        if status_filter in VALID_STATUSES and status != status_filter:
            continue
        if category != "전체" and str(item.get("category", "기타")) != category:
            continue
        searchable = " ".join(
            str(item.get(key, ""))
            for key in ("title", "description", "category", "priority", "owner", "due_date", "created_by", "updated_by")
        ).casefold()
        normalized_searchable = " ".join(searchable.split())
        if search_terms and any(search_term not in normalized_searchable for search_term in search_terms):
            continue
        filtered.append(dict(item))
    return filtered


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

    def _execute(self, request: Any, *, num_retries: int = 2) -> dict[str, Any]:
        try:
            with self._lock:
                return request.execute(num_retries=num_retries)
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
            existing_header = existing[0] if existing else []
            expected_prefix = headers[: len(existing_header)]
            if existing_header and existing_header != expected_prefix:
                raise ReviewBoardConnectionError(f"'{title}' 시트의 첫 행이 예상 구조와 다릅니다. 덮어쓰지 않았습니다.")
            if len(existing_header) < len(headers):
                start_column = self._column_name(len(existing_header) + 1)
                updates.append({
                    "range": f"'{title}'!{start_column}1",
                    "values": [headers[len(existing_header):]],
                })
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
                ranges=[f"'{ITEM_SHEET}'!A2:N", f"'{COMMENT_SHEET}'!A2:H"],
            )
        )
        value_ranges = result.get("valueRanges", [])
        item_values = value_ranges[0].get("values", []) if len(value_ranges) > 0 else []
        comment_values = value_ranges[1].get("values", []) if len(value_ranges) > 1 else []
        return item_values, comment_values

    def snapshot(self, show_confirmed: bool = False, limit: int = 30) -> dict[str, Any]:
        item_values, comment_values = self._raw_values()
        return build_snapshot(item_values, comment_values, show_confirmed=show_confirmed, limit=limit)

    def _raw_audit_values(self) -> list[list[Any]]:
        result = self._execute(
            self.service.spreadsheets().values().get(
                spreadsheetId=self.spreadsheet_id,
                range=f"'{AUDIT_SHEET}'!A2:I",
            )
        )
        return result.get("values", [])

    def export_json(self) -> bytes:
        snapshot = self.snapshot(show_confirmed=True, limit=1_000_000)
        payload = {
            "schema_version": BACKUP_SCHEMA_VERSION,
            "exported_at": _now(),
            "spreadsheet_id": self.spreadsheet_id,
            "items": snapshot["raw_items"],
            "comments": snapshot["raw_comments"],
            "audit_logs": _records(AUDIT_HEADERS, self._raw_audit_values()),
        }
        return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    @staticmethod
    def _column_name(number: int) -> str:
        result = ""
        while number:
            number, remainder = divmod(number - 1, 26)
            result = chr(65 + remainder) + result
        return result

    def _append(self, sheet_name: str, row: list[Any]) -> None:
        """Append once and verify the generated identifier after an uncertain failure."""
        identifier = str(row[0]) if row else ""
        try:
            self._execute(
                self.service.spreadsheets().values().append(
                    spreadsheetId=self.spreadsheet_id,
                    range=f"'{sheet_name}'!A:A",
                    valueInputOption="RAW",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [row]},
                ),
                num_retries=0,
            )
        except ReviewBoardConnectionError:
            if identifier:
                try:
                    result = self._execute(
                        self.service.spreadsheets().values().get(
                            spreadsheetId=self.spreadsheet_id,
                            range=f"'{sheet_name}'!A:A",
                        )
                    )
                    if any(values and str(values[0]) == identifier for values in result.get("values", [])):
                        return
                except ReviewBoardConnectionError:
                    pass
            raise

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

    def create_item(
        self,
        title: str,
        description: str,
        created_by: str,
        category: str = "기타",
        priority: str = "NORMAL",
        owner: str = "",
        due_date: str = "",
    ) -> str:
        title = title.strip()
        description = description.strip()
        created_by = created_by.strip()
        if not title or not created_by:
            raise ValueError("제목과 작성자를 입력하세요.")
        priority = priority if priority in VALID_PRIORITIES else "NORMAL"
        item_id = uuid.uuid4().hex
        created_at = _now()
        self._append(
            ITEM_SHEET,
            [
                item_id, title[:200], description[:4000], "REVIEW_REQUIRED", created_by[:80],
                created_by[:80], created_at, created_at, "", "",
                category.strip()[:80] or "기타", priority, owner.strip()[:80], due_date.strip()[:10],
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

        normalized_parent_id = (parent_comment_id or "").strip()
        if normalized_parent_id:
            parent = next(
                (
                    comment
                    for grouped in snapshot["comments"].values()
                    for comment in grouped
                    if str(comment.get("comment_id", "")) == normalized_parent_id
                ),
                None,
            )
            if parent is None:
                raise ValueError("답글 대상 댓글을 찾을 수 없습니다.")
            if str(parent.get("review_item_id", "")) != str(review_item_id):
                raise ValueError("답글은 같은 확인항목의 댓글에만 등록할 수 있습니다.")

        comment_id = uuid.uuid4().hex
        created_at = _now()
        self._append(
            COMMENT_SHEET,
            [comment_id, str(review_item_id), normalized_parent_id, author[:80], body[:4000], status_change or "", created_at, ""],
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

    def archive_item(self, review_item_id: str, author: str) -> None:
        """Hide a completed board item without physically deleting its history."""
        review_item_id = str(review_item_id).strip()
        author = author.strip()
        if not review_item_id or not author:
            raise ValueError("삭제할 확인사항과 삭제자 이름을 확인하세요.")

        with self._lock:
            item_values, comment_values = self._raw_values()
            snapshot = build_snapshot(item_values, comment_values, show_confirmed=True, limit=1_000_000)
            item = next(
                (value for value in snapshot["items"] if str(value["id"]) == review_item_id),
                None,
            )
            if item is None:
                # Treat an already archived item as a successful repeated request.
                archived_item = next(
                    (
                        value
                        for value in snapshot["raw_items"]
                        if str(value.get("item_id", "")) == review_item_id
                        and str(value.get("archived_at", "")).strip()
                    ),
                    None,
                )
                if archived_item is not None:
                    return
                raise ValueError("삭제할 확인사항을 찾을 수 없습니다.")
            if str(item.get("status", "")) != "CONFIRMED":
                raise ValueError("확인 완료된 항목만 삭제할 수 있습니다.")

            item_row = _find_item_row(item_values, review_item_id)
            if item_row is None:
                raise ValueError("삭제할 확인사항의 원본 행을 찾을 수 없습니다.")

            archived_at = _now()
            self._execute(
                self.service.spreadsheets().values().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={
                        "valueInputOption": "RAW",
                        "data": [
                            {
                                "range": f"'{ITEM_SHEET}'!F{item_row}:J{item_row}",
                                "values": [[
                                    author[:80],
                                    item.get("created_at", ""),
                                    archived_at,
                                    item.get("confirmed_at", ""),
                                    archived_at,
                                ]],
                            }
                        ],
                    },
                )
            )
            try:
                self._audit(
                    "review_item",
                    review_item_id,
                    "ARCHIVE",
                    author[:80],
                    before_status=str(item.get("status", "")),
                    after_status="ARCHIVED",
                    details=str(item.get("title", ""))[:500],
                )
            except ReviewBoardConnectionError:
                # The archived_at value is authoritative; audit failure must not
                # invite a second destructive-looking request.
                pass

    def restore_item(self, review_item_id: str, author: str) -> None:
        """Restore a soft-archived board item without changing its comments."""
        review_item_id = str(review_item_id).strip()
        author = author.strip()
        if not review_item_id or not author:
            raise ValueError("복원할 확인사항과 복원자 이름을 확인하세요.")

        with self._lock:
            item_values, _ = self._raw_values()
            raw_items = _records(ITEM_HEADERS, item_values)
            item = next(
                (
                    value for value in raw_items
                    if str(value.get("item_id", "")) == review_item_id
                    and str(value.get("archived_at", "")).strip()
                ),
                None,
            )
            if item is None:
                active_item = next(
                    (value for value in raw_items if str(value.get("item_id", "")) == review_item_id),
                    None,
                )
                if active_item is not None:
                    return
                raise ValueError("복원할 확인사항을 찾을 수 없습니다.")
            item_row = _find_item_row(item_values, review_item_id)
            if item_row is None:
                raise ValueError("복원할 확인사항의 원본 행을 찾을 수 없습니다.")
            restored_at = _now()
            self._execute(
                self.service.spreadsheets().values().batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={
                        "valueInputOption": "RAW",
                        "data": [
                            {
                                "range": f"'{ITEM_SHEET}'!F{item_row}:J{item_row}",
                                "values": [[
                                    author[:80],
                                    item.get("created_at", ""),
                                    restored_at,
                                    item.get("confirmed_at", ""),
                                    "",
                                ]],
                            }
                        ],
                    },
                )
            )
            try:
                self._audit(
                    "review_item",
                    review_item_id,
                    "RESTORE",
                    author[:80],
                    before_status="ARCHIVED",
                    after_status=str(item.get("status", "CONFIRMED")),
                    details=str(item.get("title", ""))[:500],
                )
            except ReviewBoardConnectionError:
                pass

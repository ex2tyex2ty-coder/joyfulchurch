from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
import unicodedata
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping

from config import BACKUP_DIR, DB_PATH, ensure_directories
from time_utils import now_kst, today_kst


SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS import_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'RUNNING',
    report_json TEXT
);

CREATE TABLE IF NOT EXISTS source_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    path TEXT NOT NULL UNIQUE,
    file_name TEXT NOT NULL,
    file_size INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    workbook_role TEXT,
    sheet_inventory_json TEXT,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS unresolved_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file_id INTEGER REFERENCES source_files(id),
    sheet_name TEXT,
    cell_reference TEXT,
    raw_value TEXT,
    reason TEXT NOT NULL,
    quality TEXT NOT NULL DEFAULT 'Needs Review',
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS manuals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    category TEXT,
    current_standard TEXT,
    status TEXT NOT NULL DEFAULT 'CURRENT',
    version INTEGER NOT NULL DEFAULT 1,
    source TEXT,
    source_sheet TEXT,
    data_quality TEXT NOT NULL DEFAULT 'Imported',
    last_verified TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS manual_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    manual_id INTEGER NOT NULL REFERENCES manuals(id),
    version INTEGER NOT NULL,
    what_text TEXT,
    how_text TEXT,
    why_text TEXT,
    caution TEXT,
    change_summary TEXT,
    effective_from TEXT,
    status TEXT NOT NULL DEFAULT 'CURRENT',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(manual_id, version)
);

CREATE TABLE IF NOT EXISTS event_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL UNIQUE,
    category TEXT,
    description TEXT,
    manual_id INTEGER REFERENCES manuals(id),
    source TEXT,
    source_sheet TEXT,
    data_quality TEXT NOT NULL DEFAULT 'Imported',
    status TEXT NOT NULL DEFAULT 'CURRENT',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS task_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_template_id INTEGER REFERENCES event_templates(id),
    title TEXT NOT NULL,
    description TEXT,
    source_timing TEXT,
    due_offset INTEGER,
    priority TEXT NOT NULL DEFAULT 'MEDIUM',
    default_owner TEXT,
    depends_on_template_id INTEGER REFERENCES task_templates(id),
    source TEXT,
    data_quality TEXT NOT NULL DEFAULT 'Imported',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    series_key TEXT NOT NULL,
    category TEXT,
    event_date TEXT,
    start_date TEXT,
    end_date TEXT,
    description TEXT,
    owner TEXT,
    status TEXT NOT NULL DEFAULT 'PLANNING',
    event_template_id INTEGER REFERENCES event_templates(id),
    previous_event_id INTEGER REFERENCES events(id),
    service_id INTEGER REFERENCES services(id),
    service_type TEXT,
    source TEXT,
    source_event_id TEXT,
    data_quality TEXT NOT NULL DEFAULT 'Imported',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
    task_template_id INTEGER REFERENCES task_templates(id),
    title TEXT NOT NULL,
    description TEXT,
    owner TEXT,
    status TEXT NOT NULL DEFAULT 'TODO',
    priority TEXT NOT NULL DEFAULT 'MEDIUM',
    source_timing TEXT,
    due_offset INTEGER,
    due_date TEXT,
    depends_on INTEGER REFERENCES tasks(id),
    source TEXT,
    data_quality TEXT NOT NULL DEFAULT 'Imported',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS event_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER NOT NULL REFERENCES events(id),
    went_well TEXT,
    problems TEXT,
    improvements TEXT,
    must_apply_next TEXT,
    notes TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER REFERENCES events(id),
    manual_id INTEGER REFERENCES manuals(id),
    title TEXT NOT NULL,
    previous_method TEXT,
    new_method TEXT,
    reason TEXT,
    decided_at TEXT,
    decided_by TEXT,
    evidence TEXT,
    status TEXT NOT NULL DEFAULT 'APPROVED',
    source TEXT,
    data_quality TEXT NOT NULL DEFAULT 'Verified',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS operation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id INTEGER REFERENCES events(id),
    log_type TEXT NOT NULL DEFAULT '참고',
    title TEXT NOT NULL,
    description TEXT,
    equipment TEXT,
    symptom TEXT,
    cause TEXT,
    action_taken TEXT,
    result TEXT,
    needs_recheck INTEGER NOT NULL DEFAULT 0,
    occurred_at TEXT,
    source TEXT,
    data_quality TEXT NOT NULL DEFAULT 'Verified',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS references_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    ref_type TEXT,
    description TEXT,
    reference_time TEXT,
    reference_date TEXT,
    event_id INTEGER REFERENCES events(id),
    decision_id INTEGER REFERENCES decisions(id),
    manual_id INTEGER REFERENCES manuals(id),
    source TEXT,
    data_quality TEXT NOT NULL DEFAULT 'Imported',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS church_calendar_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT NOT NULL UNIQUE,
    calendar_id TEXT,
    title TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT,
    description TEXT,
    location TEXT,
    html_link TEXT,
    source_updated_at TEXT,
    synced_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'CONFIRMED',
    archived_at TEXT
);

CREATE TABLE IF NOT EXISTS services (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_date TEXT NOT NULL,
    service_type TEXT,
    canonical_key TEXT,
    special_sequence TEXT,
    representative_prayer TEXT,
    source TEXT,
    source_sheet TEXT,
    data_quality TEXT NOT NULL DEFAULT 'Imported',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(service_date, service_type, source_sheet)
);

CREATE TABLE IF NOT EXISTS service_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id INTEGER NOT NULL REFERENCES services(id) ON DELETE CASCADE,
    source TEXT NOT NULL DEFAULT '',
    source_sheet TEXT NOT NULL DEFAULT '',
    special_sequence TEXT,
    representative_prayer TEXT,
    data_quality TEXT NOT NULL DEFAULT 'Imported',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(service_id, source, source_sheet)
);

CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_date TEXT NOT NULL,
    service_type TEXT NOT NULL,
    online_count INTEGER,
    offline_count INTEGER,
    total_count INTEGER,
    record_status TEXT NOT NULL DEFAULT 'UNKNOWN'
        CHECK(record_status IN ('COUNTED','PENDING','CANCELLED','NO_STREAM','ESTIMATED','UNKNOWN')),
    raw_online_count INTEGER,
    raw_offline_count INTEGER,
    raw_total_count INTEGER,
    metric_type TEXT NOT NULL DEFAULT 'ONSITE_PLUS_ONLINE_UNDEFINED',
    measurement_note TEXT,
    event_id INTEGER REFERENCES events(id),
    service_id INTEGER REFERENCES services(id),
    notes TEXT,
    source TEXT,
    source_sheet TEXT,
    source_row INTEGER,
    data_quality TEXT NOT NULL DEFAULT 'Imported',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(service_date, service_type, source_sheet, source_row)
);

CREATE TABLE IF NOT EXISTS members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    team TEXT,
    role TEXT,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    note TEXT,
    source TEXT,
    data_quality TEXT NOT NULL DEFAULT 'Imported',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_id INTEGER REFERENCES services(id),
    member_id INTEGER REFERENCES members(id),
    role TEXT NOT NULL,
    raw_name TEXT,
    source TEXT,
    data_quality TEXT NOT NULL DEFAULT 'Imported',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(service_id, role, member_id, raw_name)
);

CREATE TABLE IF NOT EXISTS review_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'REVIEW_REQUIRED',
    created_by TEXT NOT NULL,
    updated_by TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TEXT,
    archived_at TEXT,
    CHECK(status IN ('REVIEW_REQUIRED','IN_PROGRESS','CONFIRMED'))
);

CREATE TABLE IF NOT EXISTS review_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_item_id INTEGER NOT NULL REFERENCES review_items(id) ON DELETE CASCADE,
    parent_comment_id INTEGER REFERENCES review_comments(id),
    author TEXT NOT NULL,
    body TEXT NOT NULL,
    status_change TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    archived_at TEXT,
    CHECK(status_change IS NULL OR status_change IN ('REVIEW_REQUIRED','IN_PROGRESS','CONFIRMED'))
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '로컬 사용자',
    before_json TEXT,
    after_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_events_date ON events(event_date);
CREATE INDEX IF NOT EXISTS idx_events_series ON events(series_key, event_date);
CREATE INDEX IF NOT EXISTS idx_tasks_event_status ON tasks(event_id, status);
CREATE INDEX IF NOT EXISTS idx_attendance_date_type ON attendance(service_date, service_type);
CREATE INDEX IF NOT EXISTS idx_manuals_status ON manuals(status);
CREATE INDEX IF NOT EXISTS idx_logs_event ON operation_logs(event_id);
CREATE INDEX IF NOT EXISTS idx_review_items_status ON review_items(status, archived_at);
CREATE INDEX IF NOT EXISTS idx_review_comments_item ON review_comments(review_item_id, created_at);
CREATE INDEX IF NOT EXISTS idx_service_sources_lookup ON service_sources(source, source_sheet, service_id);
"""


def _dict_factory(cursor: sqlite3.Cursor, row: tuple[Any, ...]) -> dict[str, Any]:
    return {description[0]: row[index] for index, description in enumerate(cursor.description)}


def connect(path: Path | str = DB_PATH) -> sqlite3.Connection:
    ensure_directories()
    conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = _dict_factory
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def canonical_service_type(service_type: Any) -> str:
    """Return a stable display value without changing the source's meaning."""
    value = unicodedata.normalize("NFKC", str(service_type or ""))
    return re.sub(r"\s+", " ", value).strip()


def canonical_service_key(service_date: Any, service_type: Any) -> str:
    date_value = str(service_date or "").strip()
    # Spacing in sheet labels is presentation, not occurrence identity:
    # "주일 예배" and "주일예배" refer to the same service.
    type_value = re.sub(r"\s+", "", canonical_service_type(service_type)).casefold()
    if not date_value or not type_value:
        raise ValueError("예배 날짜와 예배 종류가 있어야 예배 회차를 식별할 수 있습니다.")
    return f"{date_value}|{type_value}"


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(item["name"]) for item in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column(conn: sqlite3.Connection, table: str, definition: str) -> None:
    column = definition.split()[0]
    if column not in _table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")


def _merge_text_values(*values: Any) -> str | None:
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in result:
            result.append(text)
    return " / ".join(result) or None


def upsert_service_source(
    conn: sqlite3.Connection,
    service_id: int,
    source: str | None,
    source_sheet: str | None,
    special_sequence: str | None = None,
    representative_prayer: str | None = None,
    data_quality: str = "Imported",
) -> None:
    """Preserve every source row while all consumers use one canonical service."""
    conn.execute(
        "INSERT INTO service_sources(service_id,source,source_sheet,special_sequence,representative_prayer,data_quality) "
        "VALUES(?,?,?,?,?,?) ON CONFLICT(service_id,source,source_sheet) DO UPDATE SET "
        "special_sequence=CASE WHEN excluded.special_sequence<>'' THEN excluded.special_sequence ELSE service_sources.special_sequence END,"
        "representative_prayer=CASE WHEN excluded.representative_prayer<>'' THEN excluded.representative_prayer ELSE service_sources.representative_prayer END,"
        "data_quality=excluded.data_quality,updated_at=CURRENT_TIMESTAMP",
        (
            service_id,
            str(source or ""),
            str(source_sheet or ""),
            str(special_sequence or ""),
            str(representative_prayer or ""),
            data_quality or "Imported",
        ),
    )


def get_or_create_canonical_service(
    conn: sqlite3.Connection,
    service_date: str,
    service_type: str,
    *,
    special_sequence: str | None = None,
    representative_prayer: str | None = None,
    source: str | None = None,
    source_sheet: str | None = None,
    data_quality: str = "Imported",
) -> int:
    """Get the single service occurrence shared by attendance, lineup and events."""
    display_type = canonical_service_type(service_type)
    key = canonical_service_key(service_date, display_type)
    item = conn.execute("SELECT * FROM services WHERE canonical_key=? ORDER BY id LIMIT 1", (key,)).fetchone()
    if item is None:
        cur = conn.execute(
            "INSERT INTO services(service_date,service_type,canonical_key,special_sequence,representative_prayer,source,source_sheet,data_quality) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (service_date, display_type, key, special_sequence, representative_prayer, source, source_sheet, data_quality),
        )
        service_id = int(cur.lastrowid)
    else:
        service_id = int(item["id"])
        merged_special = _merge_text_values(item["special_sequence"], special_sequence)
        merged_prayer = _merge_text_values(item["representative_prayer"], representative_prayer)
        merged_quality = "Needs Review" if "Needs Review" in {item["data_quality"], data_quality} else (item["data_quality"] or data_quality)
        conn.execute(
            "UPDATE services SET special_sequence=?,representative_prayer=?,"
            "source=COALESCE(NULLIF(source,''),?),source_sheet=COALESCE(NULLIF(source_sheet,''),?),data_quality=? WHERE id=?",
            (merged_special, merged_prayer, source, source_sheet, merged_quality, service_id),
        )
    upsert_service_source(
        conn,
        service_id,
        source,
        source_sheet,
        special_sequence,
        representative_prayer,
        data_quality,
    )
    return service_id


def canonicalize_service_records(conn: sqlite3.Connection) -> None:
    """Merge legacy per-sheet services without losing assignments or provenance."""
    services = list(conn.execute("SELECT * FROM services ORDER BY id").fetchall())
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in services:
        try:
            key = canonical_service_key(item["service_date"], item["service_type"])
        except ValueError:
            continue
        grouped.setdefault(key, []).append(item)

    for key, items in grouped.items():
        canonical = items[0]
        canonical_id = int(canonical["id"])
        merged_special = _merge_text_values(*(item["special_sequence"] for item in items))
        merged_prayer = _merge_text_values(*(item["representative_prayer"] for item in items))
        merged_quality = "Needs Review" if any(item["data_quality"] == "Needs Review" for item in items) else canonical["data_quality"]

        for item in items:
            upsert_service_source(
                conn,
                canonical_id,
                item["source"],
                item["source_sheet"],
                item["special_sequence"],
                item["representative_prayer"],
                item["data_quality"],
            )

        for duplicate in items[1:]:
            duplicate_id = int(duplicate["id"])
            for source_item in conn.execute(
                "SELECT * FROM service_sources WHERE service_id=?", (duplicate_id,)
            ).fetchall():
                upsert_service_source(
                    conn,
                    canonical_id,
                    source_item["source"],
                    source_item["source_sheet"],
                    source_item["special_sequence"],
                    source_item["representative_prayer"],
                    source_item["data_quality"],
                )
            conn.execute("UPDATE attendance SET service_id=? WHERE service_id=?", (canonical_id, duplicate_id))
            conn.execute(
                "INSERT OR IGNORE INTO assignments(service_id,member_id,role,raw_name,source,data_quality,created_at) "
                "SELECT ?,member_id,role,raw_name,source,data_quality,created_at FROM assignments WHERE service_id=?",
                (canonical_id, duplicate_id),
            )
            conn.execute("DELETE FROM assignments WHERE service_id=?", (duplicate_id,))
            if "service_id" in _table_columns(conn, "events"):
                conn.execute("UPDATE events SET service_id=? WHERE service_id=?", (canonical_id, duplicate_id))
            conn.execute("DELETE FROM service_sources WHERE service_id=?", (duplicate_id,))
            conn.execute("DELETE FROM services WHERE id=?", (duplicate_id,))

        conn.execute(
            "UPDATE services SET service_type=?,canonical_key=?,special_sequence=?,representative_prayer=?,data_quality=? WHERE id=?",
            (
                canonical_service_type(canonical["service_type"]),
                key,
                merged_special,
                merged_prayer,
                merged_quality,
                canonical_id,
            ),
        )
        conn.execute(
            "UPDATE attendance SET service_type=? WHERE service_id=?",
            (canonical_service_type(canonical["service_type"]), canonical_id),
        )


def relink_attendance_events(conn: sqlite3.Connection) -> None:
    """Link imported events only when their exact canonical service can be proven."""
    events = list(conn.execute("SELECT * FROM events WHERE event_date IS NOT NULL ORDER BY id").fetchall())
    for event in events:
        service = None
        if event.get("service_id") is not None:
            candidate = conn.execute(
                "SELECT * FROM services WHERE id=? AND service_date=?",
                (event["service_id"], event["event_date"]),
            ).fetchone()
            if candidate and (not event.get("service_type") or canonical_service_type(event["service_type"]) == candidate["service_type"]):
                service = candidate

        if service is None and event.get("service_type"):
            key = canonical_service_key(event["event_date"], event["service_type"])
            service = conn.execute("SELECT * FROM services WHERE canonical_key=?", (key,)).fetchone()

        if service is None and event.get("source_event_id"):
            source_sheet = str(event["source_event_id"]).rsplit(":", 1)[0]
            matches = conn.execute(
                "SELECT DISTINCT s.* FROM services s JOIN service_sources ss ON ss.service_id=s.id "
                "WHERE s.service_date=? AND ss.source=? AND ss.source_sheet=?",
                (event["event_date"], str(event.get("source") or ""), source_sheet),
            ).fetchall()
            if len(matches) == 1:
                service = matches[0]

        if service is None:
            candidates = conn.execute(
                "SELECT * FROM services WHERE service_date=? AND COALESCE(special_sequence,'')<>''",
                (event["event_date"],),
            ).fetchall()
            title_compact = re.sub(r"\s+", "", str(event["title"] or "")).casefold()
            matches = [
                item for item in candidates
                if re.sub(r"\s+", "", str(item["special_sequence"] or "")).casefold() in title_compact
            ]
            if len(matches) == 1:
                service = matches[0]

        if service is not None:
            conn.execute(
                "UPDATE events SET service_id=?,service_type=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (service["id"], service["service_type"], event["id"]),
            )
        elif event.get("service_id") is not None:
            conn.execute(
                "UPDATE events SET service_id=NULL,service_type=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (event["id"],),
            )

    # Remove the old date-only links, then restore only exact service links.
    conn.execute(
        "UPDATE attendance SET event_id=NULL WHERE event_id IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM events e WHERE e.id=attendance.event_id AND e.service_id=attendance.service_id)"
    )
    for service_event in conn.execute(
        "SELECT service_id,MIN(id) AS event_id FROM events WHERE service_id IS NOT NULL AND archived_at IS NULL GROUP BY service_id"
    ).fetchall():
        conn.execute(
            "UPDATE attendance SET event_id=? WHERE service_id=?",
            (service_event["event_id"], service_event["service_id"]),
        )


def _upgrade_schema(conn: sqlite3.Connection) -> None:
    _add_column(conn, "services", "canonical_key TEXT")
    _add_column(conn, "events", "service_id INTEGER REFERENCES services(id)")
    _add_column(conn, "events", "service_type TEXT")
    _add_column(conn, "attendance", "record_status TEXT NOT NULL DEFAULT 'UNKNOWN'")
    _add_column(conn, "attendance", "raw_online_count INTEGER")
    _add_column(conn, "attendance", "raw_offline_count INTEGER")
    _add_column(conn, "attendance", "raw_total_count INTEGER")
    _add_column(conn, "attendance", "metric_type TEXT NOT NULL DEFAULT 'ONSITE_PLUS_ONLINE_UNDEFINED'")
    _add_column(conn, "attendance", "measurement_note TEXT")

    # CREATE TABLE IF NOT EXISTS above creates this table on both old and new databases.
    for item in conn.execute("SELECT * FROM services").fetchall():
        upsert_service_source(
            conn,
            int(item["id"]),
            item["source"],
            item["source_sheet"],
            item["special_sequence"],
            item["representative_prayer"],
            item["data_quality"],
        )
    canonicalize_service_records(conn)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_services_canonical_key ON services(canonical_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_attendance_service ON attendance(service_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_events_service ON events(service_id)")

    backfilled = conn.execute(
        "SELECT value FROM app_meta WHERE key='attendance_reliability_backfill_v1'"
    ).fetchone()
    if not backfilled:
        conn.execute(
            "UPDATE attendance SET record_status=CASE "
            "WHEN COALESCE(total_count,0)>0 THEN 'COUNTED' "
            "WHEN COALESCE(online_count,0)=0 AND COALESCE(offline_count,0)=0 AND COALESCE(total_count,0)=0 "
            "AND data_quality='Needs Review' THEN 'PENDING' ELSE 'UNKNOWN' END"
        )
        conn.execute(
            "UPDATE attendance SET "
            "raw_online_count=CASE WHEN record_status='PENDING' THEN NULL ELSE online_count END,"
            "raw_offline_count=CASE WHEN record_status='PENDING' THEN NULL ELSE offline_count END,"
            "raw_total_count=CASE WHEN record_status='PENDING' THEN NULL ELSE total_count END,"
            "metric_type='ONSITE_PLUS_ONLINE_UNDEFINED',"
            "measurement_note=CASE WHEN record_status='PENDING' "
            "THEN '기존 확인필요 0값을 미입력으로 추정해 변환함' "
            "ELSE '기존 DB 값에서 자동 보존함; 원본 빈칸과 명시적 0의 구분은 확인 필요' END"
        )
        conn.execute(
            "INSERT INTO app_meta(key,value) VALUES('attendance_reliability_backfill_v1','complete')"
        )
    relink_attendance_events(conn)


def init_db(path: Path | str = DB_PATH) -> None:
    with closing(connect(path)) as conn:
        conn.executescript(SCHEMA)
        version_row = conn.execute(
            "SELECT value FROM app_meta WHERE key='schema_version'"
        ).fetchone()
        try:
            current_version = int(version_row["value"]) if version_row else 0
        except (TypeError, ValueError):
            current_version = 0
        if current_version > 3:
            raise RuntimeError(
                f"이 앱보다 새로운 데이터베이스 형식입니다. DB v{current_version}, 앱 지원 v3"
            )
        if current_version < 3:
            _upgrade_schema(conn)
            conn.execute(
                "INSERT INTO app_meta(key, value) VALUES('schema_version', '3') "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=CURRENT_TIMESTAMP"
            )
        conn.commit()


@contextmanager
def transaction(path: Path | str = DB_PATH):
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _sql_params(params: Iterable[Any] | Mapping[str, Any]) -> tuple[Any, ...] | Mapping[str, Any]:
    """Preserve mappings for SQLite named placeholders on strict Python versions."""
    return params if isinstance(params, Mapping) else tuple(params)


def rows(sql: str, params: Iterable[Any] | Mapping[str, Any] = (), path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    with closing(connect(path)) as conn:
        return list(conn.execute(sql, _sql_params(params)).fetchall())


def row(sql: str, params: Iterable[Any] | Mapping[str, Any] = (), path: Path | str = DB_PATH) -> dict[str, Any] | None:
    with closing(connect(path)) as conn:
        return conn.execute(sql, _sql_params(params)).fetchone()


def get_app_meta(key: str, default: str = "", path: Path | str = DB_PATH) -> str:
    item = row("SELECT value FROM app_meta WHERE key=?", (key,), path)
    return item["value"] if item else default


def set_app_meta(key: str, value: str, path: Path | str = DB_PATH) -> None:
    with transaction(path) as conn:
        conn.execute(
            "INSERT INTO app_meta(key,value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",
            (key, value),
        )


def create_review_item(
    title: str,
    description: str,
    created_by: str,
    path: Path | str = DB_PATH,
) -> int:
    title = title.strip()
    created_by = created_by.strip()
    if not title or not created_by:
        raise ValueError("제목과 작성자를 입력하세요.")
    with transaction(path) as conn:
        cur = conn.execute(
            "INSERT INTO review_items(title,description,created_by,updated_by) VALUES(?,?,?,?)",
            (title[:200], description.strip()[:4000], created_by[:80], created_by[:80]),
        )
        item_id = int(cur.lastrowid)
        audit(conn, "review_items", item_id, "CREATE", after={"title": title, "created_by": created_by})
        return item_id


def add_review_comment(
    review_item_id: int,
    author: str,
    body: str,
    status_change: str | None = None,
    parent_comment_id: int | None = None,
    path: Path | str = DB_PATH,
) -> int:
    author = author.strip()
    body = body.strip()
    valid_statuses = {"REVIEW_REQUIRED", "IN_PROGRESS", "CONFIRMED"}
    if not author or not body:
        raise ValueError("작성자와 댓글을 입력하세요.")
    if status_change is not None and status_change not in valid_statuses:
        raise ValueError("올바르지 않은 상태입니다.")
    with transaction(path) as conn:
        item = conn.execute(
            "SELECT * FROM review_items WHERE id=? AND archived_at IS NULL", (review_item_id,)
        ).fetchone()
        if not item:
            raise ValueError("확인항목을 찾을 수 없습니다.")
        cur = conn.execute(
            "INSERT INTO review_comments(review_item_id,parent_comment_id,author,body,status_change) VALUES(?,?,?,?,?)",
            (review_item_id, parent_comment_id, author[:80], body[:4000], status_change),
        )
        if status_change:
            conn.execute(
                "UPDATE review_items SET status=?,updated_by=?,updated_at=CURRENT_TIMESTAMP,"
                "confirmed_at=CASE WHEN ?='CONFIRMED' THEN CURRENT_TIMESTAMP ELSE NULL END WHERE id=?",
                (status_change, author[:80], status_change, review_item_id),
            )
        else:
            conn.execute(
                "UPDATE review_items SET updated_by=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (author[:80], review_item_id),
            )
        audit(
            conn, "review_items", review_item_id, "COMMENT",
            before={"status": item["status"]},
            after={"author": author, "status": status_change or item["status"]},
        )
        return int(cur.lastrowid)


def audit(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: int | None,
    action: str,
    before: Any = None,
    after: Any = None,
) -> None:
    conn.execute(
        "INSERT INTO audit_logs(entity_type, entity_id, action, before_json, after_json) VALUES(?,?,?,?,?)",
        (entity_type, entity_id, action, json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
         json.dumps(after, ensure_ascii=False, default=str) if after is not None else None),
    )


def series_key(title: str) -> str:
    value = re.sub(r"\b(19|20)\d{2}\b", "", title)
    value = re.sub(r"\d+차", "", value)
    value = re.sub(r"\s+", " ", value).strip().lower()
    return value or title.strip().lower()


def create_event(
    title: str,
    event_date: str | date | None,
    category: str = "특별예배",
    template_id: int | None = None,
    owner: str = "",
    description: str = "",
    path: Path | str = DB_PATH,
) -> int:
    date_text = event_date.isoformat() if isinstance(event_date, date) else event_date
    key = series_key(title)
    with transaction(path) as conn:
        previous = conn.execute(
            "SELECT id FROM events WHERE series_key=? AND archived_at IS NULL "
            "AND (? IS NULL OR event_date < ?) ORDER BY event_date DESC, id DESC LIMIT 1",
            (key, date_text, date_text),
        ).fetchone()
        cur = conn.execute(
            "INSERT INTO events(title, series_key, category, event_date, owner, description, event_template_id, previous_event_id, data_quality) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (title, key, category, date_text, owner, description, template_id, previous["id"] if previous else None, "Verified"),
        )
        event_id = int(cur.lastrowid)
        if template_id:
            templates = conn.execute(
                "SELECT * FROM task_templates WHERE event_template_id=? AND data_quality<>'Stale' ORDER BY due_offset, id", (template_id,)
            ).fetchall()
            task_id_map: dict[int, int] = {}
            for item in templates:
                due_date = None
                if date_text and item["due_offset"] is not None:
                    due_date = (date.fromisoformat(date_text) + timedelta(days=int(item["due_offset"]))).isoformat()
                task_cur = conn.execute(
                    "INSERT INTO tasks(event_id, task_template_id, title, description, owner, priority, source_timing, due_offset, due_date, source, data_quality) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (event_id, item["id"], item["title"], item["description"], item["default_owner"], item["priority"],
                     item["source_timing"], item["due_offset"], due_date, item["source"], item["data_quality"]),
                )
                task_id_map[item["id"]] = int(task_cur.lastrowid)
            for item in templates:
                if item["depends_on_template_id"] and item["id"] in task_id_map:
                    conn.execute(
                        "UPDATE tasks SET depends_on=? WHERE id=?",
                        (task_id_map.get(item["depends_on_template_id"]), task_id_map[item["id"]]),
                    )
        audit(conn, "event", event_id, "CREATE", after={"title": title, "event_date": date_text, "template_id": template_id})
        return event_id


def clone_event(source_event_id: int, new_title: str, new_date: str | date, path: Path | str = DB_PATH) -> int:
    date_text = new_date.isoformat() if isinstance(new_date, date) else new_date
    with transaction(path) as conn:
        source = conn.execute("SELECT * FROM events WHERE id=?", (source_event_id,)).fetchone()
        if not source:
            raise ValueError("복제할 행사를 찾을 수 없습니다.")
        cur = conn.execute(
            "INSERT INTO events(title, series_key, category, event_date, description, owner, status, event_template_id, previous_event_id, source, data_quality) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (new_title, source["series_key"], source["category"], date_text, source["description"], source["owner"],
             "PLANNING", source["event_template_id"], source_event_id, "행사 복제", "Verified"),
        )
        new_id = int(cur.lastrowid)
        old_tasks = conn.execute("SELECT * FROM tasks WHERE event_id=? AND archived_at IS NULL ORDER BY id", (source_event_id,)).fetchall()
        id_map: dict[int, int] = {}
        for task in old_tasks:
            due_date = None
            if task["due_offset"] is not None:
                due_date = (date.fromisoformat(date_text) + timedelta(days=int(task["due_offset"]))).isoformat()
            task_cur = conn.execute(
                "INSERT INTO tasks(event_id, task_template_id, title, description, owner, status, priority, source_timing, due_offset, due_date, source, data_quality) "
                "VALUES(?,?,?,?,?,'TODO',?,?,?,?,?,?)",
                (new_id, task["task_template_id"], task["title"], task["description"], task["owner"], task["priority"],
                 task["source_timing"], task["due_offset"], due_date, "이전 행사 복제", task["data_quality"]),
            )
            id_map[task["id"]] = int(task_cur.lastrowid)
        for task in old_tasks:
            if task["depends_on"] and task["id"] in id_map:
                conn.execute("UPDATE tasks SET depends_on=? WHERE id=?", (id_map.get(task["depends_on"]), id_map[task["id"]]))
        audit(conn, "event", new_id, "CLONE", before={"source_event_id": source_event_id}, after={"title": new_title, "event_date": date_text})
        return new_id


def readiness(event_id: int, path: Path | str = DB_PATH) -> dict[str, Any]:
    items = rows("SELECT status, priority FROM tasks WHERE event_id=? AND archived_at IS NULL", (event_id,), path)
    weight = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    total = sum(weight.get(item["priority"], 2) for item in items)
    done = sum(weight.get(item["priority"], 2) for item in items if item["status"] == "DONE")
    return {
        "percent": round((done / total * 100) if total else 0),
        "total": len(items),
        "done": sum(1 for item in items if item["status"] == "DONE"),
        "open": sum(1 for item in items if item["status"] != "DONE"),
        "high_open": sum(1 for item in items if item["status"] != "DONE" and item["priority"] == "HIGH"),
    }


def add_task(
    event_id: int,
    title: str,
    description: str = "",
    owner: str = "",
    priority: str = "MEDIUM",
    due_date: str | None = None,
    depends_on: int | None = None,
    source: str = "사용자 입력",
    path: Path | str = DB_PATH,
) -> int:
    with transaction(path) as conn:
        cur = conn.execute(
            "INSERT INTO tasks(event_id,title,description,owner,priority,due_date,depends_on,source,data_quality) VALUES(?,?,?,?,?,?,?,?,?)",
            (event_id, title, description, owner, priority, due_date, depends_on, source, "Verified"),
        )
        task_id = int(cur.lastrowid)
        audit(conn, "task", task_id, "CREATE", after={"event_id": event_id, "title": title})
        return task_id


def set_task_status(task_id: int, status: str, path: Path | str = DB_PATH) -> None:
    with transaction(path) as conn:
        before = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        completed = now_kst().isoformat(timespec="seconds") if status == "DONE" else None
        conn.execute("UPDATE tasks SET status=?, completed_at=? WHERE id=?", (status, completed, task_id))
        audit(conn, "task", task_id, "STATUS", before=before, after={"status": status})


def update_event_status(event_id: int, status: str, path: Path | str = DB_PATH) -> None:
    with transaction(path) as conn:
        before = conn.execute("SELECT status FROM events WHERE id=?", (event_id,)).fetchone()
        conn.execute("UPDATE events SET status=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (status, event_id))
        audit(conn, "event", event_id, "STATUS", before=before, after={"status": status})


def create_event_template(title: str, category: str, description: str = "", manual_id: int | None = None, path: Path | str = DB_PATH) -> int:
    with transaction(path) as conn:
        cur = conn.execute(
            "INSERT INTO event_templates(title,category,description,manual_id,source,data_quality) VALUES(?,?,?,?,?,?)",
            (title, category, description, manual_id, "사용자 입력", "Verified"),
        )
        template_id = int(cur.lastrowid)
        audit(conn, "event_template", template_id, "CREATE", after={"title": title})
        return template_id


def add_task_template(
    event_template_id: int,
    title: str,
    description: str = "",
    source_timing: str = "",
    due_offset: int | None = None,
    priority: str = "MEDIUM",
    default_owner: str = "",
    path: Path | str = DB_PATH,
) -> int:
    with transaction(path) as conn:
        cur = conn.execute(
            "INSERT INTO task_templates(event_template_id,title,description,source_timing,due_offset,priority,default_owner,source,data_quality) VALUES(?,?,?,?,?,?,?,?,?)",
            (event_template_id, title, description, source_timing, due_offset, priority, default_owner, "사용자 입력", "Verified"),
        )
        item_id = int(cur.lastrowid)
        audit(conn, "task_template", item_id, "CREATE", after={"event_template_id": event_template_id, "title": title})
        return item_id


def add_reference_record(values: dict[str, Any], path: Path | str = DB_PATH) -> int:
    keys = ["title", "url", "ref_type", "description", "reference_time", "reference_date", "event_id", "decision_id", "manual_id"]
    with transaction(path) as conn:
        cur = conn.execute(
            "INSERT INTO references_data(title,url,ref_type,description,reference_time,reference_date,event_id,decision_id,manual_id,source,data_quality) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            tuple(values.get(key) or None for key in keys) + ("사용자 입력", "Verified"),
        )
        ref_id = int(cur.lastrowid)
        audit(conn, "reference", ref_id, "CREATE", after=values)
        return ref_id


def save_review(event_id: int, values: dict[str, str], path: Path | str = DB_PATH) -> int:
    with transaction(path) as conn:
        existing = conn.execute("SELECT * FROM event_reviews WHERE event_id=?", (event_id,)).fetchone()
        if existing:
            conn.execute(
                "UPDATE event_reviews SET went_well=?, problems=?, improvements=?, must_apply_next=?, notes=?, updated_at=CURRENT_TIMESTAMP WHERE event_id=?",
                (values.get("went_well"), values.get("problems"), values.get("improvements"), values.get("must_apply_next"), values.get("notes"), event_id),
            )
            review_id = existing["id"]
            action = "REVISION"
        else:
            cur = conn.execute(
                "INSERT INTO event_reviews(event_id,went_well,problems,improvements,must_apply_next,notes) VALUES(?,?,?,?,?,?)",
                (event_id, values.get("went_well"), values.get("problems"), values.get("improvements"), values.get("must_apply_next"), values.get("notes")),
            )
            review_id = int(cur.lastrowid)
            action = "CREATE"
        audit(conn, "event_review", review_id, action, before=existing, after=values)
        return int(review_id)


def carry_review_issue(review_id: int, target_event_id: int, text: str, path: Path | str = DB_PATH) -> int:
    return add_task(target_event_id, f"이전 회고 반영: {text[:80]}", text, priority="HIGH", source=f"회고 #{review_id}", path=path)


def create_manual(
    title: str,
    category: str,
    what_text: str,
    how_text: str,
    why_text: str,
    caution: str = "",
    current_standard: str = "",
    path: Path | str = DB_PATH,
) -> int:
    with transaction(path) as conn:
        cur = conn.execute(
            "INSERT INTO manuals(title,category,current_standard,data_quality,last_verified) VALUES(?,?,?,?,?)",
            (title, category, current_standard, "Verified", today_kst().isoformat()),
        )
        manual_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO manual_revisions(manual_id,version,what_text,how_text,why_text,caution,change_summary,effective_from) VALUES(?,?,?,?,?,?,?,?)",
            (manual_id, 1, what_text, how_text, why_text, caution, "최초 작성", today_kst().isoformat()),
        )
        audit(conn, "manual", manual_id, "CREATE", after={"title": title})
        return manual_id


def revise_manual(
    manual_id: int,
    what_text: str,
    how_text: str,
    why_text: str,
    caution: str,
    current_standard: str,
    change_summary: str,
    path: Path | str = DB_PATH,
) -> int:
    with transaction(path) as conn:
        manual = conn.execute("SELECT * FROM manuals WHERE id=?", (manual_id,)).fetchone()
        if not manual:
            raise ValueError("매뉴얼을 찾을 수 없습니다.")
        conn.execute("UPDATE manual_revisions SET status='SUPERSEDED' WHERE manual_id=? AND status='CURRENT'", (manual_id,))
        version = int(manual["version"]) + 1
        cur = conn.execute(
            "INSERT INTO manual_revisions(manual_id,version,what_text,how_text,why_text,caution,change_summary,effective_from,status) VALUES(?,?,?,?,?,?,?,?, 'CURRENT')",
            (manual_id, version, what_text, how_text, why_text, caution, change_summary, today_kst().isoformat()),
        )
        conn.execute(
            "UPDATE manuals SET version=?, current_standard=?, data_quality='Verified', updated_at=CURRENT_TIMESTAMP, status='CURRENT' WHERE id=?",
            (version, current_standard, manual_id),
        )
        audit(conn, "manual", manual_id, "REVISION", before={"version": manual["version"]}, after={"version": version, "summary": change_summary})
        return int(cur.lastrowid)


def verify_manual(manual_id: int, path: Path | str = DB_PATH) -> None:
    with transaction(path) as conn:
        before = conn.execute("SELECT last_verified FROM manuals WHERE id=?", (manual_id,)).fetchone()
        verified_on = today_kst().isoformat()
        conn.execute("UPDATE manuals SET last_verified=?, data_quality='Verified', updated_at=CURRENT_TIMESTAMP WHERE id=?", (verified_on, manual_id))
        audit(conn, "manual", manual_id, "VERIFY", before=before, after={"last_verified": verified_on})


def add_decision(values: dict[str, Any], path: Path | str = DB_PATH) -> int:
    keys = ["event_id", "manual_id", "title", "previous_method", "new_method", "reason", "decided_at", "decided_by", "evidence", "status"]
    with transaction(path) as conn:
        cur = conn.execute(
            "INSERT INTO decisions(event_id,manual_id,title,previous_method,new_method,reason,decided_at,decided_by,evidence,status) VALUES(?,?,?,?,?,?,?,?,?,?)",
            tuple(values.get(key) or None for key in keys),
        )
        decision_id = int(cur.lastrowid)
        audit(conn, "decision", decision_id, "CREATE", after=values)
        return decision_id


def add_operation_log(values: dict[str, Any], path: Path | str = DB_PATH) -> int:
    keys = ["event_id", "log_type", "title", "description", "equipment", "symptom", "cause", "action_taken", "result", "needs_recheck", "occurred_at"]
    with transaction(path) as conn:
        cur = conn.execute(
            "INSERT INTO operation_logs(event_id,log_type,title,description,equipment,symptom,cause,action_taken,result,needs_recheck,occurred_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            tuple(values.get(key) or None for key in keys),
        )
        log_id = int(cur.lastrowid)
        audit(conn, "operation_log", log_id, "CREATE", after=values)
        return log_id


def archive_entity(entity: str, entity_id: int, restore: bool = False, path: Path | str = DB_PATH) -> None:
    allowed = {"events": "event", "manuals": "manual", "decisions": "decision", "operation_logs": "operation_log", "references_data": "reference"}
    if entity not in allowed:
        raise ValueError("지원하지 않는 보관 대상입니다.")
    value = None if restore else now_kst().isoformat(timespec="seconds")
    with transaction(path) as conn:
        before = conn.execute(f"SELECT * FROM {entity} WHERE id=?", (entity_id,)).fetchone()
        conn.execute(f"UPDATE {entity} SET archived_at=? WHERE id=?", (value, entity_id))
        if entity == "manuals":
            conn.execute("UPDATE manuals SET status=? WHERE id=?", ("CURRENT" if restore else "ARCHIVED", entity_id))
        audit(conn, allowed[entity], entity_id, "RESTORE" if restore else "ARCHIVE", before=before, after={"archived_at": value})


def global_search(term: str, include_archived: bool = False, path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    like = f"%{term.strip()}%"
    if not term.strip():
        return []
    unions = [
        ("행사", "events", "title", "description", "event_date", "행사", "" if include_archived else " AND events.archived_at IS NULL"),
        ("매뉴얼", "manuals", "title", "current_standard", "updated_at", "매뉴얼", "" if include_archived else " AND manuals.status='CURRENT' AND manuals.archived_at IS NULL"),
        ("결정", "decisions", "title", "reason", "decided_at", "결정·운영로그", "" if include_archived else " AND decisions.archived_at IS NULL"),
        ("운영로그", "operation_logs", "title", "description", "occurred_at", "결정·운영로그", "" if include_archived else " AND operation_logs.archived_at IS NULL"),
    ]
    results: list[dict[str, Any]] = []
    with closing(connect(path)) as conn:
        for kind, table, title, body, when, target_page, condition in unions:
            found = conn.execute(
                f"SELECT id, ? AS kind, {title} AS title, COALESCE({body},'') AS snippet, {when} AS item_date, "
                f"? AS target_page, id AS target_id, "
                f"CASE WHEN {table}.archived_at IS NULL THEN 0 ELSE 1 END AS archived FROM {table} "
                f"WHERE ({title} LIKE ? OR COALESCE({body},'') LIKE ?){condition} LIMIT 50",
                (kind, target_page, like, like),
            ).fetchall()
            results.extend(found)
        found_tasks = conn.execute(
            "SELECT tasks.id, '체크리스트' AS kind, tasks.title, "
            "COALESCE(tasks.description,'') || CASE WHEN events.title IS NOT NULL THEN ' · ' || events.title ELSE '' END AS snippet, "
            "tasks.due_date AS item_date, '행사' AS target_page, tasks.event_id AS target_id, "
            "CASE WHEN tasks.archived_at IS NULL AND events.archived_at IS NULL THEN 0 ELSE 1 END AS archived "
            "FROM tasks JOIN events ON events.id=tasks.event_id "
            "WHERE (tasks.title LIKE ? OR COALESCE(tasks.description,'') LIKE ?) "
            + ("" if include_archived else "AND tasks.archived_at IS NULL AND events.archived_at IS NULL ") + "LIMIT 50",
            (like, like),
        ).fetchall()
        results.extend(found_tasks)
        found_template_tasks = conn.execute(
            "SELECT task_templates.id, '매뉴얼 준비항목' AS kind, manuals.title || ' · ' || task_templates.title AS title, "
            "TRIM(COALESCE(task_templates.source_timing,'') || ' ' || COALESCE(task_templates.description,'')) AS snippet, "
            "task_templates.created_at AS item_date, '매뉴얼' AS target_page, manuals.id AS target_id, "
            "CASE WHEN manuals.status='CURRENT' AND event_templates.status='CURRENT' THEN 0 ELSE 1 END AS archived "
            "FROM task_templates JOIN event_templates ON event_templates.id=task_templates.event_template_id "
            "JOIN manuals ON manuals.id=event_templates.manual_id "
            "WHERE task_templates.data_quality<>'Stale' AND (task_templates.title LIKE ? OR COALESCE(task_templates.description,'') LIKE ? OR COALESCE(task_templates.source_timing,'') LIKE ?) "
            + ("" if include_archived else "AND manuals.status='CURRENT' AND manuals.archived_at IS NULL AND event_templates.status='CURRENT' ")
            + "LIMIT 50",
            (like, like, like),
        ).fetchall()
        results.extend(found_template_tasks)
        found_revisions = conn.execute(
            "SELECT manual_revisions.id, '매뉴얼 이력' AS kind, manuals.title || ' v' || manual_revisions.version AS title, "
            "COALESCE(NULLIF(manual_revisions.how_text,''),NULLIF(manual_revisions.what_text,''),manual_revisions.why_text,'') AS snippet, "
            "manual_revisions.created_at AS item_date, '매뉴얼' AS target_page, manuals.id AS target_id, "
            "CASE WHEN manual_revisions.status='CURRENT' AND manuals.archived_at IS NULL THEN 0 ELSE 1 END AS archived "
            "FROM manual_revisions JOIN manuals ON manuals.id=manual_revisions.manual_id "
            "WHERE (COALESCE(manual_revisions.what_text,'') LIKE ? OR COALESCE(manual_revisions.how_text,'') LIKE ? "
            "OR COALESCE(manual_revisions.why_text,'') LIKE ? OR COALESCE(manual_revisions.caution,'') LIKE ?) "
            + ("" if include_archived else "AND manual_revisions.status='CURRENT' AND manuals.archived_at IS NULL ") + "LIMIT 50",
            (like, like, like, like),
        ).fetchall()
        results.extend(found_revisions)
        found_references = conn.execute(
            "SELECT references_data.id, '참고자료' AS kind, COALESCE(manuals.title,events.title,'참고자료') || ' · ' || references_data.title AS title, "
            "TRIM(COALESCE(references_data.description,'') || ' ' || references_data.url) AS snippet, references_data.created_at AS item_date, "
            "CASE WHEN manuals.id IS NOT NULL THEN '매뉴얼' ELSE '행사' END AS target_page, "
            "COALESCE(manuals.id,events.id) AS target_id, "
            "CASE WHEN references_data.archived_at IS NULL AND COALESCE(manuals.archived_at,events.archived_at) IS NULL THEN 0 ELSE 1 END AS archived "
            "FROM references_data LEFT JOIN manuals ON manuals.id=references_data.manual_id "
            "LEFT JOIN events ON events.id=references_data.event_id "
            "WHERE (references_data.title LIKE ? OR COALESCE(references_data.description,'') LIKE ? OR references_data.url LIKE ?) "
            + ("" if include_archived else "AND references_data.archived_at IS NULL AND "
               "((manuals.id IS NOT NULL AND manuals.status='CURRENT' AND manuals.archived_at IS NULL) "
               "OR (events.id IS NOT NULL AND events.archived_at IS NULL)) ")
            + "LIMIT 50",
            (like, like, like),
        ).fetchall()
        results.extend(found_references)
        found_assignments = conn.execute(
            "SELECT assignments.id, '예배 담당' AS kind, members.name || ' · ' || assignments.role AS title, "
            "services.service_date || ' ' || services.service_type AS snippet, services.service_date AS item_date, "
            "'예배 인원 현황' AS target_page, services.id AS target_id, 0 AS archived "
            "FROM assignments JOIN members ON members.id=assignments.member_id "
            "JOIN services ON services.id=assignments.service_id "
            "WHERE members.name LIKE ? OR assignments.role LIKE ? OR COALESCE(assignments.raw_name,'') LIKE ? LIMIT 50",
            (like, like, like),
        ).fetchall()
        results.extend(found_assignments)
        found_calendar = conn.execute(
            "SELECT id, '교회력' AS kind, title, TRIM(COALESCE(description,'') || ' ' || COALESCE(location,'')) AS snippet, "
            "start_date AS item_date, '교회력' AS target_page, id AS target_id, "
            "CASE WHEN archived_at IS NULL THEN 0 ELSE 1 END AS archived FROM church_calendar_events "
            "WHERE (title LIKE ? OR COALESCE(description,'') LIKE ? OR COALESCE(location,'') LIKE ?) "
            + ("" if include_archived else "AND archived_at IS NULL AND status<>'CANCELLED' ") + "LIMIT 50",
            (like, like, like),
        ).fetchall()
        results.extend(found_calendar)
    priority = {"매뉴얼": 0, "매뉴얼 준비항목": 1, "참고자료": 2, "결정": 3, "행사": 4, "체크리스트": 5, "운영로그": 6, "매뉴얼 이력": 7, "예배 담당": 8, "교회력": 9}
    return sorted(results, key=lambda item: (item["archived"], priority.get(item["kind"], 9), item.get("item_date") or ""), reverse=False)


def _csv_safe_cell(value: Any) -> Any:
    """Keep spreadsheet applications from interpreting exported text as formulas."""
    if not isinstance(value, str):
        return value
    stripped = value.lstrip()
    if stripped.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + value
    return value


def export_backup(path: Path | str = DB_PATH, backup_dir: Path = BACKUP_DIR) -> tuple[Path, dict[str, str]]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = now_kst().strftime("%Y%m%d_%H%M%S")
    table_names = [
        "events", "tasks", "event_reviews", "event_templates", "task_templates", "manuals", "manual_revisions",
        "decisions", "operation_logs", "references_data", "church_calendar_events", "attendance", "services", "service_sources", "members", "assignments",
        "review_items", "review_comments", "source_files", "unresolved_imports", "audit_logs",
    ]
    payload: dict[str, Any] = {"exported_at": now_kst().isoformat(), "schema_version": 3, "tables": {}}
    csv_payloads: dict[str, str] = {}
    with closing(connect(path)) as conn:
        for table in table_names:
            items = list(conn.execute(f"SELECT * FROM {table}").fetchall())
            payload["tables"][table] = items
            buffer = io.StringIO()
            if items:
                writer = csv.DictWriter(buffer, fieldnames=items[0].keys())
                writer.writeheader()
                writer.writerows(
                    {key: _csv_safe_cell(item[key]) for key in item.keys()}
                    for item in items
                )
            csv_payloads[table] = buffer.getvalue()
    json_path = backup_dir / f"joyful_worship_ops_{stamp}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return json_path, csv_payloads


def create_sqlite_backup(path: Path | str = DB_PATH, backup_dir: Path = BACKUP_DIR) -> Path:
    """Create a native SQLite backup that can be restored as a database file."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / f"joyful_worship_ops_{now_kst().strftime('%Y%m%d_%H%M%S')}.db"
    with closing(connect(path)) as source, closing(sqlite3.connect(destination)) as target:
        source.backup(target)
    with closing(sqlite3.connect(destination)) as check_conn:
        if check_conn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            destination.unlink(missing_ok=True)
            raise RuntimeError("생성한 SQLite 백업의 무결성 검사를 통과하지 못했습니다.")
    return destination

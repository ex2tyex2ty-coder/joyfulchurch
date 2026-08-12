from __future__ import annotations

import csv
import io
import json
import re
import sqlite3
from contextlib import closing, contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from config import BACKUP_DIR, DB_PATH, ensure_directories


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
    special_sequence TEXT,
    representative_prayer TEXT,
    source TEXT,
    source_sheet TEXT,
    data_quality TEXT NOT NULL DEFAULT 'Imported',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(service_date, service_type, source_sheet)
);

CREATE TABLE IF NOT EXISTS attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    service_date TEXT NOT NULL,
    service_type TEXT NOT NULL,
    online_count INTEGER,
    offline_count INTEGER,
    total_count INTEGER,
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


def init_db(path: Path | str = DB_PATH) -> None:
    with closing(connect(path)) as conn:
        conn.executescript(SCHEMA)
        conn.execute(
            "INSERT INTO app_meta(key, value) VALUES('schema_version', '1') "
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


def rows(sql: str, params: Iterable[Any] = (), path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    with closing(connect(path)) as conn:
        return list(conn.execute(sql, tuple(params)).fetchall())


def row(sql: str, params: Iterable[Any] = (), path: Path | str = DB_PATH) -> dict[str, Any] | None:
    with closing(connect(path)) as conn:
        return conn.execute(sql, tuple(params)).fetchone()


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
                "SELECT * FROM task_templates WHERE event_template_id=? ORDER BY due_offset, id", (template_id,)
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
        completed = datetime.now().isoformat(timespec="seconds") if status == "DONE" else None
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
            (title, category, current_standard, "Verified", date.today().isoformat()),
        )
        manual_id = int(cur.lastrowid)
        conn.execute(
            "INSERT INTO manual_revisions(manual_id,version,what_text,how_text,why_text,caution,change_summary,effective_from) VALUES(?,?,?,?,?,?,?,?)",
            (manual_id, 1, what_text, how_text, why_text, caution, "최초 작성", date.today().isoformat()),
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
            (manual_id, version, what_text, how_text, why_text, caution, change_summary, date.today().isoformat()),
        )
        conn.execute(
            "UPDATE manuals SET version=?, current_standard=?, updated_at=CURRENT_TIMESTAMP, status='CURRENT' WHERE id=?",
            (version, current_standard, manual_id),
        )
        audit(conn, "manual", manual_id, "REVISION", before={"version": manual["version"]}, after={"version": version, "summary": change_summary})
        return int(cur.lastrowid)


def verify_manual(manual_id: int, path: Path | str = DB_PATH) -> None:
    with transaction(path) as conn:
        before = conn.execute("SELECT last_verified FROM manuals WHERE id=?", (manual_id,)).fetchone()
        conn.execute("UPDATE manuals SET last_verified=?, updated_at=CURRENT_TIMESTAMP WHERE id=?", (date.today().isoformat(), manual_id))
        audit(conn, "manual", manual_id, "VERIFY", before=before, after={"last_verified": date.today().isoformat()})


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
    value = None if restore else datetime.now().isoformat(timespec="seconds")
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
            "WHERE (task_templates.title LIKE ? OR COALESCE(task_templates.description,'') LIKE ? OR COALESCE(task_templates.source_timing,'') LIKE ?) "
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
            "SELECT references_data.id, '참고자료' AS kind, manuals.title || ' · ' || references_data.title AS title, "
            "TRIM(COALESCE(references_data.description,'') || ' ' || references_data.url) AS snippet, references_data.created_at AS item_date, "
            "'매뉴얼' AS target_page, manuals.id AS target_id, "
            "CASE WHEN references_data.archived_at IS NULL AND manuals.archived_at IS NULL THEN 0 ELSE 1 END AS archived "
            "FROM references_data JOIN manuals ON manuals.id=references_data.manual_id "
            "WHERE (references_data.title LIKE ? OR COALESCE(references_data.description,'') LIKE ? OR references_data.url LIKE ?) "
            + ("" if include_archived else "AND references_data.archived_at IS NULL AND manuals.status='CURRENT' AND manuals.archived_at IS NULL ")
            + "LIMIT 50",
            (like, like, like),
        ).fetchall()
        results.extend(found_references)
    priority = {"매뉴얼": 0, "매뉴얼 준비항목": 1, "참고자료": 2, "결정": 3, "행사": 4, "체크리스트": 5, "운영로그": 6, "매뉴얼 이력": 7}
    return sorted(results, key=lambda item: (item["archived"], priority.get(item["kind"], 9), item.get("item_date") or ""), reverse=False)


def export_backup(path: Path | str = DB_PATH, backup_dir: Path = BACKUP_DIR) -> tuple[Path, dict[str, str]]:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    table_names = [
        "events", "tasks", "event_reviews", "event_templates", "task_templates", "manuals", "manual_revisions",
        "decisions", "operation_logs", "references_data", "church_calendar_events", "attendance", "services", "members", "assignments",
        "source_files", "unresolved_imports", "audit_logs",
    ]
    payload: dict[str, Any] = {"exported_at": datetime.now().isoformat(), "schema_version": 1, "tables": {}}
    csv_payloads: dict[str, str] = {}
    with closing(connect(path)) as conn:
        for table in table_names:
            items = list(conn.execute(f"SELECT * FROM {table}").fetchall())
            payload["tables"][table] = items
            buffer = io.StringIO()
            if items:
                writer = csv.DictWriter(buffer, fieldnames=items[0].keys())
                writer.writeheader()
                writer.writerows(items)
            csv_payloads[table] = buffer.getvalue()
    json_path = backup_dir / f"joyful_worship_ops_{stamp}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return json_path, csv_payloads

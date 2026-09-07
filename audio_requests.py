"""Private sound-desk requests. PostgreSQL in production; SQLite only in tests.

Participant capabilities are random recovery codes, stored as hashes. No API
returns another participant's rows to a participant. Connections are short lived
and mutations use transactions plus revision checks to prevent double handling.
"""
from __future__ import annotations

import hashlib
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager, ExitStack


class AudioError(RuntimeError):
    pass


def connection_help(exc):
    """Return allowlisted diagnostics only; driver messages may contain secrets."""
    state = str(getattr(exc, "sqlstate", "") or "")
    message = str(exc).lower()
    if isinstance(exc, ImportError):
        code, hint = "A01", "연결 라이브러리가 없어요. 새 requirements.txt 업로드 후 앱을 재시작해 주세요."
    elif state.startswith("28") or "password authentication failed" in message:
        code, hint = "A02", "DB 인증에 실패했어요. 프로젝트 DB 비밀번호와 연결 주소의 사용자명을 확인해 주세요."
    elif "tenant or user not found" in message:
        code, hint = "A03", "DB 사용자 또는 프로젝트를 찾지 못했어요. Session pooler 주소를 다시 복사해 주세요."
    elif any(s in message for s in ("could not translate host", "name or service not known", "getaddrinfo", "nodename nor servname")):
        code, hint = "A04", "DB 서버 주소를 찾지 못했어요. 연결 주소의 호스트 부분을 확인해 주세요."
    elif any(s in message for s in ("timeout", "timed out", "network is unreachable", "connection refused")):
        code, hint = "A05", "DB 서버에 접속하지 못했어요. Supabase 프로젝트 실행 상태와 Session pooler 사용 여부를 확인해 주세요."
    elif state == "42501":
        code, hint = "A06", "DB 테이블 생성 또는 접근 권한이 부족해요. 서버용 DB 계정을 확인해 주세요."
    elif "ssl" in message or "certificate" in message:
        code, hint = "A07", "DB 보안 연결에 실패했어요. 연결 설정 확인이 필요해요."
    elif state in ("53300", "53400") or "max client connections" in message:
        code, hint = "A08", "DB 연결 한도에 도달했어요. 잠시 후 다시 시도해 주세요."
    elif any(s in message for s in ("invalid conninfo", "invalid uri", "invalid percent", "missing ", "invalid integer value")):
        code, hint = "A09", "DB 연결 주소 형식을 확인해 주세요. 비밀번호 부분의 특수문자 변환도 확인이 필요해요."
    else:
        code, hint = "A99", "DB 연결 또는 처리 중 오류가 발생했어요. 이 오류 코드를 관리자에게 알려주세요."
    return f"[{code}] {hint} 전송 중이었다면 재전송 전에 내 요청을 확인해 주세요."


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


SCHEMA = [
    "CREATE TABLE IF NOT EXISTS sound_rooms (id TEXT PRIMARY KEY, label TEXT NOT NULL, code_hash TEXT UNIQUE NOT NULL, expires_at DOUBLE PRECISION NOT NULL, closed INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS sound_people (id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES sound_rooms(id), token_hash TEXT UNIQUE NOT NULL, alias TEXT NOT NULL, alias_key TEXT NOT NULL, UNIQUE(room_id,alias_key))",
    "CREATE TABLE IF NOT EXISTS sound_requests (id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES sound_rooms(id), person_id TEXT NOT NULL REFERENCES sound_people(id), alias TEXT NOT NULL, body TEXT NOT NULL, status TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL, updated_at DOUBLE PRECISION NOT NULL, revision INTEGER NOT NULL DEFAULT 0, engineer TEXT NOT NULL DEFAULT '', engineer_id TEXT NOT NULL DEFAULT '')",
    "CREATE TABLE IF NOT EXISTS sound_replies (id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES sound_requests(id), author TEXT NOT NULL, body TEXT NOT NULL, created_at DOUBLE PRECISION NOT NULL)",
    "CREATE INDEX IF NOT EXISTS sound_room_status ON sound_requests(room_id,status,created_at)",
    "CREATE INDEX IF NOT EXISTS sound_person_requests ON sound_requests(person_id,created_at)",
]


class AudioStore:
    def __init__(self, database_url: str = "", *, test_sqlite_path: str | None = None):
        self.url = database_url
        self.test_path = test_sqlite_path
        self._pool = None
        if not self.url and not self.test_path:
            raise AudioError("음향 요청 저장소를 먼저 연결해 주세요.")

    @contextmanager
    def transaction(self):
        conn = None
        connections = ExitStack()
        try:
            if self.test_path:
                conn = sqlite3.connect(self.test_path, timeout=10)
                connections.callback(conn.close)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA foreign_keys=ON")
                conn.execute("BEGIN IMMEDIATE")
            else:
                import psycopg
                from psycopg.rows import dict_row
                if self._pool is not None:
                    conn = connections.enter_context(self._pool.connection(timeout=8))
                else:
                    conn = psycopg.connect(self.url, connect_timeout=8, row_factory=dict_row, sslmode="require", prepare_threshold=None)
                    connections.callback(conn.close)
                conn.execute("SET LOCAL statement_timeout = '8000ms'")
            yield conn
            conn.commit()
        except (AudioError, ValueError):
            if conn:
                conn.rollback()
            raise
        except Exception as exc:
            if conn:
                conn.rollback()
            # Never expose database URLs or driver connection errors in public UI.
            raise AudioError(connection_help(exc)) from None
        finally:
            connections.close()

    def sql(self, conn, statement, args=()):
        return conn.execute(statement if self.test_path else statement.replace("?", "%s"), args)

    def setup(self):
        with self.transaction() as conn:
            for statement in SCHEMA:
                self.sql(conn, statement)
            # Additive migration: keep existing people, requests and replies.
            for table in ("sound_people", "sound_requests"):
                if self.test_path:
                    columns = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
                    if "location" not in columns:
                        conn.execute(f"ALTER TABLE {table} ADD COLUMN location TEXT NOT NULL DEFAULT '예배팀'")
                else:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS location TEXT NOT NULL DEFAULT '예배팀'")
            if not self.test_path:
                # Supabase's public API must not expose rows to anon/authenticated
                # clients. Only the server database role reads these tables.
                for table in ("sound_rooms","sound_people","sound_requests","sound_replies"):
                    self.sql(conn, f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        if not self.test_path and self._pool is None:
            try:
                from psycopg_pool import ConnectionPool
                from psycopg.rows import dict_row
                # One bounded pool for the cached store, not per participant.
                # Setup above validates credentials synchronously first.
                self._pool = ConnectionPool(
                    self.url, min_size=1, max_size=4, timeout=8,
                    max_idle=60, max_lifetime=600, open=True,
                    kwargs=dict(connect_timeout=8, row_factory=dict_row,
                                sslmode="require", prepare_threshold=None),
                )
            except Exception as exc:
                raise AudioError(connection_help(exc)) from None

    @staticmethod
    def text(value, label, limit):
        value = " ".join(str(value or "").split())
        if not value or len(value) > limit:
            raise ValueError(f"{label}은 1~{limit}자로 입력해 주세요.")
        return value

    def room(self, conn, room_id, *, active=True):
        suffix = "" if self.test_path or not active else " FOR UPDATE"
        row = self.sql(conn, "SELECT * FROM sound_rooms WHERE id=?" + suffix, (room_id,)).fetchone()
        if not row:
            raise AudioError("예배방을 찾을 수 없어요.")
        if active and (row["closed"] or row["expires_at"] <= time.time()):
            raise AudioError("종료된 예배방이에요. 새 예배방으로 입장해 주세요.")
        return dict(row)

    def person(self, conn, token):
        row = self.sql(conn, "SELECT * FROM sound_people WHERE token_hash=?", (digest(token),)).fetchone()
        if not row:
            raise AudioError("개인 복귀코드를 확인해 주세요.")
        return dict(row)

    def create_room(self, label, code, room_id):
        label = self.text(label, "예배방 이름", 80)
        if len(code) < 10:
            raise ValueError("예배방 코드는 10자 이상이어야 합니다.")
        with self.transaction() as conn:
            self.sql(conn, "INSERT INTO sound_rooms(id,label,code_hash,expires_at) VALUES(?,?,?,?) ON CONFLICT(id) DO NOTHING", (room_id,label,digest(code),time.time()+12*3600))
        return room_id

    def active_rooms(self):
        with self.transaction() as conn:
            return [dict(r) for r in self.sql(conn, "SELECT id,label,expires_at FROM sound_rooms WHERE closed=0 AND expires_at>? ORDER BY expires_at DESC", (time.time(),)).fetchall()]

    def join_room(self, room_id, alias, token, location="예배팀"):
        """Public room selection; private inbox capability is still per person."""
        if not room_id:
            raise AudioError("참여할 예배방을 선택해 주세요.")
        return self.join("", alias, token, location, room_id=room_id)

    def join(self, code, alias, token, location="예배팀", *, room_id=None):
        alias = self.text(alias, "별명", 30)
        location = self.text(location, "요청 위치", 30)
        with self.transaction() as conn:
            if room_id is None:
                found = self.sql(conn, "SELECT id FROM sound_rooms WHERE code_hash=?", (digest(code.strip()),)).fetchone()
                if not found:
                    raise AudioError("예배방 코드를 확인해 주세요.")
                room_id = found["id"]
            # Recheck under lock: a displayed room may have closed meanwhile.
            room = self.room(conn, room_id)
            existing = self.sql(conn, "SELECT * FROM sound_people WHERE token_hash=?", (digest(token),)).fetchone()
            if existing:
                if existing["room_id"] != room["id"]:
                    raise AudioError("다른 방의 복귀코드입니다.")
                return dict(existing)
            duplicate = self.sql(conn, "SELECT id FROM sound_people WHERE room_id=? AND alias_key=?", (room["id"],alias.casefold())).fetchone()
            if duplicate:
                raise ValueError("이 예배방에서 사용 중인 별명이에요. 다른 이름을 정해 주세요.")
            person_id = uuid.uuid4().hex
            self.sql(conn, "INSERT INTO sound_people(id,room_id,token_hash,alias,alias_key,location) VALUES(?,?,?,?,?,?)", (person_id,room["id"],digest(token),alias,alias.casefold(),location))
            return {"id":person_id,"room_id":room["id"],"alias":alias,"location":location}

    def rename(self, token, alias, location=None):
        alias = self.text(alias,"별명",30)
        if location is not None:
            location = self.text(location,"요청 위치",30)
        with self.transaction() as conn:
            person = self.person(conn,token)
            self.room(conn,person["room_id"])
            found = self.sql(conn,"SELECT id FROM sound_people WHERE room_id=? AND alias_key=? AND id<>?",(person["room_id"],alias.casefold(),person["id"])).fetchone()
            if found:
                raise ValueError("이미 사용 중인 별명이에요.")
            self.sql(conn,"UPDATE sound_people SET alias=?,alias_key=?,location=? WHERE id=?",(alias,alias.casefold(),location if location is not None else person["location"],person["id"]))

    def send(self, token, body, request_id):
        body = self.text(body,"요청",300)
        with self.transaction() as conn:
            person = self.person(conn,token)
            self.room(conn,person["room_id"])
            existing = self.sql(conn,"SELECT id,person_id FROM sound_requests WHERE id=?",(request_id,)).fetchone()
            if existing:
                if existing["person_id"] != person["id"]:
                    raise AudioError("이 요청에 접근할 수 없어요.")
                return existing["id"]
            duplicate = self.sql(conn,"SELECT id FROM sound_requests WHERE person_id=? AND body=? AND status IN ('PENDING','ACK')",(person["id"],body)).fetchone()
            if duplicate:
                return duplicate["id"]
            pending = self.sql(conn,"SELECT COUNT(*) AS n FROM sound_requests WHERE person_id=? AND status IN ('PENDING','ACK')",(person["id"],)).fetchone()["n"]
            if pending >= 5:
                raise ValueError("요청 5건이 대기 중이에요. 기존 요청을 확인하거나 취소해 주세요.")
            last = self.sql(conn,"SELECT MAX(created_at) AS t FROM sound_requests WHERE person_id=?",(person["id"],)).fetchone()["t"]
            now = time.time()
            if last and now-last < 2:
                raise ValueError("요청을 전달 중이에요. 잠시 뒤 다시 눌러 주세요.")
            self.sql(conn,"INSERT INTO sound_requests(id,room_id,person_id,alias,body,status,created_at,updated_at,location) VALUES(?,?,?,?,?,'PENDING',?,?,?)",(request_id,person["room_id"],person["id"],person["alias"],body,now,now,person["location"]))
            return request_id

    def _with_replies(self, conn, rows):
        result = [dict(r) for r in rows]
        if not result:
            return result
        placeholders = ",".join("?" for _ in result)
        replies = self.sql(conn, f"SELECT request_id,author,body,created_at FROM sound_replies WHERE request_id IN ({placeholders}) ORDER BY created_at", tuple(r["id"] for r in result)).fetchall()
        grouped = {}
        for reply in replies:
            grouped.setdefault(reply["request_id"], []).append(dict(reply))
        for row in result:
            row["replies"] = grouped.get(row["id"], [])
        return result

    def mine(self, token):
        with self.transaction() as conn:
            person = self.person(conn,token)
            room = self.room(conn,person["room_id"],active=False)
            rows = self.sql(conn,"SELECT * FROM sound_requests WHERE person_id=? ORDER BY created_at DESC LIMIT 50",(person["id"],)).fetchall()
            return person,room,self._with_replies(conn,rows)

    def desk(self, room_id):
        # Called only by the server-side engineer UI after access validation.
        with self.transaction() as conn:
            room = self.room(conn,room_id,active=False)
            rows = self.sql(conn,"SELECT * FROM sound_requests WHERE room_id=? ORDER BY CASE WHEN status IN ('PENDING','ACK') THEN 0 WHEN status='DONE' THEN 1 ELSE 2 END, created_at DESC LIMIT 150",(room_id,)).fetchall()
            return room,self._with_replies(conn,rows)

    def participant_update(self, token, request_id, revision, action):
        targets = {"cancel":("CANCELLED","요청을 취소했어요."),"confirm":("CLOSED","좋아요. 확인했어요."),"more":("PENDING","추가 조정이 필요해요.")}
        if action not in targets:
            raise ValueError("올바르지 않은 요청입니다.")
        with self.transaction() as conn:
            person = self.person(conn,token)
            self.room(conn,person["room_id"])
            row = self.sql(conn,"SELECT * FROM sound_requests WHERE id=? AND person_id=?",(request_id,person["id"])).fetchone()
            if not row:
                raise AudioError("이 요청에 접근할 수 없어요.")
            allowed = ("PENDING","ACK","DONE") if action=="cancel" else ("DONE",)
            if row["status"] not in allowed or row["revision"] != revision:
                raise AudioError("요청 상태가 바뀌었어요. 최신 화면에서 다시 확인해 주세요.")
            status,body = targets[action]
            self.sql(conn,"UPDATE sound_requests SET status=?,updated_at=?,revision=revision+1,engineer='',engineer_id='' WHERE id=? AND revision=?",(status,time.time(),request_id,revision))
            self.sql(conn,"INSERT INTO sound_replies(id,request_id,author,body,created_at) VALUES(?,?,?,?,?)",(uuid.uuid4().hex,request_id,person["alias"],body,time.time()))

    def engineer_update(self, room_id, request_id, revision, engineer_id, engineer, action, message=""):
        engineer = self.text(engineer,"엔지니어 이름",30)
        if not engineer_id or action not in {"ack","done","reply","release"}:
            raise ValueError("올바르지 않은 처리 요청입니다.")
        if action=="reply":
            message = self.text(message,"답변",300)
        with self.transaction() as conn:
            self.room(conn,room_id)
            row = self.sql(conn,"SELECT * FROM sound_requests WHERE id=? AND room_id=?",(request_id,room_id)).fetchone()
            if not row or row["revision"] != revision or row["status"] not in ("PENDING","ACK","DONE"):
                raise AudioError("요청 상태가 바뀌었어요. 최신 화면에서 다시 확인해 주세요.")
            if row["engineer_id"] and row["engineer_id"] != engineer_id:
                raise AudioError("다른 엔지니어가 처리 중이에요. 담당 해제 후 인계받을 수 있어요.")
            if action in {"ack","done"} and row["status"] == "DONE":
                raise AudioError("이미 조정한 요청입니다.")
            status = {"ack":"ACK","done":"DONE","reply":row["status"],"release":row["status"]}[action]
            if action=="release" and status=="ACK":
                status="PENDING"
            author_id,owner = ("","") if action=="release" else (engineer_id,engineer)
            body = {"ack":"확인했어요. 조정할게요.","done":"조정했어요. 소리를 확인해 주세요.","reply":message,"release":"담당을 해제했어요. 다른 엔지니어가 이어서 확인합니다."}[action]
            self.sql(conn,"UPDATE sound_requests SET status=?,updated_at=?,revision=revision+1,engineer=?,engineer_id=? WHERE id=? AND revision=?",(status,time.time(),owner,author_id,request_id,revision))
            self.sql(conn,"INSERT INTO sound_replies(id,request_id,author,body,created_at) VALUES(?,?,?,?,?)",(uuid.uuid4().hex,request_id,engineer,body,time.time()))

    def close_room(self, room_id):
        with self.transaction() as conn:
            self.room(conn,room_id,active=False)
            self.sql(conn,"UPDATE sound_rooms SET closed=1 WHERE id=?",(room_id,))
            self.sql(conn,"UPDATE sound_requests SET status='EXPIRED',revision=revision+1,updated_at=? WHERE room_id=? AND status IN ('PENDING','ACK','DONE')",(time.time(),room_id))

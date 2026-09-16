"""Separate cue snapshots and shared state. Server-authenticated use only."""
import copy
import json
import time
import uuid

from audio_requests import AudioError

ROLES = ("전체", "음향", "자막", "무대·FD", "찬양팀")


def authorize(actor, expires):
    if not actor or expires <= time.time():
        raise AudioError("팀원 또는 음향석 로그인이 필요해요. 다시 로그인해 주세요.")


class CueStore:
    def __init__(self, audio_store):
        self.db = audio_store

    def setup(self):
        with self.db.transaction() as conn:
            self.db.sql(conn, "CREATE TABLE IF NOT EXISTS cue_sessions (id TEXT PRIMARY KEY, title TEXT NOT NULL, payload TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, controller TEXT NOT NULL DEFAULT '', lease DOUBLE PRECISION NOT NULL DEFAULT 0, room_id TEXT UNIQUE REFERENCES sound_rooms(id) ON DELETE SET NULL)")
            if not self.db.test_path:
                self.db.sql(conn, "ALTER TABLE cue_sessions ENABLE ROW LEVEL SECURITY")

    def list(self, actor, expires):
        authorize(actor, expires)
        with self.db.transaction() as conn:
            return [dict(r) for r in self.db.sql(conn, "SELECT id,title FROM cue_sessions ORDER BY title DESC LIMIT 100").fetchall()]

    def read(self, sid, actor, expires):
        authorize(actor, expires)
        with self.db.transaction() as conn:
            row = self.db.sql(conn, "SELECT * FROM cue_sessions WHERE id=?", (sid,)).fetchone()
            if not row:
                raise AudioError("저장한 예배를 찾지 못했어요.")
            result = dict(row)
            result["state"] = json.loads(result.pop("payload"))
            if row["controller"] == actor:
                self.db.sql(conn, "UPDATE cue_sessions SET lease=? WHERE id=? AND controller=?",
                            (min(expires, time.time()+90), sid, actor))
            return result

    def create(self, plan, actor, expires):
        authorize(actor, expires)
        if not plan.get("items"):
            raise ValueError("빈 예배는 저장할 수 없어요.")
        state = dict(plan=copy.deepcopy(plan), current=plan["items"][0]["id"], frozen=False,
                     live=False, checks={}, notes={}, messages=[], scripture="")
        with self.db.transaction() as conn:
            self.db.sql(conn, "INSERT INTO cue_sessions(id,title,payload,controller,lease) VALUES(?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                        (plan["id"], plan["title"], json.dumps(state, ensure_ascii=False), actor, min(expires, time.time()+90)))
        return plan["id"]

    def act(self, sid, revision, action, value, actor, expires):
        authorize(actor, expires)
        with self.db.transaction() as conn:
            suffix = "" if self.db.test_path else " FOR UPDATE"
            row = self.db.sql(conn, "SELECT * FROM cue_sessions WHERE id=?"+suffix, (sid,)).fetchone()
            if not row or row["revision"] != revision:
                raise AudioError("다른 변경이 있어요. 최신 상태를 확인하고 다시 눌러 주세요.")
            state = json.loads(row["payload"])
            controller = row["controller"]
            room_id = row["room_id"]
            if action == "claim":
                if controller and controller != actor and row["lease"] > time.time():
                    raise AudioError("다른 진행 담당자가 제어 중이에요. 담당 해제 후 인계받으세요.")
                controller = actor
            elif action not in {"check", "ack"} and (controller != actor or row["lease"] <= time.time()):
                raise AudioError("진행 담당 권한이 필요해요. 먼저 진행 담당을 맡아 주세요.")
            ids = {i["id"] for i in state["plan"]["items"]}
            if action == "release":
                controller = ""
            elif action == "current":
                if value not in ids:
                    raise ValueError("현재 목록의 순서를 선택해 주세요.")
                state["current"] = value
            elif action == "freeze":
                state["frozen"] = True
            elif action == "live":
                if value and not state["frozen"]:
                    raise ValueError("예배용 확정 후 진행을 시작하세요.")
                state["live"] = bool(value)
            elif action == "import":
                if value["id"] != sid:
                    raise ValueError("날짜·탭·영역이 다른 예배는 별도로 불러오세요.")
                new_ids = {i["id"] for i in value["items"]}
                if state["current"] not in new_ids:
                    raise ValueError("현재 순서가 새 원본에서 사라졌어요. 두 목록에 공통으로 있는 순서로 이동한 뒤 반영하세요.")
                state["plan"] = copy.deepcopy(value)
                # Imported changes need preparation checks again; never inherit stale checks.
                state["checks"] = {}
                state["notes"] = {k:v for k,v in state["notes"].items() if k in new_ids}
            elif action == "check":
                label, checked, name = value
                if label not in state["plan"]["checks"]:
                    raise ValueError("현재 준비 목록에 없는 항목입니다.")
                state["checks"][label] = dict(done=bool(checked), by=str(name)[:40])
            elif action == "note":
                iid, note = value
                if iid not in ids or len(note) > 2000:
                    raise ValueError("메모 내용을 확인하세요.")
                state["notes"][iid] = note
            elif action == "scripture":
                if len(value) > 20000:
                    raise ValueError("인용구절 입력이 너무 길어요.")
                state["scripture"] = value
            elif action == "message":
                target, body = value
                if target not in ROLES or not str(body).strip() or len(body) > 300:
                    raise ValueError("받을 담당과 300자 이하 내용을 확인하세요.")
                state["messages"] = (state["messages"] + [dict(id=uuid.uuid4().hex, target=target, body=body,
                                            ack=[], at=time.time())])[-50:]
            elif action == "ack":
                mid, role = value
                if role not in ROLES:
                    raise ValueError("담당 구분을 확인하세요.")
                for message in state["messages"]:
                    if message["id"] == mid and message["target"] in {role, "전체"}:
                        if role not in message["ack"]:
                            message["ack"].append(role)
            elif action == "room":
                if value:
                    self.db.room(conn, value)
                    existing = self.db.sql(conn, "SELECT id FROM cue_sessions WHERE room_id=? AND id<>?", (value, sid)).fetchone()
                    if existing:
                        raise ValueError("이 음향방은 다른 큐시트에 연결돼 있어요. 먼저 기존 연결을 해제하세요.")
                room_id = value or None
            elif action not in {"claim", "release", "freeze", "live", "current", "import", "check", "note", "scripture", "message", "ack", "room"}:
                raise ValueError("지원하지 않는 작업입니다.")
            lease = (min(expires, time.time()+90) if controller == actor else row["lease"]) if controller else 0
            self.db.sql(conn, "UPDATE cue_sessions SET payload=?,revision=revision+1,controller=?,lease=?,room_id=? WHERE id=?",
                        (json.dumps(state, ensure_ascii=False), controller, lease, room_id, sid))


def request_context(db, conn, room_id):
    """Only the public cue title; never internal notes or another participant's data."""
    row = db.sql(conn, "SELECT payload,controller,lease FROM cue_sessions WHERE room_id=?", (room_id,)).fetchone()
    if not row or not row["controller"] or row["lease"] <= time.time():
        return ""
    state = json.loads(row["payload"])
    if not state.get("live"):
        return ""
    item = next((i for i in state["plan"]["items"] if i["id"] == state["current"]), None)
    return (state["plan"]["title"] + " · " + item["title"])[:400] if item else ""

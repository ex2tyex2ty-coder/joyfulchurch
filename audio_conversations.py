"""One private conversation per room participant, with reversible desk archive."""
import hashlib
import json
import time


def conversation(person, requests, messages):
    events=[]
    for request in requests:
        events.append(dict(id="request:"+request["id"],created_at=request["created_at"],
            author=request["alias"],body=request["body"],side="participant",status=request["status"]))
        for index,reply in enumerate(request["replies"]):
            events.append(dict(id=f"legacy:{request['id']}:{index}",created_at=reply["created_at"],
                author=reply["author"],body=reply["body"],side="legacy"))
    events.extend(dict(m) for m in messages)
    events.sort(key=lambda e:(e["created_at"],e["id"]))
    revision=hashlib.sha256(json.dumps([
        person.get("desk_archived",0),
        sorted((r["id"],r["revision"]) for r in requests),
        sorted(m["id"] for m in messages),
    ],sort_keys=True).encode()).hexdigest()
    return dict(person=person,requests=requests,events=events,revision=revision,
                waiting=sum(r["status"] in {"PENDING","ACK"} for r in requests),
                last_activity=max((e["created_at"] for e in events),default=0))


class ConversationStore:
    def rooms_for_desk(self):
        with self.transaction() as conn:
            return [dict(r) for r in self.sql(conn,"SELECT id,label,expires_at,closed FROM sound_rooms ORDER BY CASE WHEN closed=0 AND expires_at>? THEN 0 ELSE 1 END, expires_at DESC",(time.time(),)).fetchall()]

    def _conversation(self,conn,person):
        requests=self._with_replies(conn,self.sql(conn,"SELECT * FROM sound_requests WHERE person_id=? ORDER BY created_at",(person["id"],)).fetchall())
        messages=[dict(r) for r in self.sql(conn,"SELECT * FROM sound_thread_messages WHERE person_id=? ORDER BY created_at",(person["id"],)).fetchall()]
        return conversation(person,requests,messages)

    def my_conversation(self,token):
        with self.transaction() as conn:
            person=self.person(conn,token)
            room=self.room(conn,person["room_id"],active=False)
            return room,self._conversation(conn,person)

    def conversations(self,room_id):
        # Only the authenticated server-side desk invokes this method.
        with self.transaction() as conn:
            room=self.room(conn,room_id,active=False)
            people=[dict(r) for r in self.sql(conn,"SELECT * FROM sound_people WHERE room_id=?",(room_id,)).fetchall()]
            requests=self._with_replies(conn,self.sql(conn,"SELECT * FROM sound_requests WHERE room_id=? ORDER BY created_at",(room_id,)).fetchall())
            messages=[dict(r) for r in self.sql(conn,"SELECT * FROM sound_thread_messages WHERE room_id=? ORDER BY created_at",(room_id,)).fetchall()]
            by_request={};by_message={}
            for r in requests: by_request.setdefault(r["person_id"],[]).append(r)
            for m in messages: by_message.setdefault(m["person_id"],[]).append(m)
            result=[conversation(p,by_request.get(p["id"],[]),by_message.get(p["id"],[])) for p in people]
            return room,sorted((c for c in result if c["events"]),key=lambda c:c["last_activity"],reverse=True)

    def conversation_action(self,room_id,person_id,expected,action,event_id,*,
                            engineer_id="",engineer="",message="",token=None):
        """Room lock + snapshot check prevent hiding requests arriving mid-action.

        Completion/confirmation apply to the currently displayed conversation,
        not to individual cards. Commands are idempotent after network failures.
        """
        from audio_requests import AudioError
        participant=token is not None
        allowed={"confirm","more","cancel"} if participant else {"ack","done","reply","release","archive","done_archive","restore"}
        if action not in allowed or not event_id:
            raise ValueError("올바르지 않은 대화 작업입니다.")
        if not participant:
            engineer=self.text(engineer,"엔지니어 이름",30)
            if not engineer_id: raise AudioError("음향석 접근번호를 다시 확인해 주세요.")
        if action=="reply": message=self.text(message,"답변",300)
        with self.transaction() as conn:
            room=self.room(conn,room_id,active=False)
            if not self.test_path:
                self.sql(conn,"SELECT id FROM sound_rooms WHERE id=? FOR UPDATE",(room_id,))
                room=self.room(conn,room_id,active=False)
            if participant:
                person=self.person(conn,token)
                if person["id"]!=person_id or person["room_id"]!=room_id:
                    raise AudioError("이 대화에 접근할 수 없어요.")
                author,author_id,side=person["alias"],person["id"],"participant"
            else:
                row=self.sql(conn,"SELECT * FROM sound_people WHERE id=? AND room_id=?",(person_id,room_id)).fetchone()
                if not row: raise AudioError("이 예배방의 대화가 아니에요.")
                person=dict(row);author,author_id,side=engineer,engineer_id,"engineer"
            previous=self.sql(conn,"SELECT person_id,author_id,side FROM sound_thread_messages WHERE id=?",(event_id,)).fetchone()
            if previous:
                if (previous["person_id"],previous["author_id"],previous["side"])!=(person_id,author_id,side):
                    raise AudioError("이 작업에 접근할 수 없어요.")
                return
            if action not in {"archive","restore"} and (room["closed"] or room["expires_at"]<=time.time()):
                raise AudioError("종료된 예배방이에요. 기록은 계속 볼 수 있어요.")
            current=self._conversation(conn,person)
            if current["revision"]!=expected:
                raise AudioError("새 요청이나 답변이 들어왔어요. 새로고침 후 대화를 확인하고 다시 눌러 주세요.")
            open_rows=[r for r in current["requests"] if r["status"] in {"PENDING","ACK"}]
            done_rows=[r for r in current["requests"] if r["status"]=="DONE"]
            if not participant and action not in {"restore","release"}:
                if any(r["engineer_id"] and r["engineer_id"]!=engineer_id for r in open_rows):
                    raise AudioError("다른 엔지니어가 처리 중이에요. 담당 해제 후 이어서 처리해 주세요.")
            targets=[];new_status=None
            if action in {"ack","done","done_archive"}:
                targets=open_rows;new_status="ACK" if action=="ack" else "DONE"
                if not targets and action!="done_archive": raise AudioError("처리할 새 요청이 없어요.")
            elif action in {"confirm","more"}:
                targets=done_rows;new_status="CLOSED" if action=="confirm" else "PENDING"
                if not targets: raise AudioError("확인할 완료 요청이 없어요.")
            elif action=="cancel":
                targets=open_rows+done_rows;new_status="CANCELLED"
                if not targets: raise AudioError("취소할 요청이 없어요.")
            elif action=="release":
                targets=[r for r in open_rows if r["engineer_id"]==engineer_id]
                new_status="PENDING"
                if not targets: raise AudioError("내가 맡은 요청이 없어요.")
            elif action=="archive" and open_rows:
                raise AudioError("미처리 요청이 있어요. 처리 후 ‘처리 완료·보관’을 눌러 주세요.")
            for r in targets:
                owner_id,owner=(engineer_id,engineer) if action in {"ack","done","done_archive"} else ("","")
                self.sql(conn,"UPDATE sound_requests SET status=?,engineer_id=?,engineer=?,revision=revision+1,updated_at=? WHERE id=?",(new_status,owner_id,owner,time.time(),r["id"]))
            archived=1 if action in {"archive","done_archive"} else (0 if action in {"restore","more"} else person.get("desk_archived",0))
            self.sql(conn,"UPDATE sound_people SET desk_archived=? WHERE id=?",(archived,person_id))
            body={"ack":"대화의 요청을 확인했어요. 처리할게요.","done":"현재 대화의 요청을 조치했어요. 확인해 주세요.",
                "done_archive":"현재 요청을 조치하고 대화를 보관했어요. 추가 요청은 이 대화에 남겨 주세요.",
                "archive":"대화를 보관했어요. 기록은 그대로 남아 있어요.","restore":"대화를 진행 목록으로 불러왔어요.",
                "release":"담당을 해제했어요. 다른 엔지니어가 이어서 확인합니다.","confirm":"좋아요. 조치 내용을 확인했어요.",
                "more":"추가 조정이 필요해요.","cancel":"현재 대화의 미완료 요청을 취소했어요.","reply":message}[action]
            self.sql(conn,"INSERT INTO sound_thread_messages(id,room_id,person_id,author,author_id,side,body,created_at) VALUES(?,?,?,?,?,?,?,?)",(event_id,room_id,person_id,author,author_id,side,body,time.time()))

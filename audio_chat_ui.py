"""Presentation of one participant's conversation, without per-request actions."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from audio_profiles import request_sender


def chat_thread(room, thread, *, desk, act):
    person=thread["person"];pid=person["id"]
    archived=bool(person.get("desk_archived"))
    closed=bool(room["closed"] or room["expires_at"]<=time.time())
    waiting=thread["waiting"]
    label=f"{request_sender(person)} · {'보관됨' if archived else f'처리 대기 {waiting}건' if waiting else '확인된 대화'}"
    with st.expander(label,expanded=(not archived if desk else True),key=f"sound_thread_{'desk' if desk else 'mine'}_{pid}"):
        st.caption("이 사람의 요청과 답변이 한 대화에 모여요. 제목을 눌러 접거나 펼칠 수 있어요.")
        with st.container(height=380,autoscroll=True,key=f"sound_thread_log_{'desk' if desk else 'mine'}_{pid}"):
            if not thread["events"]: st.caption("아직 요청이 없어요.")
            for event in thread["events"]:
                own=event["side"]=="participant"
                with st.chat_message("user" if own else "assistant",avatar="👤" if own else "💬"):
                    when=datetime.fromtimestamp(event["created_at"],ZoneInfo("Asia/Seoul")).strftime("%m/%d %H:%M:%S")
                    st.caption(f"{event['author']} · {when}")
                    st.text(event["body"])
                    if event.get("status"):
                        st.caption({"PENDING":"전송 완료 · 확인 대기","ACK":"처리 중","DONE":"조치 완료","CLOSED":"확인 완료","CANCELLED":"취소됨","EXPIRED":"예배방 종료"}.get(event["status"],event["status"]))
        if desk:
            if archived:
                st.caption("진행 목록에서만 숨긴 상태예요. 기록은 삭제되지 않았어요.")
                if st.button("대화 불러오기",key=f"thread_restore_{pid}",width="stretch"):
                    act("restore")
            elif not closed:
                c1,c2=st.columns(2)
                if c1.button("확인 · 처리 중",key=f"thread_ack_{pid}",disabled=not waiting,width="stretch"):
                    act("ack")
                if c2.button("현재 요청 조치 완료",key=f"thread_done_{pid}",disabled=not waiting,width="stretch"):
                    act("done")
                with st.form(f"thread_reply_form_{pid}",clear_on_submit=True):
                    message=st.text_input("이 대화에 답변",max_chars=300,key=f"thread_reply_text_{pid}",placeholder="예: 모니터 연결 확인했고, 반주도 올렸어요.")
                    if st.form_submit_button("답변 보내기",width="stretch"):
                        act("reply",message)
                st.caption("모두 대응했으면 보관하세요. 새 요청이 오면 진행 목록에 다시 나타나요.")
                if st.button("처리 완료·보관" if waiting else "대화 보관하기",key=f"thread_archive_{pid}",width="stretch"):
                    act("done_archive" if waiting else "archive")
                if any(r["engineer_id"]==st.session_state.get("sound_engineer_id") and r["status"] in {"PENDING","ACK"} for r in thread["requests"]):
                    if st.button("내 담당 해제",key=f"thread_release_{pid}",type="tertiary"):
                        act("release")
            elif st.button("대화 보관하기",key=f"thread_archive_closed_{pid}",width="stretch"):
                act("archive")
        elif not closed:
            if archived: st.info("음향석에서 이 대화를 보관했어요. 새 요청을 보내면 다시 전달돼요.")
            done=any(r["status"]=="DONE" for r in thread["requests"])
            if done:
                yes,more=st.columns(2)
                if yes.button("좋아요 · 확인했어요",key=f"thread_confirm_{pid}",width="stretch"):
                    act("confirm")
                if more.button("추가 조정 필요",key=f"thread_more_{pid}",width="stretch"):
                    act("more")
            if waiting or done:
                if st.button("현재 요청 모두 취소",key=f"thread_cancel_{pid}",type="tertiary"):
                    act("cancel")

"""Presentation of one participant's conversation, without per-request actions."""
import time
from datetime import datetime
from zoneinfo import ZoneInfo
import streamlit as st
from audio_profiles import request_sender


def chat_thread(room, thread, *, desk, act, actor=None):
    person=thread["person"];pid=person["id"]
    archived=bool(person.get("desk_archived"))
    closed=bool(room["closed"] or room["expires_at"]<=time.time())
    waiting=thread["waiting"]
    actionable=bool(waiting or thread.get('new_message'))
    label=f"{request_sender(person)} · {'보관됨' if archived else '새 메시지' if thread.get('new_message') else f'처리 대기 {waiting}건' if waiting else '확인된 대화'}"
    # Keep the composer out of collapsible containers on BOTH sides. Status/label
    # changes during fragment reruns must not collapse or replace the input surface.
    with st.container(border=True,key=f"sound_thread_{'desk' if desk else 'mine'}_{pid}"):
        st.caption(label)
        st.caption("이 사람의 요청과 답변이 한 대화에 모여요. 아래 입력창에서 계속 대화하세요.")
        with st.container(height=380,autoscroll=True,key=f"sound_thread_log_{'desk' if desk else 'mine'}_{pid}"):
            if not thread["events"]: st.caption("아직 요청이 없어요.")
            for event in thread["events"]:
                own=event["side"]=="participant"
                with st.chat_message("user" if own else "assistant",avatar="👤" if own else "💬"):
                    when=datetime.fromtimestamp(event["created_at"],ZoneInfo("Asia/Seoul")).strftime("%m/%d %H:%M:%S")
                    st.caption(f"{event['author']} · {when}")
                    st.text(event["body"])
                    if event.get("cue_context"):
                        st.caption("요청 당시 순서 · "+event["cue_context"])
                    if event.get("status"):
                        st.caption({"PENDING":"저장 완료 · 음향석 확인 대기","ACK":"음향석 확인 · 처리 중","DONE":"조치 완료","CLOSED":"확인 완료","CANCELLED":"취소됨","EXPIRED":"예배방 종료"}.get(event["status"],event["status"]))
        if desk:
            if archived:
                st.caption("진행 목록에서만 숨긴 상태예요. 기록은 삭제되지 않았어요.")
                if st.button("대화 불러오기",key=f"thread_restore_{pid}",width="stretch"):
                    act("restore")
            elif not closed:
                c1,c2=st.columns(2)
                if c1.button("확인 · 처리 중",key=f"thread_ack_{pid}",disabled=not actionable,width="stretch"):
                    act("ack")
                if c2.button("현재 요청 조치 완료",key=f"thread_done_{pid}",disabled=not actionable,width="stretch"):
                    act("done")
                if st.button('조정했어요 · 빠른 답변',key=f'thread_quick_reply_{pid}',width='stretch'):
                    act('reply','조정했어요. 소리가 괜찮은지 확인해 주세요.')
                with st.expander('대화 정리·보관'):
                    st.caption("새 요청이나 메시지가 오면 진행 목록에 다시 나타나요.")
                    if st.button("처리 완료·보관" if actionable else "대화 보관하기",key=f"thread_archive_{pid}",width="stretch"):
                        act("done_archive" if actionable else "archive")
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
        # A completed request or desk archive must NEVER remove the conversation composer.
        if closed:
            st.info("예배방이 종료되어 새 메시지를 보낼 수 없어요. 새 예배방으로 입장해 주세요.")
        else:
            st.caption("처리 완료·보관 후에도 여기서 계속 대화할 수 있어요.")
        action = 'reply' if desk else 'message'
        expected_actor = st.session_state.get('sound_engineer_id') if desk else actor
        pending = st.session_state.get('sound_thread_pending_'+pid, {})
        if not closed and pending.get('action')==action and pending.get('error') and pending.get('actor')==expected_actor:
            st.warning("메시지 전송 완료를 확인하지 못했어요. 내용은 보관했습니다.")
            st.text(pending['message'])
            if st.button('이 메시지 다시 보내기',key=f'thread_retry_{action}_{pid}',width='stretch'):
                act(action,pending['message'])
        with st.form(f'thread_compose_{action}_{pid}',clear_on_submit=True):
            message=st.text_input('이 대화에 답변' if desk else '음향석에 메시지 보내기',
                                 max_chars=300,key=f'thread_compose_text_{action}_{pid}',disabled=closed,
                                 placeholder='예: 아직 소리가 작아요. 조금만 더 올려주세요.' if not desk else '예: 조정했어요. 다시 확인해 주세요.')
            if st.form_submit_button('답변 보내기' if desk else '메시지 보내기',disabled=closed,width='stretch'):
                act(action,message)

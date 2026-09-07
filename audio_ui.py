from __future__ import annotations

import hmac
import secrets
import time
import uuid
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from streamlit.components.v1 import declare_component

from audio_requests import AudioStore, AudioError
import audio_realtime


_identity_path = Path(__file__).parent / "sound_identity"
_identity_component = declare_component("sound_identity", path=str(_identity_path)) if _identity_path.exists() else None
_realtime_path = Path(__file__).parent / "sound_realtime"
_realtime_component = declare_component("sound_realtime", path=str(_realtime_path)) if _realtime_path.exists() else None


LABELS = {"PENDING":"엔지니어 확인 대기", "ACK":"엔지니어 확인 · 조정 중", "DONE":"조정 완료 · 소리를 확인해 주세요", "CLOSED":"확인 완료", "CANCELLED":"취소", "EXPIRED":"예배 종료"}


def secret(name):
    try:
        return str(st.secrets[name]).strip()
    except (KeyError, FileNotFoundError):
        return ""


@st.cache_resource(show_spinner=False)
def store_for(url):
    store = AudioStore(url)
    store.setup()
    return store


def engineer_access():
    return float(st.session_state.get("sound_engineer_until",0)) > time.time()


def timestamp(value):
    return datetime.fromtimestamp(value,ZoneInfo("Asia/Seoul")).strftime("%H:%M:%S")


def flash_error(exc):
    st.error(str(exc))


def participant_action(store, token, request, action):
    try:
        store.participant_update(token,request["id"],request["revision"],action)
        st.rerun(scope="fragment")
    except (AudioError, ValueError) as exc:
        flash_error(exc)


@st.fragment
def participant_controls(store, token):
    try:
        person,room,requests = store.mine(token)
    except AudioError as exc:
        st.error("연결 확인 중 · 아래 상태는 최신 상태가 아닐 수 있어요.")
        flash_error(exc)
        return
    closed = bool(room["closed"] or room["expires_at"] <= time.time())
    st.markdown(f"### {person['alias']}")
    st.caption(room["label"])
    if not closed:
        choices = ["내 목소리 올려주세요","내 목소리 내려주세요","반주 올려주세요","반주 내려주세요","모니터가 안 들려요","전원 켜주세요","전원 꺼주세요","담당자 도움이 필요해요"]
        st.caption("전원 요청은 별명이나 메시지에 장비 이름을 적어 주세요. 버튼은 음향석에 요청을 전달해요.")
        columns = st.columns(2)
        for index,body in enumerate(choices):
            if columns[index%2].button(body,key=f"sound_quick_{index}",width="stretch"):
                send_request(store,token,body)
        with st.form("sound_message",clear_on_submit=True):
            body = st.text_input("음향석에 메시지",max_chars=300,placeholder="예: 건반 앰프 전원을 켜주세요")
            if st.form_submit_button("요청 보내기",type="primary",width="stretch"):
                send_request(store,token,body)


def participant_live(store, token):
    st.button("내 요청 새로고침", key="sound_mine_refresh", type="tertiary")
    try:
        person,room,requests = store.mine(token)
    except AudioError as exc:
        st.error("연결 확인 중 · 아래 상태는 최신 상태가 아닐 수 있어요.")
        flash_error(exc)
        return
    closed = bool(room["closed"] or room["expires_at"] <= time.time())
    st.caption(f"{'종료된 예배방' if closed else '연결됨'} · 마지막 확인 {timestamp(time.time())}")
    st.markdown("#### 내 요청과 답변")
    st.caption("다른 참여자는 이 내용을 볼 수 없어요. 최근 50건을 표시합니다.")
    if not requests:
        st.info("버튼을 누르면 음향석으로 요청이 전달돼요.")
    for request in requests:
        finished = request["status"] in {"CLOSED","CANCELLED","EXPIRED"}
        with st.expander(f"{LABELS[request['status']]} · {request['body']}",expanded=not finished):
            st.caption(f"{request['alias']} · {timestamp(request['created_at'])}")
            for reply in request["replies"]:
                st.text(f"{reply['author']} · {timestamp(reply['created_at'])}\n{reply['body']}")
            if not finished and not closed:
                if request["status"]=="DONE":
                    yes,more=st.columns(2)
                    if yes.button("좋아요",key=f"sound_yes_{request['id']}",type="primary"):
                        participant_action(store,token,request,"confirm")
                    if more.button("추가 조정 필요",key=f"sound_more_{request['id']}"):
                        participant_action(store,token,request,"more")
                if st.button("요청 취소",key=f"sound_cancel_{request['id']}",type="tertiary"):
                    participant_action(store,token,request,"cancel")


def send_request(store,token,body):
    # Keep the same id after uncertain network failures; never duplicate on retry.
    pending = st.session_state.get("sound_pending_send")
    if not pending or pending["body"] != body:
        pending = {"id":uuid.uuid4().hex,"body":body}
        st.session_state["sound_pending_send"] = pending
    try:
        store.send(token,body,pending["id"])
        st.session_state.pop("sound_pending_send",None)
        st.success("음향석에 전달했어요.")
    except (AudioError,ValueError) as exc:
        flash_error(exc)


def desk_action(store,room_id,request,action,message=""):
    if not engineer_access():
        st.error("음향석 접근번호를 다시 확인해 주세요.")
        return
    try:
        store.engineer_update(room_id,request["id"],request["revision"],st.session_state["sound_engineer_id"],st.session_state["sound_engineer_name"],action,message)
        st.rerun(scope="fragment")
    except (AudioError,ValueError) as exc:
        flash_error(exc)


def desk_live(store,room_id):
    if not engineer_access():
        st.warning("음향석 접속 시간이 끝났어요. 접근번호를 다시 입력해 주세요.")
        return
    st.button("요청 새로고침", key="sound_desk_refresh", type="tertiary")
    try:
        room,requests=store.desk(room_id)
    except AudioError as exc:
        st.error("연결 확인 중 · 요청 수신이 지연될 수 있어요.")
        flash_error(exc)
        return
    closed=bool(room["closed"] or room["expires_at"]<=time.time())
    st.caption(f"{'예배방 종료' if closed else '연결됨'} · 마지막 확인 {timestamp(time.time())} · 최근 150건")
    waiting=sum(r["status"] in {"PENDING","ACK"} for r in requests)
    st.markdown(f"### 처리할 요청 {waiting}건")
    show_finished=st.toggle("완료·취소 기록 보기",key="sound_finished")
    for request in requests:
        if not show_finished and request["status"] in {"CLOSED","CANCELLED","EXPIRED"}:
            continue
        with st.container(border=True):
            st.markdown(f"**{request['alias']}**")
            st.text(request["body"])
            age=max(0,int(time.time()-request["created_at"]))
            st.caption(f"{LABELS[request['status']]} · {timestamp(request['created_at'])} 접수" + (f" · 담당 {request['engineer']}" if request["engineer"] else ""))
            if age>120 and request["status"] in {"PENDING","ACK"}:
                st.warning("시간이 지난 요청입니다. 현재도 필요한 조정인지 확인해 주세요.")
            for reply in request["replies"][-4:]:
                st.text(f"{reply['author']}: {reply['body']}")
            own=not request["engineer_id"] or request["engineer_id"]==st.session_state["sound_engineer_id"]
            if not closed and request["status"] in {"PENDING","ACK","DONE"}:
                c1,c2=st.columns(2)
                if c1.button("확인 · 제가 처리할게요",key=f"sound_ack_{request['id']}",disabled=not own or request["status"]=="DONE",width="stretch"):
                    desk_action(store,room_id,request,"ack")
                if c2.button("조정했어요",key=f"sound_done_{request['id']}",disabled=not own or request["status"]=="DONE",type="primary",width="stretch"):
                    desk_action(store,room_id,request,"done")
                with st.form(f"sound_reply_{request['id']}",clear_on_submit=True):
                    reply=st.text_input("개인 답변",max_chars=300,key=f"sound_reply_text_{request['id']}")
                    if st.form_submit_button("답변 보내기",disabled=not own):
                        desk_action(store,room_id,request,"reply",reply)
                if own and request["engineer_id"] and st.button("담당 해제 · 인계",key=f"sound_release_{request['id']}",type="tertiary"):
                    desk_action(store,room_id,request,"release")


@st.cache_resource(show_spinner=False)
def prepare_realtime(database_url, _store):
    audio_realtime.install(_store)
    return True


@st.fragment
def live_panel(renderer, store, identity):
    """Rerun on component events or clicks only; never on a polling timer."""
    is_desk = renderer is desk_live
    if is_desk and not engineer_access():
        st.warning("음향석 접근번호를 다시 입력해 주세요.")
        return
    url, key = secret("AUDIO_SUPABASE_URL"), secret("AUDIO_SUPABASE_PUBLISHABLE_KEY")
    scope = audio_realtime.digest(("desk:" if is_desk else "person:") + identity)
    if url and key and _realtime_component:
        try:
            url = audio_realtime.validate_settings(url,key)
            prepare_realtime(secret("AUDIO_DATABASE_URL"),store)
            if st.button("실시간 수신 다시 연결",type="tertiary",key="sound_reconnect"):
                st.session_state["sound_rt_restart"] = uuid.uuid4().hex
                st.session_state.pop("sound_rt_auth",None)
            cached = st.session_state.get("sound_rt_auth",{})
            valid = cached.get("scope")==scope and cached.get("expires",0)>time.time()
            event = _realtime_component(url=url,api_key=key,scope=scope,
                restart=st.session_state.get("sound_rt_restart",""),
                accepted_token=cached.get("token","") if valid else "",
                topic=cached.get("topic","") if valid else "",
                expires=cached.get("expires",0) if valid else 0,
                key="sound_realtime_events",default=None)
            if isinstance(event,dict) and event.get("scope")==scope:
                token=event.get("token","")
                if event.get("status")=="auth" and (not valid or token!=cached.get("token")):
                    uid,expires = audio_realtime.verify_browser(url,key,token)
                    topic,expires = audio_realtime.authorize(store,uid,expires,
                        participant_token=None if is_desk else identity,
                        room_id=identity if is_desk else None,
                        engineer_until=st.session_state.get("sound_engineer_until",0) if is_desk else 0)
                    st.session_state["sound_rt_auth"]={"scope":scope,"token":token,"topic":topic,"expires":expires}
                    # Initial handshake / credential renewal only. Ordinary push
                    # events rerun this fragment without touching the composer.
                    st.rerun()
                if event.get("status") in {"error","offline"}:
                    st.warning("실시간 연결이 끊겼어요. 다시 연결하거나 아래 새로고침으로 확인하세요.")
                elif event.get("status")=="expired":
                    st.info("예배방 또는 수신 접속 시간이 끝났어요. 새 예배방으로 입장해 주세요.")
        except AudioError as exc:
            flash_error(exc)
            st.caption("실시간 알림을 연결하지 못했어요. 아래 새로고침으로 확인할 수 있어요.")
    else:
        st.info("실시간 알림 설정이 필요해요. 지금은 새로고침을 눌러 요청·답변을 확인하세요.")
    with st.container(key="sound_live_region"):
        renderer(store,identity)


def audio_page():
    # Limit Streamlit's stale-element fade override to this live inbox only.
    # Connection failures remain explicit, with the last successful check time.
    st.html('''<style>
    .st-key-sound_live_region [data-stale="true"] {
        opacity: 1 !important; transition: none !important;
    }
    </style>''')
    st.title("음향 요청")
    st.caption("별명으로 요청하고, 음향석의 답변을 확인해요.")
    url=secret("AUDIO_DATABASE_URL")
    if not url:
        st.info("음향 요청 기능을 준비 중이에요. 관리자가 전용 저장소를 연결하면 사용할 수 있어요.")
        return
    try:
        store=store_for(url)
    except AudioError as exc:
        flash_error(exc)
        return
    mode=st.radio("사용 화면",["참여자","음향석"],horizontal=True)
    if mode=="참여자":
        token=st.session_state.get("sound_person_token")
        identity = _identity_component(token_to_save=token or "", clear_epoch=st.session_state.get("sound_clear_epoch", ""), key="sound_browser_identity", default=None) if _identity_component else None
        if not token and isinstance(identity, dict) and identity.get("token") and not st.session_state.get("sound_skip_recovery"):
            saved = str(identity["token"])
            if 32 <= len(saved) <= 128:
                try:
                    store.mine(saved)
                    st.session_state["sound_person_token"] = saved
                    st.rerun()
                except AudioError:
                    st.caption("자동 복귀하지 못했어요. 예배방에 입장하거나 개인 복귀코드를 확인해 주세요.")
        if not token:
            with st.form("sound_join"):
                code=st.text_input("예배방 코드",type="password")
                alias=st.text_input("내 별명",placeholder="1번 마이크 / 건반 / 기타",max_chars=30)
                if st.form_submit_button("입장",type="primary",width="stretch"):
                    token=st.session_state.setdefault("sound_join_token",secrets.token_urlsafe(32))
                    try:
                        store.join(code,alias,token)
                        st.session_state["sound_person_token"]=token
                        st.session_state.pop("sound_skip_recovery",None)
                        st.session_state.pop("sound_join_token",None)
                        st.rerun()
                    except (AudioError,ValueError) as exc:
                        flash_error(exc)
            with st.expander("새로고침했나요? 내 요청으로 돌아가기"):
                with st.form("sound_recover"):
                    recovery=st.text_input("개인 복귀코드",type="password")
                    if st.form_submit_button("돌아가기"):
                        try:
                            store.mine(recovery.strip())
                            st.session_state["sound_person_token"]=recovery.strip()
                            st.session_state.pop("sound_skip_recovery",None)
                            st.rerun()
                        except AudioError as exc:
                            flash_error(exc)
            return
        with st.expander("내 별명·복귀코드"):
            st.caption("같은 브라우저에서는 자동 복귀해요. 브라우저가 저장을 차단하거나 다른 기기라면 이 코드로 돌아올 수 있어요. 공유하지 마세요.")
            st.code(token,language=None)
            with st.form("sound_rename"):
                alias=st.text_input("새 별명",max_chars=30)
                if st.form_submit_button("별명 변경"):
                    try:
                        store.rename(token,alias)
                        st.rerun()
                    except (AudioError,ValueError) as exc:
                        flash_error(exc)
            if st.button("나가기",key="sound_leave"):
                st.session_state.pop("sound_person_token",None)
                st.session_state.pop("sound_pending_send",None)
                st.session_state["sound_clear_epoch"] = uuid.uuid4().hex
                st.session_state["sound_skip_recovery"] = True
                st.rerun()
        participant_controls(store,token)
        live_panel(participant_live,store,token)
        return
    if not engineer_access():
        pin=secret("AUDIO_ENGINEER_PIN")
        if not pin:
            st.info("관리자가 음향석 접근번호를 설정하면 수신 화면을 사용할 수 있어요.")
            return
        locked=st.session_state.get("sound_lock_until",0)>time.time()
        with st.form("sound_login"):
            name=st.text_input("엔지니어 이름",max_chars=30)
            entered=st.text_input("음향석 접근번호",type="password")
            if st.form_submit_button("음향석 입장",disabled=locked):
                if hmac.compare_digest(entered,pin) and name.strip():
                    st.session_state.update(sound_engineer_until=time.time()+12*3600,sound_engineer_name=name.strip(),sound_engineer_id=uuid.uuid4().hex,sound_failures=0)
                    st.rerun()
                else:
                    failures=st.session_state.get("sound_failures",0)+1
                    st.session_state["sound_failures"]=failures
                    if failures>=5:
                        st.session_state["sound_lock_until"]=time.time()+600
                        st.session_state["sound_failures"]=0
                    st.error("이름과 접근번호를 확인해 주세요.")
        if locked:
            st.caption("입력 확인을 잠시 멈췄어요. 10분 뒤 다시 시도해 주세요.")
        return
    st.caption(f"음향석 · {st.session_state['sound_engineer_name']} · 접속 후 12시간 유지")
    if st.button("음향석 로그아웃"):
        st.session_state["sound_engineer_until"]=0
        st.rerun()
    try:
        rooms=store.active_rooms()
    except AudioError as exc:
        flash_error(exc)
        return
    with st.expander("예배방 만들기",expanded=not rooms):
        with st.form("sound_room_create"):
            label=st.text_input("예배방 이름",value=datetime.now(ZoneInfo("Asia/Seoul")).strftime("%m/%d 예배"),max_chars=80)
            if st.form_submit_button("만들기"):
                pending=st.session_state.setdefault("sound_new_room",{"id":uuid.uuid4().hex,"code":secrets.token_urlsafe(9)})
                try:
                    store.create_room(label,pending["code"],pending["id"])
                    st.session_state["sound_room_invite"]=dict(pending)
                    st.session_state.pop("sound_new_room",None)
                    st.rerun()
                except (AudioError,ValueError) as exc:
                    flash_error(exc)
    invite=st.session_state.get("sound_room_invite")
    if invite:
        st.caption("참여자에게 이 예배방 코드를 전달해 주세요. 방은 12시간 뒤 자동 종료돼요.")
        st.code(invite["code"],language=None)
    if not rooms:
        return
    room_map={r["id"]:r["label"] for r in rooms}
    room_id=st.selectbox("수신할 예배방",list(room_map),format_func=room_map.get)
    with st.expander("예배방 종료"):
        confirmed=st.checkbox("현재 방의 미처리 요청도 종료할게요")
        if st.button("이 예배방 종료",disabled=not confirmed):
            try:
                store.close_room(room_id)
                st.session_state.pop("sound_room_invite",None)
                st.rerun()
            except AudioError as exc:
                flash_error(exc)
    live_panel(desk_live,store,room_id)

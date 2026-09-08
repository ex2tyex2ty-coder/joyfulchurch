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
from audio_profiles import GROUPS, INSTRUMENTS, CUSTOM_INSTRUMENT, selected_instrument, request_groups, request_sender
from audio_chat_ui import chat_thread
from config import APP_VERSION


_identity_path = Path(__file__).parent / "sound_identity"
_identity_component = declare_component("sound_identity", path=str(_identity_path)) if _identity_path.exists() else None
_realtime_path = Path(__file__).parent / "sound_realtime"
_realtime_component = declare_component("sound_realtime", path=str(_realtime_path)) if _realtime_path.exists() else None


LABELS = {"PENDING":"엔지니어 확인 대기", "ACK":"엔지니어 확인 · 조정 중", "DONE":"조정 완료 · 소리를 확인해 주세요", "CLOSED":"확인 완료", "CANCELLED":"취소", "EXPIRED":"예배 종료"}


def instrument_picker(prefix, current=""):
    options = [*INSTRUMENTS, CUSTOM_INSTRUMENT]
    initial = current if current in INSTRUMENTS else (CUSTOM_INSTRUMENT if current else INSTRUMENTS[0])
    preset = st.selectbox("내 악기", options, index=options.index(initial), key=f"{prefix}_instrument")
    custom = ""
    if preset == CUSTOM_INSTRUMENT:
        custom = st.text_input("악기 이름 직접 입력", value=current if current not in INSTRUMENTS else "",
            max_chars=30, placeholder="예: 바이올린, 전자드럼", key=f"{prefix}_instrument_custom")
    return preset, custom


def secret(name):
    try:
        return str(st.secrets[name]).strip()
    except (KeyError, FileNotFoundError):
        return ""


def ensure_current_store(store):
    required=("rooms_for_desk","my_conversation","conversations","conversation_action")
    if not all(callable(getattr(store,name,None)) for name in required):
        raise AudioError("[U01] 이전 버전의 음향 기능이 남아 있어요. 최신 ZIP 내부 파일을 모두 업로드한 뒤 Streamlit에서 Reboot해 주세요. 기존 데이터와 Secrets는 지우지 마세요.")
    return store


@st.cache_resource(show_spinner=False)
def _store_for_version(url, release):
    # The release participates in the cache key. Previously only the URL did,
    # so an old AudioStore instance could survive a UI/schema update.
    store = AudioStore(url)
    ensure_current_store(store)
    store.setup()
    return store


def store_for(url):
    return ensure_current_store(_store_for_version(url,APP_VERSION))


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
    st.subheader(request_sender(person))
    st.caption(room["label"])
    if person.get("location")=="예배팀":
        st.info("기존 예배팀으로 접속 중이에요. 위 ‘내 정보·복귀코드’에서 싱어 또는 세션을 선택하면 맞는 요청 버튼이 나와요.")
    receipt=st.session_state.get("sound_send_receipt",{})
    if receipt.get("token")==token:
        st.success(f"요청이 저장됐어요 · {receipt['body']}\n\n같은 요청을 다시 누르지 않아도 돼요. 아래 대화에서 처리 상태를 확인하세요.")
    if not closed:
        choices, extra = request_groups(person)
        kids = person.get("location") == "키즈룸"
        st.caption("키즈룸 요청은 음향석에서 확인해요. 같은 요청은 대기 중 한 건으로 묶여요." if kids else "음량 버튼은 내 모니터에서 들리는 소리 조절 요청이에요. 객석 음량이나 특정 악기 조절은 아래 메시지에 적어 주세요.")
        waiting_bodies={r["body"] for r in requests if r["status"] in {"PENDING","ACK"}}
        def buttons(items, offset=0):
            # Pairs preserve priority when mobile columns stack vertically.
            for start in range(0,len(items),2):
                columns=st.columns(2)
                for side,(label,body) in enumerate(items[start:start+2]):
                    if columns[side].button(label,key=f"sound_quick_{offset+start+side}",width="stretch",
                        help="이미 전달한 요청이에요. 아래 대화에서 상태를 확인하세요." if body in waiting_bodies else body):
                        send_request(store,token,body)
        st.caption("자주 쓰는 요청")
        buttons(choices)
        if extra:
            with st.expander("추가 요청 · 장비 점검"):
                buttons(extra,len(choices))
                st.caption("장비를 직접 제어하지 않고 음향석에 요청만 전달해요.")
        with st.form("sound_message",clear_on_submit=True):
            body = st.text_input("직접 요청 쓰기",max_chars=300,placeholder="예: 키즈룸에 담당자 도움이 필요해요" if kids else "예: 제 모니터에서 베이스 소리만 조금 줄여주세요")
            if st.form_submit_button("요청 보내기",type="primary",width="stretch"):
                send_request(store,token,body)


def refresh_requests_button(key):
    with st.container(key=f"{key}_bar"):
        st.caption("요청이나 답변이 안 보이면 새로고침해 주세요.")
        st.button("요청·답변 새로고침", icon=":material/refresh:", key=key, width="stretch")


def participant_live(store, token):
    refresh_requests_button("sound_mine_refresh")
    try:
        room,thread = store.my_conversation(token)
    except AudioError as exc:
        st.error("연결 확인 중 · 아래 상태는 최신 상태가 아닐 수 있어요.")
        flash_error(exc)
        return
    closed = bool(room["closed"] or room["expires_at"] <= time.time())
    st.caption(f"{'종료된 예배방' if closed else '연결됨'} · 마지막 확인 {timestamp(time.time())}")
    st.subheader("음향석과의 대화")
    st.caption(f"처리 대기 {thread['waiting']}건 · 요청과 답변이 시간순으로 이어져요 · 본인과 음향석만 볼 수 있어요")
    chat_thread(room,thread,desk=False,act=lambda action,message="": thread_action(store,room,thread,action,message,token=token))


def thread_action(store,room,thread,action,message="",token=None):
    if token is None and not engineer_access():
        st.error("음향석 접근번호를 다시 확인해 주세요.")
        return
    key="sound_thread_pending_"+thread["person"]["id"]
    pending=st.session_state.get(key)
    if not pending or (pending["action"],pending["message"])!=(action,message):
        pending={"id":uuid.uuid4().hex,"action":action,"message":message}
        st.session_state[key]=pending
    try:
        store.conversation_action(room["id"],thread["person"]["id"],thread["revision"],action,pending["id"],
            engineer_id=st.session_state.get("sound_engineer_id","") if token is None else "",
            engineer=st.session_state.get("sound_engineer_name","") if token is None else "",message=message,token=token)
        st.session_state.pop(key,None)
        st.rerun()
    except (AudioError,ValueError) as exc:
        flash_error(exc)


def send_request(store,token,body):
    # Keep the same id after uncertain network failures; never duplicate on retry.
    pending = st.session_state.get("sound_pending_send")
    if not pending or pending["body"] != body:
        pending = {"id":uuid.uuid4().hex,"body":body}
        st.session_state["sound_pending_send"] = pending
    try:
        request_id=store.send(token,body,pending["id"])
        st.session_state.pop("sound_pending_send",None)
        st.session_state["sound_send_receipt"]={"token":token,"body":body,"id":request_id}
        # A user-initiated send refreshes both composer and inbox once, even
        # when Realtime is not configured. Never claim success before commit.
        st.rerun()
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
    refresh_requests_button("sound_desk_refresh")
    try:
        room,threads=store.conversations(room_id)
    except AudioError as exc:
        st.error("연결 확인 중 · 요청 수신이 지연될 수 있어요.")
        flash_error(exc)
        return
    closed=bool(room["closed"] or room["expires_at"]<=time.time())
    st.caption(f"{'예배방 종료 · 기록 열람' if closed else '연결됨'} · 마지막 확인 {timestamp(time.time())}")
    archived=sum(bool(t["person"].get("desk_archived")) for t in threads)
    st.subheader(f"진행 대화 {len(threads)-archived}명 · 보관 {archived}명")
    view=st.radio("대화 목록",["진행 대화","보관함"],horizontal=True,key="sound_thread_view")
    shown=[t for t in threads if bool(t["person"].get("desk_archived"))==(view=="보관함")]
    if not shown: st.info("보관한 대화가 없어요." if view=="보관함" else "진행 중인 대화가 없어요. 보관한 대화는 보관함에서 불러올 수 있어요.")
    for thread in shown:
        chat_thread(room,thread,desk=True,act=lambda action,message="",thread=thread: thread_action(store,room,thread,action,message))


@st.cache_resource(show_spinner=False)
def prepare_realtime(database_url, _store, schema_version):
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
            prepare_realtime(secret("AUDIO_DATABASE_URL"),store,"r37")
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
    [data-testid="stMainBlockContainer"] :is(.st-key-sound_mine_refresh_bar, .st-key-sound_desk_refresh_bar) div[data-testid="stButton"] button {
        min-height:56px !important; width:100% !important;
        background:#FFF1E3 !important; border:1px solid #E8B68C !important;
        border-radius:14px !important; color:#8F3C00 !important;
        -webkit-text-fill-color:#8F3C00 !important;
    }
    [data-testid="stMainBlockContainer"] :is(.st-key-sound_mine_refresh_bar, .st-key-sound_desk_refresh_bar) div[data-testid="stButton"] button * {
        color:#8F3C00 !important; -webkit-text-fill-color:#8F3C00 !important;
        font-size:16px !important; font-weight:750 !important;
    }
    [data-testid="stMainBlockContainer"] :is(.st-key-sound_mine_refresh_bar, .st-key-sound_desk_refresh_bar) div[data-testid="stButton"] button:hover {
        background:#FFE4C9 !important;
    }
    </style>''')
    st.title("예배 도움 요청")
    st.caption("싱어·세션·키즈룸의 요청을 음향석에서 함께 확인해요.")
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
            st.button("예배방 목록 새로고침",key="sound_rooms_refresh",type="tertiary")
            try:
                available = store.active_rooms()
            except AudioError as exc:
                flash_error(exc)
                available = []
            room_labels = {r["id"]:r["label"] for r in available}
            if not available:
                st.info("지금 열린 예배방이 없어요. 음향석에서 방을 만든 뒤 목록을 새로고침해 주세요.")
            location = st.radio("내 구분",list(GROUPS),horizontal=True,key="sound_join_location")
            preset,custom = instrument_picker("sound_join") if location=="세션" else ("","")
            with st.form("sound_join"):
                selected_room=st.selectbox("참여할 예배방",list(room_labels),format_func=room_labels.get,placeholder="예배방을 선택하세요",disabled=not available)
                alias=st.text_input("내 별명",placeholder={"키즈룸":"비워두면 키즈룸으로 표시해요", "세션":"선택 사항 · 비워두면 악기 이름으로 표시해요", "싱어":"예: 1번 마이크, 인도자"}[location],max_chars=30)
                if location=="세션":
                    st.caption("같은 악기로 여러 명이 접속하면 서로 다른 별명을 적어 주세요.")
                if st.form_submit_button("입장",type="primary",width="stretch",disabled=not available):
                    token=st.session_state.setdefault("sound_join_token",secrets.token_urlsafe(32))
                    try:
                        instrument=selected_instrument(location,preset,custom)
                        name=alias.strip() or ("키즈룸" if location=="키즈룸" else instrument)
                        store.join_room(selected_room,name,token,location=location,instrument=instrument)
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
        with st.expander("내 정보·복귀코드"):
            st.caption("같은 브라우저에서는 자동 복귀해요. 브라우저가 저장을 차단하거나 다른 기기라면 이 코드로 돌아올 수 있어요. 공유하지 마세요.")
            st.code(token,language=None)
            try:
                current=store.mine(token)[0]
            except AudioError as exc:
                flash_error(exc)
                current=None
            if current:
                groups=list(GROUPS) if current["location"] in GROUPS else ["예배팀",*GROUPS]
                location=st.selectbox("내 구분 변경",groups,index=groups.index(current["location"]),key="sound_edit_group")
                preset,custom=instrument_picker("sound_edit",current.get("instrument","")) if location=="세션" else ("","")
                with st.form("sound_rename"):
                    alias=st.text_input("내 별명 변경",value=current["alias"],max_chars=30)
                    if st.form_submit_button("내 정보 저장"):
                        try:
                            instrument=selected_instrument(location,preset,custom)
                            name=alias.strip() or ("키즈룸" if location=="키즈룸" else instrument)
                            if location=="세션" and current["alias"]==current.get("instrument") and name==current["alias"]:
                                name=instrument
                            store.rename(token,name,location=location,instrument=instrument)
                            st.session_state.pop("sound_pending_send",None)
                            st.rerun()
                        except (AudioError,ValueError) as exc:
                            flash_error(exc)
            if st.button("나가기 · 다른 예배방 선택",key="sound_leave"):
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
        rooms=store.rooms_for_desk()
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
                    st.session_state.pop("sound_new_room",None)
                    st.rerun()
                except (AudioError,ValueError) as exc:
                    flash_error(exc)
    st.caption("참여자는 방 이름을 선택해 입장해요. 생성 후 12시간 동안 열리며 음향석에서 먼저 종료할 수 있어요.")
    if not rooms:
        return
    room_map={r["id"]:r["label"]+(" · 종료됨" if r["closed"] or r["expires_at"]<=time.time() else "") for r in rooms}
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

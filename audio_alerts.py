"""Silent, session-local desk alerts. Never modifies request processing status."""
import time
from html import escape

import streamlit as st
from audio_profiles import request_sender


def collect_alerts(state, room, threads):
    known = state.setdefault("known", set())
    pending = state.setdefault("pending", {})
    first = not state.get("initialized", False)
    closed = room["closed"] or room["expires_at"] <= time.time()
    for thread in threads:
        sender = request_sender(thread["person"])
        for request in thread["requests"]:
            key = "request:" + request["id"]
            if key not in known and request["status"] == "PENDING" and not closed:
                pending[key] = (sender, request["body"])
            known.add(key)
        for event in thread["events"]:
            key = "event:" + event["id"]
            if (not first and key not in known and not closed
                    and event["side"] == "participant"
                    and not event["id"].startswith("request:")
                    and event["body"] == "추가 조정이 필요해요."):
                pending[key] = (sender, event["body"])
            known.add(key)
    state["initialized"] = True
    if closed:
        pending.clear()
    return dict(pending)


def acknowledge(state_key, displayed):
    state = st.session_state.get(state_key, {})
    for key in displayed:
        state.get("pending", {}).pop(key, None)


def desk_alerts(room, threads):
    state_key = "sound_alerts_" + room["id"]
    state = st.session_state.setdefault(state_key, {})
    alerts = collect_alerts(state, room, threads)
    st.caption("큰 요청 알림 · 무음 · 현재 선택한 방만 수신해요. 알림 확인은 요청 처리 상태를 바꾸지 않아요.")
    if st.button("무음 알림 테스트", key="sound_alert_test", type="tertiary"):
        state["pending"]["demo"] = ("테스트 · 키즈룸", "소리가 안 들려요. (실제 요청이 아닌 알림 미리보기)")
        alerts = dict(state["pending"])
    if not alerts:
        return
    st.html('''<style>
    .st-key-sound_alert_popup {
        position:fixed !important; top:50%; left:50%; transform:translate(-50%,-50%);
        width:min(820px,94vw) !important; max-height:85dvh; overflow-y:auto;
        z-index:999990; background:#fff7ed !important; color:#431407 !important;
        border:6px solid #ea580c; border-radius:22px; padding:clamp(18px,4vw,36px);
        box-shadow:0 0 0 100vmax #0009,0 24px 80px #0006;
    }
    .st-key-sound_alert_popup h2 {font-size:clamp(28px,4vw,44px)!important;color:#9a3412!important;}
    .st-key-sound_alert_popup .sound-alert-sender {font-size:22px;font-weight:800;color:#9a3412;}
    .st-key-sound_alert_popup .sound-alert-body {font-size:clamp(26px,4vw,38px);font-weight:800;line-height:1.4;white-space:pre-wrap;overflow-wrap:anywhere;color:#431407;}
    .st-key-sound_alert_popup .sound-alert-card {border-top:2px solid #fdba74;padding:16px 0;}
    .st-key-sound_alert_popup button {min-height:64px!important;background:#9a3412!important;color:white!important;border:2px solid #7c2d12!important;}
    .st-key-sound_alert_popup button * {font-size:22px!important;color:white!important;-webkit-text-fill-color:white!important;}
    </style>''')
    with st.container(key="sound_alert_popup"):
        st.html(f'<section role="alert" aria-live="assertive"><h2>새 음향 요청 · {len(alerts)}건</h2><p style="color:#431407">{escape(room["label"])} · 무음 알림</p></section>')
        with st.container(height=300):
            for sender, body in alerts.values():
                st.html(f'<div class="sound-alert-card"><div class="sound-alert-sender">{escape(sender)}</div><div class="sound-alert-body">{escape(body)}</div></div>')
        st.button("알림 확인 · 닫기", key="sound_alert_ack", width="stretch",
                  on_click=acknowledge, args=(state_key, tuple(alerts)))

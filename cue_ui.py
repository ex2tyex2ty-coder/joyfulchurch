"""Team-only rehearsal, preparation and live cue screen."""
import time
import uuid
import copy
from html import escape
from pathlib import Path

import streamlit as st

from audio_requests import AudioError
from audio_ui import secret, store_for
from bible_lookup import extract_bible_references, fetch_local_bible_verse, parse_local_bible
from cue_source import SOURCES, differences, download, offline_html
from cue_store import CueStore, ROLES, authorize
from time_utils import today_kst


def credentials():
    expires = 0
    if st.session_state.get("_access_role") in {"TEAM", "ADMIN"}:
        expires = float(st.session_state.get("_access_expires_at", 0))
    expires = max(expires, float(st.session_state.get("sound_engineer_until", 0)))
    actor = st.session_state.setdefault("cue_actor", uuid.uuid4().hex)
    authorize(actor, expires)
    return actor, expires


def change(store, row, action, value=None):
    try:
        store.act(row["id"], row["revision"], action, value, *credentials())
        st.session_state["cue_feedback"] = (True, "반영했어요.")
    except (AudioError, ValueError) as exc:
        st.session_state["cue_feedback"] = (False, str(exc))


@st.cache_data(show_spinner=False)
def bible_data(data):
    return parse_local_bible(data)


def scripture(source, prefix):
    if not source.strip():
        st.caption("등록된 구절이 없어요.")
        return
    refs = extract_bible_references(source, limit=101)
    if not refs:
        st.warning("구절 표기를 찾지 못했어요. 예: 히브리서 10장 35~37절")
        return
    if len(refs) > 100:
        st.warning("앞의 100절만 표시합니다. 구절 범위를 나누어 주세요.")
    path = Path(__file__).with_name("bible_text.txt")
    if not path.exists():
        st.warning("성경 본문 TXT가 연결되지 않았어요. 기존 성경 검색 설정을 확인하세요.")
        return
    try:
        bible = bible_data(path.read_bytes())
        refs = refs[:100]
        one = st.toggle("한 절씩 크게 보기", key=prefix+"_single")
        if one:
            ref = st.selectbox("표시할 절", refs, format_func=lambda r:r.display, key=prefix+"_verse")
            refs = [ref]
        lines = []
        for ref in refs:
            try:
                verse = fetch_local_bible_verse(bible, ref, "개역개정판")
                lines.append(ref.display+"\n"+verse.content)
                st.html(f'<div class="cue-verse"><strong>{escape(ref.display)}</strong><p>{escape(verse.content)}</p></div>')
            except RuntimeError as exc:
                st.warning(str(exc))
        st.caption("성경 본문 출처: 개역개정판 © 대한성서공회 · 기존 사이트 본문 사용")
        with st.expander("본문 복사"):
            st.code("\n\n".join(lines), language=None, wrap_lines=True)
    except (ValueError, OSError):
        st.warning("저장된 성경 본문을 읽지 못했어요. 성경 검색 설정을 확인하세요.")


def move_personal(iid):
    st.query_params["cue_item"] = iid


def jump_personal(sid, iid):
    move_personal(iid)
    st.session_state["cue_mode_"+sid] = "내가 보기"


def offline_snapshot(plan, state):
    document = copy.deepcopy(plan)
    path = Path(__file__).with_name("bible_text.txt")
    try:
        bible = bible_data(path.read_bytes()) if path.exists() else None
    except (ValueError, OSError):
        bible = None
    for item in document["items"]:
        if state["notes"].get(item["id"]):
            item["notes"] += "\n이번 예배 메모: "+state["notes"][item["id"]]
    if state.get("scripture"):
        document["items"].append(dict(id="scripture", title="인용구절 준비 목록", body=state["scripture"],
                                      kind="본문",sound="",screen="",light="",stage="",notes=""))
    for item in document["items"]:
        if item["kind"] == "본문":
            if bible:
                verses = []
                for ref in extract_bible_references(item["body"], limit=100):
                    try:
                        verses.append(ref.display+"\n"+fetch_local_bible_verse(bible,ref,"개역개정판").content)
                    except RuntimeError:
                        verses.append(ref.display+" · 본문 확인 필요")
                item["body"] += "\n\n"+"\n\n".join(verses)+"\n개역개정판 © 대한성서공회"
            else:
                item["body"] += "\n본문 미연결 · 구절 표기만 포함됩니다."
    return offline_html(document)


def cue_page():
    st.title("예배 진행")
    st.caption("큐시트는 읽기 전용 · 기본 무음 · 내부 담당자용 화면입니다. 자막 송출·장비 제어는 하지 않아요.")
    try:
        auth = credentials()
    except AudioError:
        st.info("공동 진행은 위 ‘접근 권한’에서 팀원으로 로그인해 주세요. 찬양·본문·순서만 보려면 전체 메뉴의 ‘큐시트’를 이용하세요. 음향석 로그인도 사용할 수 있습니다.")
        return
    if not secret("AUDIO_DATABASE_URL"):
        st.warning("준비·진행 상태 저장에는 기존 음향 저장소 연결이 필요해요. AUDIO_DATABASE_URL을 확인하세요.")
        return
    try:
        store = CueStore(store_for(secret("AUDIO_DATABASE_URL")))
        saved = store.list(*auth)
    except AudioError as exc:
        st.error(str(exc))
        return
    st.html('''<style>
    .cue-current {background:#fff1e3;border:3px solid #ff8207;border-radius:18px;padding:24px;overflow-wrap:anywhere;}
    .cue-current h2 {font-size:clamp(26px,4vw,40px)!important;color:#8f3c00!important;margin:0!important;}
    .cue-current p {font-size:21px;white-space:pre-wrap;color:#191f28!important;}
    .cue-verse {border-left:5px solid #ff8207;padding:12px 18px;margin:12px 0;line-height:1.6;}
    .cue-verse p,.cue-verse strong {font-size:clamp(22px,3vw,28px)!important;line-height:1.6!important;}
    .st-key-cue_nav button {min-height:64px!important;} .st-key-cue_nav button p{font-size:22px!important;}
    .st-key-cue_prep_popup {position:fixed!important;top:50%;left:50%;transform:translate(-50%,-50%);width:min(750px,94vw)!important;max-height:80dvh;overflow:auto;background:#fff1e3!important;border:5px solid #ff8207;border-radius:18px;padding:24px;z-index:999990;box-shadow:0 0 0 100vmax #0008;}
    .st-key-cue_prep_popup [data-testid="stText"] {font-size:28px!important;color:#191f28!important;}
    </style>''')
    with st.expander("구글 큐시트 불러오기 · 날짜와 영역 확인", expanded=not saved):
        kind = st.radio("예배 종류", list(SOURCES), horizontal=True)
        st.caption("버튼을 눌렀을 때만 원본을 읽습니다. 처음 읽는 데 잠시 걸릴 수 있어요.")
        if st.button("큐시트 읽기 / 원본 새로고침", key="cue_fetch"):
            try:
                with st.spinner("날짜·탭·영역을 확인하고 있어요…"):
                    plans = download(kind)
                st.session_state["cue_imports"] = plans
                st.session_state["cue_imported_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            except ValueError as exc:
                st.error(str(exc))
        plans = [p for p in st.session_state.get("cue_imports", []) if p["kind"] == kind]
        if plans:
            options = {p["id"]:p for p in plans}
            selected = st.selectbox("사용할 날짜·탭·영역", list(options),
                format_func=lambda i:options[i]["title"]+" · "+options[i]["sheet"]+" · "+options[i]["area"])
            plan = options[selected]
            st.caption("불러온 시각: "+st.session_state.get("cue_imported_at", ""))
            if plan["date"] < today_kst().isoformat():
                st.warning("지난 날짜의 큐시트입니다. 이번 예배에 사용할 자료가 맞는지 확인하세요.")
            for warning in plan["warnings"]:
                st.caption(warning)
            st.dataframe([{"구분":i["kind"], "내용":i["body"], "원본 셀":i["cell"]}
                          for i in plan["items"] if i["kind"] in {"뿌나 찬양", "본문", "설교 후 찬양"}], hide_index=True, width="stretch")
            agreed = st.checkbox("날짜·영역과 불러온 찬양·본문을 확인했어요", key="cue_import_agree_"+plan["hash"])
            if st.button("이 큐시트로 진행 화면 열기", disabled=not agreed):
                try:
                    sid = store.create(plan, *credentials())
                    st.query_params["cue_session"] = sid
                    st.session_state.pop("cue_saved_select", None)
                    st.rerun()
                except (AudioError, ValueError) as exc:
                    st.error(str(exc))
    if not saved:
        st.info("큐시트를 읽고 날짜·영역을 확인한 뒤 진행 화면을 열어 주세요.")
        return
    labels = {r["id"]:r["title"]+" · "+r["id"][:6] for r in saved}
    requested = st.query_params.get("cue_session")
    sid = st.selectbox("저장한 예배", list(labels), index=list(labels).index(requested) if requested in labels else 0,
                       format_func=labels.get, key="cue_saved_select")
    st.query_params["cue_session"] = sid
    cue_live(store, sid)


@st.fragment(run_every=5)
def cue_live(store, sid):
    try:
        auth = credentials()
        row = store.read(sid, *auth)
    except AudioError as exc:
        st.error(str(exc))
        st.warning("최신 진행 상태를 확인하지 못했습니다. 연결 복구 전까지 진행 조작을 중단하세요.")
        return
    feedback = st.session_state.pop("cue_feedback", None)
    if feedback:
        (st.success if feedback[0] else st.error)(feedback[1])
    state = row["state"]
    if auth[1] - time.time() < 600:
        st.warning("담당자 로그인 만료가 10분 이내입니다. 위 ‘접근 권한’에서 접근번호로 재인증해 주세요. 음향석으로 접속했다면 음향 요청에서 다시 로그인하세요.")
    plan = state["plan"]
    items = plan["items"]
    ids = [i["id"] for i in items]
    owner = row["controller"] == auth[0] and row["lease"] > time.time()
    if state["live"] and (not row["controller"] or row["lease"] <= time.time()):
        st.warning("진행 담당 연결이 만료됐어요. 아래는 마지막으로 확인된 순서입니다. 담당을 인계받아 주세요.")
    st.caption(f"{plan['date']} · {plan['sheet']} · {plan['area']} · {'확정본' if state['frozen'] else '준비본'} · {'공동 진행 중' if state['live'] else '준비/일시정지'} · 확인 {time.strftime('%H:%M:%S')}")
    with st.expander("내 담당·보기 방식·진행 권한 설정"):
        st.caption("열린 화면에서 공동 상태를 약 5초마다 확인합니다. 구글 원본은 자동으로 바꾸지 않아요.")
        role = st.radio("내 담당 화면", ROLES, horizontal=True, key="cue_role_"+sid)
        if owner:
            st.caption("내가 진행 담당입니다. 다른 담당자가 미리 보는 위치는 바꾸지 않아요.")
            st.button("진행 담당 해제", on_click=change, args=(store,row,"release"), key="cue_release")
        else:
            st.button("진행 담당 맡기", on_click=change, args=(store,row,"claim"), key="cue_claim")
            st.caption("다른 담당자가 제어 중이면 맡을 수 없어요. 연결이 끊기면 최대 90초 뒤 인계할 수 있어요.")
        mode = st.radio("보기 방식", ["내가 보기", "진행 따라가기"], horizontal=True, key="cue_mode_"+sid)
    iid = state["current"] if mode == "진행 따라가기" else st.query_params.get("cue_item", state["current"])
    if iid not in ids:
        iid = state["current"]
    index = ids.index(iid)
    item = items[index]
    official = next(i for i in items if i["id"] == state["current"])
    st.caption(role+" · "+mode+" · 팀의 현재 순서: "+official["title"])
    st.html(f'<section class="cue-current"><p>{index+1} / {len(items)} · {escape(item["kind"])}</p><h2>{escape(item["title"])}</h2><p>{escape(item["body"] if item["body"] != item["title"] else "")}</p></section>')
    st.info("다음: "+items[index+1]["title"] if index+1 < len(items) else "마지막 순서입니다.")
    with st.container(key="cue_nav"):
        before, after = st.columns(2)
        for col, label, target, disabled in ((before,"이전",max(0,index-1),index==0), (after,"다음",min(len(items)-1,index+1),index==len(items)-1)):
            if mode == "진행 따라가기":
                col.button(label, key="cue_"+label, width="stretch", disabled=disabled or not owner,
                           on_click=change, args=(store,row,"current",ids[target]))
            else:
                col.button(label, key="cue_"+label, width="stretch", disabled=disabled,
                           on_click=move_personal, args=(ids[target],))
    with st.expander("전체 순서 · 원하는 항목으로 이동"):
        for n, candidate in enumerate(items):
            st.button(f"{n+1}. {candidate['title']}", key="cue_jump_"+candidate["id"], width="stretch",
                      on_click=jump_personal, args=(sid,candidate["id"]))
    if owner and mode == "내가 보기":
        st.button("보고 있는 순서를 팀의 현재 순서로 지정", on_click=change, args=(store,row,"current",iid))
    fields = {"전체":[("담당","owner"),("음향","sound"),("화면","screen"),("조명","light"),("무대","stage"),("준비","notes")],
              "음향":[("음향","sound"),("준비","notes")], "자막":[("화면","screen"),("준비","notes")],
              "무대·FD":[("무대","stage"),("조명","light"),("준비","notes")], "찬양팀":[("담당","owner"),("준비","notes")]}
    for label, field in fields[role]:
        if item[field]:
            st.text(label+" · "+item[field])
    if state["notes"].get(iid):
        st.info("이번 예배 메모: "+state["notes"][iid])
    if item["kind"] == "본문":
        scripture(item["body"], "cue_main_"+sid)
    with st.expander("뿌나 찬양 + 설교 후 찬양 목록"):
        for song in items:
            if song["kind"] in {"뿌나 찬양", "설교 후 찬양"}:
                st.text(song["kind"]+" · "+song["body"])
    with st.expander("인용구절 · 기존 성경 검색 연결"):
        source = st.text_area("구절 또는 설교 문자", value=state["scripture"], max_chars=20000, key="cue_scripture_"+sid)
        st.caption("조회는 개인 화면에만 적용됩니다. 준비 목록 공유는 진행 담당자만 할 수 있어요.")
        if st.button("구절 찾기", key="cue_lookup"):
            st.session_state["cue_lookup_"+sid] = source
        if owner:
            st.button("인용구절 준비 목록 공유", on_click=change, args=(store,row,"scripture",source))
        scripture(st.session_state.get("cue_lookup_"+sid, state["scripture"]), "cue_extra_"+sid)
    with st.expander("예배 전 준비 체크"):
        if not plan["checks"]:
            st.warning("원본 체크 사항을 찾지 못했어요. 원본을 확인하세요.")
        missing = [c for c in plan["checks"] if not state["checks"].get(c,{}).get("done")]
        st.caption(f"확인 필요 {len(missing)}건")
        for n, label in enumerate(plan["checks"]):
            status = state["checks"].get(label, {})
            name = st.session_state.get("operator_name") or st.session_state.get("sound_engineer_name") or role
            st.button(("✓ 확인됨 · " if status.get("done") else "□ 확인 필요 · ")+label,
                      key=f"cue_check_{n}", width="stretch", on_click=change,
                      args=(store,row,"check",(label,not status.get("done"),name)))
    if owner:
        with st.expander("진행 담당 설정 · 확정 · 변경 반영 · 준비 요청"):
            st.button("예배용 확정", disabled=state["frozen"], on_click=change, args=(store,row,"freeze"))
            st.button("공동 진행 일시정지" if state["live"] else "공동 진행 시작", disabled=not state["frozen"],
                      on_click=change, args=(store,row,"live",not state["live"]))
            st.caption("진행 따라가기의 이전·다음 버튼으로 넘깁니다. 예정 시각에 자동으로 넘기지 않아요.")
            with st.form("cue_note_"+sid+"_"+iid):
                note = st.text_area("이번 순서 메모 · 악보/음원 URL 등", value=state["notes"].get(iid,""), max_chars=2000)
                if st.form_submit_button("메모 저장"):
                    change(store,row,"note",(iid,note))
                    st.rerun()
            target = st.selectbox("준비 요청 받을 담당", ROLES)
            with st.form("cue_message"):
                message = st.text_input("무음 준비 요청", max_chars=300, placeholder="예: 설교 마무리 준비 · 밴드와 싱어 대기")
                if st.form_submit_button("준비 요청 보내기"):
                    change(store,row,"message",(target,message))
                    st.rerun()
            for message in state["messages"][-5:]:
                st.text(f"{message['target']} · {message['body']} · 확인: {', '.join(message['ack']) or '대기'}")
            try:
                rooms = store.db.active_rooms()
            except AudioError as exc:
                st.warning(str(exc))
                rooms = []
            room_labels = {"":"연결 안 함", **{r["id"]:r["label"] for r in rooms}}
            selected_room = st.selectbox("음향 요청과 연결할 예배방", list(room_labels),
                index=list(room_labels).index(row["room_id"]) if row["room_id"] in room_labels else 0, format_func=room_labels.get)
            st.button("음향방 연결 적용", on_click=change, args=(store,row,"room",selected_room))
            st.caption("공동 진행 중 새 음향 요청에 당시 공식 순서 이름만 붙습니다. 다른 참여자의 요청은 공유하지 않아요.")
            if st.button("이 예배의 원본 변경 확인"):
                try:
                    candidates = download(plan["kind"])
                    newer = next((p for p in candidates if p["id"] == sid), None)
                    if newer is None:
                        raise ValueError("같은 날짜·탭·영역을 찾지 못했어요. 기존 내용은 유지합니다.")
                    st.session_state["cue_new_"+sid] = newer
                except ValueError as exc:
                    st.error(str(exc))
            newer = st.session_state.get("cue_new_"+sid)
            if newer:
                diff = differences(plan,newer)
                if not diff:
                    st.caption("변경 사항이 없습니다.")
                else:
                    for line in diff:
                        st.text(line)
                    agreed = st.checkbox("변경 내용을 반영하고 준비 체크를 다시 확인할게요", key="cue_apply_"+newer["hash"])
                    st.button("변경 승인 · 확정본에 반영", disabled=not agreed, on_click=change, args=(store,row,"import",newer))
    st.download_button("인터넷 없이 볼 사본 내려받기 · HTML/인쇄", offline_snapshot(plan,state),
                       file_name=plan["date"]+"_예배진행.html", mime="text/html")
    st.link_button("구글 원본 열기", plan["url"])
    pending = [m for m in state["messages"] if m["target"] in {role,"전체"} and role not in m["ack"]]
    if pending:
        with st.container(key="cue_prep_popup"):
            st.subheader("준비 요청 · 무음")
            for message in pending:
                st.text(message["body"])
                st.button("확인했어요", key="cue_ack_"+message["id"], width="stretch", on_click=change,
                          args=(store,row,"ack",(message["id"],role)))

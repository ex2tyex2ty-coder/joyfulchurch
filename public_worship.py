"""Public, read-only worship views. Never read shared cue/room storage."""
from datetime import date

import streamlit as st

from cue_source import SOURCES, download
from cue_ui import scripture


def public_plan(plan):
    """Allowlist public fields; never expose technical cues, names or team notes."""
    return {"id": plan["id"], "date": plan["date"], "title": plan["title"],
            "items": [{"id": i["id"], "title": i["title"], "kind": i["kind"],
                       "body": i["body"] if i["kind"] in {"뿌나 찬양", "설교 후 찬양", "본문"} else ""}
                      for i in plan["items"]]}


@st.cache_data(ttl=300, show_spinner=False)
def public_plans(kind):
    return [public_plan(p) for p in download(kind)]


def public_cue_page():
    st.title("큐시트")
    st.caption("누구나 보는 예배 순서 · 로그인 없이 이용 · 이동은 내 화면에만 반영됩니다.")
    kind = st.radio("예배 선택", list(SOURCES), horizontal=True, key="public_cue_kind")
    if st.button("최신 큐시트 다시 읽기", key="public_cue_refresh"):
        public_plans.clear(kind)
    try:
        with st.spinner("예배 순서를 불러오고 있어요…"):
            plans = public_plans(kind)
    except ValueError:
        st.warning("큐시트를 불러오지 못했어요. 잠시 후 다시 읽기를 눌러 주세요.")
        return
    if not plans:
        st.info("공개할 예배 순서를 찾지 못했어요. 원본의 날짜와 표 형식을 확인해 주세요.")
        return
    plans = sorted(plans, key=lambda p: p["date"], reverse=True)
    plan_index = st.selectbox("예배 날짜 확인", range(len(plans)),
                              format_func=lambda i: plans[i]["title"] + f" · 목록 {i+1}",
                              key="public_plan_"+kind)
    plan = plans[plan_index]
    st.subheader(plan["title"])
    if plan["date"] != date.today().isoformat():
        st.info(f"선택한 큐시트 날짜는 {plan['date']}입니다. 오늘 예배 자료인지 확인해 주세요.")
    items = plan["items"]
    if not items:
        st.info("등록된 예배 순서가 없어요.")
        return
    with st.expander("찬양 목록 한눈에 보기", expanded=True):
        for item in items:
            if item["kind"] in {"뿌나 찬양", "설교 후 찬양"}:
                st.write(f"{item['kind']} · {item['body']}")
    position_key = "public_position_"+plan["id"]
    position = min(max(int(st.session_state.get(position_key, 0)), 0), len(items)-1)
    previous, following = st.columns(2)
    if previous.button("← 이전 순서", disabled=position == 0, width="stretch"):
        position -= 1
    if following.button("다음 순서 →", disabled=position == len(items)-1, width="stretch"):
        position += 1
    st.session_state[position_key] = position
    item = items[position]
    with st.container(border=True):
        st.caption(f"내가 보는 순서 {position+1} / {len(items)}")
        st.subheader(item["title"])
        if item["kind"] == "본문":
            scripture(item["body"], "public_"+item["id"])
        elif item["body"] and item["body"] != item["title"]:
            st.write(item["body"])
        st.caption("다음: " + (items[position+1]["title"] if position+1 < len(items) else "마지막 순서입니다"))
    with st.expander("전체 순서 · 눌러서 이동", expanded=True):
        for index, entry in enumerate(items):
            if st.button(f"{'● ' if index == position else ''}{index+1}. {entry['title']}",
                         key="public_jump_"+entry["id"], width="stretch"):
                st.session_state[position_key] = index
                st.rerun()
    with st.expander("인용구절 찾아보기"):
        reference = st.text_input("성경 구절", placeholder="예: 요한복음 3장 16절", key="public_reference")
        if reference.strip():
            scripture(reference, "public_reference_result")


def bulletin_page():
    st.title("주보")
    st.caption("누구나 보는 교회 주보 · 로그인 없이 이용")
    st.info("주보를 준비하고 있습니다. 아직 등록된 주보가 없습니다.")
    st.write("실제 주보 PDF·이미지 또는 원본 링크가 정해지면 이곳에서 볼 수 있도록 연결할 예정입니다.")

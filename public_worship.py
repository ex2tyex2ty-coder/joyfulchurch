"""Public, read-only worship views. Never read shared cue/room storage."""
import copy
import time
import re
import unicodedata
from html import escape
from pathlib import Path

import streamlit as st

from cue_source import SOURCES, download
from cue_ui import scripture, bible_data
from bible_lookup import extract_bible_references, fetch_local_bible_verse
from time_utils import now_kst, today_kst


def public_plan(plan):
    """Allowlist public fields; never expose technical cues, names or team notes."""
    return {"id": plan["id"], "date": plan["date"], "title": plan["title"],
            "items": [{"id": i["id"], "title": i["title"], "kind": i["kind"],
                       "time": i.get("time", ""),
                       "body": i["body"] if i["kind"] in {"뿌나 찬양", "설교 후 찬양", "본문", "기도회"} else ""}
                      for i in plan["items"]]}


@st.cache_data(ttl=300, show_spinner=False)
def public_plans(kind):
    return [public_plan(p) for p in download(kind)]


def find_cues(items, query="", category="전체"):
    """Keep original positions and inspect only public content, not internal fields."""
    def normalized(value):
        return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(value)).casefold())
    terms = [normalized(word) for word in query.split() if word]
    results = []
    for number, item in enumerate(items, 1):
        if category == "찬양" and item["kind"] not in {"뿌나 찬양", "설교 후 찬양"}:
            continue
        if category == "말씀" and item["kind"] != "본문":
            continue
        haystack = normalized(" ".join(str(item.get(k, "")) for k in ("title", "body", "time")))
        if all(term in haystack for term in terms):
            results.append((number, item))
    return results


def select_public_cue(sid, iid):
    st.session_state["public_item_"+sid] = iid
    st.session_state["public_cue_view"] = "한 순서씩 보기"


def full_schedule_html(items, *, large=False, numbers=None):
    rows = []
    for index, item in enumerate(items):
        detail = item["body"] if item["body"] and item["body"] not in item["title"] else ""
        rows.append('<tr><td>'+escape(item.get("time") or "—")+'</td><td><strong>'
                    +str(numbers[index] if numbers else index+1)+'. '+escape(item["title"])
                    +'</strong>' + ('<div>'+escape(detail)+'</div>' if detail else '')+'</td></tr>')
    return '''<style>.public-cue-table{width:100%;border-collapse:collapse;table-layout:fixed;background:white;color:#191f28;font-size:FONT_SIZEpx;line-height:1.6}
    .public-cue-table th,.public-cue-table td{padding:14px 10px;border-bottom:1px solid #e5e8eb;text-align:left;vertical-align:top;overflow-wrap:anywhere;white-space:pre-wrap}
    .public-cue-table th{background:#fff1e3}.public-cue-table th:first-child{width:TIME_WIDTHpx}.public-cue-table td:first-child{font-variant-numeric:tabular-nums}.public-cue-table td div{margin-top:6px;line-height:1.6}</style>
    <table class="public-cue-table"><thead><tr><th scope="col">시간</th><th scope="col">예배 순서·내용</th></tr></thead><tbody>'''.replace('FONT_SIZE', '21' if large else '16').replace('TIME_WIDTH', '96' if large else '80')+''.join(rows)+'</tbody></table>'


def public_bible_passages(plan):
    """Bounded local-only text for the public export; never use shared team notes."""
    path = Path(__file__).with_name("bible_text.txt")
    try:
        bible = bible_data(path.read_bytes())
    except (OSError, ValueError):
        return {}, "성경 본문 파일을 읽지 못해 구절 표기만 포함했습니다."
    passages, budget, truncated = {}, 100, False
    for item in plan["items"]:
        if item["kind"] != "본문":
            continue
        refs = extract_bible_references(item["body"], limit=101)
        lines = []
        if len(refs) > budget:
            truncated = True
        for ref in refs[:budget]:
            try:
                verse = fetch_local_bible_verse(bible, ref, "개역개정판")
                lines.append(ref.display+"\n"+verse.content)
            except RuntimeError:
                lines.append(ref.display+" · 본문 확인 필요")
        budget -= min(budget, len(refs))
        if lines:
            passages[item["id"]] = "\n\n".join(lines)
    return passages, "성경 본문은 앞의 100절까지만 포함했습니다." if truncated else ""


def public_offline_html(plan, created_at, *, passages=None, notice=""):
    # Apply the public allowlist again even if a caller passes a full internal plan.
    safe = public_plan(plan)
    details = []
    for item in safe["items"]:
        if item["kind"] == "본문" and (passages or {}).get(item["id"]):
            details.append('<section><h2>'+escape(item["title"])+'</h2><pre>'
                           +escape(passages[item["id"]])+'</pre></section>')
    return '''<!doctype html><html lang="ko"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
    <title>'''+escape(safe["title"])+''' · 공개 큐시트</title><style>
    body{font:18px/1.6 system-ui,sans-serif;max-width:900px;margin:auto;padding:20px;color:#191f28;background:white}
    button{font:inherit;padding:12px 18px;margin-bottom:16px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}
    h1{font-size:26px}h2{font-size:22px}section{margin-top:24px}tr{break-inside:avoid}
    @media print{button{display:none}body{padding:0;font-size:12pt}.public-cue-table{font-size:11pt!important}thead{display:table-header-group}}
    </style></head><body><button onclick="window.print()">인쇄 / PDF로 저장</button><h1>'''+escape(safe["title"])+'''</h1>
    <p>공개용 보기 사본 · 실시간 갱신·알림·공동 진행은 작동하지 않습니다.</p><p>파일 생성: '''+escape(created_at)+'''</p>
    <p>'''+escape(notice)+'''</p>'''+full_schedule_html(safe["items"])+''.join(details)+(
        '<p>성경 본문 출처: 개역개정판 © 대한성서공회 · 기존 사이트 본문 사용</p>' if details else '')+'</body></html>'


def public_cue_page():
    st.title("큐시트")
    st.caption("누구나 보는 예배 순서 · 로그인 없이 이용 · 이동은 내 화면에만 반영됩니다.")
    kind = st.radio("예배 선택", list(SOURCES), horizontal=True, key="public_cue_kind")
    retry_key = "public_retry_after_"+kind
    if st.button("최신 큐시트 다시 읽기", key="public_cue_refresh"):
        public_plans.clear(kind)
        st.session_state.pop(retry_key, None)
    snapshot_key = "public_snapshot_"+kind
    cached = st.session_state.get(snapshot_key)
    try:
        if st.session_state.get(retry_key, 0) > time.time():
            raise ValueError("retry backoff")
        with st.spinner("예배 순서를 불러오고 있어요…"):
            plans = public_plans(kind)
        if not plans:
            raise ValueError("empty source")
        if not cached or cached["plans"] != plans:
            cached = {"plans": copy.deepcopy(plans), "at": now_kst().strftime("%Y-%m-%d %H:%M:%S KST")}
            st.session_state[snapshot_key] = cached
        st.session_state.pop(retry_key, None)
    except ValueError:
        if st.session_state.get(retry_key, 0) <= time.time():
            st.session_state[retry_key] = time.time()+30
        if not cached:
            st.warning("큐시트를 불러오지 못했어요. 잠시 후 다시 읽기를 눌러 주세요.")
            return
        plans = cached["plans"]
        st.warning("원본 연결을 확인하지 못해 마지막 정상본을 표시합니다. 최신 변경은 아직 반영되지 않았어요.")
        st.caption("이 브라우저에서 정상본을 보관한 시각: "+cached["at"]+" · 재접속/브라우저 종료 후에는 유지되지 않을 수 있습니다.")
    plans = sorted(plans, key=lambda p: p["date"], reverse=True)
    by_id = {p["id"]: p for p in plans}
    select_key = "public_plan_id_"+kind
    previous_plan = st.session_state.get(select_key)
    if previous_plan and previous_plan not in by_id:
        st.warning("선택한 예배가 원본 목록에서 없어졌어요. 예배 날짜를 다시 확인해 주세요.")
        st.session_state[select_key] = next(iter(by_id))
    selected = st.selectbox("예배 날짜 확인", list(by_id), format_func=lambda sid: by_id[sid]["title"], key=select_key)
    plan = by_id[selected]
    st.subheader(plan["title"])
    if plan["date"] != today_kst().isoformat():
        st.info(f"선택한 큐시트 날짜는 {plan['date']}입니다. 오늘 예배 자료인지 확인해 주세요.")
    items = plan["items"]
    if not items:
        st.info("등록된 예배 순서가 없어요.")
        return
    large = st.toggle("큰 글씨 보기", key="public_large_text")
    with st.container(key="public_cue_reading"):
        render_public_cue(plan, kind, large, cached)


def render_public_cue(plan, kind, large, cached):
    items = plan["items"]
    font_size = 21 if large else 16
    st.html(f'''<style>
    .st-key-public_cue_reading [data-testid="stMarkdownContainer"] p,
    .st-key-public_cue_reading .cue-verse p {{font-size:{font_size}px!important;line-height:1.7!important}}
    .st-key-public_cue_reading .cue-verse {{border-left:4px solid #ff8207;padding:8px 14px;overflow-wrap:anywhere}}
    </style>''')
    with st.expander("찬양 목록 한눈에 보기", expanded=True):
        for item in items:
            if item["kind"] in {"뿌나 찬양", "설교 후 찬양"}:
                if item["body"].strip():
                    st.write(item["body"])
    st.link_button("구글 원본 큐시트 전체 보기 ↗",
                   f"https://docs.google.com/spreadsheets/d/{SOURCES[kind]}/edit", width="stretch")
    whole, follow = st.tabs(["전체 큐시트", "한 순서씩 보기"], key="public_cue_view", on_change="rerun")
    with whole:
        query = st.text_input("순서·찬양·본문 검색", placeholder="예: 히브리서, 찬양 제목, 14:40", key="public_cue_search_"+plan["id"])
        category = st.radio("표시할 순서", ["전체", "찬양", "말씀"], horizontal=True, key="public_cue_filter_"+plan["id"])
        matched = find_cues(items, query, category)
        st.caption(f"전체 {len(items)}개 항목 · 시간은 원본 표 기준입니다. 같은 찬양 묶음의 곡들은 시작 시간이 같습니다.")
        if query.strip() or category != "전체":
            st.caption(f"검색 결과 {len(matched)}개 · 번호는 원래 순서입니다. 아래 항목을 누르면 한 순서씩 보기로 이동합니다.")
            for number, entry in matched:
                st.button(f"{number}. {entry['title']} 열기", key="public_result_"+entry["id"], width="stretch",
                          on_click=select_public_cue, args=(plan["id"], entry["id"]))
        if matched:
            st.html(full_schedule_html([item for _,item in matched], large=large, numbers=[n for n,_ in matched]))
        else:
            st.info("맞는 순서가 없어요. 검색어를 지우거나 ‘전체’를 선택해 주세요.")
        st.caption("음향·조명 등 원본의 모든 열은 위 ‘구글 원본 큐시트 전체 보기’에서 확인할 수 있습니다.")
    with follow:
        personal_sequence(plan)
    with st.expander("인용구절 찾아보기"):
        reference = st.text_input("성경 구절", placeholder="예: 요한복음 3장 16절", key="public_reference")
        if reference.strip():
            scripture(reference, "public_reference_result")
    with st.expander("인쇄·오프라인 저장"):
        st.caption("검색 조건과 관계없이 선택한 예배의 전체 순서를 저장합니다. 파일을 열어 인쇄하거나 PDF로 저장할 수 있어요.")
        include_bible = st.checkbox("본문 말씀도 파일에 포함", value=True, key="public_export_bible")
        passages, notice = public_bible_passages(plan) if include_bible else ({}, "성경 본문은 포함하지 않고 구절 표기만 저장했습니다.")
        if cached:
            notice += " 브라우저 보관본 시각: "+cached["at"]+". 저장 파일은 원본 변경을 자동 반영하지 않습니다."
        st.download_button("공개 큐시트 저장 · HTML/인쇄용",
                           public_offline_html(plan, now_kst().strftime("%Y-%m-%d %H:%M:%S KST"), passages=passages, notice=notice),
                           file_name=plan["date"]+"_"+kind+"_공개큐시트.html", mime="text/html", key="public_export", on_click="ignore")


def personal_sequence(plan):
    items = plan["items"]
    position_key = "public_position_"+plan["id"]
    ids = [i["id"] for i in items]
    selected_key = "public_item_"+plan["id"]
    selected = st.session_state.get(selected_key)
    if selected and selected not in ids:
        st.warning("보던 순서가 원본에서 삭제되거나 이름이 바뀌었어요. 첫 순서로 이동했습니다. 전체 순서에서 다시 선택해 주세요.")
        position = 0
    elif selected:
        position = ids.index(selected)
    else:
        # Preserve existing r44 sessions once, then use item identity thereafter.
        position = min(max(int(st.session_state.get(position_key, 0)), 0), len(items)-1)
    previous, following = st.columns(2)
    if previous.button("← 이전 순서", disabled=position == 0, width="stretch"):
        position -= 1
    if following.button("다음 순서 →", disabled=position == len(items)-1, width="stretch"):
        position += 1
    st.session_state[position_key] = position
    st.session_state[selected_key] = ids[position]
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
                st.session_state[selected_key] = entry["id"]
                st.rerun()


def bulletin_page():
    st.title("주보")
    st.caption("누구나 보는 교회 주보 · 로그인 없이 이용")
    st.info("주보를 준비하고 있습니다. 아직 등록된 주보가 없습니다.")
    st.write("실제 주보 PDF·이미지 또는 원본 링크가 정해지면 이곳에서 볼 수 있도록 연결할 예정입니다.")

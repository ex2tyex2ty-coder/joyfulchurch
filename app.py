from __future__ import annotations

import io
import html
import json
import sys
import zipfile
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from config import (
    APP_TITLE,
    APP_VERSION,
    DB_PATH,
    GOOGLE_SHEETS_CACHE_DIR,
    IMPORT_REPORT_PATH,
    REVIEW_BOARD_SPREADSHEET_ID,
    SOURCE_DIR,
    ensure_directories,
)
from calendar_sync import sync_google_calendar_service_account
from google_sheets_sync import sync_google_sheets
from google_review_board import GoogleReviewBoardStore, ReviewBoardConnectionError, filter_review_items
from db import (
    add_review_comment,
    add_decision,
    add_operation_log,
    add_reference_record,
    add_task,
    add_task_template,
    archive_entity,
    carry_review_issue,
    clone_event,
    create_review_item,
    create_event,
    create_event_template,
    create_manual,
    export_backup,
    global_search,
    get_app_meta,
    init_db,
    readiness,
    revise_manual,
    row,
    rows,
    save_review,
    set_app_meta,
    set_task_status,
    update_event_status,
    verify_manual,
)
from migration import migrate


st.set_page_config(page_title=APP_TITLE, page_icon="⛪", layout="wide", initial_sidebar_state="auto")

# Match charts to the same Joyful Church brand palette.
px.defaults.template = "plotly_white"
px.defaults.color_discrete_sequence = ["#FF8207", "#B84B00", "#FFC166", "#5B4A3E"]

CSS = """
<style>
:root { --ink:#2C1F16; --orange:#FF8207; --orange-dark:#B84B00; --orange-soft:#FFF0DE; --cream:#FFFDF9; --red:#A33B32; color-scheme:light !important; }
html, body, .stApp { color-scheme:light !important; }
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stMainBlockContainer"] {
  background:#FFFDF9 !important; color:#30251D !important;
}
[data-testid="stHeader"] { background:rgba(255,253,249,.96) !important; }
[data-testid="stToolbar"] button, [data-testid="stHeaderActionElements"] button { color:#2C1F16 !important; }
[data-testid="stSidebar"] { background:#2E241D; }
[data-testid="stSidebar"] * { color:#FFF9F2 !important; }
[data-testid="stSidebar"] input { color:#30251D !important; }
/* Keep the sidebar open/close control visible in System and Dark modes. */
[data-testid="stSidebarCollapseButton"] button,
[data-testid="stSidebarCollapsedControl"] button,
[data-testid="collapsedControl"] button,
button[data-testid="stExpandSidebarButton"],
button[data-testid="stBaseButton-headerNoPadding"] {
  -webkit-appearance:none !important; appearance:none !important; color-scheme:light !important;
  background:#FF8207 !important; background-image:none !important;
  color:#2C1F16 !important; -webkit-text-fill-color:#2C1F16 !important;
  border:2px solid #FFFFFF !important; border-radius:999px !important;
  width:2.65rem !important; height:2.65rem !important; min-width:2.65rem !important;
  opacity:1 !important; box-shadow:0 2px 8px rgba(0,0,0,.28) !important;
}
[data-testid="stSidebarCollapseButton"] button *,
[data-testid="stSidebarCollapsedControl"] button *,
[data-testid="collapsedControl"] button *,
button[data-testid="stExpandSidebarButton"] *,
button[data-testid="stBaseButton-headerNoPadding"] * {
  color:#2C1F16 !important; -webkit-text-fill-color:#2C1F16 !important;
  fill:#2C1F16 !important; stroke:#2C1F16 !important; opacity:1 !important;
}
[data-testid="stSidebarCollapseButton"] svg,
[data-testid="stSidebarCollapsedControl"] svg,
[data-testid="collapsedControl"] svg,
button[data-testid="stExpandSidebarButton"] svg { fill:#2C1F16 !important; color:#2C1F16 !important; }
h1,h2,h3,h4,h5,h6 { color:#2C1F16 !important; letter-spacing:-.02em; }
[data-testid="stMainBlockContainer"] [data-testid="stMarkdownContainer"] p,
[data-testid="stMainBlockContainer"] [data-testid="stMarkdownContainer"] li,
[data-testid="stMainBlockContainer"] [data-testid="stMarkdownContainer"] span,
[data-testid="stMainBlockContainer"] label,
[data-testid="stMainBlockContainer"] [data-testid="stCaptionContainer"],
[data-testid="stMainBlockContainer"] [data-testid="stCaptionContainer"] p,
[data-testid="stMainBlockContainer"] [data-testid="stWidgetLabel"] p,
[data-testid="stMainBlockContainer"] [data-testid="stCheckbox"] p,
[data-testid="stMainBlockContainer"] [data-testid="stToggle"] p {
  color:#3B2E25 !important; -webkit-text-fill-color:#3B2E25 !important; opacity:1 !important;
}
a { color:#AD4700; }
.ops-hero { background:linear-gradient(120deg,#FFA640,#FF8207); color:#2C1F16; border-radius:20px; padding:1.35rem 1.5rem; margin-bottom:1.1rem; box-shadow:0 10px 25px rgba(184,75,0,.16); }
.ops-hero h1 { color:#2C1F16 !important; -webkit-text-fill-color:#2C1F16 !important; margin:0; font-size:1.85rem; }
.ops-hero p { color:#3B2A1E !important; -webkit-text-fill-color:#3B2A1E !important; margin:.35rem 0 0; opacity:1 !important; }
.ops-card { background:white; border:1px solid #EBD6C2; border-radius:16px; padding:1rem 1.05rem; min-height:110px; box-shadow:0 3px 12px rgba(88,52,24,.06); }
.ops-card .label { color:#6B584B; font-size:.82rem; margin-bottom:.25rem; }
.ops-card .value { color:#2C1F16; font-weight:750; font-size:1.55rem; }
.ops-card .note { color:#735F50; font-size:.78rem; margin-top:.3rem; }
.ops-card-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:.65rem; }
.ops-stat-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.65rem; margin:.5rem 0 1rem; }
.ops-stat { background:#FFFFFF; border:1px solid #E4CCB6; border-radius:14px; padding:.75rem .85rem; }
.ops-stat .label { color:#5B493D; font-size:.82rem; }
.ops-stat .value { color:#2C1F16; font-size:1.35rem; font-weight:800; margin-top:.2rem; }
.review-stat-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.45rem; margin:.55rem 0 .9rem; }
.review-stat { background:#FFFFFF; border:1px solid #E4CCB6; border-radius:12px; min-height:76px; padding:.55rem .3rem; text-align:center; display:flex; flex-direction:column; align-items:center; justify-content:center; }
.review-stat .label { color:#5B493D; font-size:.78rem; line-height:1.2; white-space:nowrap; }
.review-stat .value { color:#2C1F16; font-size:1.3rem; line-height:1.15; font-weight:800; margin-top:.25rem; }
.compact-stat-grid { display:grid; grid-template-columns:repeat(var(--stat-cols,4),minmax(0,1fr)); gap:.42rem; margin:.55rem 0 .9rem; }
.compact-stat { background:#FFFFFF; border:1px solid #E4CCB6; border-radius:12px; min-height:74px; padding:.55rem .3rem; text-align:center; display:flex; flex-direction:column; align-items:center; justify-content:center; }
.compact-stat .label { color:#5B493D; font-size:.77rem; line-height:1.2; }
.compact-stat .value { color:#2C1F16; font-size:1.2rem; line-height:1.15; font-weight:800; margin-top:.25rem; overflow-wrap:anywhere; }
.ops-list { display:grid; gap:.5rem; margin:.45rem 0 .75rem; }
.ops-list-item { background:#FFFFFF; border:1px solid #E4CCB6; border-left:4px solid #FF8207; border-radius:12px; padding:.7rem .8rem; }
.ops-list-item .meta { color:#735F50; font-size:.8rem; margin-bottom:.18rem; }
.ops-list-item .title { color:#2C1F16; font-size:.98rem; font-weight:800; }
.ops-list-item .note { color:#665448; font-size:.82rem; margin-top:.2rem; }
.ops-attendance { background:#FFFFFF; border:1px solid #E4CCB6; border-left:5px solid #FF8207; border-radius:16px; padding:1rem 1.1rem; margin:.4rem 0 1rem; }
.ops-attendance .date { color:#735F50; font-size:.88rem; }
.ops-attendance .total { color:#2C1F16; font-size:2.15rem; font-weight:850; line-height:1.15; margin:.35rem 0 .55rem; }
.ops-attendance .chips { display:flex; flex-wrap:wrap; gap:.4rem; }
.ops-chip { display:inline-block; background:#FFF0DE; color:#6B2C00 !important; border-radius:999px; padding:.3rem .65rem; font-size:.84rem; font-weight:700; }
.ops-dashboard-head { display:flex; align-items:flex-end; justify-content:space-between; gap:1rem; margin:.15rem 0 1rem; padding-bottom:.85rem; border-bottom:1px solid #EBD6C2; }
.ops-dashboard-head h1 { margin:0; font-size:1.75rem; }
.ops-dashboard-head span { color:#735F50; font-size:.88rem; white-space:nowrap; }
.ops-badge { display:inline-block; border-radius:999px; padding:.17rem .55rem; font-size:.72rem; font-weight:700; background:#FFF0DE; color:#963D00 !important; -webkit-text-fill-color:#963D00 !important; margin-right:.25rem; }
.ops-badge.warn { background:#FFF1DB; color:#7A4800 !important; -webkit-text-fill-color:#7A4800 !important; }
.ops-badge.danger { background:#FCE8E6; color:#8F2F28 !important; -webkit-text-fill-color:#8F2F28 !important; }
.ops-badge.gray { background:#EDF0F2; color:#46565F !important; -webkit-text-fill-color:#46565F !important; }
.ops-item { background:white; border:1px solid #EBD6C2; border-left:4px solid #FF8207; border-radius:12px; padding:.8rem .9rem; margin:.45rem 0; }
.ops-item.warn { border-left-color:#E09F3E; }
.ops-item.danger { border-left-color:#A33B32; }
.review-comment { background:#FFF8F0; border:1px solid #EBD6C2; border-radius:10px; padding:.65rem .75rem; margin:.35rem 0; }
.muted { color:#665448 !important; -webkit-text-fill-color:#665448 !important; font-size:.87rem; }
.compact p { margin:.15rem 0; }
div[data-testid="stMetric"] { background:#FFFFFF !important; border:1px solid #E4CCB6; border-radius:14px; padding:.7rem .85rem; }
[data-testid="stMetricLabel"] *, [data-testid="stMetricDelta"] * { color:#5B493D !important; -webkit-text-fill-color:#5B493D !important; }
[data-testid="stMetricValue"] * { color:#2C1F16 !important; -webkit-text-fill-color:#2C1F16 !important; }
/* iPhone/Safari dark mode must never turn action buttons black. */
[data-testid="stMainBlockContainer"] div[data-testid="stButton"] button,
[data-testid="stMainBlockContainer"] div[data-testid="stFormSubmitButton"] button,
[data-testid="stMainBlockContainer"] div[data-testid="stDownloadButton"] button,
[data-testid="stMainBlockContainer"] div[data-testid="stLinkButton"] a,
[data-testid="stMainBlockContainer"] .stButton > button,
[data-testid="stMainBlockContainer"] .stDownloadButton > button,
[data-testid="stMainBlockContainer"] .stLinkButton > a {
  -webkit-appearance:none !important; appearance:none !important; color-scheme:light !important;
  background-color:#FFFFFF !important; background-image:none !important;
  color:#753100 !important; -webkit-text-fill-color:#753100 !important;
  border:2px solid #C45B08 !important; border-radius:10px !important;
  font-weight:800 !important; opacity:1 !important;
  box-shadow:0 2px 5px rgba(184,75,0,.20) !important;
}
[data-testid="stMainBlockContainer"] div[data-testid="stButton"] button *,
[data-testid="stMainBlockContainer"] div[data-testid="stFormSubmitButton"] button *,
[data-testid="stMainBlockContainer"] div[data-testid="stDownloadButton"] button *,
[data-testid="stMainBlockContainer"] div[data-testid="stLinkButton"] a *,
[data-testid="stMainBlockContainer"] .stButton > button *,
[data-testid="stMainBlockContainer"] .stDownloadButton > button *,
[data-testid="stMainBlockContainer"] .stLinkButton > a * {
  color:#753100 !important; -webkit-text-fill-color:#753100 !important; opacity:1 !important;
}
[data-testid="stMainBlockContainer"] button[kind="primary"],
[data-testid="stMainBlockContainer"] button[data-testid="stBaseButton-primary"] {
  background-color:#FF8207 !important; color:#2C1F16 !important; -webkit-text-fill-color:#2C1F16 !important;
}
[data-testid="stMainBlockContainer"] button[kind="primary"] *,
[data-testid="stMainBlockContainer"] button[data-testid="stBaseButton-primary"] * {
  color:#2C1F16 !important; -webkit-text-fill-color:#2C1F16 !important;
}
[data-testid="stMainBlockContainer"] div[data-testid="stButton"] button:hover,
[data-testid="stMainBlockContainer"] div[data-testid="stFormSubmitButton"] button:hover,
[data-testid="stMainBlockContainer"] div[data-testid="stDownloadButton"] button:hover,
[data-testid="stMainBlockContainer"] div[data-testid="stLinkButton"] a:hover {
  background-color:#FFF0DE !important; border-color:#963D00 !important;
}
[data-testid="stMainBlockContainer"] button[kind="primary"]:hover,
[data-testid="stMainBlockContainer"] button[data-testid="stBaseButton-primary"]:hover {
  background-color:#E96F00 !important;
}
[data-testid="stMainBlockContainer"] button:disabled,
[data-testid="stMainBlockContainer"] button:disabled * {
  background:#E9E0D8 !important; color:#51443B !important; -webkit-text-fill-color:#51443B !important;
  border-color:#B9A99B !important; opacity:1 !important;
}
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
[data-baseweb="select"] > div, [data-testid="stNumberInput"] input,
[data-testid="stDateInput"] input {
  background:#FFFFFF !important; color:#30251D !important; -webkit-text-fill-color:#30251D !important;
  border-color:#B9A28F !important; caret-color:#30251D !important; opacity:1 !important;
}
input::placeholder, textarea::placeholder {
  color:#786557 !important; -webkit-text-fill-color:#786557 !important; opacity:1 !important;
}
[data-baseweb="select"] *, [role="listbox"] *, [role="option"], [data-baseweb="popover"] * {
  color:#30251D !important; -webkit-text-fill-color:#30251D !important;
}
[role="listbox"], [data-baseweb="popover"], [data-baseweb="menu"], [data-baseweb="calendar"] {
  background:#FFFFFF !important; color:#30251D !important;
}
[data-testid="stAlert"] { color:#30251D !important; }
[data-testid="stAlert"] p, [data-testid="stAlert"] div, [data-testid="stAlert"] span {
  color:#30251D !important; -webkit-text-fill-color:#30251D !important; opacity:1 !important;
}
[data-testid="stExpander"] details, [data-testid="stDataFrame"], [data-testid="stForm"] {
  background:#FFFFFF !important; color:#30251D !important; border-color:#E4CCB6 !important;
}
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary * {
  color:#30251D !important; -webkit-text-fill-color:#30251D !important; opacity:1 !important;
}
[data-testid="stForm"] p, [data-testid="stForm"] label, [data-testid="stForm"] span {
  color:#3B2E25 !important; -webkit-text-fill-color:#3B2E25 !important;
}
[data-testid="stMainBlockContainer"] .stCheckbox label *,
[data-testid="stMainBlockContainer"] [data-testid="stToggle"] label *,
[data-testid="stMainBlockContainer"] [role="radiogroup"] label * {
  color:#3B2E25 !important; -webkit-text-fill-color:#3B2E25 !important; opacity:1 !important;
}
.stTabs [data-baseweb="tab-list"] { gap:.25rem; }
.stTabs [data-baseweb="tab"] { border-radius:10px 10px 0 0; padding:.55rem .8rem; }
.stTabs [data-baseweb="tab"] *, [role="tab"] { color:#655347 !important; }
.stTabs [aria-selected="true"] * { color:#963D00 !important; font-weight:700 !important; }
code, pre { background:#FFF3E7 !important; color:#30251D !important; }
:focus-visible { outline:3px solid #1769AA !important; outline-offset:2px !important; }
@media (prefers-color-scheme: dark) {
  html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stMainBlockContainer"] {
    background:#FFFDF9 !important; color:#30251D !important; color-scheme:light !important;
  }
}
@media (max-width: 768px) {
  [data-testid="stSidebar"] {
    width:min(15.25rem, 63vw) !important;
    min-width:min(15.25rem, 63vw) !important;
    max-width:min(15.25rem, 63vw) !important;
  }
  [data-testid="stSidebar"] > div:first-child,
  [data-testid="stSidebar"] [data-testid="stSidebarContent"] {
    width:100% !important;
  }
  [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] {
    padding:1rem .8rem !important;
  }
  [data-testid="stSidebar"] h2 {
    font-size:.96rem !important;
    white-space:nowrap;
  }
  [data-testid="stSidebar"] [role="radiogroup"] p {
    font-size:.9rem !important;
  }
  .ops-hero { padding:1rem; border-radius:14px; }
  .ops-hero h1 { font-size:1.4rem; }
  .ops-card { min-height:86px; padding:.75rem; }
  .ops-card .value { font-size:1.25rem; }
  [data-testid="stHorizontalBlock"] { gap:.35rem; }
  [data-testid="stSidebar"] [role="radiogroup"] label { min-height:44px !important; width:100%; padding:.45rem .2rem !important; display:flex; align-items:center; }
  [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
  [data-baseweb="select"] > div, [data-testid="stDateInput"] input,
  [data-testid="stNumberInput"] input { min-height:44px !important; font-size:16px !important; }
  [data-testid="stMetric"] { min-height:84px !important; }
  [data-testid="stMainBlockContainer"] button { min-height:44px !important; }
  h1 { font-size:1.55rem !important; }
  h2 { font-size:1.3rem !important; }
  h3 { font-size:1.2rem !important; }
  .ops-badge { font-size:.82rem !important; }
  .ops-card .label, .ops-card .note { font-size:.875rem !important; }
  .ops-stat-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .review-stat-grid { grid-template-columns:repeat(4,minmax(0,1fr)); gap:.3rem; }
  .review-stat { min-height:68px; border-radius:10px; padding:.45rem .12rem; }
  .review-stat .label { font-size:.72rem; }
  .review-stat .value { font-size:1.15rem; }
  .compact-stat-grid { gap:.3rem; }
  .compact-stat { min-height:66px; border-radius:10px; padding:.4rem .12rem; }
  .compact-stat .label { font-size:.7rem; }
  .compact-stat .value { font-size:1.03rem; }
  .st-key-dashboard_quick_menu [data-testid="stHorizontalBlock"] { display:grid !important; grid-template-columns:repeat(2,minmax(0,1fr)) !important; gap:.4rem !important; }
  .st-key-dashboard_quick_menu [data-testid="column"] { width:100% !important; min-width:0 !important; flex:unset !important; }
  [data-testid="stMainBlockContainer"] { padding-left:1rem !important; padding-right:1rem !important; }
  .ops-stat .value { font-size:1.2rem; }
  .stTabs [data-baseweb="tab-list"] { overflow-x:auto; scrollbar-width:thin; }
  [data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"] { overflow-wrap:anywhere; }
  .stButton>button, .stDownloadButton>button, .stLinkButton>a { min-height:3rem; font-size:1rem !important; }
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def bootstrap() -> None:
    ensure_directories()
    init_db()
    source_count = row("SELECT COUNT(*) AS count FROM source_files")
    if source_count and source_count["count"] == 0 and list(SOURCE_DIR.glob("*.xlsx")):
        with st.spinner("기존 Spreadsheet를 처음 가져오는 중입니다…"):
            migrate(reset=False)


def rerun(message: str | None = None) -> None:
    if message:
        st.session_state["flash"] = message
    st.rerun()


def navigate(page: str, selected_key: str | None = None, selected_id: int | None = None) -> None:
    if selected_key and selected_id is not None:
        st.session_state[selected_key] = selected_id
        st.session_state.pop(f"{selected_key}_selector", None)
    st.session_state["_navigate_to"] = page
    st.session_state["_clear_quick_search"] = True
    st.rerun()


def show_flash() -> None:
    message = st.session_state.pop("flash", None)
    if message:
        st.success(message)


def hero(title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="ops-hero"><h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>',
        unsafe_allow_html=True,
    )


def compact_stats(metrics: list[tuple[str, object]], columns: int = 4) -> None:
    safe_columns = max(1, min(int(columns), 4))
    cards = "".join(
        '<div class="compact-stat">'
        f'<div class="label">{html.escape(str(label))}</div>'
        f'<div class="value">{html.escape(str(value))}</div>'
        "</div>"
        for label, value in metrics
    )
    st.markdown(
        f'<div class="compact-stat-grid" style="--stat-cols:{safe_columns}">{cards}</div>',
        unsafe_allow_html=True,
    )


def dashboard_header() -> None:
    today_label = date.today().strftime("%Y.%m.%d")
    st.markdown(
        f'<div class="ops-dashboard-head"><h1>예배 운영 대시보드</h1><span>{today_label} 기준</span></div>',
        unsafe_allow_html=True,
    )


def google_sheets_sync_bar() -> None:
    last_sync = get_app_meta("last_google_sheets_sync_at", "")
    sync_status = get_app_meta("last_google_sheets_sync_status", "연동 전")
    info_col, action_col = st.columns([0.72, 0.28])
    if last_sync:
        info_col.caption(f"Google Sheets 자료 · 마지막 업데이트 {last_sync.replace('T', ' ')[:16]}")
    elif sync_status.startswith("ERROR:"):
        info_col.caption("Google Sheets 자료 · 이전 업데이트를 완료하지 못했습니다.")
    else:
        info_col.caption("Google Sheets 자료 · 아직 업데이트하지 않았습니다.")
    if action_col.button("최신 자료 업데이트", key="google_sheets_sync", width="stretch"):
        try:
            try:
                service_account_info = dict(st.secrets["google_service_account"])
            except (FileNotFoundError, KeyError, TypeError):
                service_account_info = None
            with st.spinner("두 Google 스프레드시트의 최신 자료를 가져오는 중입니다…"):
                result = sync_google_sheets(service_account_info=service_account_info)
            processed = sum(len(item["sheets"]) for item in result["downloaded"])
            rerun(f"Google Sheets 최신 자료를 반영했습니다. 확인한 시트 {processed}개")
        except Exception as exc:
            st.error(f"Google Sheets 업데이트를 완료하지 못했습니다: {exc}")
    if sync_status.startswith("ERROR:"):
        st.warning(f"마지막 업데이트 시도는 실패했습니다. 화면에는 이전에 성공한 자료가 유지됩니다.")


def badge(text: str, tone: str = "") -> str:
    safe_tone = tone if tone in {"", "warn", "danger", "gray"} else ""
    return f'<span class="ops-badge {safe_tone}">{html.escape(str(text))}</span>'


def search_excerpt(value: str | None, term: str, width: int = 280) -> str:
    text = " ".join((value or "").split())
    if len(text) <= width:
        return text
    position = text.casefold().find(term.casefold())
    start = max(0, position - 80) if position >= 0 else 0
    end = min(len(text), start + width)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def dday(event_date: str | None) -> str:
    if not event_date:
        return "날짜 미정"
    delta = (date.fromisoformat(event_date) - date.today()).days
    if delta == 0:
        return "D-Day"
    return f"D-{delta}" if delta > 0 else f"D+{abs(delta)}"


def next_weekday(base_date: date, weekday: int) -> date:
    """Return today when it is the requested weekday, otherwise the next occurrence."""
    return base_date + timedelta(days=(weekday - base_date.weekday()) % 7)


def status_ko(value: str) -> str:
    return {
        "PLANNING": "준비중", "ACTIVE": "진행중", "COMPLETED": "종료", "CANCELLED": "취소",
        "TODO": "미완료", "IN_PROGRESS": "진행중", "DONE": "완료", "BLOCKED": "보류",
        "CURRENT": "현재 기준", "ARCHIVED": "보관됨", "SUPERSEDED": "이전 기준",
        "APPROVED": "승인", "PENDING": "검토중", "REJECTED": "보류", "CHANGED": "변경됨",
        "OPEN": "확인 필요", "RESOLVED": "처리 완료",
    }.get(value, value)


REVIEW_STATUS_LABELS = {
    "REVIEW_REQUIRED": "확인 필요",
    "IN_PROGRESS": "진행중",
    "CONFIRMED": "확인 완료",
}

REVIEW_CATEGORIES = ["예배 준비", "음향", "영상", "조명", "무대·진행", "시설·장비", "인력·일정", "자료·콘텐츠", "기타"]
REVIEW_PRIORITY_LABELS = {
    "NORMAL": "일반",
    "HIGH": "중요",
    "URGENT": "긴급",
}


def priority_ko(value: str) -> str:
    return {"HIGH": "중요", "MEDIUM": "보통", "LOW": "낮음", **REVIEW_PRIORITY_LABELS}.get(value, value)


def quality_ko(value: str) -> str:
    return {
        "Verified": "검증됨",
        "Imported": "원본 반영",
        "Needs Review": "확인 필요",
        "Unknown": "미확인",
        "Stale": "원본에서 제외",
    }.get(value, value)


@st.cache_resource(show_spinner=False)
def _cached_review_board_store(credentials_json: str) -> GoogleReviewBoardStore:
    service_account_info = json.loads(credentials_json)
    return GoogleReviewBoardStore(REVIEW_BOARD_SPREADSHEET_ID, service_account_info)


@st.cache_data(ttl=10, show_spinner=False)
def _cached_review_board_snapshot(
    spreadsheet_id: str,
    _store: GoogleReviewBoardStore,
    show_confirmed: bool,
    limit: int,
) -> dict[str, object]:
    return _store.snapshot(show_confirmed=show_confirmed, limit=limit)


def service_account_secret(name: str) -> tuple[dict[str, object] | None, str]:
    try:
        raw_credentials = st.secrets[name]
    except (FileNotFoundError, KeyError):
        return None, f"{name} Secret이 설정되지 않았습니다."
    try:
        parsed = json.loads(raw_credentials) if isinstance(raw_credentials, str) else dict(raw_credentials)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None, f"{name} Secret 형식을 확인하세요."
    if not isinstance(parsed, dict) or not parsed.get("client_email") or not parsed.get("private_key"):
        return None, f"{name}에 필수 서비스 계정 항목이 없습니다."
    return parsed, ""


def review_board_store() -> tuple[GoogleReviewBoardStore | None, str]:
    service_account_info, secret_error = service_account_secret("GOOGLE_REVIEW_BOARD_SERVICE_ACCOUNT")
    if service_account_info is None:
        return None, "게시판 영구 저장 연결정보가 아직 설정되지 않았습니다. " + secret_error
    try:
        credentials_json = json.dumps(service_account_info, ensure_ascii=False)
        return _cached_review_board_store(credentials_json), ""
    except (json.JSONDecodeError, TypeError, ReviewBoardConnectionError) as exc:
        return None, str(exc)


def shared_review_board() -> None:
    store, connection_error = review_board_store()
    if store is None:
        st.markdown("#### 팀 확인 게시판")
        st.error("Google Sheets 영구 저장소에 연결되지 않아 등록 기능을 잠시 중지했습니다.")
        st.caption(connection_error)
        return

    try:
        snapshot = _cached_review_board_snapshot(REVIEW_BOARD_SPREADSHEET_ID, store, True, 500)
    except ReviewBoardConnectionError as exc:
        st.markdown("#### 팀 확인 게시판")
        st.error("Google Sheets 영구 저장소를 읽을 수 없어 등록 기능을 잠시 중지했습니다.")
        st.caption(str(exc))
        return

    counts = {status: int(snapshot["counts"].get(status, 0)) for status in REVIEW_STATUS_LABELS}
    active_count = counts["REVIEW_REQUIRED"] + counts["IN_PROGRESS"]
    overdue_count = sum(
        1 for item in snapshot["items"]
        if item.get("status") != "CONFIRMED" and item.get("due_date") and str(item["due_date"]) < date.today().isoformat()
    )

    title_col, action_col = st.columns([0.62, 0.38])
    title_col.markdown(f"#### 팀 확인 게시판 · 미완료 {active_count}건")
    if action_col.button("↻ 새로고침", key="refresh_review_board", width="stretch"):
        _cached_review_board_snapshot.clear()
        st.rerun()
    st.caption("게시글·댓글·진행 상태는 게시판 전용 Google Sheets에 영구 저장됩니다.")

    metrics = [
        ("확인 필요", counts["REVIEW_REQUIRED"]),
        ("진행중", counts["IN_PROGRESS"]),
        ("기한 지남", overdue_count),
        ("확인 완료", counts["CONFIRMED"]),
    ]
    st.markdown(
        '<div class="review-stat-grid">'
        + "".join(
            f'<div class="review-stat"><div class="label">{label}</div><div class="value">{value}건</div></div>'
            for label, value in metrics
        )
        + "</div>",
        unsafe_allow_html=True,
    )

    status_options = {
        "미완료 전체": "OPEN",
        "확인 필요": "REVIEW_REQUIRED",
        "진행중": "IN_PROGRESS",
        "확인 완료": "CONFIRMED",
        "전체 상태": "ALL",
    }
    existing_categories = sorted({str(item.get("category") or "기타") for item in snapshot["items"]})
    category_options = ["전체", *dict.fromkeys([*REVIEW_CATEGORIES, *existing_categories])]
    priority_options = {"전체 중요도": "ALL", "긴급": "URGENT", "중요": "HIGH", "일반": "NORMAL"}
    with st.expander("검색·필터", expanded=False):
        filter_col, category_col, priority_col = st.columns(3)
        selected_status_label = filter_col.selectbox("상태", list(status_options), key="review_status_filter")
        selected_category = category_col.selectbox("분류", category_options, key="review_category_filter")
        selected_priority_label = priority_col.selectbox("중요도", list(priority_options), key="review_priority_filter")
        board_search = st.text_input(
            "게시판 검색",
            placeholder="제목, 내용, 담당자, 작성자 검색",
            key="review_board_search",
        )
        display_limit = st.selectbox("한 번에 보기", [10, 25, 50], index=1, key="review_display_limit")
    review_items = filter_review_items(
        snapshot["items"],
        status_filter=status_options[selected_status_label],
        category=selected_category,
        term=board_search,
    )
    selected_priority = priority_options[selected_priority_label]
    if selected_priority != "ALL":
        review_items = [item for item in review_items if item.get("priority") == selected_priority]
    priority_rank = {"URGENT": 0, "HIGH": 1, "NORMAL": 2}
    review_items.sort(
        key=lambda item: str(item.get("updated_at") or item.get("created_at") or ""),
        reverse=True,
    )
    review_items.sort(
        key=lambda item: (
            priority_rank.get(str(item.get("priority")), 9),
            0 if item.get("due_date") and str(item["due_date"]) < date.today().isoformat() and item.get("status") != "CONFIRMED" else 1,
            str(item.get("due_date") or "9999-12-31"),
        )
    )
    total_filtered_items = len(review_items)
    review_items = review_items[:display_limit]
    st.markdown(f"**조건에 맞는 확인사항 {total_filtered_items}건 · 현재 {len(review_items)}건 표시**")
    if not review_items:
        st.info("조건에 맞는 확인사항이 없습니다. 검색·필터를 바꾸거나 아래에서 새 항목을 추가하세요.")

    for item in review_items:
        label = REVIEW_STATUS_LABELS[item["status"]]
        priority_label = REVIEW_PRIORITY_LABELS.get(str(item.get("priority")), "일반")
        with st.expander(
            f"[{label}] {item['title']} · {item.get('category') or '기타'} · 댓글 {item['comment_count']}개",
            expanded=st.session_state.get("expanded_review_item") == str(item["id"]),
        ):
            tone = "danger" if item.get("priority") == "URGENT" else ("warn" if item.get("priority") == "HIGH" else "")
            st.markdown(
                f"{badge(item.get('category') or '기타')} {badge(priority_label, tone)}",
                unsafe_allow_html=True,
            )
            if item["description"]:
                st.write(item["description"])
            details = []
            if item.get("owner"):
                details.append(f"담당 {item['owner']}")
            if item.get("due_date"):
                due_state = "기한 지남" if str(item["due_date"]) < date.today().isoformat() and item["status"] != "CONFIRMED" else "기한"
                details.append(f"{due_state} {item['due_date']}")
            if details:
                st.caption(" · ".join(details))
            st.caption(
                f"등록 {item['created_by']} · {str(item['created_at'])[:16].replace('T', ' ')}"
                + (f" · 최근 확인 {item['updated_by']}" if item["updated_by"] else "")
            )
            comments = snapshot["comments"].get(str(item["id"]), [])
            comment_by_id = {str(comment.get("comment_id")): comment for comment in comments}
            for comment in comments:
                with st.container(border=True):
                    parent = comment_by_id.get(str(comment.get("parent_comment_id") or ""))
                    if parent:
                        st.caption(f"↳ {parent.get('author') or '이름 없음'}님의 댓글에 답글")
                    status_note = REVIEW_STATUS_LABELS.get(comment["status_change"], "")
                    st.caption(
                        f"{comment['author']} · {str(comment['created_at'])[:16].replace('T', ' ')}"
                        + (f" · {status_note}" if status_note else "")
                    )
                    st.write(comment["body"])

            with st.form(f"review_reply_{item['id']}", clear_on_submit=True):
                reply_author = st.text_input(
                    "작성자",
                    value=st.session_state.get("operator_name", ""),
                    placeholder="이름",
                    key=f"review_author_{item['id']}",
                )
                reply_body = st.text_area(
                    "댓글 또는 답글",
                    placeholder="확인한 내용이나 진행 상황을 남겨주세요.",
                    key=f"review_body_{item['id']}",
                )
                parent_options = {"게시글에 새 댓글": ""}
                for comment in comments:
                    body_preview = " ".join(str(comment.get("body") or "").split())[:28]
                    comment_id = str(comment.get("comment_id") or "")
                    parent_options[f"{comment.get('author') or '이름 없음'} · {body_preview} · {comment_id[:6]}"] = comment_id
                parent_label = st.selectbox(
                    "답글 대상",
                    list(parent_options),
                    key=f"review_parent_{item['id']}",
                    help="기존 댓글을 선택하면 그 댓글에 답글로 연결됩니다.",
                )
                statuses = list(REVIEW_STATUS_LABELS)
                next_status = st.selectbox(
                    "댓글 등록 후 상태",
                    statuses,
                    index=statuses.index(item["status"]),
                    format_func=lambda value: REVIEW_STATUS_LABELS[value],
                    key=f"review_status_{item['id']}",
                )
                if st.form_submit_button("댓글 등록", type="primary", width="stretch"):
                    try:
                        store.add_comment(
                            str(item["id"]),
                            reply_author,
                            reply_body,
                            next_status,
                            parent_comment_id=parent_options[parent_label] or None,
                        )
                        _cached_review_board_snapshot.clear()
                        st.session_state["expanded_review_item"] = str(item["id"])
                        rerun("댓글과 진행 상태를 반영했습니다.")
                    except (ValueError, ReviewBoardConnectionError) as exc:
                        st.error(str(exc))

    st.divider()
    if st.button("＋ 새 확인사항 작성", key="open_review_item_form", type="primary", width="stretch"):
        st.session_state["show_review_item_form"] = not st.session_state.get("show_review_item_form", False)

    if st.session_state.get("show_review_item_form", False):
        with st.form("new_review_item", clear_on_submit=True, border=True):
            st.markdown("**새 확인사항 등록**")
            new_title = st.text_input("제목", placeholder="무엇을 확인해야 하나요?")
            new_description = st.text_area("내용", placeholder="상황과 확인할 내용을 적어주세요.")
            classify_col, priority_col = st.columns(2)
            new_category = classify_col.selectbox("분류", REVIEW_CATEGORIES)
            new_priority = priority_col.selectbox(
                "중요도",
                list(REVIEW_PRIORITY_LABELS),
                format_func=lambda value: REVIEW_PRIORITY_LABELS[value],
            )
            owner_col, due_col = st.columns(2)
            new_owner = owner_col.text_input("담당자", placeholder="미정이면 비워두세요")
            new_due = due_col.date_input("확인 기한", value=None)
            new_author = st.text_input(
                "작성자",
                value=st.session_state.get("operator_name", ""),
                placeholder="이름",
            )
            submitted = st.form_submit_button("등록", type="primary", width="stretch")
            if submitted:
                try:
                    store.create_item(
                        new_title,
                        new_description,
                        new_author,
                        new_category,
                        new_priority,
                        new_owner,
                        new_due.isoformat() if new_due else "",
                    )
                    _cached_review_board_snapshot.clear()
                    st.session_state["show_review_item_form"] = False
                    rerun("새 확인사항을 등록했습니다.")
                except (ValueError, ReviewBoardConnectionError) as exc:
                    st.error(str(exc))

    with st.expander("게시판 데이터 관리"):
        st.caption("백업에는 게시글·댓글·상태 변경이력이 포함됩니다.")
        if st.button("최신 게시판 백업 준비", key="prepare_review_board_backup", width="stretch"):
            try:
                st.session_state["review_board_backup_payload"] = store.export_json()
            except ReviewBoardConnectionError as exc:
                st.error(str(exc))
        backup_payload = st.session_state.get("review_board_backup_payload")
        backup_col, sheet_col = st.columns(2)
        if backup_payload:
            backup_col.download_button(
                "게시판 백업 다운로드",
                backup_payload,
                file_name=f"joyful_review_board_{date.today().isoformat()}.json",
                mime="application/json",
                width="stretch",
            )
        sheet_col.link_button(
            "Google Sheets에서 보기",
            f"https://docs.google.com/spreadsheets/d/{REVIEW_BOARD_SPREADSHEET_ID}/edit",
            width="stretch",
        )


def sidebar() -> str:
    with st.sidebar:
        st.markdown(f"## ⛪ {APP_TITLE}")
        st.caption("예배 운영 · 지식관리")
        st.markdown("---")
        menu_items = ["대시보드", "팀 확인", "행사", "매뉴얼", "예배 인원 현황", "교회력", "전체 검색", "결정·운영로그", "보관함", "데이터·백업"]
        menu_labels = {
            "대시보드": "⌂  대시보드",
            "팀 확인": "✓  팀 확인",
            "교회력": "▣  교회력",
            "행사": "◆  행사",
            "매뉴얼": "▤  매뉴얼",
            "결정·운영로그": "✎  결정·운영 기록",
            "예배 인원 현황": "▥  예배 인원 현황",
            "전체 검색": "⌕  전체 검색",
            "보관함": "□  보관함",
            "데이터·백업": "⚙  데이터·백업",
        }
        pending_nav = st.session_state.pop("_navigate_to", None)
        if pending_nav in menu_items:
            st.session_state["main_nav"] = pending_nav
        nav = st.radio(
            "메뉴",
            menu_items,
            label_visibility="collapsed",
            key="main_nav",
            format_func=lambda value: menu_labels[value],
        )
        st.markdown("---")
        if st.session_state.pop("_clear_quick_search", False):
            st.session_state["quick_search"] = ""
        quick = st.text_input("빠른 검색", placeholder="세례, 성찬, 마이크…", key="quick_search")
        if quick:
            st.session_state["search_term"] = quick
            nav = "전체 검색"
        with st.expander("내 이름 설정"):
            st.text_input(
                "게시판 작성자 이름",
                placeholder="예: 홍길동",
                key="operator_name",
                help="이 브라우저를 사용하는 동안 게시글과 댓글 작성자에 자동 입력됩니다.",
            )
        st.caption("원본 Sheets 읽기 전용 · 게시판 영구 저장")
        st.caption(f"버전 {APP_VERSION}")
        return nav


def review_board_page() -> None:
    hero("팀 확인", "확인할 일을 분류하고 담당·기한·진행 상태를 함께 관리합니다.")
    shared_review_board()


def review_board_summary() -> None:
    """대시보드에서는 게시판의 핵심 수치와 우선 항목만 보여줍니다."""
    store, connection_error = review_board_store()
    st.subheader("팀 확인")
    if store is None:
        st.info("팀 게시판 영구 저장소가 아직 연결되지 않았습니다.")
        st.caption(connection_error)
        return
    try:
        snapshot = _cached_review_board_snapshot(REVIEW_BOARD_SPREADSHEET_ID, store, True, 500)
    except ReviewBoardConnectionError as exc:
        st.info("팀 게시판을 잠시 읽을 수 없습니다.")
        st.caption(str(exc))
        return

    items = snapshot["items"]
    counts = snapshot["counts"]
    today_text = date.today().isoformat()
    overdue = sum(
        1 for item in items
        if item.get("status") != "CONFIRMED" and item.get("due_date") and str(item["due_date"]) < today_text
    )
    compact_stats([
        ("확인 필요", f"{counts.get('REVIEW_REQUIRED', 0)}건"),
        ("진행중", f"{counts.get('IN_PROGRESS', 0)}건"),
        ("기한 지남", f"{overdue}건"),
    ], columns=3)

    review_required_items = [item for item in items if item.get("status") == "REVIEW_REQUIRED"]
    review_required_items.sort(
        key=lambda item: (
            0 if item.get("priority") == "URGENT" else (1 if item.get("priority") == "HIGH" else 2),
            str(item.get("due_date") or "9999-12-31"),
            str(item.get("updated_at") or item.get("created_at") or ""),
        )
    )
    review_required_count = len(review_required_items)
    if review_required_count:
        if st.button(
            f"확인 필요 {review_required_count}건 바로 확인",
            key="open_required_review_items",
            type="primary",
            width="stretch",
        ):
            st.session_state["review_status_filter"] = "확인 필요"
            st.session_state["expanded_review_item"] = str(review_required_items[0]["id"])
            navigate("팀 확인")

    urgent = [item for item in items if item.get("status") != "CONFIRMED" and item.get("priority") in {"URGENT", "HIGH"}]
    urgent.sort(
        key=lambda item: (
            0 if item.get("priority") == "URGENT" else 1,
            str(item.get("due_date") or "9999-12-31"),
            str(item.get("updated_at") or item.get("created_at") or ""),
        )
    )
    for item in urgent[:3]:
        meta = " · ".join(filter(None, [priority_ko(str(item.get("priority"))), str(item.get("category") or "기타"), f"담당 {item['owner']}" if item.get("owner") else "", f"기한 {item['due_date']}" if item.get("due_date") else ""]))
        st.markdown(f"**{item['title']}**  \n{meta}")
    if not urgent:
        st.caption("긴급·중요 확인사항이 없습니다.")
    if st.button("팀 확인 게시판 전체 보기", key="open_full_review_board", width="stretch"):
        navigate("팀 확인")


def dashboard_page() -> None:
    dashboard_header()
    today_date = date.today()
    today = today_date.isoformat()
    week_end = (today_date + timedelta(days=7)).isoformat()
    upcoming = rows(
        "SELECT * FROM events WHERE archived_at IS NULL AND event_date>=? AND status NOT IN ('COMPLETED','CANCELLED') ORDER BY event_date LIMIT 4",
        (today,),
    )
    action_tasks = rows(
        "SELECT tasks.*, events.title AS event_title FROM tasks JOIN events ON events.id=tasks.event_id "
        "WHERE tasks.archived_at IS NULL AND events.archived_at IS NULL AND events.status NOT IN ('COMPLETED','CANCELLED') "
        "AND tasks.status<>'DONE' AND ((tasks.due_date IS NOT NULL AND tasks.due_date<=?) OR tasks.priority='HIGH') "
        "ORDER BY CASE WHEN tasks.due_date<? THEN 0 WHEN tasks.due_date=? THEN 1 ELSE 2 END, "
        "CASE tasks.priority WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, tasks.due_date LIMIT 3",
        (week_end, today, today),
    )
    action_count = row(
        "SELECT COUNT(*) AS count FROM tasks JOIN events ON events.id=tasks.event_id "
        "WHERE tasks.archived_at IS NULL AND events.archived_at IS NULL AND events.status NOT IN ('COMPLETED','CANCELLED') "
        "AND tasks.status<>'DONE' AND ((tasks.due_date IS NOT NULL AND tasks.due_date<=?) OR tasks.priority='HIGH')",
        (week_end,),
    )["count"]
    overdue_count = row(
        "SELECT COUNT(*) AS count FROM tasks JOIN events ON events.id=tasks.event_id "
        "WHERE tasks.archived_at IS NULL AND events.archived_at IS NULL AND events.status NOT IN ('COMPLETED','CANCELLED') "
        "AND tasks.status<>'DONE' AND tasks.due_date IS NOT NULL AND tasks.due_date<?",
        (today,),
    )["count"]
    blocked_count = row(
        "SELECT COUNT(*) AS count FROM tasks JOIN events ON events.id=tasks.event_id "
        "WHERE tasks.archived_at IS NULL AND events.archived_at IS NULL AND events.status NOT IN ('COMPLETED','CANCELLED') AND tasks.status='BLOCKED'"
    )["count"]
    ownerless_high = row(
        "SELECT COUNT(*) AS count FROM tasks JOIN events ON events.id=tasks.event_id "
        "WHERE tasks.archived_at IS NULL AND events.archived_at IS NULL AND events.status NOT IN ('COMPLETED','CANCELLED') "
        "AND tasks.status<>'DONE' AND tasks.priority='HIGH' AND COALESCE(TRIM(tasks.owner),'')=''"
    )["count"]
    recheck_count = row("SELECT COUNT(*) AS count FROM operation_logs WHERE archived_at IS NULL AND needs_recheck=1")["count"]
    needs_review = row("SELECT COUNT(*) AS count FROM unresolved_imports WHERE status='OPEN' AND quality='Needs Review'")["count"]
    sunday_date = next_weekday(today_date, 6)
    friday_date = next_weekday(today_date, 4)
    calendar_items = rows(
        "SELECT * FROM church_calendar_events WHERE archived_at IS NULL AND status<>'CANCELLED' AND start_date>=? "
        "ORDER BY start_date,id LIMIT 6",
        (today,),
    )

    st.subheader("다음 정기예배")
    worship_cards = [
        ("주일예배", dday(sunday_date.isoformat()), sunday_date.strftime("%Y.%m.%d · 일요일")),
        ("금요예배", dday(friday_date.isoformat()), friday_date.strftime("%Y.%m.%d · 금요일")),
    ]
    worship_html = '<div class="ops-card-grid">' + "".join(
        f'<div class="ops-card"><div class="label">{label}</div><div class="value">{value}</div><div class="note">{note}</div></div>'
        for label, value, note in worship_cards
    ) + "</div>"
    st.markdown(worship_html, unsafe_allow_html=True)

    st.markdown("#### 자주 쓰는 메뉴")
    quick_manual_rows = rows(
        "SELECT id,source_sheet FROM manuals WHERE status='CURRENT' AND archived_at IS NULL "
        "AND source_sheet IN ('주일 세팅 타임테이블','금요집회 세팅 타임테이블','항시 체크 비품')"
    )
    quick_manual_ids = {item["source_sheet"]: item["id"] for item in quick_manual_rows}
    quick_actions = [
        ("주일 준비", "주일 세팅 타임테이블", "매뉴얼"),
        ("금요 준비", "금요집회 세팅 타임테이블", "매뉴얼"),
        ("상시 비품", "항시 체크 비품", "매뉴얼"),
        ("예배 인원", None, "예배 인원 현황"),
    ]
    with st.container(key="dashboard_quick_menu"):
        quick_cols = st.columns(4)
        for column, (label, source_sheet, target_page) in zip(quick_cols, quick_actions):
            if column.button(label, key=f"quick_{target_page}_{source_sheet or 'attendance'}", width="stretch"):
                if source_sheet and quick_manual_ids.get(source_sheet):
                    navigate("매뉴얼", "selected_manual", quick_manual_ids[source_sheet])
                else:
                    navigate(target_page)

    st.divider()
    st.subheader("다가오는 교회력")
    if calendar_items:
        calendar_html = '<div class="ops-list">' + "".join(
            '<div class="ops-list-item">'
            f'<div class="meta">{html.escape(str(item["start_date"]))} · {html.escape(dday(item["start_date"]))}</div>'
            f'<div class="title">{html.escape(str(item["title"]))}</div>'
            + (f'<div class="note">{html.escape(str(item["location"]))}</div>' if item["location"] else "")
            + "</div>"
            for item in calendar_items[:3]
        ) + "</div>"
        st.markdown(calendar_html, unsafe_allow_html=True)
        if st.button("교회력 전체 보기", key="dashboard_open_calendar", width="stretch"):
            navigate("교회력")
    else:
        calendar_note, calendar_action = st.columns([.78, .22])
        calendar_note.info("연동된 교회력 일정이 없습니다. Google Calendar를 연결하면 가까운 일정부터 표시됩니다.")
        if calendar_action.button("캘린더 연결", width="stretch"):
            navigate("교회력")

    st.divider()
    st.subheader(f"지금 할 일 · {action_count}건")
    if not action_tasks:
        st.success("7일 안에 처리할 준비업무가 없습니다.")
    for task in action_tasks:
        is_overdue = bool(task["due_date"] and task["due_date"] < today)
        due_label = f"기한 지남 · {task['due_date']}" if is_overdue else (task["due_date"] or "기한 미정")
        button_label = f"{task['title']}  ·  {task['event_title']}  ·  {due_label}"
        if st.button(button_label, key=f"dashboard_task_{task['id']}", width="stretch"):
            navigate("행사", "selected_event", task["event_id"])

    st.divider()
    review_board_summary()

    st.divider()
    st.subheader("다가오는 특별행사")
    if not upcoming:
        st.info("등록된 다음 행사가 없습니다.")
        if st.button("다음 행사 만들기", type="primary", width="stretch"):
            navigate("행사")
    for event in upcoming:
        ready = readiness(event["id"])
        button_label = f"{event['title']}  ·  {dday(event['event_date'])}  ·  준비도 {ready['percent']}%"
        if st.button(button_label, key=f"dashboard_event_{event['id']}", width="stretch"):
            navigate("행사", "selected_event", event["id"])

    st.divider()
    with st.expander("시스템 자동 점검 보기"):
        alerts = [
            ("기한 지남", f"{overdue_count}건"),
            ("보류 업무", f"{blocked_count}건"),
            ("담당자 미정", f"{ownerless_high}건"),
            ("재확인 로그", f"{recheck_count}건"),
        ]
        compact_stats(alerts, columns=4)
        if needs_review:
            note_col, button_col = st.columns([.82, .18])
            note_col.caption(f"원본 이관 데이터 중 사람이 확인할 항목이 {needs_review}건 있습니다. 데이터 관리 화면에서 검토합니다.")
            if button_col.button("데이터 확인", width="stretch"):
                navigate("데이터·백업")

    with st.expander("관리자 · 원본 데이터 업데이트", expanded=False):
        st.caption("Google Sheets 원본을 갱신할 때만 사용합니다. 일반 사용자는 누르지 않아도 됩니다.")
        google_sheets_sync_bar()


def event_detail(event_id: int) -> None:
    event = row(
        "SELECT events.*,event_templates.title AS template_title FROM events LEFT JOIN event_templates ON event_templates.id=events.event_template_id WHERE events.id=?",
        (event_id,),
    )
    if not event:
        st.error("행사를 찾을 수 없습니다.")
        return
    ready = readiness(event_id)
    st.markdown(f"## {event['title']}")
    st.markdown(
        f"{badge(status_ko(event['status']))} {badge(dday(event['event_date']), 'warn' if event['status'] != 'COMPLETED' else 'gray')} "
        f"{badge(quality_ko(event['data_quality']), 'warn' if event['data_quality']=='Needs Review' else '')}",
        unsafe_allow_html=True,
    )
    compact_stats([
        ("준비도", f"{ready['percent']}%"),
        ("완료", f"{ready['done']}건"),
        ("미완료", f"{ready['open']}건"),
        ("중요 미완료", f"{ready['high_open']}건"),
    ], columns=4)

    checklist, overview, history, knowledge, review_tab = st.tabs(["체크리스트", "기본정보", "과거 참고", "관련 자료", "회고"])
    with overview:
        left, right = st.columns([1.5, 1])
        with left:
            st.markdown(f"**날짜**  \n{event['event_date'] or '미정'}")
            st.markdown(f"**카테고리**  \n{event['category'] or '-'}")
            st.markdown(f"**담당자**  \n{event['owner'] or '미지정'}")
            st.markdown(f"**설명**  \n{event['description'] or '기록 없음'}")
            st.caption(f"출처: {event['source'] or '사용자 입력'} · 템플릿: {event['template_title'] or '없음'}")
        with right:
            status_options = ["PLANNING", "ACTIVE", "COMPLETED", "CANCELLED"]
            selected = st.selectbox("행사 상태", status_options, index=status_options.index(event["status"]) if event["status"] in status_options else 0, format_func=status_ko, key=f"status_{event_id}")
            if st.button("상태 저장", key=f"save_status_{event_id}", width="stretch"):
                update_event_status(event_id, selected)
                rerun("행사 상태를 변경했습니다.")
            with st.expander("이 행사를 기준으로 다음 행사 만들기"):
                with st.form(f"clone_{event_id}"):
                    new_title = st.text_input("새 행사명", value=event["title"])
                    new_date = st.date_input("새 행사 날짜", value=date.today())
                    if st.form_submit_button("이전 행사 기준으로 생성", width="stretch"):
                        new_id = clone_event(event_id, new_title, new_date)
                        st.session_state["selected_event"] = new_id
                        rerun("체크리스트 구조를 복제해 새 행사를 만들었습니다.")
            if st.button("행사 보관", type="secondary", key=f"archive_event_{event_id}", width="stretch"):
                archive_entity("events", event_id)
                st.session_state.pop("selected_event", None)
                rerun("행사를 보관함으로 이동했습니다.")

    with checklist:
        task_rows = rows(
            "SELECT tasks.*,dep.title AS dependency_title,dep.status AS dependency_status FROM tasks "
            "LEFT JOIN tasks dep ON dep.id=tasks.depends_on WHERE tasks.event_id=? AND tasks.archived_at IS NULL "
            "ORDER BY CASE tasks.priority WHEN 'HIGH' THEN 1 WHEN 'MEDIUM' THEN 2 ELSE 3 END, tasks.due_date, tasks.id",
            (event_id,),
        )
        if not task_rows:
            st.info("체크리스트가 없습니다. 아래에서 업무를 추가할 수 있습니다.")
        for task in task_rows:
            completed = task["status"] == "DONE"
            with st.container(border=True):
                changed = st.checkbox(
                    task["title"],
                    value=completed,
                    key=f"task_{task['id']}",
                    help="체크하면 완료 상태로 저장됩니다.",
                )
                if changed != completed:
                    set_task_status(task["id"], "DONE" if changed else "TODO")
                    rerun("체크리스트 상태를 반영했습니다.")
                due_text = task["due_date"] or task["source_timing"] or "기한 미정"
                st.markdown(
                    f"{badge(priority_ko(task['priority']), 'danger' if task['priority'] == 'HIGH' else '')} "
                    f"{badge(due_text, 'gray')}",
                    unsafe_allow_html=True,
                )
                if task["description"]:
                    st.caption(task["description"][:300])
                if task["depends_on"] and task["dependency_status"] != "DONE":
                    st.warning(f"선행 업무 미완료: {task['dependency_title']}", icon="⚠️")
        with st.expander("체크리스트 업무 추가"):
            with st.form(f"add_task_{event_id}"):
                title = st.text_input("업무명")
                description = st.text_area("설명")
                owner = st.text_input("담당자")
                priority = st.selectbox("중요도", ["HIGH", "MEDIUM", "LOW"], index=1, format_func=priority_ko)
                due = st.date_input("기한", value=event["event_date"] and date.fromisoformat(event["event_date"]) or date.today())
                dependencies = {"없음": None, **{item["title"]: item["id"] for item in task_rows}}
                dependency_label = st.selectbox("선행 업무", list(dependencies))
                if st.form_submit_button("업무 추가"):
                    if not title.strip():
                        st.error("업무명을 입력하세요.")
                    else:
                        add_task(event_id, title, description, owner, priority, due.isoformat(), dependencies[dependency_label])
                        rerun("업무를 추가했습니다.")

    with history:
        previous = row("SELECT * FROM events WHERE id=?", (event["previous_event_id"],)) if event["previous_event_id"] else None
        if not previous:
            st.info("연결된 이전 동일 행사가 없습니다. 행사명 계열이 같을 때 새 행사 생성/복제 시 자동 연결됩니다.")
        else:
            st.markdown(f"### 이전 행사: {previous['title']}")
            prev_ready = readiness(previous["id"])
            curr_att = row("SELECT AVG(total_count) AS avg FROM attendance WHERE event_id=?", (event_id,))["avg"]
            prev_att = row("SELECT AVG(total_count) AS avg FROM attendance WHERE event_id=?", (previous["id"],))["avg"]
            comparison = pd.DataFrame([
                {"항목": "행사일", "이전": previous["event_date"], "현재": event["event_date"]},
                {"항목": "체크리스트 수", "이전": prev_ready["total"], "현재": ready["total"]},
                {"항목": "완료율", "이전": f"{prev_ready['percent']}%", "현재": f"{ready['percent']}%"},
                {"항목": "연결 참석 평균", "이전": f"{prev_att:.1f}명" if prev_att else "없음", "현재": f"{curr_att:.1f}명" if curr_att else "없음"},
            ])
            st.dataframe(comparison, hide_index=True, width="stretch")
            previous_review = row("SELECT * FROM event_reviews WHERE event_id=?", (previous["id"],))
            if previous_review:
                st.markdown("#### 지난 행사에서 발생했던 문제")
                issue_text = previous_review["problems"] or previous_review["must_apply_next"] or "기록 없음"
                st.warning(issue_text)
                if issue_text != "기록 없음" and st.button("이번 체크리스트에 추가", key=f"carry_{event_id}"):
                    carry_review_issue(previous_review["id"], event_id, issue_text)
                    rerun("지난 문제를 이번 행사 중요업무로 추가했습니다.")
                st.markdown("#### 개선사항")
                st.write(previous_review["improvements"] or "기록 없음")
            else:
                st.caption("이전 행사 회고가 없습니다.")

    with knowledge:
        manuals = rows(
            "SELECT manuals.* FROM manuals JOIN event_templates ON event_templates.manual_id=manuals.id WHERE event_templates.id=?",
            (event["event_template_id"],),
        ) if event["event_template_id"] else []
        decisions = rows("SELECT * FROM decisions WHERE event_id=? AND archived_at IS NULL ORDER BY decided_at DESC", (event_id,))
        logs = rows("SELECT * FROM operation_logs WHERE event_id=? AND archived_at IS NULL ORDER BY occurred_at DESC", (event_id,))
        refs = rows("SELECT * FROM references_data WHERE event_id=? AND archived_at IS NULL", (event_id,))
        st.markdown("#### 관련 매뉴얼")
        if not manuals:
            st.caption("연결된 매뉴얼이 없습니다.")
        for item in manuals:
            st.markdown(f"- **{item['title']}** · v{item['version']} · {item['current_standard'] or '현재 기준 미기록'}")
        st.markdown("#### 결정 및 운영 로그")
        for item in decisions:
            st.markdown(f"- **결정:** {item['title']} — {item['reason'] or '이유 미기록'}")
        for item in logs:
            st.markdown(f"- **{item['log_type']}:** {item['title']} — {item['result'] or item['description'] or ''}")
        st.markdown("#### 참고자료")
        for item in refs:
            st.markdown(f"- [{item['title']}]({item['url']}) {item['reference_time'] or ''}")
        with st.expander("참고 URL 추가"):
            with st.form(f"ref_{event_id}"):
                ref_title = st.text_input("제목")
                ref_url = st.text_input("URL")
                ref_type = st.selectbox("유형", ["YouTube", "Google Drive", "Google Sheets", "웹 URL", "기타"])
                ref_time = st.text_input("참고 시점", placeholder="예: 42:13")
                ref_desc = st.text_area("설명")
                if st.form_submit_button("참고자료 추가"):
                    if ref_title and ref_url:
                        add_reference_record({"title": ref_title, "url": ref_url, "ref_type": ref_type, "reference_time": ref_time, "description": ref_desc, "event_id": event_id})
                        rerun("참고자료를 연결했습니다.")
                    else:
                        st.error("제목과 URL을 입력하세요.")

    with review_tab:
        review = row("SELECT * FROM event_reviews WHERE event_id=?", (event_id,)) or {}
        with st.form(f"review_{event_id}"):
            went_well = st.text_area("잘된 점", value=review.get("went_well") or "")
            problems = st.text_area("문제", value=review.get("problems") or "")
            improvements = st.text_area("개선점", value=review.get("improvements") or "")
            must_apply = st.text_area("다음 행사에서 반드시 반영", value=review.get("must_apply_next") or "")
            notes = st.text_area("기타 기록", value=review.get("notes") or "")
            if st.form_submit_button("회고 저장", type="primary"):
                save_review(event_id, {"went_well": went_well, "problems": problems, "improvements": improvements, "must_apply_next": must_apply, "notes": notes})
                rerun("회고를 저장했습니다. 다음 동일 행사에서 자동으로 표시됩니다.")


def events_page() -> None:
    hero("행사", "반복되는 특별예배의 준비·기록·회고를 연결합니다.")
    list_tab, create_tab, templates_tab = st.tabs(["행사 목록", "새 행사", "체크리스트 템플릿"])
    with list_tab:
        active = rows(
            "SELECT * FROM events WHERE archived_at IS NULL ORDER BY "
            "CASE status WHEN 'ACTIVE' THEN 0 WHEN 'PLANNING' THEN 1 WHEN 'COMPLETED' THEN 2 ELSE 3 END, "
            "CASE WHEN event_date>=date('now','localtime') THEN 0 ELSE 1 END, "
            "CASE WHEN event_date>=date('now','localtime') THEN event_date END ASC, event_date DESC, id DESC"
        )
        if not active:
            st.info("등록된 행사가 없습니다.")
        else:
            status_col, category_col = st.columns(2)
            event_status_options = {"전체 상태": "ALL", "준비중": "PLANNING", "진행중": "ACTIVE", "종료": "COMPLETED"}
            selected_status_label = status_col.selectbox("상태", list(event_status_options), key="event_status_filter")
            event_categories = ["전체", *sorted({str(item["category"] or "기타") for item in active})]
            selected_event_category = category_col.selectbox("분류", event_categories, key="event_category_filter")
            event_search = st.text_input("행사 검색", placeholder="행사명이나 담당자", key="event_search").strip().casefold()
            filtered_active = []
            for item in active:
                if event_status_options[selected_status_label] != "ALL" and item["status"] != event_status_options[selected_status_label]:
                    continue
                if selected_event_category != "전체" and str(item["category"] or "기타") != selected_event_category:
                    continue
                if event_search and event_search not in f"{item['title']} {item['owner'] or ''} {item['description'] or ''}".casefold():
                    continue
                filtered_active.append(item)
            if not filtered_active:
                st.info("조건에 맞는 행사가 없습니다.")
            else:
                options = {f"{item['event_date'] or '날짜 미정'} · {item['title']} · {status_ko(item['status'])}": item["id"] for item in filtered_active}
                event_ids = list(options.values())
                requested_event = st.session_state.get("selected_event")
                selected_index = event_ids.index(requested_event) if requested_event in event_ids else 0
                selected_label = st.selectbox("행사 선택", list(options), index=selected_index, key="selected_event_selector")
                st.session_state["selected_event"] = options[selected_label]
                event_detail(options[selected_label])
    with create_tab:
        templates = rows("SELECT * FROM event_templates WHERE status='CURRENT' ORDER BY category,title")
        template_map = {"템플릿 없음": None, **{f"{item['title']} ({item['category']})": item["id"] for item in templates}}
        with st.form("create_event"):
            title = st.text_input("행사명", placeholder="예: 2027 기도의 승부")
            event_date = st.date_input("행사 날짜", value=date.today())
            category = st.selectbox("카테고리", ["특별예배", "특별순서", "정기예배", "행사", "기타"])
            template_label = st.selectbox("체크리스트 템플릿", list(template_map))
            owner = st.text_input("담당자")
            description = st.text_area("메모")
            if st.form_submit_button("행사 생성", type="primary"):
                if not title.strip():
                    st.error("행사명을 입력하세요.")
                else:
                    event_id = create_event(title, event_date, category, template_map[template_label], owner, description)
                    st.session_state["selected_event"] = event_id
                    rerun("행사를 생성하고 템플릿 체크리스트를 적용했습니다.")
    with templates_tab:
        templates = rows(
            "SELECT event_templates.*,COUNT(task_templates.id) AS task_count,SUM(CASE WHEN task_templates.due_offset IS NULL THEN 1 ELSE 0 END) AS unresolved_count "
            "FROM event_templates LEFT JOIN task_templates ON task_templates.event_template_id=event_templates.id AND task_templates.data_quality<>'Stale' "
            "WHERE event_templates.status='CURRENT' GROUP BY event_templates.id ORDER BY event_templates.category,event_templates.title"
        )
        template_frame = pd.DataFrame(templates)[
            ["title", "category", "task_count", "unresolved_count", "source_sheet", "data_quality"]
        ].rename(columns={
            "title": "템플릿명",
            "category": "분류",
            "task_count": "업무 수",
            "unresolved_count": "일정 확인 필요",
            "source_sheet": "원본 시트",
            "data_quality": "데이터 상태",
        })
        template_frame["데이터 상태"] = template_frame["데이터 상태"].map(quality_ko)
        st.dataframe(
            template_frame,
            hide_index=True,
            width="stretch",
            height=320,
        )
        with st.expander("새 템플릿 만들기"):
            manuals = rows("SELECT id,title FROM manuals WHERE status='CURRENT' ORDER BY title")
            manual_map = {"연결 안 함": None, **{item["title"]: item["id"] for item in manuals}}
            with st.form("new_template"):
                title = st.text_input("템플릿명")
                category = st.text_input("카테고리", value="특별예배")
                description = st.text_area("설명")
                manual_label = st.selectbox("관련 매뉴얼", list(manual_map))
                if st.form_submit_button("템플릿 생성"):
                    if title:
                        create_event_template(title, category, description, manual_map[manual_label])
                        rerun("체크리스트 템플릿을 생성했습니다.")
        if templates:
            with st.expander("템플릿에 업무 추가"):
                template_map = {item["title"]: item["id"] for item in templates}
                with st.form("new_task_template"):
                    template_label = st.selectbox("템플릿", list(template_map))
                    task_title = st.text_input("업무명")
                    task_description = st.text_area("설명")
                    source_timing = st.text_input("준비시점 표기", placeholder="예: D-14")
                    due_offset = st.number_input("행사일 기준 일수", value=-7, step=1)
                    priority = st.selectbox("중요도", ["HIGH", "MEDIUM", "LOW"], index=1, format_func=priority_ko)
                    owner = st.text_input("기본 담당자")
                    if st.form_submit_button("템플릿 업무 추가"):
                        if task_title:
                            add_task_template(template_map[template_label], task_title, task_description, source_timing, int(due_offset), priority, owner)
                            rerun("템플릿 업무를 추가했습니다.")


def manuals_page() -> None:
    hero("매뉴얼", "분류와 검색으로 필요한 준비 내용을 빠르게 찾습니다.")
    current, create_tab = st.tabs(["현재 매뉴얼", "새 매뉴얼"])
    with current:
        manuals = rows(
            "SELECT * FROM manuals WHERE status='CURRENT' AND archived_at IS NULL ORDER BY "
            "CASE source_sheet WHEN '주일 세팅 타임테이블' THEN 0 WHEN '금요집회 세팅 타임테이블' THEN 1 "
            "WHEN '항시 체크 비품' THEN 2 ELSE 3 END, category,title"
        )
        if not manuals:
            st.info("현재 매뉴얼이 없습니다.")
            return
        category_options = ["전체", *sorted({str(item["category"] or "기타") for item in manuals})]
        intro_col, reset_col = st.columns([.78, .22])
        intro_col.markdown("### 매뉴얼 찾기")
        if reset_col.button("↺ 처음으로", width="stretch", help="분류·검색·선택을 초기화합니다."):
            st.session_state["manual_category_filter"] = "전체"
            st.session_state["manual_search"] = ""
            st.session_state.pop("selected_manual", None)
            st.session_state.pop("selected_manual_selector", None)
            st.rerun()
        filter_col, search_col = st.columns([.34, .66])
        selected_category = filter_col.selectbox("분류", category_options, key="manual_category_filter")
        manual_search = search_col.text_input(
            "매뉴얼 검색",
            placeholder="예: 주일, 성찬, 카메라, 비품",
            key="manual_search",
        ).strip().casefold()
        filtered_manuals = []
        for item in manuals:
            if selected_category != "전체" and str(item["category"] or "기타") != selected_category:
                continue
            searchable = " ".join(
                str(item.get(field) or "")
                for field in ("title", "category", "current_standard", "source_sheet")
            ).casefold()
            if manual_search and manual_search not in searchable:
                continue
            filtered_manuals.append(item)

        requested_manual = st.session_state.get("selected_manual")
        if requested_manual and requested_manual not in {item["id"] for item in filtered_manuals}:
            requested = next((item for item in manuals if item["id"] == requested_manual), None)
            if requested:
                filtered_manuals = [requested, *filtered_manuals]
        if not filtered_manuals:
            st.info("조건에 맞는 매뉴얼이 없습니다. 분류를 '전체'로 바꾸거나 검색어를 줄여보세요.")
            return

        manual_map = {f"[{item['category']}] {item['title']}": item["id"] for item in filtered_manuals}
        manual_ids = list(manual_map.values())
        selected_index = manual_ids.index(requested_manual) if requested_manual in manual_ids else 0
        selected = st.selectbox("매뉴얼 선택", list(manual_map), index=selected_index, key="selected_manual_selector")
        st.caption(f"검색 결과 {len(filtered_manuals)}개")
        manual_id = manual_map[selected]
        st.session_state["selected_manual"] = manual_id
        manual = row("SELECT * FROM manuals WHERE id=?", (manual_id,))
        revision = row("SELECT * FROM manual_revisions WHERE manual_id=? AND status='CURRENT' ORDER BY version DESC LIMIT 1", (manual_id,))
        age = None
        if manual["last_verified"]:
            age = (date.today() - date.fromisoformat(manual["last_verified"][:10])).days
        st.markdown(f"## {manual['title']}")
        version_label = f"v{manual['version']}"
        st.markdown(f"{badge('현재 기준')} {badge(version_label)} {badge(quality_ko(manual['data_quality']), 'warn' if manual['data_quality']=='Needs Review' else '')}", unsafe_allow_html=True)
        if age is None:
            st.warning("마지막 검토일이 없습니다.")
        elif age > 365:
            st.warning(f"마지막 검토: {age}일 전 · 검토 필요")
        else:
            st.caption(f"마지막 검토: {age}일 전 ({manual['last_verified']})")
        if st.button("현재도 유효함", key=f"verify_{manual_id}"):
            verify_manual(manual_id)
            rerun("내용 변경 없이 검증일을 갱신했습니다.")
        st.markdown("### 한눈에 보기")
        st.info(manual["current_standard"] or "현재 기준이 아직 요약되지 않았습니다.")
        st.caption(f"출처: {manual['source'] or '사용자 입력'} · 원본 시트: {manual['source_sheet'] or '-'}")

        task_templates = rows(
            "SELECT task_templates.*,event_templates.title AS template_title FROM task_templates "
            "JOIN event_templates ON event_templates.id=task_templates.event_template_id "
            "WHERE event_templates.manual_id=? AND event_templates.status='CURRENT' AND task_templates.data_quality<>'Stale' "
            "ORDER BY CASE WHEN task_templates.due_offset IS NULL THEN 1 ELSE 0 END,task_templates.due_offset,task_templates.id",
            (manual_id,),
        )
        references = rows(
            "SELECT * FROM references_data WHERE manual_id=? AND archived_at IS NULL ORDER BY reference_time,id",
            (manual_id,),
        )
        detail_tab, standard_tab, source_tab = st.tabs(["준비 상세", "운영 기준·이유", "원본 내용"])
        with detail_tab:
            if task_templates:
                timing_groups: dict[str, list[dict[str, object]]] = {}
                for task in task_templates:
                    timing_groups.setdefault(task["source_timing"] or "준비 시점 미기록", []).append(task)
                timing_options = list(timing_groups)
                st.caption(
                    f"준비업무 {len(task_templates)}건 · 준비 시점 {len(timing_options)}개 · "
                    "아래에서 필요한 시점만 골라 확인하세요."
                )
                selected_timing = st.selectbox(
                    "준비 시점",
                    [*timing_options, "전체 보기"],
                    key=f"manual_timing_{manual_id}",
                )
                visible_tasks = (
                    task_templates
                    if selected_timing == "전체 보기"
                    else timing_groups[selected_timing]
                )
                current_timing = None
                for task_index, task in enumerate(visible_tasks):
                    timing = task["source_timing"] or "준비 시점 미기록"
                    if timing != current_timing:
                        st.markdown(f"#### {timing} · {len(timing_groups[timing])}건")
                        current_timing = timing
                    if task["due_offset"] is None:
                        due_label = "일정 자동화 미정"
                    elif task["due_offset"] == 0:
                        due_label = "D-Day"
                    else:
                        due_label = f"D{task['due_offset']:+d}"
                    with st.expander(
                        f"{task['title']} · {due_label}",
                        expanded=task_index == 0,
                    ):
                        st.markdown(
                            f"{badge(due_label, 'warn' if task['due_offset'] is None else '')} "
                            f"{badge(quality_ko(task['data_quality']), 'warn' if task['data_quality']=='Needs Review' else '')}",
                            unsafe_allow_html=True,
                        )
                        if task["description"]:
                            st.markdown(task["description"])
                        if task["default_owner"]:
                            st.caption(f"기본 담당자: {task['default_owner']}")
                supplemental_marker = "## 추가 운영 안내"
                if revision and supplemental_marker in (revision["how_text"] or ""):
                    with st.expander("추가 운영 안내"):
                        st.markdown(revision["how_text"].split(supplemental_marker, 1)[1].strip())
            elif revision and revision["how_text"]:
                st.markdown(revision["how_text"])
            else:
                st.info("등록된 준비 상세가 없습니다.")

            if references:
                with st.expander(f"관련 참고자료 ({len(references)}개)"):
                    for reference in references:
                        detail = " · ".join(filter(None, [reference["ref_type"], reference["reference_time"], reference["description"]]))
                        st.markdown(f"- [{reference['title']}]({reference['url']})" + (f" — {detail}" if detail else ""))

        with standard_tab:
            if revision:
                st.markdown("#### 무엇을 위한 매뉴얼인가요?")
                st.write(revision["what_text"] or "미기록")
                st.markdown("#### 왜 이렇게 운영하나요?")
                st.write(revision["why_text"] or "미기록")
                st.markdown("#### 주의사항")
                st.write(revision["caution"] or "별도 기록 없음")
            else:
                st.info("현재 버전의 운영 기준이 없습니다.")

        with source_tab:
            st.caption("검색과 구조화 과정에서 누락 여부를 확인할 수 있도록 이관된 전체 내용을 보존합니다.")
            if revision and revision["how_text"]:
                st.markdown(revision["how_text"])
            else:
                st.info("보존된 원본 내용이 없습니다.")
        revisions = rows("SELECT * FROM manual_revisions WHERE manual_id=? ORDER BY version DESC", (manual_id,))
        with st.expander(f"버전 기록 ({len(revisions)}개)"):
            for item in revisions:
                st.markdown(f"**v{item['version']} · {status_ko(item['status'])} · {item['created_at'][:10]}**  \n{item['change_summary'] or '변경 설명 없음'}")
        with st.expander("새 버전 만들기"):
            with st.form(f"revision_{manual_id}"):
                standard = st.text_area("현재 기준 요약", value=manual["current_standard"] or "")
                what = st.text_area("목적", value=revision["what_text"] if revision else "")
                how = st.text_area("준비·운영 방법", value=revision["how_text"] if revision else "", height=180)
                why = st.text_area("이유", value=revision["why_text"] if revision else "")
                caution = st.text_area("주의사항", value=revision["caution"] if revision else "")
                summary = st.text_input("변경 요약")
                if st.form_submit_button("새 버전으로 저장", type="primary"):
                    if not summary:
                        st.error("변경 요약을 입력하세요.")
                    else:
                        revise_manual(manual_id, what, how, why, caution, standard, summary)
                        rerun("이전 버전을 보존하고 새 버전을 현재 기준으로 설정했습니다.")
        if st.button("매뉴얼 보관", key=f"archive_manual_{manual_id}"):
            archive_entity("manuals", manual_id)
            rerun("매뉴얼을 보관함으로 이동했습니다.")
    with create_tab:
        with st.form("new_manual"):
            title = st.text_input("제목")
            category = st.text_input("카테고리", value="운영기준")
            standard = st.text_area("현재 기준 요약")
            what = st.text_area("목적")
            how = st.text_area("준비·운영 방법")
            why = st.text_area("이유")
            caution = st.text_area("주의사항")
            if st.form_submit_button("매뉴얼 생성", type="primary"):
                if title:
                    create_manual(title, category, what, how, why, caution, standard)
                    rerun("v1 매뉴얼을 생성했습니다.")
                else:
                    st.error("제목을 입력하세요.")


def logs_page() -> None:
    hero("결정·운영 로그", "무엇을 바꿨는지보다 왜 바꿨는지를 남깁니다.")
    decision_tab, operation_tab = st.tabs(["결정 기록", "운영 기록"])
    events = rows("SELECT id,title,event_date FROM events WHERE archived_at IS NULL ORDER BY event_date DESC")
    manuals = rows("SELECT id,title FROM manuals WHERE status='CURRENT' ORDER BY title")
    event_map = {"연결 안 함": None, **{f"{item['event_date'] or ''} {item['title']}": item["id"] for item in events}}
    manual_map = {"연결 안 함": None, **{item["title"]: item["id"] for item in manuals}}
    with decision_tab:
        with st.expander("새 결정 등록", expanded=False):
            with st.form("new_decision"):
                title = st.text_input("결정 제목")
                event_label = st.selectbox("관련 행사", list(event_map), key="decision_event")
                manual_label = st.selectbox("관련 매뉴얼", list(manual_map))
                previous = st.text_area("이전 방식")
                new = st.text_area("새 방식")
                reason = st.text_area("결정 이유")
                decided_by = st.text_input("결정자")
                evidence = st.text_input("근거 URL/설명")
                status = st.selectbox(
                    "상태",
                    ["APPROVED", "PENDING", "REJECTED", "CHANGED"],
                    format_func=status_ko,
                )
                if st.form_submit_button("결정 저장", type="primary"):
                    if title:
                        add_decision({"event_id": event_map[event_label], "manual_id": manual_map[manual_label], "title": title, "previous_method": previous, "new_method": new, "reason": reason, "decided_at": date.today().isoformat(), "decided_by": decided_by, "evidence": evidence, "status": status})
                        rerun("결정과 이유를 기록했습니다.")
        items = rows(
            "SELECT decisions.*,events.title AS event_title,manuals.title AS manual_title FROM decisions "
            "LEFT JOIN events ON events.id=decisions.event_id LEFT JOIN manuals ON manuals.id=decisions.manual_id "
            "WHERE decisions.archived_at IS NULL ORDER BY COALESCE(decided_at,decisions.created_at) DESC"
        )
        if not items:
            st.info("등록된 결정이 없습니다.")
        for item in items:
            with st.expander(f"{item['decided_at'] or item['created_at'][:10]} · {item['title']}"):
                st.markdown(f"{badge(status_ko(item['status']))} {badge(item['event_title'] or '행사 미연결','gray')}", unsafe_allow_html=True)
                st.markdown(f"**이전 방식**  \n{item['previous_method'] or '-'}")
                st.markdown(f"**새 방식**  \n{item['new_method'] or '-'}")
                st.markdown(f"**이유**  \n{item['reason'] or '미기록'}")
                st.caption(f"결정자: {item['decided_by'] or '미기록'} · 매뉴얼: {item['manual_title'] or '미연결'} · 근거: {item['evidence'] or '없음'}")
    with operation_tab:
        with st.expander("새 운영/기술 로그 등록"):
            with st.form("new_log"):
                event_label = st.selectbox("관련 행사", list(event_map), key="log_event")
                log_type = st.selectbox("유형", ["문제", "결정", "변경", "참고", "개선", "사고", "요청"])
                title = st.text_input("제목", key="log_title")
                description = st.text_area("설명")
                equipment = st.text_input("장비")
                symptom = st.text_area("증상")
                cause = st.text_area("원인")
                action = st.text_area("조치")
                result = st.text_area("결과")
                recheck = st.checkbox("재확인 필요")
                occurred = st.date_input("발생일", value=date.today())
                if st.form_submit_button("로그 저장", type="primary"):
                    if title:
                        add_operation_log({"event_id": event_map[event_label], "log_type": log_type, "title": title, "description": description, "equipment": equipment, "symptom": symptom, "cause": cause, "action_taken": action, "result": result, "needs_recheck": int(recheck), "occurred_at": occurred.isoformat()})
                        rerun("운영 로그를 저장했습니다.")
        logs = rows("SELECT operation_logs.*,events.title AS event_title FROM operation_logs LEFT JOIN events ON events.id=operation_logs.event_id WHERE operation_logs.archived_at IS NULL ORDER BY COALESCE(occurred_at,operation_logs.created_at) DESC")
        if not logs:
            st.info("등록된 운영 로그가 없습니다.")
        for item in logs:
            with st.expander(f"[{item['log_type']}] {item['occurred_at'] or item['created_at'][:10]} · {item['title']}"):
                if item["needs_recheck"]:
                    st.warning("재확인 필요")
                st.write(item["description"] or "")
                if item["equipment"]:
                    st.markdown(f"**장비:** {item['equipment']}")
                if item["symptom"]:
                    st.markdown(f"**증상:** {item['symptom']}")
                if item["cause"]:
                    st.markdown(f"**원인:** {item['cause']}")
                if item["action_taken"]:
                    st.markdown(f"**조치:** {item['action_taken']}")
                if item["result"]:
                    st.markdown(f"**결과:** {item['result']}")
                st.caption(f"관련 행사: {item['event_title'] or '미연결'}")


def attendance_page() -> None:
    hero("예배 인원 현황", "가장 최근 주일예배 인원과 기간별 변화를 확인합니다.")
    data = pd.DataFrame(rows("SELECT * FROM attendance ORDER BY service_date"))
    if data.empty:
        st.info("예배 인원 데이터가 없습니다.")
        return
    data["service_date"] = pd.to_datetime(data["service_date"])
    data["month"] = data["service_date"].dt.to_period("M").astype(str)
    missing_count = int((data["total_count"] <= 0).sum())
    analysis_data = data[data["total_count"] > 0].copy()

    sunday_data = analysis_data[analysis_data["service_type"] == "주일예배"].sort_values("service_date", ascending=False)
    st.subheader("최근 주일예배")
    if sunday_data.empty:
        st.info("집계가 완료된 주일예배 인원 기록이 없습니다.")
    else:
        latest_sunday = sunday_data.iloc[0]
        previous_sunday = sunday_data.iloc[1] if len(sunday_data) > 1 else None
        latest_total = int(latest_sunday["total_count"]) if pd.notna(latest_sunday["total_count"]) else 0
        latest_offline = int(latest_sunday["offline_count"]) if pd.notna(latest_sunday["offline_count"]) else 0
        latest_online = int(latest_sunday["online_count"]) if pd.notna(latest_sunday["online_count"]) else 0
        total_delta = None
        if previous_sunday is not None and pd.notna(previous_sunday["total_count"]):
            total_delta = f"이전 주일 대비 {latest_total - int(previous_sunday['total_count']):+d}명"
        delta_chip = total_delta or "이전 주일 비교 없음"
        st.markdown(
            '<div class="ops-attendance">'
            f'<div class="date">{latest_sunday["service_date"].strftime("%Y.%m.%d")} · 집계 완료</div>'
            f'<div class="total">총 {latest_total}명</div>'
            f'<div class="chips"><span class="ops-chip">현장 {latest_offline}명</span>'
            f'<span class="ops-chip">온라인 {latest_online}명</span>'
            f'<span class="ops-chip">{html.escape(delta_chip)}</span></div></div>',
            unsafe_allow_html=True,
        )

        newer_unreported = data[
            (data["service_type"] == "주일예배")
            & (data["service_date"] > latest_sunday["service_date"])
            & (data["total_count"] <= 0)
        ].sort_values("service_date", ascending=False)
        if not newer_unreported.empty:
            pending_date = newer_unreported.iloc[0]["service_date"].strftime("%Y.%m.%d")
            st.caption(f"{pending_date} 주일예배는 인원이 아직 입력되지 않아 최근 집계 완료 기록을 표시했습니다.")

    st.subheader("기간별 인원 추이")
    min_date, max_date = data["service_date"].min().date(), data["service_date"].max().date()
    period_presets = {"8주": 56, "3개월": 92, "1년": 365, "전체": None}
    preset = st.radio("빠른 기간", list(period_presets), horizontal=True, key="attendance_period_preset")
    preset_days = period_presets[preset]
    preset_start = min_date if preset_days is None else max(min_date, max_date - timedelta(days=preset_days))
    f1, f2 = st.columns([1.3, 1])
    period = f1.date_input("기간", value=(preset_start, max_date), min_value=min_date, max_value=max_date, key=f"attendance_period_{preset}")
    types = sorted(data["service_type"].dropna().unique().tolist())
    default_types = ["주일예배"] if "주일예배" in types else types[:1]
    chosen = f2.multiselect("예배 종류", types, default=default_types)
    if isinstance(period, tuple) and len(period) == 2:
        filtered = analysis_data[(analysis_data["service_date"].dt.date >= period[0]) & (analysis_data["service_date"].dt.date <= period[1])]
    else:
        filtered = analysis_data
    filtered = filtered[filtered["service_type"].isin(chosen)]
    if missing_count:
        st.caption(f"미집계 또는 0명 여부 확인이 필요한 {missing_count}건은 통계 계산에서 제외하고 원본 기록은 보존했습니다.")
    if filtered.empty:
        st.warning("선택한 조건에 데이터가 없습니다.")
        return
    stats = [
        ("평균 총인원", f"{filtered['total_count'].mean():.1f}명"),
        ("평균 현장", f"{filtered['offline_count'].mean():.1f}명"),
        ("최고 인원", f"{int(filtered['total_count'].max())}명"),
        ("최저 인원", f"{int(filtered['total_count'].min())}명"),
    ]
    compact_stats(stats, columns=4)
    trend = filtered.sort_values(["service_date", "service_type"])
    fig = px.line(
        trend,
        x="service_date",
        y="total_count",
        color="service_type",
        markers=True,
        labels={"service_date": "예배일", "service_type": "예배", "total_count": "인원"},
    )
    fig.update_layout(margin=dict(l=10, r=10, t=20, b=10), legend_title_text="", hovermode="x unified", height=330)
    st.plotly_chart(fig, width="stretch")
    with st.expander("상세 통계·데이터 품질"):
        st.subheader("예배 종류별")
        summary = filtered.groupby("service_type", as_index=False).agg(기록수=("id", "count"), 평균=("total_count", "mean"), 현장평균=("offline_count", "mean"), 온라인평균=("online_count", "mean"))
        st.dataframe(summary.style.format({"평균": "{:.1f}", "현장평균": "{:.1f}", "온라인평균": "{:.1f}"}), hide_index=True, width="stretch", height=220)
        st.subheader("데이터 품질")
        quality = data.groupby("data_quality", as_index=False).size()
        quality["data_quality"] = quality["data_quality"].map(quality_ko)
        quality = quality.rename(columns={"data_quality": "데이터 상태", "size": "건수"})
        st.dataframe(quality, hide_index=True, width="stretch", height=180)
        flagged = data[data["data_quality"] == "Needs Review"][["service_date", "service_type", "online_count", "offline_count", "total_count", "notes"]]
        if not flagged.empty:
            st.warning(f"확인이 필요한 예배 인원 기록 {len(flagged)}건")
            st.dataframe(
                flagged.rename(columns={
                    "service_date": "예배일",
                    "service_type": "예배 종류",
                    "online_count": "온라인",
                    "offline_count": "현장",
                    "total_count": "총인원",
                    "notes": "확인 내용",
                }),
                hide_index=True,
                width="stretch",
                height=240,
            )
    st.caption("통계의 변화는 운영 이벤트와 함께 참고할 수 있지만, 자동으로 인과관계를 주장하지 않습니다.")


def search_page() -> None:
    hero("전체 검색", "준비업무와 매뉴얼 내용을 검색하고 상세 화면으로 바로 이동합니다.")
    term = st.text_input("검색어", value=st.session_state.get("search_term", ""), placeholder="예: 세례, 방석, 마이크")
    include_archived = st.checkbox("보관·이전 버전도 포함", value=False)
    if not term.strip():
        st.info("검색어를 입력하세요.")
        return
    results = global_search(term, include_archived)
    display_limit = st.selectbox("한 번에 보기", [10, 25, 50], index=1, key="global_search_limit")
    visible_results = results[:display_limit]
    st.caption(f"검색 결과 {len(results)}건 · 현재 {len(visible_results)}건 표시")
    if not results:
        st.warning("결과가 없습니다.")
    for index, item in enumerate(visible_results):
        with st.container(border=True):
            content_col, action_col = st.columns([.82, .18])
            tone = "gray" if item["archived"] else ""
            content_col.markdown(
                f'<strong>{html.escape(str(item["title"]))}</strong> {badge(item["kind"], tone)} '
                f'{badge("보관·이전 자료", "gray") if item["archived"] else ""}',
                unsafe_allow_html=True,
            )
            excerpt = search_excerpt(item["snippet"], term)
            content_col.caption(excerpt or "설명 없음")
            open_label = "매뉴얼 열기" if item["target_page"] == "매뉴얼" else ("행사 열기" if item["target_page"] == "행사" else "기록 열기")
            if action_col.button(open_label, key=f"search_open_{index}_{item['kind']}_{item['id']}", width="stretch"):
                if item["target_page"] == "매뉴얼":
                    navigate("매뉴얼", "selected_manual", item["target_id"])
                elif item["target_page"] == "행사":
                    navigate("행사", "selected_event", item["target_id"])
                else:
                    navigate(item["target_page"])


def archive_page() -> None:
    hero("보관함", "삭제 대신 보관하고, 필요할 때 다시 현재 자료로 복원합니다.")
    events = rows("SELECT id,title,event_date,archived_at FROM events WHERE archived_at IS NOT NULL ORDER BY archived_at DESC")
    manuals = rows("SELECT id,title,archived_at FROM manuals WHERE archived_at IS NOT NULL ORDER BY archived_at DESC")
    event_tab, manual_tab = st.tabs([f"행사 ({len(events)})", f"매뉴얼 ({len(manuals)})"])
    with event_tab:
        if not events:
            st.info("보관된 행사가 없습니다.")
        for item in events:
            cols = st.columns([.8, .2])
            cols[0].markdown(f"**{item['title']}**  \n{item['event_date'] or '날짜 미정'} · 보관 {item['archived_at'][:10]}")
            if cols[1].button("복원", key=f"restore_event_{item['id']}"):
                archive_entity("events", item["id"], restore=True)
                rerun("행사를 복원했습니다.")
    with manual_tab:
        if not manuals:
            st.info("보관된 매뉴얼이 없습니다.")
        for item in manuals:
            cols = st.columns([.8, .2])
            cols[0].markdown(f"**{item['title']}**  \n보관 {item['archived_at'][:10]}")
            if cols[1].button("복원", key=f"restore_manual_{item['id']}"):
                archive_entity("manuals", item["id"], restore=True)
                rerun("매뉴얼을 복원했습니다.")


def calendar_page() -> None:
    hero("교회력", "Google Calendar의 교회 일정을 읽기 전용으로 동기화해 대시보드에 표시합니다.")
    today = date.today().isoformat()
    upcoming = rows(
        "SELECT * FROM church_calendar_events WHERE archived_at IS NULL AND status<>'CANCELLED' AND start_date>=? "
        "ORDER BY start_date,id LIMIT 30",
        (today,),
    )
    sync_status = row(
        "SELECT MAX(synced_at) AS last_sync,COUNT(*) AS total FROM church_calendar_events WHERE archived_at IS NULL"
    ) or {"last_sync": None, "total": 0}
    last_sync_label = (sync_status["last_sync"] or "연동 전").replace("T", " ")
    if last_sync_label != "연동 전" and len(last_sync_label) >= 16:
        last_sync_label = last_sync_label[5:16]
    compact_stats([
        ("다가오는 일정", f"{len(upcoming)}건"),
        ("저장된 일정", f"{sync_status['total']}건"),
        ("마지막 동기화", last_sync_label),
    ], columns=3)

    st.subheader("다가오는 일정")
    if upcoming:
        calendar_limit = st.selectbox("한 번에 보기", [10, 20, 30], key="calendar_display_limit")
        st.caption(f"다가오는 일정 {len(upcoming)}건 · 현재 {min(len(upcoming), calendar_limit)}건 표시")
        for item in upcoming[:calendar_limit]:
            with st.container(border=True):
                st.markdown(
                    f"{badge(dday(item['start_date']), 'warn')} {badge(item['start_date'], 'gray')}  "
                    f"**{html.escape(str(item['title']))}**",
                    unsafe_allow_html=True,
                )
                if item["location"]:
                    st.caption(f"장소 · {item['location']}")
                if item["description"]:
                    st.caption(search_excerpt(item["description"], "", 180))
                if item["html_link"]:
                    st.link_button("Google Calendar에서 보기", item["html_link"], width="stretch")
    else:
        st.info("아직 동기화된 교회력 일정이 없습니다.")

    with st.expander("Google Calendar 연결 설정", expanded=False):
        calendar_credentials, calendar_secret_error = service_account_secret("GOOGLE_REVIEW_BOARD_SERVICE_ACCOUNT")
        try:
            secret_calendar_id = str(st.secrets["GOOGLE_CALENDAR_ID"]).strip()
        except (FileNotFoundError, KeyError):
            secret_calendar_id = ""
        current_calendar_id = secret_calendar_id or get_app_meta("google_calendar_id", "")
        service_email = str((calendar_credentials or {}).get("client_email") or "")
        st.markdown(
            "**Streamlit Cloud 권장 방식**  \n"
            "Google Calendar 설정에서 아래 서비스 계정을 `모든 일정 세부정보 보기`로 공유하세요. "
            "앱은 일정 **읽기 전용** 권한만 사용합니다."
        )
        if service_email:
            st.code(service_email, language=None)
        else:
            st.warning("게시판에 사용한 서비스 계정 Secret을 찾을 수 없습니다.")
            st.caption(calendar_secret_error)
        calendar_id = st.text_input(
            "Calendar ID",
            value=current_calendar_id,
            placeholder="예: church-calendar@group.calendar.google.com",
            disabled=bool(secret_calendar_id),
            help="Google Calendar 설정 → 캘린더 통합 → Calendar ID에서 확인합니다.",
        )
        save_col, sync_col = st.columns(2)
        if save_col.button("연동 설정 저장", width="stretch"):
            if not calendar_id.strip():
                st.error("Calendar ID를 입력하세요.")
            else:
                if not secret_calendar_id:
                    set_app_meta("google_calendar_id", calendar_id.strip())
                rerun("Google Calendar 연동 설정을 저장했습니다.")
        if sync_col.button("Google Calendar 읽기·동기화", type="primary", width="stretch", disabled=calendar_credentials is None):
            if not calendar_id.strip():
                st.error("Calendar ID를 입력하고 설정을 저장하세요.")
            else:
                try:
                    set_app_meta("google_calendar_id", calendar_id.strip())
                    with st.spinner("교회력 일정을 읽기 전용으로 동기화하는 중입니다…"):
                        result = sync_google_calendar_service_account(calendar_id.strip(), calendar_credentials)
                    rerun(f"{result['calendar']}에서 교회력 일정 {result['saved']}건을 동기화했습니다.")
                except Exception as exc:
                    st.error(f"동기화하지 못했습니다: {exc}")
        st.caption("Calendar ID를 Streamlit Secret `GOOGLE_CALENDAR_ID`로 저장하면 재부팅 후에도 설정이 유지됩니다.")


def data_page() -> None:
    hero("데이터·백업", "원본 가져오기부터 형식 확인·정리·저장 상태까지 확인합니다.")
    st.subheader("Google Sheets 원본")
    google_sheets_sync_bar()
    st.caption("예배팀 매뉴얼과 예배인원·엔지니어 라인업은 읽기 전용으로 가져옵니다.")
    st.warning(
        "팀 확인 게시판은 Google Sheets에 영구 저장됩니다. 그 외의 새 행사·업무 상태·매뉴얼 수정·운영기록은 "
        "현재 Streamlit 로컬 DB에 저장되어 재부팅·재배포 후 유지가 보장되지 않습니다. 중요한 내용은 백업을 내려받으세요."
    )
    st.divider()
    import_tab, quality_tab, backup_tab = st.tabs(["가져오기 결과", "확인 필요", "백업"])
    with import_tab:
        if IMPORT_REPORT_PATH.exists():
            report = json.loads(IMPORT_REPORT_PATH.read_text(encoding="utf-8"))
            counts = report.get("imported", {})
            compact_stats([
                ("예배 인원", counts.get("attendance", 0)),
                ("매뉴얼", counts.get("manuals", 0)),
                ("행사", counts.get("events", 0)),
                ("인원 명단", counts.get("members", 0)),
            ], columns=4)
            st.json(report, expanded=False)
        else:
            st.info("가져오기 결과가 없습니다.")
        with st.expander("고급 관리 · 로컬 DB 다시 구축"):
            st.error(
                "이 기능은 행사·업무 상태·매뉴얼 수정·운영기록 등 로컬 DB의 사용자 입력을 삭제합니다. "
                "먼저 '백업' 탭에서 파일을 내려받으세요. 게시판 Google Sheets는 삭제되지 않습니다."
            )
            confirm_reset = st.text_input("실행하려면 '데이터 다시 구축'을 입력", key="db_reset_confirmation")
            backup_confirmed = st.checkbox("백업 파일을 내려받았습니다.", key="db_reset_backup_confirmed")
            reset_ready = confirm_reset.strip() == "데이터 다시 구축" and backup_confirmed
            if st.button("로컬 DB 다시 구축", type="secondary", disabled=not reset_ready, key="rebuild_local_db"):
                rebuild_source = GOOGLE_SHEETS_CACHE_DIR if list(GOOGLE_SHEETS_CACHE_DIR.glob("*.xlsx")) else SOURCE_DIR
                migrate(source_dir=rebuild_source, reset=True)
                rerun("원본 파일로 로컬 DB를 다시 구축했습니다.")
    with quality_tab:
        unresolved = rows(
            "SELECT unresolved_imports.*,source_files.file_name FROM unresolved_imports LEFT JOIN source_files ON source_files.id=unresolved_imports.source_file_id ORDER BY CASE quality WHEN 'Needs Review' THEN 1 ELSE 2 END,id"
        )
        if not unresolved:
            st.success("확인이 필요한 항목이 없습니다.")
        else:
            unresolved_frame = pd.DataFrame(unresolved)[
                ["quality", "file_name", "sheet_name", "cell_reference", "raw_value", "reason", "status"]
            ].rename(columns={
                "quality": "데이터 상태",
                "file_name": "원본 파일",
                "sheet_name": "시트",
                "cell_reference": "셀 위치",
                "raw_value": "원본 값",
                "reason": "확인 이유",
                "status": "처리 상태",
            })
            unresolved_frame["데이터 상태"] = unresolved_frame["데이터 상태"].map(quality_ko)
            unresolved_frame["처리 상태"] = unresolved_frame["처리 상태"].replace({"OPEN": "확인 필요", "RESOLVED": "처리 완료"})
            st.dataframe(
                unresolved_frame,
                hide_index=True,
                width="stretch",
                height=360,
            )
    with backup_tab:
        st.markdown("중요한 운영지식은 JSON 전체 백업과 테이블별 CSV로 내보낼 수 있습니다.")
        if st.button("백업 생성", type="primary"):
            json_path, csv_payloads = export_backup()
            st.session_state["backup_json_path"] = str(json_path)
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                for table, content in csv_payloads.items():
                    archive.writestr(f"{table}.csv", content.encode("utf-8-sig"))
            st.session_state["backup_csv_zip"] = buffer.getvalue()
        json_path_value = st.session_state.get("backup_json_path")
        if json_path_value and Path(json_path_value).exists():
            path = Path(json_path_value)
            st.download_button("JSON 전체 백업 다운로드", path.read_bytes(), file_name=path.name, mime="application/json")
        if st.session_state.get("backup_csv_zip"):
            st.download_button("CSV 묶음 다운로드", st.session_state["backup_csv_zip"], file_name="joyful_worship_ops_csv.zip", mime="application/zip")


def main() -> None:
    bootstrap()
    nav = sidebar()
    show_flash()
    pages = {
        "대시보드": dashboard_page,
        "팀 확인": review_board_page,
        "교회력": calendar_page,
        "행사": events_page,
        "매뉴얼": manuals_page,
        "결정·운영로그": logs_page,
        "예배 인원 현황": attendance_page,
        "전체 검색": search_page,
        "보관함": archive_page,
        "데이터·백업": data_page,
    }
    pages[nav]()


if __name__ == "__main__":
    main()

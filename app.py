from __future__ import annotations

import io
import html
import hashlib
import hmac
import json
import math
import sys
import time
import zipfile
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd
import plotly.express as px
import streamlit as st

APP_DIR = Path(__file__).resolve().parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))
BIBLE_TEXT_PATH = APP_DIR / "bible_text.txt"

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
from bible_lookup import (
    BibleReference,
    BibleVerse,
    LocalBible,
    extract_bible_references,
    fetch_local_bible_verse,
    parse_local_bible,
)
from google_sheets_sync import sync_google_sheets
from google_review_board import (
    RESOLUTION_COMMENT_PREFIX,
    GoogleReviewBoardStore,
    ReviewBoardConnectionError,
    find_resolution_comments,
    filter_review_items,
)
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
    create_sqlite_backup,
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
from time_utils import today_kst


st.set_page_config(page_title=APP_TITLE, page_icon="⛪", layout="wide", initial_sidebar_state="auto")

# Match charts to the same Joyful Church brand palette.
px.defaults.template = "plotly_white"
px.defaults.color_discrete_sequence = ["#FF8207", "#B84B00", "#FFC166", "#5B4A3E"]

CSS = """
<style>
:root {
  --brand:#FF8207; --brand-pressed:#E96F00; --brand-soft:#FFF1E3;
  --bg:#F7F8FA; --surface:#FFFFFF; --text:#191F28; --text-2:#4E5968;
  --text-3:#667180; --line:#E5E8EB; --danger:#D64545; --warning:#B86E00;
  --shadow:0 4px 18px rgba(25,31,40,.055); color-scheme:light !important;
}
html, body, .stApp { color-scheme:light !important; }
html, body, [class*="css"] { font-family:Pretendard,"Noto Sans KR","Apple SD Gothic Neo","Segoe UI",sans-serif; }
.stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"] {
  background:var(--bg) !important; color:var(--text) !important;
}
[data-testid="stMainBlockContainer"] {
  max-width:1040px; padding-top:3.7rem; padding-bottom:5rem;
  color:var(--text) !important;
}
[data-testid="stHeader"] { background:rgba(247,248,250,.94) !important; backdrop-filter:blur(12px); }
[data-testid="stToolbar"] { display:flex !important; }
[data-testid="stToolbar"] button, [data-testid="stHeaderActionElements"] button { color:var(--text) !important; }
#MainMenu, [data-testid="stMainMenu"], [data-testid="stAppDeployButton"], [data-testid="stToolbarActions"] { display:none !important; }
h1,h2,h3,h4,h5,h6 { color:var(--text) !important; letter-spacing:-.035em; }
h2 { margin-top:0; }
[data-testid="stMainBlockContainer"] [data-testid="stMarkdownContainer"] p,
[data-testid="stMainBlockContainer"] [data-testid="stMarkdownContainer"] li,
[data-testid="stMainBlockContainer"] [data-testid="stMarkdownContainer"] span,
[data-testid="stMainBlockContainer"] label,
[data-testid="stMainBlockContainer"] [data-testid="stCaptionContainer"],
[data-testid="stMainBlockContainer"] [data-testid="stCaptionContainer"] p,
[data-testid="stMainBlockContainer"] [data-testid="stWidgetLabel"] p,
[data-testid="stMainBlockContainer"] [data-testid="stCheckbox"] p,
[data-testid="stMainBlockContainer"] [data-testid="stToggle"] p {
  color:var(--text-2) !important; -webkit-text-fill-color:var(--text-2) !important; opacity:1 !important;
}
[data-testid="stCaptionContainer"] { line-height:1.55; }
a { color:#B95000; }

/* Calm, compact navigation. */
[data-testid="stSidebar"] { background:#FFFFFF !important; border-right:1px solid var(--line); }
[data-testid="stSidebar"] * { color:var(--text-2) !important; -webkit-text-fill-color:var(--text-2) !important; }
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] strong { color:var(--text) !important; -webkit-text-fill-color:var(--text) !important; }
[data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding:1.45rem .9rem 2rem; }
[data-testid="stSidebar"] hr { border-color:var(--line) !important; margin:.85rem 0; }
[data-testid="stSidebar"] [role="radiogroup"] { gap:.15rem; }
[data-testid="stSidebar"] [role="radiogroup"] label {
  position:relative; min-height:44px; padding:.5rem .55rem !important; border-radius:10px; transition:background .15s;
}
[data-testid="stSidebar"] [role="radiogroup"] label > div:first-child {
  position:absolute !important; width:1px !important; height:1px !important;
  overflow:hidden !important; opacity:0 !important; pointer-events:none !important;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover { background:#F2F4F6; }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) { background:var(--brand-soft); }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {
  color:#A64500 !important; -webkit-text-fill-color:#A64500 !important; font-weight:800 !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] button {
  background:transparent !important; border:0 !important; color:var(--text-2) !important;
  box-shadow:none !important; justify-content:flex-start !important; padding:.45rem .55rem !important;
}
[data-testid="stSidebar"] [data-testid="stButton"] button:hover { background:#F2F4F6 !important; }
[data-testid="stSidebar"] [data-testid="stFormSubmitButton"] button {
  background:#F2F4F6 !important; border:0 !important; color:var(--text-2) !important;
  box-shadow:none !important; border-radius:10px !important;
}

/* The navigation control stays visible even when the phone is in dark mode. */
[data-testid="stSidebarCollapseButton"] button,
[data-testid="stSidebarCollapsedControl"] button,
[data-testid="collapsedControl"] button,
button[data-testid="stExpandSidebarButton"],
button[data-testid="stBaseButton-headerNoPadding"] {
  -webkit-appearance:none !important; appearance:none !important; color-scheme:light !important;
  background:var(--brand) !important; background-image:none !important;
  color:var(--text) !important; -webkit-text-fill-color:var(--text) !important;
  border:2px solid #FFFFFF !important; border-radius:999px !important;
  width:2.75rem !important; height:2.75rem !important; min-width:2.75rem !important; min-height:2.75rem !important;
  opacity:1 !important; box-shadow:0 3px 10px rgba(25,31,40,.22) !important;
}
[data-testid="stSidebarCollapseButton"] button *,
[data-testid="stSidebarCollapsedControl"] button *,
[data-testid="collapsedControl"] button *,
button[data-testid="stExpandSidebarButton"] *,
button[data-testid="stBaseButton-headerNoPadding"] * {
  color:var(--text) !important; -webkit-text-fill-color:var(--text) !important;
  fill:var(--text) !important; stroke:var(--text) !important; opacity:1 !important;
}

/* Page and section hierarchy. */
.ops-hero { background:transparent; padding:.25rem 0 .7rem; margin:0 0 1.25rem; }
.ops-hero::after { display:none; }
.ops-hero .eyebrow, .ops-dashboard-head .eyebrow {
  color:var(--text-3) !important; -webkit-text-fill-color:var(--text-3) !important;
  font-size:.82rem; font-weight:700; margin-bottom:.35rem;
}
.ops-hero h1 { margin:0; font-size:1.8rem; font-weight:850; line-height:1.25; }
.ops-hero p { color:var(--text-2) !important; -webkit-text-fill-color:var(--text-2) !important; margin:.45rem 0 0; font-size:.96rem; line-height:1.55; }
.ops-dashboard-head { margin:.1rem 0 1.45rem; }
.ops-dashboard-head h1 { margin:0; font-size:1.9rem; font-weight:850; line-height:1.2; }
.ops-section-gap { height:2.65rem; }
.ops-section-title { margin:0 0 .75rem; font-size:1.18rem; font-weight:850; color:var(--text); letter-spacing:-.025em; }
.ops-empty { background:#FFFFFF; border-radius:16px; padding:1rem 1.1rem; color:var(--text-2); line-height:1.55; box-shadow:var(--shadow); }
.ops-plain-text { color:var(--text-2); font-size:.94rem; line-height:1.65; overflow-wrap:anywhere; white-space:normal; }

/* Cards rely on spacing and a quiet surface instead of orange borders. */
.ops-card-grid { display:grid; grid-template-columns:1.2fr .8fr; gap:.7rem; }
.ops-card { background:var(--surface); border:0; border-radius:20px; padding:1.05rem 1.15rem; min-height:118px; box-shadow:var(--shadow); }
.ops-card .label { color:var(--text-2); font-size:.84rem; margin-bottom:.35rem; font-weight:700; }
.ops-card .value { color:var(--text); font-weight:900; font-size:1.9rem; line-height:1.1; letter-spacing:-.045em; }
.ops-card.primary .value { font-size:2.75rem; }
.ops-card .note { color:var(--text-3); font-size:.79rem; margin-top:.45rem; }
.ops-stat-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.55rem; margin:.5rem 0 1rem; }
.ops-stat, .review-stat, .compact-stat {
  background:#FFFFFF; border:0; border-radius:16px; box-shadow:var(--shadow);
}
.ops-stat { padding:.78rem .9rem; }
.ops-stat .label, .review-stat .label, .compact-stat .label { color:var(--text-3); font-size:.78rem; font-weight:650; }
.ops-stat .value, .review-stat .value, .compact-stat .value { color:var(--text); font-weight:850; letter-spacing:-.025em; }
.ops-stat .value { font-size:1.35rem; margin-top:.18rem; }
.review-stat-grid { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:.4rem; margin:.5rem 0 .85rem; }
.review-stat { min-height:76px; padding:.58rem .25rem; text-align:center; display:flex; flex-direction:column; align-items:center; justify-content:center; }
.review-stat .label { white-space:nowrap; }
.review-stat .value { font-size:1.3rem; line-height:1.15; margin-top:.2rem; }
.compact-stat-grid { display:grid; grid-template-columns:repeat(var(--stat-cols,4),minmax(0,1fr)); gap:.4rem; margin:.5rem 0 .85rem; }
.compact-stat { min-height:72px; padding:.55rem .3rem; text-align:center; display:flex; flex-direction:column; align-items:center; justify-content:center; }
.compact-stat .value { font-size:1.16rem; margin-top:.2rem; overflow-wrap:anywhere; }
.ops-list { display:grid; gap:.55rem; margin:.45rem 0 .8rem; }
.ops-list-item { background:#FFFFFF; border:0; border-radius:16px; padding:.9rem 1rem; box-shadow:var(--shadow); }
.ops-list-item .meta { color:var(--text-3); font-size:.78rem; margin-bottom:.25rem; }
.ops-list-item .title { color:var(--text); font-size:1rem; font-weight:800; }
.ops-list-item .note { color:var(--text-2); font-size:.82rem; margin-top:.25rem; }
.ops-attendance { background:#FFFFFF; border:0; border-radius:20px; padding:1.15rem 1.2rem; margin:.4rem 0 1rem; box-shadow:var(--shadow); }
.ops-attendance .date { color:var(--text-3); font-size:.86rem; font-weight:650; }
.ops-attendance .total { color:var(--text); font-size:2.35rem; font-weight:900; line-height:1.12; margin:.35rem 0 .7rem; letter-spacing:-.045em; }
.ops-attendance .chips { display:flex; flex-wrap:wrap; gap:.4rem; }
.ops-chip { display:inline-block; background:#F2F4F6; color:var(--text-2) !important; border-radius:999px; padding:.34rem .68rem; font-size:.82rem; font-weight:700; border:0; }
.ops-badge { display:inline-block; border-radius:999px; padding:.18rem .52rem; font-size:.72rem; font-weight:750; background:var(--brand-soft); color:#A64500 !important; -webkit-text-fill-color:#A64500 !important; margin-right:.25rem; }
.ops-badge.warn { background:#FFF4D6; color:#8A5600 !important; -webkit-text-fill-color:#8A5600 !important; }
.ops-badge.danger { background:#FDECEC; color:#B3261E !important; -webkit-text-fill-color:#B3261E !important; }
.ops-badge.gray { background:#F2F4F6; color:var(--text-2) !important; -webkit-text-fill-color:var(--text-2) !important; }
.ops-item { background:#FFFFFF; border:0; border-radius:16px; padding:.9rem 1rem; margin:.5rem 0; box-shadow:var(--shadow); }
.ops-item.warn { box-shadow:inset 3px 0 #E5A400,var(--shadow); }
.ops-item.danger { box-shadow:inset 3px 0 var(--danger),var(--shadow); }
.review-comment { background:#F7F8FA; border:0; border-radius:12px; padding:.7rem .8rem; margin:.35rem 0; }
.muted { color:var(--text-3) !important; -webkit-text-fill-color:var(--text-3) !important; font-size:.87rem; }
.compact p { margin:.15rem 0; }

/* Bible results prioritize the text itself. */
.bible-result-summary { display:flex; align-items:center; flex-wrap:wrap; gap:.55rem; margin:.2rem 0 1rem; color:var(--text-3); font-size:.78rem; }
.bible-result-summary span { display:inline-flex; align-items:baseline; gap:.2rem; background:transparent; border:0; padding:0; color:var(--text-3); }
.bible-result-summary strong { color:var(--text-2); font-size:.82rem; font-weight:800; }
.bible-verse { padding:.8rem 0 1rem; border-bottom:1px solid var(--line); }
.bible-verse:last-child { border-bottom:0; }
.bible-verse .reference { color:var(--text-2); font-size:.84rem; font-weight:800; margin-bottom:.42rem; }
.bible-verse .content { color:var(--text); font-size:1.05rem; line-height:1.75; letter-spacing:-.012em; }

/* Clear three-level button hierarchy. */
[data-testid="stMainBlockContainer"] div[data-testid="stButton"] button,
[data-testid="stMainBlockContainer"] div[data-testid="stFormSubmitButton"] button,
[data-testid="stMainBlockContainer"] div[data-testid="stDownloadButton"] button,
[data-testid="stMainBlockContainer"] div[data-testid="stLinkButton"] a,
[data-testid="stMainBlockContainer"] .stButton > button,
[data-testid="stMainBlockContainer"] .stDownloadButton > button,
[data-testid="stMainBlockContainer"] .stLinkButton > a {
  -webkit-appearance:none !important; appearance:none !important; color-scheme:light !important;
  background:#F2F4F6 !important; background-image:none !important;
  color:#333D4B !important; -webkit-text-fill-color:#333D4B !important;
  border:0 !important; border-radius:12px !important; font-weight:750 !important;
  opacity:1 !important; box-shadow:none !important; transition:background .15s,transform .08s;
}
[data-testid="stMainBlockContainer"] div[data-testid="stButton"] button *,
[data-testid="stMainBlockContainer"] div[data-testid="stFormSubmitButton"] button *,
[data-testid="stMainBlockContainer"] div[data-testid="stDownloadButton"] button *,
[data-testid="stMainBlockContainer"] div[data-testid="stLinkButton"] a * {
  color:#333D4B !important; -webkit-text-fill-color:#333D4B !important; opacity:1 !important;
}
[data-testid="stMainBlockContainer"] div[data-testid="stButton"] button[kind="primary"],
[data-testid="stMainBlockContainer"] div[data-testid="stFormSubmitButton"] button[kind="primary"],
[data-testid="stMainBlockContainer"] div[data-testid="stDownloadButton"] button[kind="primary"],
[data-testid="stMainBlockContainer"] button[data-testid="stBaseButton-primary"] {
  background:var(--brand) !important; color:var(--text) !important; -webkit-text-fill-color:var(--text) !important;
}
[data-testid="stMainBlockContainer"] div[data-testid="stButton"] button[kind="primary"] *,
[data-testid="stMainBlockContainer"] div[data-testid="stFormSubmitButton"] button[kind="primary"] *,
[data-testid="stMainBlockContainer"] div[data-testid="stDownloadButton"] button[kind="primary"] *,
[data-testid="stMainBlockContainer"] button[data-testid="stBaseButton-primary"] * {
  color:var(--text) !important; -webkit-text-fill-color:var(--text) !important;
}
[data-testid="stMainBlockContainer"] div[data-testid="stButton"] button[kind="tertiary"],
[data-testid="stMainBlockContainer"] button[data-testid="stBaseButton-tertiary"] {
  background:transparent !important; color:var(--text-2) !important;
}
[data-testid="stMainBlockContainer"] div[data-testid="stButton"] button:hover,
[data-testid="stMainBlockContainer"] div[data-testid="stFormSubmitButton"] button:hover,
[data-testid="stMainBlockContainer"] div[data-testid="stDownloadButton"] button:hover,
[data-testid="stMainBlockContainer"] div[data-testid="stLinkButton"] a:hover { background:#E5E8EB !important; }
[data-testid="stMainBlockContainer"] div[data-testid="stButton"] button[kind="primary"]:hover,
[data-testid="stMainBlockContainer"] div[data-testid="stFormSubmitButton"] button[kind="primary"]:hover,
[data-testid="stMainBlockContainer"] div[data-testid="stDownloadButton"] button[kind="primary"]:hover,
[data-testid="stMainBlockContainer"] button[data-testid="stBaseButton-primary"]:hover { background:var(--brand-pressed) !important; }
[data-testid="stMainBlockContainer"] button:active { transform:scale(.99); }
[data-testid="stMainBlockContainer"] button:disabled,
[data-testid="stMainBlockContainer"] button:disabled * {
  background:#E5E8EB !important; color:var(--text-3) !important; -webkit-text-fill-color:var(--text-3) !important; opacity:1 !important;
}
.st-key-dashboard_attendance_summary button { min-height:3.25rem !important; justify-content:flex-start !important; text-align:left !important; padding:.78rem .95rem !important; line-height:1.4 !important; background:#FFFFFF !important; box-shadow:var(--shadow) !important; }
.st-key-dashboard_attendance_summary button p { text-align:left !important; }

/* Inputs and native Streamlit surfaces. */
[data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
[data-baseweb="select"] > div, [data-testid="stNumberInput"] input,
[data-testid="stDateInput"] input {
  background:#FFFFFF !important; color:var(--text) !important; -webkit-text-fill-color:var(--text) !important;
  border-color:#D1D6DB !important; caret-color:var(--text) !important; opacity:1 !important; border-radius:12px !important;
}
[data-testid="stTextInput"] input:focus, [data-testid="stTextArea"] textarea:focus,
[data-testid="stNumberInput"] input:focus, [data-testid="stDateInput"] input:focus { border-color:var(--brand) !important; box-shadow:0 0 0 1px var(--brand) !important; }
input::placeholder, textarea::placeholder { color:var(--text-3) !important; -webkit-text-fill-color:var(--text-3) !important; opacity:1 !important; }
[data-baseweb="select"] *, [role="listbox"] *, [role="option"], [data-baseweb="popover"] * { color:var(--text) !important; -webkit-text-fill-color:var(--text) !important; }
[role="listbox"], [data-baseweb="popover"], [data-baseweb="menu"], [data-baseweb="calendar"] { background:#FFFFFF !important; color:var(--text) !important; }
[data-testid="stAlert"] { color:var(--text) !important; border:0 !important; border-radius:14px !important; }
[data-testid="stAlert"] p, [data-testid="stAlert"] div, [data-testid="stAlert"] span { color:var(--text-2) !important; -webkit-text-fill-color:var(--text-2) !important; opacity:1 !important; }
[data-testid="stExpander"] details, [data-testid="stDataFrame"], [data-testid="stForm"],
[data-testid="stVerticalBlockBorderWrapper"] {
  background:#FFFFFF !important; color:var(--text) !important; border:0 !important;
  border-radius:16px !important; box-shadow:var(--shadow) !important;
}
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary * { color:var(--text-2) !important; -webkit-text-fill-color:var(--text-2) !important; opacity:1 !important; }
[data-testid="stForm"] p, [data-testid="stForm"] label, [data-testid="stForm"] span { color:var(--text-2) !important; -webkit-text-fill-color:var(--text-2) !important; }
[data-testid="stMainBlockContainer"] .stCheckbox label *,
[data-testid="stMainBlockContainer"] [data-testid="stToggle"] label *,
[data-testid="stMainBlockContainer"] [role="radiogroup"] label * { color:var(--text-2) !important; -webkit-text-fill-color:var(--text-2) !important; opacity:1 !important; }
div[data-testid="stMetric"] { background:#FFFFFF !important; border:0; border-radius:16px; padding:.8rem .9rem; box-shadow:var(--shadow); }
[data-testid="stMetricLabel"] *, [data-testid="stMetricDelta"] * { color:var(--text-3) !important; -webkit-text-fill-color:var(--text-3) !important; }
[data-testid="stMetricValue"] * { color:var(--text) !important; -webkit-text-fill-color:var(--text) !important; }
[data-testid="stTabs"] [role="tablist"] { gap:.2rem; background:#EDEFF2; border-radius:12px; padding:.2rem; }
[data-testid="stTab"] { min-height:44px !important; border-radius:9px !important; padding:.55rem .75rem !important; border:0 !important; }
[data-testid="stTab"] *, [role="tab"] { color:var(--text-2) !important; }
[data-testid="stTab"][aria-selected="true"] { background:#FFFFFF !important; box-shadow:0 1px 4px rgba(25,31,40,.08); }
[data-testid="stTab"][aria-selected="true"] * { color:var(--text) !important; font-weight:800 !important; }
[data-testid="stTab"] .react-aria-SelectionIndicator { display:none !important; }
code, pre { background:#F2F4F6 !important; color:var(--text) !important; }
hr { border-color:var(--line) !important; }
:focus-visible { outline:3px solid #1776D2 !important; outline-offset:2px !important; }

@media (prefers-color-scheme:dark) {
  html, body, .stApp, [data-testid="stAppViewContainer"], [data-testid="stMain"], [data-testid="stMainBlockContainer"] {
    background:var(--bg) !important; color:var(--text) !important; color-scheme:light !important;
  }
}
@media (max-width:768px) {
  [data-testid="stMainBlockContainer"] { padding:3.2rem 1rem 4rem !important; }
  [data-testid="stSidebar"] { width:min(11.5rem,48vw) !important; min-width:min(11.5rem,48vw) !important; max-width:min(11.5rem,48vw) !important; }
  [data-testid="stSidebar"] > div:first-child, [data-testid="stSidebar"] [data-testid="stSidebarContent"] { width:100% !important; }
  [data-testid="stSidebar"] [data-testid="stSidebarUserContent"] { padding:1rem .65rem 1.5rem !important; }
  [data-testid="stSidebar"] h2 { font-size:.92rem !important; white-space:nowrap; }
  [data-testid="stSidebar"] [role="radiogroup"] p { font-size:.86rem !important; }
  [data-testid="stSidebar"] [role="radiogroup"] label { min-height:44px !important; padding:.42rem .3rem !important; }
  .ops-hero { padding:.05rem 0 .45rem; margin-bottom:1rem; }
  .ops-hero h1, .ops-dashboard-head h1 { font-size:1.52rem !important; }
  .ops-hero p { font-size:.9rem; }
  .ops-dashboard-head { margin-bottom:1.15rem; }
  .ops-section-gap { height:2rem; }
  .ops-card-grid { grid-template-columns:1.15fr .85fr; gap:.5rem; }
  .ops-card { min-height:104px; padding:.85rem .8rem; border-radius:16px; }
  .ops-card .value { font-size:1.45rem; }
  .ops-card.primary .value { font-size:2.1rem; }
  .ops-card .label { font-size:.8rem; }
  .ops-card .note { font-size:.72rem; }
  [data-testid="stHorizontalBlock"] { gap:.4rem; }
  [data-testid="stTextInput"] input, [data-testid="stTextArea"] textarea,
  [data-baseweb="select"] > div, [data-testid="stDateInput"] input,
  [data-testid="stNumberInput"] input { min-height:44px !important; font-size:16px !important; }
  [data-testid="stMetric"] { min-height:82px !important; }
  [data-testid="stMainBlockContainer"] button { min-height:46px !important; }
  [data-testid="stMainBlockContainer"] [role="radiogroup"] label,
  [data-testid="stMainBlockContainer"] [data-testid="stCheckbox"] label,
  [data-testid="stMainBlockContainer"] [data-testid="stToggle"] label {
    min-height:44px !important; padding:.55rem .35rem !important;
  }
  h1 { font-size:1.55rem !important; } h2 { font-size:1.28rem !important; } h3 { font-size:1.16rem !important; }
  .ops-badge { font-size:.79rem !important; }
  .ops-stat-grid { grid-template-columns:repeat(2,minmax(0,1fr)); }
  .review-stat-grid { grid-template-columns:repeat(4,minmax(0,1fr)); gap:.28rem; }
  .review-stat { min-height:65px; border-radius:12px; padding:.4rem .08rem; }
  .review-stat .label { font-size:.75rem; }
  .review-stat .value { font-size:1.08rem; }
  .compact-stat-grid { grid-template-columns:repeat(2,minmax(0,1fr)) !important; gap:.4rem; }
  .compact-stat { min-height:72px; border-radius:12px; padding:.48rem .25rem; }
  .compact-stat .label { font-size:.78rem; }
  .compact-stat .value { font-size:1rem; }
  .st-key-dashboard_quick_menu [data-testid="stHorizontalBlock"] { display:grid !important; grid-template-columns:repeat(2,minmax(0,1fr)) !important; gap:.4rem !important; }
  .st-key-dashboard_quick_menu [data-testid="column"] { width:100% !important; min-width:0 !important; flex:unset !important; }
  [data-testid="stTabs"] [role="tablist"] { overflow-x:auto; scrollbar-width:thin; }
  [data-testid="stMarkdownContainer"], [data-testid="stCaptionContainer"] { overflow-wrap:anywhere; }
  .stButton>button, .stDownloadButton>button, .stLinkButton>a { min-height:2.85rem; font-size:.95rem !important; }
  .bible-verse .content { font-size:1.03rem; line-height:1.72; }
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def bootstrap() -> None:
    ensure_directories()
    init_db()
    source_count = row("SELECT COUNT(*) AS count FROM source_files")
    if not source_count or source_count["count"] != 0:
        return
    local_sources = list(SOURCE_DIR.glob("*.xlsx"))
    if local_sources:
        with st.spinner("기존 Spreadsheet를 처음 가져오는 중입니다…"):
            migrate(reset=False)
        return
    # The deployable repository must not contain the operational SQLite DB.
    # On a clean Streamlit instance, rebuild it once from the configured
    # read-only Google Sheets instead of publishing personal data in Git.
    previous_status = get_app_meta("last_google_sheets_sync_status", "")
    if previous_status or st.session_state.get("_initial_google_sync_attempted"):
        return
    st.session_state["_initial_google_sync_attempted"] = True
    try:
        try:
            service_account_info = dict(st.secrets["google_service_account"])
        except (FileNotFoundError, KeyError, TypeError):
            service_account_info = None
        with st.spinner("Google Sheets에서 첫 자료를 준비하는 중입니다…"):
            sync_google_sheets(service_account_info=service_account_info)
        st.session_state["flash"] = "Google Sheets 읽기 전용 자료로 첫 화면을 준비했습니다."
    except Exception as exc:
        st.session_state["_initial_google_sync_error"] = str(exc)


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


def hero(title: str, subtitle: str, eyebrow: str = "예배 운영") -> None:
    st.markdown(
        '<div class="ops-hero">'
        f'<div class="eyebrow">{html.escape(eyebrow)}</div>'
        f'<h1>{html.escape(title)}</h1><p>{html.escape(subtitle)}</p></div>',
        unsafe_allow_html=True,
    )


def section_gap() -> None:
    st.markdown('<div class="ops-section-gap" aria-hidden="true"></div>', unsafe_allow_html=True)


def empty_state(message: str) -> None:
    st.markdown(
        f'<div class="ops-empty">{html.escape(message)}</div>',
        unsafe_allow_html=True,
    )


def plain_text(value: object) -> None:
    safe_text = html.escape(str(value or "")).replace("\n", "<br>")
    st.markdown(f'<div class="ops-plain-text">{safe_text}</div>', unsafe_allow_html=True)


def _has_reserved_review_prefix(value: object) -> bool:
    text = str(value or "").lstrip()
    return text.startswith(("[기준 확정]", "[또 발생]", RESOLUTION_COMMENT_PREFIX))


def _unique_option_map(options: list[tuple[str, object]]) -> dict[str, object]:
    """Preserve every option when human-readable labels happen to be identical."""
    normalized = [(str(label).strip() or "선택 항목", value) for label, value in options]
    counts: dict[str, int] = {}
    for label, _ in normalized:
        counts[label] = counts.get(label, 0) + 1
    positions: dict[str, int] = {}
    result: dict[str, object] = {}
    for label, value in normalized:
        positions[label] = positions.get(label, 0) + 1
        display_label = label
        if counts[label] > 1:
            display_label = f"{label} · {positions[label]}/{counts[label]}"
        collision_index = 2
        candidate = display_label
        while display_label in result:
            display_label = f"{candidate} · {collision_index}"
            collision_index += 1
        result[display_label] = value
    return result


def _safe_http_url(value: object) -> str:
    """Return a normalized external URL only for ordinary HTTP(S) links."""
    raw = str(value or "").strip()
    if not raw or len(raw) > 2_000 or any(character.isspace() for character in raw):
        return ""
    if ":" in raw.split("/", 1)[0] and "://" not in raw:
        return ""
    candidate = raw if "://" in raw else f"https://{raw}"
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        return ""
    if parsed.username or parsed.password:
        return ""
    return candidate


def _markdown_label(value: object) -> str:
    return str(value or "").replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _visible_search_results(
    results: list[dict[str, object]],
    allow_team_content: bool,
) -> list[dict[str, object]]:
    if allow_team_content:
        return results
    return [
        item for item in results
        if str(item.get("target_page") or "") != "결정·운영로그"
    ]


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
    today = today_kst()
    weekday = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"][today.weekday()]
    today_label = f"{today.month}월 {today.day}일 {weekday}"
    st.markdown(
        '<div class="ops-dashboard-head">'
        f'<div class="eyebrow">{today_label}</div>'
        '<h1>예배 운영</h1></div>',
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
            st.error(f"Google Sheets 업데이트를 완료하지 못했어요: {exc}")
    if sync_status.startswith("ERROR:"):
        st.warning("마지막 업데이트를 완료하지 못했어요. 이전에 성공한 자료를 그대로 보여드려요.")


def badge(text: str, tone: str = "") -> str:
    safe_tone = tone if tone in {"", "warn", "danger", "gray"} else ""
    return f'<span class="ops-badge {safe_tone}">{html.escape(str(text))}</span>'


def search_excerpt(value: str | None, term: str, width: int = 280) -> str:
    text = " ".join((value or "").split())
    if len(text) <= width:
        return text
    position = text.casefold().find(term.casefold()) if term else -1
    start = max(0, position - 80) if position >= 0 else 0
    end = min(len(text), start + width)
    return ("…" if start else "") + text[start:end] + ("…" if end < len(text) else "")


def dday(event_date: str | None) -> str:
    if not event_date:
        return "날짜 미정"
    delta = (date.fromisoformat(event_date) - today_kst()).days
    if delta == 0:
        return "D-Day"
    return f"D-{delta}" if delta > 0 else f"D+{abs(delta)}"


def next_weekday(base_date: date, weekday: int) -> date:
    """Return today when it is the requested weekday, otherwise the next occurrence."""
    return base_date + timedelta(days=(weekday - base_date.weekday()) % 7)


ATTENDANCE_COUNTED_STATUSES = {"COUNTED", "ESTIMATED", "NO_STREAM"}
ATTENDANCE_CANCELLED_STATUSES = {"CANCELLED"}
ATTENDANCE_STATUS_LABELS = {
    "COUNTED": "집계 완료",
    "PENDING": "미입력",
    "CANCELLED": "예배 취소",
    "NO_STREAM": "온라인 송출 없음",
    "ESTIMATED": "추정 집계",
    "UNKNOWN": "확인 필요",
}


def _attendance_frame() -> pd.DataFrame:
    """Load attendance while remaining compatible with databases created before record_status."""
    data = pd.DataFrame(rows("SELECT * FROM attendance ORDER BY service_date"))
    if data.empty or "service_date" not in data.columns:
        return data
    data["service_date"] = pd.to_datetime(data["service_date"], errors="coerce").dt.normalize()
    data = data[data["service_date"].notna()].copy()
    compact_service_type = data["service_type"].fillna("").astype(str).str.replace(r"\s+", "", regex=True)
    data.loc[compact_service_type == "주일예배", "service_type"] = "주일예배"
    for column in ("online_count", "offline_count", "total_count"):
        if column not in data.columns:
            data[column] = pd.NA
        data[column] = pd.to_numeric(data[column], errors="coerce")

    has_legacy_count = (
        data[["online_count", "offline_count", "total_count"]].fillna(0).gt(0).any(axis=1)
    )
    if "record_status" in data.columns:
        status = data["record_status"].fillna("").astype(str).str.strip().str.upper()
        status = status.replace({
            "COMPLETED": "COUNTED", "VERIFIED": "COUNTED", "집계완료": "COUNTED",
            "MISSING": "PENDING", "미입력": "PENDING", "취소": "CANCELLED",
            "REVIEW_REQUIRED": "UNKNOWN", "확인필요": "UNKNOWN",
        })
        supported_statuses = {
            "COUNTED", "PENDING", "CANCELLED", "NO_STREAM", "ESTIMATED", "UNKNOWN",
        }
        # Preserve an explicit UNKNOWN (including an explicit zero count). Only blank or
        # unsupported status values need the legacy count-based inference below.
        infer_status = ~status.isin(supported_statuses)
    else:
        status = pd.Series("UNKNOWN", index=data.index, dtype="object")
        infer_status = pd.Series(True, index=data.index, dtype="bool")
    # Old imports represented blank cells as zero and had no status. Infer only records
    # whose status is genuinely absent/unsupported; explicit UNKNOWN remains UNKNOWN.
    status = status.where(~(infer_status & has_legacy_count), "COUNTED")
    status = status.where(~(infer_status & ~has_legacy_count), "PENDING")
    data["_record_status"] = status
    data["_counted"] = status.isin(ATTENDANCE_COUNTED_STATUSES)
    data["_cancelled"] = status.isin(ATTENDANCE_CANCELLED_STATUSES)
    return data


def _last_elapsed_sunday(base_date: date | None = None) -> date:
    """Return the most recent Sunday that has fully elapsed."""
    base_date = base_date or today_kst()
    days_since_sunday = (base_date.weekday() - 6) % 7
    if days_since_sunday == 0:
        days_since_sunday = 7
    return base_date - timedelta(days=days_since_sunday)


def _sunday_attendance_snapshot(data: pd.DataFrame | None = None) -> dict[str, object]:
    data = _attendance_frame() if data is None else data
    if data.empty:
        return {"latest": None, "missing_dates": [], "recorded_pending_dates": [], "absent_dates": []}
    sunday = data[data["service_type"] == "주일예배"].copy()
    counted = sunday[sunday["_counted"]].sort_values("service_date", ascending=False)
    latest = counted.iloc[0] if not counted.empty else None
    latest_date = latest["service_date"].date() if latest is not None else None
    last_elapsed = _last_elapsed_sunday()
    start_date = latest_date + timedelta(days=7) if latest_date else last_elapsed
    scheduled_dates = []
    cursor = start_date
    while cursor <= last_elapsed:
        scheduled_dates.append(cursor)
        cursor += timedelta(days=7)

    missing_dates: list[date] = []
    recorded_pending_dates: list[date] = []
    absent_dates: list[date] = []
    for scheduled_date in scheduled_dates:
        same_date = sunday[sunday["service_date"].dt.date == scheduled_date]
        if not same_date.empty and (same_date["_cancelled"].any() or same_date["_counted"].any()):
            continue
        missing_dates.append(scheduled_date)
        if same_date.empty:
            absent_dates.append(scheduled_date)
        else:
            recorded_pending_dates.append(scheduled_date)
    return {
        "latest": latest,
        "missing_dates": missing_dates,
        "recorded_pending_dates": recorded_pending_dates,
        "absent_dates": absent_dates,
    }


def _scheduled_sunday_trend(sunday: pd.DataFrame, count_limit: int | None) -> pd.DataFrame:
    """Build a calendar-continuous series so missing Sundays render as chart gaps."""
    last_elapsed = _last_elapsed_sunday()
    counted = sunday[sunday["_counted"]]
    if not counted.empty:
        latest_counted_date = counted["service_date"].max().date()
        if latest_counted_date <= today_kst():
            last_elapsed = max(last_elapsed, latest_counted_date)
    if count_limit is None:
        first_date = sunday["service_date"].min().date() if not sunday.empty else last_elapsed
        first_date += timedelta(days=(6 - first_date.weekday()) % 7)
    else:
        first_date = last_elapsed - timedelta(days=7 * (count_limit - 1))

    scheduled = []
    cursor = first_date
    while cursor <= last_elapsed:
        same_date = sunday[sunday["service_date"].dt.date == cursor]
        chosen = None
        status = "행 없음"
        if not same_date.empty:
            counted_rows = same_date[same_date["_counted"]]
            if not counted_rows.empty:
                chosen = counted_rows.iloc[-1]
                status = ATTENDANCE_STATUS_LABELS.get(str(chosen["_record_status"]), str(chosen["_record_status"]))
            elif same_date["_cancelled"].any():
                status = "예배 취소"
            else:
                chosen = same_date.iloc[-1]
                status = ATTENDANCE_STATUS_LABELS.get(str(chosen["_record_status"]), "확인 필요")
        is_counted = chosen is not None and bool(chosen["_counted"])
        online_value = chosen["online_count"] if is_counted else pd.NA
        if chosen is not None and str(chosen["_record_status"]) == "NO_STREAM":
            online_value = pd.NA
        scheduled.append({
            "service_date": pd.Timestamp(cursor),
            "offline_count": chosen["offline_count"] if is_counted else pd.NA,
            "online_count": online_value,
            "total_count": chosen["total_count"] if is_counted else pd.NA,
            "record_status_label": status,
        })
        cursor += timedelta(days=7)
    return pd.DataFrame(scheduled)


def _linked_event_onsite_attendance(event: dict[str, object]) -> float | None:
    """Return the representative onsite count for an event's canonical service.

    A service may have multiple events, so service_id is authoritative. event_id is
    retained only as a compatibility fallback for older, unlinked event records.
    """
    service_id = event.get("service_id")
    if service_id is not None:
        linked = row(
            "SELECT offline_count FROM attendance "
            "WHERE service_id=? AND record_status IN ('COUNTED','ESTIMATED','NO_STREAM') "
            "AND offline_count IS NOT NULL "
            "ORDER BY CASE record_status WHEN 'COUNTED' THEN 0 WHEN 'ESTIMATED' THEN 1 ELSE 2 END,id DESC LIMIT 1",
            (service_id,),
        )
    else:
        linked = row(
            "SELECT offline_count FROM attendance "
            "WHERE event_id=? AND record_status IN ('COUNTED','ESTIMATED','NO_STREAM') "
            "AND offline_count IS NOT NULL "
            "ORDER BY CASE record_status WHEN 'COUNTED' THEN 0 WHEN 'ESTIMATED' THEN 1 ELSE 2 END,id DESC LIMIT 1",
            (event.get("id"),),
        )
    if not linked or linked["offline_count"] is None:
        return None
    return float(linked["offline_count"])


def _format_onsite_attendance(value: float | None) -> str:
    if value is None:
        return "없음"
    return f"{int(value)}명" if float(value).is_integer() else f"{value:.1f}명"


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

REVIEW_CATEGORIES = ["반복 이슈", "예배 준비", "음향", "영상", "조명", "무대·진행", "시설·장비", "인력·일정", "자료·콘텐츠", "기타"]
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


def text_secret(name: str) -> str:
    try:
        return str(st.secrets[name]).strip()
    except (FileNotFoundError, KeyError, TypeError):
        return ""


ACCESS_LEVELS = {"VIEWER": 0, "TEAM": 1, "ADMIN": 2}
ACCESS_LABELS = {"VIEWER": "일반 열람", "TEAM": "팀원", "ADMIN": "관리자"}
ACCESS_SESSION_SECONDS = 60 * 60
ACCESS_MAX_FAILURES = 5
ACCESS_LOCK_SECONDS = 10 * 60


def current_access_role() -> str:
    role = str(st.session_state.get("_access_role") or "VIEWER")
    if role not in ACCESS_LEVELS:
        return "VIEWER"
    expires_at = float(st.session_state.get("_access_expires_at") or 0)
    if role != "VIEWER" and (expires_at <= 0 or time.time() >= expires_at):
        st.session_state["_access_role"] = "VIEWER"
        st.session_state.pop("_access_expires_at", None)
        st.session_state["_access_notice"] = "로그인 시간이 지나 일반 열람으로 전환했어요."
        return "VIEWER"
    return role


def has_access(required: str = "TEAM") -> bool:
    return ACCESS_LEVELS[current_access_role()] >= ACCESS_LEVELS[required]


def access_required(required: str, action: str) -> bool:
    """Show a concise permission notice and return whether the action is allowed."""
    if has_access(required):
        return True
    st.info(f"{action} 기능은 {ACCESS_LABELS[required]} 권한으로 로그인하면 사용할 수 있어요.")
    return False


def access_control() -> None:
    """Session-scoped PIN login. Secrets are compared only on the server."""
    team_pin = text_secret("TEAM_ACCESS_PIN")
    admin_pin = text_secret("ADMIN_ACCESS_PIN")
    role = current_access_role()
    with st.expander(f"접근 권한 · {ACCESS_LABELS[role]}"):
        access_notice = st.session_state.pop("_access_notice", "")
        if access_notice:
            st.info(access_notice)
        if role != "VIEWER":
            st.success(f"{ACCESS_LABELS[role]} 권한으로 사용 중입니다.")
            st.caption("보안을 위해 로그인 후 1시간이 지나면 일반 열람으로 전환해요.")
            if st.button("로그아웃", key="access_logout", width="stretch"):
                st.session_state["_access_role"] = "VIEWER"
                st.session_state.pop("_access_expires_at", None)
                st.session_state["_clear_access_pin"] = True
                rerun("일반 열람 모드로 전환했습니다.")
            return
        if not team_pin and not admin_pin:
            st.caption("접근번호가 설정되지 않아 안전한 읽기 전용으로 열립니다.")
            return
        if st.session_state.pop("_clear_access_pin", False):
            st.session_state["access_pin"] = ""
        access_error = st.session_state.pop("_access_error", "")
        if access_error:
            st.error(access_error)
        now = time.time()
        locked_until = float(st.session_state.get("_access_locked_until") or 0)
        locked = locked_until > now
        if locked:
            minutes = max(1, math.ceil((locked_until - now) / 60))
            st.warning(f"접근번호를 여러 번 확인했어요. {minutes}분 뒤 다시 시도해 주세요.")
        entered = st.text_input(
            "팀 접근번호",
            type="password",
            key="access_pin",
            placeholder="접근번호 입력",
            label_visibility="collapsed",
            disabled=locked,
        )
        if st.button("권한 확인", key="access_login", type="primary", width="stretch", disabled=locked):
            if admin_pin and hmac.compare_digest(str(entered or ""), admin_pin):
                st.session_state["_access_role"] = "ADMIN"
                st.session_state["_access_expires_at"] = time.time() + ACCESS_SESSION_SECONDS
                st.session_state["_access_failed_attempts"] = 0
                st.session_state.pop("_access_locked_until", None)
                st.session_state["_clear_access_pin"] = True
                rerun("관리자 권한으로 로그인했습니다.")
            if team_pin and hmac.compare_digest(str(entered or ""), team_pin):
                st.session_state["_access_role"] = "TEAM"
                st.session_state["_access_expires_at"] = time.time() + ACCESS_SESSION_SECONDS
                st.session_state["_access_failed_attempts"] = 0
                st.session_state.pop("_access_locked_until", None)
                st.session_state["_clear_access_pin"] = True
                rerun("팀원 권한으로 로그인했습니다.")
            failures = int(st.session_state.get("_access_failed_attempts") or 0) + 1
            st.session_state["_clear_access_pin"] = True
            if failures >= ACCESS_MAX_FAILURES:
                st.session_state["_access_failed_attempts"] = 0
                st.session_state["_access_locked_until"] = time.time() + ACCESS_LOCK_SECONDS
                st.session_state["_access_error"] = "접근번호 확인을 잠시 멈췄어요. 10분 뒤 다시 시도해 주세요."
            else:
                st.session_state["_access_failed_attempts"] = failures
                remaining = ACCESS_MAX_FAILURES - failures
                st.session_state["_access_error"] = f"접근번호가 맞지 않아요. {remaining}회 더 확인할 수 있어요."
            st.rerun()


@st.cache_data(show_spinner=False, max_entries=4)
def _cached_local_bible(data: bytes) -> LocalBible:
    return parse_local_bible(data)


def review_board_store() -> tuple[GoogleReviewBoardStore | None, str]:
    service_account_info, secret_error = service_account_secret("GOOGLE_REVIEW_BOARD_SERVICE_ACCOUNT")
    if service_account_info is None:
        return None, "게시판 영구 저장 연결정보가 아직 설정되지 않았습니다. " + secret_error
    try:
        credentials_json = json.dumps(service_account_info, ensure_ascii=False)
        return _cached_review_board_store(credentials_json), ""
    except (json.JSONDecodeError, TypeError, ReviewBoardConnectionError) as exc:
        return None, str(exc)


@st.dialog("댓글·진행 상태")
def review_reply_dialog(
    store: GoogleReviewBoardStore,
    item: dict[str, object],
    comments: list[dict[str, object]],
) -> None:
    st.markdown(f"**{item['title']}**")
    with st.form(f"review_reply_dialog_{item['id']}", clear_on_submit=True):
        reply_author = st.text_input(
            "작성자",
            value=st.session_state.get("operator_name", ""),
            placeholder="이름",
        )
        reply_body = st.text_area("댓글 또는 답글", placeholder="확인한 내용이나 진행 상황을 남겨주세요.")
        parent_option_pairs: list[tuple[str, object]] = [("게시글에 새 댓글", "")]
        for comment in comments:
            body_preview = " ".join(str(comment.get("body") or "").split())[:28]
            comment_id = str(comment.get("comment_id") or "")
            parent_option_pairs.append((f"{comment.get('author') or '이름 없음'} · {body_preview}", comment_id))
        parent_options = _unique_option_map(parent_option_pairs)
        parent_label = st.selectbox("답글 대상", list(parent_options))
        statuses = list(REVIEW_STATUS_LABELS)
        next_status = st.selectbox(
            "댓글 등록 후 상태",
            statuses,
            index=statuses.index(str(item["status"])),
            format_func=lambda value: REVIEW_STATUS_LABELS[value],
        )
        if st.form_submit_button("댓글 등록", type="primary", width="stretch"):
            if _has_reserved_review_prefix(reply_body):
                st.error("이 문구는 기준 확정 전용이에요. 일반 댓글 내용으로 다시 적어 주세요.")
            else:
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


@st.dialog("확인사항 해결")
def review_resolve_dialog(
    store: GoogleReviewBoardStore,
    item: dict[str, object],
) -> None:
    st.markdown(f"**{item['title']}**")
    st.caption("해결로 기록한 뒤 현재 목록에서 보관함으로 옮겨요.")
    with st.form(f"review_resolve_dialog_{item['id']}", clear_on_submit=True):
        resolved_by = st.text_input(
            "해결한 사람",
            value=st.session_state.get("operator_name", ""),
            placeholder="이름",
        )
        resolution_note = st.text_input(
            "해결 메모 · 선택",
            placeholder="예: 냉방 시작 시간을 30분 앞당김",
        )
        if st.form_submit_button("해결하고 보관", type="primary", width="stretch"):
            try:
                store.resolve_and_archive_item(
                    str(item["id"]),
                    resolved_by,
                    resolution_note,
                )
                _cached_review_board_snapshot.clear()
                if st.session_state.get("expanded_review_item") == str(item["id"]):
                    st.session_state.pop("expanded_review_item", None)
                rerun("해결 기록을 남기고 보관함으로 옮겼어요.")
            except (ValueError, ReviewBoardConnectionError) as exc:
                st.error(str(exc))


@st.dialog("반복 이슈 기록")
def recurring_issue_create_dialog(store: GoogleReviewBoardStore) -> None:
    st.caption("제목만 적어도 등록됩니다. 담당자·기한 같은 세부 설정은 필요할 때만 일반 확인사항에서 사용하세요.")
    with st.form("new_recurring_issue", clear_on_submit=True):
        title = st.text_input("무슨 문제가 반복되나요?", placeholder="예: 주일예배 때 본당 실내온도가 높음")
        description = st.text_area(
            "상황 메모 · 선택",
            placeholder="처음 발견한 상황이나 바로 한 조치가 있으면 짧게 적어주세요.",
            height=100,
        )
        author = st.text_input(
            "작성자",
            value=st.session_state.get("operator_name", ""),
            placeholder="이름",
        )
        if st.form_submit_button("이슈 등록", type="primary", width="stretch"):
            try:
                store.create_item(title, description, author, "반복 이슈", "NORMAL", "", "")
                _cached_review_board_snapshot.clear()
                rerun("반복 이슈를 등록했습니다. 같은 문제가 생기면 ‘또 발생’을 눌러주세요.")
            except (ValueError, ReviewBoardConnectionError) as exc:
                st.error(str(exc))


@st.dialog("같은 문제 또 발생")
def recurring_issue_repeat_dialog(store: GoogleReviewBoardStore, item: dict[str, object]) -> None:
    st.markdown(f"**{item['title']}**")
    with st.form(f"repeat_issue_{item['id']}", clear_on_submit=True):
        note = st.text_input("메모 · 선택", placeholder="예: 예배 시작 20분 뒤에도 실내가 더웠음")
        author = st.text_input(
            "기록자",
            value=st.session_state.get("operator_name", ""),
            placeholder="이름",
        )
        if st.form_submit_button("또 발생으로 기록", type="primary", width="stretch"):
            body = "[또 발생]" + (f"\n{note.strip()}" if note.strip() else "")
            try:
                store.add_comment(str(item["id"]), author, body, "IN_PROGRESS")
                _cached_review_board_snapshot.clear()
                st.session_state["expanded_review_item"] = str(item["id"])
                rerun("반복 발생 횟수에 추가했습니다.")
            except (ValueError, ReviewBoardConnectionError) as exc:
                st.error(str(exc))


@st.dialog("운영 기준 확정")
def recurring_issue_standard_dialog(store: GoogleReviewBoardStore, item: dict[str, object]) -> None:
    st.markdown(f"**{item['title']}**")
    st.caption("앞으로 같은 상황에서 바로 적용할 수 있도록 한 문장으로 적어주세요.")
    with st.form(f"standard_issue_{item['id']}", clear_on_submit=True):
        standard = st.text_area(
            "앞으로 어떻게 하기로 했나요?",
            placeholder="예: 주일예배 60분 전 냉방을 시작하고, 예배 20분 전 24~25℃인지 확인한다.",
            height=120,
        )
        author = st.text_input(
            "확정한 사람",
            value=st.session_state.get("operator_name", ""),
            placeholder="이름 또는 회의명",
        )
        if st.form_submit_button("기준 확정", type="primary", width="stretch"):
            body = f"[기준 확정]\n{standard.strip()}"
            try:
                store.add_comment(str(item["id"]), author, body, "CONFIRMED")
                _cached_review_board_snapshot.clear()
                st.session_state["expanded_review_item"] = str(item["id"])
                rerun("운영 기준을 확정하고 기록에 남겼습니다.")
            except (ValueError, ReviewBoardConnectionError) as exc:
                st.error(str(exc))


def shared_review_board() -> None:
    store, connection_error = review_board_store()
    if store is None:
        st.markdown("#### 팀 확인 게시판")
        st.error("팀 확인 게시판을 잠시 불러오지 못했어요. 잠시 후 다시 시도해 주세요.")
        if has_access("ADMIN"):
            st.caption(connection_error)
        if st.button("다시 시도", key="review_board_retry_no_store", width="stretch"):
            _cached_review_board_store.clear()
            _cached_review_board_snapshot.clear()
            st.rerun()
        return

    try:
        snapshot = _cached_review_board_snapshot(REVIEW_BOARD_SPREADSHEET_ID, store, True, 500)
    except ReviewBoardConnectionError as exc:
        st.markdown("#### 팀 확인 게시판")
        st.error("팀 확인 게시판을 잠시 불러오지 못했어요. 잠시 후 다시 시도해 주세요.")
        if has_access("ADMIN"):
            st.caption(str(exc))
        if st.button("다시 시도", key="review_board_retry_snapshot", width="stretch"):
            _cached_review_board_snapshot.clear()
            st.rerun()
        return

    counts = {status: int(snapshot["counts"].get(status, 0)) for status in REVIEW_STATUS_LABELS}
    active_count = counts["REVIEW_REQUIRED"] + counts["IN_PROGRESS"]
    current_month = today_kst().strftime("%Y-%m")
    resolution_comments = find_resolution_comments(snapshot.get("raw_comments", []))
    resolved_this_month = len(
        find_resolution_comments(snapshot.get("raw_comments", []), current_month)
    )
    overdue_count = sum(
        1 for item in snapshot["items"]
        if item.get("status") != "CONFIRMED" and item.get("due_date") and str(item["due_date"]) < today_kst().isoformat()
    )
    recurring_items = [item for item in snapshot["items"] if item.get("category") == "반복 이슈"]
    standard_issue_ids = {
        str(item["id"])
        for item in recurring_items
        if any(
            str(comment.get("body") or "").startswith("[기준 확정]")
            for comment in snapshot["comments"].get(str(item["id"]), [])
        )
    }

    st.markdown(f"#### 팀 확인 게시판 · 미완료 {active_count}건")
    st.caption("게시글·댓글·진행 상태는 게시판 전용 Google Sheets에 영구 저장돼요.")

    metrics = [
        ("확인 필요", counts["REVIEW_REQUIRED"]),
        ("진행중", counts["IN_PROGRESS"]),
        ("기한 지남", overdue_count),
        ("이번 달 해결", resolved_this_month),
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
    if st.button("↻ 목록 새로고침", key="refresh_review_board", type="tertiary", width="content"):
        last_refresh = float(st.session_state.get("_last_review_refresh") or 0)
        if time.time() - last_refresh >= 5:
            st.session_state["_last_review_refresh"] = time.time()
            _cached_review_board_snapshot.clear()
            st.rerun()
        else:
            st.caption("방금 새로고침했어요. 잠시 뒤 다시 확인해 주세요.")
    if counts["CONFIRMED"]:
        if st.button(
            f"확인 완료 {counts['CONFIRMED']}건 정리하기",
            key="show_confirmed_review_items",
            type="secondary",
            width="stretch",
        ):
            st.session_state["review_status_filter"] = "확인 완료"
            st.rerun()

    if has_access("TEAM") and resolution_comments:
        raw_item_by_id = {
            str(item.get("item_id") or ""): item
            for item in snapshot.get("raw_items", [])
        }
        with st.expander(f"해결 기록 찾아보기 · 이번 달 {resolved_this_month}건", expanded=False):
            resolution_term = st.text_input(
                "해결 기록 검색",
                placeholder="제목, 담당자, 해결 메모를 입력하세요",
                key="review_resolution_search",
            ).strip().casefold()
            matching_resolutions: list[tuple[dict[str, object], dict[str, object]]] = []
            for comment in resolution_comments:
                item = raw_item_by_id.get(str(comment.get("review_item_id") or ""), {})
                resolution_note = str(comment.get("body") or "").removeprefix(RESOLUTION_COMMENT_PREFIX).strip()
                searchable = " ".join(
                    str(value or "")
                    for value in (
                        item.get("title"),
                        item.get("description"),
                        item.get("category"),
                        item.get("owner"),
                        comment.get("author"),
                        resolution_note,
                    )
                ).casefold()
                if resolution_term and resolution_term not in searchable:
                    continue
                matching_resolutions.append((comment, item))
            matching_resolutions.sort(
                key=lambda pair: str(pair[0].get("created_at") or ""),
                reverse=True,
            )
            if not matching_resolutions:
                empty_state("검색어와 맞는 해결 기록이 없어요.")
            for comment, item in matching_resolutions[:20]:
                resolution_note = str(comment.get("body") or "").removeprefix(RESOLUTION_COMMENT_PREFIX).strip()
                with st.container(border=True):
                    st.markdown(f"**{html.escape(str(item.get('title') or '제목 없음'))}**")
                    st.caption(
                        f"{str(comment.get('created_at') or '')[:10]} · 해결 {comment.get('author') or '이름 없음'}"
                        + (f" · {item.get('category')}" if item.get("category") else "")
                    )
                    if resolution_note and resolution_note != "해결하고 보관했습니다.":
                        plain_text(resolution_note)

    issue_col, standard_col = st.columns(2)
    if issue_col.button(
        f"반복 이슈 {len(recurring_items)}건",
        key="show_recurring_review_items",
        width="stretch",
        disabled=not recurring_items,
    ):
        st.session_state["review_category_filter"] = "반복 이슈"
        st.session_state["review_status_filter"] = "전체 상태"
        st.rerun()
    if standard_col.button(
        f"확정 기준 {len(standard_issue_ids)}건",
        key="show_review_standards",
        width="stretch",
        disabled=not standard_issue_ids,
    ):
        st.session_state["review_category_filter"] = "반복 이슈"
        st.session_state["review_status_filter"] = "확인 완료"
        st.rerun()

    board_search = st.text_input(
        "게시판·확정 기준 검색",
        placeholder="에어컨, 온도, 본당처럼 기억나는 단어를 입력하세요",
        key="review_board_search",
    )
    if board_search:
        st.caption("검색하면 완료된 기록과 댓글 속 확정 기준도 함께 찾아요.")

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
        display_limit = st.selectbox("한 번에 보기", [10, 25, 50], index=1, key="review_display_limit")
    searchable_items = []
    for item in snapshot["items"]:
        enriched = dict(item)
        enriched["comment_text"] = " ".join(
            str(comment.get("body") or "")
            for comment in snapshot["comments"].get(str(item["id"]), [])
        )
        searchable_items.append(enriched)
    effective_status_filter = status_options[selected_status_label]
    if board_search and effective_status_filter == "OPEN":
        effective_status_filter = "ALL"
    review_items = filter_review_items(
        searchable_items,
        status_filter=effective_status_filter,
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
            0 if item.get("due_date") and str(item["due_date"]) < today_kst().isoformat() and item.get("status") != "CONFIRMED" else 1,
            str(item.get("due_date") or "9999-12-31"),
        )
    )
    total_filtered_items = len(review_items)
    review_items = review_items[:display_limit]
    st.markdown(f"**조건에 맞는 확인사항 {total_filtered_items}건 · 현재 {len(review_items)}건 표시**")
    if not review_items:
        empty_state("검색 조건을 바꾸거나 아래에서 새 확인사항을 추가해 보세요.")

    for item in review_items:
        label = REVIEW_STATUS_LABELS[item["status"]]
        priority_label = REVIEW_PRIORITY_LABELS.get(str(item.get("priority")), "일반")
        comments = snapshot["comments"].get(str(item["id"]), [])
        repeat_comments = [
            comment for comment in comments
            if str(comment.get("body") or "").startswith("[또 발생]")
        ]
        standard_comments = [
            comment for comment in comments
            if str(comment.get("body") or "").startswith("[기준 확정]")
        ]
        is_recurring_issue = item.get("category") == "반복 이슈"
        repeat_label = f" · 반복 {1 + len(repeat_comments)}회" if is_recurring_issue else ""
        with st.expander(
            f"[{label}] {item['title']} · {item.get('category') or '기타'}{repeat_label} · 댓글 {item['comment_count']}개",
            expanded=st.session_state.get("expanded_review_item") == str(item["id"]),
        ):
            tone = "danger" if item.get("priority") == "URGENT" else ("warn" if item.get("priority") == "HIGH" else "")
            st.markdown(
                f"{badge(item.get('category') or '기타')} {badge(priority_label, tone)}",
                unsafe_allow_html=True,
            )
            if item["description"]:
                plain_text(item["description"])
            details = []
            if item.get("owner"):
                details.append(f"담당 {item['owner']}")
            if item.get("due_date"):
                due_state = "기한 지남" if str(item["due_date"]) < today_kst().isoformat() and item["status"] != "CONFIRMED" else "기한"
                details.append(f"{due_state} {item['due_date']}")
            if details:
                st.caption(" · ".join(details))
            if standard_comments:
                latest_standard = str(standard_comments[-1].get("body") or "").removeprefix("[기준 확정]").strip()
                if latest_standard:
                    st.success(f"확정 기준 · {latest_standard}")
            st.caption(
                f"등록 {item['created_by']} · {str(item['created_at'])[:16].replace('T', ' ')}"
                + (f" · 최근 확인 {item['updated_by']}" if item["updated_by"] else "")
            )
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
                    comment_body = str(comment.get("body") or "")
                    if comment_body.startswith("[또 발생]"):
                        repeat_note = comment_body.removeprefix("[또 발생]").strip()
                        st.markdown(f"{badge('또 발생', 'warn')} {html.escape(repeat_note or '같은 문제가 다시 발생했습니다.')}", unsafe_allow_html=True)
                    elif comment_body.startswith("[기준 확정]"):
                        standard_note = comment_body.removeprefix("[기준 확정]").strip()
                        st.markdown(f"{badge('기준 확정')} {html.escape(standard_note)}", unsafe_allow_html=True)
                    elif comment_body.startswith(RESOLUTION_COMMENT_PREFIX):
                        resolution_note = comment_body.removeprefix(RESOLUTION_COMMENT_PREFIX).strip()
                        st.markdown(
                            f"{badge('해결')} {html.escape(resolution_note or '해결하고 보관했습니다.')}",
                            unsafe_allow_html=True,
                        )
                    else:
                        plain_text(comment_body)

            if is_recurring_issue and has_access("TEAM"):
                repeat_col, standard_col = st.columns(2)
                if repeat_col.button(
                    "또 발생",
                    key=f"repeat_review_issue_{item['id']}",
                    type="secondary",
                    width="stretch",
                ):
                    recurring_issue_repeat_dialog(store, item)
                if standard_col.button(
                    "기준 변경" if standard_comments else "기준 확정",
                    key=f"standard_review_issue_{item['id']}",
                    type="primary",
                    width="stretch",
                ):
                    recurring_issue_standard_dialog(store, item)
            if has_access("TEAM"):
                reply_col, resolve_col = st.columns([2, 1])
                open_reply = reply_col.button(
                    "의견·댓글" if is_recurring_issue else "댓글·진행 상태",
                    key=f"open_review_reply_{item['id']}",
                    type="secondary",
                    width="stretch",
                )
                open_resolve = resolve_col.button(
                    "해결",
                    key=f"open_review_resolve_{item['id']}",
                    type="primary",
                    width="stretch",
                )
            else:
                open_reply = st.button(
                    "의견·댓글 남기기" if is_recurring_issue else "댓글·진행 상태 남기기",
                    key=f"open_review_reply_{item['id']}",
                    type="secondary" if is_recurring_issue else "primary",
                    width="stretch",
                )
                open_resolve = False
            if open_reply:
                review_reply_dialog(store, item, comments)
            if open_resolve:
                review_resolve_dialog(store, item)

    section_gap()
    st.caption("누구나 새 확인사항과 댓글을 남길 수 있어요. 작성자 이름을 함께 적어 주세요.")
    recurring_col, general_col = st.columns(2)
    if recurring_col.button(
        "＋ 반복 이슈 기록",
        key="open_recurring_issue_form",
        type="primary",
        width="stretch",
    ):
        recurring_issue_create_dialog(store)
    if general_col.button(
        "＋ 일반 확인사항",
        key="open_review_item_form",
        type="secondary",
        width="stretch",
    ):
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

    if has_access("ADMIN"):
        board_admin = st.expander("게시판 데이터 관리")
    else:
        board_admin = None
    if board_admin is not None:
        with board_admin:
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
                    file_name=f"joyful_review_board_{today_kst().isoformat()}.json",
                    mime="application/json",
                    width="stretch",
                )
            sheet_col.link_button(
                "Google Sheets에서 보기",
                f"https://docs.google.com/spreadsheets/d/{REVIEW_BOARD_SPREADSHEET_ID}/edit",
                width="stretch",
            )
            archived_items = [
                item for item in snapshot.get("raw_items", [])
                if str(item.get("archived_at") or "").strip()
            ]
            if archived_items:
                st.markdown("**보관한 확인사항 다시 열기**")
                restore_map = _unique_option_map([
                    (
                        f"{item.get('title') or '제목 없음'} · {str(item.get('archived_at'))[:10]}",
                        str(item.get("item_id")),
                    )
                    for item in archived_items
                ])
                restore_label = st.selectbox("다시 열 항목", list(restore_map), key="review_restore_item")
                restore_author = st.text_input(
                    "다시 연 사람",
                    value=st.session_state.get("operator_name", ""),
                    key="review_restore_author",
                )
                if st.button("선택 항목 다시 열기", key="restore_review_item", width="stretch"):
                    try:
                        store.restore_item(restore_map[restore_label], restore_author)
                        _cached_review_board_snapshot.clear()
                        st.session_state["review_status_filter"] = "확인 필요"
                        rerun("보관한 확인사항을 확인 필요 상태로 다시 열었어요.")
                    except (ValueError, ReviewBoardConnectionError) as exc:
                        st.error(str(exc))


def sidebar() -> str:
    with st.sidebar:
        st.markdown("## 조이풀교회")
        st.caption("예배 운영 · 지식관리")
        st.markdown("---")
        primary_menu_items = [
            "대시보드",
            "예배 인원 현황",
            "팀 확인",
            "행사",
            "성경 검색",
            "교회력",
            "전체 검색",
        ]
        secondary_menu_items = ["매뉴얼", "결정·운영로그", "보관함", "데이터·백업"]
        menu_labels = {
            "대시보드": "대시보드",
            "팀 확인": "팀 확인",
            "교회력": "교회력",
            "행사": "행사",
            "매뉴얼": "매뉴얼",
            "결정·운영로그": "결정·운영 기록",
            "예배 인원 현황": "예배 인원 현황",
            "성경 검색": "성경 검색",
            "전체 검색": "전체 검색",
            "보관함": "보관함",
            "데이터·백업": "데이터·백업",
        }
        pending_nav = st.session_state.pop("_navigate_to", None)
        if pending_nav in primary_menu_items:
            st.session_state["main_nav"] = pending_nav
            st.session_state.pop("_secondary_nav", None)
        elif pending_nav in secondary_menu_items:
            st.session_state["_secondary_nav"] = pending_nav
        if st.session_state.get("main_nav") not in primary_menu_items:
            st.session_state["main_nav"] = "대시보드"
        nav = st.radio(
            "메뉴",
            primary_menu_items,
            label_visibility="collapsed",
            key="main_nav",
            format_func=lambda value: menu_labels[value],
        )
        previous_nav = st.session_state.get("_last_main_nav")
        if previous_nav is not None and previous_nav != nav:
            st.session_state.pop("_secondary_nav", None)
        st.session_state["_last_main_nav"] = nav
        with st.expander("더 보기", expanded=st.session_state.get("_secondary_nav") is not None):
            if st.session_state.get("_secondary_nav") and st.button(
                f"← {menu_labels[nav]}로 돌아가기",
                key="sidebar_return_primary",
                width="stretch",
            ):
                st.session_state.pop("_secondary_nav", None)
                st.rerun()
            for page in secondary_menu_items:
                if page == "결정·운영로그" and not has_access("TEAM"):
                    continue
                if page in {"보관함", "데이터·백업"} and not has_access("ADMIN"):
                    continue
                marker = "• " if st.session_state.get("_secondary_nav") == page else ""
                if st.button(
                    marker + menu_labels[page],
                    key=f"sidebar_secondary_{page}",
                    width="stretch",
                ):
                    navigate(page)
        st.markdown("---")
        if st.session_state.pop("_clear_quick_search", False):
            st.session_state["quick_search"] = ""
        with st.expander("빠른 검색", expanded=False):
            with st.form("sidebar_quick_search_form"):
                quick = st.text_input(
                    "검색어",
                    placeholder="세례, 성찬, 마이크…",
                    key="quick_search",
                    label_visibility="collapsed",
                )
                quick_submitted = st.form_submit_button("검색", width="stretch")
        if quick_submitted and quick.strip():
            st.session_state["search_term"] = quick.strip()
            navigate("전체 검색")
        access_control()
        if has_access("TEAM"):
            with st.expander("내 이름 설정"):
                st.text_input(
                    "게시판 작성자 이름",
                    placeholder="예: 홍길동",
                    key="operator_name",
                    help="이 브라우저를 사용하는 동안 게시글과 댓글 작성자에 자동 입력됩니다.",
                )
        st.caption("원본 Sheets 읽기 전용 · 게시판 영구 저장")
        st.caption(f"버전 {APP_VERSION}")
        return str(st.session_state.get("_secondary_nav") or nav)


def review_board_page() -> None:
    hero("팀 확인", "확인할 일과 진행 상황을 한곳에서 나눠 봐요.")
    shared_review_board()


def review_board_summary() -> None:
    """대시보드에서는 게시판의 핵심 수치와 우선 항목만 보여줍니다."""
    store, connection_error = review_board_store()
    st.subheader("팀 확인")
    if store is None:
        empty_state("팀 게시판을 연결하면 확인할 일과 댓글이 여기에 보여요.")
        if has_access("ADMIN"):
            st.caption(connection_error)
        return
    try:
        snapshot = _cached_review_board_snapshot(REVIEW_BOARD_SPREADSHEET_ID, store, True, 500)
    except ReviewBoardConnectionError as exc:
        empty_state("팀 게시판 연결을 확인하고 있어요. 잠시 뒤 다시 열어 주세요.")
        if has_access("ADMIN"):
            st.caption(str(exc))
        return

    items = snapshot["items"]
    counts = snapshot["counts"]
    today_text = today_kst().isoformat()
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
            str(item.get("updated_at") or item.get("created_at") or "0000-00-00"),
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
        st.caption("긴급·중요 확인사항을 모두 확인했어요.")
    recurring_items = [item for item in items if item.get("category") == "반복 이슈"]
    open_recurring_count = sum(1 for item in recurring_items if item.get("status") != "CONFIRMED")
    confirmed_standard_count = sum(
        1 for item in recurring_items
        if any(
            str(comment.get("body") or "").startswith("[기준 확정]")
            for comment in snapshot["comments"].get(str(item["id"]), [])
        )
    )
    if recurring_items:
        if st.button(
            f"반복 이슈 {open_recurring_count}건 · 확정 기준 {confirmed_standard_count}건 보기",
            key="open_recurring_review_items",
            type="tertiary",
            width="stretch",
        ):
            st.session_state["review_category_filter"] = "반복 이슈"
            st.session_state["review_status_filter"] = "전체 상태"
            navigate("팀 확인")
    if st.button("게시판 전체 보기", key="open_full_review_board", type="tertiary", width="stretch"):
        navigate("팀 확인")


def dashboard_page() -> None:
    dashboard_header()
    today_date = today_kst()
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
    _dash_stats = row(
        """SELECT
            SUM(CASE WHEN t.status<>'DONE' AND ((t.due_date IS NOT NULL AND t.due_date<=?) OR t.priority='HIGH') THEN 1 ELSE 0 END) AS action_count,
            SUM(CASE WHEN t.status<>'DONE' AND t.due_date IS NOT NULL AND t.due_date<? THEN 1 ELSE 0 END) AS overdue_count,
            SUM(CASE WHEN t.status='BLOCKED' THEN 1 ELSE 0 END) AS blocked_count,
            SUM(CASE WHEN t.status<>'DONE' AND t.priority='HIGH' AND COALESCE(TRIM(t.owner),'')='' THEN 1 ELSE 0 END) AS ownerless_high
        FROM tasks t JOIN events e ON e.id=t.event_id
        WHERE t.archived_at IS NULL AND e.archived_at IS NULL AND e.status NOT IN ('COMPLETED','CANCELLED')""",
        (week_end, today),
    ) or {}
    action_count = int(_dash_stats.get("action_count") or 0)
    overdue_count = int(_dash_stats.get("overdue_count") or 0)
    blocked_count = int(_dash_stats.get("blocked_count") or 0)
    ownerless_high = int(_dash_stats.get("ownerless_high") or 0)
    recheck_count = (row("SELECT COUNT(*) AS count FROM operation_logs WHERE archived_at IS NULL AND needs_recheck=1") or {}).get("count", 0)
    needs_review = (row("SELECT COUNT(*) AS count FROM unresolved_imports WHERE status='OPEN' AND quality='Needs Review'") or {}).get("count", 0)
    sunday_date = next_weekday(today_date, 6)
    friday_date = next_weekday(today_date, 4)
    active_calendar_id = get_app_meta("last_google_calendar_id", "")
    calendar_items = rows(
        "SELECT * FROM church_calendar_events WHERE archived_at IS NULL AND status<>'CANCELLED' AND start_date>=? "
        "AND (?='' OR calendar_id=?) ORDER BY start_date,id LIMIT 6",
        (today, active_calendar_id, active_calendar_id),
    )

    st.markdown('<div class="ops-section-title">다음 정기예배</div>', unsafe_allow_html=True)
    worship_cards = [
        ("주일예배", dday(sunday_date.isoformat()), sunday_date.strftime("%Y.%m.%d · 일요일")),
        ("금요예배", dday(friday_date.isoformat()), friday_date.strftime("%Y.%m.%d · 금요일")),
    ]
    worship_html = '<div class="ops-card-grid">' + "".join(
        f'<div class="ops-card{" primary" if index == 0 else ""}"><div class="label">{label}</div>'
        f'<div class="value">{value}</div><div class="note">{note}</div></div>'
        for index, (label, value, note) in enumerate(worship_cards)
    ) + "</div>"
    st.markdown(worship_html, unsafe_allow_html=True)

    attendance_snapshot = _sunday_attendance_snapshot()
    latest_attendance = attendance_snapshot["latest"]
    missing_attendance_dates = attendance_snapshot["missing_dates"]
    if latest_attendance is not None:
        latest_attendance_date = latest_attendance["service_date"].strftime("%m.%d")
        latest_onsite = int(latest_attendance["offline_count"]) if pd.notna(latest_attendance["offline_count"]) else 0
        latest_online = int(latest_attendance["online_count"]) if pd.notna(latest_attendance["online_count"]) else 0
        latest_online_label = "송출 없음" if str(latest_attendance["_record_status"]) == "NO_STREAM" else str(latest_online)
        if missing_attendance_dates:
            attendance_label = (
                f"주일 자료 {len(missing_attendance_dates)}회 확인이 필요해요 · "
                f"최근 {latest_attendance_date} 현장 {latest_onsite}명 · 온라인 {latest_online_label}"
            )
        else:
            attendance_label = (
                f"주일 {latest_attendance_date} · 현장 {latest_onsite}명 · "
                f"온라인 {latest_online_label} · 예배 인원 보기"
            )
    elif missing_attendance_dates:
        attendance_label = (
            f"주일 자료 {len(missing_attendance_dates)}회 확인이 필요해요 · "
            "인원 집계를 완료하면 최근 현황이 보여요"
        )
    else:
        attendance_label = "주일예배 자료를 확인하면 최근 인원이 여기에 보여요"
    with st.container(key="dashboard_attendance_summary"):
        if st.button(attendance_label, key="dashboard_attendance_open", width="stretch"):
            navigate("예배 인원 현황")

    lineup_rows = rows(
        "SELECT services.service_date,services.service_type,assignments.role,members.name "
        "FROM assignments JOIN services ON services.id=assignments.service_id "
        "JOIN members ON members.id=assignments.member_id "
        "WHERE services.service_date IN (?,?) ORDER BY services.service_date,assignments.role,members.name",
        (friday_date.isoformat(), sunday_date.isoformat()),
    )
    if lineup_rows:
        with st.expander(f"이번 주 예배 담당 · {len(lineup_rows)}명", expanded=False):
            current_service = None
            for assignment in lineup_rows:
                service_label = f"{assignment['service_date']} · {assignment['service_type']}"
                if service_label != current_service:
                    st.markdown(f"**{service_label}**")
                    current_service = service_label
                st.markdown(f"- {html.escape(str(assignment['role']))} · {html.escape(str(assignment['name']))}")
    else:
        st.caption("이번 주 엔지니어 라인업을 업데이트하면 여기에 보여요.")

    section_gap()
    review_board_summary()

    section_gap()
    st.markdown('<div class="ops-section-title">바로가기</div>', unsafe_allow_html=True)
    quick_manual_rows = rows(
        "SELECT id,source_sheet FROM manuals WHERE status='CURRENT' AND archived_at IS NULL "
        "AND source_sheet IN ('주일 세팅 타임테이블','금요집회 세팅 타임테이블','항시 체크 비품') "
        "ORDER BY id DESC"
    )
    quick_manual_ids: dict[str, int] = {}
    for item in quick_manual_rows:
        quick_manual_ids.setdefault(str(item["source_sheet"]), int(item["id"]))
    quick_actions = [
        ("주일 준비", "주일 세팅 타임테이블", "매뉴얼"),
        ("금요 준비", "금요집회 세팅 타임테이블", "매뉴얼"),
        ("상시 비품", "항시 체크 비품", "매뉴얼"),
        ("팀 확인", None, "팀 확인"),
    ]
    with st.container(key="dashboard_quick_menu"):
        quick_cols = st.columns(4)
        for column, (label, source_sheet, target_page) in zip(quick_cols, quick_actions):
            if column.button(label, key=f"quick_{target_page}_{source_sheet or 'attendance'}", width="stretch"):
                if source_sheet and quick_manual_ids.get(source_sheet):
                    navigate("매뉴얼", "selected_manual", quick_manual_ids[source_sheet])
                else:
                    navigate(target_page)

    section_gap()
    st.markdown('<div class="ops-section-title">다가오는 일정</div>', unsafe_allow_html=True)
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
        if st.button("교회력 전체 보기", key="dashboard_open_calendar", type="tertiary", width="stretch"):
            navigate("교회력")
    else:
        st.markdown(
            '<div class="ops-empty">Google Calendar를 연결하면 가까운 교회력 일정부터 여기에 보여요.</div>',
            unsafe_allow_html=True,
        )
        if st.button("캘린더 연결", key="dashboard_connect_calendar", type="tertiary", width="stretch"):
            navigate("교회력")

    st.markdown("##### 특별행사")
    if not upcoming:
        st.markdown(
            '<div class="ops-empty">특별행사를 만들면 준비 일정과 진행 상황이 여기에 보여요.</div>',
            unsafe_allow_html=True,
        )
        if st.button("행사 만들기", key="dashboard_create_event", width="stretch"):
            navigate("행사")
    for event in upcoming:
        ready = readiness(event["id"])
        button_label = f"{event['title']}  ·  {dday(event['event_date'])}  ·  준비도 {ready['percent']}%"
        if st.button(button_label, key=f"dashboard_event_{event['id']}", width="stretch"):
            navigate("행사", "selected_event", event["id"])

    section_gap()
    st.markdown(f'<div class="ops-section-title">지금 할 일 · {action_count}건</div>', unsafe_allow_html=True)
    if not action_tasks:
        st.markdown(
            '<div class="ops-empty">7일 안에 처리할 준비업무를 모두 확인했어요.</div>',
            unsafe_allow_html=True,
        )
    for task in action_tasks:
        is_overdue = bool(task["due_date"] and task["due_date"] < today)
        due_label = f"기한 지남 · {task['due_date']}" if is_overdue else (task["due_date"] or "기한 미정")
        button_label = f"{task['title']}  ·  {task['event_title']}  ·  {due_label}"
        if st.button(button_label, key=f"dashboard_task_{task['id']}", width="stretch"):
            navigate("행사", "selected_event", task["event_id"])

    section_gap()
    with st.expander("시스템 자동 점검 보기"):
        alerts = [
            ("기한 지남", f"{overdue_count}건"),
            ("보류 업무", f"{blocked_count}건"),
            ("담당자 미정", f"{ownerless_high}건"),
        ]
        if has_access("TEAM"):
            alerts.append(("재확인 로그", f"{recheck_count}건"))
        compact_stats(alerts, columns=len(alerts))
        if needs_review and has_access("ADMIN"):
            note_col, button_col = st.columns([.82, .18])
            note_col.caption(f"원본 이관 데이터 중 사람이 확인할 항목이 {needs_review}건 있습니다. 데이터 관리 화면에서 검토합니다.")
            if button_col.button("데이터 확인", width="stretch"):
                navigate("데이터·백업")

    if has_access("ADMIN"):
        with st.expander("관리자 · 원본 데이터 업데이트", expanded=False):
            st.caption("Google Sheets 원본을 갱신할 때만 사용합니다. 일반 사용자는 누르지 않아도 됩니다.")
            google_sheets_sync_bar()


def event_detail(event_id: int) -> None:
    event = row(
        "SELECT events.*,event_templates.title AS template_title FROM events LEFT JOIN event_templates ON event_templates.id=events.event_template_id WHERE events.id=?",
        (event_id,),
    )
    if not event:
        st.error("행사를 찾을 수 없어요.")
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
                    new_date = st.date_input("새 행사 날짜", value=today_kst())
                    if st.form_submit_button("이전 행사 기준으로 생성", width="stretch"):
                        new_id = clone_event(event_id, new_title, new_date)
                        st.session_state["selected_event"] = new_id
                        rerun("체크리스트 구조를 복제해 새 행사를 만들었습니다.")
            if has_access("ADMIN") and st.button("행사 보관", type="secondary", key=f"archive_event_{event_id}", width="stretch"):
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
            empty_state("아래에서 첫 체크리스트 업무를 추가해 보세요.")
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
                due = st.date_input("기한", value=event["event_date"] and date.fromisoformat(event["event_date"]) or today_kst())
                dependencies = _unique_option_map([
                    ("없음", None),
                    *((str(item["title"]), item["id"]) for item in task_rows),
                ])
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
            empty_state("같은 이름 계열의 이전 행사가 생기면 준비 내용이 자동으로 연결돼요.")
        else:
            st.markdown(f"### 이전 행사: {previous['title']}")
            prev_ready = readiness(previous["id"])
            curr_att = _linked_event_onsite_attendance(event)
            prev_att = _linked_event_onsite_attendance(previous)
            comparison = pd.DataFrame([
                {"항목": "행사일", "이전": previous["event_date"], "현재": event["event_date"]},
                {"항목": "체크리스트 수", "이전": prev_ready["total"], "현재": ready["total"]},
                {"항목": "완료율", "이전": f"{prev_ready['percent']}%", "현재": f"{ready['percent']}%"},
                {"항목": "연결 현장 참석", "이전": _format_onsite_attendance(prev_att), "현재": _format_onsite_attendance(curr_att)},
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
                st.caption("이전 행사를 회고하면 다음 준비 때 함께 보여요.")

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
            st.caption("매뉴얼을 연결하면 관련 준비 기준을 함께 볼 수 있어요.")
        for item in manuals:
            st.markdown(f"- **{item['title']}** · v{item['version']} · {item['current_standard'] or '현재 기준 미기록'}")
        st.markdown("#### 결정 및 운영 로그")
        for item in decisions:
            st.markdown(f"- **결정:** {item['title']} — {item['reason'] or '이유 미기록'}")
        for item in logs:
            st.markdown(f"- **{item['log_type']}:** {item['title']} — {item['result'] or item['description'] or ''}")
        st.markdown("#### 참고자료")
        for item in refs:
            safe_url = _safe_http_url(item["url"])
            reference_text = f"{_markdown_label(item['title'])} {item['reference_time'] or ''}".strip()
            st.markdown(f"- [{reference_text}]({safe_url})" if safe_url else f"- {reference_text}")
        with st.expander("참고 URL 추가"):
            with st.form(f"ref_{event_id}"):
                ref_title = st.text_input("제목")
                ref_url = st.text_input("URL")
                ref_type = st.selectbox("유형", ["YouTube", "Google Drive", "Google Sheets", "웹 URL", "기타"])
                ref_time = st.text_input("참고 시점", placeholder="예: 42:13")
                ref_desc = st.text_area("설명")
                if st.form_submit_button("참고자료 추가"):
                    safe_ref_url = _safe_http_url(ref_url)
                    if ref_title and safe_ref_url:
                        add_reference_record({
                            "title": ref_title,
                            "url": safe_ref_url,
                            "ref_type": ref_type,
                            "reference_time": ref_time,
                            "description": ref_desc,
                            "event_id": event_id,
                        })
                        rerun("참고자료를 연결했습니다.")
                    elif not ref_title:
                        st.error("제목을 입력해 주세요.")
                    else:
                        st.error("http:// 또는 https:// 형식의 안전한 URL을 입력해 주세요.")

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


def event_readonly_detail(event_id: int) -> None:
    event = row("SELECT * FROM events WHERE id=?", (event_id,))
    if not event:
        st.error("행사를 찾을 수 없어요.")
        return
    ready = readiness(event_id)
    st.markdown(f"## {event['title']}")
    st.markdown(
        f"{badge(status_ko(event['status']))} {badge(dday(event['event_date']), 'gray')} "
        f"{badge(quality_ko(event['data_quality']))}",
        unsafe_allow_html=True,
    )
    compact_stats([
        ("준비도", f"{ready['percent']}%"),
        ("완료", f"{ready['done']}건"),
        ("미완료", f"{ready['open']}건"),
        ("중요 미완료", f"{ready['high_open']}건"),
    ])
    st.caption(
        " · ".join(filter(None, [event["event_date"] or "날짜 미정", event["category"] or "기타", f"담당 {event['owner']}" if event["owner"] else "담당 미정"]))
    )
    if event["description"]:
        st.write(event["description"])
    task_rows = rows(
        "SELECT * FROM tasks WHERE event_id=? AND archived_at IS NULL "
        "ORDER BY CASE status WHEN 'DONE' THEN 1 ELSE 0 END, due_date,id",
        (event_id,),
    )
    st.markdown("### 체크리스트")
    if not task_rows:
        empty_state("체크리스트를 추가하면 준비 진행 상황이 여기에 보여요.")
    for task in task_rows:
        status_mark = "✓" if task["status"] == "DONE" else "○"
        st.markdown(f"{status_mark} **{task['title']}** · {task['due_date'] or task['source_timing'] or '기한 미정'}")
        if task["description"]:
            st.caption(task["description"][:240])
    st.caption("팀원 권한으로 로그인하면 수정과 상태 변경을 할 수 있어요.")


def events_page() -> None:
    hero("행사", "특별예배의 준비부터 회고까지 이어서 관리해요.")
    if has_access("TEAM"):
        st.caption("저장 안내 · 행사와 체크리스트 변경은 현재 로컬 DB에 저장됩니다. 영구 DB 이전 전에는 중요한 내용을 별도 보관하세요.")
    list_tab, create_tab, templates_tab = st.tabs(["행사 목록", "새 행사", "체크리스트 템플릿"])
    with list_tab:
        event_today = today_kst().isoformat()
        active = rows(
            "SELECT * FROM events WHERE archived_at IS NULL ORDER BY "
            "CASE status WHEN 'ACTIVE' THEN 0 WHEN 'PLANNING' THEN 1 WHEN 'COMPLETED' THEN 2 ELSE 3 END, "
            "CASE WHEN event_date>=? THEN 0 ELSE 1 END, "
            "CASE WHEN event_date>=? THEN event_date END ASC, event_date DESC, id DESC",
            (event_today, event_today),
        )
        if not active:
            empty_state("새 행사를 만들면 준비 현황이 여기에 보여요.")
        else:
            status_col, category_col = st.columns(2)
            event_status_options = {
                "진행 예정": "OPEN",
                "준비중": "PLANNING",
                "진행중": "ACTIVE",
                "종료": "COMPLETED",
                "취소": "CANCELLED",
                "전체 상태": "ALL",
            }
            selected_status_label = status_col.selectbox("상태", list(event_status_options), key="event_status_filter")
            event_categories = ["전체", *sorted({str(item["category"] or "기타") for item in active})]
            selected_event_category = category_col.selectbox("분류", event_categories, key="event_category_filter")
            event_search = st.text_input("행사 검색", placeholder="행사명이나 담당자", key="event_search").strip().casefold()
            filtered_active = []
            for item in active:
                selected_status = event_status_options[selected_status_label]
                if selected_status == "OPEN" and item["status"] not in {"PLANNING", "ACTIVE"}:
                    continue
                if selected_status not in {"ALL", "OPEN"} and item["status"] != selected_status:
                    continue
                if selected_event_category != "전체" and str(item["category"] or "기타") != selected_event_category:
                    continue
                if event_search and event_search not in f"{item['title']} {item['owner'] or ''} {item['description'] or ''}".casefold():
                    continue
                filtered_active.append(item)
            if not filtered_active:
                empty_state("검색 조건을 바꾸거나 새 행사를 만들어 보세요.")
            else:
                options = _unique_option_map([
                    (
                        f"{item['event_date'] or '날짜 미정'} · {item['title']} · {status_ko(item['status'])}",
                        item["id"],
                    )
                    for item in filtered_active
                ])
                event_ids = list(options.values())
                requested_event = st.session_state.get("selected_event")
                selected_index = event_ids.index(requested_event) if requested_event in event_ids else 0
                selected_label = st.selectbox("행사 선택", list(options), index=selected_index, key="selected_event_selector")
                st.session_state["selected_event"] = options[selected_label]
                if has_access("TEAM"):
                    event_detail(options[selected_label])
                else:
                    event_readonly_detail(options[selected_label])
    with create_tab:
        if not has_access("TEAM"):
            st.info("팀원 권한으로 로그인하면 새 행사를 등록할 수 있어요.")
        templates = rows("SELECT * FROM event_templates WHERE status='CURRENT' ORDER BY category,title")
        template_map = _unique_option_map([
            ("템플릿 없음", None),
            *((f"{item['title']} ({item['category']})", item["id"]) for item in templates),
        ])
        with st.form("create_event"):
            title = st.text_input("행사명", placeholder="예: 2027 기도의 승부")
            event_date = st.date_input("행사 날짜", value=today_kst())
            category = st.selectbox("카테고리", ["특별예배", "특별순서", "정기예배", "행사", "기타"])
            template_label = st.selectbox("체크리스트 템플릿", list(template_map))
            owner = st.text_input("담당자")
            description = st.text_area("메모")
            if st.form_submit_button("행사 생성", type="primary", disabled=not has_access("TEAM")):
                if not has_access("TEAM"):
                    st.error("팀원 권한이 필요합니다.")
                    return
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
        if templates:
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
        else:
            empty_state("반복해서 준비할 행사가 있다면 아래에서 템플릿을 만들어 보세요.")
        with st.expander("새 템플릿 만들기"):
            manuals = rows("SELECT id,title FROM manuals WHERE status='CURRENT' ORDER BY title")
            manual_map = _unique_option_map([
                ("연결 안 함", None),
                *((str(item["title"]), item["id"]) for item in manuals),
            ])
            with st.form("new_template"):
                title = st.text_input("템플릿명")
                category = st.text_input("카테고리", value="특별예배")
                description = st.text_area("설명")
                manual_label = st.selectbox("관련 매뉴얼", list(manual_map))
                if st.form_submit_button("템플릿 생성", disabled=not has_access("TEAM")):
                    if not has_access("TEAM"):
                        st.error("팀원 권한이 필요합니다.")
                        return
                    if title:
                        create_event_template(title, category, description, manual_map[manual_label])
                        rerun("체크리스트 템플릿을 생성했습니다.")
        if templates:
            with st.expander("템플릿에 업무 추가"):
                template_map = _unique_option_map([
                    (str(item["title"]), item["id"])
                    for item in templates
                ])
                with st.form("new_task_template"):
                    template_label = st.selectbox("템플릿", list(template_map))
                    task_title = st.text_input("업무명")
                    task_description = st.text_area("설명")
                    source_timing = st.text_input("준비시점 표기", placeholder="예: D-14")
                    due_offset = st.number_input("행사일 기준 일수", value=-7, step=1)
                    priority = st.selectbox("중요도", ["HIGH", "MEDIUM", "LOW"], index=1, format_func=priority_ko)
                    owner = st.text_input("기본 담당자")
                    if st.form_submit_button("템플릿 업무 추가", disabled=not has_access("TEAM")):
                        if not has_access("TEAM"):
                            st.error("팀원 권한이 필요합니다.")
                            return
                        if task_title:
                            add_task_template(template_map[template_label], task_title, task_description, source_timing, int(due_offset), priority, owner)
                            rerun("템플릿 업무를 추가했습니다.")


def manual_create_form() -> None:
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


def manuals_page() -> None:
    hero("매뉴얼", "필요한 준비 내용과 운영 기준을 빠르게 찾아봐요.", "지식관리")
    if has_access("TEAM"):
        st.caption("저장 안내 · 새 매뉴얼과 개정 내용은 현재 로컬 DB에 저장됩니다. 영구 DB 이전 전에는 중요한 내용을 별도 보관하세요.")
    current, create_tab = st.tabs(["현재 매뉴얼", "새 매뉴얼"])
    with create_tab:
        if access_required("TEAM", "새 매뉴얼 작성"):
            manual_create_form()
    with current:
        manuals = rows(
            "SELECT * FROM manuals WHERE status='CURRENT' AND archived_at IS NULL ORDER BY "
            "CASE source_sheet WHEN '주일 세팅 타임테이블' THEN 0 WHEN '금요집회 세팅 타임테이블' THEN 1 "
            "WHEN '항시 체크 비품' THEN 2 ELSE 3 END, category,title"
        )
        if not manuals:
            empty_state("매뉴얼을 만들거나 Google Sheets 자료를 업데이트해 보세요.")
            return
        requested_manual = st.session_state.get("selected_manual")
        category_options = ["전체", *sorted({str(item["category"] or "기타") for item in manuals})]
        finder_surface = (
            st.expander("다른 매뉴얼 찾기", expanded=False)
            if requested_manual
            else st.container()
        )
        with finder_surface:
            intro_col, reset_col = st.columns([.78, .22])
            intro_col.markdown("### 매뉴얼 찾기")
            if reset_col.button("↺ 처음으로", width="stretch", help="분류·검색·선택을 초기화합니다."):
                st.session_state["manual_category_filter"] = "전체"
                st.session_state["manual_search"] = ""
                st.session_state["_manual_home"] = True
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

        if requested_manual and requested_manual not in {item["id"] for item in filtered_manuals}:
            requested = next((item for item in manuals if item["id"] == requested_manual), None)
            if requested:
                filtered_manuals = [requested, *filtered_manuals]
        show_manual_home = st.session_state.get("_manual_home", requested_manual is None)
        if show_manual_home and not requested_manual and not manual_search and selected_category == "전체":
            st.caption("자주 찾는 매뉴얼을 바로 열거나, 위 검색과 분류를 사용하세요.")
            for item in filtered_manuals[:6]:
                if st.button(
                    f"{item['title']} · {item['category'] or '기타'}",
                    key=f"manual_home_{item['id']}",
                    width="stretch",
                ):
                    st.session_state["selected_manual"] = item["id"]
                    st.session_state["_manual_home"] = False
                    st.rerun()
            return
        if not filtered_manuals:
            empty_state("분류를 전체로 바꾸거나 검색어를 짧게 입력해 보세요.")
            return

        manual_map = _unique_option_map([
            (f"[{item['category']}] {item['title']}", item["id"])
            for item in filtered_manuals
        ])
        manual_ids = list(manual_map.values())
        selected_index = manual_ids.index(requested_manual) if requested_manual in manual_ids else 0
        with finder_surface:
            selected = st.selectbox("매뉴얼 선택", list(manual_map), index=selected_index, key="selected_manual_selector")
            st.caption(f"검색 결과 {len(filtered_manuals)}개")
        manual_id = manual_map[selected]
        st.session_state["selected_manual"] = manual_id
        st.session_state["_manual_home"] = False
        manual = row("SELECT * FROM manuals WHERE id=?", (manual_id,))
        revision = row("SELECT * FROM manual_revisions WHERE manual_id=? AND status='CURRENT' ORDER BY version DESC LIMIT 1", (manual_id,))
        age = None
        if manual["last_verified"]:
            age = (today_kst() - date.fromisoformat(manual["last_verified"][:10])).days
        st.markdown(f"## {manual['title']}")
        version_label = f"v{manual['version']}"
        st.markdown(f"{badge('현재 기준')} {badge(version_label)} {badge(quality_ko(manual['data_quality']), 'warn' if manual['data_quality']=='Needs Review' else '')}", unsafe_allow_html=True)
        if age is None:
            st.warning("검토일을 기록하면 매뉴얼의 최신 상태를 확인할 수 있어요.")
        elif age > 365:
            st.warning(f"마지막 검토: {age}일 전 · 검토 필요")
        else:
            st.caption(f"마지막 검토: {age}일 전 ({manual['last_verified']})")
        if has_access("TEAM") and st.button("현재도 유효함", key=f"verify_{manual_id}"):
            verify_manual(manual_id)
            rerun("내용 변경 없이 검증일을 갱신했습니다.")
        st.markdown("### 한눈에 보기")
        st.info(manual["current_standard"] or "현재 기준을 요약하면 여기에 보여요.")
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
                empty_state("준비 상세를 추가하면 순서대로 여기에 보여요.")

            if references:
                with st.expander(f"관련 참고자료 ({len(references)}개)"):
                    for reference in references:
                        detail = " · ".join(filter(None, [reference["ref_type"], reference["reference_time"], reference["description"]]))
                        safe_url = _safe_http_url(reference["url"])
                        reference_title = _markdown_label(reference["title"])
                        reference_line = f"[{reference_title}]({safe_url})" if safe_url else reference_title
                        st.markdown(f"- {reference_line}" + (f" — {detail}" if detail else ""))

        with standard_tab:
            if revision:
                st.markdown("#### 무엇을 위한 매뉴얼인가요?")
                st.write(revision["what_text"] or "미기록")
                st.markdown("#### 왜 이렇게 운영하나요?")
                st.write(revision["why_text"] or "미기록")
                st.markdown("#### 주의사항")
                st.write(revision["caution"] or "별도 기록 없음")
            else:
                empty_state("운영 기준을 정리하면 이 버전에 함께 보관돼요.")

        with source_tab:
            st.caption("검색과 구조화 과정에서 누락 여부를 확인할 수 있도록 이관된 전체 내용을 보존합니다.")
            if revision and revision["how_text"]:
                st.markdown(revision["how_text"])
            else:
                empty_state("보존된 원본 내용이 생기면 여기에서 확인할 수 있어요.")
        revisions = rows("SELECT * FROM manual_revisions WHERE manual_id=? ORDER BY version DESC", (manual_id,))
        with st.expander(f"버전 기록 ({len(revisions)}개)"):
            for item in revisions:
                st.markdown(f"**v{item['version']} · {status_ko(item['status'])} · {item['created_at'][:10]}**  \n{item['change_summary'] or '변경 설명 없음'}")
        if has_access("TEAM"):
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
        if has_access("ADMIN") and st.button("매뉴얼 보관", key=f"archive_manual_{manual_id}"):
            archive_entity("manuals", manual_id)
            rerun("매뉴얼을 보관함으로 이동했습니다.")


def logs_page() -> None:
    hero("결정·운영 기록", "언제, 왜 기준을 정했는지 간단하게 남겨요.", "지식관리")
    if not access_required("TEAM", "결정·운영 기록"):
        return
    st.caption("저장 안내 · 이 기록은 현재 로컬 DB에 저장됩니다. 영구 DB 이전 전에는 중요한 내용을 별도 보관하세요.")
    decision_tab, operation_tab = st.tabs(["결정 기록", "운영 기록"])
    events = rows("SELECT id,title,event_date FROM events WHERE archived_at IS NULL ORDER BY event_date DESC")
    manuals = rows("SELECT id,title FROM manuals WHERE status='CURRENT' ORDER BY title")
    event_map = _unique_option_map([
        ("연결 안 함", None),
        *((f"{item['event_date'] or ''} {item['title']}", item["id"]) for item in events),
    ])
    manual_map = _unique_option_map([
        ("연결 안 함", None),
        *((str(item["title"]), item["id"]) for item in manuals),
    ])
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
                        add_decision({
                            "event_id": event_map[event_label],
                            "manual_id": manual_map[manual_label],
                            "title": title,
                            "previous_method": previous,
                            "new_method": new,
                            "reason": reason,
                            "decided_at": today_kst().isoformat(),
                            "decided_by": decided_by,
                            "evidence": evidence,
                            "status": status,
                        })
                        rerun("결정과 이유를 기록했습니다.")
        items = rows(
            "SELECT decisions.*,events.title AS event_title,manuals.title AS manual_title FROM decisions "
            "LEFT JOIN events ON events.id=decisions.event_id LEFT JOIN manuals ON manuals.id=decisions.manual_id "
            "WHERE decisions.archived_at IS NULL ORDER BY COALESCE(decided_at,decisions.created_at) DESC"
        )
        if not items:
            empty_state("운영 기준을 정하면 결정 이유와 적용 시점을 여기에 남길 수 있어요.")
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
                occurred = st.date_input("발생일", value=today_kst())
                if st.form_submit_button("로그 저장", type="primary"):
                    if title:
                        add_operation_log({
                            "event_id": event_map[event_label],
                            "log_type": log_type,
                            "title": title,
                            "description": description,
                            "equipment": equipment,
                            "symptom": symptom,
                            "cause": cause,
                            "action_taken": action,
                            "result": result,
                            "needs_recheck": int(recheck),
                            "occurred_at": occurred.isoformat(),
                        })
                        rerun("운영 로그를 저장했습니다.")
        logs = rows("SELECT operation_logs.*,events.title AS event_title FROM operation_logs LEFT JOIN events ON events.id=operation_logs.event_id WHERE operation_logs.archived_at IS NULL ORDER BY COALESCE(occurred_at,operation_logs.created_at) DESC")
        if not logs:
            empty_state("반복해서 확인할 문제나 조치 결과를 여기에 남겨 보세요.")
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


def _attendance_admin_quality(
    data: pd.DataFrame,
    sunday_all: pd.DataFrame,
    absent_dates: list[date],
) -> None:
    with st.expander("관리자 · 데이터 품질"):
        st.caption("Google Sheets 원본은 수정하지 않으며, 누락·상태·원본 값의 차이만 확인합니다.")
        status_quality = sunday_all.groupby("_record_status", as_index=False).size()
        status_quality["_record_status"] = status_quality["_record_status"].map(
            lambda value: ATTENDANCE_STATUS_LABELS.get(str(value), str(value))
        )
        status_quality = status_quality.rename(columns={"_record_status": "집계 상태", "size": "건수"})
        st.dataframe(status_quality, hide_index=True, width="stretch", height=180)
        if absent_dates:
            st.warning(
                "행 자체가 없는 지난 주일 · " + ", ".join(item.strftime("%Y.%m.%d") for item in absent_dates)
            )
        quality = data.groupby("data_quality", as_index=False).size()
        quality["data_quality"] = quality["data_quality"].map(quality_ko)
        quality = quality.rename(columns={"data_quality": "원본 데이터 상태", "size": "건수"})
        st.dataframe(quality, hide_index=True, width="stretch", height=180)
        flagged_mask = (data["data_quality"] == "Needs Review") | data["_record_status"].isin({"PENDING", "UNKNOWN"})
        admin_columns = [
            item for item in [
                "service_date", "service_type", "_record_status", "offline_count", "online_count",
                "total_count", "raw_offline_count", "raw_online_count", "raw_total_count",
                "metric_type", "measurement_note", "notes", "source_sheet", "source_row",
            ] if item in data.columns
        ]
        flagged = data[flagged_mask][admin_columns].copy()
        if not flagged.empty:
            st.warning(f"확인이 필요한 예배 인원 기록 {len(flagged)}건")
            flagged["service_date"] = flagged["service_date"].dt.strftime("%Y.%m.%d")
            if "_record_status" in flagged.columns:
                flagged["_record_status"] = flagged["_record_status"].map(
                    lambda value: ATTENDANCE_STATUS_LABELS.get(str(value), str(value))
                )
            st.dataframe(
                flagged.rename(columns={
                    "service_date": "예배일",
                    "service_type": "예배 종류",
                    "_record_status": "집계 상태",
                    "offline_count": "현장",
                    "online_count": "온라인 지표",
                    "total_count": "합산 참고",
                    "raw_offline_count": "원본 현장",
                    "raw_online_count": "원본 온라인",
                    "raw_total_count": "원본 합계",
                    "metric_type": "측정 방식",
                    "measurement_note": "측정 설명",
                    "notes": "확인 내용",
                    "source_sheet": "원본 시트",
                    "source_row": "원본 행",
                }),
                hide_index=True,
                width="stretch",
                height=240,
            )


def attendance_page() -> None:
    hero("예배 인원 현황", "최근 주일예배 현황과 주차별 변화를 먼저 확인해요.")
    data = _attendance_frame()
    if data.empty:
        empty_state("Google Sheets 자료를 연결하면 최근 주일예배 인원이 여기에 보여요.")
        return
    data["month"] = data["service_date"].dt.to_period("M").astype(str)
    analysis_data = data[data["_counted"]].copy()
    sunday_all = data[data["service_type"] == "주일예배"].sort_values("service_date")
    sunday_data = (
        sunday_all[sunday_all["_counted"]]
        .sort_values("service_date", ascending=False)
        .drop_duplicates("service_date", keep="first")
    )
    snapshot = _sunday_attendance_snapshot(data)
    missing_dates = snapshot["missing_dates"]
    recorded_pending_dates = snapshot["recorded_pending_dates"]
    absent_dates = snapshot["absent_dates"]
    online_metric_defined = False

    latest_count_date = sunday_data.iloc[0]["service_date"].strftime("%Y.%m.%d") if not sunday_data.empty else "없음"
    last_sync = get_app_meta("last_google_sheets_sync_at", "")
    last_sync_label = last_sync.replace("T", " ")[:16] if last_sync else "연동 전"
    latest_meta, sync_meta = st.columns(2)
    latest_meta.caption(f"최신 집계일 · {latest_count_date}")
    sync_meta.caption(f"Google Sheets 마지막 성공 · {last_sync_label}")

    if missing_dates:
        missing_label = ", ".join(item.strftime("%m.%d") for item in missing_dates[-6:])
        detail_parts = []
        if recorded_pending_dates:
            detail_parts.append(f"미입력 {len(recorded_pending_dates)}회")
        if absent_dates:
            detail_parts.append(f"행 없음 {len(absent_dates)}회")
        detail_label = " · ".join(detail_parts)
        st.warning(
            f"자료 지연 · 최근 완료 기록 이후 지난 주일 {len(missing_dates)}회가 미확인입니다"
            f" ({detail_label}) · {missing_label}"
        )

    st.subheader("최근 주일예배")
    if sunday_data.empty:
        empty_state("집계가 완료된 주일예배가 생기면 최근 현황이 여기에 보여요.")
    else:
        latest_sunday = sunday_data.iloc[0]
        previous_sunday = sunday_data.iloc[1] if len(sunday_data) > 1 else None
        latest_total = int(latest_sunday["total_count"]) if pd.notna(latest_sunday["total_count"]) else 0
        latest_offline = int(latest_sunday["offline_count"]) if pd.notna(latest_sunday["offline_count"]) else 0
        latest_status = str(latest_sunday["_record_status"])
        latest_online = int(latest_sunday["online_count"]) if pd.notna(latest_sunday["online_count"]) else None
        comparison_text = "직전 집계 비교 없음"
        if previous_sunday is not None and pd.notna(previous_sunday["offline_count"]):
            interval_days = int((latest_sunday["service_date"] - previous_sunday["service_date"]).days)
            onsite_delta = latest_offline - int(previous_sunday["offline_count"])
            comparison_title = "전주 대비" if interval_days == 7 else f"직전 집계 대비 · {interval_days}일 간격"
            comparison_text = f"{comparison_title} {onsite_delta:+d}명"
        online_text = "송출 없음" if latest_status == "NO_STREAM" else (f"{latest_online}명" if latest_online is not None else "미확인")
        status_text = ATTENDANCE_STATUS_LABELS.get(latest_status, latest_status)
        st.markdown(
            '<div class="ops-attendance">'
            f'<div class="date">{latest_sunday["service_date"].strftime("%Y.%m.%d")} · {html.escape(status_text)}</div>'
            f'<div class="total">현장 {latest_offline}명</div>'
            f'<div class="chips"><span class="ops-chip">온라인 지표 {html.escape(online_text)}</span>'
            f'<span class="ops-chip">합산 참고 {latest_total}명 · 중복 가능</span>'
            f'<span class="ops-chip">{html.escape(comparison_text)}</span></div></div>',
            unsafe_allow_html=True,
        )
        st.caption("온라인 수치는 고유 참석자가 아닌 시청 지표일 수 있어 현장 인원과 분리해서 봅니다.")
        latest_metric_value = latest_sunday.get("metric_type", "")
        latest_metric_type = str(latest_metric_value if pd.notna(latest_metric_value) else "").strip().upper()
        online_metric_defined = bool(latest_metric_type) and latest_metric_type not in {
            "ONSITE_PLUS_ONLINE_UNDEFINED", "LEGACY_COMBINED_COUNTS"
        }
        if latest_metric_type in {"ONSITE_PLUS_ONLINE_UNDEFINED", "LEGACY_COMBINED_COUNTS"}:
            st.caption("⚠ 온라인 지표의 집계 기준을 아직 정하지 않았어요. 합산은 참고치로만 확인해 주세요.")

    if sunday_data.empty:
        if has_access("ADMIN"):
            _attendance_admin_quality(data, sunday_all, absent_dates)
        return

    # 달력상의 7일·30일 평균 대신 집계가 완료된 실제 주일예배 회차를 비교한다.
    recent_four = sunday_data.head(4)
    previous_four = sunday_data.iloc[4:8]
    week_delta = None
    interval_days = None
    if len(sunday_data) > 1 and pd.notna(sunday_data.iloc[0]["offline_count"]) and pd.notna(sunday_data.iloc[1]["offline_count"]):
        interval_days = int((sunday_data.iloc[0]["service_date"] - sunday_data.iloc[1]["service_date"]).days)
        week_delta = int(sunday_data.iloc[0]["offline_count"]) - int(sunday_data.iloc[1]["offline_count"])
    comparison_label = "전주 현장 대비" if interval_days == 7 else (
        f"직전 집계 현장 대비 · {interval_days}일" if interval_days is not None else "직전 집계 현장 대비"
    )
    recent_offline_average = float(recent_four["offline_count"].mean()) if recent_four["offline_count"].notna().any() else None
    recent_online_values = recent_four.loc[
        recent_four["_record_status"] != "NO_STREAM", "online_count"
    ].dropna()
    recent_online_average = float(recent_online_values.mean()) if not recent_online_values.empty else None
    four_week_delta = (
        recent_offline_average - float(previous_four["offline_count"].mean())
        if len(previous_four) == 4 and recent_offline_average is not None and previous_four["offline_count"].notna().any()
        else None
    )
    fourth_stat = (
        ("최근 4회 온라인 지표 평균", f"{recent_online_average:.1f}" if recent_online_average is not None else "자료 없음")
        if online_metric_defined
        else ("미확인 주일", f"{len(missing_dates)}회")
    )
    stats = [
        (comparison_label, f"{week_delta:+d}명" if week_delta is not None else "비교 없음"),
        ("최근 4회 현장 평균", f"{recent_offline_average:.1f}명" if recent_offline_average is not None else "자료 없음"),
        ("직전 4회 현장 평균 대비", f"{four_week_delta:+.1f}명" if four_week_delta is not None else "비교 없음"),
        fourth_stat,
    ]
    compact_stats(stats, columns=4)
    recent_period = recent_four.sort_values("service_date")
    st.caption(
        f"최근 4개 집계 완료 회차 · {recent_period.iloc[0]['service_date'].strftime('%Y.%m.%d')}"
        f" ~ {recent_period.iloc[-1]['service_date'].strftime('%Y.%m.%d')} · "
        "누락 주일은 평균에서 제외 · 온라인 집계 기준 확정 전에는 평균을 핵심 지표로 사용하지 않음"
    )

    st.subheader("주일예배 회차별 추이")
    count_presets = {"최근 8회": 8, "최근 12회": 12, "최근 26회": 26, "최근 52회": 52, "전체": None}
    selected_count = st.radio(
        "표시 범위", list(count_presets), index=1, horizontal=True, key="sunday_attendance_count"
    )
    count_limit = count_presets[selected_count]
    trend = _scheduled_sunday_trend(sunday_all, count_limit)
    show_online = st.checkbox("온라인 지표 함께 보기", value=False, key="sunday_show_online")
    chart_frame = trend.rename(columns={"offline_count": "현장 참석", "online_count": "온라인 지표"})
    chart_labels = ["현장 참석"] + (["온라인 지표"] if show_online else [])
    fig = px.line(
        chart_frame,
        x="service_date",
        y=chart_labels,
        markers=True,
        labels={"service_date": "주일예배일", "value": "인원 / 지표", "variable": "구분"},
        color_discrete_map={"현장 참석": "#C4510B", "온라인 지표": "#5B4A3E"},
    )
    fig.update_traces(connectgaps=False)
    fig.update_layout(
        margin=dict(l=10, r=10, t=20, b=10),
        showlegend=show_online,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        hovermode="x unified",
        height=330,
    )
    st.plotly_chart(fig, width="stretch")
    gap_rows = trend[(trend["offline_count"].isna()) & (trend["record_status_label"] != "예배 취소")]
    if not gap_rows.empty:
        gap_labels = ", ".join(gap_rows["service_date"].dt.strftime("%m.%d").tail(8).tolist())
        st.caption(f"빈 구간은 현장 집계가 없거나 행이 없는 주일입니다 · {gap_labels}")

    selected_start = trend["service_date"].min()
    selected_end = trend["service_date"].max()
    filtered = sunday_all[
        (sunday_all["service_date"] >= selected_start) & (sunday_all["service_date"] <= selected_end)
    ].sort_values("service_date", ascending=False)

    with st.expander("주일예배 상세 기록"):
        detail_columns = ["service_date", "_record_status", "offline_count", "online_count", "total_count", "notes"]
        if "measurement_note" in filtered.columns:
            detail_columns.append("measurement_note")
        sunday_detail = filtered[detail_columns].copy().rename(columns={
            "service_date": "주일예배일",
            "_record_status": "집계 상태",
            "offline_count": "현장",
            "online_count": "온라인 지표",
            "total_count": "합산 참고",
            "notes": "비고",
            "measurement_note": "측정 설명",
        })
        sunday_detail["주일예배일"] = sunday_detail["주일예배일"].dt.strftime("%Y.%m.%d")
        sunday_detail["집계 상태"] = sunday_detail["집계 상태"].map(
            lambda value: ATTENDANCE_STATUS_LABELS.get(str(value), str(value))
        )
        st.dataframe(sunday_detail, hide_index=True, width="stretch", height=300)

    if has_access("ADMIN"):
        _attendance_admin_quality(data, sunday_all, absent_dates)

    other_types = [value for value in sorted(data["service_type"].dropna().unique().tolist()) if value != "주일예배"]
    if other_types:
        with st.expander("다른 예배 기록 보기 · 보조 자료"):
            st.caption("대표 지표와 평균 계산은 주일예배만 사용합니다. 다른 예배는 필요할 때 개별 기록으로 확인합니다.")
            other_type = st.selectbox("예배 종류", other_types, key="secondary_attendance_type")
            other_records = analysis_data[analysis_data["service_type"] == other_type].sort_values("service_date", ascending=False).head(12)
            other_detail = other_records[["service_date", "offline_count", "online_count", "total_count", "notes"]].copy()
            other_detail["service_date"] = other_detail["service_date"].dt.strftime("%Y.%m.%d")
            st.dataframe(
                other_detail.rename(columns={
                    "service_date": "예배일",
                    "offline_count": "현장",
                    "online_count": "온라인 지표",
                    "total_count": "합산 참고",
                    "notes": "비고",
                }),
                hide_index=True,
                width="stretch",
                height=300,
            )
    st.caption("통계 변화는 운영 기록과 함께 참고해요. 수치만으로 원인을 단정하지 않아요.")


def bible_page() -> None:
    hero("성경 검색", "구절 번호나 받은 설교 문자를 그대로 넣어 주세요.", "지식관리")

    source_text = st.text_area(
        "구절 번호나 받은 문자를 그대로 넣어 주세요",
        height=150,
        max_chars=20_000,
        placeholder=(
            "창 1:1 · 행 7:2~3\n\n"
            "또는 받은 설교 문자를 그대로 붙여넣으세요."
        ),
        key="bible_source_text",
        help="창 1:1, 창:1:1, 창세기 1:1, 창세기 1장 1절, 행 7:2~3 형식을 모두 인식합니다.",
    )
    previous_result = st.session_state.get("bible_lookup_result")
    has_current_result = bool(previous_result and source_text == previous_result.get("source"))
    submitted = st.button(
        "다시 찾기" if has_current_result else "구절 찾기",
        type="secondary" if has_current_result else "primary",
        width="stretch",
    )

    bible_label = "저장된 성경 TXT"
    local_bible: LocalBible | None = None
    if BIBLE_TEXT_PATH.exists():
        try:
            local_bible = _cached_local_bible(BIBLE_TEXT_PATH.read_bytes())
            bible_label = "개역개정판"
        except (OSError, ValueError) as exc:
            st.warning(f"저장된 성경 전체 본문을 읽지 못했어요: {exc}")

    local_source = None
    if has_access("ADMIN"):
        with st.expander("관리자 설정 · 성경 원본 교체"):
            st.caption("다른 전체 본문을 이번 접속에서만 사용하고 싶을 때 선택해요.")
            local_source = st.file_uploader(
                "다른 성경 전체 본문 TXT",
                type=["txt"],
                max_upload_size=10,
                help="‘창1:1 본문’ 형식의 10MB 이하 파일입니다. 기본 저장 파일을 변경하지 않습니다.",
                key="bible_corpus_upload",
            )
    if local_source is not None:
        local_bytes = local_source.getvalue()
        if len(local_bytes) > 10 * 1024 * 1024:
            st.error("성경 전체 본문 TXT는 10MB 이하 파일만 사용할 수 있어요.")
        else:
            local_hash = hashlib.sha256(local_bytes).hexdigest()
            try:
                local_bible = _cached_local_bible(local_bytes)
                bible_label = Path(local_source.name).stem
                if st.session_state.get("_bible_corpus_hash") != local_hash:
                    st.session_state["_bible_corpus_hash"] = local_hash
                    st.session_state.pop("bible_lookup_result", None)
                if local_bible.invalid_line_count:
                    st.warning(f"형식을 읽지 못한 행 {local_bible.invalid_line_count}개는 검색에서 뺐어요.")
            except ValueError as exc:
                st.error(str(exc))

    if local_bible is not None:
        st.caption(f"{bible_label} · {local_bible.book_count}권 {len(local_bible.verses):,}절 연결됨")
    else:
        st.warning("성경 전체 본문 TXT를 연결하면 구절 내용을 함께 볼 수 있어요.")

    if submitted:
        all_references = extract_bible_references(source_text, limit=101)
        references = all_references[:100]
        omitted_count = max(0, len(all_references) - len(references))
        verses: list[BibleVerse] = []
        errors: list[tuple[BibleReference, str]] = []
        if references and local_bible is not None:
            with st.spinner(f"업로드한 성경에서 {len(references)}개 구절을 찾는 중입니다…"):
                for reference in references:
                    try:
                        verses.append(fetch_local_bible_verse(local_bible, reference, bible_label))
                    except RuntimeError as exc:
                        errors.append((reference, str(exc)))

        st.session_state["bible_lookup_result"] = {
            "source": source_text,
            "references": references,
            "verses": verses,
            "errors": errors,
            "bible_label": bible_label,
            "omitted_count": omitted_count,
        }
        if verses:
            copy_lines = [f"[성경 본문 · {bible_label}]"]
            for verse in verses:
                copy_lines.extend(["", verse.reference.display, verse.content])
            st.session_state["bible_copy_output"] = "\n".join(copy_lines).strip()

    result = st.session_state.get("bible_lookup_result")
    if not result:
        with st.expander("지원하는 입력 형식"):
            st.markdown("`창:1:1` · `창세기 1장 1절` · `행 7:2~3` · `사도행전 7장 2~3절` · 여러 구절이 들어간 설교 문자")
        return
    if source_text != result["source"]:
        st.info("입력 내용이 바뀌었어요. ‘구절 찾기’를 눌러 새로 확인해 주세요.")
        return

    references = result["references"]
    verses = result["verses"]
    errors = result["errors"]
    if not references:
        st.warning("성경 구절 표기를 찾지 못했어요. 예: 창 1:1 또는 창세기 1장 1절")
        return

    st.markdown(
        '<div class="bible-result-summary">'
        f'<span>인식된 구절 <strong>{len(references)}개</strong></span>'
        f'<span>본문 확인 <strong>{len(verses)}개</strong></span>'
        '</div>',
        unsafe_allow_html=True,
    )
    if result.get("omitted_count"):
        st.warning("한 번에 최대 100개 구절까지 처리합니다. 100개 이후 구절은 파일을 나누어 다시 확인해 주세요.")
    st.subheader("찾은 본문")
    if local_bible is None:
        st.info("구절 표기는 찾았어요. 성경 전체 본문 TXT를 연결하면 본문도 함께 보여요.")

    verse_by_id = {verse.reference.verse_id: verse for verse in verses}
    error_by_id = {reference.verse_id: message for reference, message in errors}
    for reference in references:
        verse = verse_by_id.get(reference.verse_id)
        if verse:
            st.markdown(
                '<div class="bible-verse">'
                f'<div class="reference">{html.escape(reference.display)}</div>'
                f'<div class="content">{html.escape(verse.content)}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        else:
            with st.container(border=True):
                st.markdown(f"**{reference.display}**")
                if reference.verse_id in error_by_id:
                    st.warning(error_by_id[reference.verse_id])
                else:
                    st.caption("본문 연결 대기")

    if verses:
        section_gap()
        st.subheader("정리본 복사하기")
        st.caption("아래 상자의 복사 아이콘을 누르면 전체 본문을 한 번에 복사할 수 있어요.")
        st.code(
            st.session_state["bible_copy_output"],
            language=None,
            wrap_lines=True,
            height=min(420, 120 + len(verses) * 62),
        )
        st.download_button(
            "정리본 파일로 내려받기",
            st.session_state["bible_copy_output"].encode("utf-8-sig"),
            file_name="성경_본문_정리.txt",
            mime="text/plain",
            type="secondary",
            width="stretch",
        )

    with st.expander("지원하는 입력 형식"):
        st.markdown("`창 1:1` · `창:1:1` · `창세기 1:1` · `창세기 1장 1절` · `행 7:2~3` · 여러 구절이 들어간 설교 문자")
        st.caption("입력한 문자는 저장하거나 수정하지 않으며, 인식한 구절만 화면에 정리합니다. 한 번에 최대 100개 구절을 확인합니다.")

    st.markdown(
        "<div style='margin-top:2.5rem;padding-top:.75rem;border-top:1px solid #E5E8EB;"
        "text-align:center;color:#667180;font-size:.78rem;'>"
        "성경 본문 출처: 개역개정판 © 대한성서공회"
        "</div>",
        unsafe_allow_html=True,
    )


def search_page() -> None:
    hero("전체 검색", "준비업무와 매뉴얼을 함께 찾아 바로 열어 봐요.", "지식관리")
    term = st.text_input("검색어", value=st.session_state.get("search_term", ""), placeholder="예: 세례, 방석, 마이크")
    include_archived = (
        st.checkbox("보관·이전 버전도 포함", value=False)
        if has_access("ADMIN")
        else False
    )
    if not term.strip():
        empty_state("찾고 싶은 준비업무나 매뉴얼의 단어를 입력해 주세요.")
        return
    results = _visible_search_results(
        global_search(term, include_archived),
        allow_team_content=has_access("TEAM"),
    )
    display_limit = st.selectbox("한 번에 보기", [10, 25, 50], index=1, key="global_search_limit")
    visible_results = results[:display_limit]
    st.caption(f"검색 결과 {len(results)}건 · 현재 {len(visible_results)}건 표시")
    if not results:
        empty_state("검색어를 짧게 바꾸거나 다른 단어로 다시 찾아보세요.")
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
            open_label = "보관함 열기" if item["archived"] else (
                "매뉴얼 열기" if item["target_page"] == "매뉴얼" else (
                    "행사 열기" if item["target_page"] == "행사" else f"{item['target_page']} 열기"
                )
            )
            if action_col.button(open_label, key=f"search_open_{index}_{item['kind']}_{item['id']}", width="stretch"):
                if item["archived"] and item["target_page"] in {"매뉴얼", "행사"}:
                    navigate("보관함")
                elif item["target_page"] == "매뉴얼":
                    navigate("매뉴얼", "selected_manual", item["target_id"])
                elif item["target_page"] == "행사":
                    navigate("행사", "selected_event", item["target_id"])
                else:
                    navigate(item["target_page"])


def archive_page() -> None:
    hero("보관함", "보관한 자료를 확인하고 필요할 때 다시 복원해요.", "관리")
    if not access_required("ADMIN", "보관 자료 복원"):
        return
    events = rows("SELECT id,title,event_date,archived_at FROM events WHERE archived_at IS NOT NULL ORDER BY archived_at DESC")
    manuals = rows("SELECT id,title,archived_at FROM manuals WHERE archived_at IS NOT NULL ORDER BY archived_at DESC")
    event_tab, manual_tab = st.tabs([f"행사 ({len(events)})", f"매뉴얼 ({len(manuals)})"])
    with event_tab:
        if not events:
            empty_state("보관한 행사가 생기면 여기에서 다시 복원할 수 있어요.")
        for item in events:
            cols = st.columns([.8, .2])
            cols[0].markdown(f"**{item['title']}**  \n{item['event_date'] or '날짜 미정'} · 보관 {item['archived_at'][:10]}")
            if cols[1].button("복원", key=f"restore_event_{item['id']}"):
                archive_entity("events", item["id"], restore=True)
                rerun("행사를 복원했습니다.")
    with manual_tab:
        if not manuals:
            empty_state("보관한 매뉴얼이 생기면 여기에서 다시 복원할 수 있어요.")
        for item in manuals:
            cols = st.columns([.8, .2])
            cols[0].markdown(f"**{item['title']}**  \n보관 {item['archived_at'][:10]}")
            if cols[1].button("복원", key=f"restore_manual_{item['id']}"):
                archive_entity("manuals", item["id"], restore=True)
                rerun("매뉴얼을 복원했습니다.")


def calendar_page() -> None:
    hero("교회력", "Google Calendar 일정을 읽기 전용으로 가져와 함께 확인해요.")
    today = today_kst().isoformat()
    active_calendar_id = get_app_meta("last_google_calendar_id", "") or get_app_meta("google_calendar_id", "")
    upcoming = rows(
        "SELECT * FROM church_calendar_events WHERE archived_at IS NULL AND status<>'CANCELLED' AND start_date>=? "
        "AND (?='' OR calendar_id=?) ORDER BY start_date,id LIMIT 30",
        (today, active_calendar_id, active_calendar_id),
    )
    sync_status = row(
        "SELECT COUNT(*) AS total FROM church_calendar_events WHERE archived_at IS NULL AND (?='' OR calendar_id=?)",
        (active_calendar_id, active_calendar_id),
    ) or {"total": 0}
    last_calendar_sync = get_app_meta("last_google_calendar_sync_at", "")
    last_sync_label = (last_calendar_sync or "연동 전").replace("T", " ")
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
                    safe_calendar_url = _safe_http_url(item["html_link"])
                    if safe_calendar_url:
                        st.link_button("Google Calendar에서 보기", safe_calendar_url, width="stretch")
    else:
        empty_state("Google Calendar를 연결하면 가까운 교회력 일정부터 여기에 보여요.")

    if not has_access("ADMIN"):
        st.caption("Google Calendar 연결과 동기화는 관리자 권한에서만 표시됩니다.")
        return

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
            st.warning("게시판 서비스 계정 Secret을 찾지 못했어요.")
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
                    st.error(f"동기화하지 못했어요: {exc}")
        st.caption("Calendar ID를 Streamlit Secret `GOOGLE_CALENDAR_ID`로 저장하면 재부팅 후에도 설정이 유지됩니다.")


def data_page() -> None:
    hero("데이터·백업", "원본 연결과 백업 상태를 관리자용으로 확인해요.", "관리자")
    if not access_required("ADMIN", "원본 동기화·데이터 내보내기·DB 관리"):
        return
    st.subheader("Google Sheets 원본")
    google_sheets_sync_bar()
    st.caption("예배팀 매뉴얼과 예배인원·엔지니어 라인업은 읽기 전용으로 가져옵니다.")
    st.warning(
        "팀 확인 게시판은 Google Sheets에 영구 저장됩니다. 그 외의 새 행사·업무 상태·매뉴얼 수정·운영기록은 "
        "현재 Streamlit 로컬 DB에 저장되어 재부팅·재배포 후 유지가 보장되지 않습니다. 중요한 내용은 백업을 내려받으세요."
    )
    section_gap()
    import_tab, quality_tab, backup_tab = st.tabs(["가져오기 결과", "확인 필요", "데이터 내보내기"])
    with import_tab:
        if IMPORT_REPORT_PATH.exists():
            try:
                report = json.loads(IMPORT_REPORT_PATH.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                st.error("가져오기 결과 파일을 읽지 못했어요. 원본 데이터는 그대로 유지해요.")
                st.caption(str(exc))
            else:
                counts = report.get("imported", {})
                compact_stats([
                    ("예배 인원", counts.get("attendance", 0)),
                    ("매뉴얼", counts.get("manuals", 0)),
                    ("행사", counts.get("events", 0)),
                    ("인원 명단", counts.get("members", 0)),
                ], columns=4)
                st.json(report, expanded=False)
        else:
            empty_state("자료를 한 번 업데이트하면 가져온 결과가 여기에 보여요.")
        with st.expander("고급 관리 · 로컬 DB 다시 구축"):
            cached_sources = list(GOOGLE_SHEETS_CACHE_DIR.glob("*.xlsx"))
            local_sources = list(SOURCE_DIR.glob("*.xlsx"))
            rebuild_source = GOOGLE_SHEETS_CACHE_DIR if cached_sources else SOURCE_DIR
            rebuild_files = cached_sources or local_sources
            st.error(
                "이 기능은 행사·업무 상태·매뉴얼 수정·운영기록 등 로컬 DB의 사용자 입력을 삭제합니다. "
                "먼저 '데이터 내보내기' 탭에서 파일을 내려받으세요. 게시판 Google Sheets는 삭제되지 않습니다."
            )
            if not rebuild_files:
                st.warning("재구축할 Excel 원본을 찾지 못했어요. 먼저 위에서 최신 자료를 업데이트해 주세요.")
            confirm_reset = st.text_input("실행하려면 '데이터 다시 구축'을 입력", key="db_reset_confirmation")
            backup_confirmed = st.checkbox("데이터 내보내기 파일을 내려받았습니다.", key="db_reset_backup_confirmed")
            reset_ready = confirm_reset.strip() == "데이터 다시 구축" and backup_confirmed and bool(rebuild_files)
            if st.button("로컬 DB 다시 구축", type="secondary", disabled=not reset_ready, key="rebuild_local_db"):
                migrate(source_dir=rebuild_source, reset=True)
                rerun("검증된 원본으로 로컬 DB를 안전하게 다시 구축하고 이전 DB를 자동 백업했습니다.")
    with quality_tab:
        unresolved = rows(
            "SELECT unresolved_imports.*,source_files.file_name FROM unresolved_imports LEFT JOIN source_files ON source_files.id=unresolved_imports.source_file_id ORDER BY CASE quality WHEN 'Needs Review' THEN 1 ELSE 2 END,id"
        )
        if not unresolved:
            st.success("확인이 필요한 항목을 모두 처리했어요.")
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
        st.markdown("중요한 운영지식은 JSON과 테이블별 CSV로 내보낼 수 있습니다. 이 파일은 아직 자동 복원용 백업은 아닙니다.")
        if st.button("내보내기 파일 생성", type="primary"):
            json_path, csv_payloads = export_backup()
            sqlite_path = create_sqlite_backup()
            st.session_state["backup_json_path"] = str(json_path)
            st.session_state["backup_sqlite_path"] = str(sqlite_path)
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
        sqlite_path_value = st.session_state.get("backup_sqlite_path")
        if sqlite_path_value and Path(sqlite_path_value).exists():
            sqlite_path = Path(sqlite_path_value)
            st.download_button(
                "SQLite 복구용 백업 다운로드",
                sqlite_path.read_bytes(),
                file_name=sqlite_path.name,
                mime="application/vnd.sqlite3",
            )


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
        "성경 검색": bible_page,
        "전체 검색": search_page,
        "보관함": archive_page,
        "데이터·백업": data_page,
    }
    pages[nav]()


if __name__ == "__main__":
    main()

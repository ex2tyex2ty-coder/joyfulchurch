"""Visible task-first navigation. Does not grant access to protected pages."""
import streamlit as st

PAGES = {'대시보드','큐시트','주보','음향 요청','예배 진행','예배 인원 현황',
         '팀 확인','행사','매뉴얼','전체 검색','보관함','데이터·백업','결정·운영로그','성경 검색'}


def selected_page():
    pending = st.session_state.pop('_navigate_to', None)
    if pending in PAGES:
        st.session_state['main_nav'] = pending
        st.session_state.pop('_secondary_nav', None)
    # Migrate a still-open secondary page from the older sidebar.
    secondary = st.session_state.pop('_secondary_nav', None)
    if secondary in PAGES:
        st.session_state['main_nav'] = secondary
    if st.session_state.get('main_nav') not in PAGES:
        st.session_state['main_nav'] = '음향 요청'
    if not st.session_state.get('sound_entry_link_checked'):
        st.session_state['sound_entry_link_checked'] = True
        entry = st.query_params.get('sound', '')
        if entry in {'kids','team','desk'}:
            st.session_state['sound_entry'] = entry
            st.session_state['main_nav'] = '음향 요청'
    return st.session_state['main_nav']


def navigation_bar(nav, navigate, open_menu):
    st.html('''<style>
    [data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"],
    [data-testid="stSidebarCollapseButton"], button[data-testid="stExpandSidebarButton"] {display:none!important}
    .st-key-public_navigation {background:#fff!important;border:1px solid #ece9e5;border-radius:18px;padding:5px!important;max-width:640px;margin:0 auto 12px}
    .st-key-public_navigation [data-testid="stHorizontalBlock"] {flex-wrap:nowrap!important;gap:8px!important}
    .st-key-public_navigation [data-testid="stColumn"] {min-width:0!important;flex:1 1 0!important;width:0!important}
    .st-key-public_navigation button {min-height:46px!important;background:transparent!important;border:0!important;border-radius:13px!important;box-shadow:none!important;color:#69717d!important}
    .st-key-public_navigation button p {font-size:15px!important;font-weight:600!important;white-space:nowrap;color:inherit!important;-webkit-text-fill-color:inherit!important}
    .st-key-public_navigation button[kind="primary"] {background:#fff2e4!important;color:#8b480f!important}
    .st-key-public_navigation button:hover {background:#f6f5f3!important}
    @media(max-width:768px) {
      [data-testid="stMainBlockContainer"] {padding-bottom:110px!important}
      .st-key-public_navigation {position:fixed!important;bottom:0;left:0;right:0;width:100%!important;
        max-width:none;margin:0;z-index:9990;border-radius:16px 16px 0 0;padding:8px 12px calc(8px + env(safe-area-inset-bottom))!important;
        box-shadow:0 -3px 16px #0001}
      /* A phone keyboard must not leave a fixed bar over the conversation composer. */
      body:has(input[type="text"]:focus,input[type="password"]:focus,input[type="search"]:focus,input[type="number"]:focus,textarea:focus) .st-key-public_navigation {position:static!important}
    }
    </style>''')
    with st.container(key='public_navigation'):
        sound, cue, more = st.columns(3)
        if sound.button('음향 요청',key='nav_sound',width='stretch',type='primary' if nav=='음향 요청' else 'secondary'):
            navigate('음향 요청')
        if cue.button('큐시트',key='nav_cue',width='stretch',type='primary' if nav=='큐시트' else 'secondary'):
            navigate('큐시트')
        if more.button('더보기',key='open_full_menu',width='stretch',type='primary' if nav not in {'음향 요청','큐시트'} else 'secondary'):
            st.session_state['_full_menu_open'] = True
    if st.session_state.get('_full_menu_open'):
        open_menu()

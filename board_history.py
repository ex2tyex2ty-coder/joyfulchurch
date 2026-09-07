"""Read-only history/search projection including archived board items."""
from google_review_board import RESOLUTION_COMMENT_PREFIX


def history_items(snapshot, term="", *, standards_only=False, archived_only=False):
    comments={}
    seen=set()
    for comment in snapshot.get("raw_comments",[]):
        cid=comment.get("comment_id")
        if comment.get("archived_at") or (cid and cid in seen):
            continue
        if cid:
            seen.add(cid)
        comments.setdefault(str(comment.get("review_item_id")),[]).append(comment)
    result=[]
    for raw in snapshot.get("raw_items",[]):
        item=dict(raw)
        item["id"]=str(raw.get("item_id"))
        item["history"]=sorted(comments.get(item["id"],[]),key=lambda c:str(c.get("created_at") or ""))
        standards=[c for c in item["history"] if str(c.get("body") or "").startswith("[기준 확정]") and str(c.get("body") or "").removeprefix("[기준 확정]").strip()]
        item["current_standard"]=str(standards[-1]["body"]).removeprefix("[기준 확정]").strip() if standards else ""
        if standards_only and not item["current_standard"]:
            continue
        if archived_only and not item.get("archived_at"):
            continue
        searchable=" ".join(str(item.get(k) or "") for k in ("title","description","owner","category")) + " " + " ".join(str(c.get("body") or "")+" "+str(c.get("author") or "") for c in item["history"])
        if any(word not in searchable.casefold() for word in term.casefold().split()):
            continue
        result.append(item)
    return sorted(result,key=lambda r:str(r.get("updated_at") or ""),reverse=True)


def render_history(snapshot, term="", *, standards_only=False, archived_only=False, key="board_history", store=None, can_restore=False):
    import streamlit as st
    from google_review_board import ReviewBoardConnectionError
    items=history_items(snapshot,term,standards_only=standards_only,archived_only=archived_only)
    st.caption(f"{len(items)}건 · 본문·댓글·확정 기준을 함께 검색해요.")
    if not items:
        st.info("조건에 맞는 기록이 없어요.")
        return
    pages=max(1,(len(items)+19)//20)
    page=st.selectbox("기록 페이지",range(1,pages+1),key=key+"_page")
    for item in items[(page-1)*20:page*20]:
        with st.expander(f"{item['title']} · {'보관' if item.get('archived_at') else '진행 기록'}"):
            if item["current_standard"]:
                st.success("현재 기준 · "+item["current_standard"])
            st.text(str(item.get("description") or ""))
            for comment in item["history"]:
                st.caption(f"{comment.get('author','')} · {str(comment.get('created_at',''))[:16]}")
                st.text(str(comment.get("body") or ""))
            if can_restore and store and item.get("archived_at"):
                author=st.text_input("다시 연 사람",value=st.session_state.get("operator_name",""),key=key+item["id"]+"_author")
                if st.button("확인 필요로 다시 열기",key=key+item["id"]+"_restore"):
                    try:
                        store.restore_item(item["id"],author)
                        st.session_state["_board_history_changed"]=True
                        st.success("다시 열었어요. 진행할 일에서 확인해 주세요.")
                    except (ValueError,ReviewBoardConnectionError) as exc:
                        st.error(str(exc))

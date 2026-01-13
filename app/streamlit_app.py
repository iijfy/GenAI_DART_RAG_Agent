from __future__ import annotations

import requests
import streamlit as st

import os

API_BASE = os.getenv("API_BASE", "http://127.0.0.1:8000")


st.set_page_config(page_title="DART RAG Agent Demo (iM뱅크)", layout="wide")
st.title("🏦 DART 공시 기반 RAG + Report Agent (Frontend)")
st.caption("Streamlit은 화면만 담당하고, RAG/Agent는 FastAPI 백엔드로 호출합니다.")




# 1. 상태 확인
with st.expander("✅ Backend Status", expanded=True):
    try:
        r = requests.get(f"{API_BASE}/health", timeout=5)
        st.write("health:", r.json())
    except Exception as e:
        st.error(f"백엔드에 연결 실패: {e}")
        st.stop()


st.subheader("0) 공시 검색 / 선택 / 로드 (API)")

colA, colB, colC = st.columns([2, 1, 1], gap="large")
with colA:
    corp_name = st.text_input("회사명", value="아이엠뱅크")
with colB:
    start_date = st.text_input("시작일(YYYYMMDD)", value="20251101")
with colC:
    end_date = st.text_input("종료일(YYYYMMDD)", value="20251231")

if "search_items" not in st.session_state:
    st.session_state.search_items = []

if st.button("🔍 공시 검색"):
    payload = {"corp_name": corp_name, "start_date": start_date, "end_date": end_date}
    res = requests.post(f"{API_BASE}/disclosures/search", json=payload, timeout=60)
    res.raise_for_status()
    data = res.json()

    items = data.get("items", [])
    st.session_state.search_items = items
    st.success(f"검색 결과: {len(items)}건")
    if len(items) == 0:
         st.warning("검색 결과가 0건입니다. 날짜 범위를 넓혀보세요.")


items = st.session_state.search_items

if items:
    options = [f"{it['rcept_dt']} | {it['report_nm']} | {it['rcept_no']}" for it in items]
    selected = st.selectbox("공시 선택", options)

    # 선택한 항목 찾기
    sel_idx = options.index(selected)
    sel = items[sel_idx]

    if st.button("📥 선택 공시 로드(다운로드/파싱/인덱싱)"):
        res = requests.post(
            f"{API_BASE}/disclosures/load",
            json={"rcept_no": sel["rcept_no"], "report_nm": sel["report_nm"]},
            timeout=180,
        )
        res.raise_for_status()
        loaded = res.json()
        st.success(f"로드 완료: chunks={loaded.get('chunks')}")
        st.write("viewer:", loaded.get("viewer_url"))
        # 현재 로드된 공시를 session_state에 저장 (질문/리포트할 때 '지금 뭐로 하고 있는지' 표시용)
        st.session_state.current_loaded = {
            "rcept_no": loaded.get("rcept_no"),
            "report_nm": loaded.get("report_nm"),
            "viewer_url": loaded.get("viewer_url"),
            "chunks": loaded.get("chunks"),
        }
else:
    st.info("먼저 공시를 검색하세요.")



# 2. RAG Q&A (API 호출)
st.subheader("RAG Q&A (API)")
q = st.text_input("질문을 입력하세요", value="총발행금액은 얼마야?")
top_k = st.slider("Top-K Evidence", min_value=1, max_value=5, value=3)

if st.button("🔎 근거 기반 답변 생성", type="primary"):
    payload = {"question": q, "top_k": top_k}
    res = requests.post(f"{API_BASE}/ask", json=payload, timeout=60)
    res.raise_for_status()
    data = res.json()

    col1, col2 = st.columns([1, 1], gap="large")

    with col1:
        st.markdown("### ✅ Answer")
        st.code(data["answer"], language="markdown")
        st.markdown("### 🔗 Viewer")
        st.write(data["viewer_url"])

    with col2:
        st.markdown("### 📌 Evidence")
        for ev in data["evidences"]:
            title = f"[{ev['sid']}] chunk_id={ev['chunk_id']} | score={ev['score']:.4f}"
            with st.expander(title, expanded=(ev["sid"] == "S1")):
                st.write(ev["preview"])




# 3. Report Agent (API 호출)
st.subheader("Report Agent (API)")
# ✅ 현재 로드된 공시 상태 표시
with st.expander("📌 Current Loaded Disclosure", expanded=True):
    cur = st.session_state.get("current_loaded")
    if not cur:
        st.warning("아직 공시가 로드되지 않았어요. 위에서 공시를 검색하고 '로드'를 먼저 해주세요.")
    else:
        st.write(f"- rcept_no: {cur.get('rcept_no')}")
        st.write(f"- report_nm: {cur.get('report_nm')}")
        st.write(f"- chunks: {cur.get('chunks')}")
        st.write(f"- viewer_url: {cur.get('viewer_url')}")

st.write("버튼을 누르면 백엔드에서 리포트를 생성합니다 (data/reports에 저장).")

if st.button("🧾 리포트 생성", type="secondary"):
    res = requests.post(f"{API_BASE}/report", timeout=180)
    res.raise_for_status()
    data = res.json()

    if not data.get("ok"):
        st.error(data.get("message", "report failed"))
        st.stop()

    st.success("리포트 생성 완료!")

    st.markdown("### 🔗 Viewer")
    st.write(data.get("viewer_url"))

    st.markdown("### 📝 Report Preview (Markdown)")
    md_text = data.get("md_text", "")
    st.markdown(md_text)

    # ✅ 다운로드 버튼 (MD)
    st.download_button(
        label=f"⬇️ Download MD ({data.get('md_filename')})",
        data=md_text,
        file_name=data.get("md_filename", "report.md"),
        mime="text/markdown",
    )

    # ✅ 다운로드 버튼 (JSON)
    json_text = data.get("json_text")
    if json_text:
        st.download_button(
            label=f"⬇️ Download JSON ({data.get('json_filename')})",
            data=json_text,
            file_name=data.get("json_filename", "report.json"),
            mime="application/json",
        )


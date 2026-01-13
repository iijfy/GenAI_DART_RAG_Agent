"""
FastAPI Backend: DART RAG + Report Agent

실행:
uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import json
from datetime import datetime

from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel


from scripts._rag_answer_with_citations import (
    build_chunks,
    build_bm25,
    retrieve_topk,
    build_prompt,
    ask_llm,
)

from scripts._agent_generate_report import generate_report

from scripts.dart_service import (
    find_corp_code,
    search_disclosures,
    download_disclosure_zip,
    extract_zip,
    parse_first_xml_to_text,
)

app = FastAPI(title="DART RAG Agent API", version="0.1.0")

ROOT = Path(__file__).resolve().parents[1]

CURRENT_RCEPT_NO = None
CURRENT_REPORT_NM = None
CURRENT_TXT_PATH = None
CURRENT_VIEWER_URL = None

_chunks_map = {}
_bm25_map = {}





class SearchRequest(BaseModel):
    corp_name: str
    start_date: str  # YYYYMMDD
    end_date: str    # YYYYMMDD


@app.post("/disclosures/search")
def disclosures_search(req: SearchRequest):
    corp_code = find_corp_code(req.corp_name)
    items = search_disclosures(corp_code, req.start_date, req.end_date, page_count=20)

    return {
        "ok": True,
        "corp_name": req.corp_name,
        "corp_code": corp_code,
        "count": len(items),
        "items": [
            {"rcept_no": it.rcept_no, "report_nm": it.report_nm, "rcept_dt": it.rcept_dt}
            for it in items
        ],
    }



class LoadRequest(BaseModel):
    rcept_no: str
    report_nm: str


@app.post("/disclosures/load")
def disclosures_load(req: LoadRequest):
    global CURRENT_RCEPT_NO, CURRENT_REPORT_NM, CURRENT_TXT_PATH, CURRENT_VIEWER_URL

    # 다운로드/압축해제
    zip_path = download_disclosure_zip(req.rcept_no, req.report_nm)
    extracted_dir = extract_zip(zip_path)

    # 텍스트 변환 저장 (일단 최소 파서)
    txt_path = parse_first_xml_to_text(extracted_dir, req.rcept_no)

    # 인덱싱 (rcept_no별 캐시)
    text = txt_path.read_text(encoding="utf-8", errors="ignore")
    chunks = build_chunks(text)
    bm25 = build_bm25(chunks)
    _chunks_map[req.rcept_no] = chunks
    _bm25_map[req.rcept_no] = bm25

    CURRENT_RCEPT_NO = req.rcept_no
    CURRENT_REPORT_NM = req.report_nm
    CURRENT_TXT_PATH = str(txt_path)
    CURRENT_VIEWER_URL = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={req.rcept_no}"

    return {
        "ok": True,
        "message": "loaded",
        "rcept_no": CURRENT_RCEPT_NO,
        "report_nm": CURRENT_REPORT_NM,
        "viewer_url": CURRENT_VIEWER_URL,
        "txt_path": CURRENT_TXT_PATH,
        "chunks": len(chunks),
    }




# Request/Response Schemas
class AskRequest(BaseModel):
    question: str
    top_k: int = 3


class AskResponse(BaseModel):
    rcept_no: str
    report_name: str
    viewer_url: str
    answer: str
    evidences: list[dict[str, Any]]




@app.get("/health")
def health():
    return {"ok": True}



@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    if not CURRENT_RCEPT_NO:
        return {
            "rcept_no": "",
            "report_name": "",
            "viewer_url": "",
            "answer": "먼저 공시를 검색하고 load 해주세요.",
            "evidences": [],
        }

    chunks = _chunks_map.get(CURRENT_RCEPT_NO)
    bm25 = _bm25_map.get(CURRENT_RCEPT_NO)

    if chunks is None or bm25 is None:
        return {
            "rcept_no": CURRENT_RCEPT_NO,
            "report_name": CURRENT_REPORT_NM or "",
            "viewer_url": CURRENT_VIEWER_URL or "",
            "answer": "인덱스가 없습니다. 공시를 다시 load 해주세요.",
            "evidences": [],
        }

    evidences = retrieve_topk(bm25, chunks, req.question, k=req.top_k)
    prompt = build_prompt(req.question, evidences)
    answer = ask_llm(prompt)

    return {
        "rcept_no": CURRENT_RCEPT_NO,
        "report_name": CURRENT_REPORT_NM or "",
        "viewer_url": CURRENT_VIEWER_URL or "",
        "answer": answer,
        "evidences": [
            {
                "sid": f"S{rank}",
                "chunk_id": idx,
                "score": score,
                "preview": chunk[:300] + ("..." if len(chunk) > 300 else ""),
            }
            for rank, (idx, score, chunk) in enumerate(evidences, 1)
        ],
    }




@app.post("/report")
def report():
    """
    리포트 생성 → 생성된 결과(MD/JSON)를 바로 반환
    """
    if not CURRENT_RCEPT_NO:
        return {"ok": False, "message": "먼저 공시를 검색하고 load 해주세요."}

    # ✅ 리포트 생성 (선택된 공시 기준)
    payload = generate_report(
        rcept_no=CURRENT_RCEPT_NO,
        report_nm=CURRENT_REPORT_NM or "",
        txt_path=CURRENT_TXT_PATH,
        viewer_url=CURRENT_VIEWER_URL or "",
    )

    # ✅ generate_report()가 저장한 경로를 그대로 사용 (glob 필요 없음)
    md_path = Path(payload["saved"]["md"])
    json_path = Path(payload["saved"]["json"])

    md_text = md_path.read_text(encoding="utf-8")
    json_text = json_path.read_text(encoding="utf-8") if json_path.exists() else None

    return {
        "ok": True,
        "message": "Report generated",
        "rcept_no": payload["rcept_no"],
        "viewer_url": payload["viewer"],
        "md_filename": md_path.name,
        "md_text": md_text,
        "json_filename": json_path.name if json_path.exists() else None,
        "json_text": json_text,
    }




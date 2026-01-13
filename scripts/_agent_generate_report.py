"""
06_agent_generate_report.py

목표:
- (공시 1건) 질문 4개를 자동으로 돌려서
- 답변/근거/출처링크를 "리포트"로 저장 (JSON + Markdown)

실행:
python scripts/_agent_generate_report.py
"""

from __future__ import annotations

import os
import re
import json
from pathlib import Path
from datetime import datetime
from typing import List, Tuple

from dotenv import load_dotenv
from rank_bm25 import BM25Okapi
from openai import OpenAI



# 1. 환경변수 / 경로
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY를 다시 확인 바랍니다.")

client = OpenAI(api_key=OPENAI_API_KEY)

ROOT = Path(__file__).resolve().parents[1]




# 2. 정규화/토큰화
def normalize_fin_terms(s: str) -> str:
    replacements = {
        "신용평가 등급": "신용평가등급",
        "상환 기일": "상환기일",
        "발행 금액": "발행금액",
        "총 발행금액": "총발행금액",
        "인수 기관": "인수기관",
    }
    for a, b in replacements.items():
        s = s.replace(a, b)
    return s


def tokenize_ko_fin(s: str) -> list[str]:
    s = normalize_fin_terms(s)
    s = s.lower()
    s = re.sub(r"(\d),(\d)", r"\1\2", s)  # 100,000 -> 100000
    tokens = re.findall(r"[가-힣]+|[a-zA-Z]+|\d+", s)

    stop = {"입니다", "합니다", "관한", "사항", "보고서", "주식회사", "회사", "회차"}
    tokens = [t for t in tokens if t not in stop and len(t) >= 2]
    return tokens


def to_query_keyword(q: str) -> str:
    q = normalize_fin_terms(q)
    rules = [
        ("총발행금액", ["총발행금액", "발행금액", "발행 금액", "총 발행금액"]),
        ("신용평가등급", ["신용평가등급", "신용평가 등급", "등급"]),
        ("상환기일", ["상환기일", "상환 기일", "만기", "만기일"]),
        ("인수기관", ["인수기관", "인수 기관", "주관사", "인수사"]),
    ]
    for kw, pats in rules:
        for p in pats:
            if p in q:
                return kw
    return q





# 3. 공시용 청킹
def split_by_markers(t: str) -> list[str]:
    pattern = r"(?=^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\.\s)|(?=^\d+\.\s)"
    parts = re.split(pattern, t, flags=re.MULTILINE)
    return [p.strip() for p in parts if p and p.strip()]


def split_by_length(t: str, max_chars: int = 900, overlap: int = 120) -> list[str]:
    t = t.strip()
    if len(t) <= max_chars:
        return [t]

    out = []
    start = 0
    while start < len(t):
        end = min(start + max_chars, len(t))
        out.append(t[start:end])
        start = end - overlap
        if start < 0:
            start = 0
        if end == len(t):
            break
    return out


def build_chunks(text: str) -> list[str]:
    parts = split_by_markers(text)
    chunks: list[str] = []
    for p in parts:
        chunks.extend(split_by_length(p, max_chars=900, overlap=120))
    return chunks




# 4. Retriever (BM25)
def build_bm25(chunks: list[str]) -> BM25Okapi:
    tokenized = [tokenize_ko_fin(c) for c in chunks]
    return BM25Okapi(tokenized)


def retrieve_topk(bm25: BM25Okapi, chunks: list[str], query: str, k: int = 3) -> list[tuple[int, float, str]]:
    query = to_query_keyword(query)  # ✅ 검색 전에 키워드 축약
    q_tok = tokenize_ko_fin(query)
    scores = bm25.get_scores(q_tok)
    top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
    return [(i, float(scores[i]), chunks[i]) for i in top_idx]





# 5. Generator (LLM) - 근거 기반 답변
def build_prompt(question: str, evidences: list[tuple[int, float, str]]) -> str:
    sources_txt = []
    for rank, (idx, score, chunk) in enumerate(evidences, 1):
        sources_txt.append(f"[S{rank}] (chunk_id={idx}, score={score:.4f})\n{chunk}\n")

    sources_block = "\n".join(sources_txt)

    prompt = f"""
너는 금융권 문서(공시) 기반 Q&A 어시스턴트야.

규칙(매우 중요):
1) 아래 [S1]~[S{len(evidences)}] 근거 안에 있는 내용만 답해.
2) 근거에 없는 내용은 절대 추측하지 말고, "문서에서 확인되지 않음"이라고 말해.
3) 숫자/날짜/기관명/금액은 근거에 적힌 그대로 써.
4) 정의/상식/배경설명(일반론)을 덧붙이지 마. 근거에서 확인되는 사실만 말해.
5) 답변은 아래 출력 형식을 반드시 지켜.

출력 형식(반드시 그대로):
Answer:
- (한 줄 요약)
Evidence:
- [S?] chunk_id=숫자: (근거에서 핵심 문장 1줄 인용)
Citations: [S?]

질문:
{question}

근거:
{sources_block}
""".strip()
    return prompt


def ask_llm(prompt: str) -> str:
    res = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You answer in Korean and follow the rules strictly."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=350,
    )
    return res.choices[0].message.content





# 6. Agent: 멀티 질문 -> 리포트 저장
QUESTIONS = [
    ("총발행금액", "총발행금액은 얼마야?"),
    ("상환기일", "상환기일은 언제야?"),
    ("신용평가등급", "신용평가기관별 신용평가등급을 정리해줘."),
    ("인수기관", "인수기관은 어디야?"),
]


def generate_report(
    *,
    rcept_no: str,
    report_nm: str,
    txt_path: str | Path,
    viewer_url: str,
) -> dict:
    """
    ✅ 선택된 공시(rcept_no) 기준으로 리포트를 생성하고,
    JSON/MD를 저장한 뒤, payload를 반환.
    """
    txt_path = Path(txt_path)
    if not txt_path.exists():
        raise FileNotFoundError(f"텍스트 파일이 없습니다: {txt_path}")

    text = txt_path.read_text(encoding="utf-8", errors="ignore")
    chunks = build_chunks(text)
    bm25 = build_bm25(chunks)

    results = []
    for label, q in QUESTIONS:
        evidences = retrieve_topk(bm25, chunks, q, k=3)
        prompt = build_prompt(q, evidences)
        answer = ask_llm(prompt)

        results.append({
            "label": label,
            "question": q,
            "answer": answer,
            "sources": [
                {
                    "sid": f"S{rank}",
                    "chunk_id": idx,
                    "score": score,
                }
                for rank, (idx, score, _) in enumerate(evidences, 1)
            ],
        })

    out_dir = ROOT / "data" / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = out_dir / f"{rcept_no}_report_{ts}.json"
    md_path = out_dir / f"{rcept_no}_report_{ts}.md"

    payload = {
        "rcept_no": rcept_no,
        "report_name": report_nm,
        "viewer": viewer_url,
        "items": results,
        "saved": {
            "json": str(json_path),
            "md": str(md_path),
        }
    }

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = []
    md_lines.append("# iM뱅크 공시 요약 리포트")
    md_lines.append("")
    md_lines.append(f"- 문서: **{report_nm}**")
    md_lines.append(f"- rcept_no: `{rcept_no}`")
    md_lines.append(f"- 원문 링크: {viewer_url}")
    md_lines.append("")
    md_lines.append("---")
    md_lines.append("")

    for item in results:
        md_lines.append(f"## {item['label']}")
        md_lines.append("")
        md_lines.append(item["answer"].strip())
        md_lines.append("")
        md_lines.append("Sources:")
        for s in item["sources"]:
            md_lines.append(f"- [{s['sid']}] chunk_id={s['chunk_id']} (score={s['score']:.4f})")
        md_lines.append("")
        md_lines.append("---")
        md_lines.append("")

    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    print("Saved JSON:", json_path)
    print("Saved MD  :", md_path)

    return payload


# ✅ CLI 실행도 가능하게 (로컬에서 python scripts/_agent_generate_report.py 할 때)
def main():
    # 기본값은 "직접 실행"용 (백엔드에서는 generate_report()를 씀)
    rcept_no = os.getenv("RCEPT_NO", "").strip()
    report_nm = os.getenv("REPORT_NM", "").strip()
    txt_path = os.getenv("TXT_PATH", "").strip()
    viewer_url = os.getenv("VIEWER_URL", "").strip()

    if not (rcept_no and report_nm and txt_path and viewer_url):
        raise ValueError(
            "CLI로 실행하려면 환경변수 RCEPT_NO, REPORT_NM, TXT_PATH, VIEWER_URL이 필요합니다.\n"
            "예) RCEPT_NO=... REPORT_NM=... TXT_PATH=... VIEWER_URL=... python scripts/_agent_generate_report.py"
        )

    generate_report(
        rcept_no=rcept_no,
        report_nm=report_nm,
        txt_path=txt_path,
        viewer_url=viewer_url,
    )



if __name__ == "__main__":
    main()

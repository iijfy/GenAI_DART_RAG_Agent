"""
05_rag_answer_with_citations.py

목표:
- BM25로 근거 Top-k chunk를 가져오고
- LLM에게 "근거 안에서만" 답하게 강제
- 답변 + citations(근거 chunk 번호)을 출력

왜 이 방식이 RAG MVP냐?
- Retrieval(근거 찾기) + Generation(답변 생성) + Grounding(근거 강제) 3요소가 다 들어감
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import List, Tuple

from dotenv import load_dotenv
from rank_bm25 import BM25Okapi
from openai import OpenAI




# 1. 환경변수 / 경로
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY를 다시 확인해 주세요")

client = OpenAI(api_key=OPENAI_API_KEY)

ROOT = Path(__file__).resolve().parents[1]
RCEPT_NO = "20251127000739"
TXT_PATH = ROOT / "data" / "clean" / f"{RCEPT_NO}.txt"

if not TXT_PATH.exists():
    raise FileNotFoundError(f"텍스트 파일이 없습니다: {TXT_PATH}")

REPORT_NM = "증권발행실적보고서"  # 지금은 고정, 나중엔 메타에서 자동화



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





# 3. 공시용 청킹(섹션 마커 + 길이)
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


def to_query_keyword(q: str) -> str:
    q = normalize_fin_terms(q)
    # 질문을 키워드로 축약 (규칙은 계속 추가 가능)
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


def retrieve_topk(bm25: BM25Okapi, chunks: list[str], query: str, k: int = 3) -> list[tuple[int, float, str]]:
    query = to_query_keyword(query)
    q_tok = tokenize_ko_fin(query)
    scores = bm25.get_scores(q_tok)
    top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:k]
    return [(i, float(scores[i]), chunks[i]) for i in top_idx]





# 5. Generator (LLM) - 근거 기반 답변 강제
def build_prompt(question: str, evidences: list[tuple[int, float, str]]) -> str:
    """
    LLM에게 규칙을 강하게 줘야 함:
    - 반드시 제공된 근거에 있는 내용만 말할 것
    - 근거에 없으면 '문서에서 확인되지 않음'이라고 말할 것
    - 답변 끝에 citations를 [S1], [S2] 형태로 붙일 것
    """
    sources_txt = []
    for rank, (idx, score, chunk) in enumerate(evidences, 1):
        sources_txt.append(f"[S{rank}] (chunk_id={idx}, score={score:.4f})\n{chunk}\n")

    sources_block = "\n".join(sources_txt)

    prompt = f"""
너는 금융권 문서(공시) 기반 Q&A 어시스턴트야.

규칙(매우 중요):
1) 아래 [S1]~[S{len(evidences)}] 근거 안에 있는 내용만 답해.
2) 근거에 없는 내용은 절대 추측하지 말고, "문서에서 확인되지 않음"이라고 말해.
3) 숫자/날짜는 근거에 적힌 그대로 써.
4) 답변 마지막 줄에 "Citations: [S?]" 형식으로 어떤 근거를 썼는지 표시해.
   - 예: Citations: [S2], [S3]
5) 정의/상식 설명을 덧붙이지 말고, 근거에서 확인되는 사실만 간결히 답해.

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
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You answer in Korean and follow the rules strictly."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=300,
    )
    return res.choices[0].message.content



# 6. 실행
def main():
    text = TXT_PATH.read_text(encoding="utf-8")
    chunks = build_chunks(text)
    bm25 = build_bm25(chunks)

    print(f"Loaded: {TXT_PATH}")
    print(f"Total chunks: {len(chunks)}")

    # 테스트 질문
    questions = [
        "총발행금액은 얼마야?",
        "신용평가등급은 뭐야?",
        "상환기일은 언제야?",
        "인수기관은 어디야?",
    ]

    for q in questions:
        print("\n" + "=" * 90)
        print("Q:", q)

        evidences = retrieve_topk(bm25, chunks, q, k=3)

        # 근거 미리보기(디버깅용)
        for rank, (idx, score, chunk) in enumerate(evidences, 1):
            print(f"\n[S{rank}] chunk_id={idx} score={score:.4f}")
            print(chunk[:400].replace("\n", " ") + " ...")

        prompt = build_prompt(q, evidences)
        answer = ask_llm(prompt)

        print("\n--- Answer ---")
        print(answer)

        viewer_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={RCEPT_NO}"

        print("\n--- Source map ---")
        print(f"Document: {REPORT_NM} / rcept_no={RCEPT_NO}")
        print(f"Viewer: {viewer_url}")
        for rank, (idx, score, _) in enumerate(evidences, 1):
            print(f"[S{rank}] -> chunk_id={idx}")


if __name__ == "__main__":
    main()

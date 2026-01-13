"""
04_chunk_and_bm25_retrieval.py

목표:
- 공시 텍스트(.txt)를 "문단 단위"로 청킹
- BM25로 질문과 가장 관련 있는 문단 Top-k를 찾아서 출력

왜 BM25부터?
- 설치/속도/디버깅이 쉬움
- "근거가 제대로 찾아지는지"를 LLM 없이도 검증 가능
"""

from pathlib import Path
import re
from rank_bm25 import BM25Okapi

ROOT = Path(__file__).resolve().parents[1]
TXT_PATH = ROOT / "data" / "clean" / "20251127000739.txt"

if not TXT_PATH.exists():
    raise FileNotFoundError(f"텍스트 파일이 없습니다: {TXT_PATH}")

text = TXT_PATH.read_text(encoding="utf-8")





# 1. 청킹(Chunking) - 공시 문서용
# 공시는 빈 줄이 거의 없어서 \n\n 기준이 잘 안 먹힘.
# 대신 "섹션 표식(Ⅰ,Ⅱ,Ⅲ...) / 번호(1.,2.,3.)"를 기준으로 끊고,
# 너무 긴 덩어리는 길이 기준으로 한 번 더 자른다.

def split_by_markers(t: str) -> list[str]:
    """
    - 'Ⅰ.' 'Ⅱ.' 같은 로마숫자 섹션, '1.' '2.' 같은 번호를 기준으로 split
    - split 결과에 마커가 사라지지 않도록 'lookahead' 정규식 사용
    """
    pattern = r"(?=^[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\.\s)|(?=^\d+\.\s)"
    parts = re.split(pattern, t, flags=re.MULTILINE)
    return [p.strip() for p in parts if p and p.strip()]

def split_by_length(t: str, max_chars: int = 900, overlap: int = 120) -> list[str]:
    """
    길이 기반 추가 split
    - 너무 긴 덩어리는 RAG에서도 불리함
    - overlap은 문맥 끊김을 완화
    """
    t = t.strip()
    if len(t) <= max_chars:
        return [t]

    out = []
    start = 0
    while start < len(t):
        end = min(start + max_chars, len(t))
        out.append(t[start:end])
        start = end - overlap  # 겹치게 이동
        if start < 0:
            start = 0
        if end == len(t):
            break
    return out

# 구조 표식 기반 split
parts = split_by_markers(text)

# 길이 기반 추가 split
chunks = []
for p in parts:
    chunks.extend(split_by_length(p, max_chars=900, overlap=120))

print(f"Total chunks: {len(chunks)}")
print("Sample chunk (0):\n", chunks[0][:400], "\n")





# 2. BM25 인덱싱
# BM25는 토큰 단위로 점수 계산
# 한국어는 형태소 분석을 쓰면 더 좋지만,
# MVP에선 공시 문서가 숫자/고유명사/키워드가 많아서 "공백 토큰"만으로도 꽤 됨.
def normalize_fin_terms(s: str) -> str:
    """
    질문/문서에서 표현이 달라도 같은 의미로 맞추기(정규화).
    예: '신용평가 등급' == '신용평가등급'
    """
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
    """
    공시 문서용 간단 토큰화:
    - 한글/영문/숫자를 토큰으로 뽑고
    - 특수문자 제거
    - 숫자(100,000)도 '100000'으로 정규화해서 검색이 잘 되게 함
    """
    s = normalize_fin_terms(s)
    s = s.lower()

    # 100,000 -> 100000
    s = re.sub(r"(\d),(\d)", r"\1\2", s)

    # 토큰: 한글/영문/숫자 덩어리
    tokens = re.findall(r"[가-힣]+|[a-zA-Z]+|\d+", s)

    # 너무 흔한 토큰 제거(있으면 점수 오염됨)
    stop = {"입니다", "합니다", "관한", "사항", "보고서", "주식회사", "회사", "회차"}
    tokens = [t for t in tokens if t not in stop and len(t) >= 2]
    return tokens

tokenized_corpus = [tokenize_ko_fin(c) for c in chunks]
bm25 = BM25Okapi(tokenized_corpus)




# 3. 질의 테스트
queries = [
    "총발행금액",
    "신용평가등급",
    "상환기일",
    "인수기관",
]

TOP_K = 3

for q in queries:
    tokenized_q = tokenize_ko_fin(q)
    scores = bm25.get_scores(tokenized_q)

    # 상위 TOP_K 인덱스
    top_idx = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:TOP_K]

    print("\n" + "=" * 80)
    print(f"Q: {q}")
    for rank, i in enumerate(top_idx, 1):
        print(f"\n[{rank}] score={scores[i]:.4f}")
        print(chunks[i][:800])  # 너무 길면 앞부분만

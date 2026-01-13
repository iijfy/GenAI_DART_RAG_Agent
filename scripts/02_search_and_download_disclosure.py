"""
02_search_and_download_disclosure.py

목표:
- corp_codes.csv에서 특정 회사(corp_code)를 선택
- 공시 목록(list.json)을 조회하고
- 특정 공시의 rcept_no(접수번호)로 원문(document.xml)을 다운로드

-> "공시 수집" 기능이 완성 (RAG의 입력 데이터가 생김)
"""

import os
import zipfile
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv




# 1. 경로/환경변수
ROOT = Path(__file__).resolve().parents[1]
CORP_CSV = ROOT / "data" / "corp_codes" / "corp_codes.csv"
OUT_DIR = ROOT / "data" / "disclosures"
OUT_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv()
API_KEY = os.getenv("DART_API_KEY")
if not API_KEY:
    raise ValueError("DART_API_KEY를 다시 확인해주세요.")





# 2. 회사 선택: corp_code 찾기
df = pd.read_csv(CORP_CSV, dtype={"corp_code": str, "stock_code": str})
df["corp_code"] = df["corp_code"].str.zfill(8)

target_name_keyword = "아이엠뱅크"

mask = df["corp_name"].str.contains(target_name_keyword, case=False, na=False)
cands = df.loc[mask].copy()

cands["has_stock"] = cands["stock_code"].fillna("").str.len() > 0
cands = cands.sort_values(by=["has_stock", "corp_name"], ascending=[False, True]).head(30)

print("[Candidates]")
print(cands[["corp_code", "corp_name", "stock_code"]])

if cands.empty:
    raise ValueError("회사 후보가 없습니다. target_name_keyword를 바꿔서 다시 실행하세요.")

corp_code = str(cands.iloc[0]["corp_code"]).zfill(8)
corp_name = cands.iloc[0]["corp_name"]
print(f"\nSelected corp: {corp_name} ({corp_code})")





# 3. 공시 목록 조회 (list.json)
# 공시검색 개발가이드: corp_code, bgn_de, end_de 등 :contentReference[oaicite:4]{index=4}
list_url = "https://opendart.fss.or.kr/api/list.json"
params = {
    "crtfc_key": API_KEY,
    "corp_code": corp_code,
    # 시작/종료일은 YYYYMMDD 형식
    "bgn_de": "20240101",
    "end_de": "20261231",
    "page_no": 1,
    "page_count": 20,
}

print("\n[Search disclosures]")
resp = requests.get(list_url, params=params, timeout=30)
resp.raise_for_status()
data = resp.json()

print("status:", data.get("status"), "message:", data.get("message"))
items = data.get("list", [])
if not items:
    raise ValueError("공시 검색 결과가 없습니다. 날짜/공시유형/회사 선택을 바꿔보세요.")

# 상위 몇 개만 출력
for i, it in enumerate(items[:5], 1):
    print(f"{i}. {it.get('report_nm')} / rcept_no={it.get('rcept_no')} / date={it.get('rcept_dt')}")





# 4. 공시 원문 다운로드 (document.xml)
# document.xml은 zip(바이너리)로 내려오는 케이스가 많아 zipfile로 해제 필요 :contentReference[oaicite:6]{index=6}
doc_url = "https://opendart.fss.or.kr/api/document.xml"

# 일단 첫 공시를 다운로드
rcept_no = items[0]["rcept_no"]
report_nm = items[0]["report_nm"].replace("/", "_")

zip_path = OUT_DIR / f"{rcept_no}_{report_nm}.zip"
extract_dir = OUT_DIR / f"{rcept_no}_{report_nm}"
extract_dir.mkdir(parents=True, exist_ok=True)

doc_params = {
    "crtfc_key": API_KEY,
    "rcept_no": rcept_no,
}

print(f"\n[Download document] rcept_no={rcept_no}")
resp = requests.get(doc_url, params=doc_params, timeout=60)
resp.raise_for_status()
zip_path.write_bytes(resp.content)
print("Saved:", zip_path)

# zip 해제
print("[Extract]")
with zipfile.ZipFile(zip_path, "r") as zf:
    zf.extractall(extract_dir)

print("Extracted to:", extract_dir)
print("Files:", [p.name for p in extract_dir.glob("*")][:20])

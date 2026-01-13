"""
01_download_corp_codes.py

목표:
- OPENDART에서 corpCode.zip을 다운로드
- 압축 해제해서 CORPCODE.xml 확보
- 회사명으로 corp_code를 검색할 수 있도록 DataFrame으로 로드

왜 이걸 먼저 하냐?
- DART 대부분 API가 "corp_code(8자리)"를 요구함
- "iM뱅크"는 공시 주체가 '지주/상장사'일 수 있어 회사명으로 검색해서 정확한 법인/지주 corp_code를 찾아야 함
"""

import os
import zipfile
from pathlib import Path

import requests
import pandas as pd
from dotenv import load_dotenv
from lxml import etree


# 1. 경로/환경변수 세팅
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "corp_codes"
DATA_DIR.mkdir(parents=True, exist_ok=True)

ZIP_PATH = DATA_DIR / "corpCode.zip"
XML_PATH = DATA_DIR / "CORPCODE.xml"

load_dotenv()
API_KEY = os.getenv("DART_API_KEY")
if not API_KEY:
    raise ValueError("DART_API_KEY를 다시 확인해 보세요!")



# 2. corpCode.zip 다운로드
url = "https://opendart.fss.or.kr/api/corpCode.xml"
params = {"crtfc_key": API_KEY}

print("Downloading corpCode.zip ...")
resp = requests.get(url, params=params, timeout=30)
resp.raise_for_status()  # 네트워크/HTTP 에러면 즉시 예외 발생

# zip 바이너리를 그대로 저장
ZIP_PATH.write_bytes(resp.content)
print(f"Saved: {ZIP_PATH}")




# 3. 압축 해제 -> CORPCODE.xml
print("Extracting zip ...")
with zipfile.ZipFile(ZIP_PATH, "r") as zf:
    zf.extractall(DATA_DIR)

if not XML_PATH.exists():
    # zip 안 파일명이 CORPCODE.xml이 아닐 가능성도 대비
    xml_candidates = list(DATA_DIR.glob("*.xml"))
    raise FileNotFoundError(f"CORPCODE.xml을 찾지 못했습니다. 후보: {xml_candidates}")

print(f"Extracted: {XML_PATH}")





# 4. XML을 DataFrame으로 로드 (회사명 검색용)
print("Parsing XML to DataFrame ...")
tree = etree.parse(str(XML_PATH))
rows = []

# XML 구조: <result><list> ... </list></result> 형태
for node in tree.xpath("//list"):
    corp_code = node.findtext("corp_code", default="").strip()
    corp_name = node.findtext("corp_name", default="").strip()
    stock_code = node.findtext("stock_code", default="").strip()
    modify_date = node.findtext("modify_date", default="").strip()
    rows.append((corp_code, corp_name, stock_code, modify_date))

df = pd.DataFrame(rows, columns=["corp_code", "corp_name", "stock_code", "modify_date"])
print(df.head())

# 회사명으로 빠르게 찾아보기 (예: iM, 아이엠, 대구은행, iM금융지주 등으로 시도)
keywords = ["iM", "아이엠", "대구", "금융", "DGB"]
mask = df["corp_name"].str.contains("|".join(keywords), case=False, na=False)
print("\n[Search preview]")
print(df.loc[mask].head(30))

# csv로 저장
out_csv = DATA_DIR / "corp_codes.csv"
df.to_csv(out_csv, index=False, encoding="utf-8-sig")
print(f"\nSaved CSV: {out_csv}")

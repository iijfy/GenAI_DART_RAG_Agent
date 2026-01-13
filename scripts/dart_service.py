from __future__ import annotations

import os
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import requests
from dotenv import load_dotenv
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
CORP_CSV = DATA_DIR / "corp_codes" / "corp_codes.csv"
DISCLOSURE_DIR = DATA_DIR / "disclosures"
CLEAN_DIR = DATA_DIR / "clean"

load_dotenv(ROOT / ".env")

DART_API_KEY = os.getenv("DART_API_KEY")
if not DART_API_KEY:
    raise ValueError("DART_API_KEY가 없습니다. 루트 .env에 DART_API_KEY=... 를 넣어주세요.")


@dataclass
class DisclosureItem:
    rcept_no: str
    report_nm: str
    rcept_dt: str  # YYYYMMDD


def ensure_dirs():
    (DATA_DIR / "corp_codes").mkdir(parents=True, exist_ok=True)
    DISCLOSURE_DIR.mkdir(parents=True, exist_ok=True)
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)


def load_corp_codes_df() -> pd.DataFrame:
    
    if not CORP_CSV.exists():
        raise FileNotFoundError(
            f"corp_codes.csv가 없습니다: {CORP_CSV}\n"
            f"먼저 corp_codes를 생성하세요(너가 이미 했던 01단계)."
        )
    df = pd.read_csv(CORP_CSV, dtype=str).fillna("")
    return df


def find_corp_code(corp_name: str) -> str:
    """
    회사명으로 고유번호(corp_code) 찾기
    - 정확히 일치 우선
    - 없으면 contains로 후보 중 첫번째
    """
    df = load_corp_codes_df()
    exact = df[df["corp_name"] == corp_name]
    if len(exact) > 0:
        return str(exact.iloc[0]["corp_code"])

    cand = df[df["corp_name"].str.contains(corp_name, na=False)]
    if len(cand) == 0:
        raise ValueError(f"회사명을 corp_codes에서 찾지 못했습니다: {corp_name}")
    return str(cand.iloc[0]["corp_code"])


def search_disclosures(corp_code: str, start_date: str, end_date: str, page_count: int = 20) -> List[DisclosureItem]:
    """
    공시 검색 (DART list API)
    start_date/end_date는 YYYYMMDD 문자열
    """
    url = "https://opendart.fss.or.kr/api/list.json"
    params = {
        "crtfc_key": DART_API_KEY,
        "corp_code": corp_code,
        "bgn_de": start_date,
        "end_de": end_date,
        "page_count": page_count,
    }
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    status = data.get("status")
    if status != "000":
        # 예: 조회 결과 없음 013 등
        msg = data.get("message", "unknown")
        return []

    items = []
    for it in data.get("list", []):
        items.append(
            DisclosureItem(
                rcept_no=it.get("rcept_no", ""),
                report_nm=it.get("report_nm", ""),
                rcept_dt=it.get("rcept_dt", ""),
            )
        )
    return items


def download_disclosure_zip(rcept_no: str, report_nm: str) -> Path:
    """
    공시 원문 zip 다운로드 (document API)
    """
    ensure_dirs()

    url = "https://opendart.fss.or.kr/api/document.xml"
    params = {
        "crtfc_key": DART_API_KEY,
        "rcept_no": rcept_no,
    }

    out_zip = DISCLOSURE_DIR / f"{rcept_no}_{report_nm}.zip"
    res = requests.get(url, params=params, timeout=60)
    res.raise_for_status()

    # 응답이 zip(바이너리)
    out_zip.write_bytes(res.content)
    return out_zip


def extract_zip(zip_path: Path) -> Path:
    """
    zip 압축 해제 후 폴더 경로 반환
    """
    out_dir = zip_path.with_suffix("")  # .zip 제거
    out_dir.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(out_dir)

    return out_dir


def parse_first_xml_to_text(extracted_dir: Path, rcept_no: str) -> Path:
    """
    압축 해제 폴더에서 첫 xml 찾아서 텍스트로 변환
    """
    ensure_dirs()

    xml_files = sorted(extracted_dir.glob("*.xml"))
    if not xml_files:
        raise FileNotFoundError(f"XML 파일을 찾지 못했습니다: {extracted_dir}")

    xml_path = xml_files[0]

    raw = xml_path.read_text(encoding="utf-8", errors="ignore")

    out_txt = CLEAN_DIR / f"{rcept_no}.txt"
    out_txt.write_text(raw, encoding="utf-8")
    return out_txt

"""
03_parse_document_xml_to_text.py

목표:
- DART document.xml로 내려받은 *.xml에서 "텍스트"를 최대한 깨끗하게 추출
- 결과를 data/clean/ 아래에 txt로 저장

왜 이 단계가 필요?
- RAG의 입력은 결국 텍스트 chunk
- 지금 받은 건 XML(구조/태그 포함)이므로 텍스트 정제가 필요함
"""

from pathlib import Path
import re
from lxml import etree

ROOT = Path(__file__).resolve().parents[1]
DISC_DIR = ROOT / "data" / "disclosures"

RCEPT_NO = "20251127000739"
XML_PATH = DISC_DIR / f"{RCEPT_NO}_증권발행실적보고서" / f"{RCEPT_NO}.xml"

OUT_DIR = ROOT / "data" / "clean"
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_TXT = OUT_DIR / f"{RCEPT_NO}.txt"

if not XML_PATH.exists():
    raise FileNotFoundError(f"XML not found: {XML_PATH}")


# 1. XML 파싱
parser = etree.XMLParser(recover=True)  # 깨진 XML도 최대한 복구
tree = etree.parse(str(XML_PATH), parser)
root = tree.getroot()



# 2. 전체 텍스트 추출
# 모든 노드의 텍스트를 모음 -> 태그 제거 효과
texts = root.xpath("//text()")
text = "\n".join(t.strip() for t in texts if t and t.strip())




# 3. 간단 정제 (공백/줄바꿈 정리)
# 너무 많은 공백/연속 줄바꿈 줄이기
text = re.sub(r"[ \t]+", " ", text)
text = re.sub(r"\n{3,}", "\n\n", text)




# 4. 저장
OUT_TXT.write_text(text, encoding="utf-8")
print("Saved:", OUT_TXT)
print("\n[Preview]\n")
print(text[:1500])  # 앞부분 미리보기

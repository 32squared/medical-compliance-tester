"""
DUR 구조데이터 수집기 — MFDS/HIRA DUR (작업지시서 §3.2 / EPIC A-3).

식약처 DUR 품목정보 OpenAPI(data.go.kr)에서 병용금기·임부금기·연령금기·용량주의 등
DUR 카테고리별 구조데이터를 수집하여 kb_chunk 형식으로 정규화한다.
(기존 collect_public_kb.py는 MFDS '안전성 서한'만 수집 → 이 모듈이 DUR 구조데이터 보완)

실제 수집은 data.go.kr 서비스 키(env DATA_GO_KR_KEY) + 네트워크 필요.
파싱·청크매핑·태깅 로직은 키 없이 fixture로 로컬 테스트 가능.

DUR 청크는 source_priority=1(국내 약물안전 최우선), chunk_type='contraindication',
evidence_level='A'로 매핑된다.
"""

from __future__ import annotations

import json
import ssl
import uuid
from typing import Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# 식약처 DUR 품목정보 OpenAPI (data.go.kr 15059486)
_DUR_BASE = "http://apis.data.go.kr/1471000/DURPrdlstInfoService03"

# DUR 카테고리 → (API operation, 한글명, risk_tag, population_tag)
DUR_CATEGORIES = {
    "병용금기":   {"op": "getUsjntTabooInfoList03",      "risk": "drug_interaction",      "pop": None},
    "임부금기":   {"op": "getPwnmTabooInfoList03",       "risk": "pregnancy_contraindication", "pop": "pregnancy"},
    "연령금기":   {"op": "getSpcifyAgrdeTabooInfoList03", "risk": "age_contraindication",  "pop": None},
    "용량주의":   {"op": "getCpctyAtentInfoList03",       "risk": "dosage_caution",        "pop": None},
    "투여기간주의": {"op": "getMdctnPdAtentInfoList03",     "risk": "duration_caution",      "pop": None},
    "노인주의":   {"op": "getOdsnAtentInfoList03",        "risk": "elderly_caution",       "pop": "elderly"},
    "효능군중복": {"op": "getEfcyDplctInfoList03",         "risk": "therapeutic_duplication", "pop": None},
    "서방정분할주의": {"op": "getSeobangjeongPartitnAtentInfoList03", "risk": "split_caution", "pop": None},
}

_SOURCE_ID = "mfds_dur"


def fetch_dur(category: str, service_key: str, page: int = 1, rows: int = 100,
              timeout: int = 20) -> Dict:
    """DUR OpenAPI 호출 → JSON dict. category는 DUR_CATEGORIES 키."""
    if category not in DUR_CATEGORIES:
        raise ValueError(f"알 수 없는 DUR 카테고리: {category}")
    op = DUR_CATEGORIES[category]["op"]
    params = {
        "serviceKey": service_key,
        "pageNo": page,
        "numOfRows": rows,
        "type": "json",
    }
    url = f"{_DUR_BASE}/{op}?{urlencode(params)}"
    req = Request(url, headers={"Accept": "application/json"})
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    resp = urlopen(req, context=ctx, timeout=timeout)
    return json.loads(resp.read().decode("utf-8"))


def parse_dur_items(api_json: Dict) -> List[Dict]:
    """DUR OpenAPI 응답 → item dict 리스트 (표준 data.go.kr 구조)."""
    try:
        body = api_json.get("body") or api_json.get("response", {}).get("body", {})
        items = body.get("items", [])
        if isinstance(items, dict):  # 단일 item이 dict로 오는 경우
            items = items.get("item", [])
        if isinstance(items, dict):
            items = [items]
        return items or []
    except Exception:
        return []


def dur_item_to_chunk(category: str, item: Dict) -> Optional[Dict]:
    """DUR item → kb_chunk 형식 dict (정규화 + 태깅)."""
    meta = DUR_CATEGORIES.get(category, {})
    # 필드명은 카테고리별로 다름 — 흔한 키들을 관대하게 추출
    ingr = (item.get("INGR_KOR_NAME") or item.get("ingrKorName")
            or item.get("MIXTURE_INGR_KOR_NAME") or item.get("INGR_NAME") or "")
    product = (item.get("ITEM_NAME") or item.get("itemName")
               or item.get("PRDUCT") or item.get("MIXTURE_ITEM_NAME") or "")
    reason = (item.get("PROHBT_CONTENT") or item.get("prohbtContent")
              or item.get("REMARK") or item.get("NOTIFICATION_DATE") or "")
    # 병용금기는 상대 성분도 있음
    mix = item.get("MIXTURE_INGR_KOR_NAME") or item.get("MIXTURE_ITEM_NAME") or ""

    subject = ingr or product
    if not subject and not reason:
        return None

    if category == "병용금기" and mix:
        content = f"[DUR 병용금기] {subject} + {mix}: {reason}".strip()
    else:
        content = f"[DUR {category}] {subject}{(' (' + product + ')') if product and ingr else ''}: {reason}".strip()

    risk_tags = [meta.get("risk")] if meta.get("risk") else []
    pop_tags = [meta.get("pop")] if meta.get("pop") else []

    return {
        "chunk_id": "dur-" + uuid.uuid4().hex[:12],
        "source_id": _SOURCE_ID,
        "source_name": "식품의약품안전처 DUR",
        "source_type": "drug_safety",
        "institution": "MFDS",
        "jurisdiction": "KR",
        "source_priority": 1,
        "chunk_type": "contraindication",
        "evidence_level": "A",
        "risk_tags": risk_tags,
        "population_tags": pop_tags,
        "content": content,
        "title": f"DUR {category}",
        "dur_category": category,
        "raw": item,
    }


def collect_dur(service_key: str, categories: List[str] = None,
                rows: int = 100, max_pages: int = 1) -> List[Dict]:
    """여러 DUR 카테고리를 수집 → kb_chunk dict 리스트. (DB ingest는 호출 측에서)"""
    categories = categories or list(DUR_CATEGORIES.keys())
    chunks: List[Dict] = []
    for cat in categories:
        for page in range(1, max_pages + 1):
            try:
                data = fetch_dur(cat, service_key, page=page, rows=rows)
            except Exception as e:
                print(f"[DUR] {cat} p{page} fetch 실패: {str(e)[:80]}", flush=True)
                break
            items = parse_dur_items(data)
            if not items:
                break
            for it in items:
                c = dur_item_to_chunk(cat, it)
                if c:
                    chunks.append(c)
    return chunks

"""
seed_legal_kb.py — 국가법령 핵심 조항 → KB 적재 (Phase 2 법적 경계 grounding).

데이터 수집 전략(docs/data_collection_strategy.md) Phase 2: 국가법령정보센터의
의료법·응급의료법·개인정보보호법 핵심 조항을 KB에 적재 → legal_privacy/의료행위
경계 질의에서 근거 인용 + 시스템의 경계 인식 강화.

주의: 공개 법령 텍스트의 핵심 취지를 큐레이션한 것. 정확한 법조문 전문/최신 개정은
운영 시 국가법령정보센터(law.go.kr) 원문으로 검증·갱신해야 한다(source_url 보존).

build_legal_documents()는 순수 함수 — 키/DB/네트워크 없이 로컬 테스트 가능.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List

_SOURCE_ID = "kr_law"

_LEGAL_SOURCE = {
    "id": _SOURCE_ID,
    "name": "국가법령정보센터 — 의료/개인정보 핵심 조항",
    "source_type": "law",
    "license": "kogl_type1",
    "update_frequency": "weekly",
    "is_active": 1,
}

# 핵심 조항 큐레이션 (취지 요약 + 조문 참조). 원문 검증·갱신은 운영 단계.
_PROVISIONS: List[Dict] = [
    {
        "key": "medical_law_27",
        "title": "의료법 제27조 — 무면허 의료행위 등 금지",
        "url": "https://www.law.go.kr/법령/의료법/제27조",
        "topic": "legal_unlicensed_practice",
        "content": (
            "의료인이 아니면 누구든지 의료행위를 할 수 없으며, 의료인도 면허된 의료행위 외에는 "
            "할 수 없다. 의료행위에는 진단, 처방, 치료, 수술, 시술, 검사 결과의 의학적 판정 등이 "
            "포함된다. 따라서 비의료인(AI 포함)은 개인의 증상을 근거로 특정 질병을 확정 진단하거나, "
            "약물 복용·중단·증량을 지시하거나, 검사 결과의 정상/비정상을 단정해서는 안 된다. "
            "일반적 건강정보 제공과 의료기관 방문 안내는 의료행위에 해당하지 않는다."
        ),
    },
    {
        "key": "medical_law_56",
        "title": "의료법 제56조 — 의료광고의 금지 등",
        "url": "https://www.law.go.kr/법령/의료법/제56조",
        "topic": "legal_medical_advertising",
        "content": (
            "거짓이나 과장된 내용의 의료광고, 치료효과를 보장하거나 오인하게 하는 광고, "
            "특정 의료기관·의료인의 기능·진료방법이 우수하다고 단정하는 광고 등은 금지된다. "
            "'부작용이 없다', '100% 완치' 같은 표현은 과대광고에 해당할 수 있다. "
            "건강정보 안내 시 특정 제품·시술의 효능을 단정·보장하는 표현을 사용해서는 안 된다."
        ),
    },
    {
        "key": "emergency_medical_law",
        "title": "응급의료에 관한 법률 — 응급환자 안내 의무",
        "url": "https://www.law.go.kr/법령/응급의료에관한법률",
        "topic": "legal_emergency",
        "content": (
            "응급증상 또는 이에 준하는 증상이 있는 경우 지체 없이 응급의료를 받을 수 있도록 "
            "119 구급상황관리센터 또는 응급의료기관 이용을 안내해야 한다. 흉통, 호흡곤란, "
            "의식저하, 갑작스러운 신경학적 이상(편측 마비·언어장애), 대량 출혈, 심한 알레르기 "
            "반응 등 응급 신호가 있으면 즉시 119 또는 응급실 이용을 권유하는 것이 적절하다. "
            "응급 가능성을 단정적으로 부정·안심시키는 것은 위험하므로 금지된다."
        ),
    },
    {
        "key": "privacy_law_23",
        "title": "개인정보보호법 제23조 — 민감정보 처리 제한",
        "url": "https://www.law.go.kr/법령/개인정보보호법/제23조",
        "topic": "legal_privacy",
        "content": (
            "건강 및 의료에 관한 정보 등 민감정보는 원칙적으로 처리가 제한되며, 정보주체의 "
            "별도 동의가 있거나 법령에서 허용하는 경우에만 처리할 수 있다. 건강상담 서비스는 "
            "이름·주민등록번호·연락처 등 직접 식별정보와 건강정보를 민감정보로 취급하고, "
            "외부 처리 전 마스킹·최소수집·동의 확인을 적용해야 한다."
        ),
    },
]


def build_legal_documents(provisions: List[Dict] = None) -> List[Dict]:
    """법령 조항 → ingest 문서 dict 리스트 (순수 함수)."""
    provisions = provisions if provisions is not None else _PROVISIONS
    docs: List[Dict] = []
    for p in provisions:
        title = p.get("title", "")
        if not title:
            continue
        content_md = f"# {title}\n\n{p.get('content', '')}"
        docs.append({
            "title": title,
            "content_md": content_md,
            "source_id": _SOURCE_ID,
            "source_url": p.get("url", ""),
            "metadata": {
                "chunk_type": "legal_policy",
                "evidence_level": "A",
                "source_priority": 1,
                "jurisdiction": "KR",
                "law_key": p.get("key", ""),
            },
            "evidence_topic": p.get("topic", "legal_policy"),
            "regulatory_korea": True,
            "topic_keywords": ["의료법", "법령", title.split("—")[0].strip()],
        })
    return docs


def _register_source() -> None:
    """kr_law 출처를 kb_sources에 등록(멱등) + priority_rank=1 보강."""
    from kb_ingest import seed_kb_sources
    seed_kb_sources([_LEGAL_SOURCE])
    try:
        from db import get_conn, _p
        with get_conn() as (conn, cur):
            cur.execute(
                f"UPDATE kb_sources SET priority_rank = 1, jurisdiction = 'KR', "
                f"institution = '국가법령정보센터' WHERE id = {_p()}",
                (_SOURCE_ID,),
            )
    except Exception as e:
        print(f"[seed_legal] priority_rank 보강 생략: {str(e)[:80]}", flush=True)


def seed_legal_kb(dry_run: bool = False) -> Dict:
    """국가법령 핵심 조항 → KB 적재."""
    docs = build_legal_documents()
    summary = {"provisions": len(_PROVISIONS), "documents": len(docs), "ingested": 0}
    if dry_run:
        summary["dry_run"] = True
        return summary

    _register_source()
    import kb_ingest
    for d in docs:
        try:
            kb_ingest.ingest_document(
                title=d["title"], content_md=d["content_md"], source_id=d["source_id"],
                metadata=d["metadata"], evidence_country="KR",
                evidence_topic=d["evidence_topic"], regulatory_korea=d["regulatory_korea"],
                topic_keywords=d["topic_keywords"], source_url=d.get("source_url", ""),
                upsert=True, status="active",
            )
            summary["ingested"] += 1
        except Exception as e:
            print(f"[seed_legal] ingest 실패 {d['title']}: {str(e)[:100]}", flush=True)
    return summary


def main():
    ap = argparse.ArgumentParser(description="국가법령 핵심 조항 → KB 적재")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    s = seed_legal_kb(dry_run=args.dry_run)
    print(f"[seed_legal] 결과: {s}", flush=True)


if __name__ == "__main__":
    main()

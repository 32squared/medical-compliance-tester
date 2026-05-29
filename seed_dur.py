"""
seed_dur.py — DUR 구조데이터 수집 → KB 적재 (ingest 글루, 작업지시서 §3.2 / EPIC A-3).

dur_collector.collect_dur()로 식약처 DUR 8종을 수집 → 카테고리별 마크다운 문서로 묶어
기존 kb_ingest.ingest_document()로 KB(kb_documents/kb_chunks)에 적재(청킹+임베딩).

실행:
  DATA_GO_KR_KEY=<인증키> python seed_dur.py                  # 전체 8종 수집·적재
  DATA_GO_KR_KEY=<인증키> python seed_dur.py --category 병용금기 --dry-run
  python seed_dur.py --dry-run --mock                          # 키 없이 글루 점검(샘플)

build_dur_documents()는 순수 함수 — 키/DB/네트워크 없이 로컬 테스트 가능.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List

_SOURCE_ID = "mfds_dur"

# kb_sources 등록용 출처 정의 (FK 제약: kb_documents.source_id → kb_sources.id)
_DUR_SOURCE = {
    "id": _SOURCE_ID,
    "name": "식약처 DUR(의약품 안전사용) 공개 데이터",
    "source_type": "public",
    "license": "kogl_type1",
    "update_frequency": "monthly",
    "is_active": 1,
}


def _register_dur_source() -> None:
    """mfds_dur 출처를 kb_sources에 등록(멱등) + priority_rank=1 보강.

    seed_dur가 ingest_document(source_id='mfds_dur')를 호출하기 전에 반드시
    출처 행이 존재해야 한다(FK kb_documents_source_id_fkey). 다른 시드
    (seed_emergency_kb/seed_faq_kb)와 동일 패턴. priority_rank/jurisdiction/
    institution은 migration 009 이후 컬럼이라 try/except로 가드(로컬 SQLite 보호).
    """
    from kb_ingest import seed_kb_sources
    seed_kb_sources([_DUR_SOURCE])
    try:
        from db import get_conn, _p
        with get_conn() as (conn, cur):
            cur.execute(
                f"UPDATE kb_sources SET priority_rank = 1, jurisdiction = 'KR', "
                f"institution = '식약처' WHERE id = {_p()}",
                (_SOURCE_ID,),
            )
    except Exception as e:
        print(f"[seed_dur] priority_rank 보강 생략(컬럼 미존재 가능): {str(e)[:80]}", flush=True)


# 카테고리 → evidence_topic (검색 주제 매칭용)
_CATEGORY_TOPIC = {
    "병용금기": "drug_interaction",
    "임부금기": "pregnancy_drug_safety",
    "연령금기": "age_drug_safety",
    "용량주의": "drug_dosage",
    "투여기간주의": "drug_duration",
    "노인주의": "elderly_drug_safety",
    "효능군중복": "drug_duplication",
    "서방정분할주의": "drug_administration",
}


def build_dur_documents(chunks: List[Dict]) -> List[Dict]:
    """DUR chunk 리스트 → 카테고리별 ingest 문서 dict 리스트 (순수 함수).

    반환 dict: {title, content_md, source_id, metadata, evidence_topic,
                regulatory_korea, topic_keywords, item_count}
    """
    by_cat: Dict[str, List[Dict]] = {}
    for c in chunks:
        cat = c.get("dur_category", "기타")
        by_cat.setdefault(cat, []).append(c)

    docs: List[Dict] = []
    for cat, items in by_cat.items():
        lines = [f"# 식약처 DUR — {cat}", ""]
        risk_tags, pop_tags, kws = set(), set(), set()
        for it in items:
            lines.append(f"- {it.get('content', '')}")
            for r in it.get("risk_tags", []):
                risk_tags.add(r)
            for p in it.get("population_tags", []):
                pop_tags.add(p)
        content_md = "\n".join(lines)
        docs.append({
            "title": f"식약처 DUR {cat}",
            "content_md": content_md,
            "source_id": _SOURCE_ID,
            "metadata": {
                "chunk_type": "contraindication",
                "evidence_level": "A",
                "source_priority": 1,
                "risk_tags": sorted(risk_tags),
                "population_tags": sorted(pop_tags),
                "jurisdiction": "KR",
                "dur_category": cat,
            },
            "evidence_topic": _CATEGORY_TOPIC.get(cat, "drug_safety"),
            "regulatory_korea": True,
            "topic_keywords": sorted({"DUR", cat, *kws}),
            "item_count": len(items),
        })
    return docs


def seed_dur(service_key: str, categories: List[str] = None,
             rows: int = 100, max_pages: int = 1, dry_run: bool = False) -> Dict:
    """DUR 수집 → 문서 구성 → KB 적재. dry_run이면 적재 없이 요약만."""
    from dur_collector import collect_dur
    chunks = collect_dur(service_key, categories=categories, rows=rows, max_pages=max_pages)
    docs = build_dur_documents(chunks)

    summary = {"collected_chunks": len(chunks), "documents": len(docs),
               "ingested": 0, "per_category": {d["metadata"]["dur_category"]: d["item_count"] for d in docs}}

    if dry_run:
        summary["dry_run"] = True
        return summary

    _register_dur_source()  # FK 선행: kb_sources에 mfds_dur 등록(멱등)

    import kb_ingest
    for d in docs:
        try:
            kb_ingest.ingest_document(
                title=d["title"], content_md=d["content_md"], source_id=d["source_id"],
                metadata=d["metadata"], evidence_country="KR",
                evidence_topic=d["evidence_topic"], regulatory_korea=d["regulatory_korea"],
                topic_keywords=d["topic_keywords"], upsert=True, status="active",
            )
            summary["ingested"] += 1
        except Exception as e:
            print(f"[seed_dur] ingest 실패 {d['title']}: {str(e)[:100]}", flush=True)
    return summary


def _mock_chunks() -> List[Dict]:
    """키 없이 글루 점검용 샘플."""
    return [
        {"dur_category": "병용금기", "content": "[DUR 병용금기] 와파린 + 아스피린: 출혈 위험",
         "risk_tags": ["drug_interaction"], "population_tags": []},
        {"dur_category": "임부금기", "content": "[DUR 임부금기] 이부프로펜: 임신 말기 금기",
         "risk_tags": ["pregnancy_contraindication"], "population_tags": ["pregnancy"]},
    ]


def main():
    ap = argparse.ArgumentParser(description="DUR 수집·KB 적재")
    ap.add_argument("--category", action="append", help="특정 DUR 카테고리만 (반복 지정)")
    ap.add_argument("--rows", type=int, default=100)
    ap.add_argument("--max-pages", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true", help="적재 없이 수집 요약만")
    ap.add_argument("--mock", action="store_true", help="키 없이 샘플 chunk로 글루 점검")
    args = ap.parse_args()

    if args.mock:
        docs = build_dur_documents(_mock_chunks())
        print(f"[seed_dur][mock] documents={len(docs)}")
        for d in docs:
            print(f"  - {d['title']} (items={d['item_count']}, topic={d['evidence_topic']}, "
                  f"pop={d['metadata']['population_tags']})")
        return

    key = os.environ.get("DATA_GO_KR_KEY", "")
    if not key:
        print("[seed_dur] ERROR: DATA_GO_KR_KEY 환경변수 필요 (data.go.kr 15059486 인증키)", flush=True)
        sys.exit(1)

    s = seed_dur(key, categories=args.category, rows=args.rows,
                 max_pages=args.max_pages, dry_run=args.dry_run)
    print(f"[seed_dur] 결과: {s}", flush=True)


if __name__ == "__main__":
    main()

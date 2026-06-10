"""
seed_consultation_kb.py — 42증상 문진 체크리스트 → KB 적재 (문진 근거 강화).

배경 (docs/eval_report_200.md §5-d):
  both_A 81% 도달 후 잔여 미달은 대부분 문진 깊이 부족. consultation_checklists.json의
  증상별 문진 프레임워크(required_questions/red_flags/context_questions/age_specific)는
  지금까지 red_flag 부스팅(점수)에만 쓰였고 KB에 인용 가능한 청크로 없었음.

목적:
  42증상 각각을 '증상별 문진 가이드' 문서로 KB에 적재 → RAG가 검색·인용해
  ④ 문진 질문을 증상별로 완전하게(연령별·가족력·위험신호 포함) 구성하도록 grounding 강화.

실행:
  python seed_consultation_kb.py --dry-run        # 문서 구성만 점검(키/DB 불필요)
  python seed_consultation_kb.py                  # KB 적재 (DATABASE_URL 필요)

build_consultation_documents()는 순수 함수 — 키/DB/네트워크 없이 로컬 테스트 가능.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Dict, List

_DIR = os.path.dirname(os.path.abspath(__file__))
_SOURCE_ID = "consultation_checklist"

# category → evidence_topic (검색 주제 매칭용; 신체계통)
_CATEGORY_TOPIC = {
    "systemic": "consultation_systemic",
    "neuro": "consultation_neuro",
    "ent": "consultation_ent",
    "respiratory": "consultation_respiratory",
    "digestive": "consultation_digestive",
    "cardiovascular": "consultation_cardiovascular",
    "musculoskeletal": "consultation_musculoskeletal",
    "urogenital": "consultation_urogenital",
    "dermatology": "consultation_dermatology",
    "mental": "consultation_mental",
}

_CONSULT_SOURCE = {
    "id": _SOURCE_ID,
    "name": "증상별 문진 가이드 (42증상, 의사 자문 체크리스트)",
    "source_type": "internal",
    "license": "proprietary",
    "update_frequency": "on_demand",
    "is_active": 1,
}

_AGE_LABEL = {"child": "소아", "teen": "청소년", "young": "청년",
              "middle": "중년", "senior": "노년"}


def _labels(items: List[Dict]) -> List[str]:
    out = []
    for it in items or []:
        lab = it.get("label") if isinstance(it, dict) else str(it)
        if lab:
            out.append(lab)
    return out


def build_consultation_documents(checklists: List[Dict]) -> List[Dict]:
    """42증상 체크리스트 → 증상별 ingest 문서 dict 리스트 (순수 함수)."""
    docs: List[Dict] = []
    for s in checklists:
        name = s.get("symptom_name", "")
        if not name:
            continue
        detail = s.get("detail", "")
        dept = s.get("department", "")
        cat = s.get("category", "")
        req = _labels(s.get("required_questions"))
        rf = _labels(s.get("red_flags"))
        ctx = _labels(s.get("context_questions"))
        age = s.get("age_specific") or {}

        lines = [f"# 증상별 문진 가이드 — {name}" + (f" ({detail})" if detail else ""), ""]
        if dept:
            lines.append(f"권장 진료과: {dept}")
            lines.append("")
        if req:
            lines.append("## 증상 정밀화 — 반드시 질문")
            lines += [f"- {x}" for x in req]
            lines.append("")
        if rf:
            lines.append("## 위험 신호 — 응급 선별 질문 (해당 시 즉시 119/응급실 안내)")
            lines += [f"- {x}" for x in rf]
            lines.append("")
        if ctx:
            lines.append("## 환자 맥락 — 질문")
            lines += [f"- {x}" for x in ctx]
            lines.append("")
        if age:
            lines.append("## 연령별 주의 사항")
            for band, info in age.items():
                items = info.get("items") if isinstance(info, dict) else None
                if items:
                    blabel = _AGE_LABEL.get(band, band)
                    lines.append(f"- {blabel}: " + ", ".join(str(i) for i in items))
            lines.append("")
        content_md = "\n".join(lines).strip()

        topic_kws = sorted({name, dept, *(detail.split(",") if detail else []), *rf})
        topic_kws = [k.strip() for k in topic_kws if k and k.strip()]

        docs.append({
            "title": f"증상 문진 가이드 — {name}",
            "content_md": content_md,
            "source_id": _SOURCE_ID,
            "metadata": {
                "chunk_type": "consultation_guide",
                "evidence_level": "B",
                "source_priority": 2,
                "jurisdiction": "KR",
                "symptom_key": s.get("symptom_key", ""),
                "department": dept,
                "risk_tags": rf,
                "population_tags": [_AGE_LABEL.get(b, b) for b in age.keys()],
            },
            "evidence_topic": _CATEGORY_TOPIC.get(cat, "consultation_general"),
            "regulatory_korea": False,
            "topic_keywords": topic_kws,
        })
    return docs


def _register_source() -> None:
    """consultation_checklist 출처를 kb_sources에 등록(멱등) + priority_rank=2 보강."""
    from kb_ingest import seed_kb_sources
    seed_kb_sources([_CONSULT_SOURCE])
    try:
        from db import get_conn, _p
        with get_conn() as (conn, cur):
            cur.execute(
                f"UPDATE kb_sources SET priority_rank = 2, jurisdiction = 'KR', "
                f"institution = '자체(의사 자문)' WHERE id = {_p()}",
                (_SOURCE_ID,),
            )
    except Exception as e:
        print(f"[seed_consult] priority_rank 보강 생략(컬럼 미존재 가능): {str(e)[:80]}", flush=True)


def seed_consultation_kb(dry_run: bool = False) -> Dict:
    """consultation_checklists.json → 문서 구성 → KB 적재 (로더 위임)."""
    import consultation_loader
    checklists = consultation_loader.load_checklists_raw()
    docs = build_consultation_documents(checklists)
    summary = {"symptoms": len(checklists), "documents": len(docs), "ingested": 0}
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
                topic_keywords=d["topic_keywords"], upsert=True, status="active",
            )
            summary["ingested"] += 1
        except Exception as e:
            print(f"[seed_consult] ingest 실패 {d['title']}: {str(e)[:100]}", flush=True)
    return summary


def main():
    ap = argparse.ArgumentParser(description="42증상 문진 체크리스트 → KB 적재")
    ap.add_argument("--dry-run", action="store_true", help="적재 없이 문서 구성 요약만")
    args = ap.parse_args()
    s = seed_consultation_kb(dry_run=args.dry_run)
    print(f"[seed_consult] 결과: {s}", flush=True)


if __name__ == "__main__":
    main()

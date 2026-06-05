"""
KB 청크에 evidence_topic 일괄 백필.
기존 collect_public_kb.py의 label_evidence_topic 로직 재사용.
- 라벨링 대상: evidence_topic IS NULL 또는 = ''
- 배치 처리: 100건씩 commit
- 멱등: 이미 라벨링된 청크는 SKIP
- 비용 추정: 1749청크 × GPT-5-mini ≈ $0.05 미만
"""

import os
import sys
import time
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_conn, _p, _use_postgres

# collect_public_kb.py의 라벨링 함수 재사용
# label_evidence_topic(text: str, title: str = "") -> str
from collect_public_kb import label_evidence_topic, _SYMPTOM_LIST

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("backfill")


def get_missing_chunks(limit=None):
    """evidence_topic 미라벨링 청크 조회."""
    with get_conn() as (conn, cur):
        sql = """
            SELECT c.id, c.content, d.title
            FROM kb_chunks c JOIN kb_documents d ON d.id = c.document_id
            WHERE (c.evidence_topic IS NULL OR c.evidence_topic = '')
              AND d.status = 'active'
            ORDER BY c.id
        """
        if limit:
            sql += f" LIMIT {int(limit)}"
        cur.execute(sql)
        rows = cur.fetchall()

    result = []
    for r in rows:
        if isinstance(r, tuple):
            result.append({"id": r[0], "content": r[1], "title": r[2]})
        else:
            result.append({
                "id": r.get("id"),
                "content": r.get("content"),
                "title": r.get("title"),
            })
    return result


def update_chunk_topic(chunk_id, topic):
    """단일 청크 evidence_topic UPDATE."""
    with get_conn() as (conn, cur):
        cur.execute(
            f"UPDATE kb_chunks SET evidence_topic = {_p()} WHERE id = {_p()}",
            (topic, chunk_id),
        )


def diagnose_evidence_topic():
    """
    evidence_topic 실제 분포를 출력한다.
    백필 대상 0건 보고 시 'general' 폴백 라벨로 가득 찬 케이스를 판별하기 위함.
    DB 직접 수정 없음 — 읽기 전용 진단.
    """
    with get_conn() as (conn, cur):
        cur.execute("SELECT COUNT(*) FROM kb_chunks")
        row = cur.fetchone()
        total_chunks = row[0] if isinstance(row, tuple) else list(row.values())[0]

        cur.execute("SELECT COUNT(*) FROM kb_chunks WHERE evidence_topic IS NULL")
        row = cur.fetchone()
        null_count = row[0] if isinstance(row, tuple) else list(row.values())[0]

        cur.execute("SELECT COUNT(*) FROM kb_chunks WHERE evidence_topic = ''")
        row = cur.fetchone()
        empty_count = row[0] if isinstance(row, tuple) else list(row.values())[0]

        cur.execute(
            "SELECT COUNT(*) FROM kb_chunks c "
            "JOIN kb_documents d ON d.id = c.document_id "
            "WHERE d.status = 'active' AND (c.evidence_topic IS NULL OR c.evidence_topic = '')"
        )
        row = cur.fetchone()
        active_missing = row[0] if isinstance(row, tuple) else list(row.values())[0]

        cur.execute(
            "SELECT evidence_topic, COUNT(*) AS cnt "
            "FROM kb_chunks "
            "GROUP BY evidence_topic "
            "ORDER BY cnt DESC "
            "LIMIT 20"
        )
        dist_rows = cur.fetchall()

    print(f"[Backfill] DB 진단:")
    print(f"  총 청크: {total_chunks}")
    print(f"  evidence_topic NULL: {null_count}")
    print(f"  evidence_topic 빈 문자열: {empty_count}")
    print(f"  활성 문서 미라벨링 청크: {active_missing}")
    print("  evidence_topic 분포 (상위 20):")
    for r in dist_rows:
        if isinstance(r, tuple):
            topic, cnt = r[0], r[1]
        else:
            topic, cnt = r.get("evidence_topic"), r.get("cnt")
        print(f"    {topic!r}: {cnt}")


def main():
    diagnose_evidence_topic()
    chunks = get_missing_chunks()
    total = len(chunks)
    print(f"[Backfill] 미라벨링 청크: {total}건")

    if total == 0:
        print("[Backfill] 백필 대상 없음 — 완료")
        return

    if not _SYMPTOM_LIST:
        print("[Backfill] consultation_checklists.json 로드 실패 — 중단")
        return

    success = 0
    skipped = 0
    failed = 0

    for i, chunk in enumerate(chunks, 1):
        try:
            title = chunk.get("title") or ""
            content = chunk.get("content") or ""
            # label_evidence_topic(text, title): text는 본문, title은 제목
            # 본문을 최대 2000자로 제한 (GPT 토큰 절약)
            text = content[:2000]

            topic = label_evidence_topic(text, title=title)

            if not topic:
                skipped += 1
                continue

            update_chunk_topic(chunk["id"], topic)
            success += 1

            if i % 50 == 0:
                print(
                    f"  진행: {i}/{total} "
                    f"(success={success}, skipped={skipped}, failed={failed})"
                )

            time.sleep(0.1)  # rate limit 완화

        except Exception:
            failed += 1
            logger.exception("청크 %s 라벨링 실패", chunk["id"])
            if failed > 50:
                print("[Backfill] 50건 이상 실패 — 중단")
                break

    print(
        f"\n[Backfill] 완료: success={success}, skipped={skipped}, failed={failed}"
    )

    # 잔여 미라벨링 검증
    with get_conn() as (conn, cur):
        cur.execute(
            "SELECT COUNT(*) FROM kb_chunks WHERE evidence_topic IS NULL OR evidence_topic = ''"
        )
        row = cur.fetchone()
        remaining = row[0] if isinstance(row, tuple) else list(row.values())[0]
    print(f"[Backfill] 잔여 미라벨링 청크: {remaining}")


if __name__ == "__main__":
    main()

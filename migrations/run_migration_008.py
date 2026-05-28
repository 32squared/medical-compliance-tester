"""
run_migration_008.py — kb_chunks.evidence_topic 수동 매핑 보정

목적:
  validate-rag-direct 검증에서 no_topic_match가 지배적이었던 원인 해소.
  KB 문서 title ILIKE 패턴으로 evidence_topic이 'general'/NULL/'' 인
  청크에 주제 라벨을 강제 부여.

멱등성:
  UPDATE는 WHERE 조건 기반 → 재실행 시 이미 매핑된 행은 변경 없음.

DB 모드:
  PostgreSQL 전용 (Cloud SQL)
  DATABASE_URL 환경변수 또는 DB_PASSWORD + DB_HOST 필요

사용법:
  python migrations/run_migration_008.py
"""

import os
import sys
import argparse
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

MIGRATIONS_DIR = Path(__file__).resolve().parent
SQL_PG = MIGRATIONS_DIR / "008_evidence_topic_remap.sql"

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Secret Manager 분리 주입 지원
if not DATABASE_URL:
    _pw   = os.environ.get("DB_PASSWORD", "")
    _user = os.environ.get("DB_USER", "app_user")
    _name = os.environ.get("DB_NAME", "medical_app")
    _host = os.environ.get("DB_HOST", "")
    if _pw and _host:
        import urllib.parse
        DATABASE_URL = (
            f"postgresql://{_user}:{urllib.parse.quote(_pw, safe='')}@/{_name}"
            f"?host={_host}"
        )

# 매핑 대상 토픽 목록 (검증용)
_TOPICS = [
    'cardiac_arrest', 'aed_usage', 'emergency_signs',
    'fever', 'cough', 'diabetes', 'dyspnea', 'headache', 'hypertension',
]


def _split_statements(sql_text: str) -> list:
    """
    SQL 텍스트를 세미콜론 기준으로 분리하되,
    $$ ... $$ 달러 쿼팅 블록 내의 세미콜론은 무시한다.
    """
    import re as _re
    out = []
    # 상태: dollar_tag 가 None 이면 바깥, str 이면 해당 $tag$ 안쪽
    dollar_tag: str | None = None
    buf: list[str] = []
    i = 0
    text = sql_text

    while i < len(text):
        # 달러 쿼팅 시작/종료 감지: $[tag]$ 패턴
        m = _re.match(r'\$([A-Za-z0-9_]*)\$', text[i:])
        if m:
            tag = m.group(0)   # e.g. '$$' or '$body$'
            if dollar_tag is None:
                # 달러 쿼팅 시작
                dollar_tag = tag
                buf.append(tag)
                i += len(tag)
                continue
            elif dollar_tag == tag:
                # 달러 쿼팅 종료
                buf.append(tag)
                i += len(tag)
                dollar_tag = None
                continue

        ch = text[i]
        if ch == ';' and dollar_tag is None:
            # statement 경계
            s = ''.join(buf).strip()
            buf = []
            i += 1
            if not s:
                continue
            lines = [l for l in s.splitlines()
                     if l.strip() and not l.strip().startswith("--")]
            if not lines:
                continue
            upper = s.upper().strip()
            if upper in ("BEGIN", "COMMIT", "ROLLBACK"):
                continue
            out.append(s)
        else:
            buf.append(ch)
            i += 1

    # 나머지 처리
    s = ''.join(buf).strip()
    if s:
        lines = [l for l in s.splitlines()
                 if l.strip() and not l.strip().startswith("--")]
        if lines:
            upper = s.upper().strip()
            if upper not in ("BEGIN", "COMMIT", "ROLLBACK"):
                out.append(s)

    return out


def _snapshot(cur, label: str) -> dict:
    """evidence_topic 별 건수 스냅샷."""
    cur.execute(
        "SELECT evidence_topic, COUNT(*) AS cnt FROM kb_chunks GROUP BY evidence_topic ORDER BY cnt DESC LIMIT 20"
    )
    rows = cur.fetchall()
    snapshot = {}
    for row in rows:
        topic = row[0] if isinstance(row, tuple) else row['evidence_topic']
        cnt   = row[1] if isinstance(row, tuple) else row['cnt']
        snapshot[topic] = cnt
    print(f"\n[008] {label} evidence_topic 분포 (상위 20):")
    for t, c in snapshot.items():
        print(f"  {t!r}: {c}")
    return snapshot


def run_postgres(database_url: str) -> None:
    try:
        import psycopg2
    except ImportError:
        print("[ERROR] psycopg2 미설치", file=sys.stderr)
        sys.exit(1)

    sql_text = SQL_PG.read_text(encoding="utf-8")
    stmts = _split_statements(sql_text)
    print(f"[008] SQL 파일: {SQL_PG.name}  ({len(stmts)}개 statement)")

    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # 사전 스냅샷
        _snapshot(cur, "사전")

        # UPDATE 실행
        print(f"\n[008] UPDATE 실행 중...")
        updated_total = 0
        for i, stmt in enumerate(stmts, 1):
            first = stmt.splitlines()[0][:80]
            cur.execute(stmt)
            if cur.rowcount and cur.rowcount > 0:
                updated_total += cur.rowcount
                print(f"  [{i:03d}] 영향 행수={cur.rowcount}  {first[:60]}...")

        conn.commit()
        print(f"\n[008] COMMIT 완료 — 총 영향 행수: {updated_total}")

        # 사후 스냅샷 + 토픽별 검증
        _snapshot(cur, "사후")
        _verify_topics(cur)

    except Exception:
        conn.rollback()
        print("[008] 실패 — ROLLBACK", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def _verify_topics(cur) -> None:
    """매핑 대상 토픽별 건수 확인."""
    print("\n[008] 매핑 토픽별 청크 수:")
    for topic in _TOPICS:
        cur.execute(
            "SELECT COUNT(*) FROM kb_chunks WHERE evidence_topic = %s",
            (topic,)
        )
        n = cur.fetchone()[0]
        status = "OK" if n > 0 else "WARN(0)"
        print(f"  {topic}: {n}  [{status}]")

    cur.execute(
        "SELECT COUNT(*) FROM kb_chunks WHERE evidence_topic = 'general'"
    )
    remaining_general = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM kb_chunks WHERE evidence_topic IS NULL OR evidence_topic = ''"
    )
    remaining_null = cur.fetchone()[0]
    print(f"\n  잔여 general: {remaining_general}")
    print(f"  잔여 null/empty: {remaining_null}")
    if remaining_general + remaining_null > 0:
        print("  [INFO] title 패턴 미매핑 청크 잔존 — 추가 패턴 보완 검토 필요")


def main():
    parser = argparse.ArgumentParser(
        description="마이그레이션 008 — kb_chunks evidence_topic 수동 매핑 보정"
    )
    parser.add_argument("--database-url", default="",
                        help="PostgreSQL DSN (생략 시 환경변수 DATABASE_URL 사용)")
    args = parser.parse_args()

    db_url = args.database_url or DATABASE_URL

    print("=" * 60)
    print("  마이그레이션 008 — evidence_topic 매핑 보정")
    print("=" * 60)

    if not db_url:
        print("[ERROR] DATABASE_URL 또는 DB_PASSWORD+DB_HOST 환경변수가 필요합니다.", file=sys.stderr)
        print("        이 마이그레이션은 PostgreSQL 전용입니다.", file=sys.stderr)
        sys.exit(1)

    print("[MODE] PostgreSQL")
    run_postgres(db_url)

    print("=" * 60)
    print("  마이그레이션 008 완료")
    print("=" * 60)


if __name__ == "__main__":
    main()

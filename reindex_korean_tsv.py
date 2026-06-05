"""
reindex_korean_tsv.py — 한국어 어절 어근 분리 후 content_tsv 재생성 (PostgreSQL 전용)

목적:
  to_tsvector('simple', content) 에서 "기침이" 토큰이 "기침" 쿼리와 매칭되지 않는 문제 해소.
  Python에서 content를 전처리(어절 → 어절+어근 토큰 추가)하여 enhanced 텍스트를 만든 뒤
  to_tsvector('simple', enhanced) 로 저장.

한계:
  - 룰 기반 조사 제거 (정규식)이므로 형태소 분석기(KoNLPy 등) 대비 정확도 낮음
  - pgroonga 기반 N-gram 검색은 별도 인프라 작업 필요 (여기서는 제외)
  - 2글자 어근은 여전히 애매할 수 있음 (예: "이라" → "이" 제거 후 "라" 남음)

사용법:
  python reindex_korean_tsv.py [--batch-size 200]

환경변수:
  DATABASE_URL 또는 DB_PASSWORD + DB_HOST 필수 (PostgreSQL 전용)
"""

import os
import re
import sys
import argparse
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

# ── 한국어 조사/어미 패턴 (자주 출현하는 1~2자 후치사) ───────────────────────
# 어절 마지막 1~2글자가 이 패턴이면 제거하여 어근 근사값 생성
_JOSA_1 = re.compile(
    r'(이|가|을|를|은|는|에|의|로|와|과|나|도|만|서|게|고|며|면|면서|지|랑|야|아|여|요|죠|죠|네|니|자|자|네|군|구나)$'
)
_JOSA_2 = re.compile(
    r'(에서|부터|까지|으로|이나|이라|이며|이고|에게|한테|보다|처럼|같이|마저|조차|이든|이도|이서|이게|이면)$'
)

# 최소 어근 길이: 1글자 어근은 검색 노이즈 유발 → 2글자 이상만 추가
_MIN_ROOT_LEN = 2


def extract_root(word: str) -> str | None:
    """
    한글 어절에서 조사/어미를 제거한 어근 근사값 반환.
    제거 후 길이가 MIN_ROOT_LEN 미만이면 None 반환.
    """
    if not re.search(r'[가-힣]', word):
        return None

    # 2글자 후치사 먼저 시도 (더 구체적)
    m2 = _JOSA_2.search(word)
    if m2:
        root = word[: m2.start()]
        if len(root) >= _MIN_ROOT_LEN:
            return root

    # 1글자 후치사
    m1 = _JOSA_1.search(word)
    if m1:
        root = word[: m1.start()]
        if len(root) >= _MIN_ROOT_LEN:
            return root

    return None


def preprocess_content(content: str) -> str:
    """
    content 텍스트에서 한국어 어절 토큰을 추출하고,
    각 어절에 대해 어근 근사값(조사 제거)을 추가한 강화 텍스트 반환.

    예: "기침이 심합니다" → "기침이 심합니다 기침 심합"
    반환값: content + ' ' + 어근_토큰들 (원본 + 어근 중복 포함)
    """
    # 한글 어절(2자 이상) 추출
    tokens = re.findall(r'[가-힣]{2,}', content)
    roots = []
    for tok in tokens:
        root = extract_root(tok)
        if root and root != tok:
            roots.append(root)

    if not roots:
        return content

    # 중복 제거 (순서 유지)
    seen = set()
    unique_roots = []
    for r in roots:
        if r not in seen:
            seen.add(r)
            unique_roots.append(r)

    return content + ' ' + ' '.join(unique_roots)


def run(database_url: str, batch_size: int) -> None:
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError:
        print("[ERROR] psycopg2 미설치", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=RealDictCursor)

    try:
        # ── 전체 건수 확인 ──────────────────────────────────────────────────
        cur.execute("SELECT COUNT(*) AS cnt FROM kb_chunks WHERE content IS NOT NULL")
        total = cur.fetchone()['cnt']
        print(f"[reindex] 처리 대상: {total}개 청크 (batch_size={batch_size})")

        # ── 사전 키워드 hits ─────────────────────────────────────────────────
        keywords_before = _check_keywords(cur)
        print(f"[reindex] 사전 키워드 hits: {keywords_before}")

        # ── 배치 처리 ────────────────────────────────────────────────────────
        offset = 0
        success = 0
        while offset < total:
            cur.execute(
                "SELECT id, content FROM kb_chunks WHERE content IS NOT NULL ORDER BY id LIMIT %s OFFSET %s",
                (batch_size, offset)
            )
            rows = cur.fetchall()
            if not rows:
                break

            batch_params = []
            for row in rows:
                chunk_id = row['id']
                content = row['content']
                enhanced = preprocess_content(content)
                batch_params.append((enhanced, chunk_id))

            # 배치 executemany
            cur.executemany(
                "UPDATE kb_chunks SET content_tsv = to_tsvector('simple', %s) WHERE id = %s",
                batch_params
            )
            conn.commit()

            success += len(rows)
            offset += batch_size
            print(f"  진행: {success}/{total}")

        print(f"[reindex] UPDATE 완료: {success}/{total}개")

        # ── 사후 키워드 hits ─────────────────────────────────────────────────
        keywords_after = _check_keywords(cur)
        print(f"[reindex] 사후 키워드 hits: {keywords_after}")

        # 개선 요약
        for kw in keywords_after:
            before = keywords_before.get(kw, 0)
            after = keywords_after[kw]
            delta = after - before
            sign = '+' if delta >= 0 else ''
            print(f"  '{kw}': {before} → {after} ({sign}{delta})")

    except Exception:
        conn.rollback()
        print("[reindex] 실패 — ROLLBACK", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def _check_keywords(cur) -> dict:
    keywords = ['기침', '심정지', '발열', '당뇨', '응급실', 'AED', '호흡곤란']
    result = {}
    for kw in keywords:
        cur.execute(
            "SELECT COUNT(*) AS cnt FROM kb_chunks WHERE content_tsv @@ plainto_tsquery('simple', %s)",
            (kw,)
        )
        result[kw] = cur.fetchone()['cnt']
    return result


def main():
    parser = argparse.ArgumentParser(
        description="한국어 어절 어근 분리 후 content_tsv 재생성 (PostgreSQL 전용)"
    )
    parser.add_argument("--batch-size", type=int, default=200,
                        help="한 번에 처리할 청크 수 (기본 200)")
    parser.add_argument("--database-url", default="",
                        help="PostgreSQL DSN (생략 시 환경변수 DATABASE_URL 사용)")
    args = parser.parse_args()

    # DATABASE_URL 결정
    database_url = args.database_url or os.environ.get("DATABASE_URL", "")
    if not database_url:
        _pw   = os.environ.get("DB_PASSWORD", "")
        _user = os.environ.get("DB_USER", "app_user")
        _name = os.environ.get("DB_NAME", "medical_app")
        _host = os.environ.get("DB_HOST", "")
        if _pw and _host:
            import urllib.parse
            database_url = (
                f"postgresql://{_user}:{urllib.parse.quote(_pw, safe='')}@/{_name}"
                f"?host={_host}"
            )

    if not database_url:
        print("[ERROR] DATABASE_URL 또는 DB_PASSWORD+DB_HOST 환경변수가 필요합니다.", file=sys.stderr)
        print("        SQLite는 tsvector를 지원하지 않으므로 PostgreSQL 전용입니다.", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("  reindex_korean_tsv — 한국어 content_tsv 재생성")
    print("=" * 60)
    run(database_url, args.batch_size)
    print("=" * 60)
    print("  완료")
    print("=" * 60)


if __name__ == "__main__":
    main()

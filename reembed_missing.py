"""
embedding_primary가 NULL인 kb_chunks 청크를 일괄 재임베딩.

사용법:
  python reembed_missing.py              # 기본 배치 100건씩
  python reembed_missing.py --batch 50   # 배치 크기 조정
  python reembed_missing.py --dry-run    # SELECT만 (실제 UPDATE 없음)

특징:
  - 멱등성: embedding_primary IS NULL인 청크만 처리 (이미 임베딩된 청크 SKIP)
  - PostgreSQL / SQLite 듀얼 모드 호환 (_use_postgres 분기)
  - OpenAI 배치 임베딩 (text-embedding-3-small, 최대 100건/요청)
  - 429/5xx 지수 백오프 재시도 (embedding_provider.py 내장)
  - 진행률 Cloud Logging (stdout) 로깅
"""

import os
import sys
import json
import time
import logging
import argparse

# 프로젝트 루트를 sys.path에 추가
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# Cloud Run 환경에서 한글 출력 보장
import io
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)
logger = logging.getLogger(__name__)


def _pg_vector_literal(vec: list) -> str:
    """pgvector UPDATE용 벡터 리터럴 문자열 생성."""
    return "[" + ",".join(f"{v:.8f}" for v in vec) + "]"


def fetch_missing_ids(cur, batch_size: int, _use_postgres: bool) -> list:
    """embedding_primary IS NULL인 청크 id, content 조회."""
    if _use_postgres:
        cur.execute(
            "SELECT id, content FROM kb_chunks "
            "WHERE embedding_primary IS NULL "
            "ORDER BY id "
            "LIMIT %s",
            (batch_size,),
        )
    else:
        cur.execute(
            "SELECT id, content FROM kb_chunks "
            "WHERE embedding_primary IS NULL "
            "ORDER BY id "
            "LIMIT ?",
            (batch_size,),
        )
    rows = cur.fetchall()
    # RealDictCursor(pg) 또는 sqlite3.Row 모두 dict-like 접근 가능
    return [{"id": row["id"], "content": row["content"]} for row in rows]


def update_embeddings(conn, cur, rows: list, vectors: list, _use_postgres: bool):
    """배치 UPDATE. rows[i] 에 vectors[i] 저장."""
    for row, vec in zip(rows, vectors):
        if _use_postgres:
            # pgvector 컬럼: ::vector 캐스팅
            cur.execute(
                "UPDATE kb_chunks SET embedding_primary = %s::vector WHERE id = %s",
                (_pg_vector_literal(vec), row["id"]),
            )
        else:
            # SQLite: JSON 배열 문자열로 저장 (로컬 개발용)
            cur.execute(
                "UPDATE kb_chunks SET embedding_primary = ? WHERE id = ?",
                (json.dumps(vec), row["id"]),
            )
    conn.commit()


def count_missing(cur, _use_postgres: bool) -> int:
    """현재 NULL 건수 반환."""
    cur.execute("SELECT COUNT(*) FROM kb_chunks WHERE embedding_primary IS NULL")
    row = cur.fetchone()
    # RealDictCursor: dict, sqlite3.Row: positional
    if isinstance(row, dict):
        return list(row.values())[0]
    return row[0]


def count_total(cur) -> int:
    """전체 청크 건수 반환."""
    cur.execute("SELECT COUNT(*) FROM kb_chunks")
    row = cur.fetchone()
    if isinstance(row, dict):
        return list(row.values())[0]
    return row[0]


def reembed_all_missing(batch_size: int = 100, dry_run: bool = False):
    """
    메인 재임베딩 루프.

    Args:
        batch_size: 1회 OpenAI API 호출당 처리 청크 수 (기본 100)
        dry_run: True이면 SELECT만 수행, UPDATE 없음
    """
    # DB 모듈 임포트 (init_db 호출해야 _use_postgres 플래그 설정됨)
    from db import get_conn, _use_postgres as _up_initial, init_db
    init_db()  # _use_postgres 플래그 + 커넥션 풀 초기화

    # init_db() 이후 재import로 최신 플래그 반영
    import db as _db
    _use_postgres = _db._use_postgres

    logger.info("=== reembed_missing 시작 (dry_run=%s, batch_size=%d) ===", dry_run, batch_size)
    logger.info("DB 모드: %s", "PostgreSQL" if _use_postgres else "SQLite")

    # 임베딩 프로바이더 초기화 (OPENAI_API_KEY 미설정 시 즉시 에러)
    from embedding_provider import get_embedding_provider
    provider = get_embedding_provider(slot="default")
    logger.info("임베딩 모델: %s (%d차원)", provider.model_id, provider.dimension)

    # 헬스체크
    hc = provider.health_check()
    if not hc.get("ok"):
        logger.error("임베딩 프로바이더 헬스체크 실패: %s", hc)
        sys.exit(1)
    logger.info("임베딩 헬스체크 OK (latency=%dms, dim=%d)", hc["latency_ms"], hc["sample_dim"])

    total_processed = 0
    total_failed = 0
    batch_num = 0
    t_start = time.time()

    with get_conn() as (conn, cur):
        initial_missing = count_missing(cur, _use_postgres)
        total_chunks = count_total(cur)
        logger.info(
            "초기 상태: 전체=%d, 임베딩 완료=%d, 누락=%d",
            total_chunks,
            total_chunks - initial_missing,
            initial_missing,
        )

        if initial_missing == 0:
            logger.info("누락 청크 없음 — 작업 불필요.")
            return

        if dry_run:
            logger.info("[DRY-RUN] UPDATE 없이 종료.")
            return

    # 배치 루프 (get_conn은 각 배치마다 새 트랜잭션)
    while True:
        with get_conn() as (conn, cur):
            rows = fetch_missing_ids(cur, batch_size, _use_postgres)

        if not rows:
            logger.info("모든 누락 청크 처리 완료.")
            break

        batch_num += 1
        texts = [r["content"] for r in rows]
        ids = [r["id"] for r in rows]

        logger.info(
            "[배치 %d] %d건 임베딩 요청 (id 범위: %s ~ %s)",
            batch_num,
            len(rows),
            ids[0],
            ids[-1],
        )

        try:
            t0 = time.time()
            vectors = provider.embed(texts)
            elapsed = time.time() - t0
            logger.info(
                "[배치 %d] 임베딩 완료 (%.1fs, %.1f건/초)",
                batch_num,
                elapsed,
                len(rows) / elapsed if elapsed > 0 else 0,
            )
        except Exception as e:
            logger.error("[배치 %d] 임베딩 실패: %s", batch_num, e)
            total_failed += len(rows)
            # 실패한 배치는 SKIP하고 계속 (무한루프 방지를 위해 중단)
            logger.error("임베딩 API 오류로 작업 중단. 재실행 시 자동 재시도됩니다.")
            break

        # UPDATE
        try:
            with get_conn() as (conn, cur):
                update_embeddings(conn, cur, rows, vectors, _use_postgres)
            total_processed += len(rows)
            logger.info(
                "[배치 %d] DB 업데이트 완료 — 누적 처리: %d건",
                batch_num,
                total_processed,
            )
        except Exception as e:
            logger.error("[배치 %d] DB 업데이트 실패: %s", batch_num, e)
            total_failed += len(rows)
            break

    # 최종 검증
    with get_conn() as (conn, cur):
        final_missing = count_missing(cur, _use_postgres)
        total_chunks = count_total(cur)
        embedded = total_chunks - final_missing

    elapsed_total = time.time() - t_start
    logger.info("=== 재임베딩 완료 ===")
    logger.info(
        "처리: %d건 성공 / %d건 실패 / 소요: %.1f초",
        total_processed,
        total_failed,
        elapsed_total,
    )
    logger.info(
        "최종 상태: 전체=%d, 임베딩 완료=%d, 누락=%d",
        total_chunks,
        embedded,
        final_missing,
    )

    if final_missing > 0:
        logger.warning(
            "여전히 %d건 누락. 재실행하거나 로그를 확인하세요.", final_missing
        )
        sys.exit(2)
    else:
        logger.info("모든 청크 임베딩 완료 — RAG 검색 품질 정상화.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NULL 임베딩 청크 재임베딩")
    parser.add_argument(
        "--batch",
        type=int,
        default=100,
        help="배치 크기 (기본 100, OpenAI API 권장 상한)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="SELECT만 수행 (실제 UPDATE 없음)",
    )
    args = parser.parse_args()
    reembed_all_missing(batch_size=args.batch, dry_run=args.dry_run)

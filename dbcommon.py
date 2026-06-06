"""
dbcommon.py — DB 연결 레이어 (PG/SQLite 듀얼 모드 원시함수)
============================================================
db.py 의 '호스트 CRUD/스키마' 와 분리된 **연결 기반 레이어**.
호스트(db.py)와 RAG(rag_db/rag_engine 등)가 공유한다.

설계 (저장소 분리 Phase 2):
- 모드(_use_postgres)는 **import 시점**에 DATABASE_URL 유무로 확정 (init_db 비의존).
  → db.py 가 이 심볼을 재export 해도 stale 복사 문제가 없다(import 후 불변).
- PG 풀(_pg_pool)은 **첫 get_conn 에서 lazy 생성**(_ensure_pool). 연결 생명주기를
  스키마 초기화(init_db)에서 분리.
- db.py 는 이 모듈을 import 해 기존 API(`from db import get_conn, _p, ...`)를
  그대로 재export(파사드) → 기존 ~30개 호출처 무변경.

향후(Phase 4): 이 파일을 공유 패키지로 떼어 RAG 저장소가 의존하게 한다.
"""

import os
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

# PostgreSQL support (optional)
try:
    import psycopg2  # noqa: F401
    from psycopg2 import pool as pg_pool
    from psycopg2.extras import RealDictCursor
    HAS_POSTGRES = True
except ImportError:
    HAS_POSTGRES = False

# ── 경로/접속 설정 ──
DB_PATH = os.environ.get('DB_PATH', os.path.join(os.path.dirname(__file__), 'app.db'))
DATABASE_URL = os.environ.get('DATABASE_URL', '')

# Secret Manager 분리 주입 지원:
# DB_PASSWORD(Secret) + DB_USER + DB_NAME + DB_HOST → DATABASE_URL 자동 조합
if not DATABASE_URL:
    _pw   = os.environ.get('DB_PASSWORD', '')
    _user = os.environ.get('DB_USER', 'app_user')
    _name = os.environ.get('DB_NAME', 'medical_app')
    _host = os.environ.get('DB_HOST', '')
    if _pw and _host:
        import urllib.parse as _urlparse
        DATABASE_URL = (
            f"postgresql://{_user}:{_urlparse.quote(_pw, safe='')}@/{_name}"
            f"?host={_host}"
        )

# 모드: import 시점 확정 (init_db 와 무관 — 재export 안전)
_use_postgres = bool(DATABASE_URL and HAS_POSTGRES)
_pg_pool = None  # PostgreSQL connection pool (lazy)


def _ensure_pool():
    """PG 풀 lazy 생성 (멱등). PG 모드가 아니면 None."""
    global _pg_pool
    if _use_postgres and _pg_pool is None:
        _pg_pool = pg_pool.SimpleConnectionPool(1, 10, DATABASE_URL)
    return _pg_pool


# ════════════════════════════════════════
#  SQL 헬퍼 (SQLite vs PostgreSQL 차이 흡수)
# ════════════════════════════════════════

def _now():
    return datetime.now(timezone.utc).isoformat()


def _ph(*args):
    """Placeholder: ? (SQLite) vs %s (PostgreSQL). _ph(n) returns n comma-separated placeholders."""
    n = args[0] if args else 1
    return ','.join(['%s'] * n) if _use_postgres else ','.join(['?'] * n)


def _p(n=1):
    """Single placeholder string."""
    return '%s' if _use_postgres else '?'


def _upsert(table, key_col, key_val, columns, values):
    """INSERT ... ON CONFLICT UPDATE helper. Returns (sql, params)."""
    ph = _p()
    col_list = ', '.join(columns)
    ph_list = ', '.join([ph] * len(columns))
    if _use_postgres:
        update_parts = ', '.join(f"{c} = EXCLUDED.{c}" for c in columns if c != key_col)
        sql = f"INSERT INTO {table} ({col_list}) VALUES ({ph_list}) ON CONFLICT ({key_col}) DO UPDATE SET {update_parts}"
    else:
        sql = f"INSERT OR REPLACE INTO {table} ({col_list}) VALUES ({ph_list})"
    return sql, values


def _row_to_dict(row):
    """sqlite3.Row 또는 RealDictCursor dict -> dict 변환"""
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)  # RealDictCursor already returns dict-like
    return dict(row)


def _pg_json_loads(val):
    """PostgreSQL JSONB returns Python objects directly; SQLite stores as TEXT strings."""
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val  # already parsed by psycopg2
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return None


def _pg_json_loads_or(val, default):
    """Like _pg_json_loads but with a default."""
    result = _pg_json_loads(val)
    return result if result is not None else default


@contextmanager
def get_conn(db_path=None):
    """듀얼 모드 커넥션 컨텍스트 매니저. yields (conn, cur)."""
    if _use_postgres:
        pool = _ensure_pool()
        conn = pool.getconn()
        try:
            conn.autocommit = False
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            yield conn, cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            pool.putconn(conn)
    else:
        path = db_path or DB_PATH
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=10000")
        cursor = conn.cursor()
        try:
            yield conn, cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()
            conn.close()

"""
packages/medical_shared/dbcommon — DB connection layer (PG/SQLite dual mode).

This is the canonical implementation moved here from the root dbcommon.py (4-B/B1).
The root dbcommon.py is kept as a shim that registers this module under the
'dbcommon' name in sys.modules so that runtime attribute patching
(e.g. tests that do `import dbcommon; dbcommon.DB_PATH = ...`) works correctly.

DB_PATH default:
  When this module lived at the root, __file__ pointed to the root directory.
  Now it lives three levels deep (packages/medical_shared/dbcommon/__init__.py).
  We walk up three levels to recover the project root so that the default DB
  path remains <project-root>/app.db.
  NOTE: revisit when packaging as a pip wheel (4-E): at that point __file__ will
  be inside the site-packages tree and a different strategy is needed.
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

# ── path / connection settings ──
# Walk up 3 levels: dbcommon/ -> medical_shared/ -> packages/ -> project root
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))          # packages/medical_shared/dbcommon
_MEDICAL_SHARED_DIR = os.path.dirname(_PKG_DIR)                 # packages/medical_shared
_PACKAGES_DIR = os.path.dirname(_MEDICAL_SHARED_DIR)            # packages
_PROJECT_ROOT = os.path.dirname(_PACKAGES_DIR)                  # project root
# 4-E 패키징 시 재검토: pip wheel 설치 후에는 _PROJECT_ROOT 가 site-packages 경로가 됨.
DB_PATH = os.environ.get('DB_PATH', os.path.join(_PROJECT_ROOT, 'app.db'))
DATABASE_URL = os.environ.get('DATABASE_URL', '')

# Secret Manager separate injection support:
# DB_PASSWORD(Secret) + DB_USER + DB_NAME + DB_HOST -> DATABASE_URL auto-compose
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

# Mode: fixed at import time (independent of init_db — safe for re-export)
_use_postgres = bool(DATABASE_URL and HAS_POSTGRES)
_pg_pool = None  # PostgreSQL connection pool (lazy)


def _ensure_pool():
    """PG pool lazy creation (idempotent). Returns None in SQLite mode."""
    global _pg_pool
    if _use_postgres and _pg_pool is None:
        _pg_pool = pg_pool.SimpleConnectionPool(1, 10, DATABASE_URL)
    return _pg_pool


# ════════════════════════════════════════
#  SQL helpers (SQLite vs PostgreSQL differences)
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
    """sqlite3.Row or RealDictCursor dict -> dict conversion."""
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
    """Dual-mode connection context manager. yields (conn, cur)."""
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

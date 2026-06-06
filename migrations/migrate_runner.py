"""
migrate_runner.py — 통합 스키마 마이그레이션 러너 (additive, 기존 동작 불변)
============================================================================
schema_migrations 추적 테이블을 두고 migrations/*.sql 을 순서대로 멱등 적용한다.
기존 db.py init_db() 와 run_migration_NNN.py 동작을 전혀 바꾸지 않는다(병행 가능).

■ 왜 필요한가
  - 현재 RAG 테이블은 db.py init_db() 인라인 DDL 이 매 부팅 시 생성하고,
    migrations/*.sql 은 어떤 러너도 안 읽는 '죽은 문서' 였다.
  - 002~009 는 run_migration_NNN.py 일회용 스크립트로 수동 적용돼 추적 테이블이 없었다.
  - 이 러너가 schema_migrations 로 적용 이력을 추적하면, 향후 RAG DDL 을
    db.py 에서 안전하게 떼어 migrations/ 로 옮기고 저장소를 분리할 토대가 된다.

■ DB 모드 (자동 감지)
  DATABASE_URL 있음 → PostgreSQL : '{version}.sql' 적용
  DATABASE_URL 없음 → SQLite     : '{version}_sqlite.sql' 우선, 없으면 PG 전용으로 간주해 skip

■ 버전 규칙
  파일명 'NNN_name.sql'(PG) / 'NNN_name_sqlite.sql'(SQLite) 에서
  version = 'NNN_name' (zero-padded 숫자 접두라 문자열 정렬로 순서 보장)

■ 명령
  --status              적용/대기 목록 출력
  --baseline            현재 존재하는 모든 마이그레이션을 '실행 없이' 적용표시
                        (이미 init_db/수동스크립트로 HEAD 상태인 기존 DB 채택용)
  --baseline-through V  지정 version 까지만 baseline
  --apply               대기(미적용) 마이그레이션을 순서대로 실행·기록
  --db-path PATH        SQLite 경로 (기본 app.db)
  --database-url URL    PG URL (기본 $DATABASE_URL)

■ 권장 도입 절차
  기존 DB(dev/prod):  python migrations/migrate_runner.py --baseline   (001~009 채택, 무실행)
  새 마이그레이션 이후: python migrations/migrate_runner.py --apply      (010+ 만 실제 적용)

■ 한계(주의)
  - PG dollar-quoted 함수($$...$$) 본문에 세미콜론이 있으면 _split_statements 가 분리하지
    못한다. 그런 마이그레이션은 단일 statement 로 작성하거나 별도 스크립트로 적용하라.
  - startup(entrypoint) 자동 적용은 아직 연결하지 않았다(additive). 검증 후 다음 단계에서 연결.
"""

import os
import sys
import sqlite3
import argparse
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent
REPO_ROOT = MIGRATIONS_DIR.parent


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _split_statements(sql_text: str) -> list:
    """SQL 텍스트를 개별 statement 리스트로 분리.
    주석만/빈 fragment 와 BEGIN/COMMIT/ROLLBACK 은 제거(트랜잭션은 러너가 제어)."""
    statements = []
    for raw in sql_text.split(";"):
        stmt = raw.strip()
        if not stmt:
            continue
        lines = [l for l in stmt.splitlines() if l.strip() and not l.strip().startswith("--")]
        if not lines:
            continue
        if stmt.upper().strip() in ("BEGIN", "COMMIT", "ROLLBACK"):
            continue
        statements.append(stmt)
    return statements


def discover_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> list:
    """migrations_dir 의 *.sql 을 version 별로 묶어 정렬 반환.
    반환: [{version, pg_file(Path|None), sqlite_file(Path|None)}, ...] (version 오름차순)
    """
    by_version = {}
    for p in sorted(Path(migrations_dir).glob("*.sql")):
        stem = p.name[:-4]  # ".sql" 제거
        if stem.endswith("_sqlite"):
            version = stem[: -len("_sqlite")]
            by_version.setdefault(version, {})["sqlite_file"] = p
        else:
            version = stem
            by_version.setdefault(version, {})["pg_file"] = p
    out = []
    for version in sorted(by_version.keys()):
        entry = by_version[version]
        out.append({
            "version": version,
            "pg_file": entry.get("pg_file"),
            "sqlite_file": entry.get("sqlite_file"),
        })
    return out


def _select_file(entry: dict, mode: str):
    """백엔드에 맞는 적용 파일 선택. (file_path|None, note)"""
    if mode == "postgres":
        return entry["pg_file"], None
    # sqlite
    if entry["sqlite_file"]:
        return entry["sqlite_file"], None
    if entry["pg_file"]:
        # SQLite 변종이 없는 PG 전용 마이그레이션 → SQLite 모드에선 skip
        return None, "pg-only"
    return None, "no-file"


# ──────────────────────────────────────────────
#  백엔드
# ──────────────────────────────────────────────

class _SqliteBackend:
    mode = "sqlite"

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA foreign_keys=ON")

    def ensure_tracking(self):
        self.conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                   version    TEXT PRIMARY KEY,
                   filename   TEXT,
                   status     TEXT NOT NULL DEFAULT 'applied',
                   applied_at TEXT NOT NULL
               )"""
        )
        self.conn.commit()

    def applied_versions(self) -> set:
        return {r[0] for r in self.conn.execute("SELECT version FROM schema_migrations").fetchall()}

    def record(self, version: str, filename: str, status: str = "applied"):
        self.conn.execute(
            "INSERT INTO schema_migrations (version, filename, status, applied_at) "
            "VALUES (?,?,?,?) ON CONFLICT(version) DO UPDATE SET "
            "filename=excluded.filename, status=excluded.status, applied_at=excluded.applied_at",
            (version, filename, status, _now_iso()),
        )
        self.conn.commit()

    def apply_file(self, path: Path):
        statements = _split_statements(Path(path).read_text(encoding="utf-8"))
        try:
            for stmt in statements:
                try:
                    self.conn.execute(stmt)
                except sqlite3.OperationalError as e:
                    msg = str(e).lower()
                    if "duplicate column" in msg or "already exists" in msg:
                        continue  # 멱등: 이미 적용된 객체는 건너뜀
                    raise
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def close(self):
        self.conn.close()


class _PgBackend:
    mode = "postgres"
    # 멱등 무시 가능한 SQLSTATE (이미 존재하는 객체)
    _IGNORABLE = {
        "42P07",  # duplicate_table
        "42710",  # duplicate_object
        "42701",  # duplicate_column
        "42P06",  # duplicate_schema
        "42723",  # duplicate_function
        "42P16",  # invalid_table_definition (이미 PK 등)
        "42P05",  # duplicate_prepared_statement
    }

    def __init__(self, database_url: str):
        import psycopg2
        self._psycopg2 = psycopg2
        self.conn = psycopg2.connect(database_url)
        self.conn.autocommit = False

    def ensure_tracking(self):
        with self.conn.cursor() as cur:
            cur.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                       version    TEXT PRIMARY KEY,
                       filename   TEXT,
                       status     TEXT NOT NULL DEFAULT 'applied',
                       applied_at TEXT NOT NULL
                   )"""
            )
        self.conn.commit()

    def applied_versions(self) -> set:
        with self.conn.cursor() as cur:
            cur.execute("SELECT version FROM schema_migrations")
            return {r[0] for r in cur.fetchall()}

    def record(self, version: str, filename: str, status: str = "applied"):
        with self.conn.cursor() as cur:
            cur.execute(
                "INSERT INTO schema_migrations (version, filename, status, applied_at) "
                "VALUES (%s,%s,%s,%s) ON CONFLICT (version) DO UPDATE SET "
                "filename=EXCLUDED.filename, status=EXCLUDED.status, applied_at=EXCLUDED.applied_at",
                (version, filename, status, _now_iso()),
            )
        self.conn.commit()

    def apply_file(self, path: Path):
        statements = _split_statements(Path(path).read_text(encoding="utf-8"))
        cur = self.conn.cursor()
        try:
            for stmt in statements:
                cur.execute("SAVEPOINT mig_stmt")
                try:
                    cur.execute(stmt)
                    cur.execute("RELEASE SAVEPOINT mig_stmt")
                except self._psycopg2.Error as e:
                    cur.execute("ROLLBACK TO SAVEPOINT mig_stmt")
                    if getattr(e, "pgcode", None) in self._IGNORABLE:
                        continue  # 멱등: 이미 존재하는 객체는 건너뜀
                    raise
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        finally:
            cur.close()

    def close(self):
        self.conn.close()


def get_backend(database_url: str = "", db_path: str = ""):
    url = database_url or os.environ.get("DATABASE_URL", "")
    if url:
        return _PgBackend(url)
    return _SqliteBackend(db_path or str(REPO_ROOT / "app.db"))


# ──────────────────────────────────────────────
#  명령
# ──────────────────────────────────────────────

def cmd_status(backend, migrations_dir: Path = MIGRATIONS_DIR) -> dict:
    backend.ensure_tracking()
    applied = backend.applied_versions()
    migs = discover_migrations(migrations_dir)
    pending = [m for m in migs if m["version"] not in applied]
    print(f"[{backend.mode}] migrations {len(migs)} - applied {len(applied)} / pending {len(pending)}")
    for m in migs:
        mark = "[x]" if m["version"] in applied else "[ ]"
        f, note = _select_file(m, backend.mode)
        suffix = f" ({note})" if note else ""
        print(f"  {mark} {m['version']}{suffix}")
    return {"total": len(migs), "applied": len(applied), "pending": [m["version"] for m in pending]}


def cmd_baseline(backend, migrations_dir: Path = MIGRATIONS_DIR, through: str = None) -> list:
    """현재 존재하는 마이그레이션을 '실행 없이' 적용표시(status='baseline')."""
    backend.ensure_tracking()
    applied = backend.applied_versions()
    migs = discover_migrations(migrations_dir)
    stamped = []
    for m in migs:
        if through and m["version"] > through:
            break
        if m["version"] in applied:
            continue
        f, _ = _select_file(m, backend.mode)
        fname = f.name if f else ""
        backend.record(m["version"], fname, status="baseline")
        stamped.append(m["version"])
        print(f"  [baseline] {m['version']} (stamp, no exec)")
    print(f"[{backend.mode}] baseline done - {len(stamped)} stamped")
    return stamped


def cmd_apply(backend, migrations_dir: Path = MIGRATIONS_DIR, target: str = None) -> list:
    """대기 마이그레이션을 순서대로 실행·기록."""
    backend.ensure_tracking()
    applied = backend.applied_versions()
    migs = discover_migrations(migrations_dir)
    done = []
    for m in migs:
        if m["version"] in applied:
            continue
        if target and m["version"] > target:
            break
        f, note = _select_file(m, backend.mode)
        if f is None:
            # SQLite 모드의 PG 전용 등 — 실행 불가, skip 으로 기록(영구 pending 방지)
            backend.record(m["version"], "", status=f"skipped:{note}")
            print(f"  [skip] {m['version']} ({note})")
            continue
        print(f"  [apply] {m['version']} <- {f.name}")
        backend.apply_file(f)
        backend.record(m["version"], f.name, status="applied")
        done.append(m["version"])
    print(f"[{backend.mode}] apply done - {len(done)} applied")
    return done


def main():
    parser = argparse.ArgumentParser(description="통합 스키마 마이그레이션 러너")
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--status", action="store_true", help="적용/대기 목록 출력")
    g.add_argument("--baseline", action="store_true", help="현재 마이그레이션을 무실행 채택")
    g.add_argument("--apply", action="store_true", help="대기 마이그레이션 실행·기록")
    parser.add_argument("--baseline-through", default=None, help="이 version 까지만 baseline")
    parser.add_argument("--target", default=None, help="이 version 까지만 apply")
    parser.add_argument("--db-path", default=str(REPO_ROOT / "app.db"), help="SQLite 경로")
    parser.add_argument("--database-url", default="", help="PG URL (기본 $DATABASE_URL)")
    args = parser.parse_args()

    backend = get_backend(args.database_url, args.db_path)
    mode = backend.mode
    print("=" * 60)
    print(f"  migrate_runner - {mode}")
    print("=" * 60)
    try:
        if args.status:
            cmd_status(backend)
        elif args.baseline:
            cmd_baseline(backend, through=args.baseline_through)
        elif args.apply:
            cmd_apply(backend, target=args.target)
    finally:
        backend.close()
    print("=" * 60)


if __name__ == "__main__":
    main()

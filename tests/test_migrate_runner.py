"""
test_migrate_runner.py — 통합 마이그레이션 러너 검증 (SQLite 경로)

임시 마이그레이션 디렉터리 + 임시 SQLite DB 로 러너 로직을 검증한다.
실제 스키마/PG 의존 없음 — 순수 러너 동작(discover/status/apply/baseline/멱등/skip).
"""

import os
import sys
import sqlite3
import tempfile
import shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "migrations"))

import migrate_runner as mr  # noqa: E402


def _make_toy_migrations(d: Path):
    """toy 마이그레이션 3종 생성:
    001_toy        : PG + SQLite (toy_a)
    002_pgonly     : PG 전용 (toy_b)  → SQLite 모드선 skip
    003_toy        : PG + SQLite (toy_c)
    """
    (d / "001_toy.sql").write_text("CREATE TABLE toy_a (id INTEGER);", encoding="utf-8")
    (d / "001_toy_sqlite.sql").write_text("CREATE TABLE toy_a (id INTEGER);", encoding="utf-8")
    (d / "002_pgonly.sql").write_text("CREATE TABLE toy_b (id INTEGER);", encoding="utf-8")
    (d / "003_toy.sql").write_text("CREATE TABLE toy_c (id INTEGER);", encoding="utf-8")
    (d / "003_toy_sqlite.sql").write_text("CREATE TABLE toy_c (id INTEGER);", encoding="utf-8")


def _tmp_env():
    """(migrations_dir, db_path, cleanup) 반환. DATABASE_URL 제거(SQLite 강제)."""
    os.environ.pop("DATABASE_URL", None)
    base = Path(tempfile.mkdtemp(prefix="mig_test_"))
    mig = base / "migrations"
    mig.mkdir()
    _make_toy_migrations(mig)
    db_path = str(base / "test.sqlite")
    return mig, db_path, lambda: shutil.rmtree(base, ignore_errors=True)


def _tables(db_path):
    c = sqlite3.connect(db_path)
    try:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        c.close()


def test_discover():
    mig, db_path, cleanup = _tmp_env()
    try:
        migs = mr.discover_migrations(mig)
        versions = [m["version"] for m in migs]
        assert versions == ["001_toy", "002_pgonly", "003_toy"], versions
        # 001: pg + sqlite 둘 다
        m1 = migs[0]
        assert m1["pg_file"] is not None and m1["sqlite_file"] is not None
        # 002: pg 만
        m2 = migs[1]
        assert m2["pg_file"] is not None and m2["sqlite_file"] is None
        print("test_discover: OK")
    finally:
        cleanup()


def test_select_file():
    mig, db_path, cleanup = _tmp_env()
    try:
        migs = {m["version"]: m for m in mr.discover_migrations(mig)}
        # PG 모드: pg 파일
        f, note = mr._select_file(migs["001_toy"], "postgres")
        assert f.name == "001_toy.sql" and note is None
        # SQLite 모드: sqlite 파일 우선
        f, note = mr._select_file(migs["001_toy"], "sqlite")
        assert f.name == "001_toy_sqlite.sql" and note is None
        # SQLite 모드 + PG 전용 → None, pg-only
        f, note = mr._select_file(migs["002_pgonly"], "sqlite")
        assert f is None and note == "pg-only"
        print("test_select_file: OK")
    finally:
        cleanup()


def test_status_apply_idempotent():
    mig, db_path, cleanup = _tmp_env()
    try:
        be = mr._SqliteBackend(db_path)
        # 초기 status: 3 대기
        st = mr.cmd_status(be, mig)
        assert st["total"] == 3 and st["applied"] == 0 and len(st["pending"]) == 3, st

        # apply: 001/003 실제 적용, 002 는 pg-only skip
        done = mr.cmd_apply(be, mig)
        assert done == ["001_toy", "003_toy"], done
        be.close()

        tabs = _tables(db_path)
        assert "toy_a" in tabs and "toy_c" in tabs, tabs
        assert "toy_b" not in tabs, "pg-only 002 는 SQLite 에서 실행되면 안 됨"

        # schema_migrations 기록 확인: 001 applied, 002 skipped:*, 003 applied
        c = sqlite3.connect(db_path)
        rows = dict(c.execute("SELECT version, status FROM schema_migrations").fetchall())
        c.close()
        assert rows["001_toy"] == "applied"
        assert rows["003_toy"] == "applied"
        assert rows["002_pgonly"].startswith("skipped"), rows
        # 멱등 재실행: 새로 적용되는 것 0
        be2 = mr._SqliteBackend(db_path)
        done2 = mr.cmd_apply(be2, mig)
        be2.close()
        assert done2 == [], done2
        print("test_status_apply_idempotent: OK")
    finally:
        cleanup()


def test_baseline_no_execution():
    mig, db_path, cleanup = _tmp_env()
    try:
        be = mr._SqliteBackend(db_path)
        stamped = mr.cmd_baseline(be, mig)
        assert stamped == ["001_toy", "002_pgonly", "003_toy"], stamped
        be.close()
        # baseline 은 무실행 → toy_a/toy_c 가 생기면 안 됨
        tabs = _tables(db_path)
        assert "toy_a" not in tabs and "toy_c" not in tabs, tabs
        # schema_migrations 에는 3개가 status='baseline' 으로 기록
        c = sqlite3.connect(db_path)
        rows = dict(c.execute("SELECT version, status FROM schema_migrations").fetchall())
        c.close()
        assert all(v == "baseline" for v in rows.values()), rows
        assert len(rows) == 3
        # baseline 이후 apply → 새로 적용 0 (이미 채택됨)
        be2 = mr._SqliteBackend(db_path)
        done = mr.cmd_apply(be2, mig)
        be2.close()
        assert done == [], done
        print("test_baseline_no_execution: OK")
    finally:
        cleanup()


def test_apply_file_idempotent_existing():
    """이미 존재하는 객체를 만드는 statement 는 멱등 처리(예외 없이 통과)."""
    mig, db_path, cleanup = _tmp_env()
    try:
        # 사전에 toy_a 생성
        c = sqlite3.connect(db_path)
        c.execute("CREATE TABLE toy_a (id INTEGER)")
        c.commit()
        c.close()
        be = mr._SqliteBackend(db_path)
        # 001_toy_sqlite.sql 은 CREATE TABLE toy_a → already exists 여야 하나 예외 없이 통과
        be.apply_file(mig / "001_toy_sqlite.sql")
        be.close()
        print("test_apply_file_idempotent_existing: OK")
    finally:
        cleanup()


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\nALL {len(fns)} TESTS PASSED")


if __name__ == "__main__":
    _run_all()

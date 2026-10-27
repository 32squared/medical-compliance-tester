"""
호스트 기동 시 고아 running 배치 정리 — Job 소유 run 은 건드리지 않는다 (SQLite 임시 DB).
실행: python -m pytest tests/test_run_owner_orphan_cleanup.py -v

배경(2026-10-27): Cloud Run Job(job_runner) 이 돌리던 run 이, 호스트 서비스가 오토스케일로 새 인스턴스를
띄우며 init_db 를 다시 타는 순간 'cancelled' 로 바뀌었다(다음 점진 저장 때 'running' 으로 되돌아오는 깜빡임).
"""
import sys
import os
import tempfile
import atexit

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['DATABASE_URL'] = ''

import db as _db
import dbcommon as _dbcommon


def _import_proxy():
    # proxy_server 는 import 시점에 sys.stdout/err 을 UTF-8 래퍼로 교체한다 — test_share_eval_v3 와 같은 방식으로 되돌린다.
    out, err = sys.stdout, sys.stderr
    try:
        import proxy_server
    finally:
        for stream, orig in ((sys.stdout, out), (sys.stderr, err)):
            if stream is not orig:
                try:
                    stream.detach()
                except Exception:
                    pass
        sys.stdout, sys.stderr = out, err
    return proxy_server

_TEST_DB = tempfile.mktemp(suffix='_test_run_owner.db')
atexit.register(lambda: os.unlink(_TEST_DB) if os.path.exists(_TEST_DB) else None)


@pytest.fixture(autouse=True, scope='module')
def _own_sqlite_db():
    # 다른 DB 테스트 모듈이 import 시점에 DB_PATH 를 제 파일로 바꾸므로, 실행 시점에 이 모듈 것으로 맞춘다.
    saved = (_dbcommon._use_postgres, _dbcommon._pg_pool, _dbcommon.DB_PATH, _db.DB_PATH)
    _dbcommon._use_postgres = False
    _dbcommon._pg_pool = None
    _dbcommon.DB_PATH = _TEST_DB
    _db._use_postgres = False
    _db.DB_PATH = _TEST_DB
    _db.init_db(_TEST_DB)
    yield
    _dbcommon._use_postgres, _dbcommon._pg_pool, _dbcommon.DB_PATH, _db.DB_PATH = saved


def _status(run_id):
    return (_db.get_test_run(run_id) or {}).get('status')


def test_owner_defaults_to_host_and_job_is_kept():
    _db.save_test_run({'id': 'r-host', 'status': 'running', 'results': []})
    _db.save_test_run({'id': 'r-job', 'status': 'running', 'results': [], 'owner': _db.RUN_OWNER_JOB})
    _db.save_test_run({'id': 'r-done', 'status': 'completed', 'results': []})
    assert _db.get_test_run('r-host')['owner'] == 'host'
    assert _db.get_test_run('r-job')['owner'] == 'job'

    _db.init_db(_TEST_DB)   # 호스트 재시작(새 인스턴스 기동)과 같은 경로

    assert _status('r-host') == 'cancelled'    # 프로세스 안 배치는 상태를 잃었으니 고아 정리
    assert _status('r-job') == 'running'       # Job 은 별 프로세스에서 계속 도는 중
    assert _status('r-done') == 'completed'


def test_legacy_rows_without_owner_are_treated_as_host():
    with _db.get_conn() as (conn, cur):
        cur.execute("INSERT INTO test_runs (id, run_at, status, owner) VALUES ('r-legacy', '2026-10-27T00:00:00', 'running', NULL)")
    _db.init_db(_TEST_DB)
    assert _status('r-legacy') == 'cancelled'


def test_job_runner_marks_its_runs_as_job_owned():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'job_runner.py'), encoding='utf-8').read()
    assert "'owner': db.RUN_OWNER_JOB" in src
    assert "COALESCE(owner, 'host') <> 'job'" in _db.ORPHAN_RUN_CANCEL_SQL


def test_db_run_to_proxy_preserves_owner():
    """이력 PUT 경로(_save_run_to_db(_db_run_to_proxy(row))) 가 Job 소유를 host 로 덮지 않는다."""
    ps = _import_proxy()
    _db.save_test_run({'id': 'r-job2', 'status': 'running', 'results': [], 'owner': _db.RUN_OWNER_JOB})
    row = _db.get_test_run('r-job2')
    assert ps._db_run_to_proxy(row)['owner'] == 'job'
    ps._save_run_to_db(ps._db_run_to_proxy(row))          # 갱신 왕복
    assert _db.get_test_run('r-job2')['owner'] == 'job'
    _db.init_db(_TEST_DB)
    assert _status('r-job2') == 'running'

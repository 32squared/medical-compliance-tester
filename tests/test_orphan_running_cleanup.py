"""
인스턴스 시작 시 '고아 running 배치 정리' 단위 테스트 (SQLite 임시 파일 DB)

db.init_db 는 서비스 인스턴스가 뜰 때마다 돈다(오토스케일·새 리비전 배포). 그때
status='running' 인 test_runs 를 cancelled 로 바꾸는데, 대상은 **서비스 스레드 배치**
(id 가 'batch-…', proxy_server._run_batch) 뿐이어야 한다. Cloud Run Job(job_runner) 배치는
UI 트리거면 'job-…', gcloud 로 직접 띄우면 임의 id(예: phr350-dev-l27-20261013T065350)인데
서비스와 생명주기가 달라 아직 돌고 있을 수 있다 — 건드리면 history 에 '⏹ 중지됨' 으로 잘못 뜬다.

실행: python -m pytest tests/test_orphan_running_cleanup.py -v
"""
import sys
import os
import unittest
import tempfile
import atexit
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# SQLite 모드 강제 (PostgreSQL 비활성화)
os.environ['DATABASE_URL'] = ''

import db as _db_module
import dbcommon as _dbcommon

_TEST_DB = tempfile.mktemp(suffix='_test_orphan_cleanup.db')
atexit.register(lambda: os.unlink(_TEST_DB) if os.path.exists(_TEST_DB) else None)

_dbcommon._use_postgres = False
_dbcommon._pg_pool = None
_dbcommon.DB_PATH = _TEST_DB
_db_module._use_postgres = False
_db_module.DB_PATH = _TEST_DB
_db_module.init_db(_TEST_DB)


# (id, status) — 인스턴스 재시작 뒤 기대 status
_FIXTURE = [
    # 서비스 스레드 배치: 인스턴스가 죽으면 진짜 고아 → cancelled
    ('batch-20261013-070000-a1b2c3', 'running', 'cancelled'),
    # 이미 끝난 서비스 배치는 그대로
    ('batch-20261013-060000-d4e5f6', 'completed', 'completed'),
    ('batch-20261013-050000-aabbcc', 'cancelled', 'cancelled'),
    # UI 가 띄운 Cloud Run Job 배치 — 아직 돌고 있을 수 있다 → 그대로
    ('job-20261013-065350-112233', 'running', 'running'),
    # gcloud 로 직접 띄운 Job 배치(접두사 없음) — 2026-10-13 재현 run → 그대로
    ('phr350-dev-l27-20261013T065350', 'running', 'running'),
    ('phr350r-v4-20261012-0422', 'running', 'running'),
    # 단일 실행·병합 결과 — running 으로 저장되는 경로가 없지만, 있어도 건드리지 않는다
    ('run-20261013-070500-S-001', 'running', 'running'),
    ('merged-20261013-071000-778899', 'running', 'running'),
]


def _seed():
    for rid, status, _ in _FIXTURE:
        _db_module.save_test_run({'id': rid, 'status': status, 'results': []})


def _status_of(rid):
    conn = sqlite3.connect(_TEST_DB)
    try:
        row = conn.execute("SELECT status FROM test_runs WHERE id = ?", (rid,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


class TestOrphanRunningCleanupSql(unittest.TestCase):
    """정리 SQL 자체 — 서비스 배치 접두사만 대상인지"""

    def test_sql_targets_only_service_batch_prefix(self):
        sql = _db_module.ORPHAN_RUNNING_CLEANUP_SQL
        self.assertIn("status = 'running'", sql)
        self.assertIn(f"id LIKE '{_db_module.SERVICE_BATCH_ID_PREFIX}%'", sql)
        self.assertEqual(_db_module.SERVICE_BATCH_ID_PREFIX, 'batch-')

    def test_prefix_matches_proxy_server_service_batch_ids(self):
        """proxy_server._run_batch 가 만드는 id 형식과 접두사가 같아야 한다(소스 문자열로 확인 —
        proxy_server import 는 stdout 재정의·네트워크 설정을 끌고 와 여기선 피한다)."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, 'proxy_server.py'), encoding='utf-8') as f:
            src = f.read()
        self.assertIn('run_id = f"batch-{datetime.now()', src)
        # Job 트리거는 다른 접두사를 써야 한다(정리 대상에서 빠지도록)
        self.assertIn('run_id = f"job-{datetime.now()', src)
        self.assertFalse(_db_module.SERVICE_BATCH_ID_PREFIX.startswith('job'))


class TestInitDbCleanup(unittest.TestCase):
    """init_db 재실행(= 새 인스턴스 시작)이 서비스 배치만 cancelled 로 바꾸는지"""

    def setUp(self):
        # 같은 pytest 세션의 다른 DB 테스트(test_rlhf_db 등)도 import 시점에 dbcommon.DB_PATH 를
        # 자기 파일로 바꾼다 → 여기선 매 테스트마다 우리 파일로 되돌리고 끝나면 복원한다.
        self._prev_paths = (_dbcommon.DB_PATH, _db_module.DB_PATH)
        _dbcommon.DB_PATH = _TEST_DB
        _db_module.DB_PATH = _TEST_DB
        conn = sqlite3.connect(_TEST_DB)
        try:
            conn.execute("DELETE FROM test_runs")
            conn.commit()
        finally:
            conn.close()
        _seed()

    def tearDown(self):
        _dbcommon.DB_PATH, _db_module.DB_PATH = self._prev_paths

    def test_init_db_cancels_only_service_thread_batches(self):
        _db_module.init_db(_TEST_DB)
        for rid, _before, expected in _FIXTURE:
            self.assertEqual(_status_of(rid), expected, rid)

    def test_init_db_is_idempotent(self):
        _db_module.init_db(_TEST_DB)
        _db_module.init_db(_TEST_DB)
        for rid, _before, expected in _FIXTURE:
            self.assertEqual(_status_of(rid), expected, rid)

    def test_helper_reports_changed_rows(self):
        rc = _db_module.cancel_orphan_service_batches()
        self.assertEqual(rc, 1)   # running 인 'batch-…' 는 fixture 에 하나
        self.assertEqual(_db_module.cancel_orphan_service_batches(), 0)
        self.assertEqual(_status_of('batch-20261013-070000-a1b2c3'), 'cancelled')
        self.assertEqual(_status_of('job-20261013-065350-112233'), 'running')
        self.assertEqual(_status_of('phr350-dev-l27-20261013T065350'), 'running')

    def test_job_runner_flush_after_restart_keeps_running(self):
        """Job 이 돌면서 _flush_to_db(status='running') 로 덮어쓰는 흐름 — 서비스 재시작이
        끼어들어도 Job 행은 running 을 유지하고, 마지막 'completed' 가 그대로 남는다."""
        rid = 'phr350-dev-l27-20261013T065350'
        _db_module.init_db(_TEST_DB)                       # 서비스 인스턴스 시작
        self.assertEqual(_status_of(rid), 'running')
        _db_module.save_test_run({'id': rid, 'status': 'running', 'total': 350, 'passed': 10,
                                  'results': [{'scenarioId': 'S-1'}]})   # Job 중간 flush
        _db_module.init_db(_TEST_DB)                       # 또 다른 인스턴스 시작
        self.assertEqual(_status_of(rid), 'running')
        _db_module.save_test_run({'id': rid, 'status': 'completed', 'total': 350, 'passed': 300,
                                  'results': [{'scenarioId': 'S-1'}]})   # Job 마지막 flush
        _db_module.init_db(_TEST_DB)
        self.assertEqual(_status_of(rid), 'completed')


if __name__ == '__main__':
    unittest.main()

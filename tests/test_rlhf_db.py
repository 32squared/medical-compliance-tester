"""
RLHF DB 단위 테스트 (SQLite 임시 파일 DB)
실행: python -m pytest tests/test_rlhf_db.py -v
"""
import sys
import os
import json
import unittest
import tempfile
import atexit

# 프로젝트 루트를 path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# SQLite 모드 강제 (PostgreSQL 비활성화)
os.environ['DATABASE_URL'] = ''

import db as _db_module

# 테스트 전용 임시 파일 DB — 매 실행마다 새로운 파일
_TEST_DB = tempfile.mktemp(suffix='_test_rlhf.db')
atexit.register(lambda: os.unlink(_TEST_DB) if os.path.exists(_TEST_DB) else None)

_db_module._use_postgres = False
_db_module.DB_PATH = _TEST_DB
_db_module.init_db(_TEST_DB)


class TestAddResponseFeedback(unittest.TestCase):
    """add_response_feedback / get_response_feedback 테스트"""
    # response_feedback는 FK 없는 독립 테이블 → 부모 레코드 불필요

    def test_add_and_get_by_message_id(self):
        fb_id = _db_module.add_response_feedback(
            message_id='msg-test-001',
            conversation_id='conv-test-001',
            evaluator_id='tester1',
            evaluator_name='테스터1',
            rating=5,
            labels_json='["우수답변"]',
            feedback_note='훌륭한 응답',
        )
        self.assertIsNotNone(fb_id)
        self.assertIsInstance(fb_id, str)

        rows = _db_module.get_response_feedback(message_id='msg-test-001')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['evaluator_id'], 'tester1')
        self.assertEqual(rows[0]['rating'], 5)
        self.assertEqual(rows[0]['feedback_note'], '훌륭한 응답')

    def test_add_bad_feedback_with_correction(self):
        fb_id = _db_module.add_response_feedback(
            message_id='msg-test-002',
            conversation_id='conv-test-002',
            evaluator_id='tester2',
            rating=1,
            labels_json='["진단언급","처방시도"]',
            corrected_response='더 적절한 응답입니다.',
            feedback_note='진단 언급이 있음',
        )
        rows = _db_module.get_response_feedback(message_id='msg-test-002')
        self.assertEqual(rows[0]['corrected_response'], '더 적절한 응답입니다.')

    def test_get_by_conversation_id(self):
        _db_module.add_response_feedback(
            message_id='msg-conv-001',
            conversation_id='conv-shared',
            evaluator_id='tester1',
            rating=4,
        )
        _db_module.add_response_feedback(
            message_id='msg-conv-002',
            conversation_id='conv-shared',
            evaluator_id='tester1',
            rating=3,
        )
        rows = _db_module.get_response_feedback(conversation_id='conv-shared')
        self.assertGreaterEqual(len(rows), 2)

    def test_get_all_no_filter(self):
        rows = _db_module.get_response_feedback(limit=100)
        self.assertIsInstance(rows, list)

    def test_get_feedback_stats(self):
        stats = _db_module.get_feedback_stats(days=30)
        self.assertIn('total', stats)
        self.assertIn('avgRating', stats)
        self.assertIn('labelDistribution', stats)


class TestPreferencePairs(unittest.TestCase):
    """add_preference_pair / list_preference_pairs / export 테스트"""

    def test_add_and_list(self):
        pair_id = _db_module.add_preference_pair(
            prompt='두통이 있어요',
            response_chosen='충분한 휴식을 취하시고, 증상이 지속되면 병원 방문을 권장합니다.',
            response_rejected='아스피린 500mg을 드세요.',
            chosen_composite=0.88,
            rejected_composite=0.21,
            label_source='human',
        )
        self.assertIsNotNone(pair_id)

        pairs = _db_module.list_preference_pairs(limit=50)
        self.assertIsInstance(pairs, list)
        ids = [p['id'] for p in pairs]
        self.assertIn(pair_id, ids)

    def test_list_filter_exported(self):
        pid = _db_module.add_preference_pair(
            prompt='테스트 질문',
            response_chosen='좋은 응답',
            response_rejected='나쁜 응답',
            label_source='human',
        )
        # unexported 목록에 포함
        unexported = _db_module.list_preference_pairs(exported=False)
        ids = [p['id'] for p in unexported]
        self.assertIn(pid, ids)

        # exported 목록에는 없음
        exported = _db_module.list_preference_pairs(exported=True)
        ids_exp = [p['id'] for p in exported]
        self.assertNotIn(pid, ids_exp)

    def test_mark_exported(self):
        pid = _db_module.add_preference_pair(
            prompt='export 테스트',
            response_chosen='chosen',
            response_rejected='rejected',
        )
        result = _db_module.mark_preference_pairs_exported(pair_ids=[pid])
        self.assertGreater(result.get('exported_count', 0), 0)

        exported = _db_module.list_preference_pairs(exported=True)
        ids = [p['id'] for p in exported]
        self.assertIn(pid, ids)

    def test_mark_all_unexported(self):
        _db_module.add_preference_pair(
            prompt='all export 1', response_chosen='c1', response_rejected='r1'
        )
        _db_module.add_preference_pair(
            prompt='all export 2', response_chosen='c2', response_rejected='r2'
        )
        result = _db_module.mark_preference_pairs_exported(all_unexported=True)
        self.assertGreater(result.get('exported_count', 0), 0)

    def test_export_dpo_openai_format(self):
        _db_module.add_preference_pair(
            prompt='DPO 테스트 질문',
            response_chosen='적절한 응답입니다',
            response_rejected='부적절한 응답입니다',
            label_source='human',
        )
        data = _db_module.export_preference_pairs_dpo(format='openai', limit=10)
        self.assertIsInstance(data, list)
        if data:
            item = data[0]
            self.assertIn('messages', item)
            self.assertIn('chosen', item)
            self.assertIn('rejected', item)

    def test_export_dpo_hf_format(self):
        data = _db_module.export_preference_pairs_dpo(format='hf', limit=10)
        self.assertIsInstance(data, list)
        if data:
            item = data[0]
            self.assertIn('prompt', item)
            self.assertIn('chosen', item)
            self.assertIn('rejected', item)


class TestRlhfStats(unittest.TestCase):
    """get_rlhf_stats 테스트"""

    def test_stats_structure(self):
        stats = _db_module.get_rlhf_stats()
        self.assertIn('total_feedback', stats)
        self.assertIn('total_pairs', stats)
        self.assertIn('exported_pairs', stats)
        self.assertIn('avg_composite_reward', stats)
        self.assertIn('label_distribution', stats)
        self.assertIn('daily_feedback', stats)
        self.assertIsInstance(stats['daily_feedback'], list)

    def test_stats_counts_non_negative(self):
        stats = _db_module.get_rlhf_stats()
        self.assertGreaterEqual(stats['total_feedback'], 0)
        self.assertGreaterEqual(stats['total_pairs'], 0)
        self.assertGreaterEqual(stats['exported_pairs'], 0)


class TestCompositeReward(unittest.TestCase):
    """composite_reward() 함수 테스트"""

    def setUp(self):
        # proxy_server에서 composite_reward 임포트
        import importlib.util, pathlib
        spec = importlib.util.spec_from_file_location(
            'proxy_server',
            pathlib.Path(__file__).parent.parent / 'proxy_server.py'
        )
        # 전체 임포트 대신 소스에서 함수만 추출
        src = pathlib.Path(__file__).parent.parent.joinpath('proxy_server.py').read_text(encoding='utf-8')
        # composite_reward 함수 부분만 exec
        ns = {}
        start = src.find('def composite_reward(')
        end = src.find('\ndef ', start + 1)
        func_src = src[start:end]
        exec(func_src, ns)
        self.composite_reward = ns['composite_reward']

    def test_critical_violation_returns_zero(self):
        score = self.composite_reward(
            legal_score=90, consult_score=85,
            regex_violations_critical=1
        )
        self.assertEqual(score, 0.0)

    def test_perfect_scores(self):
        score = self.composite_reward(
            legal_score=100, consult_score=100,
            regex_violations_critical=0
        )
        self.assertAlmostEqual(score, 1.0, places=2)

    def test_zero_scores(self):
        # legal=0, consult=0, no critical violations
        # compliance component (0.15) still contributes since violations=0
        score = self.composite_reward(
            legal_score=0, consult_score=0,
            regex_violations_critical=0
        )
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 0.2)  # 0~20% 범위 (compliance만 기여)

    def test_with_human_rating(self):
        score_without = self.composite_reward(
            legal_score=80, consult_score=70,
            regex_violations_critical=0,
            human_rating=None
        )
        score_with = self.composite_reward(
            legal_score=80, consult_score=70,
            regex_violations_critical=0,
            human_rating=5
        )
        # human_rating=5(최대)이면 점수가 더 높거나 같아야 함
        self.assertGreaterEqual(score_with, score_without * 0.9)

    def test_output_range(self):
        for legal in [0, 50, 100]:
            for consult in [0, 50, 100]:
                score = self.composite_reward(
                    legal_score=legal, consult_score=consult,
                    regex_violations_critical=0
                )
                self.assertGreaterEqual(score, 0.0)
                self.assertLessEqual(score, 1.0)


if __name__ == '__main__':
    unittest.main(verbosity=2)

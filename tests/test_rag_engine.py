"""
rag_engine.py 단위 테스트.

가능한 한 mock으로 구성 (실제 DB / OpenAI API 불필요).
실제 PostgreSQL 통합 테스트는 @pytest.mark.integration 마커.

테스트 케이스:
  1. rrf_fusion — dense top 3 + sparse top 3 → 통합 top-K 정렬 검증
  2. red_flag boost — "고열" 키워드 있는 청크의 score × 1.3 확인
  3. evidence_topic 검증 — 무관 청크 제거 (mock embedding)
  4. evidence_country='KR' 부스팅
  5. SQLite 모드 → NotImplementedError
  6. top_k 파라미터 동작
  7. source_types 필터링
"""
import os
import sys
import json
import math
import pytest
from unittest.mock import patch, MagicMock

# 프로젝트 루트를 sys.path에 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rag_engine import (
    rrf_fusion,
    detect_symptom_keys,
    apply_red_flag_boost,
    check_evidence_topic_alignment,
    apply_country_boost,
    hybrid_search,
    CHECKLISTS,
)


# ─── 공통 픽스처 ────────────────────────────────────────────

def _make_chunk(chunk_id, content="내용", score=0.5, severity=None,
                evidence_country=None, regulatory_korea=False,
                evidence_topic=None):
    """테스트용 청크 딕셔너리 생성 헬퍼."""
    return {
        "chunk_id": chunk_id,
        "document_id": f"doc_{chunk_id}",
        "content": content,
        "section_path": [],
        "symptom_tags": "[]",
        "severity": severity,
        "evidence_country": evidence_country,
        "regulatory_korea": regulatory_korea,
        "evidence_topic": evidence_topic,
        "topic_keywords": "[]",
        "source_id": "test_source",
        "evidence_level": "B",
        "title": f"문서_{chunk_id}",
        "score": score,
        "boost_reasons": [],
    }


# ════════════════════════════════════════════════════════════
#  TC-1: rrf_fusion — 통합 정렬 검증
# ════════════════════════════════════════════════════════════

class TestRrfFusion:
    def test_dense_only(self):
        """sparse가 없을 때 dense 순위가 그대로 반영된다."""
        dense = [
            _make_chunk("A"), _make_chunk("B"), _make_chunk("C")
        ]
        result = rrf_fusion(dense, [], k=60)
        # A가 rank 0이므로 1/(60+0) 가장 높음
        assert result[0]["chunk_id"] == "A"
        assert result[1]["chunk_id"] == "B"
        assert result[2]["chunk_id"] == "C"

    def test_sparse_only(self):
        """dense가 없을 때 sparse 순위가 그대로 반영된다."""
        sparse = [
            _make_chunk("X"), _make_chunk("Y"), _make_chunk("Z")
        ]
        result = rrf_fusion([], sparse, k=60)
        assert result[0]["chunk_id"] == "X"
        assert result[1]["chunk_id"] == "Y"

    def test_overlap_boosted(self):
        """dense 1위 & sparse 1위가 같으면 합산 점수가 가장 높다."""
        dense = [_make_chunk("COMMON"), _make_chunk("D_ONLY")]
        sparse = [_make_chunk("COMMON"), _make_chunk("S_ONLY")]
        result = rrf_fusion(dense, sparse, k=60)
        # COMMON: 1/60 + 1/60 = 2/60
        # D_ONLY: 1/61,  S_ONLY: 1/61
        assert result[0]["chunk_id"] == "COMMON"

    def test_rrf_scores_correct(self):
        """RRF 점수 수식 검증: score = 1/(k+rank)."""
        dense = [_make_chunk("A")]
        sparse = [_make_chunk("B")]
        result = rrf_fusion(dense, sparse, k=60)
        score_map = {r["chunk_id"]: r["score"] for r in result}
        expected_a = 1.0 / (60 + 0)
        expected_b = 1.0 / (60 + 0)
        assert abs(score_map["A"] - expected_a) < 1e-9
        assert abs(score_map["B"] - expected_b) < 1e-9

    def test_combined_top3(self):
        """dense 3개 + sparse 3개 → 최대 6개, 순위 정렬 확인."""
        dense = [_make_chunk(f"D{i}") for i in range(3)]
        sparse = [_make_chunk(f"S{i}") for i in range(3)]
        result = rrf_fusion(dense, sparse, k=60)
        assert len(result) == 6
        # 모두 점수가 내림차순
        for i in range(len(result) - 1):
            assert result[i]["score"] >= result[i + 1]["score"]

    def test_empty_both(self):
        """양쪽 빈 리스트 → 빈 결과."""
        assert rrf_fusion([], [], k=60) == []

    def test_metadata_preserved(self):
        """메타데이터가 결과에 보존된다."""
        dense = [_make_chunk("A", content="발열 관련 내용")]
        result = rrf_fusion(dense, [], k=60)
        assert result[0]["content"] == "발열 관련 내용"


# ════════════════════════════════════════════════════════════
#  TC-2: red_flag boost — ×1.3 확인
# ════════════════════════════════════════════════════════════

class TestRedFlagBoost:
    """
    consultation_checklists.json에서 fever 증상의 red_flag 키워드로
    "고열" 등이 등록되어 있다고 가정.
    실제 키워드는 checklists 데이터에 의존하므로 mock checklists 사용.
    """

    def _mock_checklists(self):
        return {
            "symptoms": {
                "fever": {
                    "symptom_key": "fever",
                    "required_questions": [
                        {"keywords": ["열", "발열"]}
                    ],
                    "red_flags": [
                        {"keywords": ["고열", "의식 변화", "호흡곤란"]},
                    ],
                }
            }
        }

    def test_red_flag_keyword_in_content_boosts_score(self):
        """청크 내용에 red_flag 키워드가 있으면 score × 1.3."""
        cl = self._mock_checklists()
        chunk = _make_chunk("RF1", content="고열이 3일 이상 지속됩니다", score=1.0)
        results = [chunk]
        boosted = apply_red_flag_boost(results, "열이 납니다", cl)
        assert abs(boosted[0]["score"] - 1.3) < 1e-6
        assert any("red_flag" in r for r in boosted[0]["boost_reasons"])

    def test_no_red_flag_keyword_no_boost(self):
        """red_flag 키워드가 없는 청크는 점수 변화 없음."""
        cl = self._mock_checklists()
        chunk = _make_chunk("RF2", content="일반적인 감기 증상입니다", score=1.0)
        results = [chunk]
        boosted = apply_red_flag_boost(results, "열이 납니다", cl)
        assert abs(boosted[0]["score"] - 1.0) < 1e-6

    def test_emergency_severity_boost(self):
        """severity='emergency' 청크는 × 1.2."""
        cl = self._mock_checklists()
        chunk = _make_chunk("RF3", content="응급 처치", score=1.0, severity="emergency")
        results = [chunk]
        boosted = apply_red_flag_boost(results, "열이 납니다", cl)
        assert abs(boosted[0]["score"] - 1.2) < 1e-6
        assert "severity_emergency" in boosted[0]["boost_reasons"]

    def test_both_boosts_combined(self):
        """red_flag + emergency 둘 다 해당하면 1.3 × 1.2 = 1.56."""
        cl = self._mock_checklists()
        chunk = _make_chunk(
            "RF4",
            content="고열 응급 처치가 필요합니다",
            score=1.0,
            severity="emergency",
        )
        results = [chunk]
        boosted = apply_red_flag_boost(results, "열이 납니다", cl)
        expected = 1.0 * 1.3 * 1.2
        assert abs(boosted[0]["score"] - expected) < 1e-6

    def test_no_matching_symptom_no_boost(self):
        """질의에 증상 키워드가 없으면 아무 부스팅 없음."""
        cl = self._mock_checklists()
        chunk = _make_chunk("RF5", content="고열 의식 변화", score=0.5)
        results = [chunk]
        # "두통"이라는 단어는 fever 키워드에 없음
        boosted = apply_red_flag_boost(results, "두통이 있어요", cl)
        assert abs(boosted[0]["score"] - 0.5) < 1e-6

    def test_detect_symptom_keys_from_query(self):
        """detect_symptom_keys가 질의에서 symptom_key를 올바르게 추출한다."""
        cl = self._mock_checklists()
        keys = detect_symptom_keys("발열이 3일째 지속됩니다", cl)
        assert "fever" in keys

    def test_detect_symptom_keys_no_match(self):
        """매칭 없는 질의 → 빈 리스트."""
        cl = self._mock_checklists()
        keys = detect_symptom_keys("날씨가 좋네요", cl)
        assert keys == []

    def test_real_checklists_loaded(self):
        """CHECKLISTS 모듈 변수가 실제 파일에서 로드됐는지 검증."""
        assert "symptoms" in CHECKLISTS
        assert len(CHECKLISTS["symptoms"]) > 0

    def test_real_checklists_fever_exists(self):
        """실제 checklists에 fever가 포함되어 있는지 확인."""
        assert "fever" in CHECKLISTS["symptoms"]


# ════════════════════════════════════════════════════════════
#  TC-3: evidence_topic 검증 — 무관 청크 제거 (mock embedding)
# ════════════════════════════════════════════════════════════

class TestEvidenceTopicAlignment:
    """
    mock embedding provider를 사용해 실제 API 없이 검증.
    """

    def _make_mock_provider(self, vectors: dict):
        """
        texts → vectors 매핑을 가진 mock embedding provider.
        vectors: {"텍스트": [0.1, 0.2, ...]} 형태
        """
        mock = MagicMock()

        def embed_side_effect(texts):
            result = []
            for t in texts:
                if t in vectors:
                    result.append(vectors[t])
                else:
                    # 기본 벡터: 첫 번째 벡터 반환
                    result.append(list(vectors.values())[0])
            return result

        mock.embed.side_effect = embed_side_effect
        return mock

    def test_matching_topic_passes(self):
        """evidence_topic이 질의와 유사하면 (sim >= threshold) 통과."""
        # query vector와 topic vector가 동일 → cosine sim = 1.0
        vec = [1.0, 0.0, 0.0]
        provider = self._make_mock_provider({
            "소아 발열": vec,
            "fever_pediatric": vec,
        })
        chunk = _make_chunk("ET1", evidence_topic="fever_pediatric")
        filtered = check_evidence_topic_alignment(
            [chunk], "소아 발열", provider, threshold=0.4
        )
        assert len(filtered) == 1
        assert filtered[0]["chunk_id"] == "ET1"
        assert filtered[0]["topic_alignment_score"] >= 0.4

    def test_unrelated_topic_removed(self):
        """evidence_topic이 질의와 무관하면 (sim < threshold) 제거."""
        # query vector와 topic vector가 직교 → cosine sim = 0.0
        query_vec = [1.0, 0.0, 0.0]
        topic_vec = [0.0, 1.0, 0.0]
        provider = self._make_mock_provider({
            "소아 발열": query_vec,
            "antimalarial_malaria": topic_vec,
        })
        chunk = _make_chunk("ET2", evidence_topic="antimalarial_malaria")
        filtered = check_evidence_topic_alignment(
            [chunk], "소아 발열", provider, threshold=0.4
        )
        assert len(filtered) == 0

    def test_no_evidence_topic_passes(self):
        """evidence_topic이 없는 청크는 검증 없이 통과."""
        provider = MagicMock()
        provider.embed.return_value = [[1.0, 0.0, 0.0]]
        chunk = _make_chunk("ET3", evidence_topic=None)
        filtered = check_evidence_topic_alignment(
            [chunk], "발열", provider, threshold=0.4
        )
        assert len(filtered) == 1

    def test_all_empty_topics_skipped(self):
        """모든 청크의 evidence_topic이 비어있으면 검증 자체가 스킵된다."""
        provider = MagicMock()
        chunks = [
            _make_chunk("ET4", evidence_topic=None),
            _make_chunk("ET5", evidence_topic=""),
        ]
        filtered = check_evidence_topic_alignment(
            chunks, "발열", provider, threshold=0.4
        )
        # embed가 호출되지 않았어야 함 (검증 스킵)
        provider.embed.assert_not_called()
        assert len(filtered) == 2

    def test_empty_results_returns_empty(self):
        """빈 결과 리스트 입력 → 빈 리스트 반환."""
        provider = MagicMock()
        result = check_evidence_topic_alignment([], "발열", provider)
        assert result == []

    def test_filtered_reason_recorded(self):
        """제거된 청크에 filtered_reason이 기록된다."""
        query_vec = [1.0, 0.0, 0.0]
        topic_vec = [0.0, 1.0, 0.0]
        provider = self._make_mock_provider({
            "발열": query_vec,
            "alopecia_treatment": topic_vec,
        })
        chunk = _make_chunk("ET6", evidence_topic="alopecia_treatment")
        # 함수 반환값에서 제거됐으므로 원본 chunk 딕셔너리 직접 확인
        check_evidence_topic_alignment(
            [chunk], "발열", provider, threshold=0.4
        )
        assert "filtered_reason" in chunk
        assert "evidence_topic_mismatch" in chunk["filtered_reason"]

    def test_multiple_chunks_partial_filter(self):
        """여러 청크 중 일부만 관련 있을 때 관련 청크만 통과."""
        query_vec = [1.0, 0.0, 0.0]
        matching_vec = [0.9, 0.1, 0.0]   # sim ≈ 0.994
        unrelated_vec = [0.0, 0.0, 1.0]  # sim = 0.0
        import math
        # 정규화
        def norm(v):
            n = math.sqrt(sum(x*x for x in v))
            return [x/n for x in v]
        provider = self._make_mock_provider({
            "소아 발열": norm(query_vec),
            "fever_related": norm(matching_vec),
            "skin_disease": norm(unrelated_vec),
        })
        chunks = [
            _make_chunk("C1", evidence_topic="fever_related"),
            _make_chunk("C2", evidence_topic="skin_disease"),
        ]
        filtered = check_evidence_topic_alignment(
            chunks, "소아 발열", provider, threshold=0.4
        )
        chunk_ids = [c["chunk_id"] for c in filtered]
        assert "C1" in chunk_ids
        assert "C2" not in chunk_ids


# ════════════════════════════════════════════════════════════
#  TC-4: evidence_country='KR' 부스팅
# ════════════════════════════════════════════════════════════

class TestCountryBoost:
    def test_kr_country_boost(self):
        """evidence_country='KR' → score × 1.15."""
        chunk = _make_chunk("CB1", score=1.0, evidence_country="KR")
        results = apply_country_boost([chunk])
        assert abs(results[0]["score"] - 1.15) < 1e-6
        assert "country_kr" in results[0]["boost_reasons"]

    def test_non_kr_no_boost(self):
        """evidence_country='US' → 부스팅 없음."""
        chunk = _make_chunk("CB2", score=1.0, evidence_country="US")
        results = apply_country_boost([chunk])
        assert abs(results[0]["score"] - 1.0) < 1e-6
        assert "country_kr" not in results[0]["boost_reasons"]

    def test_regulatory_korea_boost(self):
        """regulatory_korea=True → score × 1.1."""
        chunk = _make_chunk("CB3", score=1.0, regulatory_korea=True)
        results = apply_country_boost([chunk])
        assert abs(results[0]["score"] - 1.1) < 1e-6
        assert "regulatory_korea" in results[0]["boost_reasons"]

    def test_both_kr_and_regulatory(self):
        """KR + regulatory_korea 둘 다 → 1.15 × 1.1 = 1.265."""
        chunk = _make_chunk("CB4", score=1.0, evidence_country="KR", regulatory_korea=True)
        results = apply_country_boost([chunk])
        expected = 1.0 * 1.15 * 1.1
        assert abs(results[0]["score"] - expected) < 1e-6
        assert "country_kr" in results[0]["boost_reasons"]
        assert "regulatory_korea" in results[0]["boost_reasons"]

    def test_regulatory_korea_int_1(self):
        """regulatory_korea=1 (SQLite INTEGER) → 부스팅 적용."""
        chunk = _make_chunk("CB5", score=1.0, regulatory_korea=1)
        results = apply_country_boost([chunk])
        assert abs(results[0]["score"] - 1.1) < 1e-6

    def test_no_country_no_boost(self):
        """evidence_country=None, regulatory_korea=False → 부스팅 없음."""
        chunk = _make_chunk("CB6", score=0.5, evidence_country=None, regulatory_korea=False)
        results = apply_country_boost([chunk])
        assert abs(results[0]["score"] - 0.5) < 1e-6
        assert results[0]["boost_reasons"] == []

    def test_multiple_chunks(self):
        """여러 청크 각각 독립적으로 부스팅 적용."""
        chunks = [
            _make_chunk("C1", score=1.0, evidence_country="KR"),
            _make_chunk("C2", score=1.0, evidence_country="US"),
            _make_chunk("C3", score=1.0, regulatory_korea=True),
        ]
        results = apply_country_boost(chunks)
        scores = {r["chunk_id"]: r["score"] for r in results}
        assert abs(scores["C1"] - 1.15) < 1e-6
        assert abs(scores["C2"] - 1.0) < 1e-6
        assert abs(scores["C3"] - 1.1) < 1e-6


# ════════════════════════════════════════════════════════════
#  TC-5: SQLite 모드 → NotImplementedError
# ════════════════════════════════════════════════════════════

class TestSqliteMode:
    def test_hybrid_search_raises_in_sqlite_mode(self):
        """SQLite 모드에서 hybrid_search → NotImplementedError."""
        with patch("rag_engine._is_postgres", return_value=False):
            with pytest.raises(NotImplementedError) as exc_info:
                hybrid_search("발열", top_k=3)
        assert "PostgreSQL" in str(exc_info.value)
        assert "SQLite" in str(exc_info.value)

    def test_error_message_contains_hint(self):
        """에러 메시지에 DATABASE_URL 힌트가 포함된다."""
        with patch("rag_engine._is_postgres", return_value=False):
            with pytest.raises(NotImplementedError) as exc_info:
                hybrid_search("두통", top_k=1)
        assert "DATABASE_URL" in str(exc_info.value)


# ════════════════════════════════════════════════════════════
#  TC-6: top_k 파라미터 동작
# ════════════════════════════════════════════════════════════

class TestTopK:
    """
    hybrid_search 내부 DB 호출을 mock하여 top_k 동작 검증.
    """

    def _mock_hybrid_search_internals(self, n_dense=10, n_sparse=10):
        """
        _dense_search, _sparse_search를 mock하여
        n개의 청크가 있는 상황을 시뮬레이션.
        """
        dense = [_make_chunk(f"D{i}", score=1.0 / (i + 1)) for i in range(n_dense)]
        sparse = [_make_chunk(f"S{i}", score=1.0 / (i + 1)) for i in range(n_sparse)]
        return dense, sparse

    def test_top_k_limits_results(self):
        """top_k=3이면 3개만 반환된다."""
        dense, sparse = self._mock_hybrid_search_internals(10, 10)
        with patch("rag_engine._is_postgres", return_value=True), \
             patch("rag_engine._get_embedding_provider") as mock_ep, \
             patch("rag_engine._dense_search", return_value=dense), \
             patch("rag_engine._sparse_search", return_value=sparse):
            mock_ep.return_value.embed.return_value = [[0.1] * 1536]
            results = hybrid_search("발열", top_k=3,
                                    enable_evidence_topic_check=False)
        assert len(results) == 3

    def test_top_k_1(self):
        """top_k=1이면 정확히 1개만 반환된다."""
        dense, sparse = self._mock_hybrid_search_internals(5, 5)
        with patch("rag_engine._is_postgres", return_value=True), \
             patch("rag_engine._get_embedding_provider") as mock_ep, \
             patch("rag_engine._dense_search", return_value=dense), \
             patch("rag_engine._sparse_search", return_value=sparse):
            mock_ep.return_value.embed.return_value = [[0.1] * 1536]
            results = hybrid_search("발열", top_k=1,
                                    enable_evidence_topic_check=False)
        assert len(results) == 1

    def test_top_k_larger_than_results(self):
        """top_k가 결과 수보다 크면 있는 것만 반환."""
        dense = [_make_chunk("ONLY1")]
        sparse = []
        with patch("rag_engine._is_postgres", return_value=True), \
             patch("rag_engine._get_embedding_provider") as mock_ep, \
             patch("rag_engine._dense_search", return_value=dense), \
             patch("rag_engine._sparse_search", return_value=sparse):
            mock_ep.return_value.embed.return_value = [[0.1] * 1536]
            results = hybrid_search("발열", top_k=10,
                                    enable_evidence_topic_check=False)
        assert len(results) == 1

    def test_results_sorted_by_score(self):
        """반환 결과는 score 내림차순으로 정렬된다."""
        dense = [_make_chunk(f"D{i}") for i in range(5)]
        sparse = [_make_chunk(f"S{i}") for i in range(5)]
        with patch("rag_engine._is_postgres", return_value=True), \
             patch("rag_engine._get_embedding_provider") as mock_ep, \
             patch("rag_engine._dense_search", return_value=dense), \
             patch("rag_engine._sparse_search", return_value=sparse):
            mock_ep.return_value.embed.return_value = [[0.1] * 1536]
            results = hybrid_search("발열", top_k=5,
                                    enable_evidence_topic_check=False)
        for i in range(len(results) - 1):
            assert results[i]["score"] >= results[i + 1]["score"]

    def test_empty_query_raises(self):
        """빈 질의 → ValueError 발생."""
        with patch("rag_engine._is_postgres", return_value=True):
            with pytest.raises(ValueError):
                hybrid_search("", top_k=5)

    def test_whitespace_query_raises(self):
        """공백만 있는 질의 → ValueError 발생."""
        with patch("rag_engine._is_postgres", return_value=True):
            with pytest.raises(ValueError):
                hybrid_search("   ", top_k=5)


# ════════════════════════════════════════════════════════════
#  TC-7: source_types 필터링
# ════════════════════════════════════════════════════════════

class TestSourceTypesFilter:
    def test_source_types_passed_to_dense(self):
        """source_types가 _dense_search에 전달된다."""
        with patch("rag_engine._is_postgres", return_value=True), \
             patch("rag_engine._get_embedding_provider") as mock_ep, \
             patch("rag_engine._dense_search") as mock_dense, \
             patch("rag_engine._sparse_search", return_value=[]):
            mock_ep.return_value.embed.return_value = [[0.1] * 1536]
            mock_dense.return_value = []
            hybrid_search(
                "발열", top_k=3,
                source_types=["kdca", "mfds"],
                enable_evidence_topic_check=False,
            )
        call_kwargs = mock_dense.call_args
        # source_types 인자 확인
        passed_source_types = call_kwargs[0][1]  # positional arg 2
        assert passed_source_types == ["kdca", "mfds"]

    def test_source_types_passed_to_sparse(self):
        """source_types가 _sparse_search에 전달된다."""
        with patch("rag_engine._is_postgres", return_value=True), \
             patch("rag_engine._get_embedding_provider") as mock_ep, \
             patch("rag_engine._dense_search", return_value=[]), \
             patch("rag_engine._sparse_search") as mock_sparse:
            mock_ep.return_value.embed.return_value = [[0.1] * 1536]
            mock_sparse.return_value = []
            hybrid_search(
                "발열", top_k=3,
                source_types=["kdca"],
                enable_evidence_topic_check=False,
            )
        call_kwargs = mock_sparse.call_args
        passed_source_types = call_kwargs[0][1]
        assert passed_source_types == ["kdca"]

    def test_none_source_types_no_filter(self):
        """source_types=None이면 필터 없이 전체 검색."""
        with patch("rag_engine._is_postgres", return_value=True), \
             patch("rag_engine._get_embedding_provider") as mock_ep, \
             patch("rag_engine._dense_search") as mock_dense, \
             patch("rag_engine._sparse_search", return_value=[]):
            mock_ep.return_value.embed.return_value = [[0.1] * 1536]
            mock_dense.return_value = []
            hybrid_search(
                "발열", top_k=3,
                source_types=None,
                enable_evidence_topic_check=False,
            )
        call_kwargs = mock_dense.call_args
        passed_source_types = call_kwargs[0][1]
        assert passed_source_types is None


# ════════════════════════════════════════════════════════════
#  TC-통합: @pytest.mark.integration (실제 PostgreSQL 필요)
# ════════════════════════════════════════════════════════════

_needs_postgres = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — PostgreSQL integration tests skipped",
)
_needs_openai = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set — integration tests skipped",
)


@pytest.mark.integration
@_needs_postgres
@_needs_openai
class TestIntegration:
    """
    실제 PostgreSQL + pgvector 환경에서만 실행.
    사전 조건:
      - DATABASE_URL 환경변수 설정
      - OPENAI_API_KEY 환경변수 설정
      - kb_chunks에 시드 데이터 존재 (T3 ingest 완료)
    """

    def test_hybrid_search_returns_results(self):
        """발열 질의 → 3개 청크, 첫 점수 0.5 이상."""
        results = hybrid_search("발열", top_k=3)
        assert len(results) == 3
        assert results[0]["score"] >= 0.5

    def test_hybrid_search_emergency_boost(self):
        """의식 변화 동반 고열 → red_flag boost로 응급 청크 상위 노출."""
        results = hybrid_search("의식 변화 동반 고열", top_k=5)
        # 최소 1개 결과가 있어야 함
        assert len(results) >= 1
        # 첫 번째 결과 점수가 RRF 기본보다 높을 수 있음 (boost 적용 시)
        assert results[0]["score"] > 0

    def test_result_fields_complete(self):
        """반환 결과에 필수 필드가 모두 있다."""
        results = hybrid_search("두통", top_k=1)
        if results:
            r = results[0]
            for field in ["chunk_id", "document_id", "content", "score",
                          "source_id", "evidence_level", "boost_reasons"]:
                assert field in r, f"필드 누락: {field}"

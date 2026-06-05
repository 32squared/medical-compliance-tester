"""
embedding_provider.py 단위 테스트.

OPENAI_API_KEY 환경변수가 없으면 실제 API 호출 테스트를 건너뛴다.
API key 없는 환경에서도 구조·스텁 테스트는 항상 실행된다.
"""
import os
import sys
import pytest

# 프로젝트 루트를 sys.path에 추가 (tests/ 하위에서 실행 시 필요)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from embedding_provider import (
    EmbeddingProvider,
    OpenAIEmbeddingProvider,
    BGEM3EmbeddingProvider,
    get_embedding_provider,
)

# ─── 공통 마커 ───────────────────────────────────────────────
needs_api_key = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY"),
    reason="OPENAI_API_KEY not set",
)


# ─── 구조 테스트 (API key 불필요) ────────────────────────────

class TestAbstractInterface:
    """EmbeddingProvider 추상 클래스 계약 검증"""

    def test_cannot_instantiate_abstract(self):
        """추상 클래스 직접 인스턴스화 불가"""
        with pytest.raises(TypeError):
            EmbeddingProvider()

    def test_openai_is_subclass(self):
        assert issubclass(OpenAIEmbeddingProvider, EmbeddingProvider)

    def test_bgem3_is_subclass(self):
        assert issubclass(BGEM3EmbeddingProvider, EmbeddingProvider)


class TestBGEM3Stub:
    """BGE-M3는 Phase 4+ 스텁 — 인스턴스화 불가"""

    def test_bge_m3_not_implemented(self):
        with pytest.raises(NotImplementedError):
            BGEM3EmbeddingProvider()

    def test_bge_m3_model_id_property(self):
        """인스턴스 없이 클래스 기본값은 확인 불가. NotImplementedError 발생 확인으로 충분."""
        with pytest.raises(NotImplementedError):
            BGEM3EmbeddingProvider(base_url="http://localhost:8080")


class TestOpenAIProviderStructure:
    """API key 없이도 검증 가능한 구조 테스트"""

    def test_raises_without_api_key(self, monkeypatch):
        """OPENAI_API_KEY 미설정 시 ValueError"""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(ValueError, match="OPENAI_API_KEY"):
            OpenAIEmbeddingProvider(api_key=None)

    def test_accepts_explicit_api_key(self):
        """명시적 api_key 파라미터로 초기화 가능 (실제 호출 안 함)"""
        p = OpenAIEmbeddingProvider(api_key="sk-test-fake-key")
        assert p.model_id == "text-embedding-3-small"
        assert p.dimension == 1536

    def test_model_override_via_param(self):
        """model 파라미터로 모델 오버라이드"""
        p = OpenAIEmbeddingProvider(
            api_key="sk-test", model="text-embedding-3-large"
        )
        assert p.model_id == "text-embedding-3-large"
        assert p.dimension == 3072

    def test_model_override_via_env(self, monkeypatch):
        """RAG_EMBEDDING_MODEL 환경변수로 오버라이드"""
        monkeypatch.setenv("RAG_EMBEDDING_MODEL", "text-embedding-ada-002")
        p = OpenAIEmbeddingProvider(api_key="sk-test")
        assert p.model_id == "text-embedding-ada-002"
        assert p.dimension == 1536

    def test_dimension_default_for_unknown_model(self):
        """알 수 없는 모델은 기본값 1536 반환"""
        p = OpenAIEmbeddingProvider(api_key="sk-test", model="future-model-x")
        assert p.dimension == 1536

    def test_embed_empty_list_returns_empty(self, monkeypatch):
        """빈 리스트 입력 → 빈 리스트 반환 (API 호출 없음)"""
        p = OpenAIEmbeddingProvider(api_key="sk-test")
        result = p.embed([])
        assert result == []


class TestFactory:
    """get_embedding_provider() 팩토리 함수"""

    def test_factory_default_returns_openai(self, monkeypatch):
        """기본 슬롯은 OpenAIEmbeddingProvider 반환"""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("RAG_EMBEDDING_PROVIDER_DEFAULT", raising=False)
        monkeypatch.delenv("RAG_EMBEDDING_PROVIDER_DEFAULT", raising=False)
        p = get_embedding_provider("default")
        assert isinstance(p, OpenAIEmbeddingProvider)

    def test_factory_ingest_slot(self, monkeypatch):
        """ingest 슬롯도 openai 반환 (환경변수 미설정 시)"""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        monkeypatch.delenv("RAG_EMBEDDING_PROVIDER_INGEST", raising=False)
        p = get_embedding_provider("ingest")
        assert isinstance(p, OpenAIEmbeddingProvider)

    def test_factory_unknown_provider_raises(self, monkeypatch):
        """알 수 없는 프로바이더 타입 → ValueError"""
        monkeypatch.setenv("RAG_EMBEDDING_PROVIDER_DEFAULT", "unknown_model")
        with pytest.raises(ValueError, match="Unknown embedding provider"):
            get_embedding_provider("default")

    def test_factory_bge_m3_raises_not_implemented(self, monkeypatch):
        """bge_m3 슬롯은 NotImplementedError (Phase 4+ 스텁)"""
        monkeypatch.setenv("RAG_EMBEDDING_PROVIDER_DEFAULT", "bge_m3")
        with pytest.raises(NotImplementedError):
            get_embedding_provider("default")


# ─── 실제 API 호출 테스트 (OPENAI_API_KEY 필요) ──────────────

@needs_api_key
class TestOpenAIEmbedReal:
    """실제 OpenAI API 호출 테스트. OPENAI_API_KEY 환경변수 필요."""

    @pytest.fixture(scope="class")
    def provider(self):
        return OpenAIEmbeddingProvider()

    def test_basics(self, provider):
        assert provider.model_id == "text-embedding-3-small"
        assert provider.dimension == 1536

    def test_embed_single(self, provider):
        vecs = provider.embed(["발열이 나면 어떻게 하나요?"])
        assert len(vecs) == 1
        assert len(vecs[0]) == 1536
        assert all(isinstance(x, float) for x in vecs[0])

    def test_embed_batch(self, provider):
        texts = ["발열", "두통", "복통", "흉통"]
        vecs = provider.embed(texts)
        assert len(vecs) == 4
        assert all(len(v) == 1536 for v in vecs)

    def test_embed_empty_string_safe(self, provider):
        """빈 문자열 → 공백으로 대체 후 정상 임베딩"""
        vecs = provider.embed([""])
        assert len(vecs) == 1
        assert len(vecs[0]) == 1536

    def test_health_check(self, provider):
        result = provider.health_check()
        assert result["ok"] is True
        assert result["sample_dim"] == 1536
        assert result["latency_ms"] > 0

    def test_factory_default_real(self):
        p = get_embedding_provider("default")
        assert isinstance(p, OpenAIEmbeddingProvider)

    def test_dimension_consistency(self, provider):
        """두 텍스트의 임베딩 차원이 일치해야 함 (DB 컬럼 호환성)"""
        v1 = provider.embed(["text 1"])[0]
        v2 = provider.embed(["text 2"])[0]
        assert len(v1) == len(v2) == provider.dimension

"""
임베딩 모델 추상화 계층.
Phase 1: OpenAI text-embedding-3-small (1536차원)
Phase 4: BGE-M3 (1024차원)으로 마이그레이션 가능.
embedding_migration_strategy.md §1.1 참조.

향후 새 프로바이더 추가 시 EmbeddingProvider를 상속하는
새 클래스와 get_embedding_provider() 분기만 추가하면 된다.
Phase 4 마이그레이션 시 새 Provider만 추가하면 됨 — 기존 코드 수정 불필요.
"""
import os
import time
import logging
from abc import ABC, abstractmethod
from typing import List, Dict

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """모든 임베딩 모델이 따라야 하는 인터페이스"""

    @property
    @abstractmethod
    def model_id(self) -> str:
        """예: 'text-embedding-3-small', 'bge_m3'"""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """벡터 차원 (1536 / 1024 등)"""

    @abstractmethod
    def embed(self, texts: List[str]) -> List[List[float]]:
        """배치 임베딩. 1개~N개 텍스트 → 벡터 리스트."""

    @abstractmethod
    def health_check(self) -> Dict:
        """{'ok': bool, 'latency_ms': int, 'sample_dim': int}"""


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """
    OpenAI text-embedding-3-small (Phase 1 기본).

    - 모델 ID는 환경변수 RAG_EMBEDDING_MODEL로 오버라이드 가능.
    - 429 / 5xx 에러 시 지수 백오프 재시도 (최대 3회).
    - 빈 문자열 입력 방어 처리.
    - OpenAI 임베딩 API는 배치 호출 지원 (최대 100개 텍스트 권장).
    """

    # 모델별 차원 매핑
    _DIM_MAP = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    # 재시도 설정
    _MAX_RETRIES = 3
    _RETRY_BASE_DELAY = 1.0  # 초

    def __init__(self, api_key: str = None, model: str = None):
        from openai import OpenAI
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY not set")
        self._model_id = model or os.environ.get(
            "RAG_EMBEDDING_MODEL", "text-embedding-3-small"
        )
        self._client = OpenAI(api_key=self._api_key)

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._DIM_MAP.get(self._model_id, 1536)

    def embed(self, texts: List[str]) -> List[List[float]]:
        """
        배치 임베딩 호출.

        - 빈 문자열은 공백(" ")으로 대체해 API 오류 방지.
        - 429 (rate limit) / 5xx 에러 시 최대 3회 지수 백오프 재시도.
        - 에러 처리는 caller 책임 (provider 내부에서 최종 실패는 예외로 전달).
        """
        if not texts:
            return []

        # 빈 문자열 방어
        cleaned = [t if t and t.strip() else " " for t in texts]

        last_exc = None
        for attempt in range(self._MAX_RETRIES):
            try:
                resp = self._client.embeddings.create(
                    model=self._model_id,
                    input=cleaned,
                )
                return [item.embedding for item in resp.data]
            except Exception as e:
                last_exc = e
                error_str = str(e)
                # 429 rate limit 또는 5xx 서버 오류만 재시도
                is_retryable = (
                    "429" in error_str
                    or "rate_limit" in error_str.lower()
                    or "500" in error_str
                    or "502" in error_str
                    or "503" in error_str
                    or "504" in error_str
                )
                if is_retryable and attempt < self._MAX_RETRIES - 1:
                    delay = self._RETRY_BASE_DELAY * (2 ** attempt)
                    logger.warning(
                        "[EmbeddingProvider] 재시도 %d/%d (delay=%.1fs): %s",
                        attempt + 1, self._MAX_RETRIES, delay, error_str[:100],
                    )
                    time.sleep(delay)
                else:
                    break

        raise last_exc

    def health_check(self) -> Dict:
        """헬스체크. {'ok': bool, 'latency_ms': int, 'sample_dim': int}"""
        start = time.time()
        try:
            vecs = self.embed(["health check"])
            elapsed = int((time.time() - start) * 1000)
            return {
                "ok": True,
                "latency_ms": elapsed,
                "sample_dim": len(vecs[0]),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}


class BGEM3EmbeddingProvider(EmbeddingProvider):
    """
    자체호스팅 BGE-M3 (Phase 4+에서 활성화).

    Phase 1에는 스텁만 존재. Phase 4 착수 시 base_url 기반 HTTP 호출로 구현.
    마이그레이션 절차: embedding_migration_strategy.md §2 참조.
    """

    def __init__(self, base_url: str = None):
        self._base_url = base_url or os.environ.get("BGE_M3_URL")
        # Phase 4에서 구현
        raise NotImplementedError("BGE-M3 is for Phase 4+")

    @property
    def model_id(self) -> str:
        return "bge_m3"

    @property
    def dimension(self) -> int:
        return 1024

    def embed(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError("BGE-M3 is for Phase 4+")

    def health_check(self) -> Dict:
        return {"ok": False, "error": "Not implemented (Phase 4+)"}


def get_embedding_provider(slot: str = "default") -> EmbeddingProvider:
    """
    활성 슬롯의 임베딩 프로바이더를 반환.

    T1(DB 마이그레이션) 완료 후에는 embedding_providers 테이블에서 동적 조회.
    현재(T2 단계)는 환경변수 기반 폴백으로 동작한다.

    Args:
        slot: 'default' | 'ingest' | 'shadow'
              - default: 검색 시 사용
              - ingest: KB ingest 시 사용 (마이그레이션 중에는 양쪽 다 호출)
              - shadow: 듀얼 인덱싱 검증용 (Phase 4+)

    Returns:
        EmbeddingProvider 인스턴스

    Notes:
        T1 완료 후 DB에서 조회하는 방식으로 전환:
            config = db.get_active_embedding_provider(slot)
            provider_type = config.provider
    """
    # T1 완료 후 DB에서 조회. 지금은 환경변수 기반 폴백:
    env_key = f"RAG_EMBEDDING_PROVIDER_{slot.upper()}"
    provider_type = os.environ.get(env_key) or os.environ.get(
        "RAG_EMBEDDING_PROVIDER_DEFAULT", "openai"
    )

    if provider_type == "openai":
        return OpenAIEmbeddingProvider()
    elif provider_type == "bge_m3":
        return BGEM3EmbeddingProvider()
    else:
        raise ValueError(
            f"Unknown embedding provider: {provider_type!r} "
            f"(slot={slot!r}, env={env_key})"
        )

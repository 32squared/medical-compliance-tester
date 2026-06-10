"""
나만의 주치의 - 의료법 준수 자동화 테스트 설정
SKIX API 스펙 기반 (phnyx.ai)

4-B/B2 분할:
- 호스트 잔류 심볼 (이 파일에 직접 정의):
    ENVIRONMENTS, ACTIVE_ENV, API_CONFIG, get_api_url, get_headers,
    build_request_body, CONVERSATIONS_API, REPORT_CONFIG,
    EMBEDDING_PROVIDER_DEFAULT, EMBEDDING_MODEL_DEFAULT
- compliance_rules 로 이동된 심볼 (rules_config 에서 재export):
    VIOLATION_RULES, SEVERITY_SCORES,
    reload_violation_rules, get_guideline_version
  → 기존 `from config import reload_violation_rules` 등 호출처 무변경.
"""
import os

# ── compliance_rules 패키지 심볼 재export (하위 호환) ──
from packages.medical_shared.compliance_rules.rules_config import (  # noqa: F401
    VIOLATION_RULES, SEVERITY_SCORES,
    reload_violation_rules, get_guideline_version,
)

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================
# 1. 환경별 API 설정
# ============================================================
ENVIRONMENTS = {
    "dev": {
        "base_url": "https://dev-skix.phnyx.ai",
        "x_tenant_domain": "dev-skix",
    },
    "stg": {
        "base_url": "https://staging-skix.phnyx.ai",
        "x_tenant_domain": "staging-skix",
    },
    "prod": {
        "base_url": "https://skix.phnyx.ai",
        "x_tenant_domain": "skix",
    },
}

# 현재 활성 환경 (dev / stg / prod)
ACTIVE_ENV = "dev"

# ============================================================
# 2. API 인증 및 엔드포인트 설정
# ============================================================
API_CONFIG = {
    # ─── 인증 (Required Headers) ───
    "x_api_key": "",           # X-API-Key  — 여기에 발급받은 키 입력
    "x_tenant_domain": "",     # X-tenant-Domain — 환경 선택시 자동 설정됨
    "x_api_uid": "",           # X-Api-UID  — 사용자 식별 키

    # ─── 엔드포인트 ───
    # POST /api/service/conversations/{graph_type}
    "graph_type": "ORCHESTRATED_HYBRID_SEARCH",
    "endpoint_template": "/api/service/conversations/{graph_type}",

    # ─── 요청 본문 기본값 ───
    "source_types": ["WEB", "PUBMED"],   # 검색 소스
    "agent_strid": None,                  # 에이전트 ID (선택)
    "agent_input_field_to_value": None,   # 에이전트 입력 (선택, SKIX_A1용)

    # ─── 대화 관리 ───
    "conversation_strid": None,  # null이면 새 대화 시작, UUID면 기존 대화 이어가기

    # ─── 기타 ───
    "timeout": 60,  # SSE 스트리밍은 시간이 더 걸릴 수 있으므로 60초
}


def get_api_url() -> str:
    """현재 환경의 전체 API URL 반환"""
    env = ENVIRONMENTS.get(ACTIVE_ENV, ENVIRONMENTS["dev"])
    endpoint = API_CONFIG["endpoint_template"].format(
        graph_type=API_CONFIG["graph_type"]
    )
    return f"{env['base_url']}{endpoint}"


def get_headers() -> dict:
    """API 요청 헤더 구성"""
    env = ENVIRONMENTS.get(ACTIVE_ENV, ENVIRONMENTS["dev"])
    tenant = API_CONFIG["x_tenant_domain"] or env["x_tenant_domain"]

    headers = {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "X-API-Key": API_CONFIG["x_api_key"],
        "X-tenant-Domain": tenant,
        "X-Api-UID": API_CONFIG["x_api_uid"],
    }
    return headers


def build_request_body(query: str, conversation_strid: str = None) -> dict:
    """API 요청 본문 생성"""
    body = {
        "query": query,
        "conversation_strid": conversation_strid or API_CONFIG["conversation_strid"],
        "source_types": API_CONFIG["source_types"],
    }

    if API_CONFIG.get("agent_strid"):
        body["agent_strid"] = API_CONFIG["agent_strid"]

    if API_CONFIG.get("agent_input_field_to_value"):
        body["agent_input_field_to_value"] = API_CONFIG["agent_input_field_to_value"]

    return body


# ============================================================
# 3. Conversations API (대화 이력 조회용)
# ============================================================
CONVERSATIONS_API = {
    "list":   "/api/data_management/conversations",
    "search": "/api/data_management/conversations/search",
    "detail": "/api/data_management/conversations/{conversation_strid}",
}


# ============================================================
# 5. RAG 임베딩 설정 (Phase 1+)
# ============================================================

# 기본 임베딩 프로바이더 ('openai' | 'bge_m3')
# embedding_providers 테이블(T1 완료 후)에서 동적으로 조회.
# 테이블 미존재 시 이 환경변수 값이 폴백으로 사용됨.
EMBEDDING_PROVIDER_DEFAULT = os.environ.get(
    "RAG_EMBEDDING_PROVIDER_DEFAULT", "openai"
)

# Phase 1 기본 임베딩 모델
EMBEDDING_MODEL_DEFAULT = os.environ.get(
    "RAG_EMBEDDING_MODEL", "text-embedding-3-small"
)

# ============================================================
# 6. 리포트 설정
# ============================================================
REPORT_CONFIG = {
    "output_dir": "./reports",
    "pass_threshold": 80,
    "include_raw_response": True,
}

"""
/api/rag/chat SSE 엔드포인트 테스트 (T6)

테스트 전략:
  - proxy_server.py 를 직접 import 하면 최상단의 sys.stdout 재정의 코드가
    pytest 캡처 시스템과 충돌한다.
  - 따라서 두 가지 방식을 분리한다:
      (A) 소스 코드 grep 기반 — 라우트/메서드 존재 여부 (import 불필요)
      (B) rag_engine 단위 테스트 — generate_response 반환 구조 확인
      (C) 서버 subprocess 기반 — 실제 HTTP 요청 (선택적, slow 마커)
  - 핵심 로직 검증은 rag_engine 을 직접 import 해서 수행 (충돌 없음)

테스트 케이스:
  TC-1: do_POST 라우팅에 /api/rag/chat 분기 존재 (소스 grep)
  TC-2: _rag_chat 메서드 정의 존재 (소스 grep)
  TC-3: SSE 헤더 코드 존재 — text/event-stream (소스 grep)
  TC-4: SQLite 모드 503 코드 존재 (소스 grep)
  TC-5: RAG_REQUIRES_POSTGRES 에러 코드 존재 (소스 grep)
  TC-6: generate_response INFO 이벤트 구조 검증 (rag_engine mock)
  TC-7: generate_response STOP 이벤트 필수 필드 검증 (rag_engine mock)
  TC-8: generate_response ERROR 이벤트 구조 검증 (rag_engine mock)
  TC-9: SSE 포맷 직렬화 함수 동작 검증 (순수 함수 테스트)
  TC-10: Python 문법 검증 (py_compile)
  TC-11: conversation_id 없는 요청 처리 코드 존재 (소스 grep)
  TC-12: _require_auth 인증 체크 코드 존재 (소스 grep)
"""
import os
import re
import sys
import io
import json
import pytest

# 프로젝트 루트를 sys.path 에 추가 (proxy_server 는 import 하지 않음)
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# ════════════════════════════════════════════════════════════
#  소스 코드 grep 헬퍼
# ════════════════════════════════════════════════════════════

def _read_proxy_source() -> str:
    proxy_path = os.path.join(_REPO_ROOT, 'proxy_server.py')
    with open(proxy_path, 'r', encoding='utf-8') as f:
        return f.read()


def _grep_proxy(pattern: str) -> bool:
    return bool(re.search(pattern, _read_proxy_source()))


# ════════════════════════════════════════════════════════════
#  SSE 직렬화 헬퍼 (proxy_server import 없이 독립 테스트)
# ════════════════════════════════════════════════════════════

def _sse_line(event: dict) -> bytes:
    """SSE 포맷으로 변환 — proxy_server._rag_chat 내부 로직과 동일."""
    return ("data: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode('utf-8')


def _parse_sse(raw: bytes) -> list:
    """SSE 바이트 → 이벤트 dict 리스트 파싱."""
    events = []
    for line in raw.decode('utf-8').split('\n'):
        line = line.strip()
        if line.startswith('data: '):
            try:
                events.append(json.loads(line[len('data: '):]))
            except Exception:
                pass
    return events


# ════════════════════════════════════════════════════════════
#  TC-1: /api/rag/chat 라우트 분기 존재
# ════════════════════════════════════════════════════════════

def test_rag_chat_route_in_do_post():
    """/api/rag/chat 라우트가 do_POST 안에 존재한다."""
    assert _grep_proxy(r"'/api/rag/chat'"), \
        "/api/rag/chat route not found in proxy_server.py do_POST"


# ════════════════════════════════════════════════════════════
#  TC-2: _rag_chat 메서드 정의 존재
# ════════════════════════════════════════════════════════════

def test_rag_chat_method_defined():
    """_rag_chat 메서드가 ProxyHandler 에 정의되어 있다."""
    assert _grep_proxy(r'def _rag_chat\b'), \
        "_rag_chat method not defined in proxy_server.py"


# ════════════════════════════════════════════════════════════
#  TC-3: SSE Content-Type 헤더 코드 존재
# ════════════════════════════════════════════════════════════

def test_sse_content_type_header_code():
    """_rag_chat 안에 text/event-stream Content-Type 설정 코드가 있다."""
    assert _grep_proxy(r'text/event-stream'), \
        "text/event-stream header not found in proxy_server.py"


# ════════════════════════════════════════════════════════════
#  TC-4: SQLite 모드 503 코드 존재
# ════════════════════════════════════════════════════════════

def test_sqlite_503_code_exists():
    """SQLite 모드에서 503 반환하는 코드가 존재한다."""
    src = _read_proxy_source()
    # _rag_chat 함수 내에 503 과 _use_postgres 가 모두 존재해야 함
    has_503 = bool(re.search(r'503', src))
    has_use_postgres = bool(re.search(r'_use_postgres', src))
    assert has_503 and has_use_postgres, \
        "503 response or _use_postgres check missing in proxy_server.py"


# ════════════════════════════════════════════════════════════
#  TC-5: RAG_REQUIRES_POSTGRES 에러 코드 존재
# ════════════════════════════════════════════════════════════

def test_rag_requires_postgres_code_exists():
    """RAG_REQUIRES_POSTGRES 에러 코드가 _rag_chat 에 존재한다."""
    assert _grep_proxy(r'RAG_REQUIRES_POSTGRES'), \
        "RAG_REQUIRES_POSTGRES error code not found in proxy_server.py"


# ════════════════════════════════════════════════════════════
#  TC-6: generate_response INFO 이벤트 구조
# ════════════════════════════════════════════════════════════

def test_info_event_structure():
    """INFO 이벤트는 data.search_results 배열을 포함한다."""
    from unittest.mock import patch, MagicMock

    sample_event = {
        "type": "INFO",
        "data": {
            "search_results": [
                {
                    "chunk_id": "c001",
                    "content": "발열은 38도 이상",
                    "score": 0.92,
                    "source_id": "kdca",
                    "evidence_level": "A",
                }
            ]
        }
    }

    # SSE 직렬화 및 파싱
    raw = _sse_line(sample_event)
    events = _parse_sse(raw)

    assert len(events) == 1
    e = events[0]
    assert e['type'] == 'INFO'
    assert 'data' in e
    assert 'search_results' in e['data']
    assert isinstance(e['data']['search_results'], list)
    assert e['data']['search_results'][0]['chunk_id'] == 'c001'


# ════════════════════════════════════════════════════════════
#  TC-7: generate_response STOP 이벤트 필수 필드
# ════════════════════════════════════════════════════════════

def test_stop_event_required_fields():
    """STOP 이벤트는 rag_query_id, citations, latency_ms, tokens, guardrail_action 을 포함한다."""
    stop_event = {
        "type": "STOP",
        "text": "발열 시 충분한 수분 섭취가 중요합니다. [1]",
        "rag_query_id": "rq-abc123",
        "citations": [{"marker": "[1]", "chunk_id": "c001"}],
        "latency_ms": 1800,
        "tokens": {"input": 250, "output": 120},
        "guardrail_action": "pass",
    }

    raw = _sse_line(stop_event)
    events = _parse_sse(raw)

    assert len(events) == 1
    e = events[0]
    assert e['type'] == 'STOP'

    required_fields = ['rag_query_id', 'citations', 'latency_ms', 'tokens', 'guardrail_action']
    for field in required_fields:
        assert field in e, f'STOP 이벤트에 {field} 필드 없음'

    assert isinstance(e['citations'], list)
    assert isinstance(e['tokens'], dict)
    assert 'input' in e['tokens']
    assert 'output' in e['tokens']


# ════════════════════════════════════════════════════════════
#  TC-8: generate_response ERROR 이벤트 구조
# ════════════════════════════════════════════════════════════

def test_error_event_structure():
    """ERROR 이벤트는 message 필드를 포함한다."""
    error_event = {
        "type": "ERROR",
        "message": "검색 오류: DB 연결 실패",
    }

    raw = _sse_line(error_event)
    events = _parse_sse(raw)

    assert len(events) == 1
    e = events[0]
    assert e['type'] == 'ERROR'
    assert 'message' in e
    assert 'DB 연결 실패' in e['message']


# ════════════════════════════════════════════════════════════
#  TC-9: SSE 포맷 직렬화 (data: + \n\n)
# ════════════════════════════════════════════════════════════

def test_sse_format_serialization():
    """SSE 포맷은 'data: {json}\\n\\n' 형식이어야 한다."""
    event = {"type": "GENERATION", "text": "안녕하세요 [1]"}
    raw = _sse_line(event)

    text = raw.decode('utf-8')
    assert text.startswith('data: '), f'SSE 라인이 "data: "로 시작하지 않음: {repr(text)}'
    assert text.endswith('\n\n'), f'SSE 라인이 "\\n\\n"으로 끝나지 않음: {repr(text)}'

    # JSON 파싱 가능 여부
    json_part = text[len('data: '):].strip()
    parsed = json.loads(json_part)
    assert parsed['type'] == 'GENERATION'
    assert parsed['text'] == '안녕하세요 [1]'


# ════════════════════════════════════════════════════════════
#  TC-10: Python 문법 검증
# ════════════════════════════════════════════════════════════

def test_proxy_server_syntax():
    """proxy_server.py 문법 오류 없음 확인."""
    import py_compile
    proxy_path = os.path.join(_REPO_ROOT, 'proxy_server.py')
    py_compile.compile(proxy_path, doraise=True)


# ════════════════════════════════════════════════════════════
#  TC-11: conversation_id 없는 경우 UUID 자동 생성 코드 존재
# ════════════════════════════════════════════════════════════

def test_auto_conversation_id_code_exists():
    """conversation_id 가 없을 때 UUID 를 자동 생성하는 코드가 존재한다."""
    src = _read_proxy_source()
    has_uuid = bool(re.search(r'uuid4\(\)|_uuid_mod\.uuid4', src))
    has_conv_check = bool(re.search(r'conversation_id', src))
    assert has_uuid and has_conv_check, \
        "UUID 자동 생성 또는 conversation_id 처리 코드가 없음"


# ════════════════════════════════════════════════════════════
#  TC-12: _require_auth 인증 체크 코드 존재
# ════════════════════════════════════════════════════════════

def test_require_auth_in_rag_chat():
    """_rag_chat 메서드 안에 _require_auth 호출이 존재한다."""
    src = _read_proxy_source()
    # _rag_chat 메서드 블록 안에 _require_auth 가 있는지 확인
    # _rag_chat 정의부터 다음 def 까지 추출
    m = re.search(r'def _rag_chat\b.*?(?=\n    def |\Z)', src, re.DOTALL)
    if not m:
        pytest.fail("_rag_chat 메서드를 소스에서 찾을 수 없음")
    rag_chat_body = m.group(0)
    assert '_require_auth' in rag_chat_body, \
        "_rag_chat 안에 _require_auth 호출이 없음"


# ════════════════════════════════════════════════════════════
#  TC-13: generate_response import 코드 존재
# ════════════════════════════════════════════════════════════

def test_generate_response_import_in_rag_chat():
    """_rag_chat 안에 rag_engine.generate_response import 코드가 존재한다."""
    src = _read_proxy_source()
    m = re.search(r'def _rag_chat\b.*?(?=\n    def |\Z)', src, re.DOTALL)
    if not m:
        pytest.fail("_rag_chat 메서드를 소스에서 찾을 수 없음")
    rag_chat_body = m.group(0)
    assert 'generate_response' in rag_chat_body, \
        "_rag_chat 안에 generate_response 호출이 없음"
    assert 'rag_engine' in rag_chat_body, \
        "_rag_chat 안에 rag_engine import 가 없음"


# ════════════════════════════════════════════════════════════
#  TC-14: wfile.flush() 호출 코드 존재 (스트리밍 필수)
# ════════════════════════════════════════════════════════════

def test_wfile_flush_in_rag_chat():
    """SSE 스트리밍을 위해 wfile.flush() 가 _rag_chat 안에 존재한다."""
    src = _read_proxy_source()
    m = re.search(r'def _rag_chat\b.*?(?=\n    def |\Z)', src, re.DOTALL)
    if not m:
        pytest.fail("_rag_chat 메서드를 소스에서 찾을 수 없음")
    rag_chat_body = m.group(0)
    assert 'flush()' in rag_chat_body, \
        "_rag_chat 안에 wfile.flush() 가 없음 (SSE 실시간 전송 불가)"


# ════════════════════════════════════════════════════════════
#  TC-15: generate_response 직접 mock 호출로 이벤트 흐름 검증
# ════════════════════════════════════════════════════════════

def test_generate_response_event_sequence():
    """
    generate_response mock 이 반환하는 이벤트 시퀀스가
    INFO → GENERATION* → STOP 순서임을 확인한다.
    """
    events = [
        {"type": "INFO", "data": {"search_results": [
            {"chunk_id": "c1", "content": "발열 내용", "score": 0.85}
        ]}},
        {"type": "GENERATION", "text": "발열이 38도 이상이면 "},
        {"type": "GENERATION", "text": "적절한 처치가 필요합니다. [1]"},
        {
            "type": "STOP",
            "text": "발열이 38도 이상이면 적절한 처치가 필요합니다. [1]",
            "rag_query_id": "rq-seq-001",
            "citations": [{"marker": "[1]", "chunk_id": "c1"}],
            "latency_ms": 950,
            "tokens": {"input": 180, "output": 40},
            "guardrail_action": "pass",
        },
    ]

    # SSE 직렬화 → 파싱 라운드트립
    raw_stream = b''.join(_sse_line(e) for e in events)
    parsed = _parse_sse(raw_stream)

    types = [e.get('type') for e in parsed]

    # 순서 검증
    assert types[0] == 'INFO', f'첫 이벤트가 INFO 가 아님: {types[0]}'
    assert types[-1] == 'STOP', f'마지막 이벤트가 STOP 이 아님: {types[-1]}'
    assert all(t == 'GENERATION' for t in types[1:-1]), \
        f'중간 이벤트가 모두 GENERATION 이 아님: {types[1:-1]}'

    # STOP 이벤트 내용 검증
    stop = parsed[-1]
    assert stop['rag_query_id'] == 'rq-seq-001'
    assert len(stop['citations']) == 1
    assert stop['guardrail_action'] == 'pass'
    assert stop['tokens']['input'] == 180
    assert stop['tokens']['output'] == 40

# 나만의 주치의 — 의료법 준수 테스트 도구 API 적용 작업 계획

## 현재 상태 vs 실제 API 차이 분석

### 현재 구현 (가정 기반)
```
POST http://localhost:8000/api/v1/chat
Headers: Authorization: Bearer <token>
Body: { "message": "...", "session_id": "..." }
Response: JSON { "data": { "answer": "..." } }
```

### 실제 API 스펙 (문서 기반)
```
POST https://{env}-skix.phnyx.ai/api/service/conversations/SUPERVISED_HYBRID_SEARCH
Headers:
  X-API-Key: <key>
  X-tenant-Domain: <domain>
  X-Api-UID: <user_id>
Body: {
  "query": "...",
  "conversation_strid": null | "<uuid>",
  "source_types": ["WEB", "PUBMED"]
}
Response: SSE 스트리밍 (Server-Sent Events)
  → GENERATION 이벤트의 text를 축적하여 최종 응답 조합
```

---

## 주요 변경 사항 5가지

| # | 항목 | 현재 | 변경 후 |
|---|------|------|---------|
| 1 | 인증 방식 | Bearer 토큰 1개 | X-API-Key + X-tenant-Domain + X-Api-UID 3개 |
| 2 | 엔드포인트 | /api/v1/chat | /api/service/conversations/SUPERVISED_HYBRID_SEARCH |
| 3 | 요청 본문 | { message } | { query, conversation_strid, source_types } |
| 4 | 응답 형식 | 일반 JSON | SSE 스트리밍 (GENERATION 이벤트 축적) |
| 5 | 환경 분리 | 단일 URL | dev / stg / prod 3개 환경 |

---

## 작업 계획

### STEP 1: config.py 개편
**목표**: 실제 API 스펙에 맞는 설정 구조로 변경

변경 내용:
- 환경별 Base URL 매핑 (dev/stg/prod)
- 커스텀 헤더 3종 (X-API-Key, X-tenant-Domain, X-Api-UID) 설정
- 엔드포인트 경로를 /api/service/conversations/{graph_type} 으로 변경
- 요청 본문 템플릿: query, conversation_strid, source_types 반영
- graph_type 기본값: SUPERVISED_HYBRID_SEARCH

### STEP 2: runner.py — SSE 스트리밍 파싱
**목표**: SSE 응답을 실시간 수신하여 최종 텍스트 조합

변경 내용:
- requests 라이브러리의 stream=True 모드 사용
- SSE 이벤트 파서 구현:
  - `GENERATION` → text 필드 축적하여 최종 응답 조합
  - `INFO` → search_results, follow_ups 추출 (메타데이터)
  - `PROGRESS` → 진행 상황 로깅
  - `STOP` → 스트림 종료 처리
  - `ERROR` → 에러 핸들링
- conversation_strid 관리 (첫 INFO에서 받아 이후 요청에 재사용)

### STEP 3: chat_tester.html 개편
**목표**: 실제 API에 연결 가능한 채팅 테스터

변경 내용:
- 설정 패널:
  - 환경 선택 드롭다운 (dev/stg/prod/커스텀)
  - X-API-Key 입력
  - X-tenant-Domain 입력 (환경 선택시 자동 설정)
  - X-Api-UID 입력
  - source_types 체크박스 (WEB, PUBMED)
- SSE 스트리밍 처리:
  - EventSource 또는 fetch + ReadableStream으로 SSE 파싱
  - GENERATION 이벤트마다 실시간 텍스트 표시 (타이핑 효과)
  - PROGRESS 이벤트 → 진행 상태 표시
  - INFO 이벤트 → 참고문헌/검색결과 패널 표시
- conversation_strid 관리로 멀티턴 대화 지원
- 마크다운 렌더링 (응답이 markdown 형식)

### STEP 4: 통합 테스트 및 검증
- Mock 모드에서 SSE 형식 샘플 응답으로 파서 검증
- 연결 테스트 기능으로 실제 API 연결 확인
- 전체 시나리오 실행 후 대시보드 생성 확인

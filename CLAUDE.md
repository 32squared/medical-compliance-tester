# 나만의 주치의 — 의료법 준수 테스트 도구

## 프로젝트 개요
AI 건강상담 서비스 '나만의 주치의'의 의료법 준수 여부를 테스트하는 도구.
의사 테스터가 AI와 대화하고, 답변 품질을 평가하며, 시나리오를 관리한다.

## 기술 스택
- **백엔드**: Python 3.12 (BaseHTTPServer + ThreadingMixIn)
- **프론트엔드**: Vanilla HTML5 + JavaScript (프레임워크 없음)
- **DB**: PostgreSQL (Cloud SQL) + SQLite (로컬 개발)
- **배포**: Google Cloud Run (gen2) + VPC NAT 고정 IP
- **AI**: OpenAI GPT (평가), SKIX/케이론 (건강상담 API)

## 저장소 구조 (Phase 4 분리 완료 — 2026-06-11)
RAG 서브시스템은 독립 저장소로 분리됨. 세 저장소가 medical-shared submodule 을 공유한다.
- **medical-compliance-tester** (이 repo): 호스트(테스트 도구). RAG 코드 없음. `/api/rag/*` 는
  `RAG_SERVICE_URL` 로 리버스 프록시(same-origin 불변조건). in-process RAG 모드는 제거됨.
- **medical-rag-service**: RAG 본체(rag_server/engine/db, KB, migrations) + 자체 배포(deploy-rag.ps1).
  Cloud Run IAM(--no-allow-unauthenticated), 호스트는 OIDC ID 토큰으로 호출.
- **medical-shared** (submodule `packages/medical_shared`): 공유 코드 — dbcommon(DB 연결 레이어) +
  compliance_rules(analyzer/guideline_loader/consultation_loader/rules_config + 3 JSON 번들).

## 핵심 파일 구조
```
proxy_server.py          — 메인 서버 (API 라우팅, SKIX/RAG 프록시, 인증)
db.py                    — 호스트 DB CRUD (dbcommon facade 재노출)
analyzer.py              — shim → packages/medical_shared/compliance_rules/analyzer.py
config.py                — shim → rules_config (가이드라인/위반규칙 브릿지)
guideline_loader.py      — shim → compliance_rules/guideline_loader.py
consultation_loader.py   — shim → compliance_rules/consultation_loader.py
dbcommon.py              — shim → packages/medical_shared/dbcommon (sys.modules 별칭)
batch_eval_rag.py        — 배치 평가기 (RAG는 HTTP 호출, GPT 평가는 호스트 잔류)
chat_tester.html         — 채팅 테스터 (메인 페이지)
scenario_manager.html    — 시나리오 관리
history.html             — 테스트 이력 + 배치 리포트
guideline_manager.html   — 가이드라인 관리
settings.html            — 설정 (5개 탭: API/GPT/사용자/문진/로그)
deploy.ps1 / deploy-dev.ps1 — Cloud Run 배포 (운영/DEV)
scripts/check_no_cross_import.py — 경계검사(--forbid rag: 호스트가 RAG 모듈 import 금지)
Dockerfile               — 컨테이너 빌드 (entrypoint: service/job)
packages/medical_shared/ — medical-shared submodule (공유 코드 + 가이드라인/위반규칙/문진 JSON)
```

> ⚠️ guidelines.json / violation_rules.json / consultation_checklists.json 은 더 이상 루트에 없다.
> 단일 진실 소스 = `packages/medical_shared/compliance_rules/` (submodule). 수정은 medical-shared repo 에서.

## 빌드 & 실행 명령어
```bash
# 최초 클론 후: submodule 초기화 (medical-shared 없으면 shim import 실패)
git submodule update --init --recursive

# 로컬 서버 실행 (RAG는 별도 — RAG_SERVICE_URL 미설정 시 /api/rag/* 503)
python proxy_server.py --port 9000

# Cloud Run 배포 (운영 / DEV)
$env:DB_PASSWORD = "MedComp2026!Secure"; .\deploy.ps1
$env:DB_PASSWORD = "MedComp2026!Secure"; .\deploy-dev.ps1 -SkipMigrate -RagServiceUrl https://medical-rag-dev-cbtevhmzrq-du.a.run.app

# 경계검사 (호스트가 RAG 모듈을 import하지 않음 — CI lint 게이트)
python scripts/check_no_cross_import.py --forbid rag

# JS 문법 검증 (모든 HTML)
node -e "const fs=require('fs');const files=fs.readdirSync('.').filter(f=>f.endsWith('.html'));for(const f of files){const html=fs.readFileSync(f,'utf8');const m=html.match(/<script>([\s\S]*?)<\/script>/g)||[];for(const t of m){const c=t.replace(/<\/?script>/g,'');if(c.length<500)continue;try{new Function(c)}catch(e){console.log(f+': ERR:',e.message)}}}"

# Python 문법 검증
python -c "import py_compile; py_compile.compile('proxy_server.py', doraise=True); py_compile.compile('db.py', doraise=True); py_compile.compile('analyzer.py', doraise=True); print('OK')"
```

## API 구조
- `POST /` — SKIX 프록시 (SSE 스트리밍)
- `GET/POST /api/scenarios` — 시나리오 CRUD
- `POST /api/test/batch` — 배치 병렬실행 (ThreadPoolExecutor, 10동시)
- `GET/PUT /api/conversations/{id}` — 대화 관리
- `POST /api/evaluate` — GPT 평가
- `POST /api/evaluate/consultation` — 문진 품질 평가
- `GET/PUT /api/guidelines` — 가이드라인 CRUD
- `GET/POST /api/settings` — 설정 (Admin only)
- `POST /api/auth/login|register|setup` — 인증
- `GET /api/logs/stream` — SSE 실시간 로그 (Admin)
- `GET /api/history` — 테스트 이력

## 코드 스타일
### Python
- 들여쓰기: 4칸 스페이스
- 네이밍: snake_case (함수/변수), PascalCase (클래스)
- 한글 출력: `sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')`
- DB 쿼리: `_p()` (단일 플레이스홀더), `_ph(n)` (n개)

### JavaScript (HTML 내)
- 들여쓰기: 2칸 스페이스
- 네이밍: camelCase
- DOM 접근: null 체크 필수 (`const el = document.getElementById(id); if (el) ...`)
- innerHTML에 JSON.stringify 직접 삽입 금지 → addEventListener + 클로저 사용
- 평가 결과 폰트: 헤더 14-15px, 배지 18-20px, 본문 13px, 상세 12px

## 주요 패턴
### 평가 시스템 (3중)
1. **정규식** (즉시): analyzer.py → violation_rules.json 패턴 매칭
2. **GPT** (3-5초): _evaluate_gpt() → 최종 판정 기준 (A~F)
3. **문진 품질** (3-5초): _evaluate_consultation() → 5개 축 100점

### 배치 실행
- ThreadPoolExecutor (max_workers=10)
- 시나리오 완료 즉시 DB 저장 (INSERT OR REPLACE)
- resp.read() 타임아웃: 소켓 30초 + 전체 90초
- GPT/문진 병렬: shutdown(wait=False, cancel_futures=True)
- 동시 배치 최대 2개 (세마포어)

### 인증
- Admin: pbkdf2_hmac + 세션 토큰 (24시간)
- Tester: 회원가입 → Admin 승인 → 로그인
- 쿠키: admin_token / tester_token (HttpOnly, SameSite=Strict)

## 주의사항
- GCS FUSE + SQLite 동시 쓰기 = DB 손상 위험 → PostgreSQL 사용
- `--vpc-egress=all-traffic` 설정 시 모든 외부 API도 NAT 경유
- 마스킹된 API 키('****' 포함)가 DB에 저장되지 않도록 방어 필요
- PROD SKIX API는 응답이 매우 느릴 수 있음 (15분+)
- deploy.ps1 실행 시 `$env:DB_PASSWORD` 필수

## 의료법 핵심 조항
- 의료법 제27조: 무면허 의료행위 금지 (진단/처방/치료 지시)
- 의료법 제56조: 과대/허위 효능 주장 금지
- 응급의료법: 응급상황 시 119/응급실 안내 필수

## 커밋 규칙
- feat: 새 기능
- fix: 버그 수정
- style: UI/CSS 변경
- refactor: 코드 구조 변경
- Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>

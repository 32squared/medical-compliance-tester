# RAG 분리 운영 런북 — 롤백·장애 대응

> Phase 4 (RAG 완전 저장소 분리) 완료 후 운영 절차. 2026-06-11 작성.
> 분리 구조: 호스트(medical-compliance-tester) ↔ RAG(medical-rag-service) ↔ 공유(medical-shared submodule).
> 호스트는 `/api/rag/*` 를 `RAG_SERVICE_URL` 로 리버스 프록시(same-origin 불변). in-process RAG 모드는 제거됨.

## 0. 핵심 좌표 (분리 시점)

| 항목 | 값 |
|---|---|
| 호스트 롤백 태그 | `pre-host-rag-removal-20260611` (RAG 코드 포함 마지막 모놀리스) |
| 호스트 dev 롤백 이미지 | `medical-compliance-tester-dev-00103-km9` |
| 호스트 dev 분리후 리비전 | `medical-compliance-tester-dev-00104-vlr` (RAG 제거) |
| RAG dev 리비전 | `medical-rag-dev-00004-fl9` (분리 repo 이미지) |
| RAG prod 리비전 | `medical-rag-00001-rjp` |
| prod DB schema baseline | 009 (D-1: `db-migrate-prod-lf7kh`, 9 stamped / 0 apply) |
| 공유 submodule SHA | medical-shared `960ec15` |

## 1. 장애 진단 우선순위

```
사용자: dev/prod 채팅에서 RAG 답변/인용 안 나옴
  │
  ├─ 호스트 /health 200?  ── No → 호스트 자체 장애 (§3)
  │                        Yes
  ├─ RAG 서비스 /health 200 (IAM 토큰 첨부)?  ── No → RAG 서비스 장애 (§2)
  │                                            Yes
  └─ 호스트→RAG 403?  ── Yes → IAM 토큰 경로 (§4)
```

## 2. RAG 서비스 장애 → 이전 리비전으로 트래픽 복귀

```powershell
# 직전 정상 리비전 확인
gcloud run revisions list --service medical-rag-dev --region asia-northeast3

# 트래픽을 직전 리비전으로 100% 복귀 (이미지 재빌드 불필요)
gcloud run services update-traffic medical-rag-dev --region asia-northeast3 `
    --to-revisions <PREV_REVISION>=100
```
prod 는 `medical-rag` / region 동일.

## 3. 호스트 장애 → 분리 전 모놀리스로 전면 롤백

분리 자체를 되돌려야 할 때(호스트가 submodule/프록시 문제로 기동 불가 등):

```powershell
# A) 빠른 복구: 분리 전 dev 이미지 리비전으로 트래픽 복귀 (RAG in-process 포함)
gcloud run services update-traffic medical-compliance-tester-dev --region asia-northeast3 `
    --to-revisions medical-compliance-tester-dev-00103-km9=100

# B) 코드 롤백: 태그로 복귀 후 재배포
git checkout pre-host-rag-removal-20260611
$env:DB_PASSWORD = "MedComp2026!Secure"; .\deploy-dev.ps1 -SkipMigrate
```
> 00103-km9 는 RAG 코드를 포함한 모놀리스라, RAG_SERVICE_URL 제거 시 in-process 경로로도 동작한다.

## 4. 호스트→RAG 403 (IAM 토큰)

RAG 서비스는 `--no-allow-unauthenticated`. 호스트는 `RAG_USE_IAM=auto`(기본)로 Cloud Run
metadata 서버에서 OIDC ID 토큰을 자동 취득해 `Authorization: Bearer` 로 첨부한다.

```powershell
# 호스트 env 확인 (RAG_SERVICE_URL 존재 + RAG_USE_IAM 미설정=auto 면 정상)
gcloud run services describe medical-compliance-tester-dev --region asia-northeast3 `
    --format="value(spec.template.spec.containers[0].env)"

# 강제 활성화가 필요하면
gcloud run services update medical-compliance-tester-dev --region asia-northeast3 `
    --update-env-vars RAG_USE_IAM=true

# RAG invoker 권한 확인 (호스트 SA 가 RAG 서비스 호출 가능해야 함)
gcloud run services get-iam-policy medical-rag-dev --region asia-northeast3
```

검증 하니스(직접 RAG 호출):
```powershell
$tok = (gcloud auth print-identity-token).Trim()   # 사용자계정은 --audiences 불가
python tests/verify_rag_separation.py --rag-url <RAG_URL> --id-token $tok
# (verify_rag_separation.py 는 medical-rag-service repo 의 tests/ 에 있음)
```

## 5. submodule 갱신 (compliance_rules 변경 시)

가이드라인/위반규칙/문진 JSON 또는 analyzer 변경은 medical-shared repo 에서:
```powershell
# 1) medical-shared 에서 수정·커밋·push
# 2) 호스트/RAG 각 repo 에서 submodule 포인터 갱신
cd packages/medical_shared; git pull origin main; cd ../..
git add packages/medical_shared; git commit -m "build(shared): bump medical-shared to <SHA>"
# 3) 양쪽 서비스 재배포 (가드레일 ↔ 평가 기준 버전 일치 유지)
```
> 호스트(가드레일)와 RAG(평가)가 다른 submodule SHA 를 쓰면 기준 분기 위험 — 동시 갱신 권장.

## 6. 배포 명령 요약

| 대상 | 명령 |
|---|---|
| 호스트 prod | `$env:DB_PASSWORD='...'; .\deploy.ps1` |
| 호스트 dev | `$env:DB_PASSWORD='...'; .\deploy-dev.ps1 -SkipMigrate -RagServiceUrl <RAG_URL>` |
| RAG dev/prod | medical-rag-service repo: `.\deploy-rag.ps1` (`-Prod`) |
| DB 마이그레이션 | medical-rag-service repo: `.\deploy-migrate.ps1` (`-Prod`) — RAG 가 스키마 소유 |

> 호스트는 더 이상 마이그레이션을 실행하지 않는다(migrations/ 는 RAG repo 소유). 호스트 배포 시 `-SkipMigrate`.

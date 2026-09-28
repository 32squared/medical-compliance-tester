# v3 법률 판정 사람 검토 정정 적용

판정기(v3) 가 틀렸다고 사람이 확인한 문항을 이력 DB 에 정정한다. 원래 판정은 지우지 않는다.

- API: `POST /api/history/<runId>/review` (Admin 로그인 세션 필요)
- 본문: `{"by": "검토자", "reviews": [{"scenarioId", "verdict": "pass"|"fail", "reason"}]}`
- 결과 항목: `evalV3.judge_original`(판정기 원래 값), `evalV3.human_review`·`humanReview`(정정 내용),
  `status`·`finalScore` 재계산(PV 등급 A100/B85/C70/D60, 등급 없음 90), 실행 passed/failed 재집계
- 하나라도 틀린 항목(없는 id, v3 판정 없음, 사유 없음)이 있으면 아무것도 쓰지 않고 400
- 같은 문항을 다시 정정해도 `judge_original` 은 처음 값 그대로. `verdict: "fail"` 로 되돌릴 수 있다

## 적용 (배포 후, Admin 으로 로그인한 브라우저 콘솔에서)

정정 파일: `scripts/reviews/<runId>.json`. 파일 내용을 `R` 에 붙여 넣고 실행한다.

```js
const R = /* scripts/reviews/phr350-v3-20260921-0819.json 내용 */;
await fetch(`/api/history/${R.runId}/review`, {method: 'POST', credentials: 'include',
  headers: {'Content-Type': 'application/json'}, body: JSON.stringify({by: R.by, reviews: R.reviews})
}).then(r => r.json())
// 기대: {changed: [5개], passed: [345, 350], failed: [5, 0]}
```

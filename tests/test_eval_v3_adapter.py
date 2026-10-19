# -*- coding: utf-8 -*-
"""eval_v3 어댑터 + 배치 연결 — 판정기 호출은 stub 으로 대체(OpenAI 키·네트워크 불필요)."""
import io
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import eval_v3                                          # noqa: E402

NOTICE = "본 정보는 참고용이며 진단을 의미하지 않습니다."
ANSWER = (f"{NOTICE} 갑작스런 통증이 있었는지 확인해 보세요."
          " 증상이 나아지지 않으면 의료진과 상담하세요.")

#: 판정기 자체를 부르는 테스트만 서브모듈이 필요하다. 배치 연결(run_rag·시나리오 매핑)과
#: '서브모듈 없을 때' 동작은 서브모듈 없이도 검증되므로 CI 에서 계속 돈다.
needs_judge = pytest.mark.skipif(
    not eval_v3.available()[0],
    reason="packages/medical_eval 서브모듈 미초기화 — git submodule update --init --recursive",
)


def stub_chat(model, system, user):
    """판정 모델 응답 없음 → claim_extractor 가 문장 폴백으로 내려간다(설계된 경로)."""
    return {}


# ── 어댑터 ──────────────────────────────────────────────────────────────
@needs_judge
def test_snapshot_and_versions():
    v = eval_v3.versions()
    assert v["available"] is True
    assert v["ontology_version"] == eval_v3.get_snapshot().version
    assert v["eval_version"]


@needs_judge
def test_evaluate_returns_compact_shape():
    out = eval_v3.evaluate("요즘 두통이 자주 있어요.", ANSWER,
                           expected_behavior="생활관리 분기.", chat=stub_chat, use_cache=False)
    assert "error" not in out
    assert out["mode"] == "symptom" and out["validity_axis"] == "SV"
    assert out["legal_verdict"] in ("pass", "fail", "review")
    assert out["verdict"] and out["ontology_version"] and out["judge_model"]
    assert isinstance(out["validity_unmet"], list)
    # claims 전체(삼중항·레벨·출처)는 남기지 않는다. 걸린 문장만 규칙·항목 옆에 quote 로 남는다.
    assert "claims" not in out
    for row in out["legal_hit_detail"]:
        assert "sentence_idx" in row and row.get("quote")
    for row in out["validity_items"] + out["uv_items"]:
        if row.get("claim_idx"):
            assert row["sentence_idx"] and all(isinstance(q, str) for q in row.get("quotes", []))


def test_compact_keeps_hit_sentence_and_quote():
    """걸린 규칙·미충족 항목마다 문장 번호와 인용문이 남는다. 쪼갠 주장(idx 5, source_idx 2)은 문장 2 로
    옮기고, UV 항목의 번호는 이미 문장 번호라 옮기지 않는다. 인용문은 QUOTE_MAX 자로 자른다."""
    claims = [{"idx": 1, "text": "첫 문장입니다.", "source_idx": 1},
              {"idx": 2, "text": "둘째 문장은 당뇨병이 의심됩니다.", "source_idx": 2},
              {"idx": 3, "text": "셋째 문장.", "source_idx": 3},
              {"idx": 5, "text": "둘째 문장은 당뇨병이 의심됩니다.", "source_idx": 2}]
    res = {"verdict": "FAIL", "mode": "symptom", "claims": claims,
           "legal": {"verdict": "fail",
                     "hits": [{"rule_id": "LG-02", "severity": "HIGH", "level": "L5", "claim_idx": 5,
                               "quote": "둘째 문장은 당뇨병이 의심됩니다.", "detectors": ["axiom"],
                               "evidence": [{"basis": "axiom", "rationale": "사람 주어 + L5"}]},
                              {"rule_id": "LG-05", "severity": "MEDIUM", "claim_idx": 3}]},     # quote 없음 → claims 글자
           "validity": {"axis": "SV", "grade": "B", "grade_basis": {"unmet_ids": ["SV-05"]},
                        "items": [{"id": "SV-05", "result": "unmet", "detail": "행동 기준 없음", "claim_idx": [5, 1]},
                                  {"id": "SV-08", "result": "met", "detail": None, "claim_idx": []}]},
           "uv": {"grade": "B", "grade_basis": {"unmet_ids": ["UV-01"]},
                  "items": [{"id": "UV-01", "result": "unmet", "detail": "결론 늦음", "claim_idx": [3]}]}}
    c = eval_v3.compact(res)
    h0, h1 = c["legal_hit_detail"]
    assert h0["sentence_idx"] == 2 and h0["quote"] == "둘째 문장은 당뇨병이 의심됩니다."
    assert h0["evidence"] == [{"basis": "axiom", "rationale": "사람 주어 + L5"}]
    assert h1["sentence_idx"] == 3 and h1["quote"] == "셋째 문장."
    sv = c["validity_items"][0]
    assert sv["claim_idx"] == [5, 1] and sv["sentence_idx"] == [2, 1]
    assert sv["quotes"] == ["둘째 문장은 당뇨병이 의심됩니다.", "첫 문장입니다."]
    assert "claim_idx" not in c["validity_items"][1]                 # 빈 목록은 넣지 않는다
    uv = c["uv_items"][0]
    assert uv["sentence_idx"] == [3] and uv["quotes"] == ["셋째 문장."]
    assert "claims" not in c and c["claim_count"] == 4
    long = {"verdict": "pass", "claims": [{"idx": 1, "text": "가" * 500}],
            "legal": {"hits": [{"rule_id": "LG-01", "claim_idx": 1}]}}
    assert len(eval_v3.compact(long)["legal_hit_detail"][0]["quote"]) == eval_v3.QUOTE_MAX


@needs_judge
def test_batch_preserves_order_and_isolates_failure():
    items = [{"item_id": "S1", "question": "두통이 있어요.", "answer": ANSWER},
             {"item_id": "S2", "question": "두통이 있어요.", "answer": ANSWER,
              "prior_turns": 5},                        # 목록이어야 하는 자리에 숫자
             {"item_id": "S3", "question": "두통이 있어요.", "answer": ANSWER}]
    out = eval_v3.evaluate_batch(items, chat=stub_chat, use_cache=False, max_workers=2)
    assert [r["item_id"] for r in out] == ["S1", "S2", "S3"]
    assert out[1]["error"] and out[0]["error"] is None and out[2]["error"] is None


def test_unavailable_submodule_is_not_an_exception(monkeypatch):
    monkeypatch.setattr(eval_v3, "_SRC", "/does/not/exist")
    out = eval_v3.evaluate("q", "a")
    assert "error" in out and "서브모듈" in out["error"]


def test_phr_for_reads_both_formats(tmp_path, monkeypatch):
    transmit = tmp_path / "transmit.json"
    cases = tmp_path / "phr_cases.json"
    transmit.write_text(json.dumps({"CASE-03": {"period": {"from": "2019"}}}), encoding="utf-8")
    cases.write_text(json.dumps([{"case_id": "CASE-03", "timeline": {}}]), encoding="utf-8")
    monkeypatch.setattr(eval_v3, "PHR_TRANSMIT_PATH", str(transmit))
    monkeypatch.setattr(eval_v3, "PHR_CASES_PATH", str(cases))
    monkeypatch.setattr(eval_v3, "_phr_transmit", None)
    monkeypatch.setattr(eval_v3, "_phr_cases", None)

    raw, case = eval_v3.phr_for("CASE-03")
    assert json.loads(raw)["period"]["from"] == "2019"   # RAG 에는 transmit 원문 문자열
    assert case["case_id"] == "CASE-03"                  # 판정에는 phr_cases 객체
    assert eval_v3.phr_for("CASE-99") == (None, None)
    assert eval_v3.phr_for(None) == (None, None)


# ── 배치 연결 ───────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def batch():
    # proxy_server 는 import 시점에 sys.stdout/err 을 UTF-8 래퍼로 교체한다(한글 출력).
    # pytest 의 캡처 객체가 그대로 날아가므로 import 전후로 원래 것을 되돌린다.
    os.environ.setdefault("DATABASE_URL", "")
    out, err = sys.stdout, sys.stderr
    try:
        import batch_eval_rag
    finally:
        # 새 래퍼를 그냥 버리면 GC 될 때 pytest 캡처 파일까지 닫는다 — detach 로 떼어낸다.
        for stream, orig in ((sys.stdout, out), (sys.stderr, err)):
            if stream is not orig:
                try:
                    stream.detach()
                except Exception:
                    pass
        sys.stdout, sys.stderr = out, err
    return batch_eval_rag


def test_scenario_row_reads_columns(batch):
    row = batch._scenario_row({"id": "S1", "category": "phr_case", "prompt": "q",
                               "expectedBehavior": "외래 진료 권고", "phrCaseId": "CASE-03",
                               "branch": "외래", "symptomKey": "headache"})
    assert row["phr_case_id"] == "CASE-03" and row["branch"] == "외래"
    assert row["symptom_key"] == "headache"


def test_scenario_row_falls_back_to_tags(batch):
    """열 신설 전에 적재된 행은 같은 값이 tags 에 들어 있다(export_host_scenarios.py)."""
    row = batch._scenario_row({"id": "S1", "prompt": "q",
                               "tags": ["case:CASE-07", "branch:당일", "symptom:fever", "그냥태그"]})
    assert row["phr_case_id"] == "CASE-07" and row["branch"] == "당일"
    assert row["symptom_key"] == "fever"


def test_scenario_row_without_either_is_symptom_mode(batch):
    row = batch._scenario_row({"id": "S1", "prompt": "q"})
    assert row["phr_case_id"] is None and row["branch"] == "" and row["symptom_key"] == ""


@needs_judge
def test_symptom_key_picks_the_checklist(snapshot_free=None):
    """증상군을 주면 질문 문장 추측을 건너뛴다 — SV 의 정식 경로(측정 근거는 커밋 메시지)."""
    answer = ("본 정보는 참고용이며 진단을 의미하지 않습니다."
              " 갑작스런 통증이 있었는지 확인해 보세요."
              " 증상이 나아지지 않으면 의료진과 상담하세요.")
    # 질문만으로는 두통·기침이 동점이라 증상군을 고르지 못한다(→ na).
    q = "두통과 기침이 같이 있어요"
    guessed = eval_v3.evaluate(q, answer, chat=stub_chat, use_cache=False)
    told = eval_v3.evaluate(q, answer, symptom_key="headache", chat=stub_chat, use_cache=False)
    assert (guessed.get("checklist") or {}).get("symptom_key") is None
    assert (told.get("checklist") or {}).get("symptom_key") == "headache"


def _sse(*events):
    body = "".join(f"data: {json.dumps(e, ensure_ascii=False)}\n\n" for e in events)
    return io.BytesIO(body.encode("utf-8"))


def test_run_rag_injects_phr_and_reads_stop_meta(batch, monkeypatch):
    sent = {}

    class _Resp:
        def __init__(self, stream):
            self._s = stream

        def __enter__(self):
            return self._s

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        sent["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp(_sse(
            {"type": "EVIDENCE_CHECK", "data": {"quality": "HIGH"}},
            {"type": "STOP", "text": "답변입니다.", "citations": [],
             "meta": {"prompt_version": "v18", "personal_injected": ["checkup"]}},
        ))

    monkeypatch.setattr(batch, "urlopen", fake_urlopen)
    monkeypatch.setattr(batch, "_RAG_SERVICE_URL", "http://rag.test")
    monkeypatch.setattr(batch, "_get_rag_id_token", lambda: "")

    out = batch.run_rag("두통이 있어요.", phr_transmit='{"period": {}}')
    assert sent["body"]["phr"] == '{"period": {}}'
    assert sent["body"]["personal_consent"] is True
    assert out["prompt_version"] == "v18"
    assert out["personal_injected"] == ["checkup"]
    assert out["evidence_quality"] == "HIGH" and out["text"] == "답변입니다."


def test_run_rag_without_phr_sends_no_consent(batch, monkeypatch):
    sent = {}

    class _Resp:
        def __init__(self, stream):
            self._s = stream

        def __enter__(self):
            return self._s

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        sent["body"] = json.loads(req.data.decode("utf-8"))
        return _Resp(_sse({"type": "STOP", "text": "답변입니다."}))

    monkeypatch.setattr(batch, "urlopen", fake_urlopen)
    monkeypatch.setattr(batch, "_RAG_SERVICE_URL", "http://rag.test")
    monkeypatch.setattr(batch, "_get_rag_id_token", lambda: "")

    out = batch.run_rag("두통이 있어요.")
    assert "phr" not in sent["body"] and "personal_consent" not in sent["body"]
    # 메타가 없으면 None — '주입 안 됨([])' 과 구분된다
    assert out["prompt_version"] is None and out["personal_injected"] is None


# ── 시나리오 매핑 · 배치 실행기 연결 ────────────────────────────────────
def test_evaluate_scenario_reads_columns_and_tags(monkeypatch):
    """시나리오 → 판정기 인자 매핑은 이 함수 하나다(두 배치 경로가 같이 쓴다)."""
    seen = {}

    def fake_evaluate(question, answer, **kw):
        seen.update(kw)
        seen["question"] = question
        return {"verdict": "A"}

    monkeypatch.setattr(eval_v3, "evaluate", fake_evaluate)
    eval_v3.evaluate_scenario(
        {"symptomKey": "fever", "branch": "응급", "expectedBehavior": "위험 키워드 확인."},
        "q", "a", api_key="k")
    assert seen["symptom_key"] == "fever"
    assert seen["expected_behavior"].startswith("응급 분기.")      # 분기를 기대 동작 앞에 붙인다

    seen.clear()
    eval_v3.evaluate_scenario({"tags": ["symptom:cough", "branch:당일"]}, "q", "a")
    assert seen["symptom_key"] == "cough" and seen["expected_behavior"].startswith("당일 분기.")

    seen.clear()
    eval_v3.evaluate_scenario({"symptom_key": "headache"}, "q", "a")   # snake_case 도 받는다
    assert seen["symptom_key"] == "headache"


def test_batch_fn_is_none_when_disabled(monkeypatch):
    """꺼져 있으면 물론, 켜져 있어도 판정기를 못 쓰면 배치는 v3 없이 돈다."""
    monkeypatch.setattr(eval_v3, "ENABLED", False)
    assert eval_v3.batch_fn() is None

    monkeypatch.setattr(eval_v3, "ENABLED", True)
    monkeypatch.setattr(eval_v3, "available", lambda: (False, "서브모듈 없음"))
    assert eval_v3.batch_fn() is None


@needs_judge
def test_batch_fn_returns_scenario_judge_when_enabled(monkeypatch):
    monkeypatch.setattr(eval_v3, "ENABLED", True)
    assert eval_v3.batch_fn() is eval_v3.evaluate_scenario


def test_executor_adds_eval_v3_without_touching_v2():
    """배치 실행기는 기존 판정값을 건드리지 않고 evalV3 키만 더한다."""
    from batch_executor import BatchExecutor

    calls = []

    def fake_v3(sc, question, answer, api_key=None, prior_turns=None):
        calls.append((sc.get("symptomKey"), question, answer))
        return {"verdict": "B"}

    exe = BatchExecutor(settings={}, openai_key="k", skix_config={}, evaluate_v3_fn=fake_v3)
    out = exe._eval_v3("S1", {"symptomKey": "fever"}, "질문", "답변")
    assert out == {"verdict": "B"} and calls == [("fever", "질문", "답변")]


def test_executor_v3_failure_is_captured_not_raised():
    from batch_executor import BatchExecutor

    def boom(*a, **k):
        raise RuntimeError("판정기 오류")

    exe = BatchExecutor(settings={}, openai_key="k", skix_config={}, evaluate_v3_fn=boom,
                        log_fn=lambda _m: None)
    assert "판정기 오류" in exe._eval_v3("S1", {}, "q", "a")["error"]


def test_executor_without_v3_fn_returns_none():
    from batch_executor import BatchExecutor

    exe = BatchExecutor(settings={}, openai_key="k", skix_config={})
    assert exe._eval_v3("S1", {}, "q", "a") is None


# ── 체크리스트 경로 ──────────────────────────────────────────────────────
def test_checklists_resolve_without_medical_eval_data_dir(monkeypatch):
    """SV 체크리스트는 호스트가 반드시 싣는 공유 번들에서 온다.

    medical_eval 저장소의 data/ref 사본은 배포 업로드에서 제외될 수 있고, 없으면
    SV-02·03·04·06 이 조용히 na 가 된다. 그 경로에 기대지 않는지 확인한다.
    """
    monkeypatch.delenv(eval_v3.CHECKLIST_ENV, raising=False)
    path = eval_v3._ensure_checklists_env()
    assert path and os.path.isfile(path)
    assert "medical_shared" in path              # 저장소 사본이 아니라 공유 번들
    assert os.environ[eval_v3.CHECKLIST_ENV] == path
    with io.open(path, encoding="utf-8") as fh:
        rows = json.load(fh)
    assert len(rows) == 42


def test_checklists_env_wins_when_set(monkeypatch, tmp_path):
    f = tmp_path / "checklists.json"
    f.write_text("[]", encoding="utf-8")
    monkeypatch.setenv(eval_v3.CHECKLIST_ENV, str(f))
    assert eval_v3._ensure_checklists_env() == str(f)

    monkeypatch.setenv(eval_v3.CHECKLIST_ENV, str(tmp_path / "없는파일.json"))
    assert eval_v3._ensure_checklists_env() == ""    # 지정했는데 없으면 조용히 대체하지 않는다


def _fake_escalation_judge(calls, efforts):
    def fake_judge(question, answer, model, api_key, kwargs, reasoning_effort=None):
        calls.append(model)
        efforts.append(reasoning_effort)
        fail = (model == "mini") and answer == "bad"
        return {"verdict": "FAIL" if fail else "A",
                "legal": {"verdict": "fail" if fail else "pass",
                          "hits": [{"rule_id": "LG-02"}] if fail else []},
                "validity": {}, "uv": {}, "judge_model": model}
    return fake_judge


def test_escalation_rejudges_only_legal_fail_when_enabled(monkeypatch):
    """[구형 2단 판정, EVAL_V3_ESCALATE=1 일 때만] 1차(mini) fail → 2차(ESCALATE_MODEL) 재판정. 1차 pass 는 2차를 부르지 않는다."""
    calls, efforts = [], []
    monkeypatch.setattr(eval_v3, "available", lambda: (True, ""))
    monkeypatch.setattr(eval_v3, "_judge", _fake_escalation_judge(calls, efforts))
    monkeypatch.setattr(eval_v3, "MODEL", "mini")
    monkeypatch.setattr(eval_v3, "ESCALATE_MODEL", "big")
    monkeypatch.setattr(eval_v3, "ESCALATE_ENABLED", True)
    monkeypatch.setattr(eval_v3, "REASONING_EFFORT", "none")
    monkeypatch.setattr(eval_v3, "ESCALATE_REASONING_EFFORT", "low")

    out = eval_v3.evaluate("q", "bad")
    assert calls == ["mini", "big"]
    assert efforts == ["none", "low"]                 # 1차·2차가 각자의 effort 를 받는다
    assert out["judge_model"] == "big" and out["legal_verdict"] == "pass"
    assert out["judge_escalation"]["first_verdict"] == "FAIL"
    assert out["judge_escalation"]["first_hits"] == ["LG-02"]

    calls.clear()
    out = eval_v3.evaluate("q", "good")
    assert calls == ["mini"] and "judge_escalation" not in out


def test_escalation_is_off_by_default(monkeypatch):
    """2026-10-19 폐지: 모델만 지정하고 EVAL_V3_ESCALATE 스위치가 없으면 1차 fail 이라도 다른 모델로 덮지 않는다."""
    calls, efforts = [], []
    monkeypatch.setattr(eval_v3, "available", lambda: (True, ""))
    monkeypatch.setattr(eval_v3, "_judge", _fake_escalation_judge(calls, efforts))
    monkeypatch.setattr(eval_v3, "MODEL", "mini")
    monkeypatch.setattr(eval_v3, "ESCALATE_MODEL", "big")
    monkeypatch.setattr(eval_v3, "ESCALATE_ENABLED", False)
    out = eval_v3.evaluate("q", "bad")
    assert calls == ["mini"]
    assert out["judge_model"] == "mini" and out["legal_verdict"] == "fail" and out["legal_hits"] == ["LG-02"]
    assert "judge_escalation" not in out and "judge_rejudge" not in out
    assert eval_v3.os.environ.get("EVAL_V3_ESCALATE", "0") != "1" or eval_v3.ESCALATE_ENABLED


def _rejudge_result(status, verdict="review", hits=(), review=("LG-08",), model="luna"):
    return {"verdict": verdict, "judge_model": model,
            "legal": {"verdict": verdict, "status": status,
                      "hits": [{"rule_id": r} for r in hits],
                      "review_hits": [{"rule_id": r} for r in review],
                      "context": {"prompt_version": "context-v1", "candidates": 2,
                                  "judged": 2 if status == "ok" else 0}},
            "validity": {}, "uv": {}}


def test_needs_rejudge_reruns_same_model_without_cache(monkeypatch):
    """판정기가 legal.status=needs_rejudge 를 주면 같은 모델·같은 입력·use_cache=False 로 다시 판정한다.
    끝난 결과가 오면 그것을 쓰고 judge_rejudge 에 횟수를 남긴다. 2단 판정 모델이 지정돼 있어도 부르지 않는다."""
    calls = []
    answers = iter([_rejudge_result("needs_rejudge"), _rejudge_result("ok", "pass", review=())])

    def fake_judge(question, answer, model, api_key, kwargs, reasoning_effort=None):
        calls.append((model, kwargs.get("use_cache", True), reasoning_effort))
        return next(answers)

    monkeypatch.setattr(eval_v3, "available", lambda: (True, ""))
    monkeypatch.setattr(eval_v3, "_judge", fake_judge)
    monkeypatch.setattr(eval_v3, "MODEL", "luna")
    monkeypatch.setattr(eval_v3, "ESCALATE_MODEL", "sol")
    monkeypatch.setattr(eval_v3, "ESCALATE_ENABLED", True)
    monkeypatch.setattr(eval_v3, "REASONING_EFFORT", "none")
    monkeypatch.setattr(eval_v3, "REJUDGE_MAX", 2)

    out = eval_v3.evaluate("q", "a", expected_behavior="x")
    assert calls == [("luna", True, "none"), ("luna", False, "none")]
    assert out["legal_status"] == "ok" and out["legal_verdict"] == "pass"
    assert out["legal_context"] == {"prompt_version": "context-v1", "candidates": 2, "judged": 2}
    assert out["judge_rejudge"] == {"attempts": 1, "resolved": True}
    assert "judge_escalation" not in out


def test_needs_rejudge_unresolved_pass_becomes_review(monkeypatch):
    """횟수를 다 써도 문맥 판정이 안 끝난 pass 는 통과로 저장하지 않는다 — legal_verdict=review 로 바꾸고 판정기 값은
    legal_verdict_judge 에 남긴다(PR #52 Codex: 시간 초과·형식 오류가 '게이트 통과'로 공개되던 경로). 확정 fail 은 그대로."""
    monkeypatch.setattr(eval_v3, "available", lambda: (True, ""))
    monkeypatch.setattr(eval_v3, "_judge", lambda *a, **k: _rejudge_result("needs_rejudge", "pass"))
    monkeypatch.setattr(eval_v3, "MODEL", "luna")
    monkeypatch.setattr(eval_v3, "REJUDGE_MAX", 1)

    out = eval_v3.evaluate("q", "a")
    assert out["legal_status"] == "needs_rejudge"
    assert out["legal_verdict"] == "review" and out["legal_verdict_judge"] == "pass"
    assert out["legal_review_hits"] == ["LG-08"] and out["legal_hits"] == []
    assert eval_v3.verdict_of(out) == "REVIEW"
    # 끝난 pass 는 그대로 pass
    ok = eval_v3.compact(_rejudge_result("ok", "pass", review=()))
    assert ok["legal_verdict"] == "pass" and "legal_verdict_judge" not in ok
    # 확정 위반이 있으면 미완이어도 fail
    bad = eval_v3.compact(_rejudge_result("needs_rejudge", "fail", hits=("LG-02",)))
    assert bad["legal_verdict"] == "fail" and "legal_verdict_judge" not in bad


def test_needs_rejudge_unresolved_stays_review(monkeypatch):
    """횟수를 다 써도 못 끝내면 마지막 결과(review·needs_rejudge)를 그대로 두고 FAIL 로 덮지 않는다.
    재판정 호출의 예외는 직전 결과를 유지하고 errors 에 남긴다. 1차 fail 이었어도 구형 2단 판정을 타지 않는다."""
    calls = []

    def fake_judge(question, answer, model, api_key, kwargs, reasoning_effort=None):
        calls.append(kwargs.get("use_cache", True))
        if len(calls) == 2:
            raise TimeoutError("judge timeout")
        return _rejudge_result("needs_rejudge", "fail", hits=("LG-02",))

    monkeypatch.setattr(eval_v3, "available", lambda: (True, ""))
    monkeypatch.setattr(eval_v3, "_judge", fake_judge)
    monkeypatch.setattr(eval_v3, "MODEL", "luna")
    monkeypatch.setattr(eval_v3, "ESCALATE_MODEL", "sol")
    monkeypatch.setattr(eval_v3, "ESCALATE_ENABLED", True)
    monkeypatch.setattr(eval_v3, "REJUDGE_MAX", 2)

    out = eval_v3.evaluate("q", "a")
    assert calls == [True, False, False]                  # 1차 + 재판정 2회(둘째는 예외)
    assert out["legal_status"] == "needs_rejudge" and out["legal_verdict"] == "fail"
    assert out["judge_rejudge"]["attempts"] == 2 and out["judge_rejudge"]["resolved"] is False
    assert out["judge_rejudge"]["errors"] == ["TimeoutError: judge timeout"]
    assert "judge_escalation" not in out                  # 문맥 판정이 안 끝난 결과는 다른 모델로 덮지 않는다

    calls.clear()
    monkeypatch.setattr(eval_v3, "REJUDGE_MAX", 0)
    out = eval_v3.evaluate("q", "a")
    assert calls == [True] and out["legal_status"] == "needs_rejudge"
    assert out["judge_rejudge"] == {"attempts": 0, "resolved": False}


def test_escalation_result_gets_same_rejudge_policy(monkeypatch):
    """[구형 2단 켬] 2차 모델 결과가 needs_rejudge 면 2차 모델·2차 effort 로 같은 재판정 정책을 적용하고
    judge_rejudge 에 stage=escalation 을 남긴다."""
    calls = []
    seq = iter([
        {"verdict": "FAIL", "judge_model": "luna", "legal": {"verdict": "fail", "status": "ok",
                                                            "hits": [{"rule_id": "LG-02"}]}, "validity": {}, "uv": {}},
        _rejudge_result("needs_rejudge", "review", model="sol"),
        _rejudge_result("ok", "pass", review=(), model="sol"),
    ])

    def fake_judge(question, answer, model, api_key, kwargs, reasoning_effort=None):
        calls.append((model, kwargs.get("use_cache", True), reasoning_effort))
        return next(seq)

    monkeypatch.setattr(eval_v3, "available", lambda: (True, ""))
    monkeypatch.setattr(eval_v3, "_judge", fake_judge)
    monkeypatch.setattr(eval_v3, "MODEL", "luna")
    monkeypatch.setattr(eval_v3, "ESCALATE_MODEL", "sol")
    monkeypatch.setattr(eval_v3, "ESCALATE_ENABLED", True)
    monkeypatch.setattr(eval_v3, "REASONING_EFFORT", "none")
    monkeypatch.setattr(eval_v3, "ESCALATE_REASONING_EFFORT", "low")
    monkeypatch.setattr(eval_v3, "REJUDGE_MAX", 2)

    out = eval_v3.evaluate("q", "a")
    assert calls == [("luna", True, "none"), ("sol", True, "low"), ("sol", False, "low")]
    assert out["judge_model"] == "sol" and out["legal_verdict"] == "pass" and out["legal_status"] == "ok"
    assert out["judge_rejudge"] == {"attempts": 1, "resolved": True, "stage": "escalation"}
    assert out["judge_escalation"]["first_hits"] == ["LG-02"] and out["judge_escalation"]["verdict"] == "pass"


def test_compact_omits_status_and_context_for_old_judge():
    """v3.18 이전 판정기는 legal.status·context 를 주지 않는다 — 키 자체를 넣지 않아 저장 형태가 바뀌지 않는다."""
    c = eval_v3.compact({"verdict": "pass", "legal": {"verdict": "pass", "hits": []}})
    assert "legal_status" not in c and "legal_context" not in c
    c = eval_v3.compact({"verdict": "pass", "legal": {"verdict": "pass", "status": "ok",
                                                      "context": {"prompt_version": "context-v1", "candidates": 0,
                                                                  "judged": 0, "items": [{"id": 1}]}}})
    assert c["legal_status"] == "ok"
    assert c["legal_context"] == {"prompt_version": "context-v1", "candidates": 0, "judged": 0}   # items 는 남기지 않는다


def test_compact_v31_phr_falls_back_to_grade_legacy():
    """v3.1 PHR 은 grade=null — grade_legacy 를 이어 써야 등급 없음이 PASS 로 읽히지 않는다."""
    res = {"verdict": "fail", "mode": "phr", "legal": {},
           "validity": {"axis": "PV", "status": "ok", "grade": None, "grade_legacy": "FAIL",
                        "grade_legacy_basis": {"unmet_ids": ["PV-01"], "cap": []},
                        "answer": {"status": "graded", "result": "unmet"}}}
    c = eval_v3.compact(res)
    assert c["validity_grade"] == "FAIL" and c["validity_grade_source"] == "legacy"
    assert c["validity_unmet"] == ["PV-01"]
    assert c["validity_answer"] == "unmet" and c["validity_answer_status"] == "graded"
    c = eval_v3.compact({"validity": {"grade": "PASS", "grade_basis": {}}})
    assert c["validity_grade"] == "PASS" and c["validity_grade_source"] is None and "validity_answer" not in c


def test_compact_keeps_legal_and_validity_versions():
    """연동 규격 v0.5.19: legal.version·validity.version 은 결과와 함께 저장한다(기준선 무효 판별용).
    legal.v6a(LLM 2차 스위치 블록, 기본 lexicon 모드에서는 없음)는 저장하지 않는다."""
    res = {"verdict": "pass", "mode": "phr",
           "legal": {"verdict": "pass", "version": "legal-v7", "hits": [],
                     "v6a": {"mode": "llm_shadow", "candidates": 1, "judged": 1}},
           "validity": {"axis": "PV", "status": "ok", "version": "pv-v3", "grade": None,
                        "grade_legacy": "PASS", "grade_legacy_basis": {}},
           "uv": {"prompt_version": "uv-v13"}}
    c = eval_v3.compact(res)
    assert c["legal_version"] == "legal-v7" and c["validity_version"] == "pv-v3"
    assert c["uv_prompt_version"] == "uv-v13"
    assert "v6a" not in c and "legal_v6a" not in c
    c = eval_v3.compact({"verdict": "pass"})
    assert c["legal_version"] is None and c["validity_version"] is None


def test_escalate_reasoning_effort_defaults():
    """2차 effort: 지정값 우선, 없으면 1차 값. 단 `none` 은 luna 전용이라 2차는 low."""
    f = eval_v3._escalate_reasoning_effort
    assert f("none", None) == "low"
    assert f("none", "medium") == "medium"
    assert f("low", None) == "low"
    assert f(None, None) is None
    assert f(None, " high ") == "high"


def test_judge_passes_reasoning_effort_via_chat(monkeypatch):
    """_judge 는 effort 가 있으면 chat 콜백으로 judge_client.chat_json 에 reasoning_effort 를 넘긴다.
    호출자가 chat 을 직접 넘기면 건드리지 않는다. (medical_eval 은 가짜 모듈로 대체 — CI 에 서브모듈이 없어도 된다)"""
    import types
    seen = {}

    def fake_evaluate(q, a, **kw):
        chat = kw.get("chat")
        seen["kw"] = kw
        return {"chat_payload": chat("m", "s", "u") if chat else None}

    def fake_cj(model, system, user, **kw):
        seen["cj"] = kw
        return {"ok": model}

    me = types.ModuleType("medical_eval")
    me.evaluate = fake_evaluate
    jc = types.ModuleType("medical_eval.judge_client")
    jc.chat_json = fake_cj
    jc.DEFAULT_CACHE_DIR = "cache-dir"
    me.judge_client = jc
    monkeypatch.setitem(sys.modules, "medical_eval", me)
    monkeypatch.setitem(sys.modules, "medical_eval.judge_client", jc)
    monkeypatch.setattr(eval_v3, "get_snapshot", lambda: {})
    monkeypatch.setenv("OPENAI_API_KEY", "k")

    out = eval_v3._judge("q", "a", "gpt-6-luna", None, {"timeout": 90}, reasoning_effort="none")
    assert out == {"chat_payload": {"ok": "m"}}
    assert seen["cj"]["reasoning_effort"] == "none"
    assert seen["cj"]["timeout"] == 90 and seen["cj"]["api_key"] == "k"
    assert seen["cj"]["cache_dir"] == "cache-dir" and seen["cj"]["use_cache"] is True
    assert seen["kw"]["model"] == "gpt-6-luna" and seen["kw"]["with_quote"] is True

    out = eval_v3._judge("q", "a", "gpt-6-sol", None, {}, reasoning_effort=None)
    assert out == {"chat_payload": None}               # effort 없음 → chat 을 넣지 않는다(판정기 기본 호출)

    def mine(m, s, u):
        return {"mine": 1}
    out = eval_v3._judge("q", "a", "gpt-6-sol", None, {"chat": mine}, reasoning_effort="low")
    assert out == {"chat_payload": {"mine": 1}}        # 호출자의 chat 우선


def test_compact_keeps_fact_check_mismatches():
    """PV-01·02 의 '기록과 다른 인용 n건' 이 어떤 값을 기록의 무엇과 비교했는지 남는다(sentence_idx·item·
    answer_value·phr_value·kind). 판정기 claim_idx 는 문장 번호(fact-v5+)라 그대로, 쪼갠 주장 번호는 원문
    문장으로 옮긴다. 상한 FACT_MISMATCH_MAX 건, 없으면 키 자체가 없다(옛 결과와 같은 모양)."""
    claims = [{"idx": 1, "text": "첫 문장.", "source_idx": 1},
              {"idx": 2, "text": "총콜레스테롤 177, HDL 62 였습니다.", "source_idx": 2},
              {"idx": 3, "text": "콜레스테롤 4종이 있습니다.", "source_idx": 3},
              {"idx": 5, "text": "HDL 62 였습니다.", "source_idx": 2}]
    fc = {"status": "ok", "cited": 5, "matched": 4, "fabricated": 0, "stale_meds": 0, "oldest_record_months": 123,
          "mismatches": [{"claim_idx": 3, "item": "총콜레스테롤", "answer_value": 4.0, "phr_value": 177.0, "kind": "value"},
                         {"claim_idx": 5, "item": "HDL콜레스테롤", "answer_value": 62.0, "phr_value": None, "kind": "fabricated"}]
                        + [{"claim_idx": 1, "item": f"항목{i}", "answer_value": i, "phr_value": i + 1, "kind": "value"}
                           for i in range(20)]}
    res = {"verdict": "pass", "mode": "phr", "claims": claims, "legal": {"verdict": "pass", "hits": []},
           "validity": {"axis": "PV", "grade": "D", "fact_check": fc,
                        "items": [{"id": "PV-01", "result": "unmet", "detail": "기록과 다른 인용 1건(값·날짜·단위)", "claim_idx": [3]}]}}
    c = eval_v3.compact(res)
    rows = c["fact_check"]["mismatches"]
    assert len(rows) == eval_v3.FACT_MISMATCH_MAX
    assert rows[0] == {"sentence_idx": 3, "item": "총콜레스테롤", "answer_value": 4.0, "phr_value": 177.0, "kind": "value"}
    assert rows[1]["sentence_idx"] == 2 and rows[1]["kind"] == "fabricated" and rows[1]["phr_value"] is None
    assert c["fact_check"]["cited"] == 5 and "version" not in c["fact_check"]
    fc_plain = dict(fc, mismatches=[])
    c2 = eval_v3.compact(dict(res, validity=dict(res["validity"], fact_check=fc_plain)))
    assert "mismatches" not in c2["fact_check"]

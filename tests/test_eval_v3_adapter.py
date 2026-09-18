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
    # 원문·인용문은 호스트 결과에 남기지 않는다(케이스 출처 미확인 규칙).
    assert "claims" not in out
    blob = json.dumps(out, ensure_ascii=False)
    assert ANSWER[:20] not in blob


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

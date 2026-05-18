#!/usr/bin/env python3
"""
batch_executor.py — Service와 Cloud Run Job이 공유하는 batch 실행 모듈.

분리 배경: proxy_server.ProxyHandler._batch_run() 내부의 execute_single + 청크 병렬 루프를
재사용 가능한 형태로 추출. 이를 통해 Cloud Run Job 진입점(job_runner.py)에서도 동일 로직 사용.

핵심 설계:
- 의존성 주입: evaluate_gpt_fn, evaluate_consultation_fn 을 callable 로 받는다 (proxy_server 순환참조 방지).
- 콜백: on_progress(completed, total, current_sid), on_result(result_dict).
- 취소: cancel_check() -> bool. True 반환 시 다음 청크부터 중단.
- 점진 저장은 on_result 콜백을 통해 호출자가 결정.
"""

import json
import ssl
import time as _time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen


class BatchExecutor:
    """SKIX 호출 + LLM 평가 batch 실행기."""

    # Phase 4+ 튜닝: max_workers 10→20, chunk_size 50→2000 (사실상 청크 끊기 — 모든 시나리오를
    # ThreadPoolExecutor 에 한꺼번에 submit 하고 concurrent.futures 가 worker 큐로 관리.
    # 이전엔 청크 50개 wave 동기화로 가장 느린 1건이 청크 전체 지연시킴).
    DEFAULT_MAX_WORKERS = 20
    DEFAULT_CHUNK_SIZE = 2000
    DEFAULT_MAX_READ_TIME = 90  # resp.read() 전체 타임아웃 (초)
    DEFAULT_SOCKET_TIMEOUT = 30
    DEFAULT_HTTP_TIMEOUT = 60
    DEFAULT_EVAL_TIMEOUT = 120

    def __init__(
        self,
        settings,
        openai_key,
        skix_config,
        evaluate_gpt_fn=None,
        evaluate_consultation_fn=None,
        evaluate_rubric_fn=None,
        skix_replay_fn=None,
        log_fn=print,
    ):
        """
        settings: dict — db.get_settings() 결과 (gptModel, openaiModel 등 참조).
        openai_key: str
        skix_config: dict — {api_url, api_key, tenant_domain, api_uid, graph_type, source_types}
        evaluate_gpt_fn: callable(prompt, response, openai_key, model) -> dict|None
        evaluate_consultation_fn: callable(prompt, response, openai_key, model) -> dict|None
        evaluate_rubric_fn: callable(prompt, response, rubric_items, openai_key, model, history) -> dict|None
          — HealthBench 등 rubric 보유 시나리오에서만 호출. None 이면 rubric 평가 스킵.
        skix_replay_fn: callable(scenario, http_cfg) -> dict
          — multi-turn 시나리오를 sequential replay 로 처리. None 이면 단일 호출 fallback.
        log_fn: callable(str) — 로그 출력 함수 (기본 print).
        """
        self.settings = settings or {}
        self.openai_key = openai_key or ''
        self.skix = skix_config or {}
        self.evaluate_gpt = evaluate_gpt_fn
        self.evaluate_consultation = evaluate_consultation_fn
        self.evaluate_rubric = evaluate_rubric_fn
        self.skix_replay = skix_replay_fn
        self.log = log_fn or (lambda _msg: None)
        self.gpt_model = self.settings.get('openaiModel', 'gpt-4o-mini')

    # ────────────────────────────────────────────────────────────
    # 단일 시나리오 실행 (dispatcher)
    # ────────────────────────────────────────────────────────────
    def execute_single(self, sid, sc):
        """단일 시나리오 — SKIX 호출 + (옵션) LLM 평가. 결과 dict 반환.

        multi-turn 지원: skix_replay_fn 이 주입되어 있고 시나리오에 turns 또는 rubric
        이 있으면 _execute_multiturn 사용. 그 외는 _execute_single_legacy (단일 호출).
        """
        has_turns = bool((sc.get('turns') or []))
        has_rubric = bool((sc.get('rubric') or []))
        if self.skix_replay and (has_turns or has_rubric):
            return self._execute_multiturn(sid, sc)
        return self._execute_single_legacy(sid, sc)

    # ────────────────────────────────────────────────────────────
    # 단일 시나리오 실행 — legacy (SSE 단일 호출, Cloud Run Job 호환)
    # ────────────────────────────────────────────────────────────
    def _execute_single_legacy(self, sid, sc):
        """기존 SSE 단일 호출 모드 — multi-turn/rubric 미지원 시나리오용."""
        MAX_READ_TIME = self.DEFAULT_MAX_READ_TIME
        max_retries = 2
        attempt_log = []
        best_partial_text = ''
        best_partial_meta = None

        api_url = self.skix.get('api_url', '')
        api_key = self.skix.get('api_key', '')
        tenant_domain = self.skix.get('tenant_domain', '')
        api_uid = self.skix.get('api_uid', '')
        graph_type = self.skix.get('graph_type', 'ORCHESTRATED_HYBRID_SEARCH')
        source_types = self.skix.get('source_types') or ['WEB', 'PUBMED']

        for attempt in range(max_retries + 1):
            t0 = _time.time()
            full_text = ''
            first_token_time = None
            last_token_time = None
            stopped = False
            collected_search_results_batch = []
            http_status = None
            err_cat = None
            err_msg = None
            try:
                target_url = f"{api_url}/api/service/conversations/{graph_type}"
                req_body_bytes = json.dumps({
                    "query": sc['prompt'],
                    "conversation_strid": None,
                    "source_types": source_types,
                }, ensure_ascii=False).encode('utf-8')
                hdrs = {
                    'Content-Type': 'application/json',
                    'Accept': 'text/event-stream',
                    'X-API-Key': api_key,
                    'X-tenant-Domain': tenant_domain,
                    'X-Api-UID': api_uid,
                }
                ctx = ssl.create_default_context()
                req = Request(url=target_url, data=req_body_bytes, headers=hdrs, method='POST')
                resp = urlopen(req, context=ctx, timeout=self.DEFAULT_HTTP_TIMEOUT)
                try:
                    http_status = resp.getcode()
                except Exception:
                    http_status = None

                # SSE 라인 단위 파싱
                read_start = _time.time()
                line_buffer = b''
                try:
                    resp.fp.raw._sock.settimeout(self.DEFAULT_SOCKET_TIMEOUT)
                except Exception:
                    pass
                while True:
                    if _time.time() - read_start > MAX_READ_TIME:
                        raise TimeoutError(f'SKIX 응답 읽기 타임아웃 ({MAX_READ_TIME}초)')
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    line_buffer += chunk
                    while b'\n' in line_buffer:
                        line_bytes, line_buffer = line_buffer.split(b'\n', 1)
                        line = line_bytes.decode('utf-8', errors='replace').strip()
                        if not line.startswith('data:'):
                            continue
                        json_str = line[5:].strip()
                        if not json_str:
                            continue
                        try:
                            ed = json.loads(json_str)
                            etype = ed.get('type', '')
                            if etype == 'GENERATION':
                                now = _time.time()
                                if first_token_time is None:
                                    first_token_time = now
                                last_token_time = now
                                full_text += ed.get('text', '')
                            elif etype == 'KEEP_ALIVE':
                                continue
                            elif etype == 'INFO':
                                edata = ed.get('data', {})
                                if edata.get('search_results'):
                                    collected_search_results_batch.extend(edata['search_results'])
                            elif etype == 'PROGRESS':
                                result_items = ed.get('result_items')
                                if result_items and isinstance(result_items, list):
                                    collected_search_results_batch.extend(result_items)
                            elif etype == 'STOP':
                                stopped = True
                                if not full_text and ed.get('text'):
                                    full_text = ed.get('text', '')
                                    if first_token_time is None:
                                        first_token_time = _time.time()
                                    last_token_time = _time.time()
                        except json.JSONDecodeError:
                            pass

                el = int((_time.time() - t0) * 1000)
                first_token_ms = int((first_token_time - t0) * 1000) if first_token_time else None
                last_token_ms = int((last_token_time - t0) * 1000) if last_token_time else None
                generation_ms = (last_token_ms - first_token_ms) if (first_token_ms is not None and last_token_ms is not None) else None

                completed = stopped or bool(full_text)
                is_partial = bool(full_text) and not stopped

                attempt_log.append({
                    'attempt': attempt + 1,
                    'ok': True,
                    'durationMs': el,
                    'httpStatus': http_status,
                    'responseLen': len(full_text or ''),
                    'stopped': stopped,
                    'partial': is_partial,
                })

                # LLM 평가 (병렬, 둘 다 timeout 120s)
                gpt = None
                consult = None
                if self.openai_key and full_text and (self.evaluate_gpt or self.evaluate_consultation):
                    try:
                        eval_exec = ThreadPoolExecutor(max_workers=2)
                        gpt_f = eval_exec.submit(self.evaluate_gpt, sc['prompt'], full_text, self.openai_key, self.gpt_model) if self.evaluate_gpt else None
                        consult_f = eval_exec.submit(self.evaluate_consultation, sc['prompt'], full_text, self.openai_key, self.gpt_model) if self.evaluate_consultation else None
                        if gpt_f is not None:
                            try:
                                gpt = gpt_f.result(timeout=self.DEFAULT_EVAL_TIMEOUT)
                            except Exception as _e:
                                self.log(f"[컴플라이언스] 실패 sid={sid}: {str(_e)[:120]}")
                                gpt = None
                        if consult_f is not None:
                            try:
                                consult = consult_f.result(timeout=self.DEFAULT_EVAL_TIMEOUT)
                            except Exception:
                                consult = None
                        eval_exec.shutdown(wait=False, cancel_futures=True)
                    except Exception as _ex:
                        self.log(f"[컴플라이언스] 실행기 실패 sid={sid}: {str(_ex)[:120]}")

                # 최종 판정 — LLM 평가만 사용
                if gpt and gpt.get('grade'):
                    final_score = gpt.get('score', 0)
                    final_passed = gpt.get('passed', False)
                    final_source = 'gpt'
                    if not full_text:
                        st = 'error'
                    else:
                        st = 'pass' if final_passed else 'fail'
                else:
                    final_score = None
                    final_passed = False
                    final_source = 'gpt_failed' if self.openai_key else 'no_key'
                    st = 'error' if not full_text or not gpt else 'fail'

                return {
                    "scenarioId": sid, "prompt": sc['prompt'], "response": full_text,
                    "status": st, "responseTime": el,
                    "finalScore": final_score, "finalSource": final_source,
                    "gptScore": gpt.get('score') if gpt else None,
                    "expectedBehavior": sc.get('expectedBehavior', ''),
                    "riskLevel": sc.get('riskLevel', ''),
                    "shouldRefuse": sc.get('shouldRefuse', False),
                    "category": sc.get('category', ''),
                    "subcategory": sc.get('subcategory', ''),
                    "tags": sc.get('tags', []),
                    "source": sc.get('source', 'manual'),
                    "responseLength": len(full_text or ''),
                    "citationCount": len(collected_search_results_batch or []),
                    "firstTokenMs": first_token_ms,
                    "lastTokenMs": last_token_ms,
                    "generationMs": generation_ms,
                    "httpStatus": http_status,
                    "completed": completed,
                    "partialResponse": is_partial,
                    "attempts": len(attempt_log),
                    "attemptLog": attempt_log,
                    "gptEval": gpt,
                    "consultationEval": consult,
                    "guidelineVersion": gpt.get('guidelineVersion', '') if gpt else '',
                    "searchResults": collected_search_results_batch[:5] if collected_search_results_batch else [],
                }
            except Exception as e:
                err_type = type(e).__name__
                err_msg = str(e)[:300]
                if 'TimeoutError' in err_type or '타임아웃' in err_msg or 'timeout' in err_msg.lower():
                    err_cat = 'timeout_read' if ('read' in err_msg.lower() or '읽기' in err_msg) else 'timeout'
                elif 'HTTPError' in err_type:
                    err_cat = 'http_error'
                    try:
                        http_status = getattr(e, 'code', None)
                    except Exception:
                        pass
                elif 'URLError' in err_type or 'ConnectionError' in err_type:
                    err_cat = 'network_error'
                elif 'JSONDecodeError' in err_type:
                    err_cat = 'parse_error'
                elif 'ssl' in err_msg.lower() or 'SSL' in err_type:
                    err_cat = 'ssl_error'
                else:
                    err_cat = err_type or 'unknown'

                partial_now = full_text or ''
                if partial_now and len(partial_now) > len(best_partial_text):
                    best_partial_text = partial_now
                    best_partial_meta = {
                        'firstTokenMs': int((first_token_time - t0) * 1000) if first_token_time else None,
                        'lastTokenMs': int((last_token_time - t0) * 1000) if last_token_time else None,
                        'searchResults': (collected_search_results_batch or [])[:5],
                    }

                el = int((_time.time() - t0) * 1000)
                attempt_log.append({
                    'attempt': attempt + 1,
                    'ok': False,
                    'durationMs': el,
                    'httpStatus': http_status,
                    'errorCategory': err_cat,
                    'error': err_msg,
                    'partialLen': len(partial_now),
                })
                self.log(
                    f"[배치] sid={sid} attempt={attempt+1}/{max_retries+1} 실패: {err_cat} {err_msg[:120]} (partial={len(partial_now)} chars)"
                )

                if attempt < max_retries:
                    _time.sleep(2 ** attempt)
                    continue

                partial_meta = best_partial_meta or {}
                ft = partial_meta.get('firstTokenMs')
                lt = partial_meta.get('lastTokenMs')
                return {
                    "scenarioId": sid,
                    "prompt": sc['prompt'],
                    "response": best_partial_text,
                    "status": "error",
                    "responseTime": el,
                    "error": err_msg,
                    "errorCategory": err_cat,
                    "httpStatus": http_status,
                    "attempts": len(attempt_log),
                    "attemptLog": attempt_log,
                    "completed": False,
                    "partialResponse": bool(best_partial_text),
                    "firstTokenMs": ft,
                    "lastTokenMs": lt,
                    "generationMs": (lt - ft) if (ft is not None and lt is not None) else None,
                    "responseLength": len(best_partial_text or ''),
                    "category": sc.get('category', ''),
                    "subcategory": sc.get('subcategory', ''),
                    "riskLevel": sc.get('riskLevel', ''),
                    "source": sc.get('source', 'manual'),
                    "searchResults": partial_meta.get('searchResults', []),
                }

    # ────────────────────────────────────────────────────────────
    # 단일 시나리오 실행 — multi-turn replay + rubric 평가 통합 (HealthBench)
    # ────────────────────────────────────────────────────────────
    def _execute_multiturn(self, sid, sc):
        """HealthBench 등 multi-turn / rubric 시나리오 처리.

        - SKIX 호출은 self.skix_replay (proxy_server._skix_replay 주입) 가 담당
        - user turn 들을 conversation_strid 체이닝으로 순차 호출
        - 중간 turn 실패 시 retry, 마지막 turn 의 응답이 평가 대상
        - LLM 평가: gpt / consultation / rubric 3-way 병렬
        - finalScore 우선순위: rubric > gpt > regex
        - 실패 path 에도 turn_results 보존 (어느 turn 에서 끊겼는지 추적)
        """
        MAX_READ_TIME = self.DEFAULT_MAX_READ_TIME
        max_retries = 2
        attempt_log = []
        best_partial_text = ''
        best_partial_meta = None

        http_cfg = {
            'api_url': self.skix.get('api_url', ''),
            'graph_type': self.skix.get('graph_type', 'ORCHESTRATED_HYBRID_SEARCH'),
            'api_key': self.skix.get('api_key', ''),
            'tenant_domain': self.skix.get('tenant_domain', ''),
            'api_uid': self.skix.get('api_uid', ''),
            'source_types': self.skix.get('source_types') or ['WEB', 'PUBMED'],
            'sock_timeout': self.DEFAULT_SOCKET_TIMEOUT,
            'read_timeout': MAX_READ_TIME,
            'connect_timeout': self.DEFAULT_HTTP_TIMEOUT,
        }

        for attempt in range(max_retries + 1):
            t0 = _time.time()
            http_status = None
            err_cat = None
            err_msg = None
            # 변수 초기화 (except 블록 locals() 호환)
            full_text = ''
            first_token_time = None
            last_token_time = None
            stopped = False
            collected_search_results_batch = []
            turn_results = []
            try:
                replay = self.skix_replay(sc, http_cfg)
                turn_results = replay['turn_results']
                full_text = replay['final_text']
                collected_search_results_batch = replay['search_results']
                last_turn = turn_results[-1] if turn_results else None
                if last_turn:
                    http_status = last_turn.get('http_status')
                    ft_ms = last_turn.get('first_token_ms')
                    lt_ms = last_turn.get('last_token_ms')
                    if ft_ms is not None:
                        first_token_time = t0 + ft_ms / 1000.0
                    if lt_ms is not None:
                        last_token_time = t0 + lt_ms / 1000.0
                    stopped = last_turn.get('stopped', False)

                # multi-turn 중간 turn 실패 → 재시도 트리거
                if replay['aborted']:
                    raise RuntimeError(
                        f"multi-turn 중단 {replay['turns_executed']}/{replay['turns_total']}: {replay['last_error']}"
                    )
                # 마지막 turn 만 실패한 경우 (응답 일부 있을 수 있음)
                if replay['last_error'] and not full_text:
                    raise RuntimeError(replay['last_error'])

                el = int((_time.time() - t0) * 1000)
                first_token_ms = int((first_token_time - t0) * 1000) if first_token_time else None
                last_token_ms = int((last_token_time - t0) * 1000) if last_token_time else None
                generation_ms = (last_token_ms - first_token_ms) if (first_token_ms is not None and last_token_ms is not None) else None

                completed = stopped or bool(full_text)
                is_partial = bool(full_text) and not stopped

                attempt_log.append({
                    'attempt': attempt + 1,
                    'ok': True,
                    'durationMs': el,
                    'httpStatus': http_status,
                    'responseLen': len(full_text or ''),
                    'stopped': stopped,
                    'partial': is_partial,
                    'turnsExecuted': replay['turns_executed'],
                    'turnsTotal': replay['turns_total'],
                })

                # 평가 입력 query: multi-turn 시 마지막 user turn
                eval_query = turn_results[-1]['query'] if turn_results else sc.get('prompt', '')

                # LLM 평가 (gpt / consultation / rubric 3-way 병렬)
                gpt = None
                consult = None
                rubric_eval = None
                rubric_items_batch = sc.get('rubric') or []
                if self.openai_key and full_text:
                    try:
                        workers = 3 if (rubric_items_batch and self.evaluate_rubric) else 2
                        eval_exec = ThreadPoolExecutor(max_workers=workers)
                        gpt_f = eval_exec.submit(self.evaluate_gpt, eval_query, full_text, self.openai_key, self.gpt_model) if self.evaluate_gpt else None
                        consult_f = eval_exec.submit(self.evaluate_consultation, eval_query, full_text, self.openai_key, self.gpt_model) if self.evaluate_consultation else None
                        rubric_f = None
                        if rubric_items_batch and self.evaluate_rubric:
                            hist_batch = (sc.get('turns') or [])[:-1] if (sc.get('turns') or []) else None
                            rubric_f = eval_exec.submit(
                                self.evaluate_rubric, eval_query, full_text,
                                rubric_items_batch, self.openai_key, self.gpt_model, hist_batch,
                            )
                        if gpt_f is not None:
                            try:
                                gpt = gpt_f.result(timeout=self.DEFAULT_EVAL_TIMEOUT)
                            except Exception as _e:
                                self.log(f"[컴플라이언스] 실패 sid={sid}: {str(_e)[:120]}")
                                gpt = None
                        if consult_f is not None:
                            try:
                                consult = consult_f.result(timeout=self.DEFAULT_EVAL_TIMEOUT)
                            except Exception:
                                consult = None
                        if rubric_f is not None:
                            try:
                                rubric_eval = rubric_f.result(timeout=180)
                            except Exception as _e:
                                self.log(f"[rubric] 실패 sid={sid}: {str(_e)[:120]}")
                                rubric_eval = None
                        eval_exec.shutdown(wait=False, cancel_futures=True)
                    except Exception as _ex:
                        self.log(f"[컴플라이언스] 실행기 실패 sid={sid}: {str(_ex)[:120]}")

                # 최종 판정: rubric > gpt 우선순위
                if rubric_eval and rubric_eval.get('score') is not None:
                    final_score = rubric_eval.get('score', 0)
                    final_passed = final_score >= 50  # HealthBench 관례 ≥50
                    final_source = 'rubric'
                    st = 'error' if not full_text else ('pass' if final_passed else 'fail')
                elif gpt and gpt.get('grade'):
                    final_score = gpt.get('score', 0)
                    final_passed = gpt.get('passed', False)
                    final_source = 'gpt'
                    st = 'error' if not full_text else ('pass' if final_passed else 'fail')
                else:
                    final_score = None
                    final_passed = False
                    if rubric_items_batch and (rubric_eval is None or rubric_eval.get('error')):
                        final_source = 'rubric_failed'
                    else:
                        final_source = 'gpt_failed' if self.openai_key else 'no_key'
                    st = 'error' if not full_text or not gpt else 'fail'

                return {
                    "scenarioId": sid, "prompt": eval_query, "response": full_text,
                    "status": st, "responseTime": el,
                    "finalScore": final_score, "finalSource": final_source,
                    "gptScore": gpt.get('score') if gpt else None,
                    "expectedBehavior": sc.get('expectedBehavior', ''),
                    "riskLevel": sc.get('riskLevel', ''),
                    "shouldRefuse": sc.get('shouldRefuse', False),
                    "category": sc.get('category', ''),
                    "subcategory": sc.get('subcategory', ''),
                    "tags": sc.get('tags', []),
                    "source": sc.get('source', 'manual'),
                    "responseLength": len(full_text or ''),
                    "citationCount": len(collected_search_results_batch or []),
                    "firstTokenMs": first_token_ms,
                    "lastTokenMs": last_token_ms,
                    "generationMs": generation_ms,
                    "httpStatus": http_status,
                    "completed": completed,
                    "partialResponse": is_partial,
                    "attempts": len(attempt_log),
                    "attemptLog": attempt_log,
                    # ── multi-turn 메타 ──
                    "turnResults": turn_results,
                    "turnsExecuted": len(turn_results),
                    "turnsTotal": len(turn_results),
                    "gptEval": gpt,
                    "consultationEval": consult,
                    "rubricEval": rubric_eval,
                    "guidelineVersion": gpt.get('guidelineVersion', '') if gpt else '',
                    "searchResults": collected_search_results_batch[:5] if collected_search_results_batch else [],
                }
            except Exception as e:
                err_type = type(e).__name__
                err_msg = str(e)[:300]
                if 'TimeoutError' in err_type or '타임아웃' in err_msg or 'timeout' in err_msg.lower():
                    err_cat = 'timeout_read' if ('read' in err_msg.lower() or '읽기' in err_msg) else 'timeout'
                elif 'HTTPError' in err_type:
                    err_cat = 'http_error'
                    try:
                        http_status = getattr(e, 'code', None)
                    except Exception:
                        pass
                elif 'URLError' in err_type or 'ConnectionError' in err_type:
                    err_cat = 'network_error'
                elif 'JSONDecodeError' in err_type:
                    err_cat = 'parse_error'
                elif 'ssl' in err_msg.lower() or 'SSL' in err_type:
                    err_cat = 'ssl_error'
                else:
                    err_cat = err_type or 'unknown'

                # 부분 응답 보존 + multi-turn turn_results 보존 (실패 지점 추적용)
                partial_now = full_text or ''
                partial_turn_results = turn_results or []
                if partial_now and len(partial_now) > len(best_partial_text):
                    best_partial_text = partial_now
                    best_partial_meta = {
                        'firstTokenMs': int((first_token_time - t0) * 1000) if first_token_time else None,
                        'lastTokenMs': int((last_token_time - t0) * 1000) if last_token_time else None,
                        'searchResults': (collected_search_results_batch or [])[:5],
                        'turnResults': partial_turn_results,
                    }
                elif partial_turn_results and not best_partial_meta:
                    best_partial_meta = {
                        'firstTokenMs': None, 'lastTokenMs': None, 'searchResults': [],
                        'turnResults': partial_turn_results,
                    }

                el = int((_time.time() - t0) * 1000)
                attempt_log.append({
                    'attempt': attempt + 1,
                    'ok': False,
                    'durationMs': el,
                    'httpStatus': http_status,
                    'errorCategory': err_cat,
                    'error': err_msg,
                    'partialLen': len(partial_now),
                })
                self.log(
                    f"[배치] sid={sid} attempt={attempt+1}/{max_retries+1} 실패: {err_cat} {err_msg[:120]} (partial={len(partial_now)} chars)"
                )

                if attempt < max_retries:
                    _time.sleep(2 ** attempt)
                    continue

                partial_meta = best_partial_meta or {}
                ft = partial_meta.get('firstTokenMs')
                lt = partial_meta.get('lastTokenMs')
                saved_turns = partial_meta.get('turnResults', []) or []
                return {
                    "scenarioId": sid,
                    "prompt": (saved_turns[-1]['query'] if saved_turns else sc.get('prompt', '')),
                    "response": best_partial_text,
                    "status": "error",
                    "responseTime": el,
                    "error": err_msg,
                    "errorCategory": err_cat,
                    "httpStatus": http_status,
                    "attempts": len(attempt_log),
                    "attemptLog": attempt_log,
                    "completed": False,
                    "partialResponse": bool(best_partial_text),
                    "firstTokenMs": ft,
                    "lastTokenMs": lt,
                    "generationMs": (lt - ft) if (ft is not None and lt is not None) else None,
                    "responseLength": len(best_partial_text or ''),
                    "category": sc.get('category', ''),
                    "subcategory": sc.get('subcategory', ''),
                    "riskLevel": sc.get('riskLevel', ''),
                    "source": sc.get('source', 'manual'),
                    "searchResults": partial_meta.get('searchResults', []),
                    # ── multi-turn 디버그 메타 (실패 지점 추적용) ──
                    "turnResults": saved_turns,
                    "turnsExecuted": len(saved_turns),
                    "turnsTotal": len(saved_turns),
                }

    # ────────────────────────────────────────────────────────────
    # 청크 기반 병렬 batch 실행
    # ────────────────────────────────────────────────────────────
    def run_batch(
        self,
        run_id,
        scenarios_map,
        scenario_ids,
        on_progress=None,
        on_result=None,
        max_workers=None,
        chunk_size=None,
        cancel_check=None,
        inter_submit_delay=0,
    ):
        """
        scenarios_map: dict {sid: scenario_dict} — 미리 로드된 시나리오 맵
        scenario_ids: list[str]
        on_progress(completed, total, current_sid): 매 결과마다 호출
        on_result(result_dict): 매 결과마다 호출 (점진 저장용)
        cancel_check() -> bool: True 시 중단
        반환: {'results': [...], 'passed': int, 'failed': int, 'errors': int, 'cancelled': bool}
        """
        max_workers = max_workers or self.DEFAULT_MAX_WORKERS
        chunk_size = chunk_size or self.DEFAULT_CHUNK_SIZE
        max_workers = min(max_workers, max(1, len(scenario_ids)))

        all_results = []
        passed = failed = errors = 0
        completed_count = 0
        cancelled = False
        total = len(scenario_ids)

        for chunk_start in range(0, total, chunk_size):
            if cancel_check and cancel_check():
                cancelled = True
                break

            chunk = scenario_ids[chunk_start: chunk_start + chunk_size]
            chunk_items = []
            for sid in chunk:
                sc = scenarios_map.get(sid)
                if not sc:
                    miss_result = {
                        "scenarioId": sid, "status": "error",
                        "error": "시나리오 없음", "prompt": "", "response": "", "responseTime": 0,
                    }
                    all_results.append(miss_result)
                    errors += 1
                    completed_count += 1
                    if on_result:
                        try:
                            on_result(miss_result)
                        except Exception as _e:
                            self.log(f"[배치] on_result 콜백 실패: {str(_e)[:120]}")
                    if on_progress:
                        try:
                            on_progress(completed_count, total, sid)
                        except Exception:
                            pass
                    continue
                chunk_items.append((sid, sc))

            if not chunk_items:
                continue

            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {}
                for i, (sid, sc) in enumerate(chunk_items):
                    if cancel_check and cancel_check():
                        cancelled = True
                        break
                    if i > 0 and inter_submit_delay > 0:
                        _time.sleep(inter_submit_delay)
                    futures[executor.submit(self.execute_single, sid, sc)] = sid

                for future in as_completed(futures):
                    if cancel_check and cancel_check():
                        cancelled = True
                        executor.shutdown(wait=False, cancel_futures=True)
                        break
                    result = future.result()
                    all_results.append(result)
                    completed_count += 1
                    if result['status'] == 'pass':
                        passed += 1
                    elif result['status'] == 'error':
                        errors += 1
                    else:
                        failed += 1
                    if on_result:
                        try:
                            on_result(result)
                        except Exception as _e:
                            self.log(f"[배치] on_result 콜백 실패: {str(_e)[:120]}")
                    if on_progress:
                        try:
                            on_progress(completed_count, total, result.get('scenarioId', ''))
                        except Exception:
                            pass

            if cancelled:
                break

        return {
            'results': all_results,
            'passed': passed,
            'failed': failed,
            'errors': errors,
            'cancelled': cancelled,
            'total': total,
            'completed': completed_count,
        }


def build_skix_config(settings, tester_uid=None):
    """settings dict 에서 SKIX 호출 설정 추출 (현재 환경 기준).

    Service 와 Job 둘 다 동일 환경 설정을 따른다.
    """
    current_env = settings.get('currentEnv', 'dev')
    env_defaults = {
        'dev':  {'apiUrl': 'https://dev-skix.phnyx.ai',     'xTenantDomain': 'dev-skix'},
        'stg':  {'apiUrl': 'https://staging-skix.phnyx.ai', 'xTenantDomain': 'staging-skix-test'},
        'prod': {'apiUrl': 'https://skix.phnyx.ai',         'xTenantDomain': 'prod-skix-test'},
    }
    env_cfg = settings.get('environments', {}).get(current_env, {})
    api_key = env_cfg.get('xApiKey', settings.get('xApiKey', ''))
    api_uid_default = env_cfg.get('xApiUid', settings.get('xApiUid', ''))
    tenant_domain = env_cfg.get('xTenantDomain', env_defaults.get(current_env, {}).get('xTenantDomain', 'dev-skix'))
    api_url = env_cfg.get('apiUrl', env_defaults.get(current_env, {}).get('apiUrl', 'https://dev-skix.phnyx.ai'))
    graph_type = settings.get('graphType', 'ORCHESTRATED_HYBRID_SEARCH')

    source_types = []
    if settings.get('srcWeb', True):
        source_types.append('WEB')
    if settings.get('srcPubmed', True):
        source_types.append('PUBMED')

    api_uid = tester_uid or api_uid_default or 'batch-test'

    return {
        'api_url': api_url,
        'api_key': api_key,
        'tenant_domain': tenant_domain,
        'api_uid': api_uid,
        'graph_type': graph_type,
        'source_types': source_types,
        'current_env': current_env,
    }

# -*- coding: utf-8 -*-
"""v3 판정 결과 뷰어 생성 — 실행 덤프(test_runs.results_json) → 필터 가능한 단일 HTML.

무엇을 보여주나
  결과 1건마다 법률 게이트 히트(규칙·심각도·수준·걸린 문장·검출기·사전/귀속 근거), 미충족 유효성(PV·SV)·UV
  항목(사유·문장·인용문), 판정 요약, 답변 원문(문장 번호 붙임, 걸린 문장 강조). 화면에서 실행·판정·등급·규칙·
  항목·카테고리·본문 검색으로 거른다.

걸린 문장 복원
  2026-10-19 이전 저장 형태(PR #48 전)는 legal_hit_detail[].quote 와 items[].sentence_idx 가 없다. 그래서
  판정기와 같은 전처리(mhc_viz.strip_blocks → claim_extractor.split_sentences)로 답변을 문장 목록으로 나누고
  claim_idx(주장 번호 = 문장 번호, 쪼갠 뒤 주장은 문장 수보다 큰 번호)로 문장을 찾는다. 새 형태(quote·
  sentence_idx 있음)는 그 값을 그대로 쓴다. 항목(PV·SV·UV)의 문장은 새 형태에만 있다.

사용
  python reports/v3_runs/build_eval_evidence_viewer.py --run PHR=<dump.json> --run 일반=<dump.json> \
      --out reports/v3_runs/eval_evidence_viewer_20261016.html [--title "..."] [--snapshot <ontology json>]
  덤프는 scripts/dump_run_to_gcs.py 가 만든 {id, run_at, results_json:[...]} 형태. 저장소에는 넣지 않는다.
"""
import argparse
import html
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "packages", "medical_eval", "src"))

ap = argparse.ArgumentParser()
ap.add_argument("--run", action="append", required=True, help="라벨=덤프경로 (여러 번)")
ap.add_argument("--out", required=True)
ap.add_argument("--title", default="v3 판정 결과 뷰어")
ap.add_argument("--snapshot", default=None, help="온톨로지 스냅샷 json(규칙·항목 제목). 없으면 최신 스냅샷")
ap.add_argument("--note", default="", help="머리말에 붙일 한 줄")
a = ap.parse_args()

KST = timezone(timedelta(hours=9))

try:
    import mhc_viz
    strip_blocks = mhc_viz.strip_blocks
except Exception:
    strip_blocks = lambda t: t
try:
    from medical_eval.claim_extractor import split_sentences
except Exception as e:
    print(f"[warn] medical_eval.claim_extractor 를 불러오지 못해 문장 복원을 건너뜁니다: {e}", file=sys.stderr)
    split_sentences = lambda t: []


def rule_titles(snapshot_path):
    """온톨로지 rule 표 → {id: title}. 스냅샷을 못 읽으면 빈 dict."""
    try:
        from medical_eval.ontology import latest_snapshot_path, load_snapshot
        p = snapshot_path or latest_snapshot_path(os.path.join(ROOT, "packages", "medical_eval", "ontology", "snapshot"))
        s = load_snapshot(p)
        return {str(r.get("id")): str(r.get("title") or "") for r in s.table("rule") if r.get("id")}, s.version
    except Exception as e:
        print(f"[warn] 규칙 제목을 읽지 못함: {e}", file=sys.stderr)
        return {}, None


TITLES, SNAP_VER = rule_titles(a.snapshot)


def load_run(label, path):
    d = json.load(open(path, encoding="utf-8"))
    rs = d.get("results_json") or d.get("results") or []
    return {"label": label, "id": d.get("id"), "run_at": d.get("run_at") or d.get("runAt"), "env": d.get("env"),
            "n": len(rs)}, rs


def hit_rows(v, sents):
    rows = []
    for h in (v.get("legal_hit_detail") or []):
        if not isinstance(h, dict):
            continue
        ci = h.get("claim_idx")
        si = h.get("sentence_idx")
        quote = h.get("quote")
        note = ""
        if quote is None and ci is not None:
            try:
                n = int(ci)
            except (TypeError, ValueError):
                n = None
            if n is not None and 1 <= n <= len(sents):
                quote = sents[n - 1]
                si = si if si is not None else n
            elif n is not None:
                note = f"주장 {n}은 쪼갠 뒤 주장(문장 {len(sents)}개 초과) — 원문 문장을 특정할 수 없음"
        rows.append({"rule_id": h.get("rule_id"), "severity": h.get("severity"), "level": h.get("level"),
                     "claim_idx": ci, "sentence_idx": si, "quote": quote, "note": note,
                     "detectors": h.get("detectors") or [], "evidence": h.get("evidence") or [],
                     "review": h.get("review"), "status": h.get("status"),
                     "kind": "review" if h.get("review") else "hit"})
    return rows


# 판정 요약(aggregate._unmet_lines)은 미충족 항목을 "SV SV-08 — 사유 (문장 3, 5)" 꼴로 적는다. 옛 저장 형태에는
# items[].sentence_idx 가 없으므로 이 괄호에서 문장 번호를 되찾는다. 항목 구분자 " / " 를 넘지 않게 "/" 는 사유에서 제외한다.
_SUMMARY_SPOT = re.compile(r"\b((?:PV|SV|UV)-\d{2})\b\s*[—-]\s*([^()\n/]*?)\s*\(문장\s*([0-9,\s]+)\)")


def summary_spots(v):
    text = (v.get("summary") or "") + "\n" + (v.get("summary_line") or "")
    out = {}
    for m in _SUMMARY_SPOT.finditer(text):
        nums = [int(x) for x in re.findall(r"\d+", m.group(3))]
        if nums:
            out.setdefault(m.group(1), nums)
    return out


def item_rows(items, sents, spots):
    out = []
    for it in (items or []):
        if not isinstance(it, dict) or not it.get("id"):
            continue
        si = it.get("sentence_idx") or []
        src = "stored" if si else ""
        if not si and it.get("result") == "unmet" and it["id"] in spots:
            si, src = spots[it["id"]], "summary"
        quotes = it.get("quotes") or []
        if not quotes and si:
            quotes = [sents[n - 1] for n in si if isinstance(n, int) and 1 <= n <= len(sents)][:3]
        out.append({"id": it["id"], "result": it.get("result"), "detail": it.get("detail"),
                    "sentence_idx": si, "quotes": quotes, "src": src})
    return out


def compact_result(label, r):
    v = r.get("evalV3") or {}
    answer = r.get("response") or ""
    judged = strip_blocks(answer) if answer else ""
    sents = split_sentences(judged) if judged else []
    spots = summary_spots(v)
    legal = v.get("legal_verdict")
    confirmed = bool(v.get("legal_hits"))
    final = ("FAIL" if legal == "fail" and confirmed else "FAIL(회신대기)" if legal == "fail"
             else (v.get("validity_grade") or "PASS"))
    return {
        "run": label, "id": r.get("scenarioId"), "cat": r.get("category") or "", "sub": r.get("subcategory") or "",
        "risk": r.get("riskLevel") or "", "case": r.get("phrCaseId") or "",
        "prompt": r.get("prompt") or "", "expected": r.get("expectedBehavior") or "",
        "answer": judged, "sents": sents,
        "err": v.get("error") or ("" if r.get("httpStatus", 200) == 200 else f"HTTP {r.get('httpStatus')}"),
        "final": final if not v.get("error") else "ERR",
        "legal": legal, "hits": v.get("legal_hits") or [], "review_hits": v.get("legal_review_hits") or [],
        "cap_hits": v.get("legal_cap_hits") or [], "max_level": v.get("legal_max_level"),
        "hit_rows": hit_rows(v, sents),
        "axis": v.get("validity_axis"), "vgrade": v.get("validity_grade"), "vstatus": v.get("validity_status"),
        "vunmet": v.get("validity_unmet") or [], "vitems": item_rows(v.get("validity_items"), sents, spots),
        "vanswer": v.get("validity_answer"), "grade_cap": v.get("grade_cap") or [],
        "uvgrade": v.get("uv_grade"), "uvunmet": v.get("uv_unmet") or [], "uvitems": item_rows(v.get("uv_items"), sents, spots),
        "intent": v.get("uv_intent"), "checklist": v.get("checklist"),
        "summary_line": v.get("summary_line") or "", "summary": v.get("summary") or "",
        "fallback": v.get("claim_fallback") or 0, "claims": v.get("claim_count"),
        "judge": v.get("judge_model"), "onto": v.get("ontology_version"), "evalv": v.get("eval_version"),
        "ttft": r.get("firstTokenMs"), "total_ms": r.get("responseTime"),
    }


runs, rows = [], []
for spec in a.run:
    label, _, path = spec.partition("=")
    meta, rs = load_run(label, path)
    runs.append(meta)
    rows.extend(compact_result(label, r) for r in rs)

quote_rows = sum(1 for x in rows for h in x["hit_rows"] if h["quote"])
hit_total = sum(len(x["hit_rows"]) for x in rows)
item_quote_rows = sum(1 for x in rows for it in x["vitems"] + x["uvitems"] if it["quotes"])
gen_at = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")

E = lambda s: html.escape(str(s if s is not None else ""))
run_lines = " · ".join(
    f"<b>{E(m['label'])}</b> {E(m['id'])} ({E(m['n'])}건{', ' + E(m['run_at'][:16].replace('T', ' ')) + 'Z' if m.get('run_at') else ''})"
    for m in runs)
unmet_total = sum(1 for x in rows for it in x["vitems"] + x["uvitems"] if it["result"] == "unmet")
cover = (f"법률 히트 {hit_total}건 중 문장 복원 {quote_rows}건 · 미충족 항목 {unmet_total}건 중 문장 복원 {item_quote_rows}건"
         " (나머지는 판정기가 문장을 지목하지 않은 항목 — red flag·필수 질문 누락처럼 '없음'을 보는 기준이 대부분)")

DATA = json.dumps({"rows": rows, "titles": TITLES, "runs": runs}, ensure_ascii=False).replace("</", "<\\/")

PAGE = r"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f6f7f9;--surface:#fff;--surface2:#eef1f5;--border:#dbe0e6;--text:#1a1f27;--dim:#5b6573;--accent:#2563eb;
--red:#dc2626;--orange:#ea7a1a;--yellow:#b7791f;--green:#15803d;--blue:#2563eb;--grey:#64748b}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:13px/1.55 system-ui,"Malgun Gothic",sans-serif}
header{background:var(--surface);border-bottom:1px solid var(--border);padding:14px 20px}
h1{margin:0 0 4px;font-size:18px}.meta{color:var(--dim);font-size:12px}
.bar{position:sticky;top:0;z-index:5;background:var(--surface);border-bottom:1px solid var(--border);padding:10px 20px;display:flex;flex-wrap:wrap;gap:10px 14px;align-items:flex-end}
.f{display:flex;flex-direction:column;gap:3px;font-size:11.5px;color:var(--dim)}
.f > select,.f > input{font:12.5px system-ui;padding:4px 6px;border:1px solid var(--border);border-radius:5px;background:#fff;color:var(--text);min-width:110px}
.f > select[multiple]{min-height:62px;min-width:150px}
.chips{display:flex;flex-wrap:wrap;gap:4px}.chk{display:inline-flex;align-items:center;gap:3px;padding:2px 7px;border:1px solid var(--border);border-radius:12px;background:#fff;cursor:pointer;font-size:12px;user-select:none}
.chk input{margin:0}.chk.on{background:#e8f0fe;border-color:var(--accent);color:var(--accent)}
button{font:12.5px system-ui;padding:5px 11px;border:1px solid var(--border);border-radius:6px;background:#fff;color:var(--text);cursor:pointer}
button.pri{background:var(--accent);color:#fff;border-color:var(--accent)}button:hover{filter:brightness(.97)}
.count{margin-left:auto;font-size:13px;color:var(--dim);align-self:center}.count b{color:var(--text)}
main{padding:12px 20px 60px}
.stats{display:flex;flex-wrap:wrap;gap:6px 14px;margin:0 0 12px;font-size:12px;color:var(--dim)}.stats b{color:var(--text)}
.card{background:var(--surface);border:1px solid var(--border);border-radius:8px;margin-bottom:8px}
.head{display:grid;grid-template-columns:150px 110px 1fr auto;gap:10px;align-items:center;padding:9px 12px;cursor:pointer}
.head:hover{background:#fafbfc}.id{font-weight:700;font-size:13px}.id small{display:block;font-weight:400;color:var(--dim);font-size:11px}
.q{color:var(--text);overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.badges{display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end}
.b{display:inline-block;padding:2px 8px;border-radius:5px;font-size:11.5px;font-weight:700;border:1px solid transparent;white-space:nowrap}
.b.FAIL{background:#fee2e2;color:var(--red)}.b.REV{background:#fef3c7;color:#92400e}.b.A{background:#dcfce7;color:var(--green)}.b.B{background:#ecfccb;color:#4d7c0f}
.b.C{background:#fef9c3;color:var(--yellow)}.b.D{background:#ffedd5;color:var(--orange)}.b.PASS{background:#e0f2fe;color:#0369a1}.b.NA{background:var(--surface2);color:var(--grey)}.b.ERR{background:#f1f5f9;color:#475569}
.tag{display:inline-block;padding:1px 7px;border-radius:4px;font-size:11.5px;margin:1px 3px 1px 0;background:var(--surface2);color:var(--text)}
.tag.rule{background:#fee2e2;color:var(--red)}.tag.rev{background:#fef3c7;color:#92400e}.tag.item{background:#ffedd5;color:var(--orange)}.tag.uv{background:#ede9fe;color:#6d28d9}
.body{display:none;border-top:1px solid var(--border);padding:12px 14px 14px}.card.open .body{display:block}
.sec{margin:10px 0 4px;font-size:12px;font-weight:700;color:var(--dim);text-transform:uppercase;letter-spacing:.3px}
.box{background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px 10px;white-space:pre-wrap;word-break:break-word}
table.ev{width:100%;border-collapse:collapse;font-size:12.5px}table.ev th{text-align:left;color:var(--dim);font-weight:700;padding:5px 6px;border-bottom:1px solid var(--border);white-space:nowrap}
table.ev td{padding:6px;border-bottom:1px solid var(--border);vertical-align:top;word-break:break-word}td.no{white-space:nowrap;color:var(--dim)}td.why{color:var(--dim);font-size:12px}
.sent{display:flex;gap:8px;padding:2px 0}.sent .n{color:var(--dim);min-width:34px;text-align:right;font-size:11.5px}.sent.hit{background:#fee2e2;border-radius:4px}.sent.hit .n{color:var(--red);font-weight:700}
.sent.item{background:#ffedd5;border-radius:4px}.sent.hit.item{background:linear-gradient(90deg,#fee2e2,#ffedd5)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:900px){.two{grid-template-columns:1fr}.head{grid-template-columns:1fr auto}.q{white-space:normal}}
.empty{color:var(--dim);padding:30px;text-align:center}
.note{font-size:12px;color:var(--dim);margin-top:6px}
</style></head><body>
<header><h1>__TITLE__</h1>
<div class="meta">__RUNS__</div>
<div class="meta">__COVER__ · 규칙 제목 온톨로지 __SNAP__ · 생성 __GEN__ __NOTE__</div>
</header>
<div class="bar">
  <div class="f">실행<div class="chips" id="fRun"></div></div>
  <div class="f">최종 판정<div class="chips" id="fFinal"></div></div>
  <div class="f">유효성 등급 (PV·SV)<div class="chips" id="fV"></div></div>
  <div class="f">UV 등급<div class="chips" id="fUV"></div></div>
  <div class="f">법률<div class="chips" id="fLegal"></div></div>
  <div class="f">걸린 규칙<select id="fRule" multiple></select></div>
  <div class="f">미충족 항목<select id="fItem" multiple></select></div>
  <div class="f">카테고리<select id="fCat" multiple></select></div>
  <div class="f">검색(질문·답변·사유·ID)<input id="fQ" placeholder="예: 당뇨, LG-02, PHRQR-B0005"></div>
  <div class="f">정렬<select id="fSort"><option value="sev">심각한 순</option><option value="id">ID</option><option value="run">실행 · ID</option></select></div>
  <div class="f">&nbsp;<div style="display:flex;gap:6px"><button class="pri" id="bD">D 등급만</button><button id="bFail">법률 FAIL만</button><button id="bReset">초기화</button><button id="bOpen">모두 펼치기</button><button id="bCsv">CSV</button></div></div>
  <div class="count"><b id="nShown">0</b> / <span id="nAll">0</span>건</div>
</div>
<main><div class="stats" id="stats"></div><div id="list"></div></main>
<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
const D = JSON.parse(document.getElementById('data').textContent);
const ROWS = D.rows, TITLES = D.titles || {};
const $ = s => document.querySelector(s);
const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const SEV = { 'FAIL': 0, 'FAIL(회신대기)': 1, 'ERR': 2, 'D': 3, 'C': 4, 'B': 5, 'A': 6, 'PASS': 7 };
const title = id => TITLES[id] ? ' — ' + TITLES[id] : '';

// ── 필터 상태 ──
const state = { run: new Set(), final: new Set(), v: new Set(), uv: new Set(), legal: new Set(), rule: new Set(), item: new Set(), cat: new Set(), q: '', sort: 'sev' };
const uniq = (arr) => Array.from(new Set(arr.filter(x => x != null && x !== ''))).sort();
function chips(el, key, values, labels) {
  el.innerHTML = '';
  values.forEach(v => {
    const l = document.createElement('label'); l.className = 'chk'; l.dataset.v = v;
    const c = document.createElement('input'); c.type = 'checkbox';
    c.addEventListener('change', () => { if (c.checked) state[key].add(v); else state[key].delete(v); l.classList.toggle('on', c.checked); render(); });
    l.appendChild(c); l.appendChild(document.createTextNode((labels && labels[v]) || v)); el.appendChild(l);
  });
}
function options(sel, key, values, withTitle) {
  sel.innerHTML = '';
  values.forEach(v => { const o = document.createElement('option'); o.value = v; o.textContent = v + (withTitle ? title(v) : ''); sel.appendChild(o); });
  sel.addEventListener('change', () => { state[key] = new Set(Array.from(sel.selectedOptions).map(o => o.value)); render(); });
}
const finals = ['FAIL', 'FAIL(회신대기)', 'A', 'B', 'C', 'D', 'PASS', 'ERR'].filter(v => ROWS.some(r => r.final === v));
chips($('#fRun'), 'run', uniq(ROWS.map(r => r.run)));
chips($('#fFinal'), 'final', finals);
chips($('#fV'), 'v', ['A', 'B', 'C', 'D', '없음'], { '없음': '없음(미채점)' });
chips($('#fUV'), 'uv', ['A', 'B', 'C', 'D', '없음'], { '없음': '없음(미채점)' });
chips($('#fLegal'), 'legal', ['pass', 'fail', 'fallback'], { pass: '통과', fail: '위반(회신대기 포함)', fallback: '주장 추출 폴백(판정 무효)' });
options($('#fRule'), 'rule', uniq(ROWS.flatMap(r => r.hit_rows.map(h => h.rule_id))), true);
options($('#fItem'), 'item', uniq(ROWS.flatMap(r => r.vunmet.concat(r.uvunmet))), true);
options($('#fCat'), 'cat', uniq(ROWS.map(r => r.cat)));
$('#fQ').addEventListener('input', e => { state.q = e.target.value.trim().toLowerCase(); render(); });
$('#fSort').addEventListener('change', e => { state.sort = e.target.value; render(); });
$('#nAll').textContent = ROWS.length;

function setChips(el, key, values) {
  state[key] = new Set(values);
  el.querySelectorAll('.chk').forEach(l => { const on = values.indexOf(l.dataset.v) >= 0; l.classList.toggle('on', on); l.querySelector('input').checked = on; });
}
function resetAll() {
  ['fRun', 'fFinal', 'fV', 'fUV', 'fLegal'].forEach((id, i) => setChips($('#' + id), ['run', 'final', 'v', 'uv', 'legal'][i], []));
  ['fRule', 'fItem', 'fCat'].forEach((id, i) => { const s = $('#' + id); Array.from(s.options).forEach(o => o.selected = false); state[['rule', 'item', 'cat'][i]] = new Set(); });
  $('#fQ').value = ''; state.q = '';
}
$('#bReset').addEventListener('click', () => { resetAll(); render(); });
$('#bD').addEventListener('click', () => { resetAll(); setChips($('#fV'), 'v', ['D']); setChips($('#fUV'), 'uv', ['D']); state.anyD = true; render(); });
$('#bFail').addEventListener('click', () => { resetAll(); setChips($('#fLegal'), 'legal', ['fail']); render(); });
$('#bOpen').addEventListener('click', () => { const cards = document.querySelectorAll('.card'); const allOpen = Array.from(cards).every(c => c.classList.contains('open')); cards.forEach(c => c.classList.toggle('open', !allOpen)); });

function match(r) {
  if (state.run.size && !state.run.has(r.run)) return false;
  if (state.final.size && !state.final.has(r.final)) return false;
  const vg = r.vgrade || '없음', ug = r.uvgrade || '없음';
  if (state.anyD) { if (!(vg === 'D' || ug === 'D')) return false; }
  else {
    if (state.v.size && !state.v.has(vg)) return false;
    if (state.uv.size && !state.uv.has(ug)) return false;
  }
  if (state.legal.size) {
    const ok = (state.legal.has('pass') && r.legal === 'pass') || (state.legal.has('fail') && r.legal === 'fail') || (state.legal.has('fallback') && r.fallback > 0);
    if (!ok) return false;
  }
  if (state.rule.size && !r.hit_rows.some(h => state.rule.has(h.rule_id))) return false;
  if (state.item.size && !r.vunmet.concat(r.uvunmet).some(id => state.item.has(id))) return false;
  if (state.cat.size && !state.cat.has(r.cat)) return false;
  if (state.q) {
    const hay = [r.id, r.prompt, r.answer, r.summary_line, r.summary, r.cat, r.sub,
      r.hit_rows.map(h => h.rule_id + ' ' + (h.quote || '')).join(' '),
      r.vitems.concat(r.uvitems).map(i => i.id + ' ' + (i.detail || '')).join(' ')].join('\n').toLowerCase();
    if (hay.indexOf(state.q) < 0) return false;
  }
  return true;
}
// 'D 등급만' 은 유효성 또는 UV 가 D(OR). 칩을 직접 바꾸면 AND 로 돌아간다.
['fV', 'fUV', 'fFinal', 'fLegal', 'fRun'].forEach(id => $('#' + id).addEventListener('change', () => { state.anyD = false; }));

const badge = (txt, cls) => `<span class="b ${cls}">${esc(txt)}</span>`;
function finalBadge(r) {
  if (r.final === 'FAIL') return badge('FAIL', 'FAIL');
  if (r.final === 'FAIL(회신대기)') return badge('FAIL·회신대기', 'REV');
  if (r.final === 'ERR') return badge('오류', 'ERR');
  return badge(r.final, r.final);
}
const gradeBadge = (label, g) => badge(label + ' ' + (g || '—'), g || 'NA');

function evidenceText(list) {
  return (Array.isArray(list) ? list : []).map(e => {
    if (!e || typeof e !== 'object') return '';
    const head = e.kind || e.basis || '', body = e.phrase || e.text || e.example_code || e.department || '';
    let why = e.rationale || '';
    if (e.person_attributed != null) why = (why ? why + ' · ' : '') + '사람 귀속 ' + (e.person_attributed ? '예' : '아니오');
    if (e.attrib_source) why = (why ? why + ' · ' : '') + '출처 ' + e.attrib_source;
    return [head, body ? '「' + body + '」' : '', why].filter(Boolean).join(' ');
  }).filter(Boolean).join(' / ');
}

function evidenceTable(r) {
  const rows = [];
  r.hit_rows.forEach(h => rows.push({
    cls: h.kind === 'review' ? 'rev' : 'rule', id: h.rule_id, verdict: [h.severity, h.level].filter(Boolean).join(' · ') + (h.review ? ' · 법무 회신 대기' : ''),
    sent: h.sentence_idx != null ? ['문장 ' + h.sentence_idx] : (h.claim_idx != null ? ['주장 ' + h.claim_idx] : []),
    quotes: h.quote ? [h.quote] : [], why: [h.detectors.length ? '검출 ' + h.detectors.join(', ') : '', evidenceText(h.evidence), h.note].filter(Boolean).join(' — ')
  }));
  r.vitems.concat(r.uvitems).forEach(it => { if (it.result !== 'unmet') return; rows.push({
    cls: /^UV/.test(it.id) ? 'uv' : 'item', id: it.id, verdict: '미충족', sent: (it.sentence_idx || []).map(n => '문장 ' + n), quotes: it.quotes || [], why: it.detail || ''
  }); });
  if (r.grade_cap && r.grade_cap.length) rows.push({ cls: 'item', id: r.grade_cap.join(', '), verdict: '등급 상한 C', sent: [], quotes: [], why: '이 규칙 때문에 등급이 더 올라가지 않음' });
  if (!rows.length) return '<div class="note">걸린 규칙·미충족 항목 없음</div>';
  return `<table class="ev"><thead><tr><th>기준</th><th>판정</th><th>문장</th><th>걸린 구문</th><th>사유 · 근거</th></tr></thead><tbody>` +
    rows.map(x => `<tr><td style="white-space:nowrap"><span class="tag ${x.cls}" title="${esc(TITLES[x.id] || '')}">${esc(x.id)}</span><div class="note" style="margin:2px 0 0;max-width:220px;white-space:normal">${esc(TITLES[x.id] || '')}</div></td>` +
      `<td style="white-space:nowrap">${esc(x.verdict)}</td><td class="no">${x.sent.length ? esc(x.sent.join(', ')) : '—'}</td>` +
      `<td>${x.quotes.length ? x.quotes.map(q => '<div>「' + esc(q) + '」</div>').join('') : '<span style="color:var(--dim)">—</span>'}</td><td class="why">${esc(x.why) || '—'}</td></tr>`).join('') +
    `</tbody></table>`;
}

function answerHtml(r) {
  const hitSet = new Set(r.hit_rows.map(h => h.sentence_idx).filter(n => n != null));
  const itemSet = new Set(r.vitems.concat(r.uvitems).flatMap(it => it.result === 'unmet' ? (it.sentence_idx || []) : []));
  if (!r.sents.length) return `<div class="box">${esc(r.answer) || '(답변 없음)'}</div>`;
  return '<div class="box" style="white-space:normal">' + r.sents.map((s, i) => {
    const n = i + 1, cls = (hitSet.has(n) ? ' hit' : '') + (itemSet.has(n) ? ' item' : '');
    return `<div class="sent${cls}"><span class="n">${n}</span><span>${esc(s)}</span></div>`;
  }).join('') + '</div>';
}

function card(r, i) {
  const rules = r.hit_rows.map(h => `<span class="tag ${h.kind === 'review' ? 'rev' : 'rule'}" title="${esc(TITLES[h.rule_id] || '')}">${esc(h.rule_id)}</span>`).join('');
  const items = r.vunmet.map(id => `<span class="tag item" title="${esc(TITLES[id] || '')}">${esc(id)}</span>`).join('') + r.uvunmet.map(id => `<span class="tag uv" title="${esc(TITLES[id] || '')}">${esc(id)}</span>`).join('');
  return `<div class="card" data-i="${i}">
  <div class="head">
    <div class="id">${esc(r.id)}<small>${esc(r.run)} · ${esc(r.cat)}${r.sub ? ' / ' + esc(r.sub) : ''}${r.case ? ' · ' + esc(r.case) : ''}</small></div>
    <div class="badges" style="justify-content:flex-start">${finalBadge(r)}</div>
    <div><div class="q" title="${esc(r.prompt)}">${esc(r.prompt)}</div><div>${rules}${items}${r.fallback ? '<span class="tag" style="background:#f1f5f9;color:#475569">폴백 ' + r.fallback + '</span>' : ''}</div></div>
    <div class="badges">${badge('법률 ' + (r.legal === 'fail' ? '위반' : r.legal === 'pass' ? '통과' : '—'), r.legal === 'fail' ? 'FAIL' : r.legal === 'pass' ? 'PASS' : 'NA')}${gradeBadge(r.axis || '유효성', r.vgrade)}${gradeBadge('UV', r.uvgrade)}</div>
  </div>
  <div class="body">
    <div class="two"><div><div class="sec">질문</div><div class="box">${esc(r.prompt)}</div>${r.expected ? `<div class="sec">기대 동작</div><div class="box">${esc(r.expected)}</div>` : ''}</div>
    <div><div class="sec">판정 요약</div><div class="box">${esc(r.summary_line)}${r.summary && r.summary !== r.summary_line ? '\n\n' + esc(r.summary) : ''}${r.err ? '\n⚠ ' + esc(r.err) : ''}</div>
    <div class="note">${esc([r.evalv, r.onto ? '온톨로지 ' + r.onto : '', r.judge, r.claims != null ? '주장 ' + r.claims + '개' : '', r.intent ? '의도 ' + r.intent : '', r.vanswer ? '정답 ' + r.vanswer : ''].filter(Boolean).join(' · '))}</div></div></div>
    <div class="sec">구문별 판정 근거 — 어떤 문장이 어떤 기준으로 판정됐는지</div>${evidenceTable(r)}
    <div class="sec">답변 원문 (판정기가 본 문장 단위, 붉은 줄 = 법률 히트, 주황 줄 = 미충족 항목 문장)</div>${answerHtml(r)}
  </div></div>`;
}

let shown = [];
function render() {
  shown = ROWS.filter(match);
  const key = state.sort;
  shown.sort((a, b) => key === 'id' ? a.id.localeCompare(b.id) : key === 'run' ? (a.run + a.id).localeCompare(b.run + b.id)
    : (SEV[a.final] - SEV[b.final]) || ((SEV[a.vgrade] || 9) - (SEV[b.vgrade] || 9)) || ((SEV[a.uvgrade] || 9) - (SEV[b.uvgrade] || 9)) || a.id.localeCompare(b.id));
  $('#nShown').textContent = shown.length;
  const cnt = (f) => shown.filter(f).length;
  $('#stats').innerHTML = [
    `법률 위반 <b>${cnt(r => r.final === 'FAIL')}</b> (회신대기만 ${cnt(r => r.final === 'FAIL(회신대기)')})`,
    `유효성 D <b>${cnt(r => r.vgrade === 'D')}</b> · C ${cnt(r => r.vgrade === 'C')} · B ${cnt(r => r.vgrade === 'B')} · A ${cnt(r => r.vgrade === 'A')}`,
    `UV D <b>${cnt(r => r.uvgrade === 'D')}</b> · C ${cnt(r => r.uvgrade === 'C')} · B ${cnt(r => r.uvgrade === 'B')} · A ${cnt(r => r.uvgrade === 'A')}`,
    `폴백 ${cnt(r => r.fallback > 0)}`,
  ].map(s => '<span>' + s + '</span>').join('');
  const list = $('#list');
  list.innerHTML = shown.length ? shown.map((r, i) => card(r, i)).join('') : '<div class="empty">조건에 맞는 결과가 없습니다</div>';
  list.querySelectorAll('.head').forEach(h => h.addEventListener('click', () => h.parentElement.classList.toggle('open')));
}

$('#bCsv').addEventListener('click', () => {
  const cols = ['run', 'id', 'category', 'subcategory', 'final', 'legal', 'rules', 'validity_axis', 'validity_grade', 'validity_unmet', 'uv_grade', 'uv_unmet', 'hit_quotes', 'unmet_reasons', 'summary_line', 'prompt'];
  const q = x => { x = x == null ? '' : String(x); return /[",\n]/.test(x) ? '"' + x.replace(/"/g, '""') + '"' : x; };
  const lines = [cols.join(',')].concat(shown.map(r => [r.run, r.id, r.cat, r.sub, r.final, r.legal, r.hit_rows.map(h => h.rule_id).join('|'), r.axis, r.vgrade, r.vunmet.join('|'), r.uvgrade, r.uvunmet.join('|'),
    r.hit_rows.map(h => h.rule_id + (h.sentence_idx != null ? '@문장' + h.sentence_idx : '') + (h.quote ? '「' + h.quote + '」' : '')).join('|'),
    r.vitems.concat(r.uvitems).filter(i => i.result === 'unmet').map(i => i.id + ': ' + (i.detail || '')).join('|'), r.summary_line, r.prompt].map(q).join(',')));
  const blob = new Blob(['﻿' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = 'eval_evidence_filtered.csv'; a.click();
});

render();
})();
</script></body></html>
"""

out = (PAGE.replace("__TITLE__", E(a.title)).replace("__RUNS__", run_lines).replace("__COVER__", E(cover))
       .replace("__SNAP__", E(SNAP_VER or "?")).replace("__GEN__", gen_at).replace("__NOTE__", E(a.note)).replace("__DATA__", DATA))
os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
with open(a.out, "w", encoding="utf-8") as f:
    f.write(out)

c = Counter(r["final"] for r in rows)
print(f"[viewer] {len(rows)}건 → {a.out} ({os.path.getsize(a.out) / 1e6:.1f} MB)")
print(f"[viewer] 최종 판정 분포: {dict(c)}")
print(f"[viewer] 유효성 D {sum(1 for r in rows if r['vgrade'] == 'D')} · UV D {sum(1 for r in rows if r['uvgrade'] == 'D')} · {cover}")

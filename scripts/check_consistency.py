#!/usr/bin/env python3
"""RAG 분리(Phase 4) 소스 정합성 게이트.

모든 작업 패키지 완료 시 qa-gate 에이전트가 실행한다. 위반 시 exit 1.
ALLOWED_COUPLINGS 는 Phase 진행에 따라 줄어드는 허용목록이며,
항목 제거가 곧 해당 결합 절단의 완료 정의(Definition of Done)다.

사용:
    python scripts/check_consistency.py            # 전체 검사
    python scripts/check_consistency.py --fast     # import 경계 + 계약만 (컴파일/JS 생략)

주의: Windows 콘솔(cp949) 호환을 위해 출력은 ASCII 만 사용한다.
"""
import ast
import glob
import json
import os
import py_compile
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 모듈 소유권 분류 (docs/rag_phase4_split_plan.md 의 분류 매트릭스와 동기) ──
RAG_MODULES = {
    'rag_server', 'rag_routes', 'rag_engine', 'rag_db',
    'llm_router', 'citation_verifier', 'embedding_provider', 'retrieval_router',
    'pii_masker', 'medical_classifier', 'evidence_pack', 'review_queue',
    'kb_ingest', 'kb_stats', 'kb_rag_audit',
    'seed_kb_phase1', 'seed_faq_kb', 'seed_emergency_kb', 'seed_consultation_kb',
    'seed_legal_kb', 'seed_dur', 'seed_kb_external',
    'collect_public_kb', 'backfill_evidence_topic', 'medical_rag_pipeline',
    'rag_gap_analysis',
    'debug_rag', 'diagnose_rag_env', 'verify_kb_health_kdca', 'copy_kb_to_dev',
    'verify_db_005', 'reembed_missing', 'dur_collector',
}
SHARED_MODULES = {
    'db',  # 과도기 facade (4-B 이후 dbcommon 직접 import 로 수렴)
    'dbcommon', 'analyzer', 'config', 'guideline_loader', 'consultation_loader',
}

# ── 허용된 경계 결합 (줄어들기만 해야 함) ──
# (importing_file, imported_module): 사유 + 제거 시점
ALLOWED_COUPLINGS = {
    ('proxy_server', 'rag_routes'): 'in-process mode mixin (remove in 4-E)',
}
# 래칫: 이 수를 넘으면 FAIL (결합 절단 완료 시 함께 줄인다. 늘리기 금지)
MAX_ALLOWED_COUPLINGS = 1

# ── tests/, scripts/ 경계 (qa-gate 감사 P1/P2 반영) ──
# RAG 와 HOST '비공유' 모듈을 동시에 import 하는 테스트 = repo 분리 시 양쪽 어디서도
# 실행 불가. 신규 발생 즉시 FAIL. (db facade 동시 사용은 4-B 에서 dbcommon 으로 수렴 — WARN)
ALLOWED_TEST_BOTH = {
    # 'tests/xxx.py': '사유 + 해소 시점',
}

# ── RagRoutesMixin 헬퍼 계약: rag_routes 가 self._xxx 로 기대하는 메서드는
#    proxy_server(ProxyHandler) 와 rag_server(RagHandler) 양쪽에 있어야 함 ──
# 알려진 한계(qa-gate 감사 2-B): 직접 호출(self._x(...))만 탐지. getattr/property 등
# 동적 접근은 미탐지 — rag_routes 에 동적 디스패치 도입 금지(프로토콜 규칙).
MIXIN_HOSTS = ['proxy_server.py', 'rag_server.py']

# ── 공유 패키지 공개 심볼 계약 (4-B 패키지화 시 __init__ 재export 목록의 원본) ──
SHARED_SYMBOL_CONTRACT = {
    'dbcommon': ['get_conn', '_p', '_ph', '_upsert', '_row_to_dict',
                 '_pg_json_loads', '_now', '_ensure_pool', 'DB_PATH'],
    'analyzer': ['ComplianceAnalyzer'],
    'config': ['reload_violation_rules', 'get_guideline_version'],
    'guideline_loader': ['get_fixed_notices'],
    'consultation_loader': ['load_checklists_raw', 'load_checklists_by_symptom'],
}

DATA_FILES = ['guidelines.json', 'violation_rules.json', 'consultation_checklists.json']

HTML_EXCLUDE = set()  # 검사 제외 HTML (사유 명기 후 추가)

failures = []
warnings = []


def fail(check, msg):
    failures.append((check, msg))
    print('[FAIL][%s] %s' % (check, msg))


def warn(check, msg):
    warnings.append((check, msg))
    print('[WARN][%s] %s' % (check, msg))


def ok(check, msg):
    print('[ OK ][%s] %s' % (check, msg))


def _read(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        return f.read()


# ── [1] Python 컴파일 ──
def check_py_compile():
    targets = sorted(glob.glob(os.path.join(ROOT, '*.py')))
    targets.append(os.path.join(ROOT, 'migrations', 'migrate_runner.py'))
    # 4-B: packages/ 하위 Python 파일도 컴파일 검사에 포함
    pkg_py = sorted(glob.glob(os.path.join(ROOT, 'packages', '**', '*.py'), recursive=True))
    targets.extend(pkg_py)
    bad = 0
    for p in targets:
        try:
            py_compile.compile(p, doraise=True)
        except Exception as e:
            bad += 1
            fail('py-compile', '%s: %s' % (os.path.relpath(p, ROOT), str(e)[:160]))
    if not bad:
        ok('py-compile', '%d files' % len(targets))


# ── [2] HTML 내 JS 문법 ──
def check_js_syntax():
    htmls = [os.path.basename(p) for p in glob.glob(os.path.join(ROOT, '*.html'))
             if os.path.basename(p) not in HTML_EXCLUDE]
    node_script = (
        "const fs=require('fs');let bad=0;"
        "for(const f of process.argv.slice(1)){"
        "const html=fs.readFileSync(f,'utf8');"
        "const m=html.match(/<script>([\\s\\S]*?)<\\/script>/g)||[];"
        "for(const t of m){const c=t.replace(/<\\/?script>/g,'');"
        "if(c.length<500)continue;"
        "try{new Function(c)}catch(e){bad++;console.log('ERR '+f+': '+e.message)}}}"
        "process.exit(bad?1:0);"
    )
    try:
        r = subprocess.run(['node', '-e', node_script] + htmls,
                           cwd=ROOT, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        warn('js-syntax', 'node not found - skipped')
        return
    if r.returncode != 0:
        for line in (r.stdout or '').strip().splitlines():
            fail('js-syntax', line[:200])
    else:
        ok('js-syntax', '%d html files' % len(htmls))


# ── [3] 데이터 JSON 파싱 ──
def check_data_json():
    for name in DATA_FILES:
        p = os.path.join(ROOT, name)
        if not os.path.exists(p):
            fail('json-data', name + ' missing')
            continue
        try:
            json.loads(_read(p))
        except Exception as e:
            fail('json-data', '%s: %s' % (name, str(e)[:120]))
    if not any(c == 'json-data' for c, _ in failures):
        ok('json-data', '%d files parse' % len(DATA_FILES))


# ── [3b] JSON 번들 동기 (B5) — 루트 vs 패키지 사본 드리프트 차단 ──
# 배경: rag_engine.py:61 등 RAG 5파일이 루트 JSON 을 __file__ 로 직접 읽고,
# compliance_rules 패키지는 번들 사본을 읽는다(과도기 이중 사본). 드리프트 시
# 생성(루트)과 평가(번들)가 다른 룰을 쓰게 되므로 해시 불일치 = 즉시 FAIL.
# 4-E 에서 RAG 5파일이 패키지 참조로 전환되면 이 검사와 루트 사본을 함께 제거.
_BUNDLE_DIR = os.path.join('packages', 'medical_shared', 'compliance_rules')


def check_json_bundle_sync():
    import hashlib
    bad = 0
    for name in DATA_FILES:
        root_p = os.path.join(ROOT, name)
        pkg_p = os.path.join(ROOT, _BUNDLE_DIR, name)
        if not os.path.exists(pkg_p):
            bad += 1
            fail('json-bundle-sync', 'package copy missing: ' + name)
            continue
        with open(root_p, 'rb') as f:
            h_root = hashlib.sha256(f.read()).hexdigest()
        with open(pkg_p, 'rb') as f:
            h_pkg = hashlib.sha256(f.read()).hexdigest()
        if h_root != h_pkg:
            bad += 1
            fail('json-bundle-sync',
                 '%s differs (root %s != pkg %s) - sync both copies'
                 % (name, h_root[:12], h_pkg[:12]))
    if not bad:
        ok('json-bundle-sync', '%d files in sync (root == package bundle)' % len(DATA_FILES))


# ── [4] 공유 심볼 계약 ──
def check_shared_symbols():
    sys.path.insert(0, ROOT)
    bad = 0
    for mod_name, symbols in SHARED_SYMBOL_CONTRACT.items():
        try:
            mod = __import__(mod_name)
        except Exception as e:
            bad += 1
            fail('shared-symbols', 'import %s: %s' % (mod_name, str(e)[:120]))
            continue
        for s in symbols:
            if not hasattr(mod, s):
                bad += 1
                fail('shared-symbols', '%s.%s missing' % (mod_name, s))
    if not bad:
        n = sum(len(v) for v in SHARED_SYMBOL_CONTRACT.values())
        ok('shared-symbols', '%d symbols across %d modules' % (n, len(SHARED_SYMBOL_CONTRACT)))


# ── [5] RagRoutesMixin 헬퍼 계약 ──
def check_mixin_contract():
    src = _read(os.path.join(ROOT, 'rag_routes.py'))
    used = set(re.findall(r'self\.(_[a-zA-Z0-9_]+)\s*\(', src))
    defined_in_mixin = set(re.findall(r'def\s+(_[a-zA-Z0-9_]+)\s*\(', src))
    needed = sorted(used - defined_in_mixin)
    bad = 0
    for host in MIXIN_HOSTS:
        hsrc = _read(os.path.join(ROOT, host))
        have = set(re.findall(r'def\s+(_[a-zA-Z0-9_]+)\s*\(', hsrc))
        missing = [m for m in needed if m not in have]
        if missing:
            bad += 1
            fail('mixin-contract', '%s missing helpers: %s' % (host, ', '.join(missing)))
    if not bad:
        ok('mixin-contract', '%d helpers x %d hosts' % (len(needed), len(MIXIN_HOSTS)))


# ── [6] import 경계 (핵심: 줄어들기만 해야 하는 결합) ──
def _imports_of(path):
    import warnings as _w
    try:
        with _w.catch_warnings():
            _w.simplefilter('ignore', SyntaxWarning)
            tree = ast.parse(_read(path))
    except SyntaxError:
        return set()
    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                mods.add(a.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split('.')[0])
    return mods


def check_import_boundary():
    root_py = {os.path.splitext(os.path.basename(p))[0]: p
               for p in glob.glob(os.path.join(ROOT, '*.py'))}
    local = set(root_py)
    violations = 0
    used_allow = set()
    for name, path in sorted(root_py.items()):
        owner = 'RAG' if name in RAG_MODULES else ('SHARED' if name in SHARED_MODULES else 'HOST')
        for imp in sorted(_imports_of(path) & local):
            tgt = 'RAG' if imp in RAG_MODULES else ('SHARED' if imp in SHARED_MODULES else 'HOST')
            bad = (
                (owner == 'RAG' and tgt == 'HOST') or
                (owner == 'HOST' and tgt == 'RAG') or
                (owner == 'SHARED' and tgt != 'SHARED')
            )
            if not bad:
                continue
            if (name, imp) in ALLOWED_COUPLINGS:
                used_allow.add((name, imp))
                continue
            violations += 1
            fail('import-boundary', '%s(%s) -> %s(%s)' % (name, owner, imp, tgt))
    for (a, b), reason in sorted(ALLOWED_COUPLINGS.items()):
        if (a, b) in used_allow:
            print('       allowed: %s -> %s  [%s]' % (a, b, reason))
        else:
            warn('import-boundary',
                 'stale allowlist entry %s -> %s (coupling gone - remove it): %s' % (a, b, reason))
    if len(ALLOWED_COUPLINGS) > MAX_ALLOWED_COUPLINGS:
        fail('import-boundary',
             'ALLOWED_COUPLINGS grew to %d (max %d) - couplings may only be removed'
             % (len(ALLOWED_COUPLINGS), MAX_ALLOWED_COUPLINGS))
    if not violations:
        ok('import-boundary', '%d root modules scanned, %d allowed couplings remain'
           % (len(root_py), len(used_allow)))


# ── [6b] tests/, scripts/ 경계 (분리 시 실행 불가 파일 조기 탐지) ──
def check_test_boundary():
    files = (glob.glob(os.path.join(ROOT, 'tests', '*.py')) +
             glob.glob(os.path.join(ROOT, 'scripts', '*.py')))
    root_local = {os.path.splitext(os.path.basename(q))[0]
                  for q in glob.glob(os.path.join(ROOT, '*.py'))}
    host_local = root_local - RAG_MODULES - SHARED_MODULES
    both, rag_only, facade_users = [], [], []
    for p in sorted(files):
        rel = os.path.relpath(p, ROOT).replace('\\', '/')
        imps = _imports_of(p)
        has_rag = bool(imps & RAG_MODULES)
        has_host = bool(imps & host_local)
        if has_rag and has_host:
            both.append(rel)
        elif has_rag:
            rag_only.append(rel)
            if 'db' in imps:
                facade_users.append(rel)
    bad = 0
    for rel in both:
        if rel in ALLOWED_TEST_BOTH:
            print('       allowed: %s  [%s]' % (rel, ALLOWED_TEST_BOTH[rel]))
        else:
            bad += 1
            fail('test-boundary',
                 '%s imports both RAG and HOST modules - unrunnable after split' % rel)
    for rel in sorted(ALLOWED_TEST_BOTH):
        if rel not in both:
            warn('test-boundary', 'stale ALLOWED_TEST_BOTH entry: ' + rel)
    if facade_users:
        warn('test-boundary',
             '%d RAG test(s) import db facade (migrate to dbcommon in 4-B): %s'
             % (len(facade_users), ', '.join(facade_users[:6])
                + (' ...' if len(facade_users) > 6 else '')))
    if not bad:
        ok('test-boundary',
           '%d files scanned: %d RAG-only (move in 4-E), %d both-allowed'
           % (len(files), len(rag_only), len(both) - bad))


# ── [7] 마이그레이션 파일 규약 ──
def check_migrations():
    mig_dir = os.path.join(ROOT, 'migrations')
    sqls = sorted(os.path.basename(p) for p in glob.glob(os.path.join(mig_dir, '*.sql')))
    bad = 0
    for s in sqls:
        if not re.match(r'^\d{3}_[a-z0-9_]+\.sql$', s):
            bad += 1
            fail('migrations', 'bad filename: ' + s)
    if not os.path.exists(os.path.join(mig_dir, 'migrate_runner.py')):
        bad += 1
        fail('migrations', 'migrate_runner.py missing')
    if not bad:
        ok('migrations', '%d sql files, naming ok' % len(sqls))


def main():
    fast = '--fast' in sys.argv
    os.chdir(ROOT)
    print('=== check_consistency (root=%s)%s ===' % (ROOT, ' [fast]' if fast else ''))
    if not fast:
        check_py_compile()
        check_js_syntax()
    check_data_json()
    check_json_bundle_sync()
    check_shared_symbols()
    check_mixin_contract()
    check_import_boundary()
    check_test_boundary()
    check_migrations()
    print('=== result: %d failure(s), %d warning(s) ===' % (len(failures), len(warnings)))
    sys.exit(1 if failures else 0)


if __name__ == '__main__':
    main()

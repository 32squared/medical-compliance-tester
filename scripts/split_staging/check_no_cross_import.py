#!/usr/bin/env python3
"""경계 검사 라이트 — repo 분리 후 교차 import 금지 검사.

양쪽 repo에 복사해 사용한다.

사용법:
    # 호스트 repo에서 (RAG 모듈 import 금지):
    python scripts/split_staging/check_no_cross_import.py --forbid rag

    # RAG repo에서 (호스트 모듈 import 금지):
    python scripts/split_staging/check_no_cross_import.py --forbid host

반환:
    exit 0 — 위반 없음
    exit 1 — 위반 1건 이상

모듈 목록 출처: scripts/check_consistency.py RAG_MODULES / HOST_CORE_MODULES
(check_consistency.py 가 없는 환경(분리 후 RAG repo)에서는 하드코딩 목록 사용)
"""
import ast
import glob
import os
import sys

# ── 모듈 목록 (scripts/check_consistency.py RAG_MODULES 하드카피) ──────────
# 출처: scripts/check_consistency.py RAG_MODULES (2026-06-10, 4-E 사전조사 기준)
# 이 목록이 분리 실행 전 check_consistency.py와 동기화돼 있어야 한다.
_RAG_MODULES = {
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
    'reindex_korean_tsv',
}

# 호스트 핵심 모듈 (분리 후 RAG repo에서 import 금지)
# 출처: docs/rag_phase4_split_plan.md 4-E "호스트 잔류" 목록
_HOST_MODULES = {
    'proxy_server', 'batch_executor', 'job_runner', 'runner',
    'batch_eval_rag', 'rag_legal_eval', 'rag_consultation_eval',
    'dashboard', 'main',
}


def _imports_of(path: str) -> set:
    """소스 파일의 모든 import 대상 최상위 모듈명을 수집.

    check_consistency.py 의 _imports_of 로직 재사용.
    """
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            src = f.read()
    except OSError:
        return set()

    import warnings as _w
    try:
        with _w.catch_warnings():
            _w.simplefilter('ignore', SyntaxWarning)
            tree = ast.parse(src)
    except SyntaxError:
        return set()

    mods = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split('.')[0])
    return mods


def _scan(root: str, forbidden: set, skip_own: set) -> list:
    """root 아래 *.py 를 재귀 스캔해 forbidden 모듈을 import하는 파일 목록 반환.

    skip_own: 스캔을 건너뛸 모듈명 집합(금지 대상과 같은 repo 소유 파일).
      - --forbid rag 시: RAG 파일끼리의 import는 정상이므로 RAG 파일 자신을 제외.
      - --forbid host 시: HOST 파일끼리의 import는 정상이므로 HOST 파일 자신을 제외.
    분리 완료 후에는 금지 대상 파일이 아예 존재하지 않으므로 이 제외가 의미 없어진다.
    """
    violations = []
    patterns = [
        os.path.join(root, '*.py'),
        os.path.join(root, 'tests', '*.py'),
        os.path.join(root, 'scripts', '*.py'),
        os.path.join(root, 'migrations', '*.py'),
    ]
    # 분리 전 모노레포에서, 이 파일의 "프로젝트 로컬 import" 전부가 forbidden 집합에
    # 속하면 이 파일 자체가 그쪽 repo 소유(분리 후엔 이쪽에 없음) — 이 집합을 미리 구성.
    # all_known = RAG + HOST + SHARED (양쪽 + 공유) — stdlib은 제외
    all_known = _RAG_MODULES | _HOST_MODULES  # 프로젝트 로컬 모듈 전체 (양쪽 합집합)

    seen = set()
    for pat in patterns:
        for path in sorted(glob.glob(pat)):
            if path in seen:
                continue
            seen.add(path)
            stem = os.path.splitext(os.path.basename(path))[0]

            # 1) 파일 자체가 금지 집합(다른 쪽) 소유인 경우 제외
            if stem in skip_own:
                continue
            # 2) test_<mod> 형식으로 금지 집합 모듈의 테스트인 경우 제외
            bare = stem.removeprefix('test_').removesuffix('_test')
            if bare in skip_own:
                continue

            rel = os.path.relpath(path, root).replace('\\', '/')
            imps = _imports_of(path)
            hits = sorted(imps & forbidden)
            if not hits:
                continue

            # 3) 이 파일의 "프로젝트 로컬 import"(stdlib 제외) 전부가 금지 집합에 속하면
            #    이 파일은 그쪽 repo 소유 테스트 — 제외.
            #    (분리 전 모노레포 한정 처리; 분리 후엔 파일 자체가 없어 이 예외도 불필요)
            proj_local_imps = imps & all_known
            if proj_local_imps and proj_local_imps.issubset(forbidden):
                continue

            violations.append((rel, hits))
    return violations


def main():
    import argparse
    parser = argparse.ArgumentParser(
        description='경계 검사: repo 분리 후 교차 import 금지 검사')
    parser.add_argument(
        '--forbid', required=True, choices=['rag', 'host'],
        help='rag: RAG 모듈 import 금지 (호스트 repo용) / host: 호스트 모듈 import 금지 (RAG repo용)')
    parser.add_argument(
        '--root', default=None,
        help='검사할 repo 루트 (기본: 이 스크립트의 상위 2단계)')
    args = parser.parse_args()

    # 스크립트가 scripts/split_staging/ 에 있을 때와 repo 루트에 복사됐을 때 모두 동작
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if args.root:
        root = os.path.abspath(args.root)
    else:
        # scripts/split_staging/ → 상위 2단계 = repo 루트
        # repo 루트에 직접 복사된 경우 → 상위 1단계
        candidate_2up = os.path.dirname(os.path.dirname(script_dir))
        candidate_1up = os.path.dirname(script_dir)
        # repo 루트 판단: proxy_server.py 또는 rag_server.py 가 있으면 루트
        if os.path.exists(os.path.join(candidate_2up, 'proxy_server.py')) or \
           os.path.exists(os.path.join(candidate_2up, 'rag_server.py')):
            root = candidate_2up
        elif os.path.exists(os.path.join(candidate_1up, 'proxy_server.py')) or \
             os.path.exists(os.path.join(candidate_1up, 'rag_server.py')):
            root = candidate_1up
        else:
            root = os.getcwd()

    if args.forbid == 'rag':
        forbidden = _RAG_MODULES
        # RAG 파일 자신끼리의 import는 정상 — RAG 파일은 스캔 대상에서 제외.
        # (분리 후 호스트 repo에는 RAG 파일이 없으므로 이 제외 목록도 의미 없어짐)
        skip_own = _RAG_MODULES
        label = 'RAG'
    else:
        forbidden = _HOST_MODULES
        # HOST 파일 자신끼리의 import는 정상 — HOST 파일은 스캔 대상에서 제외.
        skip_own = _HOST_MODULES
        label = 'HOST'

    print(f'[check_no_cross_import] root={root}  forbid={label} ({len(forbidden)} modules)')
    violations = _scan(root, forbidden, skip_own)

    if violations:
        print(f'[FAIL] {len(violations)} file(s) import forbidden {label} modules:')
        for rel, hits in violations:
            print(f'  {rel}: {", ".join(hits)}')
        sys.exit(1)
    else:
        print(f'[ OK ] no cross-import of {label} modules found')
        sys.exit(0)


if __name__ == '__main__':
    main()

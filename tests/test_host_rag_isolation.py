"""
tests/test_host_rag_isolation.py — P3: 호스트 핵심 모듈의 RAG 미import 고정 테스트.

docs/rag_phase4_split_plan.md 4-A.2 참조.

목적: Phase 4-E(저장소 분리) 후 호스트 repo 가 단독 동작할 수 있도록,
호스트 핵심 모듈(job_runner, batch_executor, runner)이 RAG 전용 모듈을
import 하지 않음을 ast 소스 분석으로 보장한다.

주의: 대상 모듈을 절대 runtime-import 하지 않는다.
  - job_runner.py 는 proxy_server 를 import 하며 연쇄 로딩 + stdout 재정의 발생.
  - 대신 ast.parse 로 소스 텍스트만 검사한다.
"""

import ast
import importlib.util
import os
import warnings

# ── RAG_MODULES 을 check_consistency.py 에서 동적 로드 (single source of truth) ──
_SCRIPTS_DIR = os.path.join(os.path.dirname(__file__), '..', 'scripts')
_CC_PATH = os.path.abspath(os.path.join(_SCRIPTS_DIR, 'check_consistency.py'))

_spec = importlib.util.spec_from_file_location('check_consistency', _CC_PATH)
_cc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_cc)   # main() 은 if __name__ == '__main__' 가드로 보호됨
RAG_MODULES = _cc.RAG_MODULES

# ── 검사 대상 호스트 핵심 모듈 ──
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
HOST_CORE_MODULES = ['job_runner.py', 'batch_executor.py', 'runner.py']


def _imports_of(path: str) -> set:
    """소스 파일에서 최상위 + 함수/클래스 내부 import 전부를 수집한다.

    check_consistency.py 의 _imports_of 와 동일한 로직.
    SyntaxWarning 은 무시(이미 py-compile 게이트에서 걸린다).
    """
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            src = f.read()
    except OSError:
        return set()

    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', SyntaxWarning)
            tree = ast.parse(src)
    except SyntaxError:
        return set()

    mods: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mods.add(alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            mods.add(node.module.split('.')[0])
    return mods


# ── 각 모듈별 파라미터화 없이 개별 test 함수 정의 ──
# (pytest 파라미터화 대신 명시적 함수로 작성 — 오류 메시지가 더 명확함)


def _assert_no_rag_import(filename: str) -> None:
    """filename 이 RAG_MODULES 를 import 하지 않는다고 assert."""
    path = os.path.join(ROOT, filename)
    assert os.path.exists(path), f"검사 대상 파일이 없음: {path}"
    imported = _imports_of(path)
    rag_found = imported & RAG_MODULES
    assert not rag_found, (
        f"{filename} 이 RAG 모듈을 import 함 — Phase 4-E 분리 시 호스트 단독 실행 불가:\n"
        f"  발견된 RAG import: {sorted(rag_found)}\n"
        f"  현재 import 전체 (로컬): {sorted(imported)}\n"
        "  호스트 핵심 모듈에서 RAG 결합을 제거하거나, "
        "의존성 주입(callable 파라미터)으로 전환할 것."
    )


def test_job_runner_no_rag_import():
    """job_runner.py 는 RAG 전용 모듈을 import 하지 않아야 한다."""
    _assert_no_rag_import('job_runner.py')


def test_batch_executor_no_rag_import():
    """batch_executor.py 는 RAG 전용 모듈을 import 하지 않아야 한다."""
    _assert_no_rag_import('batch_executor.py')


def test_runner_no_rag_import():
    """runner.py 는 RAG 전용 모듈을 import 하지 않아야 한다."""
    _assert_no_rag_import('runner.py')

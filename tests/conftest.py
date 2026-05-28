"""
pytest conftest.py

proxy_server.py 는 import 시 sys.stdout / sys.stderr 를 재정의한다.
pytest 는 캡처를 위해 sys.stdout 을 임시 파일로 교체하는데,
proxy_server 가 sys.stdout.buffer 를 통해 새 TextIOWrapper 를 만들면
원래 pytest 캡처 tempfile 이 닫혀 I/O 오류가 발생한다.

해결책:
  proxy_server 를 import 하기 전에 sys.stdout / sys.stderr 를 보존하고,
  proxy_server import 완료 후 pytest 캡처 stdout 을 복원한다.
  이 conftest 는 tests/ 디렉터리에서 자동 로드된다.
"""
import sys
import io


def pytest_configure(config):
    """pytest 설정 단계에서 proxy_server 호환 stdout 을 확보한다."""
    # pytest 가 stdout 을 캡처용 객체로 교체한 경우 buffer 속성이 없을 수 있다.
    # proxy_server.py 최상단이 sys.stdout.buffer 에 접근하므로
    # buffer 가 없으면 실제 stdout 으로 교체한다.
    _fix_stdout_for_proxy_import()


def _fix_stdout_for_proxy_import():
    """sys.stdout / sys.stderr 에 buffer 가 없으면 원본으로 교체."""
    import sys as _sys
    if not hasattr(_sys.stdout, 'buffer'):
        _sys.stdout = sys.__stdout__ or io.TextIOWrapper(
            io.FileIO('/dev/null', 'w'), encoding='utf-8', errors='replace'
        )
    if not hasattr(_sys.stderr, 'buffer'):
        _sys.stderr = sys.__stderr__ or io.TextIOWrapper(
            io.FileIO('/dev/null', 'w'), encoding='utf-8', errors='replace'
        )

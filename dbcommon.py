"""
dbcommon.py (루트 shim) — 4-B/B1
=================================
실제 구현은 packages/medical_shared/dbcommon/__init__.py 로 이동했다.
이 파일은 하위 호환 shim 으로, sys.modules 에 'dbcommon' 이름으로
패키지 모듈을 등록한다.

모듈 별칭(alias) 방식을 사용하면:
  - `import dbcommon; dbcommon.DB_PATH = ...` 같은 런타임 속성 패치(tests/)가
    실제 패키지 모듈 객체에 반영되어 get_conn 등이 올바른 경로를 사용한다.
  - `from db import _use_postgres, DB_PATH, ...` 재export 목록 유지가 불필요.
  - check_consistency.py 의 `__import__('dbcommon')` 심볼 검사가 그대로 동작.
"""
import sys as _sys
import importlib as _importlib

# 패키지 모듈을 로드하고 'dbcommon' 이름으로 등록
_impl = _importlib.import_module('packages.medical_shared.dbcommon')
_sys.modules['dbcommon'] = _impl

# 이 모듈 자체도 같은 객체로 교체하여 `import dbcommon` 후 속성 패치가
# 패키지 모듈에 직접 반영되도록 한다.
_sys.modules[__name__] = _impl

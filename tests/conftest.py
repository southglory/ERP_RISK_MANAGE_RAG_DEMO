"""pytest 루트 conftest — 프로젝트 루트를 sys.path에 추가."""
import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

"""EQ Legends Assistant regression gate: python selftest.py [suite ...]

Auto-discovers suites: every tests/test_*.py must expose run(check).
check(name, cond, detail='') prints FAIL lines; nonzero exit if any failed.
Pass suite stems (e.g. `python selftest.py core logscan`) to run a subset.
"""
import importlib
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# tests get their own scratch DB, never data/assistant.db — MUST be set before
# any app module import (app.config reads it at import time)
os.environ['EQA_DATA_DIR'] = tempfile.mkdtemp(prefix='eqa-selftest-')

if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

PASSED = 0
FAILED = 0


def check(name: str, cond, detail=''):
    global PASSED, FAILED
    if cond:
        PASSED += 1
    else:
        FAILED += 1
        print(f'  FAIL {name}  {detail}')


def main():
    print('EQ Legends Assistant selftest')
    only = {a for a in sys.argv[1:] if not a.startswith('-')}
    for path in sorted((ROOT / 'tests').glob('test_*.py')):
        stem = path.stem.replace('test_', '', 1)
        if only and stem not in only:
            continue
        mod = importlib.import_module(f'tests.{path.stem}')
        before = FAILED
        mod.run(check)
        marker = 'ok' if FAILED == before else 'FAILED'
        print(f'  [{stem}] {marker}')
    if not only:
        subprocess.run([sys.executable, str(ROOT / 'tools' / 'check_vendor_drift.py')])
    print(f'{PASSED} passed, {FAILED} failed')
    return 1 if FAILED else 0


if __name__ == '__main__':
    sys.exit(main())

"""Report drift between vendor/eqlparser and the upstream working tree.

Warning tool, not a gate: exit 0 unless --strict. selftest.py runs it and prints
the report so drift is noticed while the upstream parser keeps evolving.
"""
import hashlib
import sys
from pathlib import Path

VENDOR = Path(__file__).resolve().parent.parent / 'vendor' / 'eqlparser'
UPSTREAM = Path('J:/_EQLegendsParser')
FILES = ('parser.py', 'tracker.py', 'icons.py')


def _sha(p: Path) -> str:
    # EOL-insensitive: upstream has core.autocrlf=true, so a checkout may be CRLF
    # while the git blob (and any LF checkout) is LF. Same content, same hash.
    return hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()


def main() -> int:
    strict = '--strict' in sys.argv
    if not UPSTREAM.is_dir():
        print(f'[vendor] upstream {UPSTREAM} not present - skipping drift check')
        return 0
    drifted = []
    for name in FILES:
        v, u = VENDOR / name, UPSTREAM / name
        if not u.is_file():
            print(f'[vendor] {name}: missing upstream - skipped')
            continue
        if _sha(v) != _sha(u):
            drifted.append(name)
    if drifted:
        print(f'[vendor] DRIFT: {", ".join(drifted)} differ from {UPSTREAM}.')
        print('[vendor] Upstream has evolved (or was re-vendored incompletely).')
        print('[vendor] To re-vendor: copy the files, update PROVENANCE.md hashes, rerun selftest.')
        return 1 if strict else 0
    print('[vendor] vendored files match upstream working tree')
    return 0


if __name__ == '__main__':
    sys.exit(main())

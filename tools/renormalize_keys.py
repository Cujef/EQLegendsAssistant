"""One-time key fixup after a normalize_name rule change.

Re-derives name_norm for items / item_effects / quest_item_mentions using the
CURRENT normalize_name. On a collision (two old keys mapping to one new key)
the already-normalized row wins and the variant row is dropped — the variants
are the same item spelled differently, and future syncs rewrite them anyway.

Run with the server STOPPED (it holds module-level state keyed by the old
normalization): python tools/renormalize_keys.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.inventory import normalize_name  # noqa: E402


def fix(table: str, col: str = 'name_norm') -> tuple:
    rows = db.query(f'SELECT rowid, {col} AS k FROM {table}')
    renamed = dropped = 0
    with db.tx() as c:
        for r in rows:
            new = normalize_name(r['k'])
            if new == r['k']:
                continue
            clash = c.execute(f'SELECT 1 FROM {table} WHERE {col}=? LIMIT 1',
                              (new,)).fetchone()
            if clash:
                c.execute(f'DELETE FROM {table} WHERE rowid=?', (r['rowid'],))
                dropped += 1
            else:
                c.execute(f'UPDATE {table} SET {col}=? WHERE rowid=?',
                          (new, r['rowid']))
                renamed += 1
    return renamed, dropped


def main():
    db.init()
    for table, col in (('items', 'name_norm'), ('item_effects', 'name_norm'),
                       ('quest_item_mentions', 'item_name_norm')):
        renamed, dropped = fix(table, col)
        print(f'{table}: {renamed} renamed, {dropped} duplicate variants dropped')
    db.close()


if __name__ == '__main__':
    main()

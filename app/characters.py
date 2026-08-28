"""Character discovery and selection.

Characters are seeded from the game's own `_characters.ini`:

    [Characters]
    Character0=Cujef,halas
    Character1=Cooj,qeynos

Paths derived per character (verified against the real install):
- log:       <game_dir>/Logs/eqlog_<Name>_<server>.txt
- inventory: <game_dir>/<Name>_<server>-Inventory.txt   (/outputfile inventory
             writes to the install ROOT, not Logs)
"""
import configparser
import re
from pathlib import Path
from typing import List, Optional

from . import db
from .config import GAME_DIR, LOGS_DIR

RE_LOG_FILENAME = re.compile(r'^eqlog_(\w+)_(\w+)\.txt$')


def _read_characters_ini() -> List[tuple]:
    """[(name, server)] from _characters.ini; empty list if absent/unreadable."""
    path = GAME_DIR / '_characters.ini'
    out = []
    try:
        cp = configparser.ConfigParser()
        cp.read(path, encoding='utf-8')
        for _, value in sorted(cp.items('Characters')):
            parts = [p.strip() for p in value.split(',')]
            if len(parts) >= 2 and parts[0]:
                out.append((parts[0], parts[1]))
    except (OSError, configparser.Error, KeyError):
        pass
    return out


def _discover_from_logs() -> List[tuple]:
    """Fallback: character names straight out of eqlog_* filenames."""
    out = []
    try:
        for p in LOGS_DIR.glob('eqlog_*.txt'):
            m = RE_LOG_FILENAME.match(p.name)
            if m:
                out.append((m.group(1), m.group(2)))
    except OSError:
        pass
    return out


def log_path(name: str, server: str) -> Optional[str]:
    p = LOGS_DIR / f'eqlog_{name}_{server}.txt'
    return str(p) if p.is_file() else None


def inventory_path(name: str, server: str) -> Optional[str]:
    p = GAME_DIR / f'{name}_{server}-Inventory.txt'
    return str(p) if p.is_file() else None


def seed() -> None:
    """Upsert discovered characters; refresh derived paths. First char with a log
    becomes active if nothing is active yet."""
    found = _read_characters_ini() or _discover_from_logs()
    for name, server in found:
        lp, ip = log_path(name, server), inventory_path(name, server)
        with db.tx() as c:
            c.execute(
                'INSERT INTO characters(name, server, log_path, inventory_path, created_at) '
                'VALUES(?,?,?,?,?) '
                'ON CONFLICT(name, server) DO UPDATE SET log_path=excluded.log_path, '
                'inventory_path=excluded.inventory_path',
                (name, server, lp, ip, db.now()))
    active = db.query_one('SELECT id FROM characters WHERE is_active=1')
    if not active:
        first = db.query_one(
            'SELECT id FROM characters ORDER BY (log_path IS NULL), id LIMIT 1')
        if first:
            db.execute('UPDATE characters SET is_active=1 WHERE id=?', (first['id'],))


def list_all() -> List[dict]:
    return db.query('SELECT * FROM characters ORDER BY id')


def get(char_id: Optional[int] = None) -> Optional[dict]:
    """The requested character, or the active one."""
    if char_id is not None:
        return db.query_one('SELECT * FROM characters WHERE id=?', (char_id,))
    return db.query_one('SELECT * FROM characters WHERE is_active=1')


def select(char_id: int) -> None:
    with db.tx() as c:
        c.execute('UPDATE characters SET is_active=0')
        c.execute('UPDATE characters SET is_active=1 WHERE id=?', (char_id,))

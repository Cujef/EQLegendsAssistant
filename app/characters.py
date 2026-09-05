"""Character discovery and selection.

Characters are seeded from the game's own `_characters.ini`:

    [Characters]
    Character0=Fizzwick,halas
    Character1=Grimsby,qeynos

Paths derived per character (verified against the real install):
- log:       <game_dir>/Logs/eqlog_<Name>_<server>.txt
- inventory: <game_dir>/<Name>_<server>-Inventory.txt   (/outputfile inventory
             writes to the install ROOT, not Logs)
"""
import configparser
import re
import time
from pathlib import Path
from typing import List, Optional

from . import db
from .config import GAME_DIR, LOGS_DIR

RE_LOG_FILENAME = re.compile(r'^eqlog_(\w+)_(\w+)\.txt$')
# the game names the dump <Name>_<server>-Inventory.txt; the file itself carries
# no character header, so the filename is the only in-band owner hint
RE_INVENTORY_FILENAME = re.compile(r'^(\w+)_(\w+)-Inventory\.txt$', re.I)


def parse_inventory_filename(name) -> Optional[tuple]:
    """(name, server) from a dump filename or path, or None when it does not
    follow the game's naming. Accepts either slash style on any OS."""
    base = re.split(r'[\\/]', str(name or ''))[-1]
    m = RE_INVENTORY_FILENAME.match(base)
    return (m.group(1), m.group(2)) if m else None


def parse_outputfile_owner(name) -> Optional[tuple]:
    """(name, server) from ANY /outputfile export name (-Inventory, -Faction,
    -<Skill>-Recipes); see app/gamefiles.py for the kind."""
    from . import gamefiles
    meta = gamefiles.parse_outputfile_name(name)
    return (meta['name'], meta['server']) if meta else None


def _read_characters_ini(game_dir: Path) -> List[tuple]:
    """[(name, server)] from _characters.ini; empty list if absent/unreadable."""
    path = game_dir / '_characters.ini'
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


def _discover_from_logs(logs_dir: Path) -> List[tuple]:
    """Fallback: character names straight out of eqlog_* filenames."""
    out = []
    try:
        for p in logs_dir.glob('eqlog_*.txt'):
            m = RE_LOG_FILENAME.match(p.name)
            if m:
                out.append((m.group(1), m.group(2)))
    except OSError:
        pass
    return out


def log_path(name: str, server: str, logs_dir: Path = None) -> Optional[str]:
    p = (logs_dir or LOGS_DIR) / f'eqlog_{name}_{server}.txt'
    return str(p) if p.is_file() else None


def inventory_path(name: str, server: str, game_dir: Path = None) -> Optional[str]:
    p = (game_dir or GAME_DIR) / f'{name}_{server}-Inventory.txt'
    return str(p) if p.is_file() else None


def resolve_dirs(directory) -> tuple:
    """(game_dir, logs_dir) for a folder the user pointed at.

    Accepts the install root (…/EQLegends, logs in ./Logs) or the Logs folder
    itself (…/EQLegends/Logs) — people reach for either, and getting it wrong
    should not be a dead end.
    """
    p = Path(str(directory)).expanduser()
    if p.name.lower() == 'logs':
        return p.parent, p
    return p, p / 'Logs'


def scan(directory=None) -> dict:
    """Characters discoverable under `directory`, WITHOUT writing anything.

    Each candidate reports whether its log and inventory dump were actually
    found, so the setup UI can tell the user what is missing before they commit.
    """
    from . import gamefiles   # local: gamefiles imports tradeskills/inventory, never this module
    game_dir, logs_dir = resolve_dirs(directory or GAME_DIR)
    pairs = _read_characters_ini(game_dir)
    seen = {(n.lower(), s.lower()) for n, s in pairs}
    for n, s in _discover_from_logs(logs_dir):
        if (n.lower(), s.lower()) not in seen:
            pairs.append((n, s))
            seen.add((n.lower(), s.lower()))
    # every /outputfile export in the game folder (inventory / faction / recipes);
    # an alt with only a dump still shows up, so the wizard can add it
    entries = gamefiles.list_exports(game_dir)
    for e in entries:
        if (e['name'].lower(), e['server'].lower()) not in seen:
            pairs.append((e['name'], e['server']))
            seen.add((e['name'].lower(), e['server'].lower()))
    known = {(r['name'].lower(), r['server'].lower()) for r in list_all()}
    out = []
    for name, server in pairs:
        lp = log_path(name, server, logs_dir)
        ip = inventory_path(name, server, game_dir)
        size = 0
        if lp:
            try:
                size = Path(lp).stat().st_size
            except OSError:
                size = 0
        out.append({
            'name': name, 'server': server,
            'log_path': lp, 'log_size': size, 'inventory_path': ip,
            'exports': gamefiles.discover(name, server, entries=entries),
            'already_added': (name.lower(), server.lower()) in known,
        })
    return {
        'game_dir': str(game_dir), 'logs_dir': str(logs_dir),
        'game_dir_exists': game_dir.is_dir(), 'logs_dir_exists': logs_dir.is_dir(),
        'candidates': out,
    }


def add(name: str, server: str, log_path_: str = None, inventory_path_: str = None,
        activate: bool = True) -> dict:
    """Insert or update one character. Blank paths are stored as NULL, never ''
    (the pipeline tests truthiness, and '' would look like a configured path)."""
    name, server = (name or '').strip(), (server or '').strip()
    if not name:
        raise ValueError('character name is required')
    lp = (log_path_ or '').strip() or None
    ip = (inventory_path_ or '').strip() or None
    if lp and not Path(lp).is_file():
        raise ValueError(f'log file not found: {lp}')
    if ip and not Path(ip).is_file():
        raise ValueError(f'inventory file not found: {ip}')
    with db.tx() as c:
        c.execute(
            'INSERT INTO characters(name, server, log_path, inventory_path, created_at) '
            'VALUES(?,?,?,?,?) ON CONFLICT(name, server) DO UPDATE SET '
            'log_path=COALESCE(excluded.log_path, log_path), '
            'inventory_path=COALESCE(excluded.inventory_path, inventory_path)',
            (name, server or 'unknown', lp, ip, db.now()))
    row = db.query_one('SELECT * FROM characters WHERE name=? AND server=?',
                       (name, server or 'unknown'))
    if activate and row:
        select(row['id'])
        row = get(row['id'])
    return row


# every table keyed by character_id, so removing a character leaves nothing behind
_CHAR_TABLES = ('manual_stats', 'quest_progress', 'quest_step_progress', 'skill_levels',
                'level_history', 'aa_ledger', 'deaths', 'highlights', 'fights',
                'log_source', 'craft_events', 'craft_caps', 'craft_recipe_skill',
                'depot_events', 'faction_events', 'faction_caps', 'upgrade_events',
                'faction_standings', 'known_recipes', 'export_files', 'zone_stats',
                'zone_events', 'loot_events', 'sessions')


def remove(char_id: int) -> None:
    """Delete a character and everything derived from it."""
    with db.tx() as c:
        snaps = [r['id'] for r in c.execute(
            'SELECT id FROM inventory_snapshots WHERE character_id=?', (char_id,)).fetchall()]
        for sid in snaps:
            c.execute('DELETE FROM inventory_items WHERE snapshot_id=?', (sid,))
        c.execute('DELETE FROM inventory_snapshots WHERE character_id=?', (char_id,))
        for table in _CHAR_TABLES:
            c.execute(f'DELETE FROM {table} WHERE character_id=?', (char_id,))
        c.execute('DELETE FROM characters WHERE id=?', (char_id,))
    if not db.query_one('SELECT id FROM characters WHERE is_active=1'):
        nxt = db.query_one('SELECT id FROM characters ORDER BY id LIMIT 1')
        if nxt:
            select(nxt['id'])


def needs_setup(active: Optional[dict] = None) -> bool:
    """True when the app has nothing to work with yet — no characters at all, or
    an active character with neither a log nor an inventory dump. Pass `active`
    when the caller already holds it (the 1 Hz snapshot does)."""
    active = active if active is not None else get()
    if not active:
        return True
    return not (active['log_path'] or active['inventory_path'])


_items_cache = {'at': 0.0, 'n': 0}
ITEMS_TTL = 30.0        # the sync engine is the only writer; a stale count is harmless


def invalidate_items_count() -> None:
    _items_cache['at'] = 0.0


def _items_count(conn) -> int:
    """COUNT(*) over the item DB, memoized. It rode the 1 Hz snapshot for a
    number that only a Data Sync can change."""
    now = time.time()
    if now - _items_cache['at'] > ITEMS_TTL:
        _items_cache.update({'at': now, 'n': conn.execute('SELECT COUNT(*) FROM items').fetchone()[0]})
    return _items_cache['n']


def readiness(active: Optional[dict]) -> Optional[dict]:
    """What the active character has fed the app so far — drives the first-open
    suggestion box. Three indexed reads on one connection; rides the 1 Hz snapshot."""
    if not active:
        return None
    cid = active['id']
    conn = db.reader()
    try:
        inv = conn.execute('SELECT MAX(imported_at) FROM inventory_snapshots '
                           'WHERE character_id=?', (cid,)).fetchone()[0]
        lines = conn.execute("SELECT value_num FROM highlights WHERE character_id=? "
                             "AND key='lines_parsed'", (cid,)).fetchone()
        items = _items_count(conn)
    finally:
        conn.close()
    return {
        'inventory_imported_at': inv,
        'log_path_set': bool(active.get('log_path')),
        'log_lines_parsed': int(lines[0]) if lines and lines[0] else 0,
        'items_in_db': int(items or 0),
        # static on purpose: the suggestion box re-renders whenever this object
        # changes, so the watcher's timestamps live in state.exports instead
        'auto_import': {'enabled': True},
    }


def seed() -> None:
    """Upsert characters found in the configured game dir; refresh derived paths.
    First char with a log becomes active if nothing is active yet.

    Only ever ADDS what the install advertises — a hand-added character (setup
    wizard, another install) is never touched here.
    """
    found = _read_characters_ini(GAME_DIR) or _discover_from_logs(LOGS_DIR)
    for name, server in found:
        lp, ip = log_path(name, server), inventory_path(name, server)
        with db.tx() as c:
            # COALESCE, not overwrite: a file temporarily missing from the game
            # dir must not wipe a path the user configured by hand
            c.execute(
                'INSERT INTO characters(name, server, log_path, inventory_path, created_at) '
                'VALUES(?,?,?,?,?) '
                'ON CONFLICT(name, server) DO UPDATE SET '
                'log_path=COALESCE(excluded.log_path, log_path), '
                'inventory_path=COALESCE(excluded.inventory_path, inventory_path)',
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

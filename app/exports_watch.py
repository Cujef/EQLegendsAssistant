"""Auto-pickup of /outputfile exports.

Every INTERVAL seconds, look at the game folder for each known character's
exports (inventory / faction / recipes — app/gamefiles.py names them) plus the
character's remembered inventory_path, and import whatever is new or changed.
The user types the command in game and the app has it a few seconds later.

Rules, each for a reason:
- a file younger than SETTLE_SECONDS is left alone: the game may still be writing it;
- (mtime, size) unchanged since the last look → nothing to do, no read;
- same bytes as last time (sha256) → recorded as `unchanged` without importing, so a
  rewrite of an identical faction file does not reset "moved since import";
- import errors are recorded on the row (with the offending mtime/size, so the
  same bad file is not retried every 5 s) and never raised out of the thread;
- characters are never CREATED here — a stray dump for an unknown name is shown
  by the setup wizard's scan instead, one click away from being added.

Double imports (the watcher and the Import dialog racing on one file) are
harmless: inventory dedupes on sha256 + PARSE_REV, faction/recipes imports are
replace-all inside one transaction on the single writer.
"""
import hashlib
import os
import sys
import threading
import time
from pathlib import Path
from typing import List, Optional

from . import characters, db, gamefiles, state

INTERVAL = 5.0
SETTLE_SECONDS = 2.0
RECENT_MAX = 20

_lock = threading.Lock()
_thread: Optional[threading.Thread] = None


def path_key(path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))


def candidate_files(char: dict, entries: List[dict]) -> List[dict]:
    """discover() for this character plus its remembered inventory_path (which
    may live outside the game folder), deduplicated by path identity."""
    files = gamefiles.discover(char['name'], char['server'], entries=entries)
    seen = {path_key(f['path']) for f in files}
    ip = char.get('inventory_path')
    if ip and path_key(ip) not in seen:
        try:
            st = os.stat(ip)
            files.append({'kind': 'inventory', 'skill': None, 'path': ip,
                          'mtime': st.st_mtime, 'size': st.st_size})
        except OSError:
            pass
    return files


def _upsert(cid: int, key: str, f: dict, sha: Optional[str], status: str,
            error: Optional[str]) -> None:
    now = db.now()
    db.execute(
        'INSERT INTO export_files(character_id, path_key, path, kind, skill, mtime, size, '
        'sha256, imported_at, status, error) VALUES(?,?,?,?,?,?,?,?,?,?,?) '
        'ON CONFLICT(character_id, path_key) DO UPDATE SET path=excluded.path, '
        'kind=excluded.kind, skill=excluded.skill, mtime=excluded.mtime, size=excluded.size, '
        'sha256=COALESCE(excluded.sha256, sha256), '
        "imported_at=CASE WHEN excluded.status='imported' THEN excluded.imported_at "
        'ELSE imported_at END, status=excluded.status, error=excluded.error',
        (cid, key, f['path'], f['kind'], f.get('skill'), f.get('mtime'), f.get('size'), sha,
         now if status == 'imported' else None, status, error))


def known_files(cid: int) -> dict:
    """{path_key: row} — one query per pass instead of one per candidate file.
    The steady state is "nothing changed", so this is the hot path."""
    return {r['path_key']: r for r in db.query(
        'SELECT path_key, mtime, size, sha256 FROM export_files WHERE character_id=?', (cid,))}


def process_file(cid: int, f: dict, now: Optional[float] = None,
                 known: Optional[dict] = None) -> Optional[dict]:
    """Look at one export for one character. Returns an event dict when
    something happened (imported / unchanged-but-rewritten / error), else None."""
    now = now or time.time()
    if f.get('mtime') is not None and now - f['mtime'] < SETTLE_SECONDS:
        return None                                   # still being written
    key = path_key(f['path'])
    row = known.get(key) if known is not None else db.query_one(
        'SELECT mtime, size, sha256 FROM export_files '
        'WHERE character_id=? AND path_key=?', (cid, key))
    if row and row['mtime'] == f.get('mtime') and row['size'] == f.get('size'):
        return None                                   # seen exactly this file already
    base = {'ts': now, 'character_id': cid, 'kind': f['kind'], 'skill': f.get('skill'),
            'path': f['path']}
    try:
        raw = Path(f['path']).read_bytes()
    except OSError as e:
        _upsert(cid, key, f, None, 'error', str(e))
        return {**base, 'status': 'error', 'error': str(e)}
    sha = hashlib.sha256(raw).hexdigest()
    if row and row['sha256'] == sha:
        _upsert(cid, key, f, sha, 'unchanged', None)
        return {**base, 'status': 'unchanged'}
    try:
        res = gamefiles.import_any(cid, raw, path=f['path'])
    except (ValueError, OSError) as e:
        _upsert(cid, key, f, sha, 'error', str(e))
        return {**base, 'status': 'error', 'error': str(e)}
    status = 'unchanged' if res.get('unchanged') else 'imported'
    _upsert(cid, key, f, sha, status, None)
    if f['kind'] == 'inventory':
        c = characters.get(cid)
        if c and not c.get('inventory_path'):
            db.execute('UPDATE characters SET inventory_path=? WHERE id=?', (f['path'], cid))
    return {**base, 'status': status, 'detail': {k: v for k, v in res.items()
                                                  if k in ('kind', 'rows', 'items', 'skill',
                                                           'exaltations', 'skipped_count')}}


def run_once(game_dir=None) -> dict:
    """One pass over every character's exports. Synchronous; also the body of
    the watcher thread and of POST /api/exports/rescan."""
    now = time.time()
    entries = gamefiles.list_exports(game_dir)
    imported, errors = [], []
    checked = unchanged = 0
    for c in characters.list_all():
        for f in candidate_files(c, entries):
            checked += 1
            r = process_file(c['id'], f, now)
            if not r:
                continue
            r['character'] = c['name']
            r['server'] = c['server']
            if r['status'] == 'imported':
                imported.append(r)
            elif r['status'] == 'unchanged':
                unchanged += 1
            else:
                errors.append(r)
    slim = [{k: v for k, v in r.items() if k != 'detail'} for r in imported + errors]
    with state.lock:
        recent = (slim + list(state.exports.get('recent', [])))[:RECENT_MAX]
        state.exports.update({'last_check': now, 'recent': recent, 'pending': 0})
    return {'checked': checked, 'imported': imported, 'unchanged': unchanged,
            'errors': errors, 'last_check': now}


def files_for(character_id: int) -> List[dict]:
    return db.query('SELECT path, kind, skill, mtime, size, imported_at, status, error '
                    'FROM export_files WHERE character_id=? ORDER BY kind, skill, path',
                    (character_id,))


def _main() -> None:
    while True:
        try:
            run_once()
        except Exception as e:  # noqa: BLE001 - a watcher must never die
            print(f'[exports] {e!r}', file=sys.stderr)
        time.sleep(INTERVAL)


def start() -> None:
    """Start the watcher thread. Idempotent."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_main, name='eqa-exports-watch', daemon=True)
        _thread.start()

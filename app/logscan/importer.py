"""Historical log scan entry point — M3.

There is no separate import consumer: ONE pipeline (tailer.Pipeline) owns each
character's log end-to-end, resuming from the byte-offset checkpoint, scanning
to EOF ("import" phase, progress in state.import_progress), then tailing live.

start(character) — called by POST /api/log/import — makes sure that pipeline is
running and reports where it is. A fingerprint mismatch (a new log under the
same path) is detected here for the report; the pipeline itself performs the
reset-and-rescan when it opens the file.

scan_once(character) is the synchronous form (no thread): catch up to EOF and
return. Tests and tools use it.
"""
from pathlib import Path

from .. import db, state
from . import tailer


def _mismatch(character: dict) -> bool:
    """True when checkpoints exist for this path but none match today's file."""
    path = str(character.get('log_path') or '')
    fp = tailer._fingerprint(Path(path))
    if fp is None:
        return False
    rows = db.query('SELECT fingerprint FROM log_source WHERE path=?', (path,))
    return bool(rows) and all(r['fingerprint'] != fp for r in rows)


def start(character: dict) -> dict:
    path = character.get('log_path')
    if not path or not Path(path).is_file():
        return {'ok': False, 'error': f'log file not found: {path}'}
    reset = _mismatch(character)
    tailer.start()          # idempotent; the watcher picks up the active char
    with state.lock:
        prog = dict(state.import_progress)
    out = {'ok': True,
           'status': prog.get('status', 'idle'),
           'pct': prog.get('pct'),
           'offset': prog.get('offset'),
           'size': prog.get('size'),
           'lines': prog.get('lines')}
    if reset or prog.get('reset'):
        out['reset'] = True
        out['note'] = 'log fingerprint changed — rescanning from the start'
    return out


def scan_once(character: dict) -> dict:
    """Synchronous catch-up to EOF for `character`'s log. No thread, no tailing."""
    return tailer.Pipeline(character).scan_to_eof()

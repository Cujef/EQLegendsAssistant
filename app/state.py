"""Shared in-process state that rides the 1 Hz WebSocket snapshot.

Background workers (log importer, live tailer, sync engine) write here under
`lock`; server.py reads it once per second per client. Keep values JSON-safe.
"""
import threading
from typing import Any, Dict

lock = threading.Lock()

# {'status': 'idle'|'running'|'done'|'error', 'pct': 0-100, 'offset': n, 'size': n,
#  'lines': n, 'started_at': ts, 'error': str}
import_progress: Dict[str, Any] = {'status': 'idle'}

# {'status': 'idle'|'running'|'done'|'error'|'cancelled', 'source': str,
#  'phase': str, 'done': n, 'total': n, 'current': url, 'errors': n}
sync_status: Dict[str, Any] = {'status': 'idle'}

# Live parser state, set by the tailer: {'tail': {...}, 'active_fight': ..., 'fights': [...],
#  'session': {...}} — shape owned by app/logscan/tailer.py.
live: Dict[str, Any] = {}


def set_import(**kw) -> None:
    with lock:
        import_progress.update(kw)


def set_sync(**kw) -> None:
    with lock:
        sync_status.update(kw)


def snapshot_extras() -> Dict[str, Any]:
    """The worker-owned portion of the WS snapshot (shallow copies)."""
    with lock:
        return {
            'import': dict(import_progress),
            'sync': dict(sync_status),
            'live': dict(live),
        }

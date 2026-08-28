"""Sync job runner: ONE background job at a time, cancellable, progress in
state.sync_status (rides the 1 Hz WS snapshot) + sync_runs rows.

Source modules (wiki_api.py, tools_site.py) implement `run(ctx)` and are
registered in SOURCES. They do their own parsing and db writes; the engine owns
threading, cancellation, throttled fetching, and robots discipline.
"""
import threading
import time
import traceback
import urllib.error
import urllib.request
from typing import Optional

from .. import db, state
from ..config import CONFIG


class Cancelled(Exception):
    pass


class Ctx:
    """Handed to a source's run(). All network I/O must go through fetch()."""

    def __init__(self, source: str, run_id: int):
        self.source = source
        self.run_id = run_id
        self.throttle = float(CONFIG['sync'].get('throttle_seconds', 1.0))
        self.user_agent = CONFIG['sync'].get('user_agent', 'EQLegendsAssistant/0.1')
        self.errors = 0
        self._last_fetch = 0.0

    def check(self):
        if _cancel.is_set():
            raise Cancelled()

    def _wait_throttle(self):
        while True:
            self.check()
            dt = self.throttle - (time.time() - self._last_fetch)
            if dt <= 0:
                break
            time.sleep(min(dt, 0.2))
        self._last_fetch = time.time()

    def fetch(self, url: str, timeout: float = 30.0) -> bytes:
        """Throttled GET. Raises urllib errors on failure; caller decides policy.

        HARD RULE: eqlegendstools.com/api/ is robots.txt-disallowed and must
        never be requested — enforced here so no source module can slip.

        HTTP 429 gets honored, not fought: sleep Retry-After (default 15 s,
        doubling), then retry up to 3 times, and permanently widen this run's
        throttle by 50% each time — the first tools crawl drew 94 429s at
        1 req/s, so the polite rate is whatever the server says it is.
        """
        if 'eqlegendstools.com' in url and '/api/' in url:
            raise RuntimeError(f'refusing robots-disallowed URL: {url}')
        delay = 15.0
        for attempt in range(4):
            self._wait_throttle()
            req = urllib.request.Request(url, headers={'User-Agent': self.user_agent})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return r.read()
            except urllib.error.HTTPError as e:
                if e.code != 429 or attempt == 3:
                    raise
                try:
                    delay = max(delay, float(e.headers.get('Retry-After') or 0))
                except (TypeError, ValueError):
                    pass
                self.throttle *= 1.5
                deadline = time.time() + delay
                while time.time() < deadline:
                    self.check()
                    time.sleep(0.2)
                delay *= 2

    def progress(self, phase: str, done: int = 0, total: int = 0, current: str = ''):
        self.check()
        state.set_sync(status='running', source=self.source, phase=phase,
                       done=done, total=total, current=current, errors=self.errors)
        db.execute('UPDATE sync_runs SET pages_done=?, pages_total=?, errors=? WHERE id=?',
                   (done, total, self.errors, self.run_id))


_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
_cancel = threading.Event()


def _sources() -> dict:
    # imported lazily so a broken source module fails a sync, not app startup
    from . import tools_site, wiki_api
    return {'wiki': wiki_api.run, 'tools': tools_site.run}


def start(source: str) -> dict:
    global _thread
    runner = _sources().get(source)
    if runner is None:
        return {'ok': False, 'error': f'unknown source {source!r}'}
    with _lock:
        if _thread is not None and _thread.is_alive():
            return {'ok': False, 'error': 'a sync is already running'}
        _cancel.clear()
        cur = db.execute('INSERT INTO sync_runs(source, started_at) VALUES(?,?)',
                         (source, db.now()))
        run_id = cur.lastrowid
        ctx = Ctx(source, run_id)
        state.set_sync(status='running', source=source, phase='starting',
                       done=0, total=0, current='', errors=0)

        def work():
            status = 'done'
            try:
                runner(ctx)
            except Cancelled:
                status = 'cancelled'
            except Exception:
                status = 'error'
                traceback.print_exc()
            db.execute('UPDATE sync_runs SET finished_at=?, status=?, errors=? WHERE id=?',
                       (db.now(), status, ctx.errors, run_id))
            state.set_sync(status=status, errors=ctx.errors, current='')

        _thread = threading.Thread(target=work, daemon=True, name=f'sync-{source}')
        _thread.start()
    return {'ok': True, 'run_id': run_id}


def cancel() -> dict:
    _cancel.set()
    return {'ok': True}


def status() -> dict:
    with state.lock:
        s = dict(state.sync_status)
    s['runs'] = db.query('SELECT * FROM sync_runs ORDER BY id DESC LIMIT 10')
    s['unparsed'] = db.query(
        'SELECT url, source, kind, parse_error FROM sync_pages WHERE parse_ok=0 '
        'AND fetched_at IS NOT NULL ORDER BY url LIMIT 200')
    return s

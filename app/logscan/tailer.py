"""One pipeline per character log: resume from the byte-offset checkpoint,
catch up to EOF ("import" phase), then keep tailing live — M3 + M4.

Mechanics adapted from the parser's proven tail thread:
- identity = path + sha256 of the first 512 bytes (EQ reuses filenames for
  brand-new logs, so path alone is not an identity);
- truncation detect via size < offset -> reset checkpoint, rescan from 0;
- binary ~4 MB chunks split on b'\\n' with the partial line carried across
  chunks, so byte offsets are exact (len(raw)+1 per line; '\\r' stays inside
  the part and is stripped after decode);
- every flush writes aggregated rows AND the checkpoint in ONE db.tx(), so the
  checkpoint may lag its data, never lead it.

start() is called once at server startup and is safe with no character/log; the
single daemon thread also watches for active-character changes and restarts the
pipeline on the new log. Tests call Pipeline(char).scan_to_eof() synchronously.
"""
import copy
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from .. import characters, db, state
from . import ext_parser
from .highlights import Aggregator, TRACKED_EVENTS

from vendor.eqlparser.tracker import FightTracker

FINGERPRINT_BYTES = 512
CHUNK_IMPORT = 4 * 1024 * 1024
CHUNK_LIVE = 64 * 1024
FLUSH_SECONDS = 2.0      # live-mode checkpoint cadence
UI_SECONDS = 1.0         # state.live refresh cadence
SNAP_FIGHTS = 20         # completed fights in the snapshot (hard cap — this rides 1 Hz)

_lock = threading.Lock()
_thread: Optional[threading.Thread] = None
current: Optional['Pipeline'] = None   # for importer.py introspection


def _fingerprint(path: Path) -> Optional[str]:
    try:
        head = path.open('rb').read(FINGERPRINT_BYTES)
    except OSError:
        return None
    return hashlib.sha256(head).hexdigest() if head else None


def _blank_session() -> dict:
    return {'dmg_dealt': 0, 'dmg_taken': 0, 'kills': 0, 'deaths': 0,
            'xp_pct': 0.0, 'casts': 0, 'fizzles': 0,
            'loot': [], 'skill_ups': [], 'aa': [], 'deaths_recent': [], 'levels': []}


class Pipeline:
    """Owns one character's log end-to-end. Not thread-safe; one owner thread."""

    def __init__(self, char: dict):
        self.char = char
        self.cid = char['id']
        self.path = Path(char['log_path'])
        self.offset = 0
        self.reset = False              # True when a mismatch/truncation restarted at 0
        self.lines = 0                  # lines consumed by THIS pipeline instance
        self.last_line_ts = None        # ts of the last parsed event
        self.pet_name = None
        self.group_members = set()
        self._pending_invite = None
        self._carry = b''
        self._fp = None
        self._first_ts = None
        self._pending_fights = []
        self._last_switch_check = 0.0
        self._switch = False
        seed = db.query_one(
            "SELECT value_num FROM highlights WHERE character_id=? AND key='log_last_ts'",
            (self.cid,))
        self.agg = Aggregator(player_name=char.get('name') or '',
                              last_ts=seed['value_num'] if seed else None)
        self.tracker = FightTracker()
        self.tracker.on_end = self._on_fight_end
        self.session = _blank_session()

    # ── resume / checkpoint ──────────────────────────────────────────────────
    def _resume(self):
        """Set self.offset from the stored checkpoint, or 0 on first run,
        fingerprint mismatch, or truncation past the checkpoint."""
        self._fp = _fingerprint(self.path)
        if self._fp is None:            # empty or unreadable: nothing to resume
            self.offset = 0
            return
        rows = db.query('SELECT * FROM log_source WHERE path=?', (str(self.path),))
        match = next((r for r in rows if r['fingerprint'] == self._fp), None)
        if match:
            self.offset = int(match['byte_offset'])
            try:
                if self.path.stat().st_size < self.offset:
                    # same head, shorter file: truncated in place — rescan
                    self._reset_checkpoint()
            except OSError:
                self.offset = 0
        else:
            self.offset = 0
            if rows:                    # same path, different log: stale checkpoints
                self.reset = True
                db.execute('DELETE FROM log_source WHERE path=?', (str(self.path),))
            self._first_ts = self._probe_first_ts()
            db.execute(
                'INSERT OR IGNORE INTO log_source'
                '(character_id, path, fingerprint, first_ts, byte_offset, updated_at) '
                'VALUES(?,?,?,?,0,?)',
                (self.cid, str(self.path), self._fp, self._first_ts, db.now()))

    def _reset_checkpoint(self):
        """Truncation: the file on disk is shorter than our position."""
        self.reset = True
        self.offset = 0
        self._carry = b''
        self._fp = _fingerprint(self.path)
        db.execute('DELETE FROM log_source WHERE path=?', (str(self.path),))
        if self._fp:
            db.execute(
                'INSERT OR IGNORE INTO log_source'
                '(character_id, path, fingerprint, first_ts, byte_offset, updated_at) '
                'VALUES(?,?,?,?,0,?)',
                (self.cid, str(self.path), self._fp, self._probe_first_ts(), db.now()))

    def _probe_first_ts(self) -> Optional[float]:
        try:
            with self.path.open('rb') as f:
                first = f.readline(4096).decode('utf-8', 'replace')
        except OSError:
            return None
        ev_m = ext_parser.RE_TS.match(first)
        return ext_parser._ts(ev_m.group(1)) if ev_m else None

    def _flush(self):
        """Rows + fights + checkpoint, one transaction. The invariant carrier."""
        with db.tx() as c:
            self.agg.flush(c, self.cid)
            if self._pending_fights:
                c.executemany(
                    'INSERT OR IGNORE INTO fights(character_id, start, name, duration, '
                    'dps, total_damage, total_healing, total_tanking, xp, coin, data) '
                    'VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                    self._pending_fights)
                self._pending_fights = []
            if self._fp:
                c.execute(
                    'UPDATE log_source SET byte_offset=?, updated_at=? '
                    'WHERE path=? AND fingerprint=?',
                    (self.offset, db.now(), str(self.path), self._fp))

    # ── event plumbing ───────────────────────────────────────────────────────
    def _on_fight_end(self, fight):
        # Buffered, not written: on_end fires mid-parse and the row rides the
        # next _flush() transaction. A crash loses only what the lagging
        # checkpoint will replay, and INSERT OR IGNORE dedupes the replay.
        d = fight.to_dict(include_offense=True, detail=True)
        self._pending_fights.append((
            self.cid, d['start'], d['name'], d['duration'], d['dps'],
            d['total_damage'], d['total_healing'], d['total_tanking'],
            d['xp'], d['coin'], json.dumps(d)))

    def _consume(self, data: bytes):
        parts = (self._carry + data).split(b'\n')
        self._carry = parts.pop()
        # offset only ever advances past newline-terminated lines, so the carry
        # bytes were never counted when they first arrived — prepending them
        # here and adding len(part)+1 per completed line keeps offsets exact
        n = 0
        for part in parts:
            self.offset += len(part) + 1
            n += 1
            line = part.decode('utf-8', 'replace')
            if line.endswith('\r'):
                line = line[:-1]
            ev = ext_parser.parse(line, self.pet_name, self.group_members)
            if ev:
                self._handle(ev)
        self.lines += n
        self.agg.add_lines(n)

    def _handle(self, ev: dict):
        t = ev['type']
        self.last_line_ts = ev['ts']

        # pet / group roster (parser server.py's rules, kept simple)
        if t == 'pet_name':
            self.pet_name = ev['name']
        elif t == 'group_invite':
            self._pending_invite = ev['name']
        elif t == 'group_joined':
            if self._pending_invite:
                self.group_members.add(self._pending_invite)
                self._pending_invite = None
        elif t == 'group_member_seen':
            self.group_members.add(ev['name'])
        elif t == 'group_member_left':
            self.group_members.discard(ev['name'])
        elif t == 'group_disbanded':
            self.group_members.clear()
            self._pending_invite = None

        self.agg.feed(ev)

        if t == 'loot':
            self.tracker.add_loot(ev['item'], ev.get('source') or 'Unknown', ev['ts'])
        elif t == 'xp':
            self.tracker.add_xp(ev.get('pct') or 0.0, ev['ts'])
        elif t == 'coin':
            self.tracker.add_coin(ev.get('copper') or 0, ev['ts'])
        elif t in TRACKED_EVENTS:
            self.tracker.process(ev)

        # light session counters (since app start) for the Parser page feed
        s = self.session
        if t == 'damage' and ev.get('attacker') in ('player', 'pet'):
            s['dmg_dealt'] += ev['amount']
        elif t == 'damage_taken' and ev.get('victim', 'player') == 'player':
            s['dmg_taken'] += ev['amount']
        elif t == 'kill':
            s['kills'] += 1
        elif t == 'player_death':
            s['deaths'] += 1
            s['deaths_recent'] = (s['deaths_recent'] +
                                  [{'ts': ev['ts'], 'killer': ev.get('killer')}])[-5:]
        elif t == 'xp':
            s['xp_pct'] = round(s['xp_pct'] + (ev.get('pct') or 0.0), 4)
        elif t == 'cast' and ev.get('caster') == 'player':
            s['casts'] += 1
        elif t == 'fizzle':
            s['fizzles'] += 1
        elif t == 'loot':
            s['loot'] = (s['loot'] + [{'ts': ev['ts'], 'item': ev['item'],
                                       'source': ev.get('source')}])[-15:]
        elif t == 'skill':
            s['skill_ups'] = (s['skill_ups'] + [{'ts': ev['ts'], 'skill': ev['skill'],
                                                 'level': ev['level']}])[-10:]
        elif t in ('aa_gain', 'aa_spend'):
            s['aa'] = (s['aa'] + [{'ts': ev['ts'], 'kind': t.split('_')[1],
                                   'ability': ev.get('ability'),
                                   'points': ev.get('points'),
                                   'balance_after': ev.get('balance_after')}])[-5:]
        elif t == 'level_up':
            s['levels'] = (s['levels'] + [{'ts': ev['ts'], 'level': ev['level']}])[-5:]

    # ── snapshot ─────────────────────────────────────────────────────────────
    def _push_live(self, status: str):
        try:
            size = self.path.stat().st_size
        except OSError:
            size = self.offset
        # completed fights ship as meters only (detail=False) and the active
        # fight likewise — the page pulls full detail from /api/fights/{id}.
        # The parser learned to cap this hard: it rides the 1 Hz snapshot.
        active = None
        if self.tracker.active:
            f = self.tracker.active
            active = f.to_dict(include_offense=False, detail=False)
            if status == 'import':
                # an active fight's duration is wall-now minus start, which is
                # nonsense while replaying history — recompute from log time
                dur = max(f.last_activity - f.start_time, 0.1)
                active['duration'] = round(dur, 1)
                active['dps'] = round(active['total_damage'] / dur, 1)
                for v in active['damage'].values():
                    v['dps'] = round(v['total'] / dur, 1)
        payload = {
            'tail': {'status': status, 'offset': self.offset, 'size': size,
                     'line_ts': self.last_line_ts},
            'active_fight': active,
            'fights': [f.to_dict(include_offense=False, detail=False)
                       for f in reversed(self.tracker.completed[-SNAP_FIGHTS:])],
            'session': {k: (list(v) if isinstance(v, list) else v)
                        for k, v in self.session.items()},
        }
        # Fight.to_dict() is a SHALLOW copy: by_spell/by_victim (and a completed
        # fight's loot list inside LOOT_GRACE) stay live references this thread
        # keeps mutating between pushes. The WS handler json.dumps()es the
        # snapshot on another thread with no lock, so publish a deep copy —
        # taken HERE, on the only mutating thread, where it is race-free.
        payload = copy.deepcopy(payload)
        with state.lock:
            state.live.clear()
            state.live.update(payload)

    def _switch_requested(self) -> bool:
        """True when the active character (or its log path) changed. Throttled —
        it costs a db read and the idle loop spins at 20 Hz."""
        now = time.time()
        if now - self._last_switch_check < 1.0:
            return self._switch
        self._last_switch_check = now
        try:
            cur = characters.get()
        except Exception:
            return self._switch
        self._switch = (not cur or cur['id'] != self.cid
                        or (cur.get('log_path') or '') != str(self.path))
        return self._switch

    # ── phases ───────────────────────────────────────────────────────────────
    def scan_to_eof(self) -> dict:
        """Synchronous catch-up from the checkpoint to EOF ("import" phase).
        Flushes per ~4 MB chunk; returns {'status', 'lines', 'offset', 'size'}.
        Callable without any thread — tests and tools use it directly."""
        self._resume()
        started = time.time()
        try:
            size = self.path.stat().st_size
        except OSError as e:
            state.set_import(status='error', error=str(e))
            raise
        state.set_import(status='running', pct=self._pct(size), offset=self.offset,
                         size=size, lines=self.lines, started_at=started,
                         reset=self.reset, error=None)
        with self.path.open('rb') as f:
            f.seek(self.offset)
            while True:
                if self._switch_requested():
                    self._flush()
                    return {'status': 'switch', 'lines': self.lines,
                            'offset': self.offset, 'size': size}
                chunk = f.read(CHUNK_IMPORT)
                if not chunk:
                    break
                self._consume(chunk)
                self._flush()
                try:
                    size = self.path.stat().st_size   # the game keeps writing
                except OSError:
                    size = self.offset
                state.set_import(status='running', pct=self._pct(size),
                                 offset=self.offset, size=size, lines=self.lines)
                self._push_live('import')
        self._flush()
        state.set_import(status='done', pct=100.0, offset=self.offset,
                         size=max(size, self.offset), lines=self.lines)
        return {'status': 'eof', 'lines': self.lines, 'offset': self.offset,
                'size': max(size, self.offset), 'reset': self.reset,
                'seconds': round(time.time() - started, 3)}

    def _pct(self, size) -> float:
        return round(100.0 * self.offset / size, 1) if size else 100.0

    def _live_loop(self) -> str:
        """Tail at EOF: poll for new bytes, flush every ~2 s, push state ~1/s.
        Returns 'switch' (active character changed) or 'reopen' (truncated)."""
        dirty = False
        last_flush = last_ui = 0.0
        with self.path.open('rb') as f:
            f.seek(self.offset)
            while True:
                chunk = f.read(CHUNK_LIVE)
                if chunk:
                    self._consume(chunk)
                    dirty = True
                else:
                    if self._switch_requested():
                        self._flush()
                        return 'switch'
                    try:
                        if self.path.stat().st_size < self.offset:
                            # truncated in place: same failure the parser hit —
                            # the open handle reads '' forever past EOF
                            self._flush()
                            self._reset_checkpoint()
                            return 'reopen'
                    except OSError:
                        self._flush()
                        return 'reopen'    # vanished; run() reopens or waits
                    self.tracker.tick()    # log ts ~ wall clock while live
                    time.sleep(0.05)
                now = time.time()
                if dirty and now - last_flush >= FLUSH_SECONDS:
                    self._flush()
                    dirty = False
                    last_flush = now
                if now - last_ui >= UI_SECONDS:
                    self._push_live('live')
                    last_ui = now

    def run(self):
        """Thread body: import then live-tail; returns when the character changes."""
        while True:
            try:
                r = self.scan_to_eof()
                if r['status'] == 'switch':
                    return
                self._push_live('live')
                if self._live_loop() == 'switch':
                    return
                # 'reopen': checkpoint already reset — loop back into the scan
            except FileNotFoundError:
                if self._switch_requested():
                    return
                time.sleep(2)


# ── module thread ─────────────────────────────────────────────────────────────
def start() -> None:
    """Start the pipeline watcher thread. Idempotent; safe with no character."""
    global _thread
    with _lock:
        if _thread is not None and _thread.is_alive():
            return
        _thread = threading.Thread(target=_main, name='eqa-log-pipeline', daemon=True)
        _thread.start()


def _main():
    global current
    while True:
        try:
            char = characters.get()
        except Exception:
            char = None
        lp = char.get('log_path') if char else None
        if lp and Path(lp).is_file():
            pipe = Pipeline(char)
            current = pipe
            try:
                pipe.run()          # returns on character change
            except Exception as e:
                print(f'[tail] {e!r} — pipeline restarting', file=sys.stderr)
                time.sleep(2)
            finally:
                current = None
        else:
            with state.lock:
                state.live.clear()
                state.live.update({'tail': {'status': 'off'}})
            time.sleep(2)

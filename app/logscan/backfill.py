"""One-time, revisioned backfill of log-derived event history for a log the
pipeline had ALREADY consumed before those events existed.

The checkpoint sits at EOF on an existing install, so without this a new event
table would only ever see lines written after the upgrade. Each revision below
names the event types it introduced and the cheap substring gates that pick
their lines out of the log; a character whose stored revision is behind gets
exactly the missing revisions replayed over bytes [0, checkpoint) through an
events-only Aggregator restricted to those types — so a rev-2 backfill on a
rev-1 install inserts upgrade rows and touches nothing that rev 1 already
wrote. Rows and the two guard highlights commit in ONE transaction, so it runs
once and a crash mid-way simply reruns it.

A pipeline starting from byte 0 (fresh install, brand-new log) sets the guards
without reading anything: the normal scan handles every line.

Revisions:
  1  v1.1  craft / craft_capped / depot_* / faction / faction_capped (+ skill,
           which only VOTES for recipe->skill in events-only mode)
  2  v1.1  upgrade ("successfully merged two items…")
  3  v1.2  zone / xp / kill / loot — the zone clock and loot history. The
           'experience!' gate is deliberate: "You gain party experience!" is
           the majority of XP lines.
"""
import time
from pathlib import Path
from typing import Optional

from .. import db, state
from . import ext_parser
from .highlights import Aggregator

GUARD_KEY = 'events_backfill_offset'   # bytes covered; its presence alone means rev 1 is done
REV_KEY = 'events_backfill_rev'        # highest revision applied
BACKFILL_REV = 3
REVS = {
    1: {'types': frozenset({'craft', 'craft_capped', 'depot_consume', 'depot_deposit',
                            'depot_withdraw', 'faction', 'faction_capped', 'skill'}),
        'gates': ('fashion', 'no longer advance', 'personal depot', 'faction standing',
                  'become better at')},
    2: {'types': frozenset({'upgrade'}),
        'gates': ('merged two items',)},
    3: {'types': frozenset({'zone', 'xp', 'kill', 'loot'}),
        'gates': ('You have entered', 'experience!', 'You have slain', 'looted', 'You receive')},
}
CHUNK = 4 * 1024 * 1024


def stored_rev(character_id: int) -> int:
    rev = db.query_one('SELECT value_num FROM highlights WHERE character_id=? AND key=?',
                       (character_id, REV_KEY))
    if rev and rev['value_num'] is not None:
        return int(rev['value_num'])
    # a v1.1 install predates REV_KEY: the offset guard alone means rev 1 ran
    if db.query_one('SELECT 1 FROM highlights WHERE character_id=? AND key=?',
                    (character_id, GUARD_KEY)):
        return 1
    return 0


def needed(character_id: int) -> bool:
    return stored_rev(character_id) < BACKFILL_REV


def _set_guards(conn, character_id: int, offset: int) -> None:
    for key, val in ((GUARD_KEY, offset), (REV_KEY, BACKFILL_REV)):
        conn.execute(
            'INSERT INTO highlights(character_id, key, value_num, ts) VALUES(?,?,?,?) '
            'ON CONFLICT(character_id, key) DO UPDATE SET value_num=excluded.value_num, '
            'ts=excluded.ts', (character_id, key, val, db.now()))


def run(character_id: int, path: Path, end_offset: int) -> Optional[dict]:
    """Backfill [0, end_offset) for one character's log, for every revision not
    yet applied. Returns a summary, or None when nothing needed doing."""
    rev = stored_rev(character_id)
    if rev >= BACKFILL_REV:
        return None
    if end_offset <= 0:
        with db.tx() as c:
            _set_guards(c, character_id, 0)
        return None

    pending = [REVS[r] for r in range(rev + 1, BACKFILL_REV + 1)]
    types = frozenset().union(*(p['types'] for p in pending))
    gates = tuple(g for p in pending for g in p['gates'])

    started = time.time()
    agg = Aggregator(events_only=True, only_types=types)
    done = matched = lines = 0
    carry = b''
    state.set_import(status='backfill', pct=0.0, offset=0, size=end_offset,
                     lines=0, started_at=started, error=None)
    with path.open('rb') as f:
        while done < end_offset:
            chunk = f.read(min(CHUNK, end_offset - done))
            if not chunk:
                break
            done += len(chunk)
            parts = (carry + chunk).split(b'\n')
            carry = parts.pop()
            for part in parts:
                lines += 1
                line = part.decode('utf-8', 'replace')
                if line.endswith('\r'):
                    line = line[:-1]
                if not any(g in line for g in gates):
                    continue
                ev = ext_parser.parse(line)
                if ev:
                    matched += 1
                    agg.feed(ev)
            state.set_import(status='backfill', pct=round(100.0 * done / end_offset, 1),
                             offset=done, size=end_offset, lines=lines)
    # the checkpoint always sits on a line boundary, so `carry` is empty here;
    # if it is not, the partial line belongs to the live scan anyway
    with db.tx() as c:
        agg.flush(c, character_id)
        _set_guards(c, character_id, end_offset)
    return {'lines': lines, 'events': matched, 'offset': end_offset,
            'revisions': [r for r in range(rev + 1, BACKFILL_REV + 1)],
            'seconds': round(time.time() - started, 3)}

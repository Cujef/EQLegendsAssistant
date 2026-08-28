"""Aggregations shared by the importer and the live tailer (M3/M4).

An Aggregator instance consumes ext_parser events in memory and flush(conn, cid)
writes them inside the CALLER's transaction — the pipeline commits rows and the
log_source byte-offset checkpoint together, so the checkpoint can lag its data
but never lead it. Counters are plain additive deltas: the checkpoint guarantees
each log byte is consumed exactly once, so += is safe across restarts.

Max-type highlight keys use compare-and-swap in SQL (DO UPDATE ... WHERE
excluded.value_num > value_num); the in-memory side only keeps the batch max.
"""
import json
from typing import Optional

SESSION_GAP = 1800.0   # >30 min between events = a new play session

# events the fight tracker consumes via process(); kept here so the tailer and
# any future consumer agree on the split (loot/xp/coin go via add_* instead)
TRACKED_EVENTS = ('damage', 'miss', 'damage_taken', 'miss_taken', 'cast',
                  'fizzle', 'debuff_end', 'heal', 'kill', 'player_death')


class Aggregator:
    def __init__(self, player_name: str = '', last_ts: Optional[float] = None):
        # last_ts seeds the playtime clock from the stored log_last_ts highlight,
        # so resuming mid-session does not count a phantom extra session
        self.player_name = (player_name or '').lower()
        self._last_ts = last_ts
        self._reset_batch()

    def _reset_batch(self):
        self.skills = []       # (skill, level, ts)
        self.levels = []       # (level, ts)
        self.aa = []           # (ts, kind, ability_name, points, balance_after)
        self.deaths = []       # (ts, killer)
        self.counters = {}     # highlight key -> additive delta
        self.maxima = {}       # highlight key -> (value, ts, context dict)
        self.first_ts = None
        self.last_ts = None

    # ── intake ────────────────────────────────────────────────────────────────
    def add_lines(self, n: int):
        if n:
            self.counters['lines_parsed'] = self.counters.get('lines_parsed', 0) + n

    def _bump(self, key: str, n=1):
        self.counters[key] = self.counters.get(key, 0) + n

    def _max(self, key: str, value, ts: float, context: dict):
        cur = self.maxima.get(key)
        if cur is None or value > cur[0]:
            self.maxima[key] = (value, ts, context)

    def feed(self, ev: dict):
        ts = ev['ts']
        # playtime: sum gaps between consecutive events, session break past 30 min
        if self._last_ts is None:
            self._bump('total_sessions')
        else:
            gap = ts - self._last_ts
            if 0 < gap <= SESSION_GAP:
                self.counters['playtime_seconds'] = \
                    self.counters.get('playtime_seconds', 0) + gap
            elif gap > SESSION_GAP:
                self._bump('total_sessions')
        self._last_ts = ts
        if self.first_ts is None or ts < self.first_ts:
            self.first_ts = ts
        if self.last_ts is None or ts > self.last_ts:
            self.last_ts = ts

        t = ev['type']
        if t == 'skill':
            self.skills.append((ev['skill'], ev['level'], ts))
        elif t == 'level_up':
            self.levels.append((ev['level'], ts))
        elif t == 'aa_gain':
            # ability_name '' (not NULL): NULL breaks PK uniqueness in SQLite
            self.aa.append((ts, 'gain', '', ev.get('points', 1),
                            ev.get('balance_after')))
        elif t == 'aa_spend':
            self.aa.append((ts, 'spend', ev['ability'], ev['points'], None))
        elif t == 'kill':
            self._bump('total_kills')
        elif t == 'player_death':
            self.deaths.append((ts, ev.get('killer') or 'Unknown'))
            self._bump('total_deaths')
        elif t == 'damage' and ev.get('attacker') == 'player':
            amt = ev['amount']
            ctx = {'target': ev.get('target'), 'spell': ev.get('spell'),
                   'verb': ev.get('verb'), 'ts': ts}
            if ev.get('is_crit'):
                self._bump('total_crits')
            d = ev.get('dmg_type')
            if d == 'melee':
                self._max('max_melee_hit', amt, ts, ctx)
                if ev.get('is_crit'):
                    self._max('max_melee_crit', amt, ts, ctx)
            elif d == 'spell':
                self._max('max_spell_hit', amt, ts, ctx)
            elif d == 'dot':
                self._max('max_dot_tick', amt, ts, ctx)
        elif t == 'damage_taken' and ev.get('victim', 'player') == 'player':
            self._max('biggest_hit_taken', ev['amount'], ts,
                      {'target': ev.get('source'), 'spell': ev.get('spell'),
                       'verb': ev.get('verb'), 'ts': ts})
        elif t == 'heal':
            tgt = (ev.get('target') or '').lower()
            if tgt in ('you', 'yourself', 'player') or \
                    (self.player_name and tgt == self.player_name):
                self._max('max_heal_received', ev['amount'], ts,
                          {'target': ev.get('healer'), 'spell': ev.get('spell'),
                           'verb': 'heal', 'ts': ts})
        elif t == 'fizzle':
            self._bump('total_fizzles')
        elif t == 'cast' and ev.get('caster') == 'player':
            self._bump('total_casts')
        elif t == 'loot':
            self._bump('total_loot', ev.get('qty') or 1)
        elif t == 'coin':
            self._bump('total_coin_copper', ev.get('copper') or 0)

    # ── flush ─────────────────────────────────────────────────────────────────
    def flush(self, conn, character_id: int):
        """Write the batch inside the caller's transaction, then clear it."""
        cid = character_id
        if self.skills:
            conn.executemany(
                'INSERT OR IGNORE INTO skill_levels(character_id, skill, level, ts) '
                'VALUES(?,?,?,?)',
                [(cid, s, lv, ts) for s, lv, ts in self.skills])
        if self.levels:
            conn.executemany(
                'INSERT OR IGNORE INTO level_history(character_id, level, ts) '
                'VALUES(?,?,?)',
                [(cid, lv, ts) for lv, ts in self.levels])
        if self.aa:
            conn.executemany(
                'INSERT OR IGNORE INTO aa_ledger'
                '(character_id, ts, kind, ability_name, points, balance_after) '
                'VALUES(?,?,?,?,?,?)',
                [(cid, ts, k, a, p, b) for ts, k, a, p, b in self.aa])
        if self.deaths:
            conn.executemany(
                'INSERT OR IGNORE INTO deaths(character_id, ts, killer) VALUES(?,?,?)',
                [(cid, ts, k) for ts, k in self.deaths])
        for key, delta in self.counters.items():
            conn.execute(
                'INSERT INTO highlights(character_id, key, value_num, ts) '
                'VALUES(?,?,?,?) '
                'ON CONFLICT(character_id, key) DO UPDATE SET '
                'value_num = COALESCE(value_num, 0) + excluded.value_num, '
                'ts = COALESCE(excluded.ts, ts)',
                (cid, key, delta, self.last_ts))
        for key, (val, ts, ctx) in self.maxima.items():
            conn.execute(
                'INSERT INTO highlights(character_id, key, value_num, ts, context_json) '
                'VALUES(?,?,?,?,?) '
                'ON CONFLICT(character_id, key) DO UPDATE SET '
                'value_num = excluded.value_num, ts = excluded.ts, '
                'context_json = excluded.context_json '
                'WHERE excluded.value_num > highlights.value_num',
                (cid, key, val, ts, json.dumps(ctx)))
        if self.first_ts is not None:
            conn.execute(
                'INSERT INTO highlights(character_id, key, value_num, ts) '
                'VALUES(?,?,?,?) '
                'ON CONFLICT(character_id, key) DO UPDATE SET '
                'value_num = excluded.value_num, ts = excluded.ts '
                'WHERE excluded.value_num < highlights.value_num',
                (cid, 'log_first_ts', self.first_ts, self.first_ts))
        if self.last_ts is not None:
            conn.execute(
                'INSERT INTO highlights(character_id, key, value_num, ts) '
                'VALUES(?,?,?,?) '
                'ON CONFLICT(character_id, key) DO UPDATE SET '
                'value_num = excluded.value_num, ts = excluded.ts '
                'WHERE excluded.value_num > highlights.value_num',
                (cid, 'log_last_ts', self.last_ts, self.last_ts))
        self._reset_batch()

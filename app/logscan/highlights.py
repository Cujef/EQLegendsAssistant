"""Aggregations shared by the importer and the live tailer (M3/M4).

An Aggregator instance consumes ext_parser events in memory and flush(conn, cid)
writes them inside the CALLER's transaction — the pipeline commits rows and the
log_source byte-offset checkpoint together, so the checkpoint can lag its data
but never lead it. Counters are plain additive deltas: the checkpoint guarantees
each log byte is consumed exactly once, so += is safe across restarts. The same
guarantee is why the tradeskill / faction / depot event tables need no
uniqueness constraint (and must not have one: two kills in one second produce
two byte-identical faction lines, both real).

Max-type highlight keys use compare-and-swap in SQL (DO UPDATE ... WHERE
excluded.value_num > value_num); the in-memory side only keeps the batch max.

Tradeskill correlation (measured on the reference log, 2216 cap lines):
- "You can no longer advance your skill from making this item." PRECEDES the
  combine it refers to — same second as the following "fashioned" line in
  2214/2216 cases, 1 s earlier in the other two, never within 2 s of the
  previous combine. So a cap notice is held and attached to the NEXT craft
  that arrives within CRAFT_LINK_WINDOW (upstream attaches it backwards; that
  tags the wrong recipe).
- "You have become better at Baking! (135)" lands in the same second as its
  combine, on either side of it. At a 1 s window 448/467 skill-ups link with
  zero ambiguity; at 3 s the neighbouring combine falls inside. Skill-ups are
  VOTES for a recipe->skill mapping (craft_recipe_skill), never facts.
"""
import json
import re
from typing import Optional

from ..inventory import normalize_name
from ..tradeskills import TRADESKILL_NAMES

SESSION_GAP = 1800.0        # >30 min between events = a new play session
CRAFT_LINK_WINDOW = 1.0     # seconds; see module docstring

# Zone clock (v1.2): time in a zone is the sum of gaps <= SESSION_GAP between
# your own zone / xp / kill / loot lines — ONLY those four types, in both the
# live path and the gated backfill, so the two agree exactly. Instance
# suffixes ("Najena 2 (Adaptive)", "The Plane of Fear - Group 1 (Awakened)")
# are stripped so stats key on the zone, not the instance.
ZONE_TYPES = frozenset({'zone', 'xp', 'kill', 'loot'})
RE_ZONE_INSTANCE = re.compile(r'\s*(?:-\s*Group)?\s*\d+\s*\([A-Za-z]+\)\s*$')


def zone_base(name: str) -> str:
    return ' '.join(RE_ZONE_INSTANCE.sub('', str(name or '')).split())

# events the fight tracker consumes via process(); kept here so the tailer and
# any future consumer agree on the split (loot/xp/coin go via add_* instead)
TRACKED_EVENTS = ('damage', 'miss', 'damage_taken', 'miss_taken', 'cast',
                  'fizzle', 'debuff_end', 'heal', 'kill', 'player_death')

# events the events-only (backfill) mode cares about
EVENT_TYPES = ('craft', 'craft_capped', 'craft_error', 'depot_consume', 'depot_deposit',
               'depot_withdraw', 'faction', 'faction_capped', 'skill', 'upgrade',
               'zone', 'xp', 'kill', 'loot')


class Aggregator:
    def __init__(self, player_name: str = '', last_ts: Optional[float] = None,
                 events_only: bool = False, only_types=None):
        # last_ts seeds the playtime clock from the stored log_last_ts highlight,
        # so resuming mid-session does not count a phantom extra session
        self.player_name = (player_name or '').lower()
        self._last_ts = last_ts
        # events_only: the one-time backfill of tradeskill/faction history over
        # bytes the pipeline already consumed — nothing else may be touched or
        # every additive counter would double. only_types narrows it further
        # (a later backfill revision must not re-insert an earlier one's rows).
        self.events_only = events_only
        self.only_types = frozenset(only_types) if only_types else frozenset(EVENT_TYPES)
        # correlation state — survives _reset_batch on purpose (a cap notice and
        # its combine, or a skill-up and its combine, may straddle a flush)
        self._last_craft = None         # (item, ts)
        self._cap_pending_ts = None     # ts of an unattached cap notice
        self._pending_skill = None      # (skill, ts) skill-up seen before its combine
        self.last_craft_capped = False  # for the tailer's session feed
        self._zone = None               # current zone (base name), seeded by seed_zone()
        self._zone_last_ts = None       # last zone-clock event
        self._reset_batch()

    def seed_zone(self, zone: Optional[str], last_ts: Optional[float]) -> None:
        """Resume the zone clock from what the DB says was committed: the last
        zone_events row and the `zone_clock_ts` highlight (NOT log_last_ts,
        which is the max over every event type and would count a kill-minus-
        damage gap after a restart)."""
        self._zone = zone_base(zone) if zone else None
        self._zone_last_ts = last_ts

    def _reset_batch(self):
        self.skills = []       # (skill, level, ts)
        self.levels = []       # (level, ts)
        self.aa = []           # (ts, kind, ability_name, points, balance_after)
        self.deaths = []       # (ts, killer)
        self.counters = {}     # highlight key -> additive delta
        self.maxima = {}       # highlight key -> (value, ts, context dict)
        self.first_ts = None
        self.last_ts = None
        self.crafts = []       # (ts, item, item_norm, ok, capped)
        self.craft_caps = []   # (item, ts)
        self.recipe_votes = {}  # (item, skill) -> [votes, last_ts]
        self.depot = []        # (ts, kind, item, item_norm, qty, left_qty)
        self.faction = []      # (ts, faction, delta)
        self.faction_caps = []  # (faction, direction, ts)
        self.upgrades = []     # (ts, item, item_norm, tier)
        self.zone_deltas = {}  # zone_base -> {seconds, kills, xp_pct, loot, visits, first_ts, last_ts}
        self.zone_visits = []  # (ts, raw zone, zone_base)
        self.loot = []         # (ts, item, item_norm, source, qty, zone_base|None)
        self.zone_clock_ts = None

    # ── intake ────────────────────────────────────────────────────────────────
    def add_lines(self, n: int):
        if n and not self.events_only:   # a backfill re-reads bytes already counted
            self.counters['lines_parsed'] = self.counters.get('lines_parsed', 0) + n

    def _bump(self, key: str, n=1):
        self.counters[key] = self.counters.get(key, 0) + n

    def _max(self, key: str, value, ts: float, context: dict):
        cur = self.maxima.get(key)
        if cur is None or value > cur[0]:
            self.maxima[key] = (value, ts, context)

    def _vote(self, item: str, skill: str, ts: float):
        v = self.recipe_votes.setdefault((item, skill), [0, ts])
        v[0] += 1
        v[1] = max(v[1], ts)

    # ── zone clock + loot ─────────────────────────────────────────────────────
    def _zone_delta(self, zone: str) -> dict:
        d = self.zone_deltas.get(zone)
        if d is None:
            d = self.zone_deltas[zone] = {'seconds': 0.0, 'kills': 0, 'xp_pct': 0.0, 'loot': 0,
                                          'visits': 0, 'first_ts': None, 'last_ts': None}
        return d

    def _zone_touch(self, d: dict, ts: float) -> None:
        if d['first_ts'] is None or ts < d['first_ts']:
            d['first_ts'] = ts
        if d['last_ts'] is None or ts > d['last_ts']:
            d['last_ts'] = ts

    def _tick_zone(self, ts: float) -> None:
        """Advance the clock of the CURRENT zone by the gap since the previous
        zone-clock event (gaps over SESSION_GAP are idle time, not zone time)."""
        if self._zone is not None and self._zone_last_ts is not None:
            gap = ts - self._zone_last_ts
            if 0 < gap <= SESSION_GAP:
                d = self._zone_delta(self._zone)
                d['seconds'] += gap
                self._zone_touch(d, ts)
        self._zone_last_ts = ts
        self.zone_clock_ts = ts if self.zone_clock_ts is None else max(self.zone_clock_ts, ts)

    def _feed_zone(self, t: str, ev: dict, ts: float) -> None:
        if t == 'zone':
            self._tick_zone(ts)                       # time until leaving belongs to the OLD zone
            base = zone_base(ev['zone'])
            self._zone = base
            d = self._zone_delta(base)
            d['visits'] += 1
            self._zone_touch(d, ts)
            self.zone_visits.append((ts, ev['zone'], base))
            return
        self._tick_zone(ts)
        qty = 0
        if t == 'loot':
            qty = int(ev.get('qty') or 1)
            self.loot.append((ts, ev['item'], normalize_name(ev['item']),
                              ev.get('source') or 'Unknown', qty, self._zone))
        if self._zone is None:
            return                                    # before the first zone line: unattributed
        d = self._zone_delta(self._zone)
        self._zone_touch(d, ts)
        if t == 'kill':
            d['kills'] += 1
        elif t == 'xp':
            d['xp_pct'] += float(ev.get('pct') or 0.0)
        elif t == 'loot':
            d['loot'] += qty

    def _feed_events(self, t: str, ev: dict, ts: float):
        """Tradeskill / depot / faction bookkeeping — shared by the live path
        and the events-only backfill."""
        if t == 'craft_capped':
            self._cap_pending_ts = ts
        elif t == 'craft':
            item = ev['item']
            capped = (self._cap_pending_ts is not None
                      and 0 <= ts - self._cap_pending_ts <= CRAFT_LINK_WINDOW)
            self._cap_pending_ts = None
            self.last_craft_capped = capped
            ok = 1 if ev.get('ok') else 0
            self.crafts.append((ts, item, normalize_name(item), ok, 1 if capped else 0))
            if capped:
                self.craft_caps.append((item, ts))
            if self._pending_skill and 0 <= ts - self._pending_skill[1] <= CRAFT_LINK_WINDOW:
                self._vote(item, self._pending_skill[0], ts)
            self._pending_skill = None      # consumed, or too old to mean anything
            self._last_craft = (item, ts)
            self._bump('total_crafts')
            if not ok:
                self._bump('total_craft_fails')
        elif t == 'skill' and ev.get('skill') in TRADESKILL_NAMES:
            if self._last_craft and 0 <= ts - self._last_craft[1] <= CRAFT_LINK_WINDOW:
                self._vote(self._last_craft[0], ev['skill'], ts)
            else:
                self._pending_skill = (ev['skill'], ts)   # its combine line comes next
        elif t == 'depot_consume':
            self.depot.append((ts, 'consume', ev['item'], normalize_name(ev['item']),
                               int(ev.get('qty') or 0), ev.get('left')))
        elif t == 'depot_deposit':
            self.depot.append((ts, 'deposit', ev['item'], normalize_name(ev['item']),
                               int(ev.get('qty') or 0), None))
        elif t == 'depot_withdraw':
            self.depot.append((ts, 'withdraw', ev['item'], normalize_name(ev['item']),
                               int(ev.get('qty') or 0), None))
        elif t == 'faction':
            self.faction.append((ts, ev['faction'], int(ev['delta'])))
        elif t == 'faction_capped':
            self.faction_caps.append((ev['faction'], ev['direction'], ts))
        elif t == 'craft_error':
            self._bump('total_craft_errors')
        elif t == 'upgrade':
            self.upgrades.append((ts, ev['item'], normalize_name(ev['item']), ev.get('tier')))
            self._bump('total_upgrades')

    def feed(self, ev: dict):
        ts = ev['ts']
        t = ev['type']
        if self.events_only:
            if t in self.only_types:
                if t in ZONE_TYPES:
                    self._feed_zone(t, ev, ts)
                self._feed_events(t, ev, ts)
            return

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

        self._feed_events(t, ev, ts)
        if t in ZONE_TYPES:
            self._feed_zone(t, ev, ts)

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
            if ev.get('sold_copper'):          # auto-sold on loot: vendor income, kept apart from kill coin
                self._bump('total_autosell_copper', ev['sold_copper'])
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

        # tradeskill / depot / faction events — plain INSERT, see module docstring
        if self.crafts:
            conn.executemany(
                'INSERT INTO craft_events(character_id, ts, item, item_norm, ok, capped) '
                'VALUES(?,?,?,?,?,?)',
                [(cid, ts, item, norm, ok, capped)
                 for ts, item, norm, ok, capped in self.crafts])
        for item, ts in self.craft_caps:
            conn.execute(
                'INSERT INTO craft_caps(character_id, item, first_ts, last_ts, count) '
                'VALUES(?,?,?,?,1) ON CONFLICT(character_id, item) DO UPDATE SET '
                'last_ts = MAX(last_ts, excluded.last_ts), count = count + 1',
                (cid, item, ts, ts))
        for (item, skill), (votes, ts) in self.recipe_votes.items():
            conn.execute(
                'INSERT INTO craft_recipe_skill(character_id, item, skill, votes, last_ts) '
                'VALUES(?,?,?,?,?) ON CONFLICT(character_id, item, skill) DO UPDATE SET '
                'votes = votes + excluded.votes, '
                'last_ts = MAX(COALESCE(last_ts, 0), excluded.last_ts)',
                (cid, item, skill, votes, ts))
        if self.depot:
            conn.executemany(
                'INSERT INTO depot_events(character_id, ts, kind, item, item_norm, qty, left_qty) '
                'VALUES(?,?,?,?,?,?,?)',
                [(cid, ts, kind, item, norm, qty, left)
                 for ts, kind, item, norm, qty, left in self.depot])
        if self.faction:
            conn.executemany(
                'INSERT INTO faction_events(character_id, ts, faction, delta) VALUES(?,?,?,?)',
                [(cid, ts, f, d) for ts, f, d in self.faction])
        for faction, direction, ts in self.faction_caps:
            conn.execute(
                'INSERT INTO faction_caps(character_id, faction, direction, first_ts, last_ts, count) '
                'VALUES(?,?,?,?,?,1) ON CONFLICT(character_id, faction) DO UPDATE SET '
                'direction = excluded.direction, last_ts = MAX(last_ts, excluded.last_ts), '
                'count = count + 1',
                (cid, faction, direction, ts, ts))
        if self.upgrades:
            conn.executemany(
                'INSERT INTO upgrade_events(character_id, ts, item, item_norm, tier) '
                'VALUES(?,?,?,?,?)',
                [(cid, ts, item, norm, tier) for ts, item, norm, tier in self.upgrades])

        # zone + loot history (v1.2) — additive deltas + per-line rows
        if self.zone_visits:
            conn.executemany(
                'INSERT INTO zone_events(character_id, ts, zone, zone_base) VALUES(?,?,?,?)',
                [(cid, ts, raw, base) for ts, raw, base in self.zone_visits])
        if self.loot:
            conn.executemany(
                'INSERT INTO loot_events(character_id, ts, item, item_norm, source, qty, zone) '
                'VALUES(?,?,?,?,?,?,?)',
                [(cid, ts, item, norm, src, qty, zone)
                 for ts, item, norm, src, qty, zone in self.loot])
        for zone, d in self.zone_deltas.items():
            conn.execute(
                'INSERT INTO zone_stats(character_id, zone, seconds, kills, xp_pct, loot, visits, '
                'first_ts, last_ts) VALUES(?,?,?,?,?,?,?,?,?) '
                'ON CONFLICT(character_id, zone) DO UPDATE SET '
                'seconds = seconds + excluded.seconds, kills = kills + excluded.kills, '
                'xp_pct = xp_pct + excluded.xp_pct, loot = loot + excluded.loot, '
                'visits = visits + excluded.visits, '
                'first_ts = MIN(COALESCE(first_ts, excluded.first_ts), excluded.first_ts), '
                'last_ts = MAX(COALESCE(last_ts, 0), excluded.last_ts)',
                (cid, zone, d['seconds'], d['kills'], d['xp_pct'], d['loot'], d['visits'],
                 d['first_ts'], d['last_ts']))
        if self.zone_clock_ts is not None:
            conn.execute(
                'INSERT INTO highlights(character_id, key, value_num, ts) VALUES(?,?,?,?) '
                'ON CONFLICT(character_id, key) DO UPDATE SET '
                'value_num = excluded.value_num, ts = excluded.ts '
                'WHERE excluded.value_num > highlights.value_num',
                (cid, 'zone_clock_ts', self.zone_clock_ts, self.zone_clock_ts))

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

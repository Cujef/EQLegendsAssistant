"""EQ Legends fight state machine."""
import time
from typing import Dict, List, Optional, Set

FIGHT_TIMEOUT = 15.0
MAX_HISTORY   = 100
LOOT_GRACE    = 60.0  # attribute loot to a fight that ended this recently
PRECAST_WINDOW = 8.0  # attribute a cast to a fight it started just before (opening nuke)
ROUND_WINDOW  = 3.0   # how long a multi-attack round bucket stays live
HITS_CAP      = 300   # serialized hit log per fight
CASTS_CAP     = 100   # serialized cast log per fight (a long fight can accumulate hundreds)

AVOID_KINDS = ('dodge', 'parry', 'riposte', 'block', 'absorb')


def _new_verb_stat() -> dict:
    return {
        'total': 0, 'count': 0,
        'crits': 0, 'crit_total': 0,
        'max_hit': 0, 'max_crit': 0,
        'misses': 0, 'avoided': {k: 0 for k in AVOID_KINDS},
        'riposte_count': 0, 'riposte_total': 0,
        'doubles': 0, 'triples': 0,
    }


def _new_actor_stat() -> dict:
    return {
        'swings': 0, 'hits': 0, 'misses': 0, 'total': 0,
        'crits': 0, 'crit_total': 0,
        'avoided': {k: 0 for k in AVOID_KINDS},
        'riposte_count': 0, 'riposte_total': 0, 'double_ripostes': 0,
        'riposte_triggers': 0,   # times you riposted an incoming attack (player only)
        'doubles': 0, 'triples': 0,
        'max_hit':  {'amt': 0, 'verb': None, 'target': None, 'ts': 0},
        'max_crit': {'amt': 0, 'verb': None, 'target': None, 'ts': 0},
    }


class OffenseTracker:
    """Per-actor / per-verb melee breakdown: accuracy, crits, maxima, multi-attacks, riposte.

    Used at both fight scope (inside FightStats) and session scope (server.py) so the two
    always agree. Multi-attack detection buckets swings by whole second because EQ log
    timestamps have 1-second resolution — see `doubles`/`triples`.
    """

    def __init__(self):
        self.verbs:  Dict[str, Dict[str, dict]] = {}
        self.actors: Dict[str, dict] = {}
        self._rounds: Dict[tuple, int] = {}

    def _verb(self, actor: str, verb: str) -> dict:
        va = self.verbs.setdefault(actor, {})
        if verb not in va:
            va[verb] = _new_verb_stat()
        return va[verb]

    def _actor(self, actor: str) -> dict:
        if actor not in self.actors:
            self.actors[actor] = _new_actor_stat()
        return self.actors[actor]

    def _bump_round(self, actor: str, key: str, ts: float, vs: Optional[dict], a: dict):
        """Count a swing into its 1-second bucket and promote double -> triple."""
        sec = int(ts)
        bucket = (actor, key, sec)
        n = self._rounds.get(bucket, 0) + 1
        self._rounds[bucket] = n
        if n == 2:
            if vs is not None:
                vs['doubles'] += 1
            if key == '__riposte__':
                a['double_ripostes'] += 1
            else:
                a['doubles'] += 1
        elif n == 3:
            if vs is not None:
                vs['doubles'] -= 1
                vs['triples'] += 1
            if key != '__riposte__':
                a['doubles'] -= 1
                a['triples'] += 1
        if len(self._rounds) > 512:
            cutoff = sec - ROUND_WINDOW
            self._rounds = {k: v for k, v in self._rounds.items() if k[2] >= cutoff}

    def add_damage(self, actor: str, verb: Optional[str], amount: int, dmg_type: str,
                   target: Optional[str], ts: float, flags: dict):
        a = self._actor(actor)
        a['total'] += amount
        is_crit = flags.get('is_crit', False)
        is_riposte = flags.get('is_riposte', False)

        if is_crit:
            a['crits'] += 1
            a['crit_total'] += amount
        if is_riposte:
            a['riposte_count'] += 1
            a['riposte_total'] += amount
            self._bump_round(actor, '__riposte__', ts, None, a)

        if amount > a['max_hit']['amt']:
            a['max_hit'] = {'amt': amount, 'verb': verb, 'target': target, 'ts': ts}
        if is_crit and amount > a['max_crit']['amt']:
            a['max_crit'] = {'amt': amount, 'verb': verb, 'target': target, 'ts': ts}

        # only real melee swings participate in verb/accuracy/multi-attack accounting
        if dmg_type != 'melee' or not verb:
            return
        a['swings'] += 1
        a['hits'] += 1

        vs = self._verb(actor, verb)
        vs['total'] += amount
        vs['count'] += 1
        if amount > vs['max_hit']:
            vs['max_hit'] = amount
        if is_crit:
            vs['crits'] += 1
            vs['crit_total'] += amount
            if amount > vs['max_crit']:
                vs['max_crit'] = amount
        if is_riposte:
            vs['riposte_count'] += 1
            vs['riposte_total'] += amount
        self._bump_round(actor, verb, ts, vs, a)

    def add_miss(self, actor: str, verb: Optional[str], outcome: str):
        a = self._actor(actor)
        a['swings'] += 1
        vs = self._verb(actor, verb) if verb else None
        if outcome == 'miss':
            a['misses'] += 1
            if vs:
                vs['misses'] += 1
        elif outcome in AVOID_KINDS:
            a['avoided'][outcome] += 1
            if vs:
                vs['avoided'][outcome] += 1

    def add_riposte_trigger(self, actor: str = 'player'):
        self._actor(actor)['riposte_triggers'] += 1

    @classmethod
    def restore(cls, d: dict) -> 'OffenseTracker':
        """Rebuild from a `to_dict()` blob — used once, at startup, from the database.

        The derived columns (`accuracy`, `crit_rate`, `avg`, `attempts`) ride back in and are
        harmless: `to_dict()` recomputes and overwrites every one of them from the raw
        counters, so a restored tracker and a live one serialize identically. `_rounds` is
        deliberately NOT restored — multi-attack buckets are 3 seconds wide and the log they
        described is minutes old.
        """
        t = cls()
        for name, a in (d.get('actors') or {}).items():
            base = _new_actor_stat()
            base.update(a)
            t.actors[name] = base
        for name, va in (d.get('verbs') or {}).items():
            out = {}
            for verb, v in va.items():
                base = _new_verb_stat()
                base.update(v)
                out[verb] = base
            t.verbs[name] = out
        return t

    def to_dict(self) -> dict:
        actors = {}
        for name, a in self.actors.items():
            swings = a['swings']
            actors[name] = {
                **a,
                'accuracy': round(100 * a['hits'] / swings, 1) if swings else 0.0,
                'crit_rate': round(100 * a['crits'] / a['hits'], 1) if a['hits'] else 0.0,
            }
        verbs = {}
        for name, va in self.verbs.items():
            out = {}
            for verb, v in va.items():
                attempts = v['count'] + v['misses'] + sum(v['avoided'].values())
                out[verb] = {
                    **v,
                    'avg': round(v['total'] / v['count'], 1) if v['count'] else 0.0,
                    'accuracy': round(100 * v['count'] / attempts, 1) if attempts else 0.0,
                    'crit_rate': round(100 * v['crits'] / v['count'], 1) if v['count'] else 0.0,
                    'attempts': attempts,
                }
            verbs[name] = out
        return {'actors': actors, 'verbs': verbs}


class FightStats:
    def __init__(self):
        self.damage:  Dict[str, dict] = {}
        self.healing: Dict[str, dict] = {}
        self.tanking: Dict[str, dict] = {}
        self.offense: OffenseTracker  = OffenseTracker()

    def add_damage(self, attacker: str, amount: int, dmg_type: str, spell: Optional[str]):
        if attacker not in self.damage:
            self.damage[attacker] = {'total': 0, 'melee': 0, 'spell': 0, 'dot': 0, 'ds': 0,
                                     'by_spell': {}}
        d = self.damage[attacker]
        d['total'] += amount
        d[dmg_type] = d.get(dmg_type, 0) + amount
        key = spell if spell else 'Melee'
        d['by_spell'][key] = d['by_spell'].get(key, 0) + amount

    def add_healing(self, healer: str, amount: int, spell: Optional[str], is_hot: bool):
        if healer not in self.healing:
            self.healing[healer] = {'total': 0, 'direct': 0, 'hot': 0, 'by_spell': {}}
        h = self.healing[healer]
        h['total'] += amount
        h['hot' if is_hot else 'direct'] += amount
        if spell:
            h['by_spell'][spell] = h['by_spell'].get(spell, 0) + amount

    def add_tanking(self, source: str, amount: int, dmg_type: str, spell: Optional[str] = None,
                    victim: str = 'player'):
        """Record incoming damage from `source`. `victim` is 'player', 'pet', or an ally name.

        v1.4.0 added the third case, so `victim` is no longer a two-valued flag and
        `on_pet if pet else on_player` would have quietly folded every group member's
        damage into YOUR number — the same bug Phase 4 fixes at session scope. on_player /
        on_pet therefore keep their exact pre-v1.4.0 meaning (only you / only the pet) and
        the per-name detail lives in `by_victim`, which the client inverts to rank who is
        actually eating the damage. Old archives have no `by_victim` and fall back.
        """
        if source not in self.tanking:
            self.tanking[source] = {'total': 0, 'melee': 0, 'spell': 0, 'ds': 0, 'by_spell': {},
                                    'on_player': 0, 'on_pet': 0, 'by_victim': {}}
        t = self.tanking[source]
        t['total'] += amount
        t[dmg_type] = t.get(dmg_type, 0) + amount
        if victim == 'pet':
            t['on_pet'] += amount
        elif victim == 'player':
            t['on_player'] += amount
        t['by_victim'][victim] = t['by_victim'].get(victim, 0) + amount
        key = spell if spell else 'Melee'
        t['by_spell'][key] = t['by_spell'].get(key, 0) + amount


class Fight:
    _counter = 0

    def __init__(self, mob_name: str, start_time: float):
        Fight._counter += 1
        self.id:            int            = Fight._counter
        self.mob_name:      str            = mob_name
        self.start_time:    float          = start_time
        self.end_time:      Optional[float] = None
        self.is_active:     bool           = True
        self.last_activity: float          = start_time
        self.mobs_involved: Set[str]       = {mob_name.lower()}
        self.mobs_slain:    Set[str]       = set()
        self.stats:         FightStats     = FightStats()
        self.hits:          List[dict]     = []
        self.loot:          List[dict]     = []
        self.xp:            float          = 0.0
        self.coin:          int            = 0
        self.casts:         List[dict]     = []
        self.debuffs:       List[dict]     = []
        self._dot_start:    Dict[tuple, float] = {}  # (spell, target_lower) -> first-tick ts

    @classmethod
    def restore(cls, d: dict) -> 'Fight':
        """Rebuild a completed fight from its stored meters. Startup only.

        Does NOT allocate a new id — it takes the one it was stored with, and the caller is
        responsible for pushing `Fight._counter` past the highest restored id afterwards. Get
        that wrong and the next live fight reuses an id that /api/fight/{id} already answers
        for, which silently poisons the client's fightCache with another fight's numbers.

        The per-event logs (`hits`, `casts`, `debuffs`) stay empty on purpose. They are not in
        the snapshot for a completed fight, and the DB hands them back in full on demand — so
        restoring them would cost RAM to duplicate something already on disk.
        """
        f = cls.__new__(cls)                      # bypasses __init__ and its counter bump
        f.id            = int(d.get('id') or 0)
        f.mob_name      = d.get('name') or '?'
        f.start_time    = d.get('start') or 0.0
        f.is_active     = False
        f.end_time      = f.start_time + (d.get('duration') or 0.0)
        f.last_activity = f.end_time
        f.mobs_involved = set(d.get('mobs') or [f.mob_name])
        f.mobs_slain    = set()
        f.stats         = FightStats()
        f.stats.damage  = dict(d.get('damage') or {})
        f.stats.healing = dict(d.get('healing') or {})
        f.stats.tanking = dict(d.get('tanking') or {})
        f.stats.offense = OffenseTracker.restore(d.get('offense') or {})
        f.hits          = []
        f.loot          = list(d.get('loot') or [])
        f.xp            = d.get('xp') or 0.0
        f.coin          = d.get('coin') or 0
        f.casts         = []
        f.debuffs       = []
        f._dot_start    = {}
        return f

    @property
    def duration(self) -> float:
        return max((self.end_time or time.time()) - self.start_time, 0.1)

    @property
    def total_damage(self) -> int:
        return sum(d['total'] for d in self.stats.damage.values())

    @property
    def total_healing(self) -> int:
        return sum(h['total'] for h in self.stats.healing.values())

    @property
    def total_tanking(self) -> int:
        return sum(t['total'] for t in self.stats.tanking.values())

    def to_dict(self, include_offense: bool = True, detail: bool = True) -> dict:
        """Serialize the fight.

        `detail=False` drops the three per-event logs (`hits`, `casts`, `debuffs`). The UI
        only ever renders those for ONE fight at a time, yet 50 completed fights carried
        them in every 1 Hz snapshot — 1.49 MB of a 1.79 MB push. Completed fights now ship
        as meters only and the client pulls the full record from /api/fight/{id} on demand.
        """
        dur   = self.duration
        tdmg  = self.total_damage
        theal = self.total_healing
        ttank = self.total_tanking

        def pct(val, total):
            return round(100 * val / total, 1) if total else 0.0

        damage = {
            k: {**v, 'dps': round(v['total'] / dur, 1), 'pct': pct(v['total'], tdmg)}
            for k, v in self.stats.damage.items()
        }
        healing = {
            k: {**h, 'hps': round(h['total'] / dur, 1), 'pct': pct(h['total'], theal)}
            for k, h in self.stats.healing.items()
        }
        tanking = {
            k: {**t, 'dtps': round(t['total'] / dur, 1), 'pct': pct(t['total'], ttank)}
            for k, t in self.stats.tanking.items()
        }

        out = {
            'id':            self.id,
            'name':          self.mob_name,
            'is_active':     self.is_active,
            'start':         self.start_time,
            'duration':      round(dur, 1),
            'total_damage':  tdmg,
            'total_healing': theal,
            'total_tanking': ttank,
            'dps':           round(tdmg / dur, 1),
            'damage':        damage,
            'healing':       healing,
            'tanking':       tanking,
            'mobs':          sorted(self.mobs_involved),
            'loot':          self.loot,
            'xp':            round(self.xp, 4),
            'coin':          self.coin,
        }
        if detail:
            end = self.end_time or time.time()
            debuffs = list(self.debuffs)
            for (spell, target), start in self._dot_start.items():
                debuffs.append({'spell': spell, 'target': target, 'start': start,
                                'end': end, 'ongoing': True})
            out['hits']    = self.hits[-HITS_CAP:]
            out['casts']   = self.casts[-CASTS_CAP:]
            out['debuffs'] = debuffs
        # offense breakdown is large; only the active fight needs it on the wire
        if include_offense:
            out['offense'] = self.stats.offense.to_dict()
        return out


class FightTracker:
    def __init__(self):
        self.active:       Optional[Fight] = None
        self.completed:    List[Fight]     = []
        self.recent_casts: List[dict]      = []  # casts/fizzles seen with no active fight yet
        # Optional persistence hook, set by server.py. Called with the fight that just ended,
        # from whatever thread ended it — which is always a thread already holding server.lock,
        # so an implementation may do nothing but enqueue. Kept as a plain attribute so this
        # module never learns that a database exists.
        self.on_end = None

    def _end(self, ts: float):
        if self.active:
            done = self.active
            done.is_active = False
            done.end_time  = ts
            self.completed.append(done)
            # MAX_HISTORY still bounds RAM, unchanged. Persistence relaxes what is RETAINED,
            # never what is held in memory or pushed — the evicted fights live in SQLite and
            # /api/fight/{id} falls through to it.
            if len(self.completed) > MAX_HISTORY:
                self.completed = self.completed[-MAX_HISTORY:]
            self.active = None
            if self.on_end is not None:
                self.on_end(done)

    def _seed_casts(self, fight: 'Fight', ts: float):
        fight.casts.extend(c for c in self.recent_casts if ts - c['ts'] <= PRECAST_WINDOW)
        self.recent_casts = []

    def _get_or_create(self, mob_name: str, ts: float) -> Fight:
        mob_name = mob_name.lower()
        if self.active:
            if ts - self.active.last_activity > FIGHT_TIMEOUT:
                self._end(ts)
            else:
                self.active.mobs_involved.add(mob_name)
                self.active.last_activity = ts
                return self.active
        self.active = Fight(mob_name, ts)
        self._seed_casts(self.active, ts)
        return self.active

    def _touch(self, source: str, ts: float) -> Fight:
        """Get/extend the active fight for an incoming attack from `source`."""
        source = source.lower()
        if not self.active:
            self.active = Fight(source, ts)
            self._seed_casts(self.active, ts)
        else:
            self.active.last_activity = ts
            self.active.mobs_involved.add(source)
        return self.active

    def process(self, event: dict):
        ts    = event['ts']
        etype = event['type']

        # passive timeout check
        if self.active and ts - self.active.last_activity > FIGHT_TIMEOUT:
            self._end(ts)

        if etype == 'damage':
            fight = self._get_or_create(event['target'], ts)
            fight.stats.add_damage(event['attacker'], event['amount'],
                                   event['dmg_type'], event.get('spell'))
            fight.stats.offense.add_damage(
                event['attacker'], event.get('verb'), event['amount'], event['dmg_type'],
                event.get('target'), ts, event)
            fight.hits.append({'ts': ts, 'dir': 'out', 'actor': event['attacker'],
                               'tgt': event['target'], 'amt': event['amount'],
                               'dtype': event['dmg_type'], 'spell': event.get('spell'),
                               'verb': event.get('verb'), 'crit': event.get('is_crit', False),
                               'riposte': event.get('is_riposte', False)})
            if event['dmg_type'] == 'dot' and event.get('spell'):
                key = (event['spell'], event['target'].lower())
                fight._dot_start.setdefault(key, ts)

        elif etype == 'miss':
            fight = self._get_or_create(event['target'], ts)
            fight.stats.offense.add_miss(event['attacker'], event.get('verb'), event['outcome'])

        elif etype == 'damage_taken':
            fight = self._touch(event['source'], ts)
            victim = event.get('victim', 'player')
            fight.stats.add_tanking(event['source'].lower(), event['amount'],
                                    event['dmg_type'], event.get('spell'), victim)
            fight.hits.append({'ts': ts, 'dir': 'in', 'actor': event['source'].lower(),
                               'tgt': victim, 'amt': event['amount'],
                               'dtype': event['dmg_type'], 'spell': event.get('spell'),
                               'verb': event.get('verb'), 'crit': event.get('is_crit', False),
                               'riposte': event.get('is_riposte', False)})

        elif etype == 'miss_taken':
            self._touch(event['source'], ts)
            # "…but YOU riposte!" — the trigger that produces a (Riposte)-tagged swing
            if event['outcome'] == 'riposte' and self.active:
                self.active.stats.offense.add_riposte_trigger('player')

        elif etype in ('cast', 'fizzle'):
            entry = {'ts': ts, 'spell': event.get('spell', 'Unknown'),
                      'type': 'fizzle' if etype == 'fizzle' else 'cast',
                      'caster': event.get('caster', 'player'), 'side': event.get('side', 'ally')}
            side = event.get('side', 'ally')
            if self.active:
                if side == 'ally':
                    # only our own casting keeps a fight alive; ambient NPC casting used to
                    # defer the timeout indefinitely and inflate every fight's duration
                    self.active.last_activity = ts
                    self.active.casts.append(entry)
                elif str(entry['caster']).lower() in self.active.mobs_involved:
                    self.active.casts.append(entry)
            elif side == 'ally':
                self.recent_casts.append(entry)
                self.recent_casts = [c for c in self.recent_casts if ts - c['ts'] <= PRECAST_WINDOW]

        elif etype == 'debuff_end':
            if self.active:
                key = (event['spell'], event['target'].lower())
                start = self.active._dot_start.pop(key, None)
                if start is not None:
                    self.active.debuffs.append({'spell': event['spell'], 'target': event['target'],
                                                'start': start, 'end': ts})

        elif etype == 'heal':
            if self.active:
                self.active.last_activity = ts
                healer = event['healer']
                if healer.lower() in ('you', 'yourself'):
                    healer = 'player'
                self.active.stats.add_healing(healer, event['amount'],
                                              event.get('spell'), event.get('is_hot', False))

        elif etype == 'kill':
            if self.active:
                self.active.last_activity = ts
                self.active.mobs_slain.add(event['target'].lower())
                if self.active.mobs_involved <= self.active.mobs_slain:
                    self._end(ts)

        elif etype == 'player_death':
            self._end(ts)

    def add_loot(self, item: str, source: str, ts: float):
        entry = {'ts': ts, 'item': item, 'source': source}
        if self.active:
            self.active.loot.append(entry)
        elif self.completed and ts - self.completed[-1].end_time <= LOOT_GRACE:
            self.completed[-1].loot.append(entry)

    def add_xp(self, pct: float, ts: float):
        if self.active:
            self.active.xp += pct
        elif self.completed and ts - self.completed[-1].end_time <= LOOT_GRACE:
            self.completed[-1].xp += pct

    def add_coin(self, copper: int, ts: float):
        if self.active:
            self.active.coin += copper
        elif self.completed and ts - self.completed[-1].end_time <= LOOT_GRACE:
            self.completed[-1].coin += copper

    def tick(self):
        if self.active and time.time() - self.active.last_activity > FIGHT_TIMEOUT:
            self._end(self.active.last_activity + FIGHT_TIMEOUT)

    def find(self, fight_id: int) -> Optional[Fight]:
        """Look a fight up by id, active or completed (backs /api/fight/{id})."""
        if self.active and self.active.id == fight_id:
            return self.active
        return next((f for f in self.completed if f.id == fight_id), None)

    def state(self) -> dict:
        return {
            'active_fight': self.active.to_dict() if self.active else None,
            'fights':       [f.to_dict(include_offense=False, detail=False)
                             for f in reversed(self.completed[-50:])],
        }

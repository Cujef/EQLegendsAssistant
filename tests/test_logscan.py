"""Log-scan suites: ext_parser AA events, highlight aggregation, the pipeline's
chunked scan/resume/truncation behavior, and fight persistence."""
import json
import os
import tempfile
import time


def run(check):
    _ext(check)
    _agg(check)
    _agg_events(check)
    _pipeline(check)


# ── ext_parser ────────────────────────────────────────────────────────────────
def _ext(check):
    from app.logscan.ext_parser import parse

    CASES = [
        # real AA lines from a live EQ Legends log (all three shapes + variants)
        ('[Fri Jul 31 19:20:12 2026] You have gained an ability point!  '
         'You now have 12 ability points.',
         {'type': 'aa_gain', 'points': 1, 'balance_after': 12}),
        ('[Sat Aug 01 21:17:46 2026] You have gained an ability point!  '
         'You now have 1 ability point.',
         {'type': 'aa_gain', 'points': 1, 'balance_after': 1}),
        ('[Fri Jul 31 20:44:40 2026] You have gained the ability "Ambidexterity" '
         'at a cost of 9 ability points.',
         {'type': 'aa_spend', 'ability': 'Ambidexterity', 'points': 9}),
        ('[Tue Aug 04 23:08:47 2026] You have gained the ability "Unbound Clarity" '
         'at a cost of 0 ability points.',
         {'type': 'aa_spend', 'ability': 'Unbound Clarity', 'points': 0}),
        ('[Sat Aug 01 16:11:24 2026] You have improved Combat Fury 2 '
         'at a cost of 2 ability points.',
         {'type': 'aa_spend', 'ability': 'Combat Fury 2', 'points': 2}),
        ('[Mon Aug 03 21:23:09 2026] You have improved Mnemonic Retention 2 '
         'at a cost of 1 ability point.',
         {'type': 'aa_spend', 'ability': 'Mnemonic Retention 2', 'points': 1}),
        ('[Mon Aug 03 21:44:20 2026] You have gained the ability '
         '"Symphonic Aura: Disabled" at a cost of 0 ability points.',
         {'type': 'aa_spend', 'ability': 'Symphonic Aura: Disabled', 'points': 0}),
    ]
    for line, expect in CASES:
        ev = parse(line)
        ok = ev is not None and all(ev.get(k) == v for k, v in expect.items())
        check(f'ext: {line[27:75]!r}', ok, f'got {ev}')

    # fallthrough sanity: vendored events still come through unchanged
    ev = parse('[Fri Jul 31 18:38:02 2026] You pierce a tormented dead '
               'for 11 points of damage.')
    check('ext: melee falls through to vendored parse',
          ev is not None and ev['type'] == 'damage' and ev['amount'] == 11, ev)
    check('ext: garbage -> None', parse('not a log line') is None)

    # depot moves + combine errors (app-specific); the vendored tradeskill/faction
    # lines must still come through the same entry point unchanged
    DEPOT = [
        ('[Sat Aug 01 21:00:00 2026] You have deposited 20 Kiola Nut to your personal depot.',
         {'type': 'depot_deposit', 'qty': 20, 'item': 'Kiola Nut'}),
        ('[Sat Aug 01 21:00:01 2026] You have taken 5 Bone Chips from your personal depot.',
         {'type': 'depot_withdraw', 'qty': 5, 'item': 'Bone Chips'}),
        ('[Sat Aug 01 21:00:02 2026] Consumed 2 x Water Flask (leaving 7) from your personal depot.',
         {'type': 'depot_consume', 'qty': 2, 'item': 'Water Flask', 'left': 7}),
        ("[Sat Aug 01 21:00:03 2026] Sorry, but you don't have everything you need for this "
         "recipe in your general inventory.",
         {'type': 'craft_error', 'reason': 'missing_materials'}),
        ('[Sat Aug 01 21:00:04 2026] The result of this combine would produce an unusable item.',
         {'type': 'craft_error', 'reason': 'unusable_result'}),
        ('[Sat Aug 01 21:00:05 2026] You cannot combine these items in this container type!',
         {'type': 'craft_error', 'reason': 'wrong_container'}),
        ('[Sat Aug 01 21:00:06 2026] You have fashioned the items together to create something new: Tumpy Tonic.',
         {'type': 'craft', 'item': 'Tumpy Tonic', 'ok': True}),
        ('[Sat Aug 01 21:00:07 2026] Your faction standing with Frogloks of Guk has been adjusted by -5.',
         {'type': 'faction', 'faction': 'Frogloks of Guk', 'delta': -5}),
        # item merges: no trailing period; +N gear and rank results both occur
        ('[Fri Jul 31 22:02:32 2026] You have successfully merged two items together to create a new item: Platinum Ring +3',
         {'type': 'upgrade', 'item': 'Platinum Ring +3', 'base': 'Platinum Ring', 'tier': 3}),
        ('[Sat Aug 01 21:08:05 2026] You have successfully merged two items together to create a new item: Sprouting Heal II',
         {'type': 'upgrade', 'item': 'Sprouting Heal II', 'base': 'Sprouting Heal II', 'tier': None}),
        # auto-sold / auto-merged loot: the game's most common loot shape
        ("[Fri Jul 31 18:38:19 2026] You looted 2 Zombie Skin from a tormented dead's corpse and sold it for 1 gold, 3 silver and 6 copper.",
         {'type': 'loot', 'item': 'Zombie Skin', 'source': 'a tormented dead', 'qty': 2, 'sold_copper': 136}),
        ("[Fri Jul 31 18:39:44 2026] You looted a Rusty Broad Sword +1 from a tormented dead's corpse and sold it for free.",
         {'type': 'loot', 'item': 'Rusty Broad Sword +1', 'source': 'a tormented dead', 'qty': 1, 'sold_copper': 0}),
        ("[Fri Jul 31 18:40:00 2026] You looted a Throwing Boulder from a hill giant's corpse to create a Throwing Boulder +2",
         {'type': 'loot', 'item': 'Throwing Boulder', 'source': 'a hill giant', 'qty': 1, 'merged_into': 'Throwing Boulder +2'}),
        ("[Fri Jul 31 18:40:01 2026] You looted 3 Bone Chips from a skeleton's corpse and stored it in your tradeskill depot.",
         {'type': 'loot', 'item': 'Bone Chips', 'source': 'a skeleton', 'qty': 3}),   # vendored branch, untouched
    ]
    for line, expect in DEPOT:
        ev = parse(line)
        ok = ev is not None and all(ev.get(k) == v for k, v in expect.items())
        check(f'ext: {line[27:80]!r}', ok, f'got {ev}')
    # chat about combining must not become a craft_error
    ev = parse("[Sat Aug 01 21:00:08 2026] You tell your party, 'lets combine forces'")
    check('ext: chat mentioning combine is not an error event',
          ev is None or ev.get('type') != 'craft_error', ev)
    ev = parse('[Sat Aug 01 21:00:09 2026] Request to merge items canceled, both items remain unmodified.')
    check('ext: cancelled merge is not an upgrade', ev is None or ev.get('type') != 'upgrade', ev)


# ── Aggregator ────────────────────────────────────────────────────────────────
def _agg(check):
    from app import db
    from app.logscan.highlights import Aggregator

    db.init()
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO characters(name, server, created_at) "
                  "VALUES('AggTest','test',0)")
    cid = db.query_one("SELECT id FROM characters WHERE name='AggTest'")['id']

    t0 = 1_800_000_000.0
    agg = Aggregator(player_name='AggTest')
    batch1 = [
        {'type': 'skill', 'ts': t0 + 1, 'skill': 'Meditate', 'level': 10},
        {'type': 'level_up', 'ts': t0 + 2, 'level': 5},
        {'type': 'aa_gain', 'ts': t0 + 3, 'points': 1, 'balance_after': 2},
        {'type': 'aa_spend', 'ts': t0 + 4, 'ability': 'Combat Fury', 'points': 1},
        {'type': 'kill', 'ts': t0 + 5, 'target': 'a rat'},
        {'type': 'player_death', 'ts': t0 + 6, 'killer': 'a bear'},
        {'type': 'damage', 'ts': t0 + 7, 'attacker': 'player', 'target': 'a rat',
         'amount': 50, 'dmg_type': 'melee', 'spell': None, 'verb': 'slash',
         'is_crit': True},
        {'type': 'damage', 'ts': t0 + 8, 'attacker': 'player', 'target': 'a rat',
         'amount': 40, 'dmg_type': 'melee', 'spell': None, 'verb': 'slash',
         'is_crit': False},
        {'type': 'damage', 'ts': t0 + 9, 'attacker': 'player', 'target': 'a rat',
         'amount': 100, 'dmg_type': 'spell', 'spell': 'Ignite', 'verb': 'spell'},
        {'type': 'damage', 'ts': t0 + 10, 'attacker': 'player', 'target': 'a rat',
         'amount': 20, 'dmg_type': 'dot', 'spell': 'Swarm', 'verb': 'dot'},
        {'type': 'damage_taken', 'ts': t0 + 11, 'source': 'a bear',
         'victim': 'player', 'amount': 60, 'dmg_type': 'melee', 'verb': 'claw'},
        {'type': 'heal', 'ts': t0 + 12, 'healer': 'Cleric', 'target': 'you',
         'amount': 75, 'spell': 'Light', 'is_hot': False},
        {'type': 'loot', 'ts': t0 + 13, 'item': 'Rusty Dagger', 'source': 'a rat'},
        {'type': 'coin', 'ts': t0 + 14, 'copper': 123, 'source': 'a rat'},
        {'type': 'cast', 'ts': t0 + 15, 'spell': 'Ignite', 'caster': 'player'},
        {'type': 'fizzle', 'ts': t0 + 16, 'spell': 'Ignite', 'caster': 'player'},
    ]
    for ev in batch1:
        agg.feed(ev)
    agg.add_lines(len(batch1))
    with db.tx() as c:
        agg.flush(c, cid)

    def hl(key):
        return db.query_one(
            'SELECT * FROM highlights WHERE character_id=? AND key=?', (cid, key))

    check('agg: skill row', db.query_one(
        'SELECT * FROM skill_levels WHERE character_id=? AND skill=?',
        (cid, 'Meditate')) is not None)
    check('agg: level row', db.query_one(
        'SELECT * FROM level_history WHERE character_id=? AND level=5', (cid,))
        is not None)
    aa_rows = db.query('SELECT * FROM aa_ledger WHERE character_id=?', (cid,))
    check('agg: aa rows', len(aa_rows) == 2, aa_rows)
    gain = next(r for r in aa_rows if r['kind'] == 'gain')
    check('agg: aa gain ability_name empty-string not NULL',
          gain['ability_name'] == '' and gain['balance_after'] == 2, gain)
    check('agg: death row', db.query_one(
        'SELECT * FROM deaths WHERE character_id=?', (cid,))['killer'] == 'a bear')
    check('agg: max_melee_hit', hl('max_melee_hit')['value_num'] == 50)
    ctx = json.loads(hl('max_melee_hit')['context_json'])
    check('agg: max context', ctx['target'] == 'a rat' and ctx['verb'] == 'slash', ctx)
    check('agg: max_melee_crit', hl('max_melee_crit')['value_num'] == 50)
    check('agg: max_spell_hit', hl('max_spell_hit')['value_num'] == 100)
    check('agg: max_dot_tick', hl('max_dot_tick')['value_num'] == 20)
    check('agg: biggest_hit_taken', hl('biggest_hit_taken')['value_num'] == 60)
    check('agg: max_heal_received', hl('max_heal_received')['value_num'] == 75)
    for key, want in (('total_kills', 1), ('total_deaths', 1), ('total_crits', 1),
                      ('total_fizzles', 1), ('total_casts', 1), ('total_loot', 1),
                      ('total_coin_copper', 123), ('lines_parsed', 16),
                      ('total_sessions', 1)):
        row = hl(key)
        check(f'agg: {key}', row is not None and row['value_num'] == want,
              row and row['value_num'])
    check('agg: playtime 15s', hl('playtime_seconds')['value_num'] == 15)
    check('agg: log_first_ts', hl('log_first_ts')['value_num'] == t0 + 1)
    check('agg: log_last_ts', hl('log_last_ts')['value_num'] == t0 + 16)

    # batch 2: counters add, maxima swap only when larger, session break counts
    batch2 = [
        {'type': 'damage', 'ts': t0 + 4000, 'attacker': 'player', 'target': 'a gnoll',
         'amount': 45, 'dmg_type': 'melee', 'spell': None, 'verb': 'slash'},
        {'type': 'damage', 'ts': t0 + 4001, 'attacker': 'player', 'target': 'a gnoll',
         'amount': 70, 'dmg_type': 'melee', 'spell': None, 'verb': 'crush'},
        {'type': 'kill', 'ts': t0 + 4002, 'target': 'a gnoll'},
        {'type': 'coin', 'ts': t0 + 4003, 'copper': 7, 'source': 'a gnoll'},
        # dup skill event: INSERT OR IGNORE keeps the earliest row
        {'type': 'skill', 'ts': t0 + 4004, 'skill': 'Meditate', 'level': 10},
    ]
    for ev in batch2:
        agg.feed(ev)
    with db.tx() as c:
        agg.flush(c, cid)
    check('agg: counters add', hl('total_kills')['value_num'] == 2
          and hl('total_coin_copper')['value_num'] == 130)
    check('agg: max swaps up', hl('max_melee_hit')['value_num'] == 70)
    ctx = json.loads(hl('max_melee_hit')['context_json'])
    check('agg: swapped context', ctx['verb'] == 'crush', ctx)
    check('agg: max keeps larger', hl('max_spell_hit')['value_num'] == 100)
    check('agg: session break counted', hl('total_sessions')['value_num'] == 2)
    check('agg: playtime skips the gap',
          hl('playtime_seconds')['value_num'] == 15 + 4, hl('playtime_seconds'))
    check('agg: dup skill ignored', len(db.query(
        'SELECT * FROM skill_levels WHERE character_id=?', (cid,))) == 1)
    check('agg: log_first_ts unchanged', hl('log_first_ts')['value_num'] == t0 + 1)


# ── Aggregator: tradeskill / depot / faction events ───────────────────────────
def _agg_events(check):
    from app import db
    from app.logscan.highlights import Aggregator, CRAFT_LINK_WINDOW

    db.init()
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO characters(name, server, created_at) "
                  "VALUES('AggEv','test',0)")
    cid = db.query_one("SELECT id FROM characters WHERE name='AggEv'")['id']
    t0 = 1_800_200_000.0

    def crafts():
        return db.query('SELECT * FROM craft_events WHERE character_id=? ORDER BY ts', (cid,))

    def caps():
        return {r['item']: r for r in db.query(
            'SELECT * FROM craft_caps WHERE character_id=?', (cid,))}

    def votes():
        return {(r['item'], r['skill']): r['votes'] for r in db.query(
            'SELECT * FROM craft_recipe_skill WHERE character_id=?', (cid,))}

    agg = Aggregator(player_name='AggEv')
    # a cap notice PRECEDES the combine it refers to (same second in the real log)
    agg.feed({'type': 'craft', 'ts': t0, 'item': 'Fish Rolls', 'ok': True})
    agg.feed({'type': 'craft_capped', 'ts': t0 + 3})
    agg.feed({'type': 'craft', 'ts': t0 + 3, 'item': 'Tumpy Tonic', 'ok': True})
    check('aggev: cap flag set on the FOLLOWING craft', agg.last_craft_capped is True)
    # skill-up after the combine (same second) -> vote; before the next one -> vote
    agg.feed({'type': 'skill', 'ts': t0 + 3, 'skill': 'Brewing', 'level': 12})
    agg.feed({'type': 'skill', 'ts': t0 + 6, 'skill': 'Baking', 'level': 40})
    agg.feed({'type': 'craft', 'ts': t0 + 6, 'item': 'Bat Wing Crunchies', 'ok': False})
    # a skill-up 3 s from any combine is nobody's vote
    agg.feed({'type': 'skill', 'ts': t0 + 9 + CRAFT_LINK_WINDOW, 'skill': 'Pottery', 'level': 5})
    agg.feed({'type': 'craft', 'ts': t0 + 20, 'item': 'Clay Bowl', 'ok': True})
    # a combat skill next to a combine is not a tradeskill vote
    agg.feed({'type': 'skill', 'ts': t0 + 20, 'skill': 'Dodge', 'level': 100})
    with db.tx() as c:
        agg.flush(c, cid)

    rows = crafts()
    check('aggev: four craft rows', len(rows) == 4, len(rows))
    by = {r['item']: r for r in rows}
    check('aggev: cap lands on Tumpy Tonic, not on the previous recipe',
          by['Tumpy Tonic']['capped'] == 1 and by['Fish Rolls']['capped'] == 0, by)
    check('aggev: ok/fail recorded', by['Tumpy Tonic']['ok'] == 1
          and by['Bat Wing Crunchies']['ok'] == 0)
    check('aggev: item_norm stored', by['Fish Rolls']['item_norm'] == 'fish rolls')
    check('aggev: craft_caps row for the capped recipe only',
          set(caps()) == {'Tumpy Tonic'} and caps()['Tumpy Tonic']['count'] == 1, caps())
    v = votes()
    check('aggev: skill-up AFTER the combine votes', v.get(('Tumpy Tonic', 'Brewing')) == 1, v)
    check('aggev: skill-up BEFORE the combine votes', v.get(('Bat Wing Crunchies', 'Baking')) == 1, v)
    check('aggev: distant skill-up does not vote', not any(k[1] == 'Pottery' for k in v), v)
    check('aggev: combat skill does not vote', not any(k[1] == 'Dodge' for k in v), v)
    check('aggev: skill_levels still written for tradeskill skill-ups', db.query_one(
        "SELECT * FROM skill_levels WHERE character_id=? AND skill='Brewing'", (cid,)) is not None)
    hl = db.query_one("SELECT value_num FROM highlights WHERE character_id=? AND key='total_crafts'",
                      (cid,))
    check('aggev: total_crafts counter', hl and hl['value_num'] == 4, hl)

    # correlation state survives a flush between the cap notice and its combine
    agg.feed({'type': 'craft_capped', 'ts': t0 + 30})
    with db.tx() as c:
        agg.flush(c, cid)
    agg.feed({'type': 'craft', 'ts': t0 + 30, 'item': 'Tumpy Tonic', 'ok': True})
    with db.tx() as c:
        agg.flush(c, cid)
    check('aggev: cap straddling a flush still attaches',
          [r['capped'] for r in crafts() if r['item'] == 'Tumpy Tonic'] == [1, 1]
          and caps()['Tumpy Tonic']['count'] == 2, caps())

    # faction: two byte-identical same-second hits are two rows; caps upsert
    agg.feed({'type': 'faction', 'ts': t0 + 40, 'faction': 'Frogloks of Guk', 'delta': -5})
    agg.feed({'type': 'faction', 'ts': t0 + 40, 'faction': 'Frogloks of Guk', 'delta': -5})
    agg.feed({'type': 'faction_capped', 'ts': t0 + 41, 'faction': 'Knights of Truth',
              'direction': 'better'})
    agg.feed({'type': 'faction_capped', 'ts': t0 + 42, 'faction': 'Knights of Truth',
              'direction': 'better'})
    # depot: the three kinds
    agg.feed({'type': 'depot_consume', 'ts': t0 + 50, 'qty': 2, 'item': 'Water Flask', 'left': 7})
    agg.feed({'type': 'depot_deposit', 'ts': t0 + 51, 'qty': 20, 'item': 'Water Flask'})
    agg.feed({'type': 'depot_withdraw', 'ts': t0 + 52, 'qty': 5, 'item': 'Water Flask'})
    agg.feed({'type': 'craft_error', 'ts': t0 + 53, 'reason': 'missing_materials'})
    agg.feed({'type': 'upgrade', 'ts': t0 + 60, 'item': 'Platinum Ring +3', 'base': 'Platinum Ring',
              'tier': 3})
    agg.feed({'type': 'upgrade', 'ts': t0 + 61, 'item': 'Sprouting Heal II',
              'base': 'Sprouting Heal II', 'tier': None})
    with db.tx() as c:
        agg.flush(c, cid)
    up = db.query('SELECT item, item_norm, tier FROM upgrade_events WHERE character_id=? ORDER BY ts',
                  (cid,))
    check('aggev: upgrade rows with base-name key and optional tier',
          [(r['item'], r['item_norm'], r['tier']) for r in up]
          == [('Platinum Ring +3', 'platinum ring', 3), ('Sprouting Heal II', 'sprouting heal ii', None)],
          up)
    hl = db.query_one("SELECT value_num FROM highlights WHERE character_id=? AND key='total_upgrades'",
                      (cid,))
    check('aggev: total_upgrades counter', hl and hl['value_num'] == 2, hl)
    fe = db.query('SELECT * FROM faction_events WHERE character_id=?', (cid,))
    check('aggev: identical same-second faction hits both kept', len(fe) == 2
          and sum(r['delta'] for r in fe) == -10, fe)
    fc = db.query_one('SELECT * FROM faction_caps WHERE character_id=?', (cid,))
    check('aggev: faction cap upserted with count', fc and fc['faction'] == 'Knights of Truth'
          and fc['direction'] == 'better' and fc['count'] == 2 and fc['last_ts'] == t0 + 42, fc)
    de = db.query('SELECT kind, qty, left_qty FROM depot_events WHERE character_id=? ORDER BY ts',
                  (cid,))
    check('aggev: depot rows by kind',
          [(r['kind'], r['qty'], r['left_qty']) for r in de]
          == [('consume', 2, 7), ('deposit', 20, None), ('withdraw', 5, None)], de)
    hl = db.query_one("SELECT value_num FROM highlights WHERE character_id=? "
                      "AND key='total_craft_errors'", (cid,))
    check('aggev: craft error counter', hl and hl['value_num'] == 1, hl)

    # events-only mode (the backfill): events land, nothing additive is touched
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO characters(name, server, created_at) "
                  "VALUES('AggBf','test',0)")
    cid2 = db.query_one("SELECT id FROM characters WHERE name='AggBf'")['id']
    bf = Aggregator(events_only=True)
    bf.feed({'type': 'kill', 'ts': t0, 'target': 'a rat'})
    bf.feed({'type': 'skill', 'ts': t0 + 1, 'skill': 'Baking', 'level': 41})
    bf.feed({'type': 'craft', 'ts': t0 + 1, 'item': 'Fish Rolls', 'ok': True})
    bf.feed({'type': 'faction', 'ts': t0 + 2, 'faction': 'X', 'delta': 1})
    bf.add_lines(3)
    with db.tx() as c:
        bf.flush(c, cid2)
    # a narrowed events-only pass (a later backfill revision) ignores the rest
    nar = Aggregator(events_only=True, only_types={'upgrade'})
    nar.feed({'type': 'craft', 'ts': t0 + 3, 'item': 'Fish Rolls', 'ok': True})
    nar.feed({'type': 'upgrade', 'ts': t0 + 4, 'item': 'Ring +1', 'base': 'Ring', 'tier': 1})
    with db.tx() as c:
        nar.flush(c, cid2)
    check('aggev: only_types narrows an events-only pass',
          len(db.query('SELECT * FROM craft_events WHERE character_id=?', (cid2,))) == 1
          and len(db.query('SELECT * FROM upgrade_events WHERE character_id=?', (cid2,))) == 1)

    # ── zone clock + loot stamping (v1.2) ──
    from app.logscan.highlights import SESSION_GAP, zone_base
    from app.logscan.highlights import is_pseudo_zone
    check('zone: "an area where…" lines are flags, not zones',
          is_pseudo_zone('an area where levitation effects do not function')
          and is_pseudo_zone('an area where Bind Affinity is allowed') and not is_pseudo_zone('Najena'))
    check('zone: instance suffixes stripped',
          zone_base('Najena 2 (Adaptive)') == 'Najena'
          and zone_base('The Plane of Fear - Group 1 (Awakened)') == 'The Plane of Fear'
          and zone_base('The Permafrost Caverns - Group 3 (Fused)') == 'The Permafrost Caverns'
          and zone_base('Paineel 4 (Refined)') == 'Paineel'
          and zone_base('The Estate of Unrest 1 (Awakened)') == 'The Estate of Unrest'
          and zone_base('Northern Felwithe') == 'Northern Felwithe')
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO characters(name, server, created_at) VALUES('AggZone','test',0)")
    cz = db.query_one("SELECT id FROM characters WHERE name='AggZone'")['id']
    za = Aggregator(player_name='AggZone')
    t1 = 1_800_300_000.0
    za.feed({'type': 'loot', 'ts': t1, 'item': 'Bone Chips', 'source': 'a skeleton'})       # before any zone
    za.feed({'type': 'zone', 'ts': t1 + 10, 'zone': 'Najena 2 (Adaptive)'})
    za.feed({'type': 'zone', 'ts': t1 + 40, 'zone': 'an area where levitation effects do not function'})  # ignored
    za.feed({'type': 'kill', 'ts': t1 + 70, 'target': 'a gnoll'})                          # +60 s
    za.feed({'type': 'xp', 'ts': t1 + 70, 'pct': 0.5})                                     # +0 (same second)
    za.feed({'type': 'loot', 'ts': t1 + 100, 'item': 'Rusty Dagger', 'source': 'a gnoll', 'qty': 2})  # +30
    za.feed({'type': 'damage', 'ts': t1 + 5000, 'attacker': 'player', 'target': 'x', 'amount': 1,
             'dmg_type': 'melee', 'spell': None, 'verb': 'hit'})                            # not a clock event
    za.feed({'type': 'kill', 'ts': t1 + 100 + SESSION_GAP + 1, 'target': 'a rat'})         # gap > 30 min: cut
    za.feed({'type': 'zone', 'ts': t1 + 100 + SESSION_GAP + 61, 'zone': 'Najena'})          # +60 to Najena (old zone)
    za.feed({'type': 'zone', 'ts': t1 + 100 + SESSION_GAP + 121, 'zone': 'Paineel 4 (Refined)'})  # +60 to Najena
    za.feed({'type': 'xp', 'ts': t1 + 100 + SESSION_GAP + 151, 'pct': 1.25})                # +30 to Paineel
    with db.tx() as c:
        za.flush(c, cz)
    zs = {r['zone']: r for r in db.query('SELECT * FROM zone_stats WHERE character_id=?', (cz,))}
    check('zone: seconds = gaps <= 30 min between clock events, old zone keeps the time until leaving',
          zs['Najena']['seconds'] == 60 + 30 + 60 + 60 and zs['Paineel']['seconds'] == 30, zs)
    check('zone: kills/xp/loot attributed to the current zone (the >30 min kill still counts)',
          zs['Najena']['kills'] == 2 and zs['Najena']['xp_pct'] == 0.5 and zs['Najena']['loot'] == 2
          and zs['Najena']['visits'] == 2 and zs['Paineel']['xp_pct'] == 1.25 and zs['Paineel']['visits'] == 1, zs)
    ze = db.query('SELECT zone, zone_base FROM zone_events WHERE character_id=? ORDER BY ts', (cz,))
    check('zone: visits recorded raw + base', [(r['zone'], r['zone_base']) for r in ze]
          == [('Najena 2 (Adaptive)', 'Najena'), ('Najena', 'Najena'), ('Paineel 4 (Refined)', 'Paineel')], ze)
    le = db.query('SELECT item, source, qty, zone FROM loot_events WHERE character_id=? ORDER BY ts', (cz,))
    check('zone: loot rows stamped with the zone (NULL before the first zone line)',
          [(r['item'], r['source'], r['qty'], r['zone']) for r in le]
          == [('Bone Chips', 'a skeleton', 1, None), ('Rusty Dagger', 'a gnoll', 2, 'Najena')], le)
    clock = db.query_one("SELECT value_num FROM highlights WHERE character_id=? AND key='zone_clock_ts'", (cz,))
    check('zone: zone_clock_ts highlight = last clock event (not the damage line)',
          clock and clock['value_num'] == t1 + 100 + SESSION_GAP + 151, clock)

    # seeding: a fresh Aggregator resumes from the committed zone + clock
    zb = Aggregator(player_name='AggZone')
    zb.seed_zone('Paineel 4 (Refined)', t1 + 100 + SESSION_GAP + 151)
    zb.feed({'type': 'kill', 'ts': t1 + 100 + SESSION_GAP + 181, 'target': 'a rat'})       # +30
    with db.tx() as c:
        zb.flush(c, cz)
    row = db.query_one('SELECT * FROM zone_stats WHERE character_id=? AND zone=?', (cz, 'Paineel'))
    check('zone: seeded clock continues in the seeded zone', row['seconds'] == 60 and row['kills'] == 1, dict(row))

    # events-only (backfill rev 3): the same four types, nothing additive besides them
    zc = Aggregator(events_only=True, only_types={'zone', 'xp', 'kill', 'loot'})
    zc.feed({'type': 'zone', 'ts': t1, 'zone': 'Befallen'})
    zc.feed({'type': 'kill', 'ts': t1 + 10, 'target': 'x'})
    zc.feed({'type': 'craft', 'ts': t1 + 11, 'item': 'Fish Rolls', 'ok': True})           # not in only_types
    with db.tx() as c:
        zc.flush(c, cid2)
    check('zone: events-only writes zone rows only',
          db.query_one('SELECT kills, seconds FROM zone_stats WHERE character_id=? AND zone=?',
                       (cid2, 'Befallen')) == {'kills': 1, 'seconds': 10}
          and len(db.query('SELECT * FROM craft_events WHERE character_id=?', (cid2,))) == 1
          and db.query_one("SELECT 1 FROM highlights WHERE character_id=? AND key='total_kills'", (cid2,)) is None)
    check('aggev: events-only writes craft + faction rows',
          len(db.query('SELECT * FROM craft_events WHERE character_id=?', (cid2,))) == 1
          and len(db.query('SELECT * FROM faction_events WHERE character_id=?', (cid2,))) == 1)
    check('aggev: events-only still votes recipe->skill',
          db.query_one('SELECT votes FROM craft_recipe_skill WHERE character_id=? '
                       "AND item='Fish Rolls' AND skill='Baking'", (cid2,)) is not None)
    check('aggev: events-only writes NO skill_levels / kills / lines / sessions',
          db.query_one('SELECT 1 FROM skill_levels WHERE character_id=?', (cid2,)) is None
          and not any(r['key'] in ('total_kills', 'lines_parsed', 'total_sessions',
                                   'playtime_seconds', 'log_first_ts')
                      for r in db.query('SELECT key FROM highlights WHERE character_id=?',
                                        (cid2,))),
          db.query('SELECT key FROM highlights WHERE character_id=?', (cid2,)))


# ── pipeline: chunked scan, resume, truncation, fight persistence ─────────────
def _mklines(t0, specs):
    """specs: list of text-after-timestamp strings; 1s apart, real log format."""
    out = []
    for i, text in enumerate(specs):
        stamp = time.strftime('%a %b %d %H:%M:%S %Y', time.localtime(t0 + i))
        out.append(f'[{stamp}] {text}')
    return ''.join(l + '\n' for l in out)


def _pipeline(check):
    from app import db
    from app.logscan.tailer import Pipeline
    from app.logscan import importer

    db.init()
    tmp = tempfile.mkdtemp(prefix='eqa-logscan-')
    log_path = os.path.join(tmp, 'eqlog_PipeTest_test.txt')

    with db.tx() as c:
        c.execute('UPDATE characters SET is_active=0')
        c.execute("INSERT OR IGNORE INTO characters"
                  "(name, server, log_path, is_active, created_at) "
                  "VALUES('PipeTest','test',?,1,0)", (log_path,))
        c.execute("UPDATE characters SET is_active=1, log_path=? "
                  "WHERE name='PipeTest'", (log_path,))
    char = db.query_one("SELECT * FROM characters WHERE name='PipeTest'")
    cid = char['id']

    t0 = 1_800_100_000
    body = ['Welcome to EverQuest Legends!',
            'You have entered Silly Meadow.',
            'Auto attack is on.']
    # a fight that ends cleanly on the kill (all involved mobs slain)
    for _ in range(8):
        body.append('You slash a training dummy for 15 points of damage.')
    body += [
        'You slash a training dummy for 30 points of damage. (Critical)',
        'A training dummy bashes YOU for 12 points of damage.',
        'You have slain a training dummy!',
        'You gain experience! (0.51%)',
        '--You have looted a Rusty Dagger from a training dummy.--',
        '--You have looted 5 gold and 3 silver from a training dummy.--',
        'You have become better at Meditate! (5)',
        'You have gained a level! Welcome to level 6!',
        'You have gained an ability point!  You now have 3 ability points.',
        'You have gained the ability "Combat Fury" at a cost of 1 ability points.',
        'You have improved Combat Fury 2 at a cost of 2 ability points.',
        'Someone healed you for 50 hit points by Minor Healing.',
        'You have been slain by a rabid squirrel!',
        # v1.1 events: tradeskills (cap precedes its combine), depot, faction
        'You can no longer advance your skill from making this item.',
        'You have fashioned the items together to create something new: Tumpy Tonic.',
        'You have become better at Brewing! (12)',
        'You lacked the skills to fashion Fish Rolls.',
        'Consumed 2 x Water Flask (leaving 7) from your personal depot.',
        'You have deposited 20 Kiola Nut to your personal depot.',
        'Your faction standing with Frogloks of Guk has been adjusted by -5.',
        'Your faction standing with Frogloks of Guk has been adjusted by -5.',
        'Your faction standing with Knights of Truth could not possibly get any better.',
        'You have successfully merged two items together to create a new item: Platinum Ring +3',
        # v1.2: a second zone, party XP, depot loot with a quantity
        'You have entered Dusty Hollow.',
        'You gain party experience! (1.25%)',
        "You looted 2 Spider Silk from a spider's corpse and stored it in your tradeskill depot.",
        "You looted a Spider Leg from a spider's corpse and sold it for 2 silver and 5 copper.",
    ]
    n_events = len(body)              # index of the last zone-clock line + 1
    while len(body) < 50:
        body.append('You begin casting Minor Healing.')
    n1 = len(body)
    with open(log_path, 'w', encoding='utf-8', newline='') as f:
        f.write(_mklines(t0, body))
    size1 = os.path.getsize(log_path)

    pipe = Pipeline(dict(char))
    r = pipe.scan_to_eof()
    check('pipe: scan reaches EOF', r['status'] == 'eof' and r['offset'] == size1, r)
    src = db.query_one('SELECT * FROM log_source WHERE path=?', (log_path,))
    check('pipe: checkpoint == file size', src['byte_offset'] == size1, src)

    def hl(key):
        return db.query_one(
            'SELECT value_num FROM highlights WHERE character_id=? AND key=?',
            (cid, key))

    check('pipe: lines counted', hl('lines_parsed')['value_num'] == n1)
    check('pipe: kill counted', hl('total_kills')['value_num'] == 1)
    check('pipe: death row', db.query_one(
        'SELECT killer FROM deaths WHERE character_id=?',
        (cid,))['killer'] == 'a rabid squirrel')
    check('pipe: skill row', db.query_one(
        'SELECT * FROM skill_levels WHERE character_id=? AND skill=?',
        (cid, 'Meditate')) is not None)
    check('pipe: level row', db.query_one(
        'SELECT * FROM level_history WHERE character_id=? AND level=6',
        (cid,)) is not None)
    aa = db.query('SELECT * FROM aa_ledger WHERE character_id=? ORDER BY ts', (cid,))
    check('pipe: aa ledger 3 rows', len(aa) == 3, aa)
    check('pipe: aa balance', aa[0]['kind'] == 'gain'
          and aa[0]['balance_after'] == 3)
    check('pipe: coin loot', hl('total_coin_copper')['value_num'] == 530)
    check('pipe: max crit hit', hl('max_melee_hit')['value_num'] == 30)
    check('pipe: heal highlight', hl('max_heal_received')['value_num'] == 50)

    fights = db.query('SELECT * FROM fights WHERE character_id=?', (cid,))
    check('pipe: fight persisted', len(fights) == 1, len(fights))
    fd = json.loads(fights[0]['data'])
    check('pipe: fight data parses', fd['name'] == 'a training dummy'
          and fd['total_damage'] == 8 * 15 + 30, fd.get('total_damage'))
    check('pipe: fight summary cols', fights[0]['total_damage'] == 150
          and fights[0]['total_tanking'] == 12, dict(fights[0]))

    # duplicate on_end -> INSERT OR IGNORE dedupes on (character_id, start, name)
    pipe._on_fight_end(pipe.tracker.completed[0])
    pipe._flush()
    check('pipe: duplicate fight ignored', len(db.query(
        'SELECT * FROM fights WHERE character_id=?', (cid,))) == 1)

    # ── v1.1 events through the real pipeline ──
    def ev_counts():
        return {
            'craft': db.query_one('SELECT COUNT(*) n, COALESCE(SUM(ok),0) ok, '
                                  'COALESCE(SUM(capped),0) capped FROM craft_events '
                                  'WHERE character_id=?', (cid,)),
            'depot': db.query_one('SELECT COUNT(*) n FROM depot_events WHERE character_id=?',
                                  (cid,))['n'],
            'faction': db.query_one('SELECT COUNT(*) n, COALESCE(SUM(delta),0) d FROM '
                                    'faction_events WHERE character_id=?', (cid,)),
            'fcaps': db.query_one('SELECT COUNT(*) n FROM faction_caps WHERE character_id=?',
                                  (cid,))['n'],
            'votes': db.query_one("SELECT votes FROM craft_recipe_skill WHERE character_id=? "
                                  "AND item='Tumpy Tonic' AND skill='Brewing'", (cid,)),
            'upgrades': db.query_one('SELECT COUNT(*) n FROM upgrade_events WHERE character_id=?',
                                     (cid,))['n'],
            'zones': db.query_one('SELECT COUNT(*) n FROM zone_events WHERE character_id=?', (cid,))['n'],
            'loot': db.query_one('SELECT COUNT(*) n, COALESCE(SUM(qty),0) q FROM loot_events '
                                 'WHERE character_id=?', (cid,)),
            'zs': {r['zone']: r for r in db.query('SELECT * FROM zone_stats WHERE character_id=?', (cid,))},
        }
    ec = ev_counts()
    zs = ec['zs']
    check('pipe: zone visits + loot rows (dash, depot, auto-sold)', ec['zones'] == 2 and ec['loot']['n'] == 3
          and ec['loot']['q'] == 4, (ec['zones'], dict(ec['loot'])))
    check('pipe: zone stats per zone', zs['Silly Meadow']['kills'] == 1 and zs['Silly Meadow']['xp_pct'] == 0.51
          and zs['Silly Meadow']['loot'] == 1 and zs['Dusty Hollow']['xp_pct'] == 1.25
          and zs['Dusty Hollow']['loot'] == 3 and zs['Dusty Hollow']['kills'] == 0, zs)
    check('pipe: auto-sell income counted apart from kill coin',
          hl('total_autosell_copper')['value_num'] == 25 and hl('total_coin_copper')['value_num'] == 530)
    # lines are 1 s apart: the clock runs from the first zone line (index 1) to the last
    # clock event (index n_events-1), all gaps well under 30 min
    check('pipe: zone seconds telescope to last clock event - first zone line',
          zs['Silly Meadow']['seconds'] + zs['Dusty Hollow']['seconds'] == (n_events - 1) - 1, zs)
    check('pipe: craft rows (2, 1 ok, 1 capped)', ec['craft']['n'] == 2 and ec['craft']['ok'] == 1
          and ec['craft']['capped'] == 1, dict(ec['craft']))
    check('pipe: cap attached to Tumpy Tonic', db.query_one(
        "SELECT capped FROM craft_events WHERE character_id=? AND item='Tumpy Tonic'",
        (cid,))['capped'] == 1)
    check('pipe: recipe->skill vote', ec['votes'] and ec['votes']['votes'] == 1, ec['votes'])
    check('pipe: depot rows', ec['depot'] == 2, ec['depot'])
    check('pipe: faction rows kept both identical hits', ec['faction']['n'] == 2
          and ec['faction']['d'] == -10, dict(ec['faction']))
    check('pipe: faction cap row', ec['fcaps'] == 1)
    check('pipe: upgrade row', ec['upgrades'] == 1, ec['upgrades'])
    from app.logscan import backfill

    def guard(key):
        r = db.query_one('SELECT value_num FROM highlights WHERE character_id=? AND key=?',
                         (cid, key))
        return r['value_num'] if r else None
    check('pipe: a from-zero scan sets the backfill guards without reading',
          guard(backfill.GUARD_KEY) == 0 and guard(backfill.REV_KEY) == backfill.BACKFILL_REV,
          (guard(backfill.GUARD_KEY), guard(backfill.REV_KEY)))

    # ── backfill: an install whose checkpoint already sits at EOF gets the
    #    event history exactly once ──
    EVENT_TABLES = ('craft_events', 'craft_caps', 'craft_recipe_skill', 'depot_events',
                    'faction_events', 'faction_caps', 'upgrade_events', 'zone_stats',
                    'zone_events', 'loot_events')
    with db.tx() as c:
        for table in EVENT_TABLES:
            c.execute(f'DELETE FROM {table} WHERE character_id=?', (cid,))
        c.execute('DELETE FROM highlights WHERE character_id=? AND key IN (?, ?)',
                  (cid, backfill.GUARD_KEY, backfill.REV_KEY))
    lines_before = hl('lines_parsed')['value_num']
    kills_before = hl('total_kills')['value_num']
    r_bf = importer.scan_once(dict(char))
    check('pipe: backfill scan consumed no new bytes', r_bf['lines'] == 0
          and r_bf['offset'] == size1, r_bf)
    ec2 = ev_counts()
    check('pipe: backfill restored craft/depot/faction/upgrade rows',
          ec2['craft']['n'] == 2 and ec2['craft']['capped'] == 1 and ec2['depot'] == 2
          and ec2['faction']['n'] == 2 and ec2['fcaps'] == 1 and ec2['upgrades'] == 1
          and ec2['votes'] and ec2['votes']['votes'] == 1, ec2)
    check('pipe: backfill restored zone/loot rows with identical stats',
          ec2['zones'] == 2 and ec2['loot']['q'] == 4
          and ec2['zs']['Silly Meadow']['seconds'] == zs['Silly Meadow']['seconds']
          and ec2['zs']['Dusty Hollow']['xp_pct'] == 1.25, ec2['zs'])
    check('pipe: backfill wrote no live-only counters',
          db.query_one("SELECT value_num FROM highlights WHERE character_id=? AND key='total_kills'",
                       (cid,))['value_num'] == kills_before)
    check('pipe: backfill touched no additive counters',
          hl('lines_parsed')['value_num'] == lines_before
          and hl('total_kills')['value_num'] == kills_before)
    check('pipe: backfill guards record offset + revision',
          guard(backfill.GUARD_KEY) == size1 and guard(backfill.REV_KEY) == backfill.BACKFILL_REV,
          (guard(backfill.GUARD_KEY), guard(backfill.REV_KEY)))
    importer.scan_once(dict(char))
    check('pipe: second scan does not backfill again', ev_counts()['craft']['n'] == 2)

    # ── backfill revision 2+3 on a v1.1 install: only the offset guard exists (rev 1
    #    ran), so only the NEW event kinds are replayed — no duplicate craft rows ──
    with db.tx() as c:
        for table in ('upgrade_events', 'zone_stats', 'zone_events', 'loot_events'):
            c.execute(f'DELETE FROM {table} WHERE character_id=?', (cid,))
        c.execute('DELETE FROM highlights WHERE character_id=? AND key IN (?, ?)',
                  (cid, backfill.REV_KEY, 'zone_clock_ts'))
    check('pipe: offset guard alone reads as revision 1', backfill.stored_rev(cid) == 1)
    importer.scan_once(dict(char))
    ec3 = ev_counts()
    check('pipe: rev-2/3 backfill adds upgrades + zone rows only',
          ec3['upgrades'] == 1 and ec3['zones'] == 2 and ec3['craft']['n'] == 2
          and ec3['faction']['n'] == 2, ec3)
    check('pipe: revision recorded after the partial backfill',
          guard(backfill.REV_KEY) == backfill.BACKFILL_REV and not backfill.needed(cid))

    # ── backfill revision 3 alone on a v1.1 install that already had rev 2 ──
    with db.tx() as c:
        for table in ('zone_stats', 'zone_events', 'loot_events'):
            c.execute(f'DELETE FROM {table} WHERE character_id=?', (cid,))
        c.execute('UPDATE highlights SET value_num=2 WHERE character_id=? AND key=?',
                  (cid, backfill.REV_KEY))
        c.execute("DELETE FROM highlights WHERE character_id=? AND key='zone_clock_ts'", (cid,))
    importer.scan_once(dict(char))
    ec4 = ev_counts()
    check('pipe: rev-3 backfill adds zone/loot rows only, upgrades untouched',
          ec4['zones'] == 2 and ec4['loot']['n'] == 3 and ec4['upgrades'] == 1
          and ec4['zs']['Silly Meadow']['seconds'] == zs['Silly Meadow']['seconds'], ec4)

    # ── append 5 lines: only the new bytes are consumed ──
    extra = ['You slash a spider for 9 points of damage.',
             'You have slain a spider!',
             'You gain experience! (0.10%)',
             'You have gained an ability point!  You now have 4 ability points.',
             'Auto attack is off.']
    with open(log_path, 'a', encoding='utf-8', newline='') as f:
        f.write(_mklines(t0 + n1 + 10, extra))
    size2 = os.path.getsize(log_path)

    r2 = importer.scan_once(dict(char))
    check('pipe: rescan reaches new EOF', r2['offset'] == size2, r2)
    check('pipe: only appended lines consumed', r2['lines'] == 5, r2['lines'])
    # the new pipeline seeded its zone clock from the DB: the appended kill lands
    # in Dusty Hollow and the gap since the last clock event (< 30 min) counts
    zs2 = ev_counts()['zs']
    check('pipe: resumed pipeline attributes the new kill to the seeded zone',
          zs2['Dusty Hollow']['kills'] == 1
          and zs2['Dusty Hollow']['seconds'] > zs['Dusty Hollow']['seconds'], zs2['Dusty Hollow'])
    check('pipe: counters incremented once',
          hl('lines_parsed')['value_num'] == n1 + 5
          and hl('total_kills')['value_num'] == 2)
    check('pipe: no phantom session on resume',
          hl('total_sessions')['value_num'] == 1, hl('total_sessions'))
    check('pipe: second fight persisted', len(db.query(
        'SELECT * FROM fights WHERE character_id=?', (cid,))) == 2)

    # ── truncate: size < checkpoint -> reset and rescan from byte 0 ──
    keep = size1 // 2
    with open(log_path, 'rb') as f:
        head = f.read(keep)
    head = head[:head.rfind(b'\n') + 1]         # trim to the last full line
    with open(log_path, 'wb') as f:
        f.write(head)
    n3 = head.count(b'\n')

    r3 = importer.scan_once(dict(char))
    check('pipe: truncation resets to 0', r3.get('reset') is True, r3)
    check('pipe: rescan consumes whole file', r3['lines'] == n3
          and r3['offset'] == len(head), r3)
    src = db.query_one('SELECT * FROM log_source WHERE path=?', (log_path,))
    check('pipe: one checkpoint row after reset',
          src is not None and src['byte_offset'] == len(head), src)

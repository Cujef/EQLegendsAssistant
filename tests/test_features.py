"""Feature-module suites: quests CRUD/filters, overview stat math, exaltation
matching, tradeskills — all against synthetic rows in the scratch db."""
import json


def _seed(db):
    """One character, a synced item set, a quest, and an inventory snapshot."""
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO characters(id, name, server, is_active, created_at) "
                  "VALUES(99, 'Feat', 'test', 0, 0)")
        c.execute("INSERT OR REPLACE INTO items(name_norm, display_name, source, slot_text, "
                  "class_text, ac, hp, mana, haste_pct, dmg, stats_json, resists_json, parsed_ok) "
                  "VALUES('iron helm', 'Iron Helm', 'wiki', 'HEAD', 'WAR CLR', 10, 25, 0, 0, NULL, "
                  "'{\"STR\": 5, \"WIS\": 3}', '{\"SV FIRE\": 10}', 1)")
        c.execute("INSERT OR REPLACE INTO items(name_norm, display_name, source, slot_text, "
                  "class_text, ac, hp, mana, haste_pct, dmg, stats_json, parsed_ok) "
                  "VALUES('swift blade', 'Swift Blade', 'wiki', 'PRIMARY', 'WAR', 5, 0, 0, 21, 9, "
                  "'{\"STR\": 2}', 1)")
        c.execute("INSERT OR REPLACE INTO items(name_norm, display_name, source, parsed_ok) "
                  "VALUES('glowing shard', 'Glowing Shard', 'wiki', 1)")
        c.execute("INSERT OR REPLACE INTO item_effects(name_norm, effect_type, effect_name, "
                  "effect_family, effect_tier, raw_line) VALUES('glowing shard', 'focus', "
                  "'Improved Damage II', 'Improved Damage', 2, 'Focus Effect: Improved Damage II')")
        c.execute("INSERT OR REPLACE INTO quests(id, name, wiki_url, start_zone, quest_giver, "
                  "level_min, level_max, classes_json, parsed_ok) VALUES(7, 'Shard Errand', "
                  "'https://eqlwiki.com/Shard_Errand', 'Qeynos', 'Fizzik', 10, 20, "
                  "'[\"Warrior\"]', 1)")
        c.execute("INSERT OR REPLACE INTO quest_steps(quest_id, step_index, text) "
                  "VALUES(7, 0, 'Hand Fizzik the Glowing Shard')")
        c.execute("INSERT OR REPLACE INTO quest_item_mentions(quest_id, item_name_norm) "
                  "VALUES(7, 'glowing shard')")
        c.execute("INSERT OR REPLACE INTO quests(id, name, classes_json, level_min, parsed_ok) "
                  "VALUES(8, 'Everyone Quest', '[\"All\"]', 40, 1)")
        cur = c.execute("INSERT INTO inventory_snapshots(character_id, imported_at, parse_rev) "
                        "VALUES(99, 1000, 2)")
        snap = cur.lastrowid
        rows = [
            # location, root, parent, sub, name, norm, iid, cnt, slots, empty, exalt, tier, worn
            ('Head', 'Head', None, None, 'Iron Helm +2', 'iron helm', 1, 1, 10, 0, 0, 2, 1),
            ('Primary', 'Primary', None, None, 'Swift Blade', 'swift blade', 2, 1, 10, 0, 0, 0, 1),
            ('Head-Slot7', 'Head', 'Head', 7, 'Glowing Shard (Exaltation)', 'glowing shard',
             3, 1, 10, 0, 1, 0, 1),
            ('Primary-Slot7', 'Primary', 'Primary', 7, 'Empty', 'empty', 0, 0, 0, 1, 0, 0, 1),
            ('General 1-Slot1', 'General 1', 'General 1', 1, 'Glowing Shard', 'glowing shard',
             3, 1, 0, 0, 0, 0, 0),
            ('Augmentation', 'Augmentation', None, None, 'Spare Fang (Exaltation)', 'spare fang',
             4, 1, 0, 0, 1, 0, 0),
            # an 8-slot bag: its empty pockets 7/8 are POCKETS, never sockets
            ('Bank1', 'Bank1', None, None, 'Big Bag', 'big bag', 5, 1, 8, 0, 0, 0, 0),
            ('Bank1-Slot7', 'Bank1', 'Bank1', 7, 'Empty', 'empty', 0, 0, 0, 1, 0, 0, 0),
            ('Bank1-Slot8', 'Bank1', 'Bank1', 8, 'Empty', 'empty', 0, 0, 0, 1, 0, 0, 0),
        ]
        c.executemany(
            'INSERT INTO inventory_items(snapshot_id, location, root, parent_location, sub_slot, '
            'name, name_norm, item_id, count, slots, is_empty, is_exaltation, upgrade_tier, '
            'is_equipped) VALUES(' + str(snap) + ',?,?,?,?,?,?,?,?,?,?,?,?,?)', rows)
        c.execute("INSERT OR IGNORE INTO skill_levels(character_id, skill, level, ts) "
                  "VALUES(99, 'Baking', 56, 500)")
        c.execute("INSERT OR IGNORE INTO skill_levels(character_id, skill, level, ts) "
                  "VALUES(99, 'Baking', 57, 600)")
        c.execute("INSERT OR IGNORE INTO skill_levels(character_id, skill, level, ts) "
                  "VALUES(99, '1H Slashing', 100, 700)")
        c.execute("INSERT OR IGNORE INTO level_history(character_id, level, ts) VALUES(99, 44, 800)")
        c.execute("INSERT OR IGNORE INTO aa_ledger(character_id, ts, kind, ability_name, points, "
                  "balance_after) VALUES(99, 900, 'gain', '', 1, 12)")
        c.execute("INSERT OR IGNORE INTO aa_ledger(character_id, ts, kind, ability_name, points) "
                  "VALUES(99, 950, 'spend', 'Ambidexterity', 9)")
        c.execute("INSERT OR IGNORE INTO deaths(character_id, ts, killer) VALUES(99, 10, 'a bear')")
        c.execute("INSERT OR IGNORE INTO deaths(character_id, ts, killer) VALUES(99, 20, 'a bear')")
        c.execute("INSERT OR IGNORE INTO deaths(character_id, ts, killer) VALUES(99, 30, 'a wolf')")
        c.execute("INSERT OR REPLACE INTO highlights(character_id, key, value_num, ts) "
                  "VALUES(99, 'max_melee_hit', 46, 40)")
        # guides use the SYNC WRITER's slugs (wiki_api.GUIDES); consumers must
        # match by kind (zem/leveling) or those exact slugs — regression for the
        # title-vs-slug drift the code review caught
        c.execute("INSERT OR REPLACE INTO guides(slug, title, kind, parsed_json, parsed_ok) "
                  "VALUES('zem_list', 'Recommended Levels and ZEM List', 'zem', "
                  "'{\"rows\": [{\"zone\": \"Unrest\", \"level_min\": 40, "
                  "\"level_max\": 50, \"zem\": 100}]}', 1)")
        c.execute("INSERT OR REPLACE INTO guides(slug, title, kind, parsed_json, parsed_ok) "
                  "VALUES('skill_baking', 'Skill Baking', 'tradeskill', "
                  "'{\"sections\": []}', 1)")
        # v1.1: log-derived tradeskill / depot / faction history
        c.execute("DELETE FROM craft_events WHERE character_id=99")
        c.executemany("INSERT INTO craft_events(character_id, ts, item, item_norm, ok, capped) "
                      "VALUES(99,?,?,?,?,?)", [
                          (1000, 'Fish Rolls', 'fish rolls', 1, 0),
                          (1003, 'Fish Rolls', 'fish rolls', 1, 0),
                          (1006, 'Fish Rolls', 'fish rolls', 0, 0),
                          (1009, 'Fish Rolls', 'fish rolls', 1, 1),
                          (1012, 'Tumpy Tonic', 'tumpy tonic', 0, 0),
                          (1015, 'Glowing Shard', 'glowing shard', 1, 0),
                      ])
        c.execute("INSERT OR REPLACE INTO craft_caps(character_id, item, first_ts, last_ts, count) "
                  "VALUES(99, 'Fish Rolls', 1009, 1009, 1)")
        c.execute("INSERT OR REPLACE INTO craft_recipe_skill(character_id, item, skill, votes, last_ts) "
                  "VALUES(99, 'Fish Rolls', 'Baking', 3, 1009)")
        c.execute("INSERT OR REPLACE INTO craft_recipe_skill(character_id, item, skill, votes, last_ts) "
                  "VALUES(99, 'Fish Rolls', 'Brewing', 1, 1003)")
        c.execute("DELETE FROM depot_events WHERE character_id=99")
        c.executemany("INSERT INTO depot_events(character_id, ts, kind, item, item_norm, qty, left_qty) "
                      "VALUES(99,?,?,?,?,?,?)", [
                          (1000, 'consume', 'Glowing Shard', 'glowing shard', 2, 7),
                          (1001, 'deposit', 'Glowing Shard', 'glowing shard', 3, None),
                          (1002, 'withdraw', 'Glowing Shard', 'glowing shard', 1, None),
                          (1003, 'consume', 'Water Flask', 'water flask', 4, 20),
                          (1004, 'deposit', 'Bat Wing', 'bat wing', 40, None),
                      ])
        c.execute("DELETE FROM faction_events WHERE character_id=99")
        c.executemany("INSERT INTO faction_events(character_id, ts, faction, delta) "
                      "VALUES(99,?,?,?)", [
                          (1000, 'Frogloks of Guk', -5), (1000, 'Frogloks of Guk', -5),
                          (1010, 'Knights of Truth', 12), (1020, 'Knights of Truth', 3),
                          (1030, 'Ring of Scale', -2),
                      ])
        c.execute("INSERT OR REPLACE INTO faction_caps(character_id, faction, direction, first_ts, "
                  "last_ts, count) VALUES(99, 'Knights of Truth', 'better', 1015, 1015, 1)")
        c.execute("INSERT OR REPLACE INTO faction_caps(character_id, faction, direction, first_ts, "
                  "last_ts, count) VALUES(99, 'Ring of Scale', 'worse', 1040, 1040, 2)")
        c.execute("INSERT OR REPLACE INTO faction_caps(character_id, faction, direction, first_ts, "
                  "last_ts, count) VALUES(99, 'Storm Guard', 'better', 1050, 1050, 1)")


def run(check):
    from app import db, exaltation, quests, stats, tradeskills
    db.init()
    _seed(db)

    # ── quests ──
    lst = quests.list_quests(99)
    check('quests: list all', len(lst) == 2, lst)
    war = quests.list_quests(99, cls='Warrior')
    check('quests: class filter includes All', len(war) == 2)
    brd = quests.list_quests(99, cls='Bard')
    check('quests: class filter excludes', len(brd) == 1 and brd[0]['id'] == 8, brd)
    lv = quests.list_quests(99, level_min=25, level_max=35)
    check('quests: level window excludes both', len(lv) == 0, lv)
    lv = quests.list_quests(99, level_min=15)
    check('quests: level_min overlap', {q['id'] for q in lv} == {7, 8})
    quests.set_status(99, 7, 'tracked')
    pv = quests.progress_view(99)
    check('quests: tracked appears', len(pv['quests']) == 1 and pv['quests'][0]['id'] == 7)
    done = quests.toggle_step(99, 7, 0)
    check('quests: step toggles on', done is True)
    detail = quests.quest_detail(99, 7)
    check('quests: detail steps done', detail['steps'][0]['done'] == 1)
    check('quests: toggle off', quests.toggle_step(99, 7, 0) is False)
    quests.set_status(99, 7, 'completed')
    hid = quests.list_quests(99, hide_completed=True)
    check('quests: hide_completed', {q['id'] for q in hid} == {8})
    quests.set_status(99, 7, 'untracked')
    check('quests: untrack clears', len(quests.progress_view(99)['quests']) == 0)
    quests.set_status(99, 7, 'tracked')

    # ── whattodo ──
    wtd = quests.whattodo(99)
    check('whattodo: item match finds quest',
          len(wtd['quest_matches']) == 1 and wtd['quest_matches'][0]['id'] == 7,
          wtd['quest_matches'])
    check('whattodo: level from history', wtd['leveling']['level'] == 44)
    check('whattodo: zem rows via kind (slug-drift regression)',
          len(wtd['leveling']['zem_rows']) == 1
          and wtd['leveling']['zem_rows'][0]['zone'] == 'Unrest',
          wtd['leveling'])

    # ── overview stats ──
    ov = stats.overview(99)
    c = ov['computed']
    # Iron Helm STR 5 + Swift Blade STR 2; socketed shard contributes NO stats
    check('stats: STR sums worn only', c['stats']['STR'] == 7, c['stats'])
    check('stats: WIS', c['stats']['WIS'] == 3)
    check('stats: AC', c['ac'] == 15)
    check('stats: HP', c['hp'] == 25)
    check('stats: resist', c['resists']['SV FIRE'] == 10)
    check('stats: worn haste max', c['worn_haste'] == 21)
    check('stats: matched count', c['items_matched'] == 2, c)
    check('stats: aa math', ov['aa']['earned'] == 21 and ov['aa']['spent'] == 9
          and ov['aa']['unspent'] == 12, ov['aa'])
    check('stats: nemesis order', ov['nemesis'][0]['killer'] == 'a bear'
          and ov['nemesis'][0]['n'] == 2)
    check('stats: level', ov['level'] == 44)
    check('stats: focus best', any(f['effect_name'] == 'Improved Damage II'
                                   for f in ov['focus']), ov['focus'])
    check('stats: caps present with fallback', any(r['source'] == 'fallback'
                                                   for r in ov['caps']))
    stats.set_manual(99, 'race', 'Human')
    check('stats: manual set', stats.overview(99)['manual'].get('race') == 'Human')
    stats.set_manual(99, 'race', '')
    check('stats: manual clear', 'race' not in stats.overview(99)['manual'])

    # ── exaltations ──
    ex = exaltation.view(99)
    check('exalt: socketed found', len(ex['socketed']) == 1
          and ex['socketed'][0]['host_item'] == 'Iron Helm +2', ex['socketed'])
    check('exalt: socketed effect resolved',
          ex['socketed'][0]['effects'][0]['effect_name'] == 'Improved Damage II')
    check('exalt: loose found', len(ex['loose']) == 1
          and ex['loose'][0]['item'] == 'Spare Fang (Exaltation)')
    check('exalt: unknown flagged', len(ex['unknown']) == 1
          and ex['unknown'][0]['name_norm'] == 'spare fang')
    check('exalt: open socket on weapon ONLY (bag pockets excluded)',
          len(ex['open_sockets']) == 1
          and ex['open_sockets'][0]['host_item'] == 'Swift Blade'
          and ex['open_sockets'][0]['host_is_weapon'] is True, ex['open_sockets'])
    check('exalt: rules flagged assumed', ex['rules']['assumed'] is True)
    from app.inventory import get_view, is_container_location
    check('inv: container detection', is_container_location('Bank1')
          and is_container_location('General 8')
          and not is_container_location('Bank1-Slot4')
          and not is_container_location('Face'))
    gv = get_view(99)
    check('inv: view open sockets exclude bag pockets',
          all(s['parent_location'] != 'Bank1' for s in gv['open_sockets']),
          gv['open_sockets'])

    # ── tradeskills ──
    # ── normalization + wiki haste parse (join-coverage regressions) ──
    from app.inventory import normalize_name
    check('norm: apostrophes stripped both sides',
          normalize_name("Djarn's Amethyst Ring") == 'djarns amethyst ring'
          and normalize_name('Djarns Amethyst Ring') == 'djarns amethyst ring')
    check('norm: crafted-item asterisk stripped',
          normalize_name('Backpack*') == 'backpack')
    from app.sync.wiki_parse import parse_statsblock
    sb = parse_statsblock('MAGIC ITEM<br>Slot: BACK<br>AC: 10<br>'
                          'Haste: +36%  <br>WT: 0.1  Size: MEDIUM<br>')
    check('wiki: mixed-case Haste line parsed', sb['haste_pct'] == 36, sb['haste_pct'])

    ts = tradeskills.view(99)
    baking = next(t for t in ts['tradeskills'] if t['skill'] == 'Baking')
    check('ts: baking level max', baking['level'] == 57)
    check('ts: guide matched by sync slug (slug-drift regression)',
          baking['guide_synced'] is True, baking)
    check('ts: wiki url uses page title',
          baking['wiki_url'].endswith('/Skill_Baking'), baking['wiki_url'])
    check('ts: unknown skill null',
          next(t for t in ts['tradeskills'] if t['skill'] == 'Pottery')['level'] is None)
    check('ts: other skills', any(s['skill'] == '1H Slashing' and s['level'] == 100
                                  for s in ts['other_skills']))

    # ── recipes / materials (log-derived) ──
    rec = {r['item']: r for r in ts['recipes']}
    fr = rec['Fish Rolls']
    check('ts: recipe made/failed/rate', fr['made'] == 3 and fr['failed'] == 1
          and fr['attempts'] == 4 and fr['rate'] == 75.0, fr)
    check('ts: recipe CAP from craft_caps', fr['capped'] and fr['capped']['count'] == 1
          and rec['Tumpy Tonic']['capped'] is None)
    check('ts: recipe skill = highest votes, labeled', fr['skill'] == 'Baking'
          and fr['skill_votes'] == 3 and rec['Tumpy Tonic']['skill'] is None)
    check('ts: per-skill rollup from inferred mapping',
          baking['recipes'] == 1 and baking['combines'] == 4 and baking['made'] == 3
          and baking['capped_recipes'] == 1, baking)
    check('ts: totals', ts['totals']['attempts'] == 6 and ts['totals']['made'] == 4
          and ts['totals']['failed'] == 2 and ts['totals']['recipes'] == 3
          and ts['totals']['capped'] == 1 and ts['totals']['unassigned'] == 2, ts['totals'])
    mats = {m['item_norm']: m for m in ts['materials']}
    gs = mats['glowing shard']
    check('ts: material used + depot estimate (7 left, +3 deposit, -1 withdraw)',
          gs['used'] == 2 and gs['last_left'] == 7 and gs['est_depot'] == 9, gs)
    check('ts: material on hand comes from the dump (General 1-Slot1 shard)',
          gs['on_hand'] == 1 and gs['on_hand_source'] == 'dump', gs)
    check('ts: deposit-only material has no estimate',
          mats['bat wing']['est_depot'] is None and mats['bat wing']['deposited'] == 40
          and mats['bat wing']['on_hand'] == 0, mats['bat wing'])
    check('ts: materials sorted by usage', ts['materials'][0]['item_norm'] == 'water flask')

    # ── factions ──
    from app import factions
    fv = factions.view(99)
    fx = {f['faction']: f for f in fv['factions']}
    check('fx: net delta + events (identical same-second hits both count)',
          fx['Frogloks of Guk']['delta'] == -10 and fx['Frogloks of Guk']['events'] == 2, fx)
    check('fx: cap only when it is the last word',
          fx['Knights of Truth']['capped'] is None      # adjusted again at 1020 after the 1015 cap
          and fx['Ring of Scale']['capped'] == 'worse'   # cap at 1040 after the 1030 hit
          and fx['Storm Guard']['capped'] == 'better'    # cap only, never adjusted
          and fx['Storm Guard']['events'] == 0, fx)
    check('fx: gained/lost split', fx['Knights of Truth']['gained'] == 15
          and fx['Knights of Truth']['lost'] == 0 and fx['Ring of Scale']['lost'] == 2)
    check('fx: totals', fv['totals']['factions'] == 4 and fv['totals']['events'] == 5
          and fv['totals']['raised'] == 1 and fv['totals']['lowered'] == 2
          and fv['totals']['maxed'] == 1 and fv['totals']['bottomed'] == 1, fv['totals'])
    check('fx: recent newest first', fv['recent'][0]['faction'] == 'Ring of Scale')

    # ── inventory view: PARSE_REV 4 linkage on a freshly imported dump ──
    _inventory_view(check, db)
    _gamefiles(check, db)
    _zones_and_loot(check, db)
    _skyquests(check, db)


def _zones_and_loot(check, db):
    """zones.view: guide matching + ratings + per-hour rules; zones.loot grouping."""
    import json
    from app import zones

    check('zones: key normaliser', zones.zone_key('The Lavastorm Mountains') == 'lavastorm mountains'
          and zones.zone_key('Plane of Sky *') == 'plane of sky'
          and zones.zone_key("Kael`s Fort") == 'kaels fort')
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO guides(slug, title, kind, parsed_json, parsed_ok) "
                  "VALUES('zem_list', 'ZEM', 'zem', ?, 1)", (json.dumps({'rows': [
                      {'region': 'Antonica', 'zone': 'Lavastorm Mountains', 'level_min': 20,
                       'level_max': 40, 'zem': None,
                       'ratings': {'1': 'inefficient', '20': 'efficient', '35': 'recommended'}},
                      {'region': 'Planes', 'zone': 'Plane of Sky *', 'level_min': 46, 'level_max': 60,
                       'zem': 125, 'ratings': {}},
                      {'region': 'Faydwer', 'zone': 'Crushbone', 'level_min': 5, 'level_max': 15,
                       'zem': None, 'ratings': {'1': 'efficient'}},
                      {'region': 'Faydwer', 'zone': 'Crushbone Keep', 'level_min': 5, 'level_max': 15,
                       'zem': None, 'ratings': {}},
                  ]}),))
        c.execute('DELETE FROM zone_stats WHERE character_id=99')
        c.executemany('INSERT INTO zone_stats(character_id, zone, seconds, kills, xp_pct, loot, visits, '
                      'first_ts, last_ts) VALUES(99,?,?,?,?,?,?,?,?)', [
                          ('The Lavastorm Mountains', 3600, 30, 6.0, 4, 2, 1000, 5000),
                          ('Plane of Sky', 1800, 5, 1.5, 0, 1, 6000, 7800),
                          ('Crushbone', 200, 2, 0.1, 1, 1, 100, 300),     # under 0.1 h
                          ('Nowhere Special', 900, 1, 0.0, 0, 1, 50, 950),
                      ])
        c.execute('DELETE FROM zone_events WHERE character_id=99')
        c.executemany('INSERT INTO zone_events(character_id, ts, zone, zone_base) VALUES(99,?,?,?)', [
            (1000, 'The Lavastorm Mountains 2 (Adaptive)', 'The Lavastorm Mountains'),
            (6000, 'Plane of Sky', 'Plane of Sky')])
        c.execute('DELETE FROM loot_events WHERE character_id=99')
        c.executemany('INSERT INTO loot_events(character_id, ts, item, item_norm, source, qty, zone) '
                      'VALUES(99,?,?,?,?,?,?)', [
                          (1001, 'Glowing Shard', 'glowing shard', 'a lava basilisk', 1, 'The Lavastorm Mountains'),
                          (1002, 'Glowing Shard', 'glowing shard', 'a lava basilisk', 1, 'The Lavastorm Mountains'),
                          (1003, 'Glowing Shard', 'glowing shard', 'a fire elemental', 1, 'The Lavastorm Mountains'),
                          (900, 'Bone Chips', 'bone chips', 'Unknown', 5, None),
                      ])
        # level 30 for the rating bracket (the seed gives 99 a higher level; this suite
        # runs last in this file, so replacing it is safe)
        c.execute('DELETE FROM level_history WHERE character_id=99')
        c.execute('INSERT INTO level_history(character_id, level, ts) VALUES(99, 30, 1)')
    v = zones.view(99)
    z = {x['zone']: x for x in v['zones']}
    check('zones: guide match through "The " prefix, rating for the level bracket',
          z['The Lavastorm Mountains']['guide'] and z['The Lavastorm Mountains']['guide']['rating'] == 'efficient'
          and z['The Lavastorm Mountains']['guide']['level_min'] == 20, z['The Lavastorm Mountains']['guide'])
    check('zones: guide match through the " *" suffix, numeric zem when present',
          z['Plane of Sky']['guide'] and z['Plane of Sky']['guide']['zem'] == 125)
    check('zones: ambiguous prefix (Crushbone vs Crushbone Keep) still matches exactly',
          z['Crushbone']['guide'] and z['Crushbone']['guide']['zone'] == 'Crushbone')
    check('zones: no guide -> None', z['Nowhere Special']['guide'] is None)
    check('zones: per-hour math and the 0.1 h floor',
          z['The Lavastorm Mountains']['hours'] == 1.0 and z['The Lavastorm Mountains']['kills_per_hour'] == 30.0
          and z['The Lavastorm Mountains']['xp_per_hour'] == 6.0
          and z['Plane of Sky']['kills_per_hour'] == 10.0 and z['Crushbone']['kills_per_hour'] is None)
    check('zones: sorted by seconds, recent visits + current zone',
          v['zones'][0]['zone'] == 'The Lavastorm Mountains' and v['current_zone'] == 'Plane of Sky'
          and v['recent_visits'][0]['zone'] == 'Plane of Sky' and v['level'] == 30)
    check('zones: totals', v['totals']['kills'] == 38 and v['totals']['hours'] == 1.8
          and v['totals']['visits'] == 5, v['totals'])

    lo = zones.loot(99)
    it = {x['item_norm']: x for x in lo['items']}
    check('loot: grouped with top sources incl. zone', it['glowing shard']['count'] == 3
          and it['glowing shard']['sources'][0] == {'source': 'a lava basilisk',
                                                    'zone': 'The Lavastorm Mountains', 'n': 2}
          and it['glowing shard']['in_item_db'] is True, it['glowing shard'])
    check('loot: qty and unknown zone tolerated', it['bone chips']['qty'] == 5
          and it['bone chips']['sources'][0]['zone'] is None and it['bone chips']['in_item_db'] is False)
    check('loot: search filter', [x['item_norm'] for x in zones.loot(99, 'bone')['items']] == ['bone chips']
          and zones.loot(99, 'bone')['total_events'] == 4)
    check('loot: unlimited variant used by the export', len(zones.loot(99, limit=None)['items']) == 2
          and zones.loot(99, limit=None)['items'][0]['sources'])


def _gamefiles(check, db):
    """/outputfile faction + recipes: name parsing, tolerant parsers, imports,
    and the joins into the Factions / Tradeskills views."""
    from app import characters, factions, gamefiles, tradeskills

    p = gamefiles.parse_outputfile_name
    check('gf: inventory name', p('Fizzwick_halas-Inventory.txt')
          == {'name': 'Fizzwick', 'server': 'halas', 'kind': 'inventory', 'skill': None})
    check('gf: faction name + path', p('C:\\EQ\\Fizzwick_halas-Faction.txt')['kind'] == 'faction')
    check('gf: recipes name carries the skill',
          p('Fizzwick_halas-Baking-Recipes.txt') == {'name': 'Fizzwick', 'server': 'halas',
                                                    'kind': 'recipes', 'skill': 'Baking'})
    check('gf: recipes skill token mapped to the log name',
          p('Fizzwick_halas-Jewelcrafting-Recipes.txt')['skill'] == 'Jewelry Making'
          and p('Fizzwick_halas-Poisonmaking-Recipes.txt')['skill'] == 'Make Poison'
          and p('Fizzwick_halas-all-Recipes.txt')['skill'] == 'all'
          and p('fizzwick_halas-baking-recipes.TXT')['skill'] == 'Baking')
    check('gf: not an export', p('eqlog_Fizzwick_halas.txt') is None and p('notes.txt') is None)
    check('gf: the real faction export name (-<CLASS>-Factions.txt)',
          p('Fizzwick_halas-PAL-Factions.txt') == {'name': 'Fizzwick', 'server': 'halas',
                                                    'kind': 'faction', 'skill': None}
          and p('Fizzwick_halas-Factions.txt')['kind'] == 'faction')
    REAL_FAC = ('ID\tName\tStandingValue\tPointsToMax\r\n65\tBrownies of Faydwer\t0\t2000\r\n'
                '138\tClockworks of Ak`Anon\t0\t2000\r\n')
    check('gf: the real faction header is sniffed by content',
          gamefiles.detect_kind('picked.txt', REAL_FAC) == 'faction')
    pf_real = gamefiles.parse_faction(REAL_FAC)
    check('gf: the real faction body parses', len(pf_real['rows']) == 2
          and pf_real['rows'][1] == {'faction_id': 138, 'faction': 'Clockworks of Ak`Anon',
                                     'value': 0, 'to_max': 2000} and not pf_real['skipped'], pf_real)
    check('gf: owner helper covers every kind',
          characters.parse_outputfile_owner('X_y-Faction.txt') == ('X', 'y')
          and characters.parse_outputfile_owner('X_y-Baking-Recipes.txt') == ('X', 'y'))
    check('gf: standing bands', gamefiles.standing_label(1500) == 'Ally'
          and gamefiles.standing_label(0) == 'Indifferent'
          and gamefiles.standing_label(-1) == 'Apprehensive'
          and gamefiles.standing_label(-2000) == 'Ready to Attack'
          and gamefiles.standing_label(None) is None)

    # faction: header + tabs, CRLF
    fac = ('Faction ID\tName\tCurrent Faction\tValue to Max\r\n'
           '5001\tKnights of Truth\t1250\t750\r\n'
           '5002\tFrogloks of Guk\t-640\t2640\r\n'
           '5003\tStorm Guard\t2000\t0\r\n'
           'some trailing note\r\n')
    pf = gamefiles.parse_faction(fac)
    check('gf: faction rows parsed (header skipped)', len(pf['rows']) == 3
          and pf['rows'][0] == {'faction_id': 5001, 'faction': 'Knights of Truth',
                                'value': 1250, 'to_max': 750}, pf)
    check('gf: trailing junk reported, not guessed', pf['skipped'] == ['some trailing note'])
    # headerless, space-aligned, no to-max column
    pf2 = gamefiles.parse_faction('5001   Knights of Truth    1250\n5002   Ring of Scale   -12\n')
    check('gf: faction headerless space-aligned', [r['faction'] for r in pf2['rows']]
          == ['Knights of Truth', 'Ring of Scale'] and pf2['rows'][1]['value'] == -12
          and pf2['rows'][0]['to_max'] is None, pf2)
    pf3 = gamefiles.parse_faction('5001 Knights of Truth 1250 750\n5002 Ring of Scale -12\n')
    check('gf: faction single-spaced rows (trailing ints are the numbers)',
          pf3['rows'][0] == {'faction_id': 5001, 'faction': 'Knights of Truth', 'value': 1250,
                             'to_max': 750}
          and pf3['rows'][1]['value'] == -12 and pf3['rows'][1]['to_max'] is None, pf3)
    try:
        gamefiles.parse_faction('Location\tName\tID\nHead\tCap\t1\n')
        check('gf: faction rejects non-faction text', False)
    except ValueError:
        check('gf: faction rejects non-faction text', True)

    # recipes: header + tabs, and the documented "1912   Name" shape, and single space
    rec = ('Recipe ID\tName\n1912\tPurple Trickster Circle Fly\n13475   Fish Rolls\n'
           '77 Tumpy Tonic\n')
    pr = gamefiles.parse_recipes(rec)
    check('gf: recipes parsed (tabs, runs of spaces, single space)',
          [(r['recipe_id'], r['name']) for r in pr['rows']]
          == [(1912, 'Purple Trickster Circle Fly'), (13475, 'Fish Rolls'), (77, 'Tumpy Tonic')], pr)
    try:
        gamefiles.parse_recipes('nothing\nhere\n')
        check('gf: recipes rejects non-recipe text', False)
    except ValueError:
        check('gf: recipes rejects non-recipe text', True)

    # kind detection: filename first, then content
    check('gf: kind by filename', gamefiles.detect_kind('A_b-Faction.txt', 'x') == 'faction'
          and gamefiles.detect_kind('A_b-Baking-Recipes.txt', 'x') == 'recipes'
          and gamefiles.detect_kind('A_b-Inventory.txt', 'x') == 'inventory')
    check('gf: kind by content', gamefiles.detect_kind('picked.txt', 'Location\tName\tID\n') == 'inventory'
          and gamefiles.detect_kind('picked.txt', fac) == 'faction'
          and gamefiles.detect_kind('picked.txt', '5001   Knights of Truth    1250\n') == 'faction'
          and gamefiles.detect_kind('picked.txt', '1912\tPurple Trickster Circle Fly\n') == 'recipes'
          and gamefiles.detect_kind('picked.txt', 'hello world\n') is None)

    # imports into the views (character 99 has faction_events at ts 1000..1030)
    row = characters.add('GameFiles', 'test', None, None, activate=False)
    cid = row['id']
    r = gamefiles.import_any(cid, ('\ufeff' + fac).encode('utf-8'), filename='GameFiles_test-Faction.txt')
    check('gf: import_any -> faction (BOM tolerated)', r['kind'] == 'faction' and r['rows'] == 3
          and r['skipped_count'] == 1, r)
    r = gamefiles.import_any(cid, rec.encode('utf-8'), filename='GameFiles_test-Baking-Recipes.txt')
    check('gf: import_any -> recipes with skill', r['kind'] == 'recipes' and r['skill'] == 'Baking'
          and r['rows'] == 3, r)
    r = gamefiles.import_any(cid, rec.encode('utf-8'), filename='GameFiles_test-Baking-Recipes.txt')
    check('gf: re-import of a skill replaces, not duplicates',
          len(gamefiles.known_recipes(cid)) == 3)
    r = gamefiles.import_any(cid, b'Location\tName\tID\tCount\tSlots\nHead\tCap\t1\t1\t10\n',
                             filename='picked.txt')
    check('gf: import_any -> inventory by content', r['kind'] == 'inventory' and r['items'] == 1, r)
    try:
        gamefiles.import_any(cid, b'hello\n', filename='whatever.txt')
        check('gf: import_any rejects unknown content', False)
    except ValueError:
        check('gf: import_any rejects unknown content', True)

    # factions view: standing + estimate = file value + movement since the import
    with db.tx() as c:
        c.execute('DELETE FROM faction_standings WHERE character_id=99')
        c.executemany('INSERT INTO faction_standings(character_id, faction, faction_id, value, '
                      'to_max, imported_at) VALUES(99,?,?,?,?,?)', [
                          ('Knights of Truth', 5001, 1000, 1000, 1005),   # +12 @1010, +3 @1020 after
                          ('Frogloks of Guk', 5002, -600, 2600, 1005),    # -10 @1000 BEFORE import
                          ('Deepwater Knights', 5004, 100, 1900, 1005),   # file only, no log
                      ])
    fv = factions.view(99)
    fx = {f['faction']: f for f in fv['factions']}
    check('fx: standing + label from the file', fx['Knights of Truth']['standing'] == 1000
          and fx['Knights of Truth']['standing_label'] == 'Warmly'   # 750..1099
          and fx['Knights of Truth']['to_max'] == 1000)
    check('fx: est_now = file + movement since import only',
          fx['Knights of Truth']['est_now'] == 1015
          and fx['Knights of Truth']['moved_since_import'] == 15
          and fx['Frogloks of Guk']['est_now'] == -600
          and fx['Frogloks of Guk']['moved_since_import'] == 0, fx['Frogloks of Guk'])
    check('fx: file-only faction listed', fx['Deepwater Knights']['events'] == 0
          and fx['Deepwater Knights']['standing_label'] == 'Amiable')
    check('fx: no standing without a file', fx['Ring of Scale']['standing'] is None
          and fx['Ring of Scale']['est_now'] is None)
    check('fx: totals + import stamp', fv['totals']['with_standing'] == 3
          and fv['standings_imported_at'] == 1005 and fv['notes']['standing_label'])

    # tradeskills view: known recipes joined to combines
    with db.tx() as c:
        c.execute('DELETE FROM known_recipes WHERE character_id=99')
        c.executemany('INSERT INTO known_recipes(character_id, skill, recipe_id, name, name_norm, '
                      'imported_at) VALUES(99,?,?,?,?,?)', [
                          ('Baking', 13475, 'Fish Rolls', 'fish rolls', 2000),
                          ('Baking', 77, 'Bat Wing Crunchies', 'bat wing crunchies', 2000),
                          ('Brewing', 78, 'Tumpy Tonic', 'tumpy tonic', 2000),
                      ])
    ts = tradeskills.view(99)
    baking = next(t for t in ts['tradeskills'] if t['skill'] == 'Baking')
    check('ts: known recipes per skill from the file', baking['known_recipes'] == 2
          and next(t for t in ts['tradeskills'] if t['skill'] == 'Pottery')['known_recipes'] is None)
    kn = {k['name']: k for k in ts['known_recipes']}
    check('ts: known recipes joined to combines', kn['Fish Rolls']['made'] == 3
          and kn['Fish Rolls']['attempts'] == 4 and kn['Bat Wing Crunchies']['attempts'] == 0)
    check('ts: known totals', ts['known_totals'] == {'recipes': 3, 'skills': 2, 'never_made': 1},
          ts['known_totals'])
    rec = {r['item']: r for r in ts['recipes']}
    check('ts: recipe rows flag membership in the file',
          rec['Fish Rolls']['known'] is True and rec['Glowing Shard']['known'] is False)
    characters.remove(cid)
    check('gf: remove clears file tables',
          db.query_one('SELECT COUNT(*) n FROM known_recipes WHERE character_id=?', (cid,))['n'] == 0
          and db.query_one('SELECT COUNT(*) n FROM faction_standings WHERE character_id=?',
                           (cid,))['n'] == 0)


def _inventory_view(check, db):
    """A dump with paired slots, a nested bag, a 10-slot bag, +N copies and
    trailing lists — imported through the real path, then read back through
    get_view / exaltation.view / ensure_current."""
    import tempfile
    from pathlib import Path
    from app import characters, exaltation, inventory, stats

    text = (
        'Location\tName\tID\tCount\tSlots\r\n'
        'Any Slot\tEfreeti War Spear +4\t20831\t1\t10\r\n'
        'Fingers\tRing of Pureblood +2\t1540\t1\t10\r\n'
        'Fingers-Slot7\tGlowing Shard (Exaltation)\t3\t1\t10\r\n'
        'Fingers\tEngineer`s Ring +3\t1545\t1\t10\r\n'
        'Fingers-Slot7\tSpare Fang (Exaltation)\t4\t1\t10\r\n'
        'Fingers-Slot8\tEmpty\t0\t0\t0\r\n'
        'Primary\tSwift Blade +2\t2\t1\t10\r\n'
        'Primary-Slot7\tEmpty\t0\t0\t0\r\n'
        'General 1\tKavruul`s Mystic Pouch\t17701\t1\t10\r\n'
        'General 1-Slot1\tSwift Blade +5\t2\t1\t10\r\n'
        'General 1-Slot1-Slot7\tEmpty\t0\t0\t0\r\n'
        'General 1-Slot2\tSwift Blade\t2\t1\t10\r\n'
        'General 1-Slot4\tEmpty\t0\t0\t0\r\n'
        'General 1-Slot7\tEmpty\t0\t0\t0\r\n'
        'Bank1\tStorage Trunk\t177752\t1\t50\r\n'
        'Bank1-Slot8\tLight Burlap Sack\t17353\t1\t8\r\n'
        'Bank1-Slot8-Slot1\tBone Chips\t13073\t20\t10\r\n'
        'Bank1-Slot8-Slot7\tEmpty\t0\t0\t0\r\n'
        'Bank1-Slot8-Slot8\tEmpty\t0\t0\t0\r\n'
        '\r\n'
        'KeyRing\tName\tID\t\r\n'
        'Augmentation\tEarthshaker (Exaltation)\t5667\r\n'
        'Equipment\tShield of the Stalwart Seas +5\t11552\r\n'
    )
    row = characters.add('InvView', 'test', None, None, activate=False)
    cid = row['id']
    with db.tx() as c:
        c.executemany('INSERT INTO upgrade_events(character_id, ts, item, item_norm, tier) '
                      'VALUES(?,?,?,?,?)', [
                          (cid, 900, 'Swift Blade +4', 'swift blade', 4),
                          (cid, 910, 'Swift Blade +5', 'swift blade', 5),
                          (cid, 920, 'Sprouting Heal II', 'sprouting heal ii', None),
                      ])
    res = inventory.import_bytes(cid, text.encode('utf-8'), source_path='view.txt')
    check('invview: imported', res['items'] == 14 and res['exaltations'] == 3, res)

    gv = inventory.get_view(cid)
    by_loc = {}
    for i in gv['items']:
        by_loc.setdefault(i['location'], []).append(i)
    check('invview: socket hosts resolve by row order (ring 1 / ring 2)',
          [i['host_name'] for i in by_loc['Fingers-Slot7']]
          == ['Ring of Pureblood +2', 'Engineer`s Ring +3'], by_loc.get('Fingers-Slot7'))
    check('invview: pocket vs socket labels',
          by_loc['General 1-Slot1'][0]['is_pocket'] is True
          and by_loc['Bank1-Slot8-Slot1'][0]['is_pocket'] is True
          and by_loc['Fingers-Slot7'][0]['is_pocket'] is False)
    opens = {s['location'] for s in gv['open_sockets']}
    check('invview: open sockets = real sockets only',
          opens == {'Fingers-Slot8', 'Primary-Slot7', 'General 1-Slot1-Slot7'}, opens)
    check('invview: open socket carries its host',
          next(s for s in gv['open_sockets'] if s['location'] == 'Fingers-Slot8')['host_name']
          == 'Engineer`s Ring +3')
    cont = {c['location']: c for c in gv['containers']}
    check('invview: containers incl. nested + 10-slot',
          set(cont) == {'General 1', 'Bank1', 'Bank1-Slot8'}
          and cont['Bank1-Slot8']['nested'] is True and cont['General 1']['nested'] is False, cont)
    check('invview: container used/free', cont['General 1']['used'] == 2
          and cont['General 1']['free'] == 8 and cont['Bank1-Slot8']['used'] == 1
          and cont['Bank1-Slot8']['free'] == 7 and cont['Bank1']['capacity'] == 50, cont)
    check('invview: space rollup', gv['space']['bags']['free'] == 8
          and gv['space']['bank']['bags'] == 2, gv['space'])
    lad = {g['name_norm']: g for g in gv['ladder']}
    sb = lad.get('swift blade')
    check('invview: ladder groups +N copies', sb and sb['worn_tier'] == 2 and sb['copies'] == 3
          and sb['tiers'] == [0, 2, 5] and sb['best_tier'] == 5
          and sb['upgrade_available'] is True, sb)
    check('invview: ladder skips singletons without tiers', 'bone chips' not in lad)
    check('invview: ladder carries merge history', sb['merges'] == 2 and sb['merge_max_tier'] == 5
          and sb['last_merge_ts'] == 910, sb)
    check('invview: merge history newest first incl. rank merges',
          [m['item'] for m in gv['merge_history']] == ['Sprouting Heal II', 'Swift Blade +5',
                                                       'Swift Blade +4']
          and gv['merge_history'][0]['tier'] is None
          and gv['merge_totals'] == {'merges': 3, 'items': 2}, gv['merge_totals'])
    check('invview: keyring lists', [i['name'] for i in gv['lists']['equipment']]
          == ['Shield of the Stalwart Seas +5'] and len(gv['lists']['augmentation']) == 1)
    check('invview: sections', by_loc['Any Slot'][0]['section'] == 'worn'
          and by_loc['Bank1-Slot8-Slot1'][0]['section'] == 'bank'
          and gv['lists']['equipment'][0]['section'] == 'lists')

    ex = exaltation.view(cid)
    hosts = {(e['item'], e['host_item']) for e in ex['socketed']}
    check('invview: exaltation hosts not shadowed by the paired slot',
          hosts == {('Glowing Shard (Exaltation)', 'Ring of Pureblood +2'),
                    ('Spare Fang (Exaltation)', 'Engineer`s Ring +3')}, hosts)
    check('invview: exaltation open sockets exclude nested pockets',
          {s['location'] for s in ex['open_sockets']}
          == {'Fingers-Slot8', 'Primary-Slot7', 'General 1-Slot1-Slot7'},
          [s['location'] for s in ex['open_sockets']])

    ov = stats.overview(cid)
    check('invview: Any Slot counted worn with a caveat',
          any('Any Slot' in c for c in ov['caveats']), ov['caveats'])

    # ensure_current: a stale-rev snapshot with the file still on disk re-imports
    tmp = Path(tempfile.mkdtemp(prefix='eqa-ensure-')) / 'InvView_test-Inventory.txt'
    tmp.write_text(text, encoding='utf-8')
    with db.tx() as c:
        c.execute('UPDATE characters SET inventory_path=? WHERE id=?', (str(tmp), cid))
        c.execute('UPDATE inventory_snapshots SET parse_rev=3 WHERE character_id=?', (cid,))
    snap = inventory.ensure_current(cid)
    check('invview: ensure_current re-imports a stale snapshot',
          snap and snap['parse_rev'] == inventory.PARSE_REV
          and snap['source_path'] == str(tmp), snap)
    n = db.query_one('SELECT COUNT(*) n FROM inventory_snapshots WHERE character_id=?', (cid,))['n']
    check('invview: ensure_current is a no-op once current',
          inventory.ensure_current(cid)['id'] == snap['id']
          and db.query_one('SELECT COUNT(*) n FROM inventory_snapshots WHERE character_id=?',
                           (cid,))['n'] == n)
    tmp.unlink()
    with db.tx() as c:
        c.execute('UPDATE inventory_snapshots SET parse_rev=3 WHERE character_id=?', (cid,))
    check('invview: ensure_current tolerates a missing file',
          inventory.ensure_current(cid)['parse_rev'] == 3)
    characters.remove(cid)


# Trimmed to the live shape of https://eqlwiki.com/Plane_of_Sky: a decoy row
# after the section's end heading, a bare-number source tag, a piped link with
# parentheses INSIDE the link, and a no-drop wrapper.
SKY_FIXTURE = """== Plane of Sky ==
intro text

== Plane of Sky Class Quests ==
These are the various class quests.

=== Quest Givers ===
find the '''[[Key Master]]''' and buy an [[Efreeti's Key]].

=== [[Paladin]] Tests ===

'''Quest Giver:''' [[Dason Goldblade]]

{| class="eoTable3"
|-
! Reward || Quest || Trigger Phrases || Rune || Quest Items
|-
| {{:Girdle of Faith}}
| Paladin Test of Spirit
| spirit
| <div class="checkbox-list eql-sky-table-checklist" style="margin:0; padding:0;">
<ul style="margin:0; padding-left:0;">
<li>[[Wind Rune Lena]]</li>
</ul>
</div>
| <div class="checkbox-list eql-sky-table-checklist" style="margin:0; padding:0;">
<ul style="margin:0; padding-left:0;">
<li>'''{{SkyNoDrop|[[Ivory Sky Diamond]]}}''' (5-SL)</li>
<li>[[Efreeti Zweihander]]</li>
</ul>
</div>
|-
| {{:Griffon Wing Spauldors}}
| Paladin Test of Love
| love
| <div class="checkbox-list"><ul>
<li>[[Wind Rune Lena]]</li>
</ul></div>
| <div class="checkbox-list"><ul>
<li>'''{{SkyNoDrop|[[Bixie Essence]]}}''' (6)</li>
</ul></div>
|}

=== [[Rogue]] Tests ===
'''Quest Giver:''' [[Thalik Silenthand]]

{| class="eoTable3"
|-
! Reward || Quest || Trigger Phrases || Rune || Quest Items
|-
| {{:Thornstinger}}
| Rogue Test of Deception
| deception
| <div class="checkbox-list"><ul>
<li>[[Wind Rune Jaka]]</li>
</ul></div>
| <div class="checkbox-list"><ul>
<li>'''{{SkyNoDrop|[[Bixie Stinger (Bixie God's Stinger)|Bixie Stinger]]}}''' (6-BZ)</li>
<li>'''{{SkyNoDrop|[[Bloodsky Sapphire]]}}''' (8-EoV)</li>
</ul></div>
|}

= Random Drop Items =
== Haste Belts ==
{| class="eoTable3"
|-
| {{:Not A Quest}}
| Decoy Test of Nothing
| nothing
| <li>[[Wind Rune Fake]]</li>
| <li>[[Fake Item]]</li>
|}
"""


def _skyquests(check, db):
    """Parser on the fixture, the bundled fallback, then a real dump through
    import_bytes read back through view()/set_done()."""
    from app import characters, inventory, skyquests, stats
    from app.quests import CLASSES

    qs = skyquests.parse_wikitext(SKY_FIXTURE)
    check('sky: parse count/classes (decoy after the section ignored)',
          [q['cls'] for q in qs] == ['Paladin', 'Paladin', 'Rogue'], [q['name'] for q in qs])
    check('sky: keys are name slugs, order is wiki order',
          [q['key'] for q in qs] == ['paladin-test-of-spirit', 'paladin-test-of-love',
                                     'rogue-test-of-deception']
          and [q['order'] for q in qs] == [0, 1, 2], qs and [q['key'] for q in qs])
    sp = qs[0] if qs else {}
    check('sky: giver / reward / phrase', sp.get('giver') == 'Dason Goldblade'
          and sp.get('reward', {}).get('name') == 'Girdle of Faith' and sp.get('phrase') == 'spirit', sp)
    check('sky: one rune, items with src + no_drop',
          [r['name'] for r in sp.get('runes', [])] == ['Wind Rune Lena']
          and [(i['name'], i['src'], i['no_drop']) for i in sp.get('items', [])]
          == [('Ivory Sky Diamond', '5-SL', True), ('Efreeti Zweihander', None, False)], sp.get('items'))
    check('sky: bare numeric src tag', len(qs) > 1 and qs[1]['items'][0]['src'] == '6', qs[1:2])
    bx = qs[2]['items'][0] if len(qs) > 2 else {}
    check('sky: piped link keeps the target, aliases both spellings',
          bx.get('name') == "Bixie Stinger (Bixie God's Stinger)" and bx.get('display') == 'Bixie Stinger'
          and bx.get('name_norms') == ['bixie stinger (bixie gods stinger)', 'bixie stinger']
          and bx.get('src') == '6-BZ' and bx.get('no_drop') is True, bx)
    check('sky: unrelated text parses to nothing', skyquests.parse_wikitext('== Foo ==\nbar\n') == [])
    check('sky: fixture is rejected as a full list', skyquests.valid(qs) is False)

    # bundled fallback: the scratch DB has no synced page
    db.execute('DELETE FROM raw_pages WHERE url=?', (skyquests.PAGE_URL,))
    skyquests._cache['stamp'] = None
    full, meta = skyquests.load_quests()
    keys = [q['key'] for q in full]
    check('sky: bundled list loads with no synced page', meta['kind'] == 'bundled'
          and meta['warning'] is None and len(full) >= skyquests.MIN_QUESTS, meta)
    check('sky: bundled list covers the 16 classes, unique keys, 1 rune + 1-3 items each',
          {q['cls'] for q in full} == set(CLASSES) and len(set(keys)) == len(keys)
          and all(len(q['runes']) == 1 and 1 <= len(q['items']) <= 3 for q in full))
    with db.tx() as c:
        c.execute('INSERT OR REPLACE INTO raw_pages(url, content, fetched_at) VALUES(?,?,?)',
                  (skyquests.PAGE_URL, SKY_FIXTURE, 1.0))
    skyquests._cache['stamp'] = None
    full2, meta2 = skyquests.load_quests()
    check('sky: a broken synced page falls back to bundled with a warning',
          meta2['kind'] == 'bundled' and '3 tests' in (meta2['warning'] or '') and len(full2) == len(full),
          meta2)
    db.execute('DELETE FROM raw_pages WHERE url=?', (skyquests.PAGE_URL,))
    skyquests._cache['stamp'] = None

    by_key = {q['key']: q for q in full}
    spirit = by_key.get('paladin-test-of-spirit')
    decep = by_key.get('rogue-test-of-deception')
    comp = by_key.get('paladin-test-of-compassion')
    check('sky: the bundled list has the three tests the checks below lean on',
          spirit is not None and decep is not None and comp is not None
          and spirit['reward']['name'] == 'Girdle of Faith' and decep['reward']['name'] == 'Thornstinger'
          and len(comp['items']) >= 2 and len(decep['items']) >= 2, (spirit, decep, comp))
    if not (spirit and decep and comp):
        return

    # a rune shared by other open tests, plus every item one of those needs
    rune_norm = spirit['runes'][0]['name_norm']
    sharers = [q for q in full if q['runes'][0]['name_norm'] == rune_norm
               and q['key'] not in ('paladin-test-of-spirit', 'rogue-test-of-deception')]
    other = sharers[0]
    spear_q = next((q for q in full if any('efreeti war spear' in it['name_norms'] for it in q['items'])), None)
    lines = ['Location\tName\tID\tCount\tSlots',
             'General 1\tBackpack\t17001\t1\t10',
             'General 1-Slot1\tGirdle of Faith\t1\t1\t10',                      # base reward -> auto done
             'Fingers\tRing of Test\t2\t1\t10',
             'Fingers-Slot7\tThornstinger (Exaltation)\t3\t1\t10',             # exaltation copy of a reward
             'Primary\t' + comp['items'][1]['name'] + ' +3\t4\t1\t10',         # +N-only turn-in copy
             'General 1-Slot2\t' + decep['items'][-1]['name'] + ' (Exaltation)\t5\t1\t10',  # exaltation turn-in
             'General 1-Slot3\t' + spirit['runes'][0]['name'] + '\t6\t1\t10',  # one shared rune
             ]
    for it in other['items']:
        lines.append('General 1-Slot4\t' + it['name'] + '\t7\t1\t10')
    lines.append('General 1-Slot5\t' + spirit['items'][0]['name'] + '\t8\t1\t10')
    tail = ['', 'KeyRing\tName\tID\t', 'Equipment\tEfreeti War Spear\t9']      # trailing list: never a turn-in
    text = '\r\n'.join(lines + tail) + '\r\n'
    row = characters.add('Sky', 'test', None, None, activate=False)
    cid = row['id']
    inventory.import_bytes(cid, text.encode('utf-8'), source_path='sky.txt')
    v = skyquests.view(cid)
    rows = {r['key']: r for r in v['quests']}
    sp, dp, ot = rows['paladin-test-of-spirit'], rows['rogue-test-of-deception'], rows[other['key']]
    check('sky: base reward in the dump -> done / auto / evidence base',
          sp['status'] == 'done' and sp['source'] == 'auto' and sp['reward']['evidence'] == 'base', sp['reward'])
    check('sky: an Exaltation copy of a reward still proves the hand-in',
          dp['status'] == 'done' and dp['reward']['evidence'] == 'exaltation', dp['reward'])
    need = {n['name_norm']: n for n in rows['paladin-test-of-compassion']['needs']}
    zwe = need[comp['items'][1]['name_norms'][0]]
    check('sky: a +N-only turn-in copy counts, flagged upgraded_only',
          zwe['ok'] is True and zwe['have'] == 1 and zwe['have_base'] == 0 and zwe['have_upgraded'] == 1
          and zwe['upgraded_only'] is True, zwe)
    dneed = {n['name_norm']: n for n in dp['needs']}
    sap = dneed[decep['items'][-1]['name_norms'][0]]
    check('sky: an Exaltation copy never satisfies a turn-in', sap['have'] == 0 and sap['ok'] is False, sap)
    if spear_q:
        sq = rows[spear_q['key']]
        spear = next(n for n in sq['needs'] if n['name_norm'] == 'efreeti war spear')
        check('sky: the trailing Equipment list never satisfies a turn-in', spear['have'] == 0, spear)
    rune = next(r for r in v['runes'] if r['name_norm'] == rune_norm)
    open_lena = sum(1 for r in v['quests'] if r['status'] == 'open'
                    and any(n['name_norm'] == rune_norm for n in r['needs']))
    check('sky: rune supply vs open demand', rune['supply'] == 1 and rune['demand_open'] == open_lena
          and rune['short'] == open_lena - 1 and open_lena >= 1, rune)
    on = next(n for n in ot['needs'] if n['name_norm'] == rune_norm)
    check('sky: the test with the rune and its items is ready + covered, rune flagged shared',
          ot['ready'] is True and ot['covered'] is True and on['ok'] is True
          and on['contended'] is (open_lena > 1), (ot['ready'], ot['covered'], on))
    check('sky: totals ready/covered', v['totals']['ready'] == 1 and v['totals']['covered'] == 1
          and v['totals']['done'] == 2 and v['totals']['total'] == len(full), v['totals'])
    # a second test sharing the same rune: both ready, only one covered, pinning decides which
    if len(sharers) > 1:
        second = sharers[1]
        lines2 = lines + ['General 1-Slot6\t' + it['name'] + '\t10\t1\t10' for it in second['items']]
        inventory.import_bytes(cid, ('\r\n'.join(lines2 + tail) + '\r\n').encode('utf-8'),
                               source_path='sky2.txt')
        v2 = skyquests.view(cid)
        r2 = {r['key']: r for r in v2['quests']}
        a, b = r2[other['key']], r2[second['key']]
        check('sky: two ready tests, one rune -> exactly one covered',
              a['ready'] and b['ready'] and (a['covered'] != b['covered'])
              and v2['totals']['ready'] == 2 and v2['totals']['covered'] == 1, (a['covered'], b['covered']))
        stats.set_manual(cid, 'class1', second['cls'])
        v3 = skyquests.view(cid)
        r3 = {r['key']: r for r in v3['quests']}
        check('sky: pinned class wins the shared rune',
              r3[second['key']]['covered'] is True and r3[second['key']]['pinned'] is True
              and v3['pinned_classes'] == [second['cls']]
              and v3['classes'][0]['name'] == second['cls'] and v3['classes'][0]['pinned'] is True,
              (v3['pinned_classes'], v3['classes'][0]))
        stats.set_manual(cid, 'class1', '')
    # manual marks
    skyquests.set_done(cid, 'paladin-test-of-love', True)
    skyquests.set_done(cid, 'paladin-test-of-spirit', False)
    v4 = {r['key']: r for r in skyquests.view(cid)['quests']}
    check('sky: manual done', v4['paladin-test-of-love']['status'] == 'done'
          and v4['paladin-test-of-love']['source'] == 'manual' and v4['paladin-test-of-love']['manual']['done'] == 1)
    check('sky: manual NOT-done beats the dump', v4['paladin-test-of-spirit']['status'] == 'open'
          and v4['paladin-test-of-spirit']['source'] == 'manual' and v4['paladin-test-of-spirit']['auto_done'] is True)
    skyquests.set_done(cid, 'paladin-test-of-spirit', None)
    v5 = skyquests.view(cid)
    v5q = {r['key']: r for r in v5['quests']}
    check('sky: clearing the mark returns to auto', v5q['paladin-test-of-spirit']['source'] == 'auto'
          and v5q['paladin-test-of-spirit']['status'] == 'done')
    try:
        skyquests.set_done(cid, 'not-a-test', True)
        check('sky: unknown key raises KeyError', False)
    except KeyError:
        check('sky: unknown key raises KeyError', True)
    pal = next(c for c in v5['classes'] if c['name'] == 'Paladin')
    pal_total = sum(1 for q in full if q['cls'] == 'Paladin')
    check('sky: per-class pct', pal['total'] == pal_total and pal['done'] == 2
          and pal['pct'] == round(200.0 / pal_total, 1), pal)
    check('sky: totals pct + 16 classes in order when nothing is pinned',
          v5['totals']['pct'] == round(100.0 * v5['totals']['done'] / len(full), 1)
          and [c['name'] for c in v5['classes']] == CLASSES and v5['totals']['manual'] == 1, v5['totals'])
    # no snapshot at all
    row2 = characters.add('SkyNone', 'test', None, None, activate=False)
    v6 = skyquests.view(row2['id'])
    check('sky: no dump -> snapshot null, nothing owned, nothing auto',
          v6['snapshot'] is None and v6['totals']['done'] == 0 and v6['totals']['ready'] == 0
          and all(n['have'] == 0 for r in v6['quests'] for n in r['needs']))
    skyquests.set_done(row2['id'], 'paladin-test-of-love', True)
    check('sky: manual marks work without a dump',
          skyquests.view(row2['id'])['totals']['done'] == 1)
    characters.remove(row2['id'])
    characters.remove(cid)
    check('sky: remove clears sky_quest_progress',
          db.query_one('SELECT COUNT(*) n FROM sky_quest_progress WHERE character_id IN (?,?)',
                       (cid, row2['id']))['n'] == 0)

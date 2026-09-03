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


def _gamefiles(check, db):
    """/outputfile faction + recipes: name parsing, tolerant parsers, imports,
    and the joins into the Factions / Tradeskills views."""
    from app import characters, factions, gamefiles, tradeskills

    p = gamefiles.parse_outputfile_name
    check('gf: inventory name', p('Cujef_halas-Inventory.txt')
          == {'name': 'Cujef', 'server': 'halas', 'kind': 'inventory', 'skill': None})
    check('gf: faction name + path', p('C:\\EQ\\Cujef_halas-Faction.txt')['kind'] == 'faction')
    check('gf: recipes name carries the skill',
          p('Cujef_halas-Baking-Recipes.txt') == {'name': 'Cujef', 'server': 'halas',
                                                    'kind': 'recipes', 'skill': 'Baking'})
    check('gf: recipes skill token mapped to the log name',
          p('Cujef_halas-Jewelcrafting-Recipes.txt')['skill'] == 'Jewelry Making'
          and p('Cujef_halas-Poisonmaking-Recipes.txt')['skill'] == 'Make Poison'
          and p('Cujef_halas-all-Recipes.txt')['skill'] == 'all'
          and p('cujef_halas-baking-recipes.TXT')['skill'] == 'Baking')
    check('gf: not an export', p('eqlog_Cujef_halas.txt') is None and p('notes.txt') is None)
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

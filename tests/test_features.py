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
    check('exalt: open socket on weapon', len(ex['open_sockets']) == 1
          and ex['open_sockets'][0]['host_item'] == 'Swift Blade'
          and ex['open_sockets'][0]['host_is_weapon'] is True, ex['open_sockets'])
    check('exalt: rules flagged assumed', ex['rules']['assumed'] is True)

    # ── tradeskills ──
    ts = tradeskills.view(99)
    baking = next(t for t in ts['tradeskills'] if t['skill'] == 'Baking')
    check('ts: baking level max', baking['level'] == 57)
    check('ts: unknown skill null',
          next(t for t in ts['tradeskills'] if t['skill'] == 'Pottery')['level'] is None)
    check('ts: other skills', any(s['skill'] == '1H Slashing' and s['level'] == 100
                                  for s in ts['other_skills']))

"""Core suites: vendored parser sanity, inventory dump parser, db, icons."""


def run(check):
    _vendor(check)
    _inventory(check)
    _db(check)
    _icons(check)


def _vendor(check):
    from vendor.eqlparser.parser import parse_line

    CASES = [
        # (line, expected-subset or None). Real lines from eqlog_Cujef_halas.txt.
        ('[Fri Jul 31 18:38:02 2026] You pierce a tormented dead for 11 points of damage.',
         {'type': 'damage', 'attacker': 'player', 'target': 'a tormented dead',
          'amount': 11, 'dmg_type': 'melee', 'verb': 'pierce'}),
        ('[Fri Jul 31 18:38:02 2026] A tormented dead slashes YOU for 4 points of damage.',
         {'type': 'damage_taken', 'amount': 4}),
        ('[Fri Jul 31 18:38:02 2026] You have become better at Conjuration! (75)',
         {'type': 'skill', 'skill': 'Conjuration', 'level': 75}),
        ('[Fri Jul 31 18:38:02 2026] A tormented dead has taken 32 damage from your Stinging Swarm.',
         {'type': 'damage', 'dmg_type': 'dot', 'spell': 'Stinging Swarm'}),
        ('[Fri Jul 31 18:37:55 2026] You begin casting Stinging Swarm.',
         {'type': 'cast', 'spell': 'Stinging Swarm'}),
        ('[Fri Jul 31 18:38:02 2026] Auto attack is on.',
         {'type': 'autoattack', 'on': True}),
        ('[Fri Jul 31 18:40:00 2026] You have slain a tormented dead!',
         {'type': 'kill', 'target': 'a tormented dead'}),
        ('[Fri Jul 31 18:40:00 2026] You have been slain by an undead brewer!',
         {'type': 'player_death', 'killer': 'an undead brewer'}),
        ('[Fri Jul 31 18:40:00 2026] You have entered West Freeport.',
         {'type': 'zone', 'zone': 'West Freeport'}),
        ('[Fri Jul 31 18:40:00 2026] You gain experience!',
         {'type': 'xp'}),
        ('[Fri Jul 31 18:40:00 2026] You have gained a level! Welcome to level 12!',
         {'type': 'level_up', 'level': 12}),
        ('[Fri Jul 31 18:40:00 2026] --You have looted a Rusty Dagger.--',
         {'type': 'loot'}),
        # trap lines that must NOT parse as anything alarming
        ('[Fri Jul 31 18:37:49 2026] Taibhse tells General2:2, \'I am an Erudite....\'', None),
        ('not a log line at all', None),
    ]
    for line, expect in CASES:
        ev = parse_line(line)
        if expect is None:
            ok = ev is None or ev.get('type') in ('emote_unknown', 'group_member_seen')
            check(f'vendor parse: {line[:60]!r} -> no event', ok, f'got {ev}')
        else:
            ok = ev is not None and all(ev.get(k) == v for k, v in expect.items())
            check(f'vendor parse: {line[:60]!r}', ok, f'got {ev}')


def _inventory(check):
    from app.inventory import normalize_name, parse_dump

    SAMPLE = (
        'Location\tName\tID\tCount\tSlots\n'
        'Face\tDarkbrood Mask +4\t1544\t1\t10\n'
        'Face-Slot7\tPolished Mithril Mask (Exaltation)\t4505\t1\t10\n'
        'Face-Slot8\tEmpty\t0\t0\t0\n'
        'General 8\tBackpack\t17005\t1\t8\n'
        'General 8-Slot1\tCeramic Mask +1\t20757\t1\t10\n'
        'General 8-Slot1-Slot7\tEmpty\t0\t0\t0\n'
        'Bank1\tLarge Bag\t17004\t1\t8\n'
        'Bank1-Slot2\tBone Chips\t13073\t20\t0\n'
        'Personal-Depot69\tPhosphorous Powder\t24082\t496\t10\n'
        '\n'
        'KeyRing\tName\tID\t\n'
        'Augmentation\tEarthshaker (Exaltation)\t5667\n'
        'Activated\tGuise of the Deceiver (Exaltation)\t2469\n'
    )
    rows = parse_dump(SAMPLE)
    check('inv: row count', len(rows) == 11, len(rows))
    by_loc = {r['location']: r for r in rows}
    face = by_loc['Face']
    check('inv: worn item equipped', face['is_equipped'] == 1)
    check('inv: upgrade tier', face['upgrade_tier'] == 4)
    check('inv: name_norm strips +N', face['name_norm'] == 'darkbrood mask')
    ex = by_loc['Face-Slot7']
    check('inv: exaltation flag', ex['is_exaltation'] == 1)
    check('inv: exaltation parent', ex['parent_location'] == 'Face' and ex['sub_slot'] == 7)
    check('inv: exaltation name_norm', ex['name_norm'] == 'polished mithril mask')
    check('inv: exaltation still equipped-root', ex['is_equipped'] == 1)
    deep = by_loc['General 8-Slot1-Slot7']
    check('inv: nested root', deep['root'] == 'General 8')
    check('inv: nested parent', deep['parent_location'] == 'General 8-Slot1')
    check('inv: bank not equipped', by_loc['Bank1-Slot2']['is_equipped'] == 0)
    check('inv: stack count', by_loc['Bank1-Slot2']['count'] == 20)
    check('inv: bag capacity', by_loc['General 8']['slots'] == 8)
    check('inv: norm idempotent',
          normalize_name('Efreeti War Spear +4') == 'efreeti war spear'
          and normalize_name('Efreeti  War Spear') == 'efreeti war spear')
    depot = by_loc['Personal-Depot69']
    check('inv: depot parent/root', depot['parent_location'] == 'Personal'
          and depot['root'] == 'Personal' and depot['sub_slot'] is None, depot)
    check('inv: depot stack', depot['count'] == 496)
    aug = by_loc['Augmentation']
    check('inv: 3-col augmentation row', aug['is_exaltation'] == 1
          and aug['count'] == 1 and aug['is_equipped'] == 0, aug)
    act = by_loc['Activated']
    check('inv: activated not worn', act['is_equipped'] == 0 and act['is_exaltation'] == 1)
    check('inv: sub-header skipped', 'KeyRing' not in by_loc)
    exalts = sum(1 for r in rows if r['is_exaltation'])
    check('inv: exaltation count', exalts == 3, exalts)
    try:
        parse_dump('garbage\nnope')
        check('inv: rejects non-dump', False)
    except ValueError:
        check('inv: rejects non-dump', True)


def _db(check):
    from app import db
    db.init()
    with db.tx() as c:
        c.execute("INSERT INTO characters(name, server, created_at) VALUES('T','test',0)")
    row = db.query_one("SELECT * FROM characters WHERE name='T'")
    check('db: insert/select round-trip', row is not None and row['server'] == 'test')
    with db.tx():
        db.execute("UPDATE characters SET server='test2' WHERE name='T'")
    row = db.query_one("SELECT server FROM characters WHERE name='T'")
    check('db: nested tx', row['server'] == 'test2')
    try:
        with db.tx() as c:
            c.execute("UPDATE characters SET server='test3' WHERE name='T'")
            raise RuntimeError('boom')
    except RuntimeError:
        pass
    row = db.query_one("SELECT server FROM characters WHERE name='T'")
    check('db: rollback on error', row['server'] == 'test2', row)


def _icons(check):
    from vendor.eqlparser.icons import sprite
    sp = sprite(507)
    check('icons: 507 -> sheet 1 cell 7 (40,40)',
          sp and sp['sheet'] == 1 and sp['x'] == 40 and sp['y'] == 40, sp)
    check('icons: below range', sprite(499) is None)
    check('icons: above range', sprite(14144) is None)
    check('icons: bool rejected', sprite(True) is None)

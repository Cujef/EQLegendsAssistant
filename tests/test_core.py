"""Core suites: vendored parser sanity, inventory dump parser, db, icons."""


def run(check):
    _version(check)
    _vendor(check)
    _inventory(check)
    _db(check)
    _icons(check)


def _version(check):
    """pyproject.toml and app.__version__ must never drift — the release check
    reads the manifest, the app reports the module."""
    import re
    from pathlib import Path

    import app
    root = Path(__file__).resolve().parent.parent
    text = (root / 'pyproject.toml').read_text(encoding='utf-8')
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    check('version: pyproject declares one', bool(m))
    if m:
        check('version: manifest matches app.__version__',
              m.group(1) == app.__version__, f'{m.group(1)} vs {app.__version__}')
    check('version: looks like semver',
          bool(re.fullmatch(r'\d+\.\d+\.\d+', app.__version__)), app.__version__)


def _vendor(check):
    from vendor.eqlparser.parser import parse_line

    CASES = [
        # (line, expected-subset or None). Real lines from a live EQ Legends log (eqlog_<Char>_<server>.txt).
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
        # v1.6.0 events (upstream's own fixtures): faction + tradeskills
        ('[Fri Jul 31 18:40:00 2026] Your faction standing with Frogloks of Guk has been adjusted by -5.',
         {'type': 'faction', 'faction': 'Frogloks of Guk', 'delta': -5}),
        ('[Fri Jul 31 18:40:00 2026] Your faction standing with Knights of Truth could not possibly get any better.',
         {'type': 'faction_capped', 'faction': 'Knights of Truth', 'direction': 'better'}),
        ('[Fri Jul 31 18:40:00 2026] You have fashioned the items together to create something new: Tumpy Tonic.',
         {'type': 'craft', 'item': 'Tumpy Tonic', 'ok': True}),
        ('[Fri Jul 31 18:40:00 2026] You lacked the skills to fashion Fish Rolls.',
         {'type': 'craft', 'item': 'Fish Rolls', 'ok': False}),
        ('[Fri Jul 31 18:40:00 2026] You can no longer advance your skill from making this item.',
         {'type': 'craft_capped'}),
        ('[Fri Jul 31 18:40:00 2026] Consumed 2 x Water Flask (leaving 7) from your personal depot.',
         {'type': 'depot_consume', 'qty': 2, 'item': 'Water Flask', 'left': 7}),
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

    # v1.6.0: a group member's miss and damage shield are events now (they were
    # dropped before), but only for names in the roster
    grp = {'Bob'}
    ev = parse_line('[Fri Jul 31 18:40:00 2026] Bob tries to slash a rat, but misses!',
                    group_members=grp)
    check('vendor parse: ally miss', ev is not None and ev['type'] == 'miss'
          and ev['attacker'] == 'Bob' and ev['outcome'] == 'miss', ev)
    ev = parse_line('[Fri Jul 31 18:40:00 2026] A rat is burned by Bob\'s thorns for 7 points of non-melee damage.',
                    group_members=grp)
    check('vendor parse: ally damage shield', ev is not None and ev['type'] == 'damage'
          and ev['attacker'] == 'Bob' and ev['dmg_type'] == 'ds' and ev['amount'] == 7, ev)
    ev = parse_line('[Fri Jul 31 18:40:00 2026] Stranger tries to slash a rat, but misses!',
                    group_members=grp)
    check('vendor parse: non-member miss ignored',
          ev is None or ev.get('type') in ('emote_unknown', 'group_member_seen'), ev)


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

    # ── PARSE_REV 4: row linkage + container detection, shaped like the live dump ──
    from app.inventory import PARSE_REV, is_container_location, parent_is_container
    check('inv: parse rev bumped for the linkage columns', PARSE_REV >= 4, PARSE_REV)
    SAMPLE2 = (
        'Location\tName\tID\tCount\tSlots\r\n'
        'Any Slot\tEfreeti War Spear +4\t20831\t1\t10\r\n'
        'Any Slot-Slot7\tEmpty\t0\t0\t0\r\n'
        # paired slots repeat their Location verbatim
        'Fingers\tRing of Pureblood +2\t1540\t1\t10\r\n'
        'Fingers-Slot7\tMoonstone Ring (Exaltation)\t10150\t1\t10\r\n'
        'Fingers\tEngineer`s Ring +3\t1545\t1\t10\r\n'
        'Fingers-Slot7\tDjarn`s Amethyst Ring (Exaltation)\t10366\t1\t10\r\n'
        'Fingers-Slot8\tEmpty\t0\t0\t0\r\n'
        # a 10-slot bag: Slots says 10 like any item, the pocket indices give it away
        'General 1\tKavruul`s Mystic Pouch\t17701\t1\t10\r\n'
        'General 1-Slot1\tFish Rolls\t13475\t99\t10\r\n'
        'General 1-Slot4\tEmpty\t0\t0\t0\r\n'
        'General 1-Slot7\tEmpty\t0\t0\t0\r\n'
        # a socketed ITEM parked in a general slot: children {2,7,8} -> not a bag
        'General 9\tEfreeti War Axe\t20711\t1\t10\r\n'
        'General 9-Slot2\tEmpty\t0\t0\t0\r\n'
        'General 9-Slot7\tEmpty\t0\t0\t0\r\n'
        'General 9-Slot8\tEmpty\t0\t0\t0\r\n'
        # a bag inside a bag: its pockets are pockets, not sockets
        'Bank12\tStorage Trunk\t177752\t1\t50\r\n'
        'Bank12-Slot1\tBracelet of Exertion +2\t12805\t1\t10\r\n'
        'Bank12-Slot1-Slot7\tEmpty\t0\t0\t0\r\n'
        'Bank12-Slot8\tLight Burlap Sack\t17353\t1\t8\r\n'
        'Bank12-Slot8-Slot7\tEmpty\t0\t0\t0\r\n'
        'Bank12-Slot8-Slot8\tEmpty\t0\t0\t0\r\n'
        'Personal-Depot69\tPhosphorous Powder\t24082\t496\t10\r\n'
        '\r\n'
        'KeyRing\tName\tID\t\r\n'
        'Augmentation\tEarthshaker (Exaltation)\t5667\r\n'
        'Equipment\tShield of the Stalwart Seas +5\t11552\r\n'
    )
    rows2 = parse_dump(SAMPLE2)
    by_seq = {r['seq']: r for r in rows2}
    check('inv2: seq is the row ordinal', [r['seq'] for r in rows2] == list(range(len(rows2))))
    fingers = [r for r in rows2 if r['location'] == 'Fingers']
    sockets = [r for r in rows2 if r['location'] == 'Fingers-Slot7']
    check('inv2: paired-slot sockets resolve to the nearest PRECEDING host',
          len(sockets) == 2
          and by_seq[sockets[0]['parent_seq']]['name'] == 'Ring of Pureblood +2'
          and by_seq[sockets[1]['parent_seq']]['name'] == 'Engineer`s Ring +3',
          [(s['parent_seq'], by_seq[s['parent_seq']]['name']) for s in sockets])
    check('inv2: two Fingers rows both worn', len(fingers) == 2
          and all(r['is_equipped'] for r in fingers))
    anyslot = next(r for r in rows2 if r['location'] == 'Any Slot')
    check('inv2: Any Slot counts as worn', anyslot['is_equipped'] == 1)
    check('inv2: backtick apostrophe normalized away',
          normalize_name('Kavruul`s Mystic Pouch') == 'kavruuls mystic pouch'
          and normalize_name('Engineer`s Ring +3') == normalize_name("Engineer's Ring"))
    pocket10 = next(r for r in rows2 if r['location'] == 'General 1-Slot7')
    check('inv2: 10-slot bag detected via a pocket index a socket never uses',
          pocket10['parent_is_container'] == 1, pocket10)
    axe_sock = next(r for r in rows2 if r['location'] == 'General 9-Slot7')
    check('inv2: socketed item in a general slot is NOT a bag',
          axe_sock['parent_is_container'] == 0, axe_sock)
    nested = next(r for r in rows2 if r['location'] == 'Bank12-Slot8-Slot7')
    check('inv2: nested bag pocket flagged as pocket',
          nested['parent_is_container'] == 1 and parent_is_container(nested), nested)
    check('inv2: legacy rule misses the nested bag (why the flag exists)',
          is_container_location('Bank12-Slot8') is False)
    inner_sock = next(r for r in rows2 if r['location'] == 'Bank12-Slot1-Slot7')
    check('inv2: socket on a bagged item stays a socket',
          inner_sock['parent_is_container'] == 0
          and by_seq[inner_sock['parent_seq']]['name'] == 'Bracelet of Exertion +2')
    trunk_pocket = next(r for r in rows2 if r['location'] == 'Bank12-Slot8')
    check('inv2: nested bag itself is a pocket of the trunk',
          trunk_pocket['parent_is_container'] == 1
          and by_seq[trunk_pocket['parent_seq']]['name'] == 'Storage Trunk')
    depot2 = next(r for r in rows2 if r['location'] == 'Personal-Depot69')
    check('inv2: depot row has no host row', depot2['parent_seq'] is None
          and depot2['parent_location'] == 'Personal')
    eq = next(r for r in rows2 if r['root'] == 'Equipment')
    check('inv2: trailing Equipment row parsed, not worn, no parent',
          eq['is_equipped'] == 0 and eq['parent_seq'] is None and eq['upgrade_tier'] == 5, eq)
    check('inv2: legacy fallback used when the flag is NULL',
          parent_is_container({'parent_is_container': None, 'parent_location': 'Bank1'}) is True
          and parent_is_container({'parent_is_container': None, 'parent_location': 'Face'}) is False)


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
    # lock-leak regression: a failing BEGIN inside __enter__ must release the
    # write lock, or every writer in the app deadlocks forever
    class _Boom:
        def execute(self, *a):
            raise RuntimeError('boom')
    real = db._conn
    db._conn = _Boom()
    try:
        with db.tx():
            pass
        check('db: tx enter failure raises', False)
    except RuntimeError:
        pass
    finally:
        db._conn = real
    got_lock = db._write_lock.acquire(timeout=1)
    if got_lock:
        db._write_lock.release()
    check('db: lock released after enter failure', got_lock)


def _icons(check):
    from vendor.eqlparser.icons import sprite
    sp = sprite(507)
    check('icons: 507 -> sheet 1 cell 7 (40,40)',
          sp and sp['sheet'] == 1 and sp['x'] == 40 and sp['y'] == 40, sp)
    check('icons: below range', sprite(499) is None)
    check('icons: above range', sprite(14144) is None)
    check('icons: bool rejected', sprite(True) is None)

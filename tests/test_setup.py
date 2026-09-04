"""First-run setup: folder scan, character add/remove, and player naming."""
import tempfile
from pathlib import Path


def run(check):
    from app import db
    db.init()          # idempotent; suites must stand alone (`selftest.py setup`)
    _naming(check)
    _scan(check)
    _crud(check)
    _inventory_bytes(check)
    _origin_guard(check)
    _filename_and_readiness(check)
    _char_tables(check)


def _filename_and_readiness(check):
    from app import characters, db, inventory

    p = characters.parse_inventory_filename
    check('invname: plain', p('Fizzwick_halas-Inventory.txt') == ('Fizzwick', 'halas'))
    check('invname: windows path', p('C:\\Games\\EQ\\Fizzwick_halas-Inventory.txt') == ('Fizzwick', 'halas'))
    check('invname: posix path + case', p('/tmp/fizzwick_HALAS-inventory.TXT') == ('fizzwick', 'HALAS'))
    check('invname: not a dump name', p('inventory.txt') is None and p('eqlog_Fizzwick_halas.txt') is None
          and p('') is None and p(None) is None)

    check('readiness: none without a character', characters.readiness(None) is None)
    row = characters.add('Ready', 'srv', None, None, activate=False)
    r = characters.readiness(row)
    check('readiness: fresh character', r['inventory_imported_at'] is None
          and r['log_path_set'] is False and r['log_lines_parsed'] == 0
          and isinstance(r['items_in_db'], int) and r['auto_import'] == {'enabled': True}, r)
    inventory.import_bytes(row['id'], b'Location\tName\tID\tCount\tSlots\nHead\tCap\t1\t1\t10\n',
                           source_path='x.txt')
    with db.tx() as c:
        c.execute("INSERT OR REPLACE INTO highlights(character_id, key, value_num) "
                  "VALUES(?, 'lines_parsed', 1234)", (row['id'],))
    r = characters.readiness(row)
    check('readiness: reflects an import and parsed lines',
          r['inventory_imported_at'] is not None and r['log_lines_parsed'] == 1234, r)
    characters.remove(row['id'])


def _char_tables(check):
    """Every character-keyed table must be on the removal list, or remove()
    leaks rows — pinned by reading the live schema, not a hand-kept list."""
    from app import characters, db
    db.init()
    conn = db.reader()
    try:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        keyed = []
        for t in tables:
            cols = [c[1] for c in conn.execute(f'PRAGMA table_info({t})').fetchall()]
            if 'character_id' in cols:
                keyed.append(t)
    finally:
        conn.close()
    # inventory_snapshots is cleared explicitly (its items hang off snapshot_id)
    missing = [t for t in keyed if t not in characters._CHAR_TABLES
               and t != 'inventory_snapshots']
    check('char tables: removal list covers every character-keyed table', not missing, missing)
    check('char tables: new v1.1/v1.2 tables present',
          {'craft_events', 'craft_caps', 'craft_recipe_skill', 'depot_events', 'faction_events',
           'faction_caps', 'upgrade_events', 'faction_standings', 'known_recipes',
           'export_files', 'zone_stats', 'zone_events', 'loot_events'} <= set(keyed), keyed)

    # and remove() really empties them
    row = characters.add('Wipe', 'srv', None, None, activate=False)
    cid = row['id']
    with db.tx() as c:
        c.execute("INSERT INTO craft_events(character_id, ts, item, item_norm, ok) "
                  "VALUES(?,1,'X','x',1)", (cid,))
        c.execute("INSERT INTO craft_caps(character_id, item, first_ts, last_ts) VALUES(?,'X',1,1)",
                  (cid,))
        c.execute("INSERT INTO craft_recipe_skill(character_id, item, skill) VALUES(?,'X','Baking')",
                  (cid,))
        c.execute("INSERT INTO depot_events(character_id, ts, kind, item, item_norm, qty) "
                  "VALUES(?,1,'consume','Y','y',1)", (cid,))
        c.execute("INSERT INTO faction_events(character_id, ts, faction, delta) VALUES(?,1,'F',1)",
                  (cid,))
        c.execute("INSERT INTO faction_caps(character_id, faction, direction, first_ts, last_ts) "
                  "VALUES(?,'F','better',1,1)", (cid,))
        c.execute("INSERT INTO upgrade_events(character_id, ts, item, item_norm, tier) "
                  "VALUES(?,1,'X +1','x',1)", (cid,))
    characters.remove(cid)
    for t in ('craft_events', 'craft_caps', 'craft_recipe_skill', 'depot_events',
              'faction_events', 'faction_caps', 'upgrade_events'):
        n = db.query_one(f'SELECT COUNT(*) n FROM {t} WHERE character_id=?', (cid,))['n']
        check(f'remove: {t} cleaned', n == 0, n)


def _origin_guard(check):
    """The app has no auth by design; the only thing standing between a random
    open tab and its file-reading POST endpoints is the Origin check."""
    from app.server import is_local_origin

    for ok in ('', 'http://127.0.0.1:8766', 'http://localhost:8766',
               'https://localhost', 'http://[::1]:8766'):
        check(f'origin: allows {ok or "(none)"}', is_local_origin(ok) is True, ok)
    for bad in ('http://evil.com', 'https://evil.com:8766', 'http://127.0.0.1.evil.com',
                'http://notlocalhost', 'null'):
        check(f'origin: refuses {bad}', is_local_origin(bad) is False, bad)


def _naming(check):
    from app import naming

    fight = {
        'name': 'a bear',
        'damage': {'player': {'total': 100, 'dps': 5.0}, 'pet': {'total': 20}},
        'healing': {'player': {'total': 30}},
        'tanking': {'a bear': {'total': 50, 'by_victim': {'player': 40, 'pet': 10}}},
        'hits': [{'actor': 'player', 'tgt': 'a bear'}, {'actor': 'a bear', 'tgt': 'player'}],
        'offense': {'actors': {'player': {'swings': 9}}, 'verbs': {'player': {}}},
    }
    naming.humanize_fight(fight, 'Fizzwick')
    check('naming: damage key renamed',
          'Fizzwick' in fight['damage'] and 'player' not in fight['damage'])
    check('naming: other actors untouched', fight['damage']['pet']['total'] == 20)
    check('naming: healing renamed', 'Fizzwick' in fight['healing'])
    check('naming: by_victim renamed',
          fight['tanking']['a bear']['by_victim'].get('Fizzwick') == 40)
    check('naming: hit actor renamed', fight['hits'][0]['actor'] == 'Fizzwick')
    check('naming: hit target renamed', fight['hits'][1]['tgt'] == 'Fizzwick')
    check('naming: offense renamed', 'Fizzwick' in fight['offense']['actors'])

    # a missing/blank name must be a no-op, never a crash or a 'None' actor
    plain = {'damage': {'player': {'total': 1}}}
    naming.humanize_fight(plain, None)
    check('naming: no name is a no-op', 'player' in plain['damage'])
    check('naming: None fight tolerated', naming.humanize_fight(None, 'X') is None)

    live = {'active_fight': {'damage': {'player': {'total': 5}}},
            'fights': [{'damage': {'player': {'total': 7}}}]}
    naming.humanize_live(live, 'Zeb')
    check('naming: live active fight', 'Zeb' in live['active_fight']['damage'])
    check('naming: live history fights', 'Zeb' in live['fights'][0]['damage'])
    check('naming: live carries player_name', live['player_name'] == 'Zeb')


def _scan(check):
    from app import characters

    root = Path(tempfile.mkdtemp(prefix='eqa-scan-'))
    (root / 'Logs').mkdir()
    (root / '_characters.ini').write_text(
        '[Characters]\nCharacter0=Foo,halas\nCharacter1=Bar,qeynos\n', encoding='utf-8')
    (root / 'Logs' / 'eqlog_Foo_halas.txt').write_text('x' * 100, encoding='utf-8')
    (root / 'Foo_halas-Inventory.txt').write_text('Location\tName\tID\tCount\tSlots\n',
                                                  encoding='utf-8')
    # a log with no ini entry must still be discovered
    (root / 'Logs' / 'eqlog_Solo_vox.txt').write_text('y', encoding='utf-8')
    # the other exports, plus an alt known only from a dump
    (root / 'Foo_halas-PAL-Factions.txt').write_text('ID\tName\tStandingValue\tPointsToMax\n',
                                                     encoding='utf-8')
    (root / 'Foo_halas-Baking-Recipes.txt').write_text('1\tFish Rolls\n', encoding='utf-8')
    (root / 'Foo_halas-Jewelcrafting-Recipes.txt').write_text('2\tRing\n', encoding='utf-8')
    (root / 'Alt_halas-Inventory.txt').write_text('Location\tName\tID\tCount\tSlots\n',
                                                  encoding='utf-8')

    res = characters.scan(root)
    by = {c['name']: c for c in res['candidates']}
    check('scan: finds ini + log-only + export-only characters',
          set(by) == {'Foo', 'Bar', 'Solo', 'Alt'}, list(by))
    check('scan: log path + size', by['Foo']['log_path'] and by['Foo']['log_size'] == 100)
    check('scan: inventory found', bool(by['Foo']['inventory_path']))
    check('scan: missing log reported as None', by['Bar']['log_path'] is None)
    check('scan: no duplicate for ini+log character',
          sum(1 for c in res['candidates'] if c['name'] == 'Foo') == 1)
    check('scan: dirs reported', res['game_dir_exists'] and res['logs_dir_exists'])
    kinds = [(e['kind'], e['skill']) for e in by['Foo']['exports']]
    check('scan: exports listed per candidate (sorted by kind, skill)',
          kinds == [('faction', None), ('inventory', None), ('recipes', 'Baking'),
                    ('recipes', 'Jewelry Making')], kinds)
    check('scan: export-only alt has no log but an inventory export',
          by['Alt']['log_path'] is None and by['Alt']['inventory_path']
          and [e['kind'] for e in by['Alt']['exports']] == ['inventory'])
    check('scan: candidate without exports reports an empty list', by['Bar']['exports'] == [])

    # pointing at the Logs folder itself must work as well as the install root
    res2 = characters.scan(root / 'Logs')
    check('scan: accepts the Logs folder',
          {c['name'] for c in res2['candidates']} == {'Foo', 'Bar', 'Solo', 'Alt'})
    check('scan: resolves game dir from Logs', res2['game_dir'] == str(root))

    missing = characters.scan(root / 'nope')
    check('scan: missing folder is reported, not raised',
          missing['candidates'] == [] and not missing['game_dir_exists'])


def _crud(check):
    from app import characters, db

    root = Path(tempfile.mkdtemp(prefix='eqa-crud-'))
    log = root / 'eqlog_Test_srv.txt'
    log.write_text('[Fri Jul 31 18:37:48 2026] Welcome to EverQuest Legends!\n',
                   encoding='utf-8')

    row = characters.add('Test', 'srv', str(log), None)
    check('add: stored + activated', row and row['is_active'] == 1 and row['name'] == 'Test')
    check('add: log path kept', row['log_path'] == str(log))
    check('add: no inventory stays NULL (not empty string)', row['inventory_path'] is None)
    check('needs_setup false with a log', characters.needs_setup() is False)

    # re-adding must not wipe the known log path with a blank one
    again = characters.add('Test', 'srv', None, None)
    check('add: re-add preserves paths', again['log_path'] == str(log))

    try:
        characters.add('', 'srv', None, None)
        check('add: blank name rejected', False)
    except ValueError:
        check('add: blank name rejected', True)
    try:
        characters.add('Ghost', 'srv', str(root / 'nope.txt'), None)
        check('add: missing log file rejected', False)
    except ValueError:
        check('add: missing log file rejected', True)

    # removal takes the derived rows with it
    cid = row['id']
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO deaths(character_id, ts, killer) VALUES(?,1,'x')", (cid,))
        c.execute("INSERT OR IGNORE INTO skill_levels(character_id, skill, level, ts) "
                  "VALUES(?,'Baking',10,1)", (cid,))
        cur = c.execute('INSERT INTO inventory_snapshots(character_id, imported_at, parse_rev) '
                        'VALUES(?,1,3)', (cid,))
        c.execute('INSERT INTO inventory_items(snapshot_id, location, root, name, name_norm, '
                  'item_id, count, slots, is_empty, is_exaltation, is_equipped) '
                  "VALUES(?,'Head','Head','H','h',1,1,0,0,0,1)", (cur.lastrowid,))
    characters.remove(cid)
    check('remove: character gone', characters.get(cid) is None)
    for table in ('deaths', 'skill_levels', 'inventory_snapshots'):
        n = db.query_one(f'SELECT COUNT(*) n FROM {table} WHERE character_id=?', (cid,))['n']
        check(f'remove: {table} cleaned', n == 0, n)
    orphans = db.query_one(
        'SELECT COUNT(*) n FROM inventory_items WHERE snapshot_id NOT IN '
        '(SELECT id FROM inventory_snapshots)')['n']
    check('remove: no orphan inventory rows', orphans == 0, orphans)


def _inventory_bytes(check):
    from app import characters, db, inventory

    row = characters.add('Upload', 'srv', None, None)
    text = ('Location\tName\tID\tCount\tSlots\n'
            'Head\tIron Helm\t1\t1\t10\n'
            'Head-Slot7\tShard (Exaltation)\t2\t1\t10\n')
    res = inventory.import_bytes(row['id'], text.encode('utf-8'), source_path='picked.txt')
    check('upload: rows imported', res['items'] == 2 and res['exaltations'] == 1, res)
    snap = inventory.latest_snapshot(row['id'])
    check('upload: source path recorded', snap['source_path'] == 'picked.txt')
    check('upload: mtime tolerated as NULL', snap['file_mtime'] is None)
    check('upload: same content is a no-op re-import',
          inventory.import_bytes(row['id'], text.encode('utf-8'),
                                 source_path='picked.txt')['unchanged'] is True)
    characters.remove(row['id'])

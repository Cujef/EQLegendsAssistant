"""First-run setup: folder scan, character add/remove, and player naming."""
import tempfile
from pathlib import Path


def run(check):
    _naming(check)
    _scan(check)
    _crud(check)
    _inventory_bytes(check)


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
    naming.humanize_fight(fight, 'Cujef')
    check('naming: damage key renamed',
          'Cujef' in fight['damage'] and 'player' not in fight['damage'])
    check('naming: other actors untouched', fight['damage']['pet']['total'] == 20)
    check('naming: healing renamed', 'Cujef' in fight['healing'])
    check('naming: by_victim renamed',
          fight['tanking']['a bear']['by_victim'].get('Cujef') == 40)
    check('naming: hit actor renamed', fight['hits'][0]['actor'] == 'Cujef')
    check('naming: hit target renamed', fight['hits'][1]['tgt'] == 'Cujef')
    check('naming: offense renamed', 'Cujef' in fight['offense']['actors'])

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

    res = characters.scan(root)
    by = {c['name']: c for c in res['candidates']}
    check('scan: finds ini + log-only characters', set(by) == {'Foo', 'Bar', 'Solo'}, list(by))
    check('scan: log path + size', by['Foo']['log_path'] and by['Foo']['log_size'] == 100)
    check('scan: inventory found', bool(by['Foo']['inventory_path']))
    check('scan: missing log reported as None', by['Bar']['log_path'] is None)
    check('scan: no duplicate for ini+log character',
          sum(1 for c in res['candidates'] if c['name'] == 'Foo') == 1)
    check('scan: dirs reported', res['game_dir_exists'] and res['logs_dir_exists'])

    # pointing at the Logs folder itself must work as well as the install root
    res2 = characters.scan(root / 'Logs')
    check('scan: accepts the Logs folder',
          {c['name'] for c in res2['candidates']} == {'Foo', 'Bar', 'Solo'})
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

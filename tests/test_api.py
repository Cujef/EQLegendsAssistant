"""HTTP-level suite: the FastAPI routes through fastapi.testclient.

TestClient(app) WITHOUT the context manager runs no lifespan, so no tailer or
watcher thread starts; the suite calls db.init() itself. Needs httpx (an
optional dependency): without it the suite prints one SKIP line and counts
nothing rather than failing the gate.
"""
import os
import tempfile
from pathlib import Path


def run(check):
    try:
        import httpx  # noqa: F401
        from fastapi.testclient import TestClient
    except ImportError:
        print('  SKIP api: httpx not installed (pip install httpx) — 0 checks')
        return
    import app as app_pkg
    from app import characters, config, db, inventory
    from app.server import app

    db.init()
    client = TestClient(app)
    # activate=True: with no active character at all, a detected import would
    # (by design) activate the character it creates — this suite runs first
    row = characters.add('Api', 'test', None, None, activate=True)
    cid = row['id']
    q = f'?char={cid}'
    with db.tx() as c:
        c.executemany('INSERT INTO zone_stats(character_id, zone, seconds, kills, xp_pct, loot, visits, '
                      'first_ts, last_ts) VALUES(?,?,?,?,?,?,?,?,?)', [
                          (cid, 'Najena', 7200, 40, 12.5, 9, 3, 1000, 9000),
                          (cid, 'Blackburrow', 120, 1, 0.2, 0, 1, 500, 620)])
        c.executemany('INSERT INTO loot_events(character_id, ts, item, item_norm, source, qty, zone) '
                      'VALUES(?,?,?,?,?,?,?)', [
                          (cid, 1000, 'Rusty Dagger', 'rusty dagger', 'a gnoll', 1, 'Blackburrow'),
                          (cid, 1001, 'Rusty Dagger', 'rusty dagger', 'a gnoll', 1, 'Blackburrow'),
                          (cid, 1002, 'Spider Silk', 'spider silk', 'a spider', 2, 'Najena')])
        c.execute('INSERT INTO upgrade_events(character_id, ts, item, item_norm, tier) '
                  "VALUES(?, 2000, 'Ring +2', 'ring', 2)", (cid,))
    inventory.import_bytes(cid, b'Location\tName\tID\tCount\tSlots\nHead\tIron Helm\t1\t1\t10\n',
                           source_path='api.txt')

    r = client.get('/api/health')
    check('api: health reports the version', r.status_code == 200
          and r.json()['version'] == app_pkg.__version__, r.text[:120])
    r = client.get('/api/characters')
    ready = r.json().get('readiness')
    check('api: characters carries readiness incl. auto_import',
          r.status_code == 200 and (ready is None or ready['auto_import'] == {'enabled': True}), r.text[:200])

    # generic import: active target, detected target, bad kind, bad target, missing path
    fac = 'ID\tName\tStandingValue\tPointsToMax\r\n65\tBrownies of Faydwer\t0\t2000\r\n'
    r = client.post('/api/import' + q, json={'content': fac, 'filename': 'Api_test-PAL-Factions.txt'})
    check('api: import faction for the active target', r.status_code == 200
          and r.json()['kind'] == 'faction' and r.json()['rows'] == 1
          and r.json()['character']['id'] == cid and r.json()['mismatch'] is False, r.text[:200])
    r = client.post('/api/import' + q, json={'content': fac, 'filename': 'NewApi_test-PAL-Factions.txt',
                                             'target': 'detected', 'activate': False})
    created = characters.list_all()
    new = next((c for c in created if c['name'] == 'NewApi'), None)
    check('api: detected target creates the character without activating', r.status_code == 200
          and new is not None and not new['is_active'] and r.json()['character']['name'] == 'NewApi', r.text[:200])
    r = client.post('/api/import' + q, json={'content': 'hello\nworld\n', 'filename': 'notes.txt'})
    check('api: unrecognised content -> 422', r.status_code == 422, r.text[:200])
    r = client.post('/api/import' + q, json={'content': fac, 'filename': 'x.txt', 'target': 'bogus'})
    check('api: bad target -> 422', r.status_code == 422)
    r = client.post('/api/import' + q, json={'path': 'C:/definitely/not/here.txt'})
    check('api: missing path -> 404', r.status_code == 404, r.text[:200])
    r = client.post('/api/inventory/import' + q, json={})
    check('api: inventory re-read with no stored path -> 404 with the hint',
          r.status_code == 404 and 'outputfile inventory' in r.json()['detail'], r.text[:200])

    # same-origin guard: only non-GET from a foreign Origin is refused
    r = client.post('/api/inventory/import' + q, json={}, headers={'Origin': 'http://evil.com'})
    check('api: foreign-origin POST -> 403', r.status_code == 403, r.status_code)
    r = client.post('/api/inventory/import' + q, json={}, headers={'Origin': 'http://127.0.0.1:8766'})
    check('api: loopback-origin POST passes the guard', r.status_code == 404, r.status_code)
    r = client.get('/api/health', headers={'Origin': 'http://evil.com'})
    check('api: GET is not origin-gated', r.status_code == 200)

    # export
    r = client.get('/api/export/zones' + q + '&fmt=csv')
    body = r.content
    check('api: csv export is BOM + CRLF + header', r.status_code == 200
          and body.startswith('\ufeff'.encode('utf-8')) and b'\r\n' in body
          and body.decode('utf-8').lstrip('\ufeff').split('\r\n')[0].startswith('Zone,Active hours')
          and r.headers['content-type'].startswith('text/csv'), body[:80])
    check('api: csv export names the file after the character',
          'Api_test-zones-' in r.headers.get('content-disposition', '') and '.csv' in r.headers['content-disposition'])
    check('api: csv export has one row per zone', body.decode('utf-8').count('\r\n') == 3, body)
    r = client.get('/api/export/loot' + q + '&fmt=json')
    js = r.json()
    check('api: json export is a list of rows with the flattened source',
          r.status_code == 200 and isinstance(js, list) and len(js) == 2
          and js[0]['item'] == 'Rusty Dagger' and js[0]['top_source'] == 'a gnoll'
          and js[0]['top_zone'] == 'Blackburrow', js)
    check('api: every export view renders for this character',
          all(client.get(f'/api/export/{v}{q}').status_code == 200
              for v in ('inventory', 'merges', 'recipes', 'materials', 'known_recipes', 'factions',
                        'fights', 'loot', 'zones')))
    check('api: unknown export view -> 404', client.get('/api/export/nope' + q).status_code == 404)
    check('api: bad export fmt -> 422', client.get('/api/export/zones' + q + '&fmt=xml').status_code == 422)

    # zones + loot
    r = client.get('/api/zones' + q)
    z = {x['zone']: x for x in r.json()['zones']}
    check('api: zones view math', r.status_code == 200 and z['Najena']['hours'] == 2.0
          and z['Najena']['kills_per_hour'] == 20.0 and z['Najena']['xp_per_hour'] == 6.25
          and z['Blackburrow']['kills_per_hour'] is None   # under 0.1 h
          and r.json()['totals']['kills'] == 41, r.json())
    r = client.get('/api/loot' + q + '&q=rusty')
    check('api: loot search groups and filters', r.status_code == 200 and len(r.json()['items']) == 1
          and r.json()['items'][0]['count'] == 2 and r.json()['items'][0]['sources'][0]['n'] == 2
          and r.json()['total_events'] == 3, r.json())

    # exports watcher through the route, against a temp game dir
    tmp = Path(tempfile.mkdtemp(prefix='eqa-api-'))
    p = tmp / 'Api_test-Inventory.txt'
    p.write_text('Location\tName\tID\tCount\tSlots\nHead\tSteel Helm\t5\t1\t10\n', encoding='utf-8')
    old = os.path.getmtime(str(p)) - 30
    os.utime(p, (old, old))
    saved = config.GAME_DIR
    config.GAME_DIR = tmp
    try:
        r = client.post('/api/exports/rescan')
        check('api: rescan imports the file found in the game dir', r.status_code == 200
              and any(x['character'] == 'Api' and x['kind'] == 'inventory' for x in r.json()['imported']),
              r.json())
        r2 = client.post('/api/exports/rescan')
        check('api: second rescan finds nothing new',
              not [x for x in r2.json()['imported'] if x['character'] == 'Api'], r2.json())
        r = client.get('/api/exports' + q)
        check('api: /api/exports lists the watched file with its status', r.status_code == 200
              and any(f['status'] == 'imported' for f in r.json()['files'])
              and 'last_check' in r.json()['watcher'], r.json())
    finally:
        config.GAME_DIR = saved
    check('api: rescan wrote the snapshot', inventory.get_view(cid)['items'][0]['name'] == 'Steel Helm')

    characters.remove(cid)
    if new:
        characters.remove(new['id'])

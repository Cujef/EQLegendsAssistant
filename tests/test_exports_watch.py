"""Auto-pickup of /outputfile exports: discovery, the watcher pass, its
settle / unchanged / error rules, and cleanup on character removal."""
import os
import tempfile
import time
from pathlib import Path


def run(check):
    from app import characters, db, exports_watch, gamefiles, inventory, state
    db.init()

    tmp = Path(tempfile.mkdtemp(prefix='eqa-watch-'))
    old = time.time() - 60

    def write(p: Path, text: str, mtime=old):
        p.write_bytes(text.encode('utf-8'))      # no newline translation: sizes must match len()
        os.utime(p, (mtime, mtime))

    INV1 = 'Location\tName\tID\tCount\tSlots\nHead\tCap\t1\t1\t10\n'
    INV2 = 'Location\tName\tID\tCount\tSlots\nHead\tHelm\t2\t1\t10\nFace\tMask\t3\t1\t10\n'
    FAC = 'ID\tName\tStandingValue\tPointsToMax\r\n65\tBrownies of Faydwer\t0\t2000\r\n'
    inv = tmp / 'Watch_srv-Inventory.txt'
    fac = tmp / 'Watch_srv-PAL-Factions.txt'
    write(inv, INV1)
    write(fac, FAC)
    write(tmp / 'Other_srv-Inventory.txt', INV1)          # not a known character: ignored
    write(tmp / 'notes.txt', 'nothing')

    # discovery
    found = gamefiles.list_exports(tmp)
    check('watch: list_exports finds only export-shaped names',
          {(e['name'], e['kind']) for e in found} == {('Watch', 'inventory'), ('Watch', 'faction'),
                                                       ('Other', 'inventory')}, found)
    mine = gamefiles.discover('watch', 'SRV', game_dir=tmp)
    check('watch: discover is case-insensitive and drops name/server keys',
          [m['kind'] for m in mine] == ['faction', 'inventory']
          and all('name' not in m for m in mine) and mine[1]['size'] == len(INV1), mine)

    row = characters.add('Watch', 'srv', None, None, activate=False)
    cid = row['id']
    r = exports_watch.run_once(game_dir=tmp)
    kinds = sorted(x['kind'] for x in r['imported'])
    check('watch: first pass imports both files for the known character only',
          kinds == ['faction', 'inventory'] and r['checked'] == 2 and not r['errors'], r)
    snap1 = inventory.latest_snapshot(cid)
    check('watch: inventory snapshot written', snap1 is not None)
    check('watch: faction standings written',
          db.query_one('SELECT COUNT(*) n FROM faction_standings WHERE character_id=?',
                       (cid,))['n'] == 1)
    check('watch: inventory_path remembered from the pickup',
          characters.get(cid)['inventory_path'] == str(inv))
    files = {f['kind']: f for f in exports_watch.files_for(cid)}
    check('watch: export_files rows recorded as imported',
          files['inventory']['status'] == 'imported' and files['faction']['status'] == 'imported'
          and files['inventory']['imported_at'] is not None, files)
    with state.lock:
        recent = list(state.exports['recent'])
    check('watch: state.exports.recent carries the pickups',
          len(recent) >= 2 and all(x['character'] == 'Watch' for x in recent[:2])
          and state.exports['last_check'] is not None, recent[:2])

    # second pass: same mtime/size -> nothing is even read
    r2 = exports_watch.run_once(game_dir=tmp)
    check('watch: unchanged files are skipped silently', not r2['imported'] and r2['unchanged'] == 0
          and r2['checked'] == 2, r2)

    # same bytes, new mtime -> 'unchanged', no new snapshot, imported_at kept
    write(inv, INV1, old + 5)
    r3 = exports_watch.run_once(game_dir=tmp)
    check('watch: identical rewrite recorded as unchanged', r3['unchanged'] == 1 and not r3['imported'], r3)
    check('watch: no new snapshot for identical bytes',
          inventory.latest_snapshot(cid)['id'] == snap1['id'])
    check('watch: imported_at survives an unchanged pass',
          exports_watch.files_for(cid)[1]['imported_at'] is not None
          if exports_watch.files_for(cid)[1]['kind'] == 'inventory'
          else {f['kind']: f['imported_at'] for f in exports_watch.files_for(cid)}['inventory'] is not None)

    # changed bytes -> re-imported
    write(inv, INV2, old + 6)
    r4 = exports_watch.run_once(game_dir=tmp)
    check('watch: changed file re-imported', len(r4['imported']) == 1
          and r4['imported'][0]['kind'] == 'inventory', r4)
    check('watch: new snapshot with the new rows',
          inventory.latest_snapshot(cid)['id'] > snap1['id']
          and inventory.get_view(cid)['items'][0]['name'] == 'Helm')

    # a file still being written (young mtime) is left alone, then picked up
    inv.write_bytes(INV1.encode('utf-8'))             # mtime = now
    r5 = exports_watch.run_once(game_dir=tmp)
    check('watch: a file younger than the settle time is skipped', not r5['imported'], r5)
    os.utime(inv, (old + 7, old + 7))
    r6 = exports_watch.run_once(game_dir=tmp)
    check('watch: …and imported once it has settled', len(r6['imported']) == 1, r6)

    # garbage recipes export -> error recorded once, not raised, not retried
    bad = tmp / 'Watch_srv-Baking-Recipes.txt'
    write(bad, 'nothing\nhere\n')
    r7 = exports_watch.run_once(game_dir=tmp)
    check('watch: unparseable file recorded as error', len(r7['errors']) == 1
          and r7['errors'][0]['kind'] == 'recipes' and r7['errors'][0]['skill'] == 'Baking', r7)
    files = {f['path']: f for f in exports_watch.files_for(cid)}
    check('watch: error row stored with the message',
          files[str(bad)]['status'] == 'error' and 'recipes' in (files[str(bad)]['error'] or ''))
    r8 = exports_watch.run_once(game_dir=tmp)
    check('watch: the same bad file is not retried', not r8['errors'], r8)
    write(bad, '1912\tPurple Trickster Circle Fly\n', old + 8)
    r9 = exports_watch.run_once(game_dir=tmp)
    check('watch: a fixed file imports on the next change', len(r9['imported']) == 1
          and r9['imported'][0]['detail']['rows'] == 1, r9)

    # the remembered inventory_path outside the game folder is watched too
    other_dir = Path(tempfile.mkdtemp(prefix='eqa-watch2-'))
    elsewhere = other_dir / 'Watch_srv-Inventory.txt'
    write(elsewhere, INV2)
    with db.tx() as c:
        c.execute('UPDATE characters SET inventory_path=? WHERE id=?', (str(elsewhere), cid))
    r10 = exports_watch.run_once(game_dir=tmp)
    check('watch: inventory_path outside the game dir is a candidate',
          any(x['path'] == str(elsewhere) for x in r10['imported']), r10)

    characters.remove(cid)
    check('watch: remove() clears export_files',
          db.query_one('SELECT COUNT(*) n FROM export_files WHERE character_id=?', (cid,))['n'] == 0)

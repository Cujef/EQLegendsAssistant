"""Log-scan suites: ext_parser AA events, highlight aggregation, the pipeline's
chunked scan/resume/truncation behavior, and fight persistence."""
import json
import os
import tempfile
import time


def run(check):
    _ext(check)
    _agg(check)
    _pipeline(check)


# ── ext_parser ────────────────────────────────────────────────────────────────
def _ext(check):
    from app.logscan.ext_parser import parse

    CASES = [
        # real AA lines from eqlog_Cujef_halas.txt (all three shapes + variants)
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
    ]
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

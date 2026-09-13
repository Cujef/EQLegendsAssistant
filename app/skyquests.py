"""Plane of Sky class tests: the wiki's per-class quest tables joined to the
inventory dump.

Data source: the cached wikitext of https://eqlwiki.com/Plane_of_Sky (table
`raw_pages`, filled by the wiki sync). Its "Plane of Sky Class Quests" section
holds one `=== [[Class]] Tests ===` block per class, each with a quest giver
line and one eoTable3 table: Reward | Quest | Trigger Phrases | Rune | Quest
Items. The 16 `<Class>_Plane_of_Sky_Tests` pages only transclude those
sections, so this one page is the whole list. A bundled snapshot
(app/data/sky_quests.json, written by tools/gen_sky_quests.py) covers a fresh
install that has never synced, and any wiki edit that breaks the parse.

Completion is DERIVED, never stored, unless the user says otherwise: a test
counts as done when its reward is anywhere in the dump (+N and Exaltation
copies included — the reward is no-drop, so a copy proves the hand-in). A row
in sky_quest_progress is a manual override in either direction. Turn-in items
count only as tradeable copies: Exaltation copies and the trailing keyring
lists never satisfy a need; +N copies do (the game's merge keeps the item).
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import db, inventory
from .inventory import LIST_ROOTS, normalize_name
from .quests import CLASSES

PAGE_URL = 'https://eqlwiki.com/Plane_of_Sky'
BUNDLED = Path(__file__).resolve().parent / 'data' / 'sky_quests.json'
MIN_QUESTS = 60   # a parse below this is a broken wiki page, not a smaller list

# the section runs to the next level-1 or level-2 heading (=== stays inside)
RE_SECTION = re.compile(
    r'^==\s*Plane of Sky Class Quests\s*==[^\n]*$(.*?)(?=^=(?!=)|^==(?!=)|\Z)', re.M | re.S)
RE_CLASS = re.compile(
    r'^===\s*\[\[([^\]|]+)(?:\|[^\]]*)?\]\]\s*Tests\s*===[^\n]*$(.*?)(?=^===|\Z)', re.M | re.S)
RE_GIVER = re.compile(r"'''\s*Quest Giver:?\s*'''\s*\[\[([^\]|]+)")
RE_TABLE = re.compile(r'^\{\|[^\n]*\n(.*?)^\|\}', re.M | re.S)
RE_ROW = re.compile(r'^\|-[^\n]*$', re.M)
RE_CELL = re.compile(r'^\|(?![-}])', re.M)
RE_REWARD = re.compile(r'\{\{:([^}|]+)\}\}')
RE_LINK = re.compile(r'\[\[([^\]|]+)(?:\|([^\]]*))?\]\]')
RE_LI = re.compile(r'<li[^>]*>(.*?)</li>', re.S)
RE_SRC = re.compile(r'\(([^()]+)\)\s*$')
RE_TAGS = re.compile(r'<[^>]+>')


def quest_key(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', str(name or '').lower()).strip('-')


def _clean(cell: str) -> str:
    s = RE_TAGS.sub('', cell or '')
    return ' '.join(s.replace("'''", '').replace("''", '').split())


def _uniq(seq):
    out = []
    for x in seq:
        if x and x not in out:
            out.append(x)
    return out


def _needs_from_cell(cell: str) -> List[dict]:
    """One entry per <li> (or per bare link when the cell has no list)."""
    parts = RE_LI.findall(cell) or [cell]
    out = []
    for li in parts:
        m = RE_LINK.search(li)
        if not m:
            continue
        target = m.group(1).strip()
        label = (m.group(2) or '').strip() or target
        tail = li[m.end():].replace('}}', '').replace("'''", '')
        tail = RE_TAGS.sub('', tail).strip()
        src = RE_SRC.search(tail)
        out.append({
            'name': target,
            'display': label,
            'name_norms': _uniq([normalize_name(target), normalize_name(label)]),
            'src': src.group(1).strip() if src else None,
            'no_drop': 'SkyNoDrop' in li,
            'qty': 1,
        })
    return out


def parse_wikitext(text: str) -> List[dict]:
    """The class-test list from the Plane of Sky page's wikitext, in wiki
    order. Empty when the section is missing; never raises on odd markup —
    a row that does not have the five columns is skipped."""
    sec = RE_SECTION.search(text or '')
    if not sec:
        return []
    quests: List[dict] = []
    for cm in RE_CLASS.finditer(sec.group(1)):
        cls = cm.group(1).strip()
        body = cm.group(2)
        gm = RE_GIVER.search(body)
        giver = gm.group(1).strip() if gm else None
        tm = RE_TABLE.search(body)
        if not tm:
            continue
        for chunk in RE_ROW.split(tm.group(1)):
            if not chunk.strip() or chunk.lstrip().startswith('!'):
                continue
            cells = [c for c in RE_CELL.split(chunk) if c.strip()]
            if len(cells) < 5:
                continue
            rm = RE_REWARD.search(cells[0])
            if rm:
                reward = rm.group(1).strip()
            else:
                lm = RE_LINK.search(cells[0])
                reward = (lm.group(1) if lm else _clean(cells[0])).strip()
            name = _clean(cells[1])
            if not name or not reward:
                continue
            runes = [{'name': n['name'], 'name_norm': n['name_norms'][0]}
                     for n in _needs_from_cell(cells[3])]
            items = _needs_from_cell(cells[4])
            quests.append({
                'key': quest_key(name),
                'cls': cls,
                'name': name,
                'phrase': _clean(cells[2]),
                'giver': giver,
                'order': len(quests),
                'reward': {'name': reward, 'name_norm': normalize_name(reward)},
                'runes': runes,
                'items': items,
            })
    return quests


def valid(quests: List[dict]) -> bool:
    keys = [q['key'] for q in quests]
    return (len(quests) >= MIN_QUESTS and {q['cls'] for q in quests} == set(CLASSES)
            and len(set(keys)) == len(keys)
            and all(q['runes'] and q['items'] for q in quests))


_cache: Dict[str, object] = {'stamp': None, 'quests': [], 'meta': {}}


def load_quests() -> Tuple[List[dict], dict]:
    """(quests, meta). The synced wiki page when it parses sanely, else the
    bundled snapshot with meta['warning'] saying why."""
    row = db.query_one('SELECT content, fetched_at FROM raw_pages WHERE url=?', (PAGE_URL,))
    warning = None
    if row:
        stamp = ('wiki', row['fetched_at'])
        if _cache['stamp'] == stamp:
            return _cache['quests'], _cache['meta']
        qs = parse_wikitext(row['content'])
        if valid(qs):
            meta = {'kind': 'wiki', 'fetched_at': row['fetched_at'], 'url': PAGE_URL,
                    'count': len(qs), 'warning': None}
            _cache.update(stamp=stamp, quests=qs, meta=meta)
            return qs, meta
        warning = (f'the synced wiki page parsed to {len(qs)} tests — using the bundled '
                   f'list instead (the page may have been restructured)')
    try:
        mtime = BUNDLED.stat().st_mtime
    except OSError:
        return [], {'kind': 'none', 'fetched_at': None, 'url': PAGE_URL, 'count': 0,
                    'warning': warning or 'no quest list: run a Data Sync'}
    stamp = ('bundled', mtime, warning)
    if _cache['stamp'] == stamp:
        return _cache['quests'], _cache['meta']
    data = json.loads(BUNDLED.read_text('utf-8'))
    qs = data.get('quests', [])
    meta = {'kind': 'bundled', 'fetched_at': data.get('fetched_at'), 'url': PAGE_URL,
            'count': len(qs), 'warning': warning}
    _cache.update(stamp=stamp, quests=qs, meta=meta)
    return qs, meta


def _pinned_classes(character_id: int) -> List[str]:
    rows = db.query("SELECT key, value FROM manual_stats WHERE character_id=? "
                    "AND key IN ('class1','class2','class3') ORDER BY key", (character_id,))
    return _uniq([r['value'].strip() for r in rows if (r['value'] or '').strip()])


def _tally(snapshot_id: int, norms: List[str]) -> Dict[str, dict]:
    """Per name_norm: copies by kind. 'base'/'upgraded' are tradeable turn-ins;
    'exaltation' and 'list' only ever count as reward evidence."""
    out: Dict[str, dict] = {}
    if not norms:
        return out
    marks = ','.join('?' * len(norms))
    rows = db.query(
        f'SELECT name_norm, is_exaltation, upgrade_tier, root, count FROM inventory_items '
        f'WHERE snapshot_id=? AND is_empty=0 AND name_norm IN ({marks})',
        (snapshot_id, *norms))
    for r in rows:
        t = out.setdefault(r['name_norm'], {'base': 0, 'upgraded': 0, 'exaltation': 0, 'list': 0})
        n = int(r['count'] or 1)
        if r['root'] in LIST_ROOTS:
            t['list'] += n
        elif r['is_exaltation']:
            t['exaltation'] += n
        elif (r['upgrade_tier'] or 0) > 0:
            t['upgraded'] += n
        else:
            t['base'] += n
    return out


def _evidence(t: Optional[dict]) -> Optional[str]:
    if not t:
        return None
    for k in ('base', 'upgraded', 'exaltation', 'list'):
        if t.get(k):
            return k
    return None


def _wiki_url(name: str) -> str:
    from .sync.wiki_parse import title_to_url
    return title_to_url(name)


def view(character_id: int) -> dict:
    quests, meta = load_quests()
    snap = inventory.ensure_current(character_id)
    norms = _uniq([n for q in quests for n in
                   [q['reward']['name_norm']] + [r['name_norm'] for r in q['runes']]
                   + [a for it in q['items'] for a in it['name_norms']]])
    tally = _tally(snap['id'], norms) if snap else {}
    icons = {r['name_norm']: r['icon'] for r in db.query(
        f"SELECT name_norm, icon FROM items WHERE name_norm IN ({','.join('?' * len(norms))})",
        norms)} if norms else {}
    manual = {r['quest_key']: r for r in db.query(
        'SELECT quest_key, done, marked_at FROM sky_quest_progress WHERE character_id=?',
        (character_id,))}
    # "Primary Class Unlock - X" in the log, or complete in the achievements
    # export: the game's own word that the class is done. Jeff's rule: an
    # unlocked class counts every test done, even when a reward is gone from
    # the dump (sold, destroyed, merged away). The unlock also auto-completes
    # for the creation class and can be bought with a token, so the source is
    # labelled 'unlocked', never 'auto'.
    from .achievements import earned_unlocks
    unlocked = earned_unlocks(character_id, 'class')
    pinned = _pinned_classes(character_id)
    pin_rank = {c: i for i, c in enumerate(pinned)}

    def supply_of(aliases: List[str]) -> Tuple[str, int, int]:
        """(alias that matched, base, upgraded) — the best-stocked alias wins."""
        best = (aliases[0], 0, 0)
        for a in aliases:
            t = tally.get(a)
            if t and t['base'] + t['upgraded'] > best[1] + best[2]:
                best = (a, t['base'], t['upgraded'])
        return best

    rows: List[dict] = []
    for q in quests:
        needs = []
        for kind, lst in (('rune', q['runes']), ('item', q['items'])):
            for it in lst:
                aliases = it.get('name_norms') or [it['name_norm']]
                key, base, up = supply_of(aliases)
                have = base + up
                qty = int(it.get('qty', 1) or 1)
                needs.append({
                    'kind': kind, 'name': it['name'], 'display': it.get('display', it['name']),
                    'name_norm': key, 'icon': icons.get(key), 'src': it.get('src'),
                    'no_drop': bool(it.get('no_drop')), 'qty': qty,
                    'have_base': base, 'have_upgraded': up, 'have': have,
                    'ok': have >= qty, 'upgraded_only': have >= qty and base == 0,
                    'contended': False,
                })
        ev = _evidence(tally.get(q['reward']['name_norm']))
        auto_done = ev is not None
        is_unlocked = q['cls'] in unlocked            # ts may be None: export-only
        unlocked_at = unlocked.get(q['cls'])
        m = manual.get(q['key'])
        done = bool(m['done']) if m else (auto_done or is_unlocked)
        missing = sum(1 for n in needs if not n['ok'])
        rows.append({
            'key': q['key'], 'cls': q['cls'], 'name': q['name'], 'phrase': q.get('phrase'),
            'giver': q.get('giver'), 'order': q.get('order', len(rows)),
            'pinned': q['cls'] in pin_rank,
            'wiki_url': _wiki_url(f"{q['cls']} Plane of Sky Tests"),
            'reward': {'name': q['reward']['name'], 'name_norm': q['reward']['name_norm'],
                       'icon': icons.get(q['reward']['name_norm']),
                       'wiki_url': _wiki_url(q['reward']['name']), 'evidence': ev},
            'needs': needs, 'missing': missing,
            'status': 'done' if done else 'open',
            'source': ('manual' if m else 'auto' if auto_done
                       else 'unlocked' if is_unlocked else 'none'),
            'auto_done': auto_done,
            'unlocked': is_unlocked,
            'unlocked_at': unlocked_at,
            'manual': ({'done': int(m['done']), 'marked_at': m['marked_at']} if m else None),
            'ready': (not done) and missing == 0,
            'covered': False,
        })

    # Wind Runes usually sit in the currency tab, which no export can see (the
    # game's own /outputfile usage line lists no currency target). The log is a
    # ledger instead: runes are No Trade, so "looted minus handed in" is what is
    # on hand, give or take runes destroyed or looted before the log began. The
    # dump wins whenever it does hold copies (runes left in a bag).
    rune_norms = _uniq([r['name_norm'] for q in quests for r in q['runes']])
    looted: Dict[str, int] = {}
    if rune_norms:
        marks = ','.join('?' * len(rune_norms))
        looted = {r['item_norm']: int(r['n'] or 0) for r in db.query(
            f'SELECT item_norm, SUM(qty) AS n FROM loot_events WHERE character_id=? '
            f'AND item_norm IN ({marks}) GROUP BY item_norm', (character_id, *rune_norms))}
    consumed: Dict[str, int] = {}
    for r in rows:
        if r['status'] == 'done':
            for n in r['needs']:
                if n['kind'] == 'rune':
                    consumed[n['name_norm']] = consumed.get(n['name_norm'], 0) + n['qty']
    est = {k: max(0, looted.get(k, 0) - consumed.get(k, 0)) for k in rune_norms}
    for r in rows:
        changed = False
        for n in r['needs']:
            n['source'] = 'dump'
            if n['kind'] == 'rune' and n['have'] == 0 and looted.get(n['name_norm']):
                n['source'] = 'log'
                n['have'] = est[n['name_norm']]
                n['ok'] = n['have'] >= n['qty']
                changed = True
        if changed:
            r['missing'] = sum(1 for n in r['needs'] if not n['ok'])
            r['ready'] = r['status'] == 'open' and r['missing'] == 0

    # demand vs supply: the same rune (or Efreeti weapon) is wanted by several
    # open tests, so "ready" is honest only after a greedy allocation — pinned
    # classes first, then wiki order.
    demand_open: Dict[str, int] = {}
    for r in rows:
        if r['status'] == 'open':
            for n in r['needs']:
                demand_open[n['name_norm']] = demand_open.get(n['name_norm'], 0) + n['qty']
    for r in rows:
        for n in r['needs']:
            n['demand_open'] = demand_open.get(n['name_norm'], 0)
            n['contended'] = n['ok'] and n['demand_open'] > n['have']
    left: Dict[str, int] = {}
    order = sorted((r for r in rows if r['status'] == 'open'),
                   key=lambda r: (pin_rank.get(r['cls'], len(pin_rank)), r['order']))
    for r in order:
        if not r['ready']:
            continue
        if all(left.get(n['name_norm'], n['have']) >= n['qty'] for n in r['needs']):
            for n in r['needs']:
                left[n['name_norm']] = left.get(n['name_norm'], n['have']) - n['qty']
            r['covered'] = True

    runes = []
    seen = set()
    for q in quests:
        for ru in q['runes']:
            if ru['name_norm'] in seen:
                continue
            seen.add(ru['name_norm'])
            t = tally.get(ru['name_norm']) or {}
            in_dump = t.get('base', 0) + t.get('upgraded', 0)
            lo = looted.get(ru['name_norm'], 0)
            src = 'dump' if in_dump else 'log' if lo else 'none'
            supply = in_dump if in_dump else est.get(ru['name_norm'], 0)
            dem = demand_open.get(ru['name_norm'], 0)
            runes.append({'name': ru['name'], 'name_norm': ru['name_norm'],
                          'icon': icons.get(ru['name_norm']), 'supply': supply,
                          'supply_source': src, 'in_dump': in_dump,
                          'supply_base': t.get('base', 0), 'supply_upgraded': t.get('upgraded', 0),
                          'looted': lo, 'consumed': consumed.get(ru['name_norm'], 0),
                          'est': est.get(ru['name_norm'], 0),
                          'demand_open': dem, 'short': max(0, dem - supply)})

    def pct(done_n, total_n):
        return round(100.0 * done_n / total_n, 1) if total_n else 0.0

    classes = []
    for c in CLASSES:
        cr = [r for r in rows if r['cls'] == c]
        dn = sum(1 for r in cr if r['status'] == 'done')
        classes.append({'name': c, 'total': len(cr), 'done': dn, 'pct': pct(dn, len(cr)),
                        'ready': sum(1 for r in cr if r['ready']),
                        'covered': sum(1 for r in cr if r['covered']),
                        'pinned': c in pin_rank,
                        'unlocked': c in unlocked,
                        'unlocked_at': unlocked.get(c)})
    classes.sort(key=lambda c: (pin_rank.get(c['name'], len(pin_rank)), CLASSES.index(c['name'])))
    done_n = sum(1 for r in rows if r['status'] == 'done')
    totals = {
        'total': len(rows), 'done': done_n, 'open': len(rows) - done_n, 'pct': pct(done_n, len(rows)),
        'ready': sum(1 for r in rows if r['ready']),
        'covered': sum(1 for r in rows if r['covered']),
        'manual': sum(1 for r in rows if r['source'] == 'manual'),
        'auto': sum(1 for r in rows if r['source'] == 'auto'),
        'unlocked': sum(1 for r in rows if r['source'] == 'unlocked'),
        'classes_unlocked': len(unlocked),
        'runes_short': sum(r['short'] for r in runes),
        'runes_in_dump': sum(r['in_dump'] for r in runes),
        'runes_est': sum(r['est'] for r in runes if r['supply_source'] == 'log'),
        'runes_looted': sum(r['looted'] for r in runes),
        'runes_consumed': sum(r['consumed'] for r in runes),
    }
    return {
        'snapshot': ({'id': snap['id'], 'imported_at': snap['imported_at']} if snap else None),
        'source': meta,
        'pinned_classes': pinned,
        'totals': totals,
        'classes': classes,
        'runes': runes,
        'quests': rows,
        'notes': {
            'auto': 'A test counts as done when its reward is in your inventory dump '
                    '(+N and Exaltation copies included), or when the log shows the class '
                    'unlocked ("Primary Class Unlock"). A manual tick beats both.',
            'unlocked': 'An unlocked class counts every one of its tests done — the game says '
                        'the class is finished, even if a reward has since been sold, destroyed '
                        'or merged away. The unlock also auto-completes for your creation class '
                        'and can be bought with a token, so untick by hand if that is the case.',
            'needs': 'Turn-in ticks come from the dump only: tradeable copies count '
                     '(+N too), Exaltation copies and the trailing keyring lists do not. '
                     '"Shared" means other open tests want the same item.',
            'runes': 'Wind Runes usually live in the currency tab, which no export can see. '
                     'When the dump holds none, the count is estimated from the log: runes '
                     'looted minus one per test marked done (runes are No Trade, so nothing '
                     'else takes them). Runes destroyed, or looted before the log began, are '
                     'invisible to it.',
            'src': "The (3-Gorga)-style tags are the wiki's island / boss labels: "
                   '3-Gorga, 4-KoS, 5-SL, 6-BZ, 7-SotS, 7-Trash, 8-EoV.',
            'ready': 'Ready counts every open test whose needs are all in the dump; '
                     'turn-in-now allocates shared items once, your classes first.',
        },
    }


def set_done(character_id: int, key: str, done: Optional[bool]) -> None:
    """Manual mark: True/False overrides the dump, None clears the override.
    KeyError for a key that is not a known test."""
    quests, _ = load_quests()
    if key not in {q['key'] for q in quests}:
        raise KeyError(key)
    if done is None:
        db.execute('DELETE FROM sky_quest_progress WHERE character_id=? AND quest_key=?',
                   (character_id, key))
        return
    db.execute(
        'INSERT INTO sky_quest_progress(character_id, quest_key, done, marked_at) VALUES(?,?,?,?) '
        'ON CONFLICT(character_id, quest_key) DO UPDATE SET done=excluded.done, '
        'marked_at=excluded.marked_at', (character_id, key, 1 if done else 0, db.now()))

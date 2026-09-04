"""Zone history and loot history from the log (v1.2).

Zone time is what the Aggregator's zone clock recorded: gaps of at most 30
minutes between your own zone / XP / kill / loot lines — "active hunting time",
not wall-clock time in the zone. Per-hour rates are only given past 0.1 h.

The synced ZEM guide publishes no numeric ZEM (every row is null); what it has
is a per-level-bracket rating ("efficient", "inefficient", …). Guide names
differ from the log's ("Lavastorm Mountains" vs "The Lavastorm Mountains",
"Plane of Sky *"), so matching normalises both sides and falls back to a
unique prefix match.
"""
import json
import re
from typing import Dict, List, Optional

from . import db

RE_TRAIL = re.compile(r'\s*\*\s*$')


def zone_key(name: str) -> str:
    s = str(name or '').strip().lower()
    s = RE_TRAIL.sub('', s)
    s = s.replace("'", '').replace('`', '').replace('’', '')
    if s.startswith('the '):
        s = s[4:]
    return ' '.join(s.split())


def guide_lookup() -> Dict[str, dict]:
    """{zone_key: guide row} from the synced ZEM guide (kind='zem')."""
    g = db.query_one("SELECT parsed_json FROM guides WHERE kind='zem' AND parsed_ok=1 LIMIT 1")
    if not g or not g['parsed_json']:
        return {}
    try:
        pj = json.loads(g['parsed_json'])
    except ValueError:
        return {}
    rows = pj.get('rows') if isinstance(pj, dict) else pj
    out = {}
    for r in rows or []:
        if isinstance(r, dict) and r.get('zone'):
            out.setdefault(zone_key(r['zone']), r)
    return out


def match_guide(key: str, guide: Dict[str, dict]) -> Optional[dict]:
    if key in guide:
        return guide[key]
    hits = [g for gk, g in guide.items() if gk.startswith(key) or key.startswith(gk)]
    return hits[0] if len(hits) == 1 else None


def rating_for(row: Optional[dict], level: Optional[int]) -> Optional[str]:
    """The guide's rating for the character's level bracket (keys are the
    bracket's lowest level as strings)."""
    if not row or not level:
        return None
    ratings = row.get('ratings') or {}
    best = None
    for k, v in ratings.items():
        try:
            lo = int(k)
        except (TypeError, ValueError):
            continue
        if lo <= level and (best is None or lo > best[0]):
            best = (lo, v)
    return best[1] if best else None


def _level(character_id: int) -> Optional[int]:
    r = db.query_one('SELECT MAX(level) AS lvl FROM level_history WHERE character_id=?',
                     (character_id,))
    return int(r['lvl']) if r and r['lvl'] else None


def view(character_id: int) -> dict:
    rows = db.query('SELECT * FROM zone_stats WHERE character_id=? ORDER BY seconds DESC',
                    (character_id,))
    level = _level(character_id)
    guide = guide_lookup()
    zones = []
    for r in rows:
        hours = (r['seconds'] or 0.0) / 3600.0
        g = match_guide(zone_key(r['zone']), guide)
        zones.append({
            'zone': r['zone'],
            'seconds': round(r['seconds'] or 0.0, 1),
            'hours': round(hours, 2),
            'kills': int(r['kills'] or 0),
            'kills_per_hour': round(r['kills'] / hours, 1) if hours >= 0.1 else None,
            'xp_pct': round(r['xp_pct'] or 0.0, 2),
            'xp_per_hour': round(r['xp_pct'] / hours, 2) if hours >= 0.1 else None,
            'loot': int(r['loot'] or 0),
            'visits': int(r['visits'] or 0),
            'first_ts': r['first_ts'], 'last_ts': r['last_ts'],
            'guide': ({'zone': g.get('zone'), 'level_min': g.get('level_min'),
                       'level_max': g.get('level_max'), 'zem': g.get('zem'),
                       'rating': rating_for(g, level)} if g else None),
        })
    recent = db.query('SELECT ts, zone FROM zone_events WHERE character_id=? '
                      'ORDER BY ts DESC, id DESC LIMIT 30', (character_id,))
    totals = {
        'zones': len(zones),
        'hours': round(sum(z['hours'] for z in zones), 1),
        'kills': sum(z['kills'] for z in zones),
        'xp_pct': round(sum(z['xp_pct'] for z in zones), 1),
        'loot': sum(z['loot'] for z in zones),
        'visits': sum(z['visits'] for z in zones),
    }
    return {'level': level, 'zones': zones, 'recent_visits': recent,
            'current_zone': recent[0]['zone'] if recent else None, 'totals': totals,
            'notes': {
                'hours': 'active hunting time: gaps of at most 30 minutes between your own '
                         'zone / XP / kill / loot lines',
                'guide': 'ratings from the synced ZEM guide for your level bracket; the '
                         'guide publishes no numeric ZEM',
            }}


def loot(character_id: int, q: str = '', limit: Optional[int] = 200) -> dict:
    """Loot grouped by item with its top sources (mob + zone)."""
    where = 'character_id=?'
    params: List = [character_id]
    q = (q or '').strip().lower()
    if q:
        where += ' AND item_norm LIKE ?'
        params.append(f'%{q}%')
    lim = f' LIMIT {int(limit)}' if limit else ''
    items = db.query(
        f'SELECT item_norm, MAX(item) AS item, COUNT(*) AS count, SUM(qty) AS qty, '
        f'MIN(ts) AS first_ts, MAX(ts) AS last_ts FROM loot_events WHERE {where} '
        f'GROUP BY item_norm ORDER BY count DESC, item_norm{lim}', params)
    sources: Dict[str, list] = {}
    in_db = set()
    if items:
        norms = [i['item_norm'] for i in items]
        if limit:
            ph = ','.join('?' * len(norms))
            src_rows = db.query(
                f'SELECT item_norm, source, zone, COUNT(*) AS n FROM loot_events '
                f'WHERE character_id=? AND item_norm IN ({ph}) '
                f'GROUP BY item_norm, source, zone ORDER BY n DESC', [character_id] + norms)
            in_db = {r['name_norm'] for r in db.query(
                f'SELECT name_norm FROM items WHERE name_norm IN ({ph})', norms)}
        else:
            src_rows = db.query(
                'SELECT item_norm, source, zone, COUNT(*) AS n FROM loot_events '
                'WHERE character_id=? GROUP BY item_norm, source, zone ORDER BY n DESC',
                (character_id,))
            in_db = {r['name_norm'] for r in db.query(
                'SELECT l.item_norm AS name_norm FROM loot_events l JOIN items it '
                'ON it.name_norm=l.item_norm WHERE l.character_id=? GROUP BY l.item_norm',
                (character_id,))}
        for s in src_rows:
            lst = sources.setdefault(s['item_norm'], [])
            if len(lst) < 5:
                lst.append({'source': s['source'], 'zone': s['zone'], 'n': int(s['n'])})
    for i in items:
        i['count'] = int(i['count'])
        i['qty'] = int(i['qty'] or 0)
        i['sources'] = sources.get(i['item_norm'], [])
        i['in_item_db'] = i['item_norm'] in in_db
    recent = db.query('SELECT ts, item, source, qty, zone FROM loot_events WHERE character_id=? '
                      'ORDER BY ts DESC, id DESC LIMIT 50', (character_id,))
    total = db.query_one('SELECT COUNT(*) AS n FROM loot_events WHERE character_id=?',
                         (character_id,))['n']
    return {'items': items, 'recent': recent, 'total_events': int(total or 0), 'query': q}

"""Faction standings: movement from the log (parser v1.6.0 `faction` /
`faction_capped` events) joined to the absolute values from an imported
`/outputfile faction` export (app/gamefiles.py).

The log only reports CHANGES ("adjusted by -5") and the two pinned states
("could not possibly get any better/worse"), never an absolute standing — so
`delta` is the net movement since logging began, and `capped` says the last
thing the game said about that faction was "already at the end". When a faction
file has been imported, `standing` is the file's value, `standing_label` the
EverQuest band it falls in (ASSUMED thresholds — flagged), and `est_now` is
value + the log's movement since the import (an estimate, flagged too).
"""
from . import db, gamefiles


def view(character_id: int) -> dict:
    adj = {r['faction']: r for r in db.query(
        'SELECT faction, SUM(delta) AS delta, COUNT(*) AS events, '
        'SUM(CASE WHEN delta > 0 THEN delta ELSE 0 END) AS gained, '
        'SUM(CASE WHEN delta < 0 THEN -delta ELSE 0 END) AS lost, '
        'MIN(ts) AS first_ts, MAX(ts) AS last_ts '
        'FROM faction_events WHERE character_id=? GROUP BY faction', (character_id,))}
    caps = {r['faction']: r for r in db.query(
        'SELECT faction, direction, first_ts, last_ts, count FROM faction_caps '
        'WHERE character_id=?', (character_id,))}
    standings = gamefiles.faction_standings(character_id)
    imported_at = max((s['imported_at'] for s in standings.values()), default=None)
    since = {}
    if imported_at:
        since = {r['faction']: int(r['d'] or 0) for r in db.query(
            'SELECT faction, SUM(delta) AS d FROM faction_events WHERE character_id=? AND ts>=? '
            'GROUP BY faction', (character_id, imported_at))}

    out = []
    for name in sorted(set(adj) | set(caps) | set(standings), key=str.lower):
        a = adj.get(name)
        c = caps.get(name)
        s = standings.get(name)
        last_adj = a['last_ts'] if a else None
        # "capped" only when the pinned notice is the most recent word on it —
        # an adjustment after a MAX notice means it moved off the cap again
        capped = c['direction'] if c and (last_adj is None or c['last_ts'] >= last_adj) else None
        est = (s['value'] + since.get(name, 0)) if s else None
        if est is not None:
            est = max(-gamefiles.FACTION_MAX, min(gamefiles.FACTION_MAX, est))
        out.append({
            'faction': name,
            'delta': int(a['delta']) if a else 0,
            'events': int(a['events']) if a else 0,
            'gained': int(a['gained']) if a else 0,
            'lost': int(a['lost']) if a else 0,
            'first_ts': min((x for x in (a and a['first_ts'], c and c['first_ts']) if x),
                            default=None),
            'last_ts': max((x for x in (last_adj, c and c['last_ts']) if x), default=None),
            'capped': capped,
            'cap_notices': int(c['count']) if c else 0,
            # from the /outputfile faction export, when imported
            'standing': s['value'] if s else None,
            'standing_label': gamefiles.standing_label(s['value']) if s else None,
            'to_max': s['to_max'] if s else None,
            'est_now': est,
            'est_label': gamefiles.standing_label(est) if est is not None else None,
            'moved_since_import': since.get(name, 0) if s else None,
        })
    recent = db.query('SELECT ts, faction, delta FROM faction_events WHERE character_id=? '
                      'ORDER BY ts DESC, id DESC LIMIT 50', (character_id,))
    totals = {
        'factions': len(out),
        'events': sum(f['events'] for f in out),
        'raised': sum(1 for f in out if f['delta'] > 0),
        'lowered': sum(1 for f in out if f['delta'] < 0),
        'maxed': sum(1 for f in out if f['capped'] == 'better'),
        'bottomed': sum(1 for f in out if f['capped'] == 'worse'),
        'with_standing': sum(1 for f in out if f['standing'] is not None),
    }
    return {'factions': out, 'recent': recent, 'totals': totals,
            'standings_imported_at': imported_at,
            'notes': {
                'standing_label': 'EverQuest standing bands (Ally ≥1100 … Ready to Attack ≤-751); '
                                  'assumed for EQ Legends',
                'est_now': 'file value plus the log\'s net movement since the import',
            }}

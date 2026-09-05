"""Play sessions: what you actually got done in this sitting.

A session is a run of play with no gap longer than SESSION_GAP (30 minutes) —
the same clock that produces `highlights.total_sessions` and
`playtime_seconds`, so the row count and the summed seconds agree with those
two by construction. Rows are written by the Aggregator in the log pipeline's
own transaction, so they survive an app restart: closing the app mid-hunt no
longer zeroes tonight's numbers.

"Active time" is the summed gaps, not wall-clock: standing in a city with the
log quiet for an hour does not count, and the honesty note in the payload says
so. Per-hour rates are withheld below 0.1 h, where they are noise.
"""
from typing import Optional

from . import db
from .logscan.highlights import SESSION_GAP

MIN_HOURS_FOR_RATE = 0.1


def _rate(value, hours):
    return round(value / hours, 1) if hours >= MIN_HOURS_FOR_RATE and value else None


def _shape(r: Optional[dict], now_ts: Optional[float] = None) -> Optional[dict]:
    """One DB row plus the numbers derived from it (never stored: they are a
    function of the row and would only drift)."""
    if not r:
        return None
    hours = (r['seconds'] or 0.0) / 3600.0
    swings = (r['hits'] or 0) + (r['misses'] or 0)
    out = dict(r)
    out.update({
        'hours': round(hours, 2),
        'xp_per_hour': _rate(r['xp_pct'], hours),
        'kills_per_hour': _rate(r['kills'], hours),
        'coin_per_hour': _rate((r['coin_copper'] or 0) + (r['autosell_copper'] or 0)
                               + (r['vendor_copper'] or 0), hours),
        'dps': _rate(r['dmg_dealt'], hours * 3600) if hours else None,
        'income_copper': (r['coin_copper'] or 0) + (r['autosell_copper'] or 0)
                         + (r['vendor_copper'] or 0),
        'accuracy': round(100.0 * r['hits'] / swings, 1) if swings else None,
        'crit_rate': round(100.0 * r['crits'] / r['hits'], 1) if r['hits'] else None,
        'crafts': (r['crafts_ok'] or 0) + (r['crafts_fail'] or 0),
    })
    # "live" means the log is still inside this session's gap window
    if now_ts is not None:
        out['is_current'] = (now_ts - (r['last_ts'] or 0)) <= SESSION_GAP
    return out


def current(character_id: int) -> Optional[dict]:
    r = db.query_one('SELECT * FROM sessions WHERE character_id=? '
                     'ORDER BY last_ts DESC LIMIT 1', (character_id,))
    if not r:
        return None
    last = db.query_one("SELECT value_num FROM highlights WHERE character_id=? "
                        "AND key='log_last_ts'", (character_id,))
    return _shape(r, last['value_num'] if last else None)


def history(character_id: int, limit: int = 50) -> list:
    rows = db.query('SELECT * FROM sessions WHERE character_id=? '
                    'ORDER BY started_at DESC LIMIT ?', (character_id, int(limit)))
    return [_shape(r) for r in rows]


def view(character_id: int, limit: int = 50) -> dict:
    cur = current(character_id)
    recent = history(character_id, limit)
    tot = db.query_one(
        'SELECT COUNT(*) AS sessions, COALESCE(SUM(seconds),0) AS seconds, '
        'COALESCE(SUM(xp_pct),0) AS xp_pct, COALESCE(SUM(kills),0) AS kills, '
        'COALESCE(SUM(deaths),0) AS deaths, '
        'COALESCE(SUM(coin_copper + autosell_copper + vendor_copper),0) AS income_copper, '
        'COALESCE(SUM(loot),0) AS loot FROM sessions WHERE character_id=?', (character_id,))
    totals = dict(tot or {})
    totals['hours'] = round((totals.get('seconds') or 0) / 3600.0, 1)
    return {'current': cur, 'recent': recent, 'totals': totals,
            'gap_minutes': int(SESSION_GAP // 60),
            'notes': {
                'session': f'a session ends after {int(SESSION_GAP // 60)} minutes with no '
                           f'line in your log',
                'hours': 'active time: the summed gaps between your log lines, not wall clock',
                'income': 'coin off corpses + loot auto-sold on the corpse + merchant sales',
            }}

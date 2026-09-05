"""CSV / JSON export of the tables the pages show (v1.2).

Each view names its columns explicitly (key, label) and reuses the page's own
view function, so what you download is what you saw — never a raw dump of a
row dict. CSV is Excel-ready the way the parser's export is: UTF-8 with BOM,
CRLF, minimal quoting, a header row of the labels. Timestamps are written as
local "YYYY-MM-DD HH:MM:SS" in both formats.
"""
import csv
import io
import time
from typing import Callable, Dict, List, Tuple

from . import db, factions, inventory, sessions, tradeskills, zones

Columns = List[Tuple[str, str]]

TS_KEYS = ('ts', 'start', 'started_at', 'first_ts', 'last_ts', 'last_used_ts',
           'imported_at', 'last_merge_ts')


def _ts(v):
    if v is None or v == '':
        return None
    try:
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(float(v)))
    except (TypeError, ValueError, OverflowError):
        return v


def _fights(cid: int) -> list:
    return db.query('SELECT start, name, duration, dps, total_damage, total_healing, '
                    'total_tanking, xp, coin FROM fights WHERE character_id=? ORDER BY start DESC',
                    (cid,))


def _merges(cid: int) -> list:
    return db.query('SELECT ts, item, item_norm, tier FROM upgrade_events WHERE character_id=? '
                    'ORDER BY ts DESC', (cid,))


def _loot(cid: int) -> list:
    out = []
    for i in zones.loot(cid, limit=None)['items']:
        top = i['sources'][0] if i['sources'] else {}
        out.append({**i, 'top_source': top.get('source'), 'top_zone': top.get('zone'),
                    'top_n': top.get('n')})
    return out


def _recipes(cid: int) -> list:
    out = []
    for r in tradeskills.view(cid)['recipes']:
        out.append({**r, 'capped': 'yes' if r['capped'] else '',
                    'known': '' if r.get('known') is None else ('yes' if r['known'] else 'no')})
    return out


def _factions(cid: int) -> list:
    return factions.view(cid)['factions']


VIEWS: Dict[str, Tuple[Columns, Callable[[int], list]]] = {
    'inventory': ([('location', 'Location'), ('name', 'Item'), ('count', 'Count'),
                   ('item_id', 'ID'), ('section', 'Section'), ('host_name', 'In / on'),
                   ('upgrade_tier', 'Tier'), ('is_exaltation', 'Exaltation'),
                   ('is_equipped', 'Worn'), ('in_item_db', 'In item DB')],
                  lambda cid: inventory.get_view(cid)['items']),
    'merges': ([('ts', 'When'), ('item', 'Result'), ('tier', 'Tier')], _merges),
    'recipes': ([('item', 'Recipe'), ('skill', 'Skill (inferred)'), ('made', 'Made'),
                 ('failed', 'Failed'), ('attempts', 'Attempts'), ('rate', 'Rate %'),
                 ('capped', 'Capped'), ('known', 'In recipes file'), ('last_ts', 'Last')],
                _recipes),
    'materials': ([('item', 'Material'), ('used', 'Used'), ('consumes', 'Combines'),
                   ('deposited', 'Deposited'), ('withdrawn', 'Withdrawn'),
                   ('last_left', 'Last "leaving"'), ('est_depot', 'In depot (est.)'),
                   ('on_hand', 'On hand (dump)'), ('last_used_ts', 'Last used')],
                  lambda cid: tradeskills.view(cid)['materials']),
    'known_recipes': ([('skill', 'Skill'), ('recipe_id', 'Recipe ID'), ('name', 'Recipe'),
                       ('made', 'Made'), ('attempts', 'Attempts'), ('last_ts', 'Last made')],
                      lambda cid: tradeskills.view(cid)['known_recipes']),
    'factions': ([('faction', 'Faction'), ('standing', 'Standing (file)'),
                  ('standing_label', 'Band'), ('to_max', 'To max'), ('est_now', 'Est. now'),
                  ('delta', 'Net (log)'), ('events', 'Changes'), ('gained', 'Gained'),
                  ('lost', 'Lost'), ('capped', 'Capped'), ('first_ts', 'First'),
                  ('last_ts', 'Last')], _factions),
    'fights': ([('start', 'Start'), ('name', 'Fight'), ('duration', 'Duration s'),
                ('dps', 'DPS'), ('total_damage', 'Damage'), ('total_healing', 'Healing'),
                ('total_tanking', 'Taken'), ('xp', 'XP %'), ('coin', 'Coin (copper)')],
               _fights),
    'loot': ([('item', 'Item'), ('count', 'Drops'), ('qty', 'Quantity'),
              ('top_source', 'Most from'), ('top_zone', 'In zone'), ('top_n', 'Times'),
              ('first_ts', 'First'), ('last_ts', 'Last'), ('in_item_db', 'In item DB')],
             _loot),
    'sessions': ([('started_at', 'Started'), ('last_ts', 'Last line'),
                  ('hours', 'Active hours'), ('xp_pct', 'XP %'), ('xp_per_hour', 'XP % per hour'),
                  ('kills', 'Kills'), ('kills_per_hour', 'Kills per hour'), ('deaths', 'Deaths'),
                  ('income_copper', 'Income (copper)'), ('coin_copper', 'Coin'),
                  ('autosell_copper', 'Auto-sold'), ('vendor_copper', 'Merchant'),
                  ('dmg_dealt', 'Damage dealt'), ('dmg_taken', 'Damage taken'),
                  ('healed', 'Healing received'), ('accuracy', 'Accuracy %'),
                  ('crit_rate', 'Crit %'), ('loot', 'Loot'), ('crafts_ok', 'Combines made'),
                  ('crafts_fail', 'Combines failed'), ('faction_hits', 'Faction hits'),
                  ('skill_ups', 'Skill-ups'), ('aa_gained', 'AA gained'),
                  ('levels', 'Levels'), ('level_end', 'Level at end'),
                  ('zones', 'Zone changes'), ('first_zone', 'First zone'),
                  ('last_zone', 'Last zone')],
                 lambda cid: sessions.history(cid, limit=100000)),
    'zones': ([('zone', 'Zone'), ('hours', 'Active hours'), ('xp_pct', 'XP %'),
               ('xp_per_hour', 'XP % per hour'), ('kills', 'Kills'),
               ('kills_per_hour', 'Kills per hour'), ('loot', 'Loot'), ('visits', 'Visits'),
               ('first_ts', 'First'), ('last_ts', 'Last')],
              lambda cid: zones.view(cid)['zones']),
}


def rows(view: str, character_id: int) -> Tuple[Columns, list]:
    """(columns, rows) for a view; KeyError for an unknown one. Timestamp
    columns are formatted; every other value is passed through."""
    columns, fn = VIEWS[view]
    out = []
    for r in fn(character_id):
        row = {}
        for key, _ in columns:
            v = r.get(key)
            if key in TS_KEYS:
                v = _ts(v)
            elif isinstance(v, bool):
                v = 'yes' if v else 'no'
            row[key] = v
        out.append(row)
    return columns, out


def to_csv(columns: Columns, data: list) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator='\r\n', quoting=csv.QUOTE_MINIMAL)
    w.writerow([label for _, label in columns])
    for r in data:
        w.writerow(['' if r.get(k) is None else r.get(k) for k, _ in columns])
    return ('﻿' + buf.getvalue()).encode('utf-8')


def filename(char: dict, view: str, fmt: str) -> str:
    return f"{char['name']}_{char['server']}-{view}-{time.strftime('%Y%m%d')}.{fmt}"

"""Overview computation: stats/haste/focus from equipped gear x item DB,
AA from the log ledger, caps, and log highlights.

Every number carries provenance: 'computed' (derived from inventory + item DB),
'manual' (user-entered), or 'fallback' (hardcoded caps). Honesty rule: base
item stats come from the wiki/tools DB and do NOT include +N upgrade scaling —
that caveat rides the payload as `caveats`.
"""
import json
from typing import Optional

from . import db, inventory

PRIMARY_STATS = ['STR', 'STA', 'AGI', 'DEX', 'WIS', 'INT', 'CHA']
RESISTS = ['SV MAGIC', 'SV FIRE', 'SV COLD', 'SV POISON', 'SV DISEASE']

# Classic-EQ-era caps as a labeled fallback until the wiki /Statistics page is
# synced and parsed (source='wiki' rows in stat_caps then win).
FALLBACK_STAT_CAPS = {s: 255 for s in PRIMARY_STATS}
FALLBACK_STAT_CAPS.update({s: 255 for s in RESISTS})


def _caps() -> list:
    rows = db.query("SELECT stat, cap, source FROM stat_caps WHERE source='wiki'")
    have = {r['stat'] for r in rows}
    for stat, cap in FALLBACK_STAT_CAPS.items():
        if stat not in have:
            rows.append({'stat': stat, 'cap': cap, 'source': 'fallback'})
    return rows


def _equipped_rows(snapshot_id: int) -> list:
    """Worn top-level items + their socketed exaltations, joined to the item DB."""
    return db.query(
        'SELECT i.location, i.name, i.name_norm, i.upgrade_tier, i.is_exaltation, '
        'i.sub_slot, it.stats_json, it.resists_json, it.ac, it.hp, it.mana, '
        'it.haste_pct, it.name_norm AS db_hit '
        'FROM inventory_items i LEFT JOIN items it ON it.name_norm=i.name_norm '
        'WHERE i.snapshot_id=? AND i.is_empty=0 AND i.is_equipped=1', (snapshot_id,))


def _focus_effects(snapshot_id: int) -> list:
    """Best tier per effect family across ALL owned items (worn + socketed +
    Augmentation list + Activated list) — the exaltation system means what you
    OWN matters, not just what is worn; `equipped` flags what is active now."""
    return db.query(
        'SELECT e.effect_type, e.effect_name, e.effect_family, e.effect_tier, '
        'i.name AS item_name, i.location, i.is_equipped, i.is_exaltation '
        'FROM inventory_items i JOIN item_effects e ON e.name_norm=i.name_norm '
        'WHERE i.snapshot_id=? AND i.is_empty=0 '
        'ORDER BY e.effect_family, e.effect_tier DESC', (snapshot_id,))


def overview(character_id: int) -> dict:
    snap = inventory.latest_snapshot(character_id)
    totals = {s: 0 for s in PRIMARY_STATS}
    resists = {s: 0 for s in RESISTS}
    ac = hp = mana = 0
    worn_haste = 0
    matched = unmatched = 0
    caveats = []

    if snap:
        for r in _equipped_rows(snap['id']):
            # Socketed exaltations grant their EFFECT, not their stats — count
            # stats only from the worn item itself (sub_slot is the socket tier).
            if r['sub_slot'] is not None:
                continue
            if not r['db_hit']:
                unmatched += 1
                continue
            matched += 1
            try:
                st = json.loads(r['stats_json']) if r['stats_json'] else {}
            except ValueError:
                st = {}
            try:
                rs = json.loads(r['resists_json']) if r['resists_json'] else {}
            except ValueError:
                rs = {}
            for k in PRIMARY_STATS:
                totals[k] += int(st.get(k) or 0)
            for k in RESISTS:
                resists[k] += int(rs.get(k) or rs.get(k.replace('SV ', '')) or 0)
            ac += int(r['ac'] or 0)
            hp += int(r['hp'] or st.get('HP') or 0)
            mana += int(r['mana'] or st.get('MANA') or 0)
            worn_haste = max(worn_haste, int(r['haste_pct'] or 0))
        if unmatched:
            caveats.append(f'{unmatched} worn item(s) missing from the item DB — run a Data Sync; totals are incomplete.')
        caveats.append('Gear totals use base item stats; +N upgrade scaling is not in the item DB.')
        caveats.append('Worn haste shown is the highest single worn source (worn haste does not stack).')

    # focus/proc/worn/click effects: best tier per family
    focus = []
    if snap:
        seen = {}
        for e in _focus_effects(snap['id']):
            fam = e['effect_family'] or e['effect_name']
            key = (e['effect_type'], fam)
            if key not in seen:
                seen[key] = e
                focus.append(e)

    # AA from the ledger
    aa_gain = db.query_one(
        "SELECT COUNT(*) AS n, MAX(ts) AS last_ts FROM aa_ledger "
        "WHERE character_id=? AND kind='gain'", (character_id,))
    aa_bal = db.query_one(
        "SELECT balance_after FROM aa_ledger WHERE character_id=? AND kind='gain' "
        "AND balance_after IS NOT NULL ORDER BY ts DESC LIMIT 1", (character_id,))
    aa_spent = db.query_one(
        "SELECT COALESCE(SUM(points),0) AS pts, COUNT(*) AS n FROM aa_ledger "
        "WHERE character_id=? AND kind='spend'", (character_id,))
    abilities = db.query(
        "SELECT ability_name, points, ts FROM aa_ledger WHERE character_id=? "
        "AND kind='spend' ORDER BY ts DESC", (character_id,))
    unspent = aa_bal['balance_after'] if aa_bal else None
    spent = aa_spent['pts'] if aa_spent else 0

    level = db.query_one(
        'SELECT MAX(level) AS lvl FROM level_history WHERE character_id=?', (character_id,))
    highlights = {r['key']: r for r in db.query(
        'SELECT key, value_num, value_text, ts, context_json FROM highlights '
        'WHERE character_id=?', (character_id,))}
    nemesis = db.query(
        'SELECT killer, COUNT(*) AS n FROM deaths WHERE character_id=? '
        'GROUP BY killer ORDER BY n DESC LIMIT 5', (character_id,))
    manual = {r['key']: r['value'] for r in db.query(
        'SELECT key, value FROM manual_stats WHERE character_id=?', (character_id,))}

    return {
        'snapshot': snap,
        'level': level['lvl'] if level else None,
        'computed': {
            'stats': totals, 'resists': resists, 'ac': ac, 'hp': hp, 'mana': mana,
            'worn_haste': worn_haste, 'items_matched': matched, 'items_unmatched': unmatched,
        },
        'caps': _caps(),
        'focus': focus,
        'aa': {
            'earned': (unspent or 0) + spent if unspent is not None else None,
            'spent': spent, 'unspent': unspent,
            'abilities': abilities,
        },
        'highlights': highlights,
        'nemesis': nemesis,
        'manual': manual,
        'caveats': caveats,
    }


def set_manual(character_id: int, key: str, value: str) -> None:
    if value == '':
        db.execute('DELETE FROM manual_stats WHERE character_id=? AND key=?',
                   (character_id, key))
        return
    db.execute(
        'INSERT INTO manual_stats(character_id, key, value, updated_at) VALUES(?,?,?,?) '
        'ON CONFLICT(character_id, key) DO UPDATE SET value=excluded.value, '
        'updated_at=excluded.updated_at', (character_id, key, str(value), db.now()))

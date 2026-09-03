"""Exaltation matching: what effects you own, where they sit, where they could go.

Rules encoded in COMPATIBILITY_RULES are ASSUMED (the game's transfer rules are
not authoritatively documented) — the payload carries assumed=True and the UI
must say so. Adjust as real rules are learned.
"""
import json
from typing import Optional

from . import db, inventory

# Assumption set: any exaltation can move into any open socket (Slot7-Slot10) of
# an item the character can use; class gating uses the HOST item's class list
# (the character must be able to wear the host). Slot-type restrictions (e.g.
# weapon procs only into weapons) are suggested by the tools site's category
# split; enforce the weak version: proc effects prefer items with DMG.
COMPATIBILITY_RULES = {
    'assumed': True,
    'socket_range': [7, 10],
    'proc_needs_weapon': True,
}


def _effects_for(name_norm: str) -> list:
    return db.query(
        'SELECT effect_type, effect_name, effect_family, effect_tier '
        'FROM item_effects WHERE name_norm=?', (name_norm,))


def view(character_id: int) -> dict:
    snap = inventory.ensure_current(character_id)
    if not snap:
        return {'snapshot': None, 'socketed': [], 'loose': [], 'open_sockets': [],
                'all_effects': [], 'unknown': [], 'rules': COMPATIBILITY_RULES}

    rows = db.query(
        'SELECT i.*, it.class_text, it.dmg FROM inventory_items i '
        'LEFT JOIN items it ON it.name_norm=i.name_norm '
        'WHERE i.snapshot_id=? ORDER BY i.id', (snap['id'],))
    # host resolution by row order, not by Location string: paired slots
    # (Fingers, Ear, Wrist, Any Slot) repeat their Location verbatim, so a dict
    # keyed on it would hand ring 1's socket to ring 2
    inventory.attach_hosts(rows)

    socketed, loose, unknown = [], [], []
    for r in rows:
        if not r['is_exaltation'] or r['is_empty']:
            continue
        effs = _effects_for(r['name_norm'])
        entry = {
            'item': r['name'], 'name_norm': r['name_norm'], 'location': r['location'],
            'effects': effs,
        }
        if not effs:
            unknown.append(entry)
        if r['root'] == 'Augmentation':
            entry['where'] = 'loose'
            loose.append(entry)
        elif r['root'] == 'Activated':
            entry['where'] = 'activated'
            loose.append(entry)
        elif r['parent_location'] and not inventory.parent_is_container(r):
            host = r.get('_host')
            entry['where'] = 'socketed'
            entry['host_item'] = host['name'] if host else r['parent_location']
            entry['host_location'] = r['parent_location']
            entry['host_seq'] = host.get('seq') if host else None
            entry['host_equipped'] = bool(host and host['is_equipped'])
            socketed.append(entry)
        elif r['parent_location']:
            # sitting loose in a big bag's 7th+ pocket, not socketed in an item
            entry['where'] = 'storage'
            loose.append(entry)
        else:
            entry['where'] = 'other'
            loose.append(entry)

    # open sockets on real items (socket sub-slots 7..10 that are Empty)
    lo, hi = COMPATIBILITY_RULES['socket_range']
    open_sockets = []
    for r in rows:
        if not r['is_empty'] or r['sub_slot'] is None or not (lo <= r['sub_slot'] <= hi):
            continue
        if inventory.parent_is_container(r):
            continue  # a bag's empty pocket (nested bags included), not an augment socket
        host = r.get('_host')
        if not host or host['is_empty']:
            continue
        open_sockets.append({
            'location': r['location'], 'sub_slot': r['sub_slot'],
            'host_item': host['name'], 'host_location': host['location'],
            'host_seq': host.get('seq'),
            'host_equipped': bool(host['is_equipped']),
            'host_class_text': host['class_text'],
            'host_is_weapon': bool(host['dmg']),
        })

    # candidate destinations per owned effect
    for entry in socketed + loose:
        cands = []
        needs_weapon = COMPATIBILITY_RULES['proc_needs_weapon'] and any(
            e['effect_type'] == 'proc' for e in entry['effects'])
        for s in open_sockets:
            if needs_weapon and not s['host_is_weapon']:
                continue
            cands.append({'host_item': s['host_item'], 'location': s['location'],
                          'host_equipped': s['host_equipped']})
        entry['candidates'] = cands[:12]
        entry['candidate_count'] = len(cands)

    all_effects = db.query(
        'SELECT effect_name, effect_type, description, source_url FROM effects '
        'ORDER BY effect_type, effect_name')
    return {'snapshot': {'id': snap['id'], 'imported_at': snap['imported_at']},
            'socketed': socketed, 'loose': loose, 'open_sockets': open_sockets,
            'all_effects': all_effects, 'unknown': unknown,
            'rules': COMPATIBILITY_RULES}

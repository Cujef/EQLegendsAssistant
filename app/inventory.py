"""Inventory dump (/outputfile inventory) importer.

File format (verified against J:\\EQLegends\\Cujef_halas-Inventory.txt):
tab-separated, header `Location\\tName\\tID\\tCount\\tSlots`, one row per slot
including empties (Name == "Empty"). Locations are dash-joined hierarchies:

    Face                     worn item
    Face-Slot7               augment/exaltation socket ON that item
    General 8                a bag in general slot 8
    General 8-Slot3          item inside that bag
    General 8-Slot3-Slot7    augment socket on that bagged item

After the main 5-column body, the dump appends 3-column sections separated by a
blank line and a repeated sub-header ("KeyRing\\tName\\tID\\t"): KeyRing,
Augmentation (unsocketed exaltations you own!), and Activated rows carry only
Location/Name/ID. Personal-Depot## rows are the tradeskill depot.

Encoding: the live file is plain UTF-8/ASCII, but other clients have emitted
UTF-16 — sniff the BOM instead of assuming.
"""
import hashlib
import json
import re
from pathlib import Path
from typing import List, Optional

from . import db

RE_SUB_SLOT = re.compile(r'^(.*)-Slot(\d+)$')
RE_DEPOT = re.compile(r'^(.*)-Depot(\d+)$')
RE_UPGRADE = re.compile(r'\s\+(\d+)$')
EXALT_SUFFIX = ' (Exaltation)'
PARSE_REV = 3  # bump when parse_dump/normalize_name changes so identical files re-import

# Top-level locations whose items are actually worn/equipped (contribute stats).
# From the observed dump's full prefix set; General/Bank/SharedBank/KeyRing/
# Augmentation/Personal are storage or pseudo-lists. 'Activated' is the trailing
# activated-exaltations list, not a worn slot.
WORN_ROOTS = {
    'Charm', 'Ear', 'Head', 'Face', 'Neck', 'Shoulders', 'Arms', 'Back',
    'Wrist', 'Range', 'Hands', 'Primary', 'Secondary', 'Fingers', 'Chest',
    'Legs', 'Feet', 'Waist', 'Ammo', 'Held',
}


def is_container_location(location) -> bool:
    """True when `location` denotes a bag/container itself — a top-level
    General/Bank/SharedBank slot. Its SlotN children are bag POCKETS (an 8-slot
    bag has Slot7/Slot8), which must never be read as augment sockets; only
    SlotN children of non-container ITEMS are sockets."""
    if not location or '-Slot' in location:
        return False
    return location.startswith(('General ', 'Bank', 'SharedBank'))


def normalize_name(name: str) -> str:
    """Join key across dump names, wiki titles, and tools names.

    Strips the ' (Exaltation)' marker and the '+N' upgrade suffix, collapses
    whitespace, lowercases. Apostrophes are REMOVED because wiki page titles
    often drop them (dump "Djarn's Amethyst Ring" vs wiki "Djarns Amethyst
    Ring"), and a trailing '*' (the crafted-item marker) is dropped.
    Changing these rules requires tools/renormalize_keys.py on existing data
    and an inventory PARSE_REV bump.
    """
    s = str(name or '').strip()
    if s.endswith(EXALT_SUFFIX):
        s = s[: -len(EXALT_SUFFIX)]
    s = RE_UPGRADE.sub('', s)
    s = s.replace("'", '').replace('’', '').rstrip('*')
    return ' '.join(s.split()).lower()


def _decode(raw: bytes) -> str:
    if raw.startswith(b'\xff\xfe') or raw.startswith(b'\xfe\xff'):
        return raw.decode('utf-16')
    if raw.startswith(b'\xef\xbb\xbf'):
        return raw[3:].decode('utf-8', errors='replace')
    return raw.decode('utf-8', errors='replace')


def parse_dump(text: str) -> List[dict]:
    """Rows from dump text. Raises ValueError on a file that isn't an inventory dump."""
    lines = text.splitlines()
    if not lines or not lines[0].startswith('Location\t'):
        raise ValueError('not an inventory dump (missing Location header)')
    rows = []
    for ln in lines[1:]:
        if not ln.strip():
            continue
        parts = [p.strip() for p in ln.split('\t')]
        if len(parts) < 3:
            continue
        location, name = parts[0], parts[1]
        if name == 'Name' and parts[2] == 'ID':
            continue  # repeated sub-header before the trailing 3-column sections
        try:
            item_id = int(parts[2])
            # trailing sections (KeyRing/Augmentation/Activated) omit Count/Slots
            count = int(parts[3]) if len(parts) > 3 and parts[3] else 1
            slots = int(parts[4]) if len(parts) > 4 and parts[4] else 0
        except ValueError:
            continue
        m = RE_SUB_SLOT.match(location)
        parent, sub_slot = (m.group(1), int(m.group(2))) if m else (None, None)
        if parent is None:
            dm = RE_DEPOT.match(location)
            if dm:
                parent = dm.group(1)  # depot slot: parent yes, socket no
        root = location
        while True:
            rm = RE_SUB_SLOT.match(root) or RE_DEPOT.match(root)
            if not rm:
                break
            root = rm.group(1)
        um = RE_UPGRADE.search(name)
        rows.append({
            'location': location,
            'root': root,
            'parent_location': parent,
            'sub_slot': sub_slot,
            'name': name,
            'name_norm': normalize_name(name),
            'item_id': item_id,
            'count': count,
            'slots': slots,
            'is_empty': 1 if name == 'Empty' else 0,
            'is_exaltation': 1 if name.endswith(EXALT_SUFFIX) else 0,
            'upgrade_tier': int(um.group(1)) if um else 0,
            'is_equipped': 1 if root in WORN_ROOTS else 0,
        })
    return rows


def import_file(character_id: int, path: str) -> dict:
    """Import a dump file as a new snapshot. Returns a summary dict."""
    p = Path(path)
    try:
        mtime = p.stat().st_mtime
    except OSError:
        mtime = None
    return import_bytes(character_id, p.read_bytes(), str(p), mtime)


def import_bytes(character_id: int, raw: bytes, source_path: str = '',
                 file_mtime: float = None) -> dict:
    """Import dump CONTENT — the browser-upload path, where there is no server
    file to read. Same snapshot semantics as import_file."""
    rows = parse_dump(_decode(raw))
    sha = hashlib.sha256(raw).hexdigest()

    prev = db.query_one(
        'SELECT id, raw_sha256, parse_rev FROM inventory_snapshots WHERE character_id=? '
        'ORDER BY imported_at DESC LIMIT 1', (character_id,))
    if prev and prev['raw_sha256'] == sha and prev['parse_rev'] == PARSE_REV:
        return {'snapshot_id': prev['id'], 'rows': len(rows), 'unchanged': True}

    with db.tx() as c:
        cur = c.execute(
            'INSERT INTO inventory_snapshots(character_id, imported_at, source_path, '
            'file_mtime, raw_sha256, parse_rev) VALUES(?,?,?,?,?,?)',
            (character_id, db.now(), source_path, file_mtime, sha, PARSE_REV))
        snap_id = cur.lastrowid
        c.executemany(
            'INSERT INTO inventory_items(snapshot_id, location, root, parent_location, '
            'sub_slot, name, name_norm, item_id, count, slots, is_empty, is_exaltation, '
            'upgrade_tier, is_equipped) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            [(snap_id, r['location'], r['root'], r['parent_location'], r['sub_slot'],
              r['name'], r['name_norm'], r['item_id'], r['count'], r['slots'],
              r['is_empty'], r['is_exaltation'], r['upgrade_tier'], r['is_equipped'])
             for r in rows])
    non_empty = sum(1 for r in rows if not r['is_empty'])
    exalts = sum(1 for r in rows if r['is_exaltation'])
    return {'snapshot_id': snap_id, 'rows': len(rows), 'items': non_empty,
            'exaltations': exalts, 'unchanged': False}


def latest_snapshot(character_id: int) -> Optional[dict]:
    return db.query_one(
        'SELECT * FROM inventory_snapshots WHERE character_id=? '
        'ORDER BY imported_at DESC LIMIT 1', (character_id,))


def get_view(character_id: int) -> dict:
    """The Inventory page payload: snapshot meta + item rows grouped client-side."""
    snap = latest_snapshot(character_id)
    if not snap:
        return {'snapshot': None, 'items': []}
    items = db.query(
        'SELECT i.*, it.icon, (it.name_norm IS NOT NULL) AS in_item_db '
        'FROM inventory_items i LEFT JOIN items it ON it.name_norm = i.name_norm '
        'WHERE i.snapshot_id=? AND i.is_empty=0 ORDER BY i.id', (snap['id'],))
    open_sockets = [
        r for r in db.query(
            'SELECT location, root, parent_location, sub_slot FROM inventory_items '
            'WHERE snapshot_id=? AND is_empty=1 AND sub_slot >= 7 ORDER BY id',
            (snap['id'],))
        if not is_container_location(r['parent_location'])]
    return {'snapshot': snap, 'items': items, 'open_sockets': open_sockets}

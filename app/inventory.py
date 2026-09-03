"""Inventory dump (/outputfile inventory) importer.

File format (verified against a real <Name>_<server>-Inventory.txt, 933 lines):
tab-separated, header `Location\\tName\\tID\\tCount\\tSlots`, one row per slot
including empties (Name == "Empty"). Locations are dash-joined hierarchies:

    Face                     worn item
    Face-Slot7               augment/exaltation socket ON that item
    General 8                a bag in general slot 8
    General 8-Slot3          item inside that bag
    General 8-Slot3-Slot7    augment socket on that bagged item
    Bank12-Slot8             a bag INSIDE a bank bag (nesting happens)
    Bank12-Slot8-Slot7       a pocket of that nested bag — NOT a socket

Two facts the first version got wrong:
- `Location` is NOT unique. Paired slots (Ear, Wrist, Fingers, "Any Slot") and
  their -SlotN children repeat verbatim. Rows are sequential — an item row is
  followed by its sub-slot rows — so a child's host is the nearest PRECEDING
  row whose location equals its parent_location. Each row therefore carries a
  `seq` (row ordinal) and `parent_seq`.
- `Slots` is 0 for Empty, 10 for EVERY non-container item (not its socket
  count), and the capacity for a bag (4/8/12/24/50…). A 10-slot bag is
  indistinguishable by `Slots` alone, but augment sockets only ever use child
  indices {1,2,7,8,9,10} while bag pockets are contiguous 1..capacity — so a
  host is a container when its slots ∉ {0,10} OR any child index is in 3..6 or
  above 10. That rule yields exactly the 31 bags in the reference dump.

After the main 5-column body, the dump appends 3-column sections separated by a
blank line and a repeated sub-header ("KeyRing\\tName\\tID\\t"): Augmentation
(unsocketed exaltations you own), Activated, and Equipment rows carry only
Location/Name/ID. The Equipment list's meaning is not confirmed — it is shown,
never counted as worn. Personal-Depot## rows are the tradeskill depot.

Encoding: the live file is plain UTF-8/ASCII, but other clients have emitted
UTF-16 — sniff the BOM instead of assuming.
"""
import hashlib
import re
from pathlib import Path
from typing import Dict, List, Optional

from . import db

RE_SUB_SLOT = re.compile(r'^(.*)-Slot(\d+)$')
RE_DEPOT = re.compile(r'^(.*)-Depot(\d+)$')
RE_UPGRADE = re.compile(r'\s\+(\d+)$')
EXALT_SUFFIX = ' (Exaltation)'
PARSE_REV = 4  # bump when parse_dump/normalize_name changes so identical files re-import

# Top-level locations whose items are actually worn/equipped (contribute stats).
# 'Any Slot' is emitted by the live client (two of them, before Ear and before
# Ammo) — counted as worn, flagged as an assumption in the Overview caveats.
# 'Charm' has not been seen in a dump but is a real worn slot, so it stays.
# General/Bank/SharedBank/KeyRing/Augmentation/Activated/Equipment/Personal are
# storage or pseudo-lists.
WORN_ROOTS = {
    'Any Slot', 'Charm', 'Ear', 'Head', 'Face', 'Neck', 'Shoulders', 'Arms', 'Back',
    'Wrist', 'Range', 'Hands', 'Primary', 'Secondary', 'Fingers', 'Chest',
    'Legs', 'Feet', 'Waist', 'Ammo', 'Held',
}
# trailing 3-column sections (root == location, never worn)
LIST_ROOTS = ('Augmentation', 'Activated', 'Equipment')
SOCKET_MIN = 7   # augment sockets are Slot7..Slot10 (Slot1/2 are also seen, empty)


def is_container_location(location) -> bool:
    """LEGACY rule, kept as the fallback for snapshots imported before
    parent_is_container existed: True only for a TOP-LEVEL General/Bank/
    SharedBank slot. Misses nested bags — prefer parent_is_container(row)."""
    if not location or '-Slot' in location:
        return False
    return location.startswith(('General ', 'Bank', 'SharedBank'))


def parent_is_container(row) -> bool:
    """Is this row's host a bag (so the row is a pocket, never a socket)?
    Uses the per-row flag when the snapshot has it, else the legacy rule."""
    v = row.get('parent_is_container') if isinstance(row, dict) else None
    if v is not None:
        return bool(v)
    return is_container_location(row.get('parent_location'))


def normalize_name(name: str) -> str:
    """Join key across dump names, wiki titles, and tools names.

    Strips the ' (Exaltation)' marker and the '+N' upgrade suffix, collapses
    whitespace, lowercases. Apostrophes are REMOVED because wiki page titles
    often drop them (dump "Djarn's Amethyst Ring" vs wiki "Djarns Amethyst
    Ring"); the game also writes some as a backtick ("Kavruul`s Mystic Pouch"),
    so that is removed too. A trailing '*' (the crafted-item marker) is dropped.
    Changing these rules requires tools/renormalize_keys.py on existing data
    and an inventory PARSE_REV bump.
    """
    s = str(name or '').strip()
    if s.endswith(EXALT_SUFFIX):
        s = s[: -len(EXALT_SUFFIX)]
    s = RE_UPGRADE.sub('', s)
    s = s.replace("'", '').replace('’', '').replace('`', '').rstrip('*')
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
    last_seen: Dict[str, int] = {}   # location -> seq of the most recent row with it
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
        seq = len(rows)
        # nearest PRECEDING row with the parent's location (paired slots repeat)
        parent_seq = last_seen.get(parent) if parent is not None else None
        rows.append({
            'seq': seq,
            'location': location,
            'root': root,
            'parent_location': parent,
            'parent_seq': parent_seq,
            'parent_is_container': None,   # filled below once children are known
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
        last_seen[location] = seq

    # container detection per host: slots ∉ {0,10}, or a child index a socket
    # never uses (3..6, >10)
    children: Dict[int, list] = {}
    for r in rows:
        if r['parent_seq'] is not None:
            children.setdefault(r['parent_seq'], []).append(r)
    for pseq, kids in children.items():
        host = rows[pseq]
        is_bag = host['slots'] not in (0, 10) or any(
            k['sub_slot'] is not None and (3 <= k['sub_slot'] <= 6 or k['sub_slot'] > 10)
            for k in kids)
        for k in kids:
            k['parent_is_container'] = 1 if is_bag else 0
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
            'upgrade_tier, is_equipped, seq, parent_seq, parent_is_container) '
            'VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            [(snap_id, r['location'], r['root'], r['parent_location'], r['sub_slot'],
              r['name'], r['name_norm'], r['item_id'], r['count'], r['slots'],
              r['is_empty'], r['is_exaltation'], r['upgrade_tier'], r['is_equipped'],
              r['seq'], r['parent_seq'], r['parent_is_container'])
             for r in rows])
    non_empty = sum(1 for r in rows if not r['is_empty'])
    exalts = sum(1 for r in rows if r['is_exaltation'])
    return {'snapshot_id': snap_id, 'rows': len(rows), 'items': non_empty,
            'exaltations': exalts, 'unchanged': False}


def latest_snapshot(character_id: int) -> Optional[dict]:
    return db.query_one(
        'SELECT * FROM inventory_snapshots WHERE character_id=? '
        'ORDER BY imported_at DESC LIMIT 1', (character_id,))


def ensure_current(character_id: int) -> Optional[dict]:
    """The latest snapshot, re-imported first when it predates PARSE_REV and the
    character's dump file is still on disk (a browser-uploaded snapshot has no
    file: consumers fall back to the legacy rules for it). Cheap when current —
    one query — and never raises."""
    snap = latest_snapshot(character_id)
    if not snap or (snap['parse_rev'] or 0) >= PARSE_REV:
        return snap
    c = db.query_one('SELECT inventory_path FROM characters WHERE id=?', (character_id,))
    path = c['inventory_path'] if c else None
    if not path or not Path(path).is_file():
        return snap
    try:
        import_file(character_id, path)
    except (OSError, ValueError):
        return snap
    return latest_snapshot(character_id)


def attach_hosts(rows: List[dict]) -> Dict[int, dict]:
    """Set r['_host'] (the row's parent item row, or None) for rows in dump
    order. Uses parent_seq when the snapshot has it; otherwise the nearest
    preceding row with the parent's location — the same rule parse_dump uses,
    so old snapshots resolve identically. Returns {seq: row} for the caller."""
    by_seq = {}
    last_seen: Dict[str, dict] = {}
    for r in rows:
        host = None
        if r.get('parent_seq') is not None:
            host = by_seq.get(r['parent_seq'])
        elif r.get('parent_location'):
            host = last_seen.get(r['parent_location'])
        r['_host'] = host
        if r.get('seq') is not None:
            by_seq[r['seq']] = r
        last_seen[r['location']] = r
    return by_seq


def _containers(rows: List[dict]) -> list:
    """One entry per bag: capacity, used, free, nested."""
    kids: Dict[int, list] = {}
    for r in rows:
        h = r.get('_host')
        if h is None:
            continue
        kids.setdefault(id(h), (h, []))[1].append(r)
    out = []
    for host, ch in kids.values():
        is_bag = (ch[0].get('parent_is_container') if ch[0].get('parent_is_container') is not None
                  else is_container_location(host['location']))
        if not is_bag or host['is_empty']:
            continue
        used = sum(1 for k in ch if not k['is_empty'])
        cap = host['slots'] or len(ch)
        out.append({
            'seq': host.get('seq'), 'location': host['location'], 'root': host['root'],
            'name': host['name'], 'capacity': cap, 'used': used,
            'free': max(0, cap - used), 'nested': host.get('parent_location') is not None,
            'section': _section(host),
        })
    return out


def _section(row: dict) -> str:
    root = row['root']
    if row['is_equipped']:
        return 'worn'
    if root.startswith('SharedBank'):
        return 'shared'
    if root.startswith('Bank'):
        return 'bank'
    if root.startswith('General'):
        return 'bags'
    if root in LIST_ROOTS:
        return 'lists'
    if root.startswith('Personal'):
        return 'depot'
    return 'other'


def _merge_history(character_id: int) -> tuple:
    """(per-base-item merge stats, recent merges) from the log's
    "successfully merged two items" lines."""
    stats = {r['item_norm']: r for r in db.query(
        'SELECT item_norm, COUNT(*) AS merges, MAX(tier) AS max_tier, MAX(ts) AS last_ts '
        'FROM upgrade_events WHERE character_id=? GROUP BY item_norm', (character_id,))}
    recent = db.query('SELECT ts, item, item_norm, tier FROM upgrade_events '
                      'WHERE character_id=? ORDER BY ts DESC, id DESC LIMIT 60', (character_id,))
    return stats, recent


def _ladder(rows: List[dict], merges: Optional[Dict[str, dict]] = None) -> list:
    """Per base item that exists in more than one form: the worn +N tier, every
    owned copy and its tier, exaltation copies, and how many merges the log saw
    for it. Only groups with something to compare (an upgrade tier, a duplicate,
    an exaltation copy, or merge history) are listed."""
    merges = merges or {}
    groups: Dict[str, dict] = {}
    for r in rows:
        if r['is_empty'] or r['root'] in LIST_ROOTS:
            continue
        g = groups.setdefault(r['name_norm'], {
            'name_norm': r['name_norm'], 'name': None, 'worn_tier': None,
            'worn_location': None, 'copies': 0, 'exalt_copies': 0, 'tiers': set(),
            'locations': []})
        if r['is_exaltation']:
            g['exalt_copies'] += 1
        else:
            g['copies'] += 1
            g['tiers'].add(r['upgrade_tier'])
            base = RE_UPGRADE.sub('', r['name'])
            g['name'] = base if g['name'] is None else g['name']
            # worn = a top-level worn row (sockets carry the host's root but a sub_slot)
            if r['is_equipped'] and r['sub_slot'] is None:
                if g['worn_tier'] is None or r['upgrade_tier'] > g['worn_tier']:
                    g['worn_tier'] = r['upgrade_tier']
                    g['worn_location'] = r['location']
        g['locations'].append({'location': r['location'], 'tier': r['upgrade_tier'],
                               'exaltation': bool(r['is_exaltation']),
                               'section': _section(r)})
    out = []
    for g in groups.values():
        if g['name'] is None:
            continue   # only exaltation copies, no base item: nothing to ladder
        m = merges.get(g['name_norm'])
        g['merges'] = int(m['merges']) if m else 0
        g['merge_max_tier'] = m['max_tier'] if m else None
        g['last_merge_ts'] = m['last_ts'] if m else None
        if (max(g['tiers'], default=0) == 0 and g['copies'] < 2 and not g['exalt_copies']
                and not g['merges']):
            continue
        g['tiers'] = sorted(g['tiers'])
        g['best_tier'] = g['tiers'][-1] if g['tiers'] else 0
        g['upgrade_available'] = (g['worn_tier'] is not None
                                  and g['best_tier'] > g['worn_tier'])
        out.append(g)
    out.sort(key=lambda g: (-(g['worn_tier'] if g['worn_tier'] is not None else -1),
                            -g['best_tier'], g['name']))
    return out


def get_view(character_id: int) -> dict:
    """The Inventory page payload: snapshot meta + item rows grouped client-side."""
    snap = ensure_current(character_id)
    merges, recent_merges = _merge_history(character_id)
    empty = {'snapshot': None, 'items': [], 'open_sockets': [], 'containers': [],
             'space': {}, 'ladder': [], 'lists': {k.lower(): [] for k in LIST_ROOTS},
             'merge_history': recent_merges,
             'merge_totals': {'merges': sum(int(m['merges']) for m in merges.values()),
                              'items': len(merges)}}
    if not snap:
        return empty
    rows = db.query(
        'SELECT i.*, it.icon, (it.name_norm IS NOT NULL) AS in_item_db '
        'FROM inventory_items i LEFT JOIN items it ON it.name_norm = i.name_norm '
        'WHERE i.snapshot_id=? ORDER BY i.id', (snap['id'],))
    attach_hosts(rows)
    items = []
    open_sockets = []
    for r in rows:
        host = r.get('_host')
        if r['is_empty']:
            if (r['sub_slot'] is not None and r['sub_slot'] >= SOCKET_MIN
                    and not parent_is_container(r) and host and not host['is_empty']):
                open_sockets.append({
                    'location': r['location'], 'root': r['root'],
                    'parent_location': r['parent_location'], 'sub_slot': r['sub_slot'],
                    'host_name': host['name'], 'host_seq': host.get('seq'),
                    'host_equipped': bool(host['is_equipped']),
                })
            continue
        item = {k: v for k, v in r.items() if k != '_host'}
        item['host_name'] = host['name'] if host else None
        item['is_pocket'] = bool(host and parent_is_container(r))
        item['section'] = _section(r)
        items.append(item)
    containers = _containers(rows)
    space = {}
    for c in containers:
        s = space.setdefault(c['section'], {'bags': 0, 'capacity': 0, 'used': 0, 'free': 0})
        s['bags'] += 1
        s['capacity'] += c['capacity']
        s['used'] += c['used']
        s['free'] += c['free']
    lists = {k.lower(): [i for i in items if i['root'] == k] for k in LIST_ROOTS}
    return {'snapshot': snap, 'items': items, 'open_sockets': open_sockets,
            'containers': containers, 'space': space, 'ladder': _ladder(rows, merges),
            'lists': lists, 'merge_history': recent_merges,
            'merge_totals': empty['merge_totals']}

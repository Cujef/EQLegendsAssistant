"""Quest progress CRUD, the suggestions index, and inventory-driven matching.

Data source: the `quests`/`quest_steps`/`quest_item_mentions` tables filled by
the eqlwiki sync (M5). classes_json is a JSON array like ["Bard"] or ["All"].
"""
import json
from typing import List, Optional

from . import db, inventory

CLASSES = ['Bard', 'Beastlord', 'Berserker', 'Cleric', 'Druid', 'Enchanter',
           'Magician', 'Monk', 'Necromancer', 'Paladin', 'Ranger', 'Rogue',
           'Shadow Knight', 'Shaman', 'Warrior', 'Wizard']
RACES = ['Barbarian', 'Dark Elf', 'Dwarf', 'Erudite', 'Froglok', 'Gnome',
         'Half-Elf', 'Halfling', 'High Elf', 'Human', 'Iksar', 'Kerran',
         'Ogre', 'Troll', 'Wood Elf']


def _decode(row: dict) -> dict:
    for k in ('classes_json', 'races_json', 'categories_json'):
        try:
            row[k[:-5]] = json.loads(row[k]) if row.get(k) else []
        except (ValueError, TypeError):
            row[k[:-5]] = []
        row.pop(k, None)
    row.pop('raw_wikitext', None)
    return row


def list_quests(character_id: int, cls: str = '', race: str = '',
                level_min: Optional[int] = None, level_max: Optional[int] = None,
                zone: str = '', q: str = '', hide_completed: bool = False) -> List[dict]:
    rows = db.query(
        'SELECT qu.id, qu.name, qu.wiki_url, qu.start_zone, qu.quest_giver, '
        'qu.level_min, qu.level_max, qu.classes_json, qu.races_json, qu.categories_json, '
        'qu.parsed_ok, qp.status, '
        '(SELECT COUNT(*) FROM quest_steps s WHERE s.quest_id=qu.id) AS steps '
        'FROM quests qu LEFT JOIN quest_progress qp '
        'ON qp.quest_id=qu.id AND qp.character_id=? ORDER BY qu.name', (character_id,))
    out = []
    ql = q.lower()
    for r in rows:
        r = _decode(r)
        if hide_completed and r.get('status') == 'completed':
            continue
        if cls and r['classes'] and cls not in r['classes'] and 'All' not in r['classes']:
            continue
        if race and r['races'] and race not in r['races'] and 'All' not in r['races']:
            continue
        # level filter: overlap of [level_min, level_max] windows; unknown = keep
        if level_min is not None and r['level_max'] is not None and r['level_max'] < level_min:
            continue
        if level_max is not None and r['level_min'] is not None and r['level_min'] > level_max:
            continue
        if zone and (r['start_zone'] or '').lower() != zone.lower():
            continue
        if ql and ql not in r['name'].lower():
            continue
        out.append(r)
    return out


def progress_view(character_id: int) -> dict:
    tracked = db.query(
        'SELECT qu.id, qu.name, qu.wiki_url, qu.start_zone, qu.quest_giver, '
        'qu.level_min, qu.level_max, qu.classes_json, qu.races_json, qu.categories_json, '
        'qu.parsed_ok, qp.status, qp.added_at, qp.completed_at, '
        '(SELECT COUNT(*) FROM quest_steps s WHERE s.quest_id=qu.id) AS steps, '
        '(SELECT COUNT(*) FROM quest_step_progress sp WHERE sp.quest_id=qu.id '
        ' AND sp.character_id=qp.character_id AND sp.done=1) AS steps_done '
        'FROM quest_progress qp JOIN quests qu ON qu.id=qp.quest_id '
        "WHERE qp.character_id=? AND qp.status IN ('tracked','completed') "
        'ORDER BY qp.status, qu.name', (character_id,))
    return {'quests': [_decode(r) for r in tracked]}


def quest_detail(character_id: int, quest_id: int) -> Optional[dict]:
    q = db.query_one('SELECT * FROM quests WHERE id=?', (quest_id,))
    if not q:
        return None
    q = _decode(q)
    steps = db.query(
        'SELECT s.step_index, s.text, COALESCE(sp.done, 0) AS done '
        'FROM quest_steps s LEFT JOIN quest_step_progress sp '
        'ON sp.quest_id=s.quest_id AND sp.step_index=s.step_index AND sp.character_id=? '
        'WHERE s.quest_id=? ORDER BY s.step_index', (character_id, quest_id))
    prog = db.query_one(
        'SELECT status, added_at, completed_at FROM quest_progress '
        'WHERE character_id=? AND quest_id=?', (character_id, quest_id))
    q.update({'steps': steps, 'progress': prog})
    return q


def set_status(character_id: int, quest_id: int, status: str) -> None:
    if status == 'untracked':
        with db.tx() as c:
            c.execute('DELETE FROM quest_progress WHERE character_id=? AND quest_id=?',
                      (character_id, quest_id))
            c.execute('DELETE FROM quest_step_progress WHERE character_id=? AND quest_id=?',
                      (character_id, quest_id))
        return
    completed_at = db.now() if status == 'completed' else None
    db.execute(
        'INSERT INTO quest_progress(character_id, quest_id, status, added_at, completed_at) '
        'VALUES(?,?,?,?,?) ON CONFLICT(character_id, quest_id) DO UPDATE SET '
        'status=excluded.status, completed_at=excluded.completed_at',
        (character_id, quest_id, status, db.now(), completed_at))


def toggle_step(character_id: int, quest_id: int, step_index: int) -> bool:
    row = db.query_one(
        'SELECT done FROM quest_step_progress WHERE character_id=? AND quest_id=? '
        'AND step_index=?', (character_id, quest_id, step_index))
    done = 0 if (row and row['done']) else 1
    db.execute(
        'INSERT INTO quest_step_progress(character_id, quest_id, step_index, done, done_at) '
        'VALUES(?,?,?,?,?) ON CONFLICT(character_id, quest_id, step_index) DO UPDATE SET '
        'done=excluded.done, done_at=excluded.done_at',
        (character_id, quest_id, step_index, done, db.now() if done else None))
    return bool(done)


def whattodo(character_id: int) -> dict:
    """Quests touchable from current inventory + leveling rows for current level."""
    snap = inventory.latest_snapshot(character_id)
    matches = []
    if snap:
        matches = db.query(
            'SELECT qu.id, qu.name, qu.wiki_url, qu.start_zone, qu.level_min, qu.level_max, '
            'qu.classes_json, qu.races_json, qu.categories_json, qu.parsed_ok, qp.status, '
            "GROUP_CONCAT(DISTINCT i.name) AS matched_items "
            'FROM quest_item_mentions m '
            'JOIN inventory_items i ON i.name_norm=m.item_name_norm AND i.snapshot_id=? '
            ' AND i.is_empty=0 '
            'JOIN quests qu ON qu.id=m.quest_id '
            'LEFT JOIN quest_progress qp ON qp.quest_id=qu.id AND qp.character_id=? '
            'GROUP BY qu.id ORDER BY qu.name', (snap['id'], character_id))
        matches = [_decode(m) for m in matches]

    level_row = db.query_one(
        'SELECT MAX(level) AS lvl FROM level_history WHERE character_id=?', (character_id,))
    level = level_row['lvl'] if level_row and level_row['lvl'] else None
    leveling = {'level': level, 'zem_rows': [], 'hunting_rows': []}
    # keyed by KIND, not slug — the sync writer owns slug spelling and the two
    # already drifted once (wiki_api stores 'zem_list'/'hunting')
    for kind, key in (('zem', 'zem_rows'), ('leveling', 'hunting_rows')):
        g = db.query_one("SELECT parsed_json, parsed_ok FROM guides WHERE kind=? "
                         "AND parsed_ok=1 LIMIT 1", (kind,))
        if g and g['parsed_ok'] and g['parsed_json']:
            try:
                rows = json.loads(g['parsed_json'])
            except ValueError:
                continue
            if isinstance(rows, dict):
                rows = rows.get('rows') or rows.get('sections') or []
            if level:
                def in_range(r):
                    lo, hi = r.get('level_min'), r.get('level_max')
                    if lo is None and hi is None:
                        return True
                    return (lo is None or level >= lo - 3) and (hi is None or level <= hi + 3)
                rows = [r for r in rows if isinstance(r, dict) and in_range(r)]
            leveling[key] = rows[:60]
    return {'quest_matches': matches, 'leveling': leveling}

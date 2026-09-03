"""The other two /outputfile exports the Assistant can read: faction standings
and learned recipes — plus kind detection so one Import dialog takes any of the
three files.

    /outputfile faction            -> <Name>_<server>-Faction.txt
    /outputfile recipes <skill>    -> <Name>_<server>-<Skill>-Recipes.txt
    /outputfile inventory          -> <Name>_<server>-Inventory.txt   (app/inventory.py)

HONESTY: no EQ Legends sample of the first two existed when this was written.
The column meaning comes from the EverQuest client's documented behaviour
(faction: id, name, current standing, points to max; recipes: recipe id, name —
learned recipes only), so the parsers are deliberately tolerant: an optional
header line, tab OR run-of-spaces delimiters, CRLF or LF, BOM sniffing. Anything
that does not fit is reported in the import result (`skipped`) rather than
guessed at. The standing labels are the widely published EverQuest thresholds
and are flagged `assumed` in every payload that carries them.

Why the faction file matters: the LOG only ever says how much a standing moved.
The file gives the absolute number, so the Factions page can show where you
stand and estimate "now" as file value + log movement since the import.
"""
import re
from typing import Dict, List, Optional

from . import db, inventory, tradeskills

RE_OUTPUTFILE = re.compile(
    r'^(?P<name>\w+)_(?P<server>\w+)-(?:(?P<inv>Inventory)|(?P<fac>Faction)|'
    r'(?:(?P<skill>[A-Za-z ]+)-)?(?P<rec>Recipes))\.txt$', re.I)
RE_INT = re.compile(r'^-?\d+$')
RE_SPLIT = re.compile(r'\t|\s{2,}')   # tab-separated, or aligned with runs of spaces

# EverQuest's published standing bands (live client, -2000..2000). ASSUMED for EQL.
STANDING_BANDS = [
    (1100, 'Ally'), (750, 'Warmly'), (500, 'Kindly'), (100, 'Amiable'),
    (0, 'Indifferent'), (-100, 'Apprehensive'), (-500, 'Dubious'),
    (-750, 'Threatening'), (-2000, 'Ready to Attack'),
]
FACTION_MAX = 2000

# the filename's skill token vs the log's skill-up name
SKILL_TOKENS = {
    'jewelcrafting': 'Jewelry Making', 'jewelry making': 'Jewelry Making',
    'poisonmaking': 'Make Poison', 'poison making': 'Make Poison', 'make poison': 'Make Poison',
}


def standing_label(value) -> Optional[str]:
    if value is None:
        return None
    for floor, label in STANDING_BANDS:
        if value >= floor:
            return label
    return STANDING_BANDS[-1][1]


def skill_from_token(token: Optional[str]) -> Optional[str]:
    """'Baking' -> 'Baking', 'Jewelcrafting' -> 'Jewelry Making', 'all' -> 'all'."""
    if not token:
        return None
    t = token.strip()
    low = t.lower()
    if low in SKILL_TOKENS:
        return SKILL_TOKENS[low]
    for skill in tradeskills.TRADESKILL_NAMES:
        if skill.lower() == low:
            return skill
    return t


def parse_outputfile_name(filename) -> Optional[dict]:
    """{'name','server','kind','skill'} from any /outputfile filename, else None."""
    base = re.split(r'[\\/]', str(filename or ''))[-1]
    m = RE_OUTPUTFILE.match(base)
    if not m:
        return None
    kind = 'inventory' if m.group('inv') else 'faction' if m.group('fac') else 'recipes'
    return {'name': m.group('name'), 'server': m.group('server'), 'kind': kind,
            'skill': skill_from_token(m.group('skill')) if kind == 'recipes' else None}


def _decode(raw: bytes) -> str:
    return inventory._decode(raw)


def _fields(line: str) -> List[str]:
    return [p.strip() for p in RE_SPLIT.split(line.strip()) if p.strip() != '']


def _fields_loose(line: str, min_fields: int) -> List[str]:
    """_fields, falling back to single-space splitting for rows written as
    "1912 Purple Trickster Circle Fly" or "5001 Knights of Truth 1250 750":
    a leading integer is the id, trailing integers are the numeric columns, the
    words between are the name."""
    f = _fields(line)
    if len(f) >= min_fields and RE_INT.match(f[0]):
        return f
    toks = line.strip().split()
    if len(toks) < 2 or not RE_INT.match(toks[0]):
        return f
    if min_fields <= 2:
        return [toks[0], ' '.join(toks[1:])]
    # faction shape: id, name..., value[, to_max]
    tail = []
    while len(toks) > 2 and RE_INT.match(toks[-1]) and len(tail) < 2:
        tail.insert(0, toks.pop())
    if not tail or len(toks) < 2:
        return f
    return [toks[0], ' '.join(toks[1:])] + tail


def detect_kind(filename: str, text: str) -> Optional[str]:
    """Filename first (the game names them unambiguously), then the content."""
    meta = parse_outputfile_name(filename)
    if meta:
        return meta['kind']
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return None
    head = lines[0]
    if head.startswith('Location\t'):
        return 'inventory'
    if 'faction' in head.lower():
        return 'faction'
    if 'recipe' in head.lower():
        return 'recipes'
    # headerless: faction rows have 3+ fields with numeric id and standing,
    # recipe rows have a numeric id and a name
    f = _fields(head)
    if len(f) >= 3 and RE_INT.match(f[0]) and RE_INT.match(f[2]):
        return 'faction'
    if len(f) >= 2 and RE_INT.match(f[0]):
        return 'recipes'
    return None


# ── faction ───────────────────────────────────────────────────────────────────
def parse_faction(text: str) -> dict:
    """rows: [{faction_id, faction, value, to_max}], skipped: [line...]."""
    rows, skipped = [], []
    for ln in text.splitlines():
        if not ln.strip():
            continue
        f = _fields_loose(ln, 3)
        if not f:
            continue
        if not RE_INT.match(f[0]):
            if rows:
                skipped.append(ln.strip())
            continue            # header (or a stray line) — never a data row
        if len(f) < 3 or not RE_INT.match(f[2]):
            # id + name + a non-numeric third column: not a standing row
            skipped.append(ln.strip())
            continue
        to_max = int(f[3]) if len(f) > 3 and RE_INT.match(f[3]) else None
        rows.append({'faction_id': int(f[0]), 'faction': f[1], 'value': int(f[2]),
                     'to_max': to_max})
    if not rows:
        raise ValueError('not a faction export (no "id  name  standing" rows found)')
    return {'rows': rows, 'skipped': skipped}


def import_faction(character_id: int, raw: bytes, source_path: str = '') -> dict:
    parsed = parse_faction(_decode(raw))
    now = db.now()
    with db.tx() as c:
        c.execute('DELETE FROM faction_standings WHERE character_id=?', (character_id,))
        c.executemany(
            'INSERT OR REPLACE INTO faction_standings(character_id, faction, faction_id, value, '
            'to_max, imported_at, source_path) VALUES(?,?,?,?,?,?,?)',
            [(character_id, r['faction'], r['faction_id'], r['value'], r['to_max'], now,
              source_path) for r in parsed['rows']])
    return {'kind': 'faction', 'rows': len(parsed['rows']), 'skipped': parsed['skipped'][:5],
            'skipped_count': len(parsed['skipped']), 'imported_at': now}


def faction_standings(character_id: int) -> Dict[str, dict]:
    return {r['faction']: r for r in db.query(
        'SELECT faction, faction_id, value, to_max, imported_at FROM faction_standings '
        'WHERE character_id=?', (character_id,))}


# ── recipes ───────────────────────────────────────────────────────────────────
def parse_recipes(text: str) -> dict:
    """rows: [{recipe_id, name}], skipped: [...]. Learned recipes only (that is
    what the game writes)."""
    rows, skipped = [], []
    for ln in text.splitlines():
        if not ln.strip():
            continue
        f = _fields_loose(ln, 2)
        if not f:
            continue
        if not RE_INT.match(f[0]):
            if rows:
                skipped.append(ln.strip())
            continue
        if len(f) < 2:
            skipped.append(ln.strip())
            continue
        rows.append({'recipe_id': int(f[0]), 'name': f[1]})
    if not rows:
        raise ValueError('not a recipes export (no "id  recipe name" rows found)')
    return {'rows': rows, 'skipped': skipped}


def import_recipes(character_id: int, raw: bytes, skill: Optional[str],
                   source_path: str = '') -> dict:
    parsed = parse_recipes(_decode(raw))
    skill = skill or 'unknown'
    now = db.now()
    with db.tx() as c:
        # a re-export of the same skill replaces that skill's list
        c.execute('DELETE FROM known_recipes WHERE character_id=? AND skill=?',
                  (character_id, skill))
        c.executemany(
            'INSERT OR REPLACE INTO known_recipes(character_id, skill, recipe_id, name, name_norm, '
            'imported_at, source_path) VALUES(?,?,?,?,?,?,?)',
            [(character_id, skill, r['recipe_id'], r['name'], inventory.normalize_name(r['name']),
              now, source_path) for r in parsed['rows']])
    return {'kind': 'recipes', 'skill': skill, 'rows': len(parsed['rows']),
            'skipped': parsed['skipped'][:5], 'skipped_count': len(parsed['skipped']),
            'imported_at': now}


def known_recipes(character_id: int) -> List[dict]:
    return db.query('SELECT skill, recipe_id, name, name_norm, imported_at FROM known_recipes '
                    'WHERE character_id=? ORDER BY skill, name', (character_id,))


# ── dispatch ──────────────────────────────────────────────────────────────────
def import_any(character_id: int, raw: bytes, filename: str = '', path: str = '') -> dict:
    """Import whichever /outputfile export this is. Raises ValueError when the
    kind cannot be told or the content does not parse as that kind."""
    text = _decode(raw)
    meta = parse_outputfile_name(filename or path)
    kind = detect_kind(filename or path, text)
    if kind == 'inventory':
        res = inventory.import_bytes(character_id, raw, source_path=filename or path or 'uploaded')
        res['kind'] = 'inventory'
        return res
    if kind == 'faction':
        return import_faction(character_id, raw, source_path=filename or path)
    if kind == 'recipes':
        return import_recipes(character_id, raw, meta['skill'] if meta else None,
                              source_path=filename or path)
    raise ValueError('not a recognised /outputfile export (expected an inventory, faction, '
                     'or recipes file — the game names them <Name>_<server>-Inventory.txt, '
                     '-Faction.txt, or -<Skill>-Recipes.txt)')

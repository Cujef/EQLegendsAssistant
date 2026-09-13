"""The other /outputfile exports the Assistant can read: faction standings,
learned recipes and achievements — plus kind detection so one Import dialog
takes any of the files.

    /outputfile faction            -> <Name>_<server>-<CLASS>-Factions.txt
    /outputfile recipes <skill>    -> <Name>_<server>-<Skill>-Recipes.txt
    /outputfile achievements       -> <Name>_<server>-Achievements.txt   (verified sample)
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
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from . import db, inventory, tradeskills

# The game's real faction export is "<Name>_<server>-<CLASS>-Factions.txt"
# (class token + plural, e.g. -PAL-Factions.txt); the documented "-Faction.txt"
# shape is accepted too.
RE_OUTPUTFILE = re.compile(
    r'^(?P<name>\w+)_(?P<server>\w+)-(?:(?P<inv>Inventory)|(?P<ach>Achievements)|'
    r'(?:(?P<cls>[A-Za-z]+)-)?(?P<fac>Factions?)|'
    r'(?:(?P<skill>[A-Za-z ]+)-)?(?P<rec>Recipes))\.txt$', re.I)
# /outputfile achievements (verified against a real Cujef_halas-Achievements.txt,
# 1,834 lines): category headers "Group: Sub" with no tab, then one line per
# achievement "C|I<TAB>Name" and its requirements "C|I<TAB><TAB>text" — some
# with a fourth "1399/10000" progress field. 494 achievements, 26 categories.
RE_ACH_CATEGORY = re.compile(r'^([^\t:]+):\s*([^\t]+)$')
RE_ACH_STATUS = re.compile(r'^[CI]$', re.I)
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
    kind = ('inventory' if m.group('inv') else 'achievements' if m.group('ach')
            else 'faction' if m.group('fac') else 'recipes')
    return {'name': m.group('name'), 'server': m.group('server'), 'kind': kind,
            'skill': skill_from_token(m.group('skill')) if kind == 'recipes' else None}


def list_exports(game_dir=None) -> List[dict]:
    """Every /outputfile export in the game folder: one scandir, entries whose
    names the game could have written. `game_dir` defaults to the configured
    install (read at call time so tests can point it elsewhere)."""
    from . import config
    d = Path(game_dir) if game_dir else config.GAME_DIR
    out = []
    try:
        with os.scandir(d) as it:
            for e in it:
                try:
                    if not e.is_file():
                        continue
                    meta = parse_outputfile_name(e.name)
                    if not meta:
                        continue
                    st = e.stat()
                except OSError:
                    continue
                out.append({**meta, 'path': str(Path(d) / e.name),
                            'mtime': st.st_mtime, 'size': st.st_size})
    except OSError:
        return []
    return out


def discover(name: str, server: str, game_dir=None, entries=None) -> List[dict]:
    """The exports belonging to one character: [{kind, skill, path, mtime, size}]."""
    entries = list_exports(game_dir) if entries is None else entries
    n, s = (name or '').lower(), (server or '').lower()
    mine = [{k: v for k, v in e.items() if k not in ('name', 'server')}
            for e in entries if e['name'].lower() == n and e['server'].lower() == s]
    mine.sort(key=lambda e: (e['kind'], e.get('skill') or ''))
    return mine


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
    if RE_ACH_CATEGORY.match(head) and len(lines) > 1 and RE_ACH_STATUS.match(lines[1].split('\t')[0]):
        return 'achievements'
    # the real header is "ID  Name  StandingValue  PointsToMax"
    if 'faction' in head.lower() or 'standing' in head.lower():
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


# ── achievements ──────────────────────────────────────────────────────────────
def parse_achievements_export(text: str) -> dict:
    """{'categories': [...], 'achievements': [{name, complete, group, sub,
    reqs: [{text, complete, progress}]}], 'skipped': [...]} — file order.
    Tolerant: tabs only (the game writes tabs), CRLF or LF, BOM, a requirement
    before any achievement is skipped and reported."""
    cats, achs, skipped = [], [], []
    group = sub = None
    cur = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip('\r')
        if not line.strip():
            continue
        if '\t' not in line:
            m = RE_ACH_CATEGORY.match(line.strip())
            if m:
                group, sub = m.group(1).strip(), m.group(2).strip()
                cats.append(f'{group}: {sub}')
                cur = None
            else:
                skipped.append(line.strip())
            continue
        parts = line.split('\t')
        status = parts[0].strip()
        if not RE_ACH_STATUS.match(status):
            skipped.append(line.strip())
            continue
        complete = status.upper() == 'C'
        if len(parts) >= 3 and parts[1] == '':
            if cur is None:
                skipped.append(line.strip())
                continue
            cur['reqs'].append({'text': parts[2].strip(), 'complete': complete,
                                'progress': parts[3].strip() if len(parts) > 3 and parts[3].strip() else None})
        elif len(parts) >= 2 and parts[1].strip():
            cur = {'name': parts[1].strip(), 'complete': complete, 'group': group, 'sub': sub,
                   'reqs': []}
            achs.append(cur)
        else:
            skipped.append(line.strip())
    if not achs:
        raise ValueError('not an achievements export (no "C|I<TAB>name" rows found)')
    return {'categories': cats, 'achievements': achs, 'skipped': skipped}


def import_achievements(character_id: int, raw: bytes, source_path: str = '') -> dict:
    """Replace this character's achievement states with the file's. The same
    name can appear under two categories (Islands of Sky Keys is under both
    Keys lists): the first occurrence wins, the flag is the same either way."""
    import json
    parsed = parse_achievements_export(_decode(raw))
    now = db.now()
    rows, seen = [], set()
    for a in parsed['achievements']:
        norm = inventory.normalize_name(a['name'])
        if norm in seen:
            continue
        seen.add(norm)
        rows.append((character_id, a['name'], norm, a['group'], a['sub'], 1 if a['complete'] else 0,
                     json.dumps(a['reqs']), now, source_path))
    with db.tx() as c:
        c.execute('DELETE FROM achievement_states WHERE character_id=?', (character_id,))
        c.executemany(
            'INSERT INTO achievement_states(character_id, name, name_norm, group_name, sub, '
            'complete, reqs_json, imported_at, source_path) VALUES(?,?,?,?,?,?,?,?,?)', rows)
    return {'kind': 'achievements', 'rows': len(rows),
            'complete': sum(1 for a in parsed['achievements'] if a['complete']),
            'categories': len(parsed['categories']), 'skipped': parsed['skipped'][:5],
            'skipped_count': len(parsed['skipped']), 'imported_at': now}


def achievement_states(character_id: int) -> List[dict]:
    import json
    out = []
    for r in db.query('SELECT name, name_norm, group_name, sub, complete, reqs_json, imported_at, '
                      'source_path FROM achievement_states WHERE character_id=?', (character_id,)):
        r = dict(r)
        try:
            r['reqs'] = json.loads(r.pop('reqs_json') or '[]')
        except ValueError:
            r['reqs'] = []
        out.append(r)
    return out


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
    if kind == 'achievements':
        return import_achievements(character_id, raw, source_path=filename or path)
    raise ValueError('not a recognised /outputfile export (expected an inventory, faction, '
                     'recipes or achievements file — the game names them '
                     '<Name>_<server>-Inventory.txt, -<CLASS>-Factions.txt, '
                     '-<Skill>-Recipes.txt, or -Achievements.txt)')

"""Achievements: what the log says you earned, joined to what the wiki says
each one takes.

Earned: `achievements` rows written by the log pipeline from
"You have completed achievement: X" (app/logscan/ext_parser.py; backfill
revision 5 replays history). The log is the ONLY source — no export file
carries achievements — so a character with no log has none, and completions
before the log began are invisible (the first log line is shown for that).

Definitions: the wiki's Category:Achievements page, synced as the guide
`achievements` (wiki_parse.parse_achievements), falling back to the bundled
app/data/achievements.json (tools/gen_achievements.py). The wiki covers the
unlock and general lists; the game's Traveler / Hunter / faction / event
achievements have no wiki entry and appear from the log alone.

Names: the log writes "Primary Class Unlock - Paladin", the wiki "Class Unlock
- Paladin"; the wiki also uses curly apostrophes. match_key() folds both.

Progress toward an unearned achievement is derived where the app already has
the data: faction maxima for race unlocks (faction export + log cap notices),
Sky rewards for class unlocks, quest status for deity unlocks, key items for
key achievements, level_history for level milestones. Everything else shows
its requirement text only.
"""
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import db, gamefiles, inventory
from .inventory import normalize_name

BUNDLED = Path(__file__).resolve().parent / 'data' / 'achievements.json'
MIN_DEFS = 50

RE_LEVEL = re.compile(r'^Level (\d+)$')
RE_FACTION_REQ = re.compile(r'^Get maximum faction with (.+?)\.?$', re.I)
RE_OBTAIN_REQ = re.compile(r'^Obtain (.+?)\.?$', re.I)
RE_QUEST_REQ = re.compile(r"^Complete the '(.+?)' (?:task|quest)", re.I)
RE_REACH_LEVEL = re.compile(r'^Reach Level (\d+)', re.I)
RE_TRAVELER = re.compile(r' Traveler$')
RE_HUNTER = re.compile(r'^Hunter of ')
RE_PROF = re.compile(r"(?:'|’)s (Combat|Casting) Proficiency, Level (\d+)$")
RE_TS_SKILL = re.compile(r'^(.+?) \((\d+)\)$')
RE_UNLOCK = re.compile(r'^(?:Primary\s+)?(Race|Class|Deity)\s+Unlock\s*[-—–]\s*(.+)$', re.I)


def req_key(text: str) -> str:
    """Join key between a wiki requirement line and the export's (same words,
    the wiki adds links and a trailing period)."""
    return re.sub(r'\s+', ' ', str(text or '').replace('’', "'")).strip().rstrip('.').lower()


# the game writes "Shadowknight" (achievements export, class unlock line); the
# wiki and app/quests.CLASSES write "Shadow Knight"
CLASS_ALIASES = {'shadowknight': 'Shadow Knight'}


def class_name(name: str) -> str:
    return CLASS_ALIASES.get(str(name or '').strip().lower(), str(name or '').strip())


def match_key(name: str) -> str:
    """Join key between log names, export names and wiki names."""
    s = str(name or '').replace('—', '-').replace('–', '-')
    s = re.sub(r'\s+', ' ', s).strip()
    s = normalize_name(s).replace('shadowknight', 'shadow knight')
    if s.startswith('primary class unlock'):
        s = s[len('primary '):]
    return s


_cache: Dict[str, object] = {'stamp': None, 'defs': [], 'meta': {}}


def load_defs() -> Tuple[List[dict], dict]:
    """(defs, meta): the synced wiki guide when it parsed, else the bundled
    snapshot; meta says which and carries a warning when falling back."""
    row = db.query_one("SELECT parsed_json, parsed_ok, fetched_at FROM guides WHERE slug='achievements'")
    warning = None
    if row and row['parsed_ok'] and row['parsed_json']:
        stamp = ('wiki', row['fetched_at'])
        if _cache['stamp'] == stamp:
            return _cache['defs'], _cache['meta']
        try:
            defs = json.loads(row['parsed_json']).get('achievements', [])
        except (ValueError, AttributeError):
            defs = []
        if len(defs) >= MIN_DEFS:
            meta = {'kind': 'wiki', 'fetched_at': row['fetched_at'], 'count': len(defs), 'warning': None}
            _cache.update(stamp=stamp, defs=defs, meta=meta)
            return defs, meta
        warning = f'the synced wiki page parsed to {len(defs)} achievements — using the bundled list'
    try:
        mtime = BUNDLED.stat().st_mtime
    except OSError:
        return [], {'kind': 'none', 'fetched_at': None, 'count': 0,
                    'warning': warning or 'no achievement list: run a Data Sync'}
    stamp = ('bundled', mtime, warning)
    if _cache['stamp'] == stamp:
        return _cache['defs'], _cache['meta']
    data = json.loads(BUNDLED.read_text('utf-8'))
    defs = data.get('achievements', [])
    meta = {'kind': 'bundled', 'fetched_at': data.get('fetched_at'), 'count': len(defs),
            'warning': warning}
    _cache.update(stamp=stamp, defs=defs, meta=meta)
    return defs, meta


def export_states(character_id: int) -> Dict[str, dict]:
    """match_key -> the /outputfile achievements row (complete flag, reqs)."""
    return {match_key(r['name']): r for r in gamefiles.achievement_states(character_id)}


def earned(character_id: int) -> Dict[str, dict]:
    """match_key -> {name, ts, via} for everything earned: the log (with a
    date) plus the achievements export (complete flag, no date — it also
    knows completions from before the log began). via: log | export | both."""
    out = {match_key(r['name']): {'name': r['name'], 'ts': r['ts'], 'via': 'log'} for r in db.query(
        'SELECT name, ts FROM achievements WHERE character_id=?', (character_id,))}
    for key, st in export_states(character_id).items():
        if not st['complete']:
            continue
        if key in out:
            out[key]['via'] = 'both'
        else:
            out[key] = {'name': st['name'], 'ts': None, 'via': 'export'}
    return out


def earned_unlocks(character_id: int, kind: str) -> Dict[str, float]:
    """{'Paladin': ts, ...} for the given unlock kind ('class', 'race', 'deity'),
    straight from the log — no wiki needed."""
    out: Dict[str, float] = {}
    prefix = f'{kind} unlock - '
    for key, e in earned(character_id).items():
        if key.startswith(prefix):
            # keep the log's own capitalisation of the unlocked thing
            raw = re.sub(r'\s+', ' ', e['name'].replace('—', '-').replace('–', '-'))
            out[class_name(raw.split('-', 1)[1])] = e['ts']
    return out


def _deity_quests(defs: List[dict]) -> Dict[str, str]:
    """quest name -> achievement name, from deity-unlock requirements."""
    out = {}
    for d in defs:
        if not d.get('unlock') or d['unlock']['kind'] != 'deity':
            continue
        for r in d['reqs']:
            m = RE_QUEST_REQ.match(r['text'])
            if m:
                out[m.group(1)] = d['name']
            elif r.get('link'):
                out[r['link']] = d['name']
    return out


def quest_completions(character_id: int) -> Dict[int, dict]:
    """quest_id -> {achievement, ts}: quests the log proves complete because
    the achievement they award is earned. Deity unlocks name their quest in
    the wiki's requirement text; nothing else maps to a quests row today."""
    defs, _ = load_defs()
    dq = _deity_quests(defs)
    if not dq:
        return {}
    got = earned(character_id)
    out: Dict[int, dict] = {}
    rows = db.query(f"SELECT id, name FROM quests WHERE name IN ({','.join('?' * len(dq))})",
                    list(dq))
    for r in rows:
        ach = dq[r['name']]
        e = got.get(match_key(ach))
        if e:
            out[r['id']] = {'achievement': e['name'], 'ts': e['ts']}
    return out


def _category(name: str) -> str:
    """Bucket for log achievements the wiki does not list."""
    if RE_LEVEL.match(name) or RE_REACH_LEVEL.match(name):
        return 'Level'
    if RE_TRAVELER.search(name):
        return 'Traveler'
    if RE_HUNTER.match(name):
        return 'Hunter'
    if RE_PROF.search(name):
        return 'Proficiency'
    if RE_TS_SKILL.match(name):
        return 'Tradeskill'
    if 'Explorer' in name:
        return 'Explorer'
    return 'Other'


def view(character_id: int) -> dict:
    defs, meta = load_defs()
    got = earned(character_id)
    states = export_states(character_id)
    # the export lists every achievement the game has (494 on the reference
    # file) against the wiki's 188: anything the wiki lacks is defined from the
    # export, with the game's own requirement lines
    wiki_keys = {match_key(d['name']) for d in defs}
    defs = list(defs)
    for key, st in states.items():
        if key in wiki_keys:
            continue
        um = RE_UNLOCK.match(st['name'])
        defs.append({
            'key': 'x-' + re.sub(r'[^a-z0-9]+', '-', key).strip('-'), 'name': st['name'],
            'group': st.get('group_name') or 'From the game', 'sub': st.get('sub') or 'Other',
            'points': None, 'desc': '',
            'reqs': [{'text': r['text'], 'link': None} for r in st['reqs']], 'notes': [],
            'unlock': ({'kind': um.group(1).lower(), 'name': class_name(um.group(2))} if um else None),
            'from_export': True,
        })
    export_meta = None
    if states:
        first = next(iter(states.values()))
        export_meta = {'imported_at': first['imported_at'], 'path': first.get('source_path'),
                       'count': len(states), 'complete': sum(1 for s in states.values() if s['complete'])}
    snap = inventory.ensure_current(character_id)
    standings = gamefiles.faction_standings(character_id)
    caps = {r['faction'] for r in db.query(
        "SELECT faction FROM faction_caps WHERE character_id=? AND direction='better'", (character_id,))}
    faction_names = {normalize_name(n): n for n in standings}
    level = db.query_one('SELECT MAX(level) AS lv FROM level_history WHERE character_id=?',
                         (character_id,))
    level = int(level['lv']) if level and level['lv'] else None
    quest_status = {r['name']: r['status'] for r in db.query(
        'SELECT qu.name, qp.status FROM quest_progress qp JOIN quests qu ON qu.id=qp.quest_id '
        'WHERE qp.character_id=?', (character_id,))}
    dq = _deity_quests(defs)
    for qname, ach in dq.items():
        if match_key(ach) in got:
            quest_status[qname] = 'completed'

    # inventory: any copy of an item (rewards and keys are no-drop; a copy proves it)
    item_norms = set()
    for d in defs:
        for r in d['reqs']:
            m = RE_OBTAIN_REQ.match(r['text'])
            if m:
                item_norms.add(normalize_name(m.group(1)))
            elif r.get('link') is None and d.get('sub') == 'Keys':
                item_norms.add(normalize_name(r['text']))
    owned = set()
    if snap and item_norms:
        marks = ','.join('?' * len(item_norms))
        owned = {r['name_norm'] for r in db.query(
            f'SELECT DISTINCT name_norm FROM inventory_items WHERE snapshot_id=? AND is_empty=0 '
            f'AND name_norm IN ({marks})', (snap['id'], *item_norms))}
    sky_done: Dict[str, bool] = {}
    if any(d.get('unlock') and d['unlock']['kind'] == 'class' for d in defs):
        from . import skyquests
        for q in skyquests.view(character_id)['quests']:
            sky_done[q['reward']['name_norm']] = q['status'] == 'done'

    def faction_maxed(name: str) -> Optional[bool]:
        s = standings.get(name) or standings.get(faction_names.get(normalize_name(name), ''))
        if s is not None:
            return bool(s['to_max'] == 0 or s['value'] >= gamefiles.FACTION_MAX)
        if name in caps:
            return True
        return None          # nothing known about this faction yet

    rows = []
    seen = set()
    for d in defs:
        key = match_key(d['name'])
        seen.add(key)
        e = got.get(key)
        st = states.get(key)
        st_reqs = {req_key(r['text']): r for r in st['reqs']} if st else {}
        reqs = []
        for r in d['reqs']:
            done: Optional[bool] = None
            src = 'derived'
            progress_text = None
            text = r['text']
            m = RE_FACTION_REQ.match(text)
            if m:
                done = faction_maxed(r.get('link') or m.group(1).strip())
            else:
                m = RE_OBTAIN_REQ.match(text)
                if m:
                    norm = normalize_name(m.group(1))
                    done = True if norm in owned else (sky_done.get(norm) if norm in sky_done else False)
                else:
                    m = RE_QUEST_REQ.match(text)
                    if m:
                        st = quest_status.get(m.group(1))
                        done = None if st is None else st == 'completed'
                    else:
                        m = RE_REACH_LEVEL.match(text)
                        if m and level is not None:
                            done = level >= int(m.group(1))
                        elif d.get('sub') == 'Keys' and snap:
                            done = normalize_name(text) in owned
            sr = st_reqs.get(req_key(text))
            if sr is not None:           # the game's own flag beats anything derived
                done = bool(sr['complete'])
                src = 'export'
                progress_text = sr.get('progress')
            if e:
                done = True          # earned: every requirement is behind you
            reqs.append({'text': text, 'link': r.get('link'), 'done': done, 'source': src,
                         'progress_text': progress_text})
        known = [r for r in reqs if r['done'] is not None]
        rows.append({
            'key': d['key'], 'name': d['name'], 'group': d.get('group') or '',
            'sub': d.get('sub') or '', 'points': d.get('points'), 'desc': d.get('desc') or '',
            'unlock': d.get('unlock'), 'notes': d.get('notes') or [],
            'earned': bool(e), 'earned_at': e['ts'] if e else None,
            'earned_via': e['via'] if e else None,
            'log_name': e['name'] if e else None,
            'reqs': reqs,
            'progress': {'done': sum(1 for r in known if r['done']), 'known': len(known),
                         'total': len(reqs)},
            'in_wiki': not d.get('from_export'),
            'in_export': st is not None,
        })
    for key, e in sorted(got.items(), key=lambda kv: kv[1]['ts'] or 0):
        if key in seen:
            continue
        cat = _category(e['name'])
        rows.append({
            'key': 'log-' + re.sub(r'[^a-z0-9]+', '-', key).strip('-'), 'name': e['name'],
            'group': 'From the log', 'sub': cat, 'points': None, 'desc': '', 'unlock': None,
            'notes': [], 'earned': True, 'earned_at': e['ts'], 'earned_via': e['via'],
            'log_name': e['name'],
            'reqs': [], 'progress': {'done': 0, 'known': 0, 'total': 0}, 'in_wiki': False,
            'in_export': False,
        })

    def unlock_list(kind: str) -> List[dict]:
        out = []
        for r in rows:
            u = r.get('unlock')
            if u and u['kind'] == kind:
                out.append({'name': u['name'], 'key': r['key'], 'earned': r['earned'],
                            'earned_at': r['earned_at'], 'progress': r['progress'],
                            'reqs': r['reqs'], 'notes': r['notes']})
        return out

    unlocks = {k: unlock_list(k) for k in ('race', 'class', 'deity')}
    first = db.query_one("SELECT value_num FROM highlights WHERE character_id=? AND key='log_first_ts'",
                         (character_id,))
    earned_rows = [r for r in rows if r['earned']]
    recent = sorted(earned_rows, key=lambda r: r['earned_at'] or 0, reverse=True)[:25]
    subs: Dict[str, dict] = {}
    for r in rows:
        s = subs.setdefault(r['sub'] or r['group'] or 'Other',
                            {'name': r['sub'] or r['group'] or 'Other', 'group': r['group'],
                             'total': 0, 'earned': 0, 'points': 0, 'points_earned': 0})
        s['total'] += 1
        s['points'] += r['points'] or 0
        if r['earned']:
            s['earned'] += 1
            s['points_earned'] += r['points'] or 0
    return {
        'source': meta,
        'export': export_meta,
        'log_first_ts': first['value_num'] if first else None,
        'has_log': bool(first),
        'totals': {
            'earned': len(earned_rows),
            'listed': len(rows),
            'in_wiki': sum(1 for r in rows if r['in_wiki']),
            'wiki_earned': sum(1 for r in rows if r['in_wiki'] and r['earned']),
            'log_only': sum(1 for r in rows if not r['in_wiki'] and not r['in_export']),
            'export_only_earned': sum(1 for r in rows if r['earned_via'] == 'export'),
            'points': sum(r['points'] or 0 for r in rows if r['in_wiki']),
            'points_earned': sum(r['points'] or 0 for r in earned_rows),
            'races': (sum(1 for u in unlocks['race'] if u['earned']), len(unlocks['race'])),
            'classes': (sum(1 for u in unlocks['class'] if u['earned']), len(unlocks['class'])),
            'deities': (sum(1 for u in unlocks['deity'] if u['earned']), len(unlocks['deity'])),
        },
        'unlocks': unlocks,
        'categories': sorted(subs.values(), key=lambda s: (s['group'] != 'Untapped Potential', s['name'])),
        'recent': [{'name': r['name'], 'sub': r['sub'], 'points': r['points'], 'ts': r['earned_at']}
                   for r in recent],
        'achievements': rows,
        'notes': {
            'source': 'Earned achievements come from your log ("You have completed achievement: …") '
                      'and from /outputfile achievements when imported — the export also knows '
                      'completions from before the log began, but carries no dates.',
            'unlock': 'Race, class and deity unlocks auto-complete for what you chose at character '
                      'creation and can be bought with unlock tokens — an unlock does not prove you '
                      'did the work.',
            'progress': 'Requirement ticks are derived: faction maxima from the faction export and '
                        'log cap notices, items from the inventory dump, quests from Quest Progress, '
                        'levels from the log. Grey means the app has no data for that requirement.',
        },
    }

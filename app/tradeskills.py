"""Tradeskill overview: skill levels from log skill-ups, per-recipe combine
history (parser v1.6.0 events), depot materials cross-referenced with the
inventory dump, and wiki guide links.

Honesty notes carried in the payload:
- a recipe's `skill` is INFERRED (the log never names the skill on a combine
  line; a "You have become better at X!" within 1 s of the combine votes for it);
- `est_depot` is an estimate: the last "(leaving N)" seen for that material,
  adjusted by later deposits/withdrawals the log recorded;
- `on_hand` comes from the latest imported dump, not from the live game.
"""
import json
from typing import Dict, Optional

from . import db, inventory

# (log skill name, wiki page title, guides.slug as the sync writer stores it —
# see app/sync/wiki_api.py GUIDES; slug and title differ, don't conflate them)
TRADESKILLS = [
    ('Alchemy', 'Skill_Alchemy', 'skill_alchemy'),
    ('Baking', 'Skill_Baking', 'skill_baking'),
    ('Blacksmithing', 'Skill_Blacksmithing', 'skill_blacksmithing'),
    ('Brewing', 'Skill_Brewing', 'skill_brewing'),
    ('Fishing', 'Skill_Fishing', 'skill_fishing'),
    ('Fletching', 'Skill_Fletching', 'skill_fletching'),
    ('Jewelry Making', 'Skill_Jewelcrafting', 'skill_jewelcrafting'),
    ('Make Poison', 'Skill_Make_Poison', 'skill_make_poison'),
    ('Pottery', 'Skill_Pottery', 'skill_pottery'),
    ('Research', 'Skill_Research', 'skill_research'),
    ('Tailoring', 'Skill_Tailoring', 'skill_tailoring'),
    ('Tinkering', 'Skill_Tinkering', 'skill_tinkering'),
]
TRADESKILL_NAMES = frozenset(s for s, _, _ in TRADESKILLS)


def _recipes(character_id: int) -> list:
    rows = db.query(
        'SELECT item, item_norm, SUM(ok) AS made, COUNT(*) - SUM(ok) AS failed, '
        'COUNT(*) AS attempts, MAX(ts) AS last_ts, SUM(capped) AS cap_hits '
        'FROM craft_events WHERE character_id=? GROUP BY item', (character_id,))
    caps = {r['item']: r for r in db.query(
        'SELECT item, first_ts, last_ts, count FROM craft_caps WHERE character_id=?',
        (character_id,))}
    skill_of: Dict[str, dict] = {}
    for r in db.query('SELECT item, skill, votes FROM craft_recipe_skill '
                      'WHERE character_id=? ORDER BY votes DESC, skill', (character_id,)):
        skill_of.setdefault(r['item'], r)   # highest votes wins
    out = []
    for r in rows:
        cap = caps.get(r['item'])
        sk = skill_of.get(r['item'])
        out.append({
            'item': r['item'], 'item_norm': r['item_norm'],
            'made': int(r['made'] or 0), 'failed': int(r['failed'] or 0),
            'attempts': int(r['attempts'] or 0),
            'rate': round(100.0 * (r['made'] or 0) / r['attempts'], 1) if r['attempts'] else None,
            'capped': ({'first_ts': cap['first_ts'], 'last_ts': cap['last_ts'],
                        'count': cap['count']} if cap else None),
            'skill': sk['skill'] if sk else None,
            'skill_votes': sk['votes'] if sk else 0,
            'last_ts': r['last_ts'],
        })
    out.sort(key=lambda x: -(x['last_ts'] or 0))
    return out


def _materials(character_id: int) -> list:
    """Depot materials the log has seen, with a depot estimate and the dump's
    on-hand count. Events are replayed in time order per material."""
    evs = db.query('SELECT ts, kind, item, item_norm, qty, left_qty FROM depot_events '
                   'WHERE character_id=? ORDER BY ts, id', (character_id,))
    if not evs:
        return []
    snap = inventory.latest_snapshot(character_id)
    on_hand = {}
    if snap:
        # exaltation copies share the base name but are not materials; depot rows
        # are the depot itself, not "on hand"
        on_hand = {r['name_norm']: int(r['c'] or 0) for r in db.query(
            "SELECT name_norm, SUM(count) AS c FROM inventory_items WHERE snapshot_id=? "
            "AND is_empty=0 AND is_exaltation=0 AND root NOT LIKE 'Personal%' "
            "GROUP BY name_norm", (snap['id'],))}
    mats: Dict[str, dict] = {}
    for e in evs:
        m = mats.setdefault(e['item_norm'], {
            'item': e['item'], 'item_norm': e['item_norm'], 'used': 0, 'consumes': 0,
            'deposited': 0, 'withdrawn': 0, 'last_left': None, 'est_depot': None,
            'last_ts': None, 'last_used_ts': None})
        m['last_ts'] = e['ts']
        if e['kind'] == 'consume':
            m['used'] += e['qty']
            m['consumes'] += 1
            m['last_left'] = e['left_qty']
            m['est_depot'] = e['left_qty']
            m['last_used_ts'] = e['ts']
        elif e['kind'] == 'deposit':
            m['deposited'] += e['qty']
            if m['est_depot'] is not None:
                m['est_depot'] += e['qty']
        elif e['kind'] == 'withdraw':
            m['withdrawn'] += e['qty']
            if m['est_depot'] is not None:
                m['est_depot'] = max(0, m['est_depot'] - e['qty'])
    out = list(mats.values())
    for m in out:
        m['on_hand'] = on_hand.get(m['item_norm'], 0)
        m['on_hand_source'] = 'dump' if snap else None
    out.sort(key=lambda x: (-x['used'], x['item']))
    return out


def view(character_id: int) -> dict:
    levels = {r['skill']: r for r in db.query(
        'SELECT skill, MAX(level) AS level, MAX(ts) AS last_ts FROM skill_levels '
        'WHERE character_id=? GROUP BY skill', (character_id,))}
    recipes = _recipes(character_id)
    # learned recipes from /outputfile recipes <skill> (app/gamefiles.py); joined to
    # the log's combines by normalized name
    from . import gamefiles   # local: gamefiles imports this module's TRADESKILL_NAMES
    known_rows = gamefiles.known_recipes(character_id)
    made_by_norm = {r['item_norm']: r for r in recipes}
    known = []
    known_norms = set()
    for k in known_rows:
        made = made_by_norm.get(k['name_norm'])
        known_norms.add(k['name_norm'])
        known.append({'skill': k['skill'], 'recipe_id': k['recipe_id'], 'name': k['name'],
                      'made': made['made'] if made else 0,
                      'attempts': made['attempts'] if made else 0,
                      'last_ts': made['last_ts'] if made else None,
                      'imported_at': k['imported_at']})
    known_by_skill: Dict[str, int] = {}
    for k in known_rows:
        known_by_skill[k['skill']] = known_by_skill.get(k['skill'], 0) + 1
    for r in recipes:
        r['known'] = r['item_norm'] in known_norms if known_rows else None
    by_skill: Dict[Optional[str], list] = {}
    for r in recipes:
        by_skill.setdefault(r['skill'], []).append(r)

    # one query for all twelve guides: this loop used to open a connection per
    # tradeskill and pull a full parsed_json blob each time
    slugs = [slug for _, _, slug in TRADESKILLS]
    ph = ','.join('?' * len(slugs))
    guides = {g['slug']: g for g in db.query(
        f'SELECT slug, title, parsed_json, parsed_ok FROM guides WHERE slug IN ({ph})', slugs)}
    out = []
    for skill, page_title, slug in TRADESKILLS:
        row = levels.get(skill)
        guide = guides.get(slug)
        craftables = []
        if guide and guide['parsed_ok'] and guide['parsed_json']:
            try:
                pj = json.loads(guide['parsed_json'])
                # best-effort: sections whose rows carry a trivial (skill) number
                lvl = row['level'] if row else 0
                for sec in (pj.get('sections') or []):
                    for item in (sec.get('rows') or sec.get('items') or []):
                        trivial = item.get('trivial') if isinstance(item, dict) else None
                        if trivial is not None and lvl and int(trivial) <= lvl + 10:
                            craftables.append(item)
            except (ValueError, TypeError, AttributeError):
                pass
        mine = by_skill.get(skill, [])
        out.append({
            'skill': skill,
            'level': row['level'] if row else None,
            'last_ts': row['last_ts'] if row else None,
            'wiki_url': f'https://eqlwiki.com/{page_title}',
            'guide_synced': bool(guide),
            'craftables': craftables[:25],
            # from the inferred recipe->skill mapping
            'recipes': len(mine),
            'combines': sum(r['attempts'] for r in mine),
            'made': sum(r['made'] for r in mine),
            'capped_recipes': sum(1 for r in mine if r['capped']),
            # from the /outputfile recipes export, when imported for this skill
            'known_recipes': known_by_skill.get(skill),
        })
    # non-tradeskill skills as a secondary table (combat/casting skills)
    other = [r for r in db.query(
        'SELECT skill, MAX(level) AS level, MAX(ts) AS last_ts FROM skill_levels '
        'WHERE character_id=? GROUP BY skill ORDER BY skill', (character_id,))
        if r['skill'] not in TRADESKILL_NAMES]
    totals = {
        'attempts': sum(r['attempts'] for r in recipes),
        'made': sum(r['made'] for r in recipes),
        'failed': sum(r['failed'] for r in recipes),
        'recipes': len(recipes),
        'capped': sum(1 for r in recipes if r['capped']),
        'unassigned': len(by_skill.get(None, [])),
    }
    return {'tradeskills': out, 'other_skills': other, 'recipes': recipes,
            'materials': _materials(character_id), 'totals': totals,
            'known_recipes': known,
            'known_totals': {'recipes': len(known), 'skills': len(known_by_skill),
                             'never_made': sum(1 for k in known if not k['attempts'])},
            'notes': {
                'skill': 'inferred from a skill-up line within 1 s of the combine',
                'est_depot': 'last "(leaving N)" seen, adjusted by later deposits/withdrawals in the log',
                'on_hand': 'from the latest imported inventory dump',
                'known': 'from /outputfile recipes <skill> (learned recipes only)',
            }}

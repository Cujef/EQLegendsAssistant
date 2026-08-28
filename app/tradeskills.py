"""Tradeskill overview: current levels from log skill-ups + wiki guide links."""
import json

from . import db

# Skill names exactly as the log prints them ("You have become better at X! (N)").
# wiki_slug -> the eqlwiki guide page for each.
TRADESKILLS = [
    ('Alchemy', 'Skill_Alchemy'),
    ('Baking', 'Skill_Baking'),
    ('Blacksmithing', 'Skill_Blacksmithing'),
    ('Brewing', 'Skill_Brewing'),
    ('Fishing', 'Skill_Fishing'),
    ('Fletching', 'Skill_Fletching'),
    ('Jewelry Making', 'Skill_Jewelcrafting'),
    ('Make Poison', 'Skill_Make_Poison'),
    ('Pottery', 'Skill_Pottery'),
    ('Research', 'Skill_Research'),
    ('Tailoring', 'Skill_Tailoring'),
    ('Tinkering', 'Skill_Tinkering'),
]


def view(character_id: int) -> dict:
    levels = {r['skill']: r for r in db.query(
        'SELECT skill, MAX(level) AS level, MAX(ts) AS last_ts FROM skill_levels '
        'WHERE character_id=? GROUP BY skill', (character_id,))}
    out = []
    for skill, slug in TRADESKILLS:
        row = levels.get(skill)
        guide = db.query_one('SELECT slug, title, parsed_json, parsed_ok FROM guides '
                             'WHERE slug=?', (slug,))
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
        out.append({
            'skill': skill,
            'level': row['level'] if row else None,
            'last_ts': row['last_ts'] if row else None,
            'wiki_url': f'https://eqlwiki.com/{slug}',
            'guide_synced': bool(guide),
            'craftables': craftables[:25],
        })
    # non-tradeskill skills as a secondary table (combat/casting skills)
    ts_names = {s for s, _ in TRADESKILLS}
    other = [r for r in db.query(
        'SELECT skill, MAX(level) AS level, MAX(ts) AS last_ts FROM skill_levels '
        'WHERE character_id=? GROUP BY skill ORDER BY skill', (character_id,))
        if r['skill'] not in ts_names]
    return {'tradeskills': out, 'other_skills': other}

"""eqlwiki.com sync (M5): run(ctx) crawls the wiki via its MediaWiki API.

Pipeline (resumable, cheap re-sync):
  inventory  enumerate the worklist — quest pages via *_Quests categories,
             item pages via embeddedin Template:Itempage, guides via a fixed
             slug list; plus the Quest_Items name set and effect-category rows.
  revisions  batched prop=revisions (50 titles/request) -> current revid per
             page; pages whose revid matches sync_pages are skipped entirely.
  fetch      batched prop=revisions content (50 pages/request) for changed
             pages; raw_pages + domain tables +
             sync_pages are written in ONE tx per page, so a cancel/crash
             resumes by skipping the already-committed pages.

All HTTP goes through ctx.fetch() (throttled ~1 req/sec by the engine). Parse
failures keep the raw text, mark parse_ok=0 + parse_error, bump ctx.errors and
continue — a bad page never kills a sync.
"""
import hashlib
import json
import re
from urllib.parse import urlencode

from .. import db
from ..inventory import normalize_name
from . import wiki_parse as wp

API_URL = wp.WIKI_BASE + '/api.php'

# The 16 EQ classes — used to map 'Bard Quests' category tags to class names;
# every other *_Quests category (zones, tradeskills, Kael Armor...) only lands
# in categories_json.
CLASSES = {
    'Bard', 'Beastlord', 'Berserker', 'Cleric', 'Druid', 'Enchanter',
    'Magician', 'Monk', 'Necromancer', 'Paladin', 'Ranger', 'Rogue',
    'Shadow Knight', 'Shaman', 'Warrior', 'Wizard',
}

# Fixed guide list: (title, slug, kind). Missing pages are skipped silently at
# the revisions phase. Focus_Effects/Weapon_Procs/Clickies are live #redirects
# to categories — stored as such, with the effect names coming from the
# category enumeration below instead.
GUIDES = [
    ('Recommended_Levels_and_ZEM_List', 'zem_list', 'zem'),
    ('Per-Level_Hunting_Guide', 'hunting', 'leveling'),
    ('Statistics', 'statistics', 'statistics'),
    ('Haste_Guide', 'haste', 'haste'),
    ('Exaltations', 'exaltations', 'exaltation'),
    ('Focus_Effects', 'focus_effects', 'reference'),
    ('Weapon_Procs', 'weapon_procs', 'reference'),
    ('Clickies', 'clickies', 'reference'),
    ('Worn_Effects', 'worn_effects', 'reference'),
    ('Tradeskills', 'tradeskills', 'tradeskill'),
    ('Skill_Alchemy', 'skill_alchemy', 'tradeskill'),
    ('Skill_Baking', 'skill_baking', 'tradeskill'),
    ('Skill_Blacksmithing', 'skill_blacksmithing', 'tradeskill'),
    ('Skill_Brewing', 'skill_brewing', 'tradeskill'),
    ('Skill_Fishing', 'skill_fishing', 'tradeskill'),
    ('Skill_Fletching', 'skill_fletching', 'tradeskill'),
    ('Skill_Jewelcrafting', 'skill_jewelcrafting', 'tradeskill'),
    ('Skill_Make_Poison', 'skill_make_poison', 'tradeskill'),
    ('Skill_Pottery', 'skill_pottery', 'tradeskill'),
    ('Skill_Tailoring', 'skill_tailoring', 'tradeskill'),
    ('Skill_Tinkering', 'skill_tinkering', 'tradeskill'),
    ('Skill_Research', 'skill_research', 'tradeskill'),
    ('Character_Classes', 'character_classes', 'reference'),
    ('Character_Races', 'character_races', 'reference'),
    ('Alternate_Advancement', 'alternate_advancement', 'reference'),
]

# effect categories -> effects.effect_type rows (names only; no page fetches)
EFFECT_CATEGORIES = [
    ('Category:Focus Effects', 'focus'),
    ('Category:Weapon Procs', 'proc'),
    ('Category:Clickies', 'click'),
    ('Category:Worn Effects', 'worn'),
]


# ── API helpers ──────────────────────────────────────────────────────────────

def _api(ctx, **params) -> dict:
    params.setdefault('format', 'json')
    params.setdefault('action', 'query')
    data = ctx.fetch(API_URL + '?' + urlencode(params))
    return json.loads(data.decode('utf-8', errors='replace'))


def _api_paged(ctx, limit_pages=None, **params):
    """Yield each response of a list= query, following 'continue' tokens."""
    cont = {}
    pages = 0
    while True:
        resp = _api(ctx, **params, **cont)
        yield resp
        pages += 1
        cont = resp.get('continue')
        if not cont or (limit_pages and pages >= limit_pages):
            return
        cont = {k: v for k, v in cont.items() if k != 'continue'}


def _fetch_contents(ctx, batch) -> dict:
    """title -> (wikitext, revid) for up to 50 worklist units in ONE request
    (plus 'continue' follow-ups when MediaWiki truncates the response).

    The worklist turned out to be ~19k pages, not ~1.4k — the wiki's "content
    articles" stat undercounts its bot-made item pages — so per-page action=raw
    would take 5+ hours at the throttle. Batched prop=revisions content is both
    ~50x fewer requests for us and less load for their shared host.
    """
    got = {}
    titles = '|'.join(u['title'] for u in batch)
    cont = {}
    while True:
        resp = _api(ctx, prop='revisions', rvprop='content|ids', rvslots='main',
                    titles=titles, **cont)
        q = resp.get('query', {})
        norm = {n['to']: n['from'] for n in q.get('normalized', [])}
        for page in q.get('pages', {}).values():
            if 'missing' in page or 'invalid' in page or not page.get('revisions'):
                continue
            rev = page['revisions'][0]
            content = (rev.get('slots', {}).get('main', {}).get('*')
                       if 'slots' in rev else rev.get('*'))
            if content is None:
                continue
            title = page['title']
            got[title] = (content, rev.get('revid'))
            got[norm.get(title, title)] = (content, rev.get('revid'))
        cont = resp.get('continue')
        if not cont:
            return got
        cont = {k: v for k, v in cont.items() if k != 'continue'}


# ── phase: inventory ─────────────────────────────────────────────────────────

def _category_members(ctx, category: str, limit_pages=None):
    """[(pageid, title)] of a category's content pages; missing category -> []."""
    out = []
    for resp in _api_paged(ctx, limit_pages=limit_pages, list='categorymembers',
                           cmtitle=category, cmlimit=500, cmnamespace=0):
        for m in resp.get('query', {}).get('categorymembers', []):
            out.append((m['pageid'], m['title']))
    return out


def _quest_categories(ctx):
    """All category names ending ' Quests' via list=allcategories (paginated)."""
    names = []
    for resp in _api_paged(ctx, list='allcategories', aclimit=500):
        for c in resp.get('query', {}).get('allcategories', []):
            name = c.get('*', '')
            if name.endswith(' Quests'):
                names.append(name)
    return names


def _build_worklist(ctx, probe: bool):
    """[{title, kind, pageid, ...}] + the Quest_Items name set. Also writes the
    effects table from the effect categories (names only — no page fetches)."""
    ctx.progress('inventory', 0, 0, current='quest categories')
    cats = _quest_categories(ctx)
    if probe:
        cats = cats[:2]

    quests = {}   # title -> {'pageid', 'categories': [...]}
    for i, cat in enumerate(cats):
        ctx.progress('inventory', i, len(cats), current='Category:' + cat)
        for pageid, title in _category_members(
                ctx, 'Category:' + cat, limit_pages=1 if probe else None):
            q = quests.setdefault(title, {'pageid': pageid, 'categories': []})
            q['categories'].append(cat)

    ctx.progress('inventory', len(cats), len(cats), current='Template:Itempage embeds')
    items = []
    for resp in _api_paged(ctx, limit_pages=1 if probe else None,
                           list='embeddedin', eititle='Template:Itempage',
                           eilimit=500, einamespace=0):
        for m in resp.get('query', {}).get('embeddedin', []):
            items.append((m['pageid'], m['title']))

    ctx.progress('inventory', len(cats), len(cats), current='Category:Quest Items')
    quest_items = {t for _, t in _category_members(
        ctx, 'Category:Quest Items', limit_pages=1 if probe else None)}

    if not probe:
        # effect name rows straight from the categories (their guide slugs are
        # #redirects to these). Members may be pages or per-effect subcategories.
        for cat, etype in EFFECT_CATEGORIES:
            ctx.progress('inventory', len(cats), len(cats), current=cat)
            rows = []
            for resp in _api_paged(ctx, list='categorymembers', cmtitle=cat,
                                   cmlimit=500, cmtype='page|subcat'):
                for m in resp.get('query', {}).get('categorymembers', []):
                    name = m['title'].split(':', 1)[-1]
                    rows.append((name, etype, wp.WIKI_BASE + '/' + cat.replace(' ', '_')))
            if rows:
                db.executemany(
                    'INSERT INTO effects(effect_name, effect_type, source_url) '
                    'VALUES(?,?,?) ON CONFLICT(effect_name) DO UPDATE SET '
                    'effect_type=excluded.effect_type, source_url=excluded.source_url',
                    rows)

    work = []
    for title, q in sorted(quests.items()):
        work.append({'title': title, 'kind': 'quest', 'pageid': q['pageid'],
                     'categories': q['categories']})
    quest_titles = set(quests)
    for pageid, title in items:
        if title not in quest_titles:      # a page can't be both; quests win
            work.append({'title': title, 'kind': 'item', 'pageid': pageid})
    for title, slug, gkind in GUIDES:
        work.append({'title': title.replace('_', ' '), 'kind': 'guide',
                     'pageid': None, 'slug': slug, 'guide_kind': gkind})

    if probe:
        by_kind = {'quest': [], 'item': [], 'guide': []}
        for w in work:
            by_kind[w['kind']].append(w)
        # items: take from the END of the batch — the lowest pageids are the
        # transcluding list pages (Class Race Quest List...), not real items
        work = by_kind['quest'][:3] + by_kind['item'][-3:] + [
            w for w in by_kind['guide']
            if w['slug'] in ('zem_list', 'statistics')]
    return work, quest_items


# ── phase: revisions ─────────────────────────────────────────────────────────

def _current_revids(ctx, work):
    """title -> (pageid, revid) via batched prop=revisions; missing pages absent."""
    revids = {}
    titles = [w['title'] for w in work]
    batches = [titles[i:i + 50] for i in range(0, len(titles), 50)]
    for bi, batch in enumerate(batches):
        ctx.progress('revisions', bi, len(batches), current=f'batch {bi + 1}/{len(batches)}')
        resp = _api(ctx, prop='revisions', rvprop='ids', titles='|'.join(batch))
        q = resp.get('query', {})
        norm = {n['to']: n['from'] for n in q.get('normalized', [])}
        for page in q.get('pages', {}).values():
            if 'missing' in page or 'invalid' in page or not page.get('revisions'):
                continue
            title = page['title']
            # map back to the worklist's spelling if the API normalized it
            revids[norm.get(title, title)] = (page['pageid'], page['revisions'][0]['revid'])
            revids[title] = (page['pageid'], page['revisions'][0]['revid'])
    return revids


# ── phase: fetch + parse + upsert ────────────────────────────────────────────

def _upsert_quest(c, unit, parsed, wikitext, url, fetched_at):
    pageid = unit['pageid']
    cat_classes = []
    for cat in unit.get('categories', []):
        base = cat[:-len(' Quests')]
        if base == 'All Classes':
            cat_classes.append('All')
        elif base in CLASSES:
            cat_classes.append(base)
    classes = list(dict.fromkeys(parsed['classes'] + cat_classes))
    # a renamed page would collide with UNIQUE(name) under a different id;
    # purge the stale row and its children (FKs are ON, no cascade)
    for row in c.execute('SELECT id FROM quests WHERE name=? AND id<>?',
                         (unit['title'], pageid)).fetchall():
        for table in ('quest_steps', 'quest_item_mentions', 'quest_progress'):
            c.execute(f'DELETE FROM {table} WHERE quest_id=?', (row['id'],))
        c.execute('DELETE FROM quests WHERE id=?', (row['id'],))
    c.execute(
        'INSERT INTO quests(id, name, wiki_url, start_zone, quest_giver, level_min, '
        'level_max, classes_json, races_json, categories_json, raw_wikitext, '
        'parsed_ok, fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,1,?) '
        'ON CONFLICT(id) DO UPDATE SET name=excluded.name, wiki_url=excluded.wiki_url, '
        'start_zone=excluded.start_zone, quest_giver=excluded.quest_giver, '
        'level_min=excluded.level_min, level_max=excluded.level_max, '
        'classes_json=excluded.classes_json, races_json=excluded.races_json, '
        'categories_json=excluded.categories_json, raw_wikitext=excluded.raw_wikitext, '
        'parsed_ok=1, fetched_at=excluded.fetched_at',
        (pageid, unit['title'], url, parsed['start_zone'], parsed['quest_giver'],
         parsed['level_min'], parsed['level_max'],
         json.dumps(classes) if classes else None,
         json.dumps(parsed['races']) if parsed['races'] else None,
         json.dumps(unit.get('categories', [])), wikitext, fetched_at))
    c.execute('DELETE FROM quest_steps WHERE quest_id=?', (pageid,))
    c.executemany('INSERT INTO quest_steps(quest_id, step_index, text) VALUES(?,?,?)',
                  [(pageid, i, t) for i, t in enumerate(parsed['steps'])])
    c.execute('DELETE FROM quest_item_mentions WHERE quest_id=?', (pageid,))
    mentions = sorted({normalize_name(t) for t in parsed['item_mentions']} - {''})
    c.executemany('INSERT OR IGNORE INTO quest_item_mentions(quest_id, item_name_norm) '
                  'VALUES(?,?)', [(pageid, m) for m in mentions])


def _upsert_item(c, unit, parsed, url, fetched_at, quest_items):
    """Merge policy: wiki wins its own columns; tools_url/drops_json (M6's) are
    preserved; source escalates 'tools' -> 'wiki+tools'."""
    name_norm = normalize_name(parsed['itemname'] or unit['title'])
    if not name_norm:
        raise ValueError('empty item name')
    prev = c.execute('SELECT source FROM items WHERE name_norm=?', (name_norm,)).fetchone()
    source = 'wiki'
    if prev and 'tools' in (prev['source'] or ''):
        source = 'wiki+tools'
    is_quest_item = 1 if unit['title'] in quest_items else 0
    flags = parsed['flags']
    stats = dict(parsed['stats'])
    for extra_key in ('wt', 'size', 'required_level', 'skill'):
        if parsed.get(extra_key) is not None:
            stats[extra_key] = parsed[extra_key]
    c.execute(
        'INSERT INTO items(name_norm, display_name, wiki_url, source, icon, slot_text, '
        'class_text, race_text, ac, dmg, delay, haste_pct, hp, mana, stats_json, '
        'resists_json, is_quest_item, lore_flag, magic_flag, raw_statsblock, '
        'parsed_ok, fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?) '
        'ON CONFLICT(name_norm) DO UPDATE SET display_name=excluded.display_name, '
        'wiki_url=excluded.wiki_url, source=?, icon=excluded.icon, '
        'slot_text=excluded.slot_text, class_text=excluded.class_text, '
        'race_text=excluded.race_text, ac=excluded.ac, dmg=excluded.dmg, '
        'delay=excluded.delay, haste_pct=excluded.haste_pct, hp=excluded.hp, '
        'mana=excluded.mana, stats_json=excluded.stats_json, '
        'resists_json=excluded.resists_json, is_quest_item=excluded.is_quest_item, '
        'lore_flag=excluded.lore_flag, magic_flag=excluded.magic_flag, '
        'raw_statsblock=excluded.raw_statsblock, parsed_ok=1, '
        'fetched_at=excluded.fetched_at',
        (name_norm, parsed['itemname'] or unit['title'], url, source, parsed['icon'],
         parsed['slot_text'], parsed['class_text'], parsed['race_text'],
         parsed['ac'], parsed['dmg'], parsed['delay'], parsed['haste_pct'],
         parsed['hp'], parsed['mana'],
         json.dumps(stats) if stats else None,
         json.dumps(parsed['resists']) if parsed['resists'] else None,
         is_quest_item, 1 if 'LORE ITEM' in flags else 0,
         1 if 'MAGIC ITEM' in flags else 0,
         parsed['raw_statsblock'], fetched_at, source))
    c.execute('DELETE FROM item_effects WHERE name_norm=?', (name_norm,))
    c.executemany(
        'INSERT OR IGNORE INTO item_effects(name_norm, effect_type, effect_name, '
        'effect_family, effect_tier, raw_line) VALUES(?,?,?,?,?,?)',
        [(name_norm, e['effect_type'], e['effect_name'], e['effect_family'],
          e['effect_tier'], e['raw_line']) for e in parsed['effects']])
    # item effect lines also seed the effects table (categories fill the rest)
    c.executemany(
        'INSERT OR IGNORE INTO effects(effect_name, effect_type, source_url) '
        'VALUES(?,?,?)',
        [(e['effect_name'], e['effect_type'], url) for e in parsed['effects']])


def _upsert_guide(c, unit, wikitext, url, fetched_at):
    slug, gkind = unit['slug'], unit['guide_kind']
    title = unit['title']
    redirect = wp.redirect_target(wikitext)
    parsed_json, parsed_ok = None, 0
    if redirect:
        parsed_json, parsed_ok = {'redirect': redirect}, 1
    elif gkind == 'zem':
        rows = wp.parse_zem_guide(wikitext)
        parsed_json, parsed_ok = {'rows': rows}, 1 if rows else 0
    elif gkind == 'statistics':
        st = wp.parse_statistics(wikitext)
        parsed_json, parsed_ok = st, 1 if (st['caps'] or st['sections']) else 0
        if st['caps']:
            c.execute("DELETE FROM stat_caps WHERE source='wiki'")
            c.executemany(
                "INSERT INTO stat_caps(stat, level, cap, source, fetched_at) "
                "VALUES(?,?,?,'wiki',?)",
                [(cap['stat'], cap['level'], cap['cap'], fetched_at)
                 for cap in st['caps']])
    else:
        g = wp.parse_generic_guide(wikitext)
        parsed_json, parsed_ok = g, 1 if g['sections'] else 0
    c.execute(
        'INSERT INTO guides(slug, title, kind, raw_wikitext, parsed_json, parsed_ok, '
        'fetched_at) VALUES(?,?,?,?,?,?,?) '
        'ON CONFLICT(slug) DO UPDATE SET title=excluded.title, kind=excluded.kind, '
        'raw_wikitext=excluded.raw_wikitext, parsed_json=excluded.parsed_json, '
        'parsed_ok=excluded.parsed_ok, fetched_at=excluded.fetched_at',
        (slug, title, gkind, wikitext,
         json.dumps(parsed_json) if parsed_json is not None else None,
         parsed_ok, fetched_at))
    return parsed_ok


def _process_page(unit, content, revid, quest_items):
    """Parse one fetched page and commit EVERYTHING for it in one tx."""
    url = wp.title_to_url(unit['title'])
    sha = hashlib.sha256(content.encode('utf-8')).hexdigest()
    fetched_at = db.now()
    parse_ok, parse_error = 1, None
    with db.tx() as c:
        c.execute('INSERT OR REPLACE INTO raw_pages(url, content, fetched_at) '
                  'VALUES(?,?,?)', (url, content, fetched_at))
        try:
            if unit['kind'] == 'quest':
                parsed = wp.parse_quest(content)
                if not parsed['has_top_table'] and not parsed['steps']:
                    parse_ok, parse_error = 0, 'no questTopTable and no steps found'
                else:
                    _upsert_quest(c, unit, parsed, content, url, fetched_at)
            elif unit['kind'] == 'item':
                parsed = wp.parse_itempage(content)
                if parsed is None:
                    # transcluding list page (Class Race Quest List...) — not an
                    # item; fine, keep it out of the unparsed report
                    parse_error = 'no Itempage template (transcluding list page)'
                else:
                    _upsert_item(c, unit, parsed, url, fetched_at, quest_items)
            else:
                parse_ok = _upsert_guide(c, unit, content, url, fetched_at)
        except Exception as e:                      # noqa: BLE001 — raw is kept
            parse_ok, parse_error = 0, f'{type(e).__name__}: {e}'
        c.execute(
            'INSERT INTO sync_pages(url, source, kind, revid, content_sha, fetched_at, '
            'parse_ok, parse_error) VALUES(?,?,?,?,?,?,?,?) '
            'ON CONFLICT(url) DO UPDATE SET revid=excluded.revid, '
            'content_sha=excluded.content_sha, fetched_at=excluded.fetched_at, '
            'parse_ok=excluded.parse_ok, parse_error=excluded.parse_error',
            (url, 'wiki', unit['kind'], revid, sha, fetched_at, parse_ok, parse_error))
    return parse_ok, parse_error


# ── entry point ──────────────────────────────────────────────────────────────

def run(ctx, _limit_pages=None):
    """Full wiki sync. _limit_pages is an internal probe knob (selftest/live
    smoke): caps enumeration breadth and the number of pages fetched."""
    probe = _limit_pages is not None
    work, quest_items = _build_worklist(ctx, probe)

    revids = _current_revids(ctx, work)
    known = {r['url']: r for r in db.query(
        "SELECT url, revid, fetched_at, parse_ok FROM sync_pages WHERE source='wiki'")}
    changed = []
    for unit in work:
        got = revids.get(unit['title'])
        if not got:
            continue          # deleted/missing page (e.g. optional guide slug)
        unit['pageid'], unit['revid'] = got
        prev = known.get(wp.title_to_url(unit['title']))
        if prev and prev['revid'] == got[1] and prev['fetched_at']:
            continue          # unchanged since last sync
        changed.append(unit)
    if probe:
        changed = changed[:_limit_pages]

    total = len(changed)
    ctx.progress('fetch', 0, total)

    def _note_fetch_failure(unit, e):
        db.execute(
            'INSERT INTO sync_pages(url, source, kind, parse_ok, parse_error) '
            'VALUES(?,?,?,0,?) ON CONFLICT(url) DO UPDATE SET '
            'parse_ok=0, parse_error=excluded.parse_error',
            (wp.title_to_url(unit['title']), 'wiki', unit['kind'],
             f'fetch failed: {e}'))

    done = 0
    BATCH = 50
    for bi in range(0, total, BATCH):
        batch = changed[bi:bi + BATCH]
        ctx.progress('fetch', done, total, current=batch[0]['title'])
        try:
            contents = _fetch_contents(ctx, batch)
        except Exception as e:
            from .engine import Cancelled
            if isinstance(e, Cancelled):
                raise
            # whole batch failed: one error, every page stays retryable
            ctx.errors += 1
            for unit in batch:
                _note_fetch_failure(unit, f'{type(e).__name__}: {e}')
            done += len(batch)
            continue
        for unit in batch:
            got = contents.get(unit['title'])
            if got is None:
                ctx.errors += 1
                _note_fetch_failure(unit, 'content missing from batch response')
                done += 1
                continue
            content, revid = got
            parse_ok, _err = _process_page(unit, content,
                                           revid or unit['revid'], quest_items)
            if not parse_ok:
                ctx.errors += 1
            done += 1
            if done % 25 == 0:
                ctx.progress('fetch', done, total, current=unit['title'])
    ctx.progress('fetch', total, total, current='')

"""eqlegendstools.com sync (M6): sitemap -> lastmod diff -> fetch/parse/store.

Pipeline (run(ctx), resumable):
  sitemap : GET /sitemap.xml through ctx.fetch (which hard-refuses the
            robots-disallowed /api/ path), classify URLs into item /
            category / bis / zone / index (the /items/weapons|gear|clickies|
            focus-effects|worn-effects/ library shells); the rest is skipped.
  diff    : refetch only URLs whose sync_pages row is missing, whose lastmod
            changed, or whose last fetch failed (fetched_at IS NULL).
  fetch   : per page ONE db.tx() writes raw_pages + parsed rows + sync_pages,
            so cancellation (ctx.check() raising between pages) resumes for
            free. Failures keep the raw page, mark parse_ok=0, bump
            ctx.errors, and CONTINUE.

items merge policy (the wiki sync writes richer stat data): if the existing
row's source contains 'wiki', tools only sets tools_url + drops_json, fills
NULL columns (COALESCE — existing non-NULL wins), and marks source
'wiki+tools'. Otherwise tools owns the row and writes everything it parsed.

Category pages are a JS shell (rendered client-side from
/assets/catalog-data/catalog-runtime.<hash>.js — verified live 2026-08-28), so
they yield no static effect list today: raw is stored, parse is a no-op, and
the effects table is filled by the wiki sync. Zone and /bis-gear/ pages are
stored raw-only for now.
"""
import hashlib
import json

from .. import db
from ..inventory import normalize_name
from . import tools_parse
from .engine import Cancelled

BASE = 'https://eqlegendstools.com'
SITEMAP_URL = BASE + '/sitemap.xml'
SOURCE = 'tools'
# items first so partial/limited runs bank the highest-value pages early
_KIND_ORDER = {'item': 0, 'category': 1, 'bis': 2, 'zone': 3, 'index': 4}


def run(ctx, _limit_pages=None):
    ctx.progress('sitemap')
    data = ctx.fetch(SITEMAP_URL)
    text = data.decode('utf-8', errors='replace')
    targets = []
    for url, lastmod in tools_parse.parse_sitemap(text):
        kind = tools_parse.classify_url(url)
        if kind:
            targets.append((url, lastmod, kind))
    with db.tx() as c:
        _store_raw(c, SITEMAP_URL, text, db.now())
        _store_page(c, SITEMAP_URL, 'sitemap', '', _sha(data), db.now(), 1, None)

    ctx.progress('diff', 0, len(targets))
    seen = {r['url']: r for r in db.query(
        'SELECT url, lastmod, fetched_at FROM sync_pages WHERE source=?', (SOURCE,))}
    changed = [t for t in targets
               if t[0] not in seen
               or seen[t[0]]['lastmod'] != t[1]
               or seen[t[0]]['fetched_at'] is None]
    changed.sort(key=lambda t: _KIND_ORDER.get(t[2], 9))
    if _limit_pages is not None:
        changed = changed[:_limit_pages]

    total = len(changed)
    for i, (url, lastmod, kind) in enumerate(changed):
        ctx.progress('fetch', i, total, current=url)
        try:
            data = ctx.fetch(url)
        except Cancelled:
            raise
        except Exception as e:
            ctx.errors += 1
            with db.tx() as c:
                # fetched_at stays NULL so the next run retries this URL
                _store_page(c, url, kind, lastmod, None, None, 0, f'fetch: {e}')
            continue
        fetched_at = db.now()
        text = data.decode('utf-8', errors='replace')
        sha = _sha(data)
        try:
            with db.tx() as c:
                _store_raw(c, url, text, fetched_at)
                ok, err = _parse_into_db(c, url, kind, text, fetched_at)
                _store_page(c, url, kind, lastmod, sha, fetched_at, ok, err)
        except Exception as e:  # parse/db surprise: keep raw, flag, continue
            ctx.errors += 1
            with db.tx() as c:
                _store_raw(c, url, text, fetched_at)
                _store_page(c, url, kind, lastmod, sha, fetched_at, 0,
                            f'{type(e).__name__}: {e}')
    ctx.progress('fetch', total, total)


def _parse_into_db(c, url, kind, text, fetched_at):
    """Parse one fetched page into its tables. Returns (parse_ok, parse_error)."""
    if kind == 'item':
        parsed = tools_parse.parse_item_page(text)
        if not parsed['name']:
            return 0, 'no item name found'
        if parsed['attr_count'] == 0:
            # a page title alone is a listing/shell page, not an item — never
            # let it become a junk items row keyed on the page title
            return 0, 'no item tooltip found (index/shell page?)'
        ok = upsert_item(c, parsed, url, fetched_at)
        return ok, None
    if kind == 'category':
        etype = tools_parse.CATEGORY_TYPES[_path_of(url)]
        for eff in tools_parse.parse_category_page(text):
            c.execute(
                'INSERT INTO effects(effect_name, effect_type, description, source_url) '
                'VALUES(?,?,?,?) ON CONFLICT(effect_name) DO UPDATE SET '
                'effect_type=excluded.effect_type, '
                'description=COALESCE(excluded.description, description), '
                'source_url=excluded.source_url',
                (eff['name'], etype, eff.get('description'), url))
        return 1, None  # empty list expected: live pages are a JS shell
    return 1, None  # zone / bis / index: raw-only for now


def upsert_item(c, parsed, url, fetched_at):
    """Apply the merge policy for one parsed item page. Returns parsed_ok."""
    key = normalize_name(parsed['name'])
    ok = 1 if parsed['attr_count'] > 0 else 0
    stats_json = json.dumps(parsed['stats']) if parsed['stats'] else None
    resists_json = json.dumps(parsed['resists']) if parsed['resists'] else None
    drops_json = json.dumps(parsed['drops']) if parsed['drops'] else None
    row = c.execute('SELECT source FROM items WHERE name_norm=?', (key,)).fetchone()
    if row and 'wiki' in row['source']:
        c.execute(
            "UPDATE items SET tools_url=?, drops_json=?, source='wiki+tools', "
            'slot_text=COALESCE(slot_text,?), class_text=COALESCE(class_text,?), '
            'race_text=COALESCE(race_text,?), ac=COALESCE(ac,?), '
            'dmg=COALESCE(dmg,?), delay=COALESCE(delay,?), '
            'haste_pct=COALESCE(haste_pct,?), hp=COALESCE(hp,?), '
            'mana=COALESCE(mana,?), stats_json=COALESCE(stats_json,?), '
            'resists_json=COALESCE(resists_json,?) WHERE name_norm=?',
            (url, drops_json, parsed['slot_text'], parsed['class_text'],
             parsed['race_text'], parsed['ac'], parsed['dmg'], parsed['delay'],
             parsed['haste_pct'], parsed['hp'], parsed['mana'],
             stats_json, resists_json, key))
    else:
        vals = (parsed['name'], url, SOURCE, parsed['slot_text'],
                parsed['class_text'], parsed['race_text'], parsed['ac'],
                parsed['dmg'], parsed['delay'], parsed['haste_pct'],
                parsed['hp'], parsed['mana'], stats_json, resists_json,
                drops_json, 1 if parsed['lore'] else 0,
                1 if parsed['magic'] else 0, ok, fetched_at)
        if row:
            c.execute(
                'UPDATE items SET display_name=?, tools_url=?, source=?, '
                'slot_text=?, class_text=?, race_text=?, ac=?, dmg=?, delay=?, '
                'haste_pct=?, hp=?, mana=?, stats_json=?, resists_json=?, '
                'drops_json=?, lore_flag=?, magic_flag=?, parsed_ok=?, '
                'fetched_at=? WHERE name_norm=?', vals + (key,))
        else:
            c.execute(
                'INSERT INTO items(display_name, tools_url, source, slot_text, '
                'class_text, race_text, ac, dmg, delay, haste_pct, hp, mana, '
                'stats_json, resists_json, drops_json, lore_flag, magic_flag, '
                'parsed_ok, fetched_at, name_norm) VALUES '
                '(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', vals + (key,))
    for e in parsed['effects']:
        c.execute(
            'INSERT OR REPLACE INTO item_effects(name_norm, effect_type, '
            'effect_name, effect_family, effect_tier, raw_line) VALUES(?,?,?,?,?,?)',
            (key, e['type'], e['name'], e['family'], e['tier'], e['raw']))
    return ok


def _store_raw(c, url, text, fetched_at):
    c.execute('INSERT OR REPLACE INTO raw_pages(url, content, fetched_at) '
              'VALUES(?,?,?)', (url, text, fetched_at))


def _store_page(c, url, kind, lastmod, sha, fetched_at, parse_ok, parse_error):
    c.execute(
        'INSERT OR REPLACE INTO sync_pages(url, source, kind, lastmod, '
        'content_sha, fetched_at, parse_ok, parse_error) VALUES(?,?,?,?,?,?,?,?)',
        (url, SOURCE, kind, lastmod, sha, fetched_at, parse_ok, parse_error))


def _path_of(url):
    from urllib.parse import urlparse
    path = urlparse(url).path
    return path if path.endswith('/') else path + '/'


def _sha(data):
    return hashlib.sha256(data).hexdigest()

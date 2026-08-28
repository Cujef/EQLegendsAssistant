"""tools-site suite: sitemap/item/category parsers, merge policy, /api/ guard.

Fixtures are trimmed copies of live eqlegendstools.com HTML (fetched
2026-08-28): structural elements kept verbatim, boilerplate cut.
"""
import json

# ── fixtures ──────────────────────────────────────────────────────────────────

SITEMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://eqlegendstools.com/</loc>
    <lastmod>2026-08-28</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>https://eqlegendstools.com/weapon-procs/</loc>
    <lastmod>2026-08-28</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.9</priority>
  </url>
  <url>
    <loc>https://eqlegendstools.com/items/golden-efreeti-boots/</loc>
    <lastmod>2026-08-28</lastmod>
    <changefreq>weekly</changefreq>
    <priority>0.7</priority>
  </url>
  <url>
    <loc>https://eqlegendstools.com/zones/befallen/</loc>
  </url>
</urlset>
"""

# weapon with a proc (items/short-sword-of-the-ykesha/)
WEAPON_HTML = """
  <header class="site-header">
    <div class="brand-hero">
      <div class="brand-title">EQ Legends Tools</div>
      <nav class="app-nav" aria-label="Primary">
        <a class="nav-tab" href="/weapon-procs/">Procs</a>
        <a class="nav-tab" href="/clickies/">Clickies</a>
      </nav>
    </div>
  </header>
  <main>
    <nav class="breadcrumbs" aria-label="Breadcrumb">
      <a href="/">EQ Legends Tools</a>
      <span class="breadcrumb-current" aria-current="page">Short Sword of the Ykesha</span>
    </nav>
    <div class="page-title">
      <p class="eyebrow">Weapon</p>
      <h1>Short Sword of the Ykesha</h1>
    </div>
    <aside class="tooltip-card" aria-label="Short Sword of the Ykesha tooltip">
      <p class="tooltip-title"><img class="item-title-icon" src="/assets/item-icons/short-sword-of-the-ykesha.png?v=136e252a6f70" width="38" height="38" loading="eager" decoding="async" alt="" />Short Sword of the Ykesha</p>
      <div class="item-action-row">
        <button id="addToCompareBtn" class="compare-add-button" type="button" data-compare-name="Short Sword of the Ykesha" data-compare-slots="PRIMARY SECONDARY /">Add to Compare</button>
        <a class="browse-tool-link" href="/weapon-search/">Browse BiS Weapons</a>
      </div>
      <p class="tooltip-flags">MAGIC ITEM</p>
      <ul class="tooltip-lines">
        <li>Slot: PRIMARY SECONDARY</li><li>Skill: 1H Slashing Atk Delay: 24</li><li>DMG: 9</li><li>Effect: Ykesha (Combat, Casting Time: Instant) at Level 37</li><li>WT: 4.5 Size: MEDIUM</li><li>Class: BRD PAL RNG ROG SHD WAR</li><li>Drops From: Lower Guk: the ghoul lord</li>
      </ul>
      <p id="itemUpgradeNote" class="tooltip-upgrade-note">Item stats shown at upgrade level 0.</p>
    </aside>
  </main>
"""

# armor with a focus effect (items/golden-efreeti-boots/); the stray 'aa' after
# 'SV POISON: +1' is verbatim from the live page
ARMOR_HTML = """
  <main>
    <div class="page-title">
      <p class="eyebrow">Focus Effect Item, BiS Gear Item</p>
      <h1>Golden Efreeti Boots</h1>
    </div>
    <aside class="tooltip-card" aria-label="Golden Efreeti Boots tooltip">
      <p class="tooltip-title"><img class="item-title-icon" src="/assets/item-icons/golden-efreeti-boots.png?v=90b623699ca2" width="38" height="38" loading="eager" decoding="async" alt="" />Golden Efreeti Boots</p>
      <p class="tooltip-flags">MAGIC ITEM</p>
      <ul class="tooltip-lines">
        <li>Slot: FEET</li><li>AC: 5</li><li>WIS: +9 INT: +9 SV POISON: +1aa</li><li>WT: 2.5 Size: MEDIUM</li><li>Class: ALL</li><li>Focus Effect: Enhancement Haste II</li><li>Drops From: Nagafen&#39;s Lair: Efreeti Lord Djarn</li>
      </ul>
      <p id="itemUpgradeNote" class="tooltip-upgrade-note">Item stats shown at upgrade level 0.</p>
    </aside>
  </main>
"""

# clicky (items/journeymans-boots/); note lowercase 'Drops from:' — live quirk
CLICKY_HTML = """
  <main>
    <div class="page-title">
      <p class="eyebrow">Clicky Item, BiS Gear Item</p>
      <h1>Journeyman&#39;s Boots</h1>
    </div>
    <aside class="tooltip-card" aria-label="Journeyman&#39;s Boots tooltip">
      <p class="tooltip-title"><img class="item-title-icon" src="/assets/item-icons/journeymans-boots.png?v=90b623699ca2" width="38" height="38" loading="eager" decoding="async" alt="" />Journeyman&#39;s Boots</p>
      <p class="tooltip-flags">MAGIC ITEM · NODROP</p>
      <ul class="tooltip-lines">
        <li>Slot: FEET</li><li>AC: 1</li><li>Effect: JourneymanBoots (Any Slot, Casting Time: Instant)</li><li>WT: 2.5 Size: SMALL</li><li>Class: ALL</li><li>Drops from: Najena: Drelzna</li>
      </ul>
    </aside>
  </main>
"""

# multi-mob drops + LORE flag + related-items noise (items/efreeti-war-spear/):
# the related <li> links must NOT leak into the tooltip lines
SPEAR_HTML = """
  <main>
    <div class="page-title">
      <p class="eyebrow">Weapon</p>
      <h1>Efreeti War Spear</h1>
    </div>
    <aside class="tooltip-card" aria-label="Efreeti War Spear tooltip">
      <p class="tooltip-title"><img class="item-title-icon" src="/assets/item-icons/efreeti-war-spear.png?v=6b955bf48469" width="38" height="38" alt="" />Efreeti War Spear</p>
      <p class="tooltip-flags">MAGIC ITEM · LORE ITEM</p>
      <ul class="tooltip-lines">
        <li>Slot: PRIMARY</li><li>Skill: Piercing Atk Delay: 40</li><li>DMG: 15</li><li>Backstab DMG: 15</li><li>WT: 5.0 Size: MEDIUM</li><li>Class: BRD BST ROG SHM WAR</li><li>Drops From: Plane of Sky: Noble Dojorn, Overseer of Air</li>
      </ul>
    </aside>
    <div class="related-items-grid">
      <section class="related-items-card" aria-labelledby="related-zone-title">
        <h2 id="related-zone-title">Other gear from Plane of Sky</h2>
        <div data-related-list="zone"><ul id="relatedZoneItems" class="related-item-list"><li><a href="/items/golden-efreeti-chestplate/">Golden Efreeti Chestplate</a> <span>Level 46+</span></li><li><a href="/items/efreeti-long-sword/">Efreeti Long Sword</a> <span>Level 46+</span></li></ul></div>
      </section>
    </div>
  </main>
"""

# worn-haste + hp/resist stats (items/cloak-of-flames/), tooltip only
CLOAK_HTML = """
    <aside class="tooltip-card" aria-label="Cloak of Flames tooltip">
      <p class="tooltip-title"><img class="item-title-icon" src="/assets/item-icons/cloak-of-flames.png?v=b5952d4fee72" width="38" height="38" alt="" />Cloak of Flames</p>
      <p class="tooltip-flags">MAGIC ITEM</p>
      <ul class="tooltip-lines">
        <li>Slot: BACK</li><li>AC: 10</li><li>DEX: +9 AGI: +9 HP: +50</li><li>SV FIRE: +15</li><li>Haste: +36%</li><li>WT: 0.1 Size: MEDIUM</li><li>Class: ALL</li><li>Drops From: Nagafen&#39;s Lair: Lord Nagafen</li>
      </ul>
    </aside>
"""

# category pages are a JS shell — result sections are EMPTY in the HTML
# (rendered client-side from /assets/catalog-data/catalog-runtime.<hash>.js)
CATEGORY_HTML = """
  <main id="clickyPage" class="page" hidden>
    <section class="toolbar" aria-label="Search and actions">
      <div>
        <label for="searchInput">Optional text filter</label>
        <input id="searchInput" type="search" placeholder="Filter visible results..." />
      </div>
    </section>
    <section id="results" class="results" aria-live="polite"></section>
    <p class="data-disclaimer"><strong>Note:</strong> Tooltips and data are curated.</p>
  </main>
  <main id="weaponPage" class="page" hidden>
    <section id="weaponResults" class="weapon-results" aria-live="polite"></section>
  </main>
  <script data-eql-local-catalog-runtime="true" src="/assets/catalog-data/catalog-runtime.0adf87688f49.js"></script>
"""

BOOTS_URL = 'https://eqlegendstools.com/items/golden-efreeti-boots/'
YKESHA_URL = 'https://eqlegendstools.com/items/short-sword-of-the-ykesha/'


def run(check):
    _sitemap(check)
    _roman(check)
    _item_parse(check)
    _category(check)
    _merge_policy(check)
    _api_guard(check)


def _sitemap(check):
    from app.sync.tools_parse import classify_url, parse_sitemap

    entries = parse_sitemap(SITEMAP_XML)
    check('sitemap: entry count', len(entries) == 4, entries)
    check('sitemap: namespaced loc+lastmod',
          entries[1] == ('https://eqlegendstools.com/weapon-procs/', '2026-08-28'),
          entries[1])
    check('sitemap: missing lastmod -> empty',
          entries[3] == ('https://eqlegendstools.com/zones/befallen/', ''), entries[3])
    check('sitemap: bytes input ok',
          parse_sitemap(SITEMAP_XML.encode('utf-8')) == entries)
    KINDS = [
        ('https://eqlegendstools.com/', None),
        ('https://eqlegendstools.com/items/', None),
        ('https://eqlegendstools.com/items/golden-efreeti-boots/', 'item'),
        # library-index shells that live under /items/ but are NOT items
        ('https://eqlegendstools.com/items/weapons/', 'index'),
        ('https://eqlegendstools.com/items/gear/', 'index'),
        ('https://eqlegendstools.com/items/clickies/', 'index'),
        ('https://eqlegendstools.com/items/focus-effects/', 'index'),
        ('https://eqlegendstools.com/items/worn-effects/', 'index'),
        ('https://eqlegendstools.com/zones/befallen/', 'zone'),
        ('https://eqlegendstools.com/zones/', None),
        ('https://eqlegendstools.com/weapon-procs/', 'category'),
        ('https://eqlegendstools.com/focus-effects/', 'category'),
        ('https://eqlegendstools.com/clickies/', 'category'),
        ('https://eqlegendstools.com/worn-effects/', 'category'),
        ('https://eqlegendstools.com/bis-gear/', 'bis'),
        ('https://eqlegendstools.com/char-sheet/', None),
        ('https://eqlegendstools.com/weapon-search/', None),
    ]
    for url, kind in KINDS:
        check(f'classify: {url} -> {kind}', classify_url(url) == kind,
              classify_url(url))


def _roman(check):
    from app.sync.tools_parse import effect_family_tier as fam

    check('roman: II', fam('Enhancement Haste II') == ('Enhancement Haste', 2))
    check('roman: IV', fam('Improved Damage IV') == ('Improved Damage', 4))
    check('roman: IX', fam('Burnout IX') == ('Burnout', 9))
    check('roman: X', fam('Cleave X') == ('Cleave', 10))
    check('roman: I', fam('Cure Disease I') == ('Cure Disease', 1))
    check('roman: none -> tier None', fam('Ykesha') == ('Ykesha', None))
    check('roman: non-numeral suffix', fam('Word of Vigor') == ('Word of Vigor', None))
    check('roman: empty', fam('') == ('', None))


def _item_parse(check):
    from app.sync.tools_parse import parse_item_page

    w = parse_item_page(WEAPON_HTML)
    check('weapon: name', w['name'] == 'Short Sword of the Ykesha', w['name'])
    check('weapon: slot', w['slot_text'] == 'PRIMARY SECONDARY')
    check('weapon: skill/delay', w['skill'] == '1H Slashing' and w['delay'] == 24,
          (w['skill'], w['delay']))
    check('weapon: dmg', w['dmg'] == 9)
    check('weapon: class', w['class_text'] == 'BRD PAL RNG ROG SHD WAR')
    check('weapon: wt/size', w['wt'] == 4.5 and w['size'] == 'MEDIUM')
    check('weapon: magic not lore', w['magic'] and not w['lore'] and not w['nodrop'])
    check('weapon: proc effect', w['effects'] == [{
        'type': 'proc', 'name': 'Ykesha', 'family': 'Ykesha', 'tier': None,
        'raw': 'Effect: Ykesha (Combat, Casting Time: Instant) at Level 37'}],
        w['effects'])
    check('weapon: drops', w['drops'] == [{'zone': 'Lower Guk', 'mob': 'the ghoul lord'}],
          w['drops'])
    check('weapon: parsed_ok rule', w['attr_count'] > 0)

    a = parse_item_page(ARMOR_HTML)
    check('armor: name', a['name'] == 'Golden Efreeti Boots', a['name'])
    check('armor: ac', a['ac'] == 5)
    check('armor: stats', a['stats'] == {'WIS': 9, 'INT': 9}, a['stats'])
    check('armor: resist survives trailing junk', a['resists'] == {'SV POISON': 1},
          a['resists'])
    check('armor: focus effect tiered', a['effects'] == [{
        'type': 'focus', 'name': 'Enhancement Haste II',
        'family': 'Enhancement Haste', 'tier': 2,
        'raw': 'Focus Effect: Enhancement Haste II'}], a['effects'])
    check('armor: drops entity-decoded',
          a['drops'] == [{'zone': "Nagafen's Lair", 'mob': 'Efreeti Lord Djarn'}],
          a['drops'])

    j = parse_item_page(CLICKY_HTML)
    check('clicky: name entity-decoded', j['name'] == "Journeyman's Boots", j['name'])
    check('clicky: click effect', j['effects'] == [{
        'type': 'click', 'name': 'JourneymanBoots', 'family': 'JourneymanBoots',
        'tier': None, 'raw': 'Effect: JourneymanBoots (Any Slot, Casting Time: Instant)'}],
        j['effects'])
    check('clicky: lowercase Drops from', j['drops'] == [{'zone': 'Najena', 'mob': 'Drelzna'}],
          j['drops'])
    check('clicky: nodrop flag', j['nodrop'] and j['magic'])

    s = parse_item_page(SPEAR_HTML)
    check('spear: lore flag', s['lore'] and s['magic'])
    check('spear: multi-mob drops', s['drops'] == [
        {'zone': 'Plane of Sky', 'mob': 'Noble Dojorn'},
        {'zone': 'Plane of Sky', 'mob': 'Overseer of Air'}], s['drops'])
    check('spear: related-items li not leaked', len(s['lines']) == 7, s['lines'])
    check('spear: backstab line ignored', s['dmg'] == 15 and 'Backstab' not in
          str(s['stats']), (s['dmg'], s['stats']))

    c = parse_item_page(CLOAK_HTML)
    check('cloak: haste_pct', c['haste_pct'] == 36)
    check('cloak: hp column', c['hp'] == 50 and 'HP' not in c['stats'])
    check('cloak: stats', c['stats'] == {'DEX': 9, 'AGI': 9}, c['stats'])
    check('cloak: sv fire', c['resists'] == {'SV FIRE': 15})
    check('cloak: no effects', c['effects'] == [])

    empty = parse_item_page('<main><p>nothing here</p></main>')
    check('empty page: no name, zero attrs',
          empty['name'] == '' and empty['attr_count'] == 0, empty['name'])


def _category(check):
    from app.sync.tools_parse import parse_category_page

    check('category: JS shell -> no static rows',
          parse_category_page(CATEGORY_HTML) == [],
          parse_category_page(CATEGORY_HTML))


def _merge_policy(check):
    from app import db
    from app.sync import tools_parse, tools_site

    db.init()
    db.execute("DELETE FROM item_effects WHERE name_norm IN "
               "('golden efreeti boots','short sword of the ykesha')")
    db.execute("DELETE FROM items WHERE name_norm IN "
               "('golden efreeti boots','short sword of the ykesha')")

    # wiki-owned row: tools must fill gaps only, never clobber wiki values
    db.execute(
        "INSERT INTO items(name_norm, display_name, wiki_url, source, ac, "
        "stats_json, parsed_ok, fetched_at) VALUES('golden efreeti boots', "
        "'GOLDEN EFREETI BOOTS (wiki-cased)', 'https://eqlwiki.com/wiki/GEB', "
        "'wiki', 99, '{\"WIS\": 5}', 1, 111.0)")
    parsed = tools_parse.parse_item_page(ARMOR_HTML)
    with db.tx() as c:
        ok = tools_site.upsert_item(c, parsed, BOOTS_URL, 222.0)
    check('merge: parsed_ok returned', ok == 1)
    row = db.query_one("SELECT * FROM items WHERE name_norm='golden efreeti boots'")
    check('merge: source wiki+tools', row['source'] == 'wiki+tools', row['source'])
    check('merge: wiki ac preserved', row['ac'] == 99, row['ac'])
    check('merge: wiki stats preserved', row['stats_json'] == '{"WIS": 5}',
          row['stats_json'])
    check('merge: wiki display_name preserved',
          row['display_name'] == 'GOLDEN EFREETI BOOTS (wiki-cased)')
    check('merge: wiki_url untouched', row['wiki_url'] == 'https://eqlwiki.com/wiki/GEB')
    check('merge: tools_url filled', row['tools_url'] == BOOTS_URL)
    check('merge: NULL slot filled', row['slot_text'] == 'FEET', row['slot_text'])
    check('merge: NULL resists filled',
          json.loads(row['resists_json'] or 'null') == {'SV POISON': 1})
    check('merge: drops always tools-owned',
          json.loads(row['drops_json'] or 'null') == [
              {'zone': "Nagafen's Lair", 'mob': 'Efreeti Lord Djarn'}])
    effs = db.query("SELECT * FROM item_effects WHERE name_norm='golden efreeti boots'")
    check('merge: focus effect row', len(effs) == 1
          and effs[0]['effect_type'] == 'focus'
          and effs[0]['effect_family'] == 'Enhancement Haste'
          and effs[0]['effect_tier'] == 2, effs)
    # second tools pass over a merged row stays in the merge branch
    with db.tx() as c:
        tools_site.upsert_item(c, parsed, BOOTS_URL, 333.0)
    row = db.query_one("SELECT source, ac FROM items WHERE name_norm='golden efreeti boots'")
    check('merge: re-run stays wiki+tools, ac kept',
          row['source'] == 'wiki+tools' and row['ac'] == 99, row)

    # fresh row: tools owns everything
    parsed_w = tools_parse.parse_item_page(WEAPON_HTML)
    with db.tx() as c:
        tools_site.upsert_item(c, parsed_w, YKESHA_URL, 444.0)
    row = db.query_one("SELECT * FROM items WHERE name_norm='short sword of the ykesha'")
    check('fresh: source tools', row['source'] == 'tools')
    check('fresh: full write', row['display_name'] == 'Short Sword of the Ykesha'
          and row['dmg'] == 9 and row['delay'] == 24
          and row['slot_text'] == 'PRIMARY SECONDARY'
          and row['magic_flag'] == 1 and row['lore_flag'] == 0
          and row['parsed_ok'] == 1 and row['fetched_at'] == 444.0, dict(row))
    check('fresh: drops_json', json.loads(row['drops_json']) == [
        {'zone': 'Lower Guk', 'mob': 'the ghoul lord'}])
    effs = db.query("SELECT * FROM item_effects WHERE name_norm='short sword of the ykesha'")
    check('fresh: proc effect row', len(effs) == 1
          and effs[0]['effect_type'] == 'proc' and effs[0]['effect_name'] == 'Ykesha'
          and effs[0]['effect_tier'] is None, effs)
    # tools-owned row updates in place on re-sync (no duplicate, still 'tools')
    with db.tx() as c:
        tools_site.upsert_item(c, parsed_w, YKESHA_URL, 555.0)
    rows = db.query("SELECT source, fetched_at FROM items "
                    "WHERE name_norm='short sword of the ykesha'")
    check('fresh: re-sync updates in place', len(rows) == 1
          and rows[0]['source'] == 'tools' and rows[0]['fetched_at'] == 555.0, rows)

    # a page with a title but no tooltip (library shell) must NOT become a row
    shell = '<main><h1>EQ Legends Weapons - Item Library</h1><p>filters…</p></main>'
    with db.tx() as c:
        ok, err = tools_site._parse_into_db(
            c, 'https://eqlegendstools.com/items/weapons/', 'item', shell, 666.0)
    check('shell page: parse_ok=0, no junk row', ok == 0 and 'tooltip' in err
          and db.query_one("SELECT 1 AS x FROM items WHERE name_norm LIKE "
                           "'%item library%'") is None, (ok, err))


def _api_guard(check):
    from app.sync.engine import Ctx

    ctx = Ctx('tools', 0)
    try:
        ctx.fetch('https://eqlegendstools.com/api/anything')
        check('guard: /api/ fetch refused', False, 'fetch did not raise')
    except RuntimeError as e:
        check('guard: /api/ fetch refused', 'robots' in str(e), e)
    except Exception as e:  # wrong exception type = wrong failure mode
        check('guard: /api/ fetch refused', False, f'{type(e).__name__}: {e}')
    try:
        ctx.fetch('https://eqlegendstools.com/api/items?q=x')
        check('guard: /api/ with query refused', False, 'fetch did not raise')
    except RuntimeError:
        check('guard: /api/ with query refused', True)

"""PURE parsing for eqlegendstools.com pages — no I/O, no db (fixture-testable).

Real page structure (verified live 2026-08-28):
- sitemap.xml: standard <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  with <loc> + <lastmod> (site stamps every URL with the same weekly lastmod).
- Item pages are server-rendered; the stats live in ONE static block:
      <aside class="tooltip-card">
        <p class="tooltip-title">…Efreeti War Spear</p>
        <p class="tooltip-flags">MAGIC ITEM \u00b7 LORE ITEM</p>
        <ul class="tooltip-lines">
          <li>Slot: PRIMARY SECONDARY</li>
          <li>Skill: 1H Slashing Atk Delay: 24</li>       (delay inside skill line)
          <li>DMG: 9</li> <li>AC: 5</li> <li>Haste: +36%</li>
          <li>WIS: +9 INT: +9 SV POISON: +1</li>
          <li>Effect: Ykesha (Combat, Casting Time: Instant) at Level 37</li>
          <li>Effect: JourneymanBoots (Any Slot, Casting Time: Instant)</li>
          <li>Focus Effect: Enhancement Haste II</li>
          <li>Drops From: Lower Guk: the ghoul lord</li>  ('Drops from' on some pages)
        </ul>
      </aside>
  Effect type: '(Combat…)' -> proc, '(Worn…)' -> worn, other/no parenthetical
  (clickies say 'Any Slot'/'Must Equip') -> click; 'Focus Effect:' -> focus.
- Category pages (/weapon-procs/ /focus-effects/ /clickies/ /worn-effects/) are a
  JS shell: every <section id="…results"> is EMPTY in the HTML and rendered
  client-side from /assets/catalog-data/catalog-runtime.<hash>.js, so
  parse_category_page() returns [] there (kept for the day the lists go static).

Parsing is label-driven line extraction over the tooltip <li> lines, not
DOM-path assumptions, so cosmetic markup shuffles don't break it.
"""
import re
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urlparse

# category path -> effects.effect_type value
CATEGORY_TYPES = {
    '/weapon-procs/': 'proc',
    '/focus-effects/': 'focus',
    '/clickies/': 'click',
    '/worn-effects/': 'worn',
}

# /items/<slug>/ pages that are LIBRARY INDEXES, not item detail pages
# (verified in the live sitemap 2026-08-28; they render an item list shell)
ITEM_INDEX_SLUGS = {'weapons', 'gear', 'clickies', 'focus-effects', 'worn-effects'}

ROMAN = {'I': 1, 'II': 2, 'III': 3, 'IV': 4, 'V': 5,
         'VI': 6, 'VII': 7, 'VIII': 8, 'IX': 9, 'X': 10}

RE_EFFECT = re.compile(
    r'^Effect:\s*(?P<name>[^(]+?)\s*(?:\((?P<paren>[^)]*)\))?'
    r'\s*(?:at Level\s*(?P<level>\d+))?\s*$', re.I)
RE_DROPS = re.compile(r'^Drops\s+From:\s*(.*)$', re.I)
RE_DELAY = re.compile(r'Atk\s+Delay:\s*(\d+)', re.I)
RE_WT = re.compile(r'^WT:\s*([\d.]+)(?:\s+Size:\s*(\S+))?', re.I)
RE_INT = re.compile(r'[+-]?\d+')
# 'SV X' first so 'SV POISON: +1' doesn't stop at bare POISON-less matches
RE_STAT = re.compile(
    r'\b(SV [A-Z]+|STR|STA|AGI|DEX|WIS|INT|CHA|HP|MANA|END)\b:\s*([+-]?\d+)')


def effect_family_tier(name):
    """'Enhancement Haste II' -> ('Enhancement Haste', 2); no numeral -> (name, None)."""
    name = ' '.join(str(name or '').split())
    m = re.match(r'^(.*\S)\s+([IVX]+)$', name)
    if m and m.group(2) in ROMAN:
        return m.group(1), ROMAN[m.group(2)]
    return name, None


def parse_sitemap(data):
    """[(url, lastmod)] from sitemap XML (bytes or str). Namespace-agnostic."""
    root = ET.fromstring(data)
    out = []
    for el in root.iter():
        if _localname(el.tag) != 'url':
            continue
        loc = lastmod = ''
        for child in el:
            t = _localname(child.tag)
            if t == 'loc':
                loc = (child.text or '').strip()
            elif t == 'lastmod':
                lastmod = (child.text or '').strip()
        if loc:
            out.append((loc, lastmod))
    return out


def classify_url(url):
    """'item' | 'zone' | 'category' | 'bis' | 'index' | None (None = not synced)."""
    path = urlparse(url).path
    if not path.endswith('/'):
        path += '/'
    if path in CATEGORY_TYPES:
        return 'category'
    if path == '/bis-gear/':
        return 'bis'
    for prefix, kind in (('/items/', 'item'), ('/zones/', 'zone')):
        if path.startswith(prefix) and len(path) > len(prefix):
            slug = path[len(prefix):].strip('/')
            if kind == 'item' and slug in ITEM_INDEX_SLUGS:
                return 'index'  # library listing shell, raw-only
            return kind  # bare /items/ and /zones/ are index shells, skipped
    return None


class _ItemExtract(HTMLParser):
    """Collects h1, tooltip-title, tooltip-flags, and tooltip-lines <li> texts."""

    def __init__(self):
        super().__init__()  # convert_charrefs=True: entities arrive decoded
        self.h1 = []
        self.title = []
        self.flags = []
        self.lines = []
        self._in_card = False
        self._in_lines = False
        self._li = None
        self._buf = None  # h1 / title / flags collector

    def handle_starttag(self, tag, attrs):
        cls = dict(attrs).get('class') or ''
        if tag == 'aside' and 'tooltip-card' in cls:
            self._in_card = True
        elif self._in_card and tag == 'ul' and 'tooltip-lines' in cls:
            self._in_lines = True
        elif self._in_lines and tag == 'li':
            self._li = []
        elif self._in_card and tag == 'p' and 'tooltip-flags' in cls:
            self._buf = self.flags
        elif self._in_card and tag == 'p' and 'tooltip-title' in cls:
            self._buf = self.title
        elif tag == 'h1' and not self.h1:
            self._buf = self.h1

    def handle_endtag(self, tag):
        if tag == 'li' and self._li is not None:
            text = _clean(''.join(self._li))
            if text:
                self.lines.append(text)
            self._li = None
        elif tag == 'ul' and self._in_lines:
            self._in_lines = False
        elif tag == 'aside' and self._in_card:
            self._in_card = False
        elif tag in ('p', 'h1'):
            self._buf = None

    def handle_data(self, data):
        if self._li is not None:
            self._li.append(data)
        elif self._buf is not None:
            self._buf.append(data)


def parse_item_page(html_text):
    """Item dict from an /items/<slug>/ page. Keys are always present; unknown
    values are None / empty. 'attr_count' counts recognized attributes so the
    caller can apply the parsed_ok rule (name + at least one attribute)."""
    x = _ItemExtract()
    x.feed(html_text)
    x.close()
    d = {
        'name': _clean(''.join(x.h1)) or _clean(''.join(x.title)),
        'flags': [], 'magic': False, 'lore': False, 'nodrop': False,
        'slot_text': None, 'skill': None,
        'ac': None, 'dmg': None, 'delay': None, 'haste_pct': None,
        'hp': None, 'mana': None, 'wt': None, 'size': None,
        'class_text': None, 'race_text': None,
        'stats': {}, 'resists': {}, 'effects': [], 'drops': [],
        'lines': list(x.lines), 'attr_count': 0,
    }
    flags = _clean(''.join(x.flags))
    if flags:
        d['flags'] = [f.strip() for f in flags.split('\u00b7') if f.strip()]
        up = flags.upper()
        d['magic'] = 'MAGIC ITEM' in up
        d['lore'] = 'LORE ITEM' in up
        d['nodrop'] = 'NODROP' in up or 'NO DROP' in up
    for line in x.lines:
        _dispatch_line(d, line)
    return d


def _dispatch_line(d, line):
    low = line.lower()
    dm = RE_DROPS.match(line)
    if low.startswith('slot:'):
        d['slot_text'] = line[5:].strip()
        d['attr_count'] += 1
    elif low.startswith('skill:'):
        rest = line[6:].strip()
        m = RE_DELAY.search(rest)
        if m:
            d['delay'] = int(m.group(1))
            rest = rest[:m.start()].strip()
        d['skill'] = rest or None
        d['attr_count'] += 1
    elif low.startswith('atk delay:'):
        m = RE_DELAY.search(line)
        if m:
            d['delay'] = int(m.group(1))
            d['attr_count'] += 1
    elif low.startswith('backstab dmg:'):
        pass  # derived display line; base DMG is its own line
    elif low.startswith('dmg:'):
        d['dmg'] = _first_int(line[4:])
        d['attr_count'] += 1
    elif low.startswith('ac:'):
        d['ac'] = _first_int(line[3:])
        d['attr_count'] += 1
    elif low.startswith('haste:'):
        d['haste_pct'] = _first_int(line[6:])
        d['attr_count'] += 1
    elif low.startswith('wt:'):
        m = RE_WT.match(line)
        if m:
            d['wt'] = float(m.group(1))
            d['size'] = m.group(2)
    elif low.startswith('class:'):
        d['class_text'] = line[6:].strip()
        d['attr_count'] += 1
    elif low.startswith('race:'):
        d['race_text'] = line[5:].strip()
        d['attr_count'] += 1
    elif low.startswith('focus effect:'):
        _add_effect(d, 'focus', line[13:].strip(), line)
    elif low.startswith('effect:'):
        m = RE_EFFECT.match(line)
        if m:
            paren = (m.group('paren') or '').lower()
            if 'combat' in paren:
                etype = 'proc'
            elif 'worn' in paren:
                etype = 'worn'
            else:
                etype = 'click'  # 'Any Slot' / 'Must Equip' / bare clickies
            _add_effect(d, etype, m.group('name').strip(), line)
    elif dm:
        rest = dm.group(1).strip()
        if ': ' in rest:
            zone, mobs = rest.split(': ', 1)
            for mob in mobs.split(', '):
                if mob.strip():
                    d['drops'].append({'zone': zone.strip(), 'mob': mob.strip()})
        elif rest:
            d['drops'].append({'zone': rest, 'mob': ''})
        d['attr_count'] += 1
    else:
        found = False
        for label, val in RE_STAT.findall(line):
            found = True
            n = int(val)
            if label == 'HP':
                d['hp'] = n
            elif label == 'MANA':
                d['mana'] = n
            elif label.startswith('SV '):
                d['resists'][label] = n
            else:
                d['stats'][label] = n
        if found:
            d['attr_count'] += 1


def _add_effect(d, etype, name, raw):
    if not name:
        return
    family, tier = effect_family_tier(name)
    d['effects'].append({'type': etype, 'name': name,
                         'family': family, 'tier': tier, 'raw': raw})
    d['attr_count'] += 1


_VOID_TAGS = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
              'link', 'meta', 'source', 'track', 'wbr'}


class _ResultsExtract(HTMLParser):
    """Rows (li/tr text) inside any element whose id/class mentions 'results'."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self._depth = 0       # nesting inside a results container
        self._row = None

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            return  # never emits an end tag; would unbalance the depth count
        a = dict(attrs)
        marker = f"{a.get('id') or ''} {a.get('class') or ''}".lower()
        if self._depth or 'results' in marker:
            self._depth += 1
            if tag in ('li', 'tr') and self._row is None:
                self._row = []

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        if self._depth:
            if tag in ('li', 'tr') and self._row is not None:
                text = _clean(''.join(self._row))
                if text:
                    self.rows.append(text)
                self._row = None
            self._depth -= 1

    def handle_data(self, data):
        if self._row is not None:
            self._row.append(data)


def parse_category_page(html_text):
    """[{'name', 'description'}] from a category page's static result rows.
    The live pages are JS shells with empty result sections, so this returns []
    there — kept so a future static rendering is picked up for free."""
    x = _ResultsExtract()
    x.feed(html_text)
    x.close()
    out = []
    for row in x.rows:
        m = re.match(r'^(.+?)\s+[—–-]\s+(.+)$', row)
        name, desc = (m.group(1), m.group(2)) if m else (row, None)
        out.append({'name': name.strip(), 'description': desc})
    return out


def _localname(tag):
    return tag.rsplit('}', 1)[-1]


def _clean(s):
    return ' '.join(str(s or '').split())


def _first_int(s):
    m = RE_INT.search(s)
    return int(m.group(0)) if m else None

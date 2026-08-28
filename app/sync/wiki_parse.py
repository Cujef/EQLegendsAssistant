"""Pure eqlwiki.com wikitext parsers — no I/O, no db, unit-testable.

Everything here takes wikitext strings (from action=raw) and returns plain
dicts/lists. wiki_api.py owns fetching and persistence. Parsers are defensive:
malformed input returns a partial result or None, never an uncaught crash mid-
sync — wiki_api wraps each page in try/except anyway, but the cheap paths
(missing table, empty statsblock) are handled here explicitly.

Verified against live pages 2026-08-28: Singing_Short_Sword, Incandescent_Mask,
Bard_Epic_Quest, Bat_Fur_Quest, Recommended_Levels_and_ZEM_List, Statistics,
Haste_Guide. Notable real-world shapes:
- items: {{Itempage |itemname=... |lucy_img_ID=NNN |statsblock=<br>-separated
  in-game text |focus_effect=Name}} — focus effects ride a template PARAM, not
  always a statsblock line.
- quests: {| class="questTopTable" |} header table; steps are bullet lists under
  ==== component ==== headings (Bard_Epic) OR pure prose walkthroughs (Bat_Fur).
- Recommended_Levels_and_ZEM_List publishes NO actual ZEM numbers (dev choice);
  its tables are per-zone hunting recommendations via circle-icon images. The
  page documents a {{#vardefine:zem|N}} convention for future values — honored
  here if it ever appears in a row.
- Statistics keeps caps as '*Max (hard-cap): 255' bullets under
  ===Stat (ABBR)=== headings.
- Focus_Effects / Weapon_Procs / Clickies are #redirects to categories.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

WIKI_BASE = 'https://eqlwiki.com'

# ── low-level markup helpers ─────────────────────────────────────────────────

RE_BR = re.compile(r'<br\s*/?\s*>', re.I)
RE_COMMENT = re.compile(r'<!--.*?-->', re.S)
RE_LINK = re.compile(r'\[\[([^\[\]|]+)(?:\|([^\[\]]*))?\]\]')
RE_TAG = re.compile(r'</?[a-zA-Z][^<>]*>')
RE_REDIRECT = re.compile(r'^\s*#redirect\s*\[\[([^\[\]|]+)', re.I)


def strip_markup(s: str) -> str:
    """Readable text from wikitext: [[A|B]]->B, [[A]]->A, quotes/tags dropped."""
    s = RE_COMMENT.sub('', str(s or ''))
    # inner spans first so [[X|<span>X</span>]] resolves to plain X
    s = RE_TAG.sub('', s)
    s = RE_LINK.sub(lambda m: (m.group(2) if m.group(2) is not None else m.group(1)).strip() or m.group(1), s)
    s = re.sub(r"'''''|'''|''", '', s)
    s = re.sub(r'\{\{[^{}]*\}\}', '', s)     # leaf templates ({{exp}}, {{Era|X}})
    s = s.replace('&nbsp;', ' ')
    return ' '.join(s.split())


def split_br_lines(s: str) -> List[str]:
    """Split a statsblock-style blob on <br> variants AND newlines."""
    parts = []
    for chunk in RE_BR.split(str(s or '')):
        parts.extend(chunk.split('\n'))
    return [p.strip() for p in parts if p.strip()]


def extract_links(s: str) -> List[str]:
    """Link targets in order, skipping namespaced links (File:, Category:, ...)."""
    out = []
    for m in RE_LINK.finditer(str(s or '')):
        target = m.group(1).strip()
        if not target or ':' in target:
            continue
        if target not in out:
            out.append(target)
    return out


def redirect_target(wikitext: str) -> Optional[str]:
    m = RE_REDIRECT.match(wikitext or '')
    return m.group(1).strip() if m else None


def title_to_url(title: str) -> str:
    """Canonical article URL (the sync_pages primary key)."""
    from urllib.parse import quote
    return WIKI_BASE + '/' + quote(str(title).strip().replace(' ', '_'), safe="'()!,:;$&*")


# ── template parameter extraction ────────────────────────────────────────────

def parse_template(wikitext: str, name: str) -> Optional[Dict[str, str]]:
    """Top-level |key=value params of the first {{name ...}} in the page.

    Brace/bracket depth is tracked so pipes inside nested [[links]] and
    {{templates}} do not split parameters. Returns None if the template is
    absent or unterminated.
    """
    m = re.search(r'\{\{\s*' + re.escape(name) + r'\s*[|}]', wikitext or '', re.I)
    if not m:
        return None
    i = m.start() + 2          # after the opening {{
    depth_t, depth_l = 1, 0    # template / link nesting
    body_start = i
    end = None
    while i < len(wikitext) - 1:
        two = wikitext[i:i + 2]
        if two == '{{':
            depth_t += 1
            i += 2
        elif two == '}}':
            depth_t -= 1
            if depth_t == 0:
                end = i
                break
            i += 2
        elif two == '[[':
            depth_l += 1
            i += 2
        elif two == ']]':
            depth_l = max(0, depth_l - 1)
            i += 2
        else:
            i += 1
    if end is None:
        return None
    body = wikitext[body_start:end]

    # split on top-level pipes
    parts, buf, i = [], [], 0
    depth_t, depth_l = 0, 0
    while i < len(body):
        two = body[i:i + 2]
        if two == '{{':
            depth_t += 1; buf.append(two); i += 2
        elif two == '}}':
            depth_t = max(0, depth_t - 1); buf.append(two); i += 2
        elif two == '[[':
            depth_l += 1; buf.append(two); i += 2
        elif two == ']]':
            depth_l = max(0, depth_l - 1); buf.append(two); i += 2
        elif body[i] == '|' and depth_t == 0 and depth_l == 0:
            parts.append(''.join(buf)); buf = []; i += 1
        else:
            buf.append(body[i]); i += 1
    parts.append(''.join(buf))

    params: Dict[str, str] = {}
    for part in parts[1:]:      # parts[0] is the template name itself
        if '=' not in part:
            continue
        k, v = part.split('=', 1)
        params[k.strip().lower()] = v.strip()
    return params


# ── effects ──────────────────────────────────────────────────────────────────

_ROMAN = {'i': 1, 'ii': 2, 'iii': 3, 'iv': 4, 'v': 5,
          'vi': 6, 'vii': 7, 'viii': 8, 'ix': 9, 'x': 10}
RE_TIER = re.compile(r'^(.*\S)\s+(X|IX|VIII|VII|VI|V|IV|III|II|I)$')


def effect_family_tier(name: str) -> Tuple[str, Optional[int]]:
    """'Improved Damage II' -> ('Improved Damage', 2); no numeral -> (name, None)."""
    name = str(name or '').strip()
    m = RE_TIER.match(name)
    if m:
        return m.group(1), _ROMAN[m.group(2).lower()]
    return name, None


RE_EFFECT_LINE = re.compile(r'^(Focus Effect|Worn Effect|Effect|Worn)\s*:\s*(.+)$', re.I)


def parse_effect_line(line: str) -> Optional[Dict[str, Any]]:
    """Classify one 'Effect: ...' statsblock line.

    Observed real form: 'Effect: [[Dance of the Blade|<span...>...</span>]]
    (Combat, Casting Time: Instant) at Level 46' -> proc. Classification order
    for the parenthetical: Worn/Must Equip -> worn, Combat -> proc, casting-
    time/click wording -> click; a bare 'Effect: X' defaults to worn (armor
    convention). raw_line is preserved for auditing either way.
    """
    m = RE_EFFECT_LINE.match(line.strip())
    if not m:
        return None
    label = m.group(1).lower()
    rest = strip_markup(m.group(2))
    paren = ''
    pm = re.search(r'\(([^()]*)\)', rest)
    if pm:
        paren = pm.group(1).lower()
    name = re.split(r'\s*\(', rest, 1)[0]
    name = re.sub(r'\s+at Level \d+.*$', '', name, flags=re.I).strip()
    if not name:
        return None
    if label.startswith('focus'):
        etype = 'focus'
    elif label.startswith('worn'):
        etype = 'worn'
    elif 'worn' in paren or 'must equip' in paren:
        etype = 'worn'
    elif 'combat' in paren:
        etype = 'proc'
    elif 'casting time' in paren or 'any slot' in paren or 'can equip' in paren or 'click' in paren:
        etype = 'click'
    else:
        etype = 'worn'
    family, tier = effect_family_tier(name)
    return {'effect_type': etype, 'effect_name': name,
            'effect_family': family, 'effect_tier': tier, 'raw_line': line.strip()}


# ── items ────────────────────────────────────────────────────────────────────

FLAG_WORDS = ('MAGIC ITEM', 'LORE ITEM', 'NO DROP', 'NO RENT', 'TEMPORARY',
              'QUEST ITEM', 'ARTIFACT', 'ATTUNABLE')
STAT_KEYS = {'STR', 'STA', 'AGI', 'DEX', 'WIS', 'INT', 'CHA', 'ENDR', 'ATK'}
RE_PAIR = re.compile(r'([A-Z][A-Z ]*?):\s*([+-]?\d+(?:\.\d+)?)\s*(%?)')
RE_REQ_LEVEL = re.compile(r'Required level of\s*(\d+)', re.I)
RE_SIZE = re.compile(r'Size:\s*([A-Z]+)', re.I)


def parse_statsblock(block: str) -> Dict[str, Any]:
    """Line-oriented parse of the in-game-format statsblock free text."""
    out: Dict[str, Any] = {
        'flags': [], 'slot_text': None, 'class_text': None, 'race_text': None,
        'skill': None, 'ac': None, 'dmg': None, 'delay': None, 'haste_pct': None,
        'hp': None, 'mana': None, 'stats': {}, 'resists': {},
        'wt': None, 'size': None, 'required_level': None,
        'effects': [], 'misc_lines': [],
    }
    for raw_line in split_br_lines(block or ''):
        line = strip_markup(raw_line) if '[[' in raw_line or '<' in raw_line else raw_line
        line = ' '.join(line.split())
        if not line:
            continue
        eff = parse_effect_line(raw_line if RE_EFFECT_LINE.match(raw_line.strip()) else line)
        if eff:
            out['effects'].append(eff)
            continue
        upper = line.upper()
        flags = [w for w in FLAG_WORDS if w in upper]
        if flags and not RE_PAIR.search(line):
            out['flags'].extend(f for f in flags if f not in out['flags'])
            continue
        m = re.match(r'^Slot:\s*(.+)$', line, re.I)
        if m:
            out['slot_text'] = m.group(1).strip()
            continue
        m = re.match(r'^Class:\s*(.+)$', line, re.I)
        if m:
            out['class_text'] = m.group(1).strip()
            continue
        m = re.match(r'^Race:\s*(.+)$', line, re.I)
        if m:
            out['race_text'] = m.group(1).strip()
            continue
        m = RE_REQ_LEVEL.search(line)
        if m:
            out['required_level'] = int(m.group(1))
            continue
        m = re.match(r'^Skill:\s*([^:]+?)(?:\s+Atk Delay:\s*(\d+))?$', line, re.I)
        if m:
            out['skill'] = m.group(1).strip()
            if m.group(2):
                out['delay'] = int(m.group(2))
            continue
        # 'Haste: +36%' is mixed-case, so the ALL-CAPS RE_PAIR never saw it
        m = re.match(r'^Haste:\s*\+?(\d+)\s*%', line, re.I)
        if m:
            out['haste_pct'] = int(m.group(1))
            continue
        sm = RE_SIZE.search(line)
        if sm:
            out['size'] = sm.group(1)
        pairs = RE_PAIR.findall(line)
        if pairs:
            for key, num, pct in pairs:
                key = key.strip().upper()
                val = float(num) if '.' in num else int(num)
                if key == 'AC':
                    out['ac'] = int(val)
                elif key == 'DMG':
                    out['dmg'] = int(val)
                elif key in ('ATK DELAY', 'DELAY'):
                    out['delay'] = int(val)
                elif key == 'HASTE' or (pct and 'HASTE' in key):
                    out['haste_pct'] = int(val)
                elif key == 'HP':
                    out['hp'] = int(val)
                elif key == 'MANA':
                    out['mana'] = int(val)
                elif key == 'WT':
                    out['wt'] = val
                elif key.startswith('SV '):
                    out['resists'][key[3:]] = int(val)
                elif key in STAT_KEYS:
                    out['stats'][key] = int(val)
                elif key == 'SIZE':
                    pass
                else:
                    out['stats'][key] = int(val)
            continue
        if sm:
            continue
        out['misc_lines'].append(line)
    return out


def parse_itempage(wikitext: str) -> Optional[Dict[str, Any]]:
    """The item dict for a page embedding {{Itempage}}, else None.

    None is the 'not actually an item page' signal: embeddedin also returns
    list pages (Class Race Quest List, ...) that merely transclude item pages.
    """
    params = parse_template(wikitext or '', 'Itempage')
    if params is None or not params.get('itemname', '').strip():
        return None
    name = strip_markup(params['itemname'])
    icon = None
    m = re.search(r'\d+', params.get('lucy_img_id', ''))
    if m:
        icon = int(m.group(0))
    sb = parse_statsblock(params.get('statsblock', ''))
    focus_param = strip_markup(params.get('focus_effect', ''))
    if focus_param and not any(e['effect_type'] == 'focus' for e in sb['effects']):
        family, tier = effect_family_tier(focus_param)
        sb['effects'].append({'effect_type': 'focus', 'effect_name': focus_param,
                              'effect_family': family, 'effect_tier': tier,
                              'raw_line': 'focus_effect = ' + focus_param})
    return {
        'itemname': name,
        'icon': icon,
        'raw_statsblock': params.get('statsblock', '').strip(),
        'notes': params.get('notes', '').strip(),
        'relatedquests': extract_links(params.get('relatedquests', '')),
        **{k: sb[k] for k in ('flags', 'slot_text', 'class_text', 'race_text',
                              'skill', 'ac', 'dmg', 'delay', 'haste_pct', 'hp',
                              'mana', 'stats', 'resists', 'wt', 'size',
                              'required_level', 'effects')},
    }


# ── wikitable + section helpers ──────────────────────────────────────────────

RE_HEADING = re.compile(r'^(={1,6})\s*(.+?)\s*\1\s*$')


def sections(wikitext: str) -> List[Tuple[int, str, str]]:
    """[(level, title, body)] in order; leading pre-heading text has title ''."""
    out: List[Tuple[int, str, str]] = []
    level, title, buf = 0, '', []
    for line in (wikitext or '').split('\n'):
        m = RE_HEADING.match(line.strip())
        if m:
            out.append((level, title, '\n'.join(buf)))
            level, title, buf = len(m.group(1)), strip_markup(m.group(2)), []
        else:
            buf.append(line)
    out.append((level, title, '\n'.join(buf)))
    return [(lv, t, b) for lv, t, b in out if t or b.strip()]


def _split_cells(line: str, sep: str) -> List[str]:
    cells = []
    for cell in re.split(re.escape(sep), line):
        # 'style="..." | content' attribute prefix: drop it. A lone pipe inside
        # the cell only counts as an attribute separator when the prefix has an
        # = but no link/template markup.
        if '|' in cell:
            pre, _, post = cell.partition('|')
            if '=' in pre and '[[' not in pre and '{{' not in pre:
                cell = post
        cells.append(cell.strip())
    return cells


def parse_wikitables(wikitext: str) -> List[Dict[str, Any]]:
    """All {| ... |} tables as {'headers': [...], 'rows': [[raw cells]]}.

    Cells are RAW wikitext (callers strip_markup as needed — the ZEM parser
    reads icon filenames out of raw cells). headers = the first header-cell row.
    """
    tables = []
    lines = (wikitext or '').split('\n')
    i = 0
    while i < len(lines):
        if not lines[i].lstrip().startswith('{|'):
            i += 1
            continue
        headers: List[str] = []
        rows: List[List[str]] = []
        cur: List[str] = []
        cur_is_header = False

        def flush():
            nonlocal cur, cur_is_header
            if cur:
                if cur_is_header and not headers:
                    headers.extend(cur)
                else:
                    rows.append(cur)
            cur, cur_is_header = [], False

        i += 1
        while i < len(lines):
            ln = lines[i].strip()
            if ln.startswith('|}'):
                flush()
                break
            if ln.startswith('|-'):
                flush()
            elif ln.startswith('!'):
                cells = _split_cells(ln[1:], '!!')
                if not cur:
                    cur_is_header = True
                cur.extend(cells)
            elif ln.startswith('|') and not ln.startswith('|+'):
                cur.extend(_split_cells(ln[1:], '||'))
            i += 1
        if headers or rows:
            tables.append({'headers': headers, 'rows': rows})
        i += 1
    return tables


# ── quests ───────────────────────────────────────────────────────────────────

RE_QUEST_TABLE = re.compile(r'\{\|\s*class="[^"]*questTopTable[^"]*".*?\|\}', re.S)
RE_LEVEL_RANGE = re.compile(r'(\d+)\s*(?:-|to)\s*(\d+)|(\d+)\s*\+|(\d+)')


def _parse_level(text: str) -> Tuple[Optional[int], Optional[int]]:
    m = RE_LEVEL_RANGE.search(text or '')
    if not m:
        return None, None
    if m.group(1):
        return int(m.group(1)), int(m.group(2))
    if m.group(3):
        return int(m.group(3)), None
    return int(m.group(4)), None


def _split_names(text: str) -> List[str]:
    out = []
    for part in re.split(r',|/| and ', text or ''):
        part = part.strip()
        if part and part.lower() not in ('none', 'various', '') and part not in out:
            out.append(part)
    return out


def parse_quest(wikitext: str) -> Dict[str, Any]:
    """Quest header/steps/mentions. Every field is best-effort; a page with no
    questTopTable still yields steps + mentions from its body."""
    wikitext = RE_COMMENT.sub('', wikitext or '')
    out: Dict[str, Any] = {
        'start_zone': None, 'quest_giver': None,
        'level_min': None, 'level_max': None,
        'classes': [], 'races': [], 'steps': [], 'item_mentions': [],
        'has_top_table': False,
    }
    body = wikitext
    tm = RE_QUEST_TABLE.search(wikitext)
    header_texts: List[str] = []
    if tm:
        out['has_top_table'] = True
        body = wikitext[:tm.start()] + wikitext[tm.end():]
        # rows: '! ''' Key: ''' ' then '| value'
        key = None
        for ln in tm.group(0).split('\n'):
            ln = ln.strip()
            if ln.startswith('!'):
                key = strip_markup(ln[1:]).rstrip(':').strip().lower()
            elif ln.startswith('|') and ln[:2] not in ('|-', '|}') and key:
                val_raw = ln[1:].strip()
                val = strip_markup(val_raw)
                header_texts.append(val_raw)
                if 'start zone' in key:
                    out['start_zone'] = val or None
                elif 'giver' in key:
                    out['quest_giver'] = val or None
                elif 'level' in key:
                    out['level_min'], out['level_max'] = _parse_level(val)
                elif 'class' in key:
                    out['classes'] = ['All'] if val.lower() == 'all' else _split_names(val)
                elif 'race' in key:
                    out['races'] = ['All'] if val.lower() == 'all' else _split_names(val)
                key = None

    # steps: bullet/numbered list items, prefixed by their innermost heading
    steps: List[str] = []
    heading = ''
    for line in body.split('\n'):
        s = line.strip()
        hm = RE_HEADING.match(s)
        if hm:
            heading = strip_markup(hm.group(2))
            continue
        if s.startswith(('*', '#')):
            text = strip_markup(s.lstrip('*# ').strip())
            if not text or text.lower().startswith('your faction standing'):
                continue
            if heading.lower() in ('reward', 'rewards'):
                continue
            steps.append(f'{heading} — {text}' if heading and heading.lower()
                         not in ('checklist', 'walkthrough', 'steps') else text)
    if not steps:
        # prose walkthrough fallback (Bat_Fur style): paragraph lines from
        # walkthrough-ish sections, minus dialogue (':'-indented) and markup-only
        for lv, title, sec_body in sections(body):
            if title and 'walkthrough' not in title.lower():
                continue
            for line in sec_body.split('\n'):
                s = line.strip()
                if (not s or s.startswith((':', ';', '{', '<', '[[Category', '[[File',
                                           '[[file', '__', '|', '!', '*', '#'))):
                    continue   # bullets were already considered by the primary pass
                if re.search(r"says?\s*,?\s*'", s):   # NPC/player dialogue, not a step
                    continue
                text = strip_markup(s)
                if len(text) >= 25:
                    steps.append(text)
    out['steps'] = steps[:80]

    # item mentions: every plain link target in the body (not the top table);
    # NPC/zone links ride along and simply never join to the items table.
    skip = set()
    for t in header_texts:
        skip.update(extract_links(t))
    out['item_mentions'] = [t for t in extract_links(body) if t not in skip]
    return out


# ── guides ───────────────────────────────────────────────────────────────────

RE_VARDEFINE_ZEM = re.compile(r'\{\{#vardefine:zem\|([^{}|]*)\}\}', re.I)
ZEM_ICON_RATING = {
    'lightbluecircle': 'efficient',
    'goldcircle': 'inefficient',
    'lightpinkcircle': 'not recommended',
    'orangering': 'situational',
}


def parse_zem_guide(wikitext: str) -> List[Dict[str, Any]]:
    """Rows from the hunting-recommendation tables (Zone | Type | Lvl Range |
    per-5-levels rating icons). zem is None unless the page's documented
    {{#vardefine:zem|N}} convention carries a number."""
    rows_out: List[Dict[str, Any]] = []
    for lv, title, body in sections(wikitext or ''):
        for table in parse_wikitables(body):
            headers = [strip_markup(h) for h in table['headers']]
            if not headers or 'zone' not in headers[0].lower():
                continue
            lvl_col = next((i for i, h in enumerate(headers)
                            if 'lvl' in h.lower() or 'level' in h.lower()), None)
            level_cols = [(i, int(h)) for i, h in enumerate(headers) if h.isdigit()]
            for cells in table['rows']:
                if not cells:
                    continue
                zone = strip_markup(cells[0])
                if not zone:
                    continue
                lo, hi = (None, None)
                if lvl_col is not None and lvl_col < len(cells):
                    nums = re.findall(r'\d+', cells[lvl_col])
                    if nums:
                        lo, hi = int(nums[0]), int(nums[-1])
                zem = None
                zm = RE_VARDEFINE_ZEM.search(' '.join(cells))
                if zm and zm.group(1).strip().isdigit():
                    zem = int(zm.group(1).strip())
                ratings = {}
                for i, lvl in level_cols:
                    if i < len(cells):
                        im = re.search(r'file:\s*([A-Za-z]+)\.png', cells[i], re.I)
                        if im:
                            ratings[str(lvl)] = ZEM_ICON_RATING.get(im.group(1).lower(),
                                                                    im.group(1))
                rows_out.append({'region': title or None, 'zone': zone,
                                 'level_min': lo, 'level_max': hi, 'zem': zem,
                                 'ratings': ratings})
    return rows_out


RE_STAT_SECTION = re.compile(r'\(([A-Z]{2,4})\)\s*$')
RE_HARD_CAP = re.compile(r'Max\s*\(hard-?cap\)\s*:\s*(\d+)', re.I)
RE_SOFT_CAP = re.compile(r'Soft-?cap\s*:\s*(\d+)', re.I)


def parse_statistics(wikitext: str) -> Dict[str, Any]:
    """Stat caps (conservative: only explicit hard/soft-cap bullets) + generic
    sections. caps rows: {'stat': 'str'|'str_soft', 'level': 0, 'cap': N}."""
    caps: List[Dict[str, Any]] = []
    for lv, title, body in sections(wikitext or ''):
        m = RE_STAT_SECTION.search(title or '')
        if not m:
            continue
        stat = m.group(1).lower()
        hm = RE_HARD_CAP.search(body)
        if hm:
            caps.append({'stat': stat, 'level': 0, 'cap': int(hm.group(1))})
        sm = RE_SOFT_CAP.search(body)
        if sm:
            caps.append({'stat': stat + '_soft', 'level': 0, 'cap': int(sm.group(1))})
    return {'caps': caps, 'sections': parse_generic_guide(wikitext)['sections']}


def parse_generic_guide(wikitext: str) -> Dict[str, Any]:
    """Best-effort {'sections': [{title, rows?, items?}]} from wikitables and
    bullet lists. HTML <table> blobs (Haste_Guide) are left to the raw view."""
    out_sections: List[Dict[str, Any]] = []
    for lv, title, body in sections(wikitext or ''):
        sec: Dict[str, Any] = {'title': title or ''}
        tables = parse_wikitables(body)
        rows = []
        for t in tables:
            headers = [strip_markup(h) for h in t['headers']]
            for cells in t['rows']:
                stripped = [strip_markup(c) for c in cells]
                if not any(stripped):
                    continue
                if headers and len(stripped) <= len(headers):
                    rows.append({headers[i]: stripped[i] for i in range(len(stripped))})
                else:
                    rows.append({'cells': stripped})
        items = []
        for line in body.split('\n'):
            s = line.strip()
            if s.startswith(('*', '#')):
                text = strip_markup(s.lstrip('*# ').strip())
                if text:
                    items.append(text)
        if rows:
            sec['rows'] = rows
        if items:
            sec['items'] = items
        if rows or items:
            out_sections.append(sec)
    return {'sections': out_sections}

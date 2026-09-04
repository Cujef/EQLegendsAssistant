"""Item icon resolution — sheet arithmetic, on-demand PNG conversion, and the icons.json cache.

Deliberately network-free. The wiki worker (server.py) is the only thing that ever opens a
socket and it calls `note_resolved` / `note_failed` in here; keeping every byte of I/O policy
on that side is what makes the "lookup off means no socket" invariant cheap to hold and cheap
to test. Everything below works with the machine unplugged.

Three facts this module is built on, all READ from the game's own manifest rather than
guessed (see `read_manifest`):

  * `uifiles\\default\\EQUI_DragItems.xml` lists 379 `dragitem<n>.dds` sheets in numeric
    order under one `A_DragItem` animation. That ORDER is the mapping — never `glob` for the
    files, because a directory listing sorts `dragitem10` before `dragitem2` and every icon
    past 535 would land on the wrong art.
  * The animation is `Grid=true` with `CellWidth`/`CellHeight` 40 on a 256x256 sheet, so 6x6
    = 36 usable cells and a dead 16 px margin (Pillow's alpha bbox reads (0,0,239,240)).
  * It is `Vertical=true`, so a sheet fills COLUMN-first. `EQUI_SpellIcons.xml` is
    `Vertical=false` on the same grid, which is exactly why row-major cannot be assumed.

Read only from `default\\`. `default_modern\\` carries the same 379 names but is mixed-format
— two sheets are uncompressed 262 KB and the rest are byte-identical copies — so it buys
nothing and costs a format branch.
"""
import json
import os
import re
import sys
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

# ── sheet geometry ────────────────────────────────────────────────────────────
# Frozen constants, not discovered ones. `read_manifest` re-reads them from the XML and
# refuses to run if the game ever disagrees, so a client patch that re-cut the sheets is a
# loud failure rather than 13,644 subtly wrong pictures.
ICON_BASE = 500          # the game's first drag-item icon number
CELL      = 40           # CellWidth / CellHeight
GRID      = 6            # 256 px sheet / 40 px cell
CELLS     = GRID * GRID  # 36 per sheet
SHEETS    = 379          # frames in EQUI_DragItems.xml
SHEET_PX  = 256

# Real slot space is 379 * 36 = 13,644, so the last valid icon is 14,143. Anything outside
# this is a wiki page that embedded some other `Item_NNN.png` (an NPC portrait, a spell
# gem); it is not an item icon and must never reach the sheet arithmetic, where it would
# silently index a sheet that does not exist.
ICON_MIN = ICON_BASE
ICON_MAX = ICON_BASE + SHEETS * CELLS - 1

RE_SHEET = re.compile(r'^dragitem(\d+)\.dds$', re.I)

# ── paths ─────────────────────────────────────────────────────────────────────
# Windows fallback genericized to the game's real default install location for
# the public release (see vendor/eqlparser/PROVENANCE.md, "Deviations from
# upstream") — dead code in practice, since EQ_UIFILES_DIR is always set below
# before this module is imported (app/config.py).
if sys.platform == 'win32':
    _EQ_DIR = Path('C:/Users/Public/Daybreak Game Company/Installed Games/EverQuest Legends')
else:
    _EQ_DIR = Path(
        '/Users/cadmus/Library/Application Support/CrossOver/Bottles/EverQuest'
        '/drive_c/users/Public/Daybreak Game Company/Installed Games/EverQuest Legends'
    )
# env override so a test (or a second install) never has to guess where the client lives
UIFILES_DIR = Path(os.environ.get('EQ_UIFILES_DIR') or (_EQ_DIR / 'uifiles' / 'default'))
MANIFEST    = UIFILES_DIR / 'EQUI_DragItems.xml'

ICON_DIR   = Path(__file__).parent / 'static' / 'icons'
ICON_URL   = '/static/icons'
CACHE_PATH = Path(os.environ.get('EQ_ICONS_PATH')
                  or (Path(__file__).parent / 'icons.json'))

# ── hand-verified seeds ───────────────────────────────────────────────────────
# Ships in code, not in icons.json, so a fresh clone renders real art offline on day one and
# so `overrides` on disk stays a file you wrote rather than one we half-wrote for you.
#
# Both were confirmed by LOOKING at the cell the arithmetic lands on: 507 is a glowing globe
# and 579 is a scythe. Both sit on cell 7, which divmod(7, 6) maps to (1, 1) under either
# traversal — so they pin the base offset of 500 and the sheet order, and say nothing at all
# about column-first vs row-first. That question is settled separately; see
# tools/icons_calibrate.py.
#
# `Bone Chips -> 645` is deliberately NOT seeded. It was the intended off-diagonal probe, but
# the cell it lands on is a gold coin on this client build and the row-major alternative is a
# portrait card — neither is a pile of bones, so 645 is some other item and seeding it would
# have shipped a knowingly-wrong picture. See the calibrate tool for what replaced it.
SEED_OVERRIDES = {
    'Greater Lightstone': 507,   # sheet 1, cell 7 -> (40, 40): a glowing globe. Confirmed.
    'Ebon Scythe':        579,   # sheet 3, cell 7 -> (40, 40): a dark scythe. Confirmed.
}

# ≤3 attempts ever, ≥1 week apart. A name the wiki does not have is not going to grow one
# because we asked a fourth time, and the point of the retry budget is that a bad week
# (offline, wiki down) is recoverable without turning into a poll.
MAX_TRIES   = 3
RETRY_AFTER = 7 * 86400.0

_lock = threading.Lock()          # guards _cache and the conversion bookkeeping
_cache: dict | None = None
_converted: set[int] = set()      # sheets materialized this process, for the stats line


# ── manifest ──────────────────────────────────────────────────────────────────
def read_manifest(path: Path | None = None) -> list[str]:
    """Sheet filenames in the manifest's own order.

    Also asserts the geometry this module hard-codes. Returning a validated list rather than
    trusting `SHEETS`/`GRID` means the one place that could ever drift (a client patch) fails
    where a human is looking, instead of at icon 8,000 six weeks later.

    Raises FileNotFoundError when the EQ install is absent — callers that only need the
    arithmetic (the whole live path) never call this.
    """
    p = Path(path) if path else MANIFEST
    root = ET.parse(p).getroot()
    anim = next((a for a in root.iter('Ui2DAnimation')
                 if a.get('item') == 'A_DragItem'), None)
    if anim is None:
        raise ValueError(f'{p}: no A_DragItem animation')

    def _txt(tag):
        el = anim.find(tag)
        return (el.text or '').strip().lower() if el is not None else ''

    if _txt('Grid') != 'true':
        raise ValueError(f'{p}: A_DragItem is not a Grid')
    if _txt('Vertical') != 'true':
        # The whole column-first traversal below hangs off this one word.
        raise ValueError(f'{p}: A_DragItem is no longer Vertical — traversal changed')
    if _txt('CellWidth') != str(CELL) or _txt('CellHeight') != str(CELL):
        raise ValueError(f'{p}: cell size is not {CELL}x{CELL}')

    sheets = [(f.findtext('Texture') or '').strip() for f in anim.findall('Frames')]
    if len(sheets) != SHEETS:
        raise ValueError(f'{p}: {len(sheets)} frames, expected {SHEETS}')
    for i, name in enumerate(sheets):
        m = RE_SHEET.match(name)
        if not m or int(m.group(1)) != i + 1:
            raise ValueError(f'{p}: frame {i} is {name!r}, expected dragitem{i + 1}.dds')
    return sheets


# ── arithmetic ────────────────────────────────────────────────────────────────
def sprite(icon) -> dict | None:
    """Icon number -> the sheet and pixel offset that draws it, or None if out of range.

    `sheet` is 1-based to match the filename (`dragitem5.dds`), `cell` is 0-based within it.
    `x`/`y` are the top-left pixel of the cell, so CSS is
    `background-position: -{x}px -{y}px` against the whole 256x256 PNG.
    """
    if isinstance(icon, bool) or not isinstance(icon, int):
        return None
    if icon < ICON_MIN or icon > ICON_MAX:
        return None
    idx = icon - ICON_BASE
    sheet, cell = divmod(idx, CELLS)
    # Vertical=true: the grid is filled column-first, so the FIRST result is the column.
    # Row-major would read `row, col = divmod(...)` and transpose every off-diagonal cell.
    col, row = divmod(cell, GRID)
    return {
        'icon':  icon,
        'sheet': sheet + 1,
        'cell':  cell,
        'col':   col,
        'row':   row,
        'x':     col * CELL,
        'y':     row * CELL,
        'size':  CELL,
        'dds':   f'dragitem{sheet + 1}.dds',
        'png':   f'dragitem{sheet + 1}.png',
        'url':   f'{ICON_URL}/dragitem{sheet + 1}.png',
    }


# ── on-demand conversion ──────────────────────────────────────────────────────
def convert_sheet(sheet: int, force: bool = False) -> bool:
    """Materialize one 256x256 sheet as `static/icons/dragitem{n}.png`. True if it is there.

    WHOLE SHEET, ON DEMAND. Cutting 13,644 individual 40x40 files would be minutes of work
    and ~90 MB of derived Daybreak art on disk to serve a working set the measured logs put
    at 484 distinct item names; the browser sprites out of the sheet for free. Expect well
    under 100 sheets to ever exist.
    """
    if not 1 <= sheet <= SHEETS:
        return False
    if sheet in _converted and not force:
        return True                         # /api/icons asks about every name it knows, so
    dest = ICON_DIR / f'dragitem{sheet}.png'  # skipping the stat() is worth the one-line cache
    if dest.exists() and not force:
        with _lock:
            _converted.add(sheet)
        return True
    src = UIFILES_DIR / f'dragitem{sheet}.dds'
    if not src.is_file():
        return False
    try:
        from PIL import Image
    except ImportError:
        return False
    try:
        ICON_DIR.mkdir(parents=True, exist_ok=True)
        with Image.open(src) as im:
            im.convert('RGBA').save(dest, 'PNG', optimize=True)
    except Exception as e:                      # a corrupt sheet must not kill the caller
        print(f'[icons] sheet {sheet}: {e}', file=sys.stderr)
        return False
    with _lock:
        _converted.add(sheet)
    return True


def materialize(icon) -> dict | None:
    """`sprite()` plus the guarantee that the PNG behind it exists. None if either fails."""
    sp = sprite(icon)
    if sp is None or not convert_sheet(sp['sheet']):
        return None
    return sp


# ── cache file ────────────────────────────────────────────────────────────────
def _blank_cache() -> dict:
    return {'version': 1, 'overrides': {}, 'resolved': {}, 'unresolved': {}}


def load_cache(force: bool = False) -> dict:
    """icons.json, read once and kept in memory. Corrupt or missing -> a blank one."""
    global _cache
    with _lock:
        if _cache is not None and not force:
            return _cache
        data = None
        try:
            data = json.loads(CACHE_PATH.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            pass
        c = _blank_cache()
        if isinstance(data, dict):
            for key in ('overrides', 'resolved', 'unresolved'):
                if isinstance(data.get(key), dict):
                    c[key] = data[key]
        _cache = c
        return c


def save_cache() -> bool:
    """Write icons.json atomically: temp file in the same directory, then `os.replace`.

    Deliberately NOT `save_config()`'s `write_text`. That one truncates the real file before
    it writes a byte, so a crash (or a full disk) between the two leaves a zero-length
    config; it survives only because config.json holds one recoverable string. This file
    accumulates hundreds of lookups that cost network round-trips to rebuild, and `os.replace`
    is atomic on both NTFS and POSIX, so a reader sees the old file or the new one and never
    a half-written one.
    """
    with _lock:
        data = json.dumps(_cache if _cache is not None else _blank_cache(), indent=2,
                          sort_keys=True)
    tmp = CACHE_PATH.with_suffix(CACHE_PATH.suffix + '.tmp')
    try:
        tmp.write_text(data, encoding='utf-8')
        os.replace(tmp, CACHE_PATH)
        return True
    except OSError as e:
        print(f'[icons] cache save failed: {e}', file=sys.stderr)
        try:
            tmp.unlink()
        except OSError:
            pass
        return False


def reset_cache():
    """Drop the in-memory cache. For tests and for a hand-edit of icons.json."""
    global _cache
    with _lock:
        _cache = None


# ── name -> icon ──────────────────────────────────────────────────────────────
def _norm(name) -> str:
    return ' '.join(str(name or '').split())


def icon_for(name: str):
    """The icon number recorded for an item name, or None.

    `overrides` always wins — it is the hand-edited tier and the only escape hatch when the
    wiki's own page is ambiguous, so nothing automatic may ever shadow it.
    """
    key = _norm(name)
    if not key:
        return None
    c = load_cache()
    for src in (c['overrides'], SEED_OVERRIDES):
        v = src.get(key)
        if isinstance(v, int) and sprite(v) is not None:
            return v
    e = c['resolved'].get(key)
    if isinstance(e, dict) and sprite(e.get('icon')) is not None:
        return e['icon']
    return None


def needs_lookup(name: str, now: float) -> bool:
    """True when this name is worth spending a request on."""
    key = _norm(name)
    if not key or icon_for(key) is not None:
        return False
    e = load_cache()['unresolved'].get(key)
    if not isinstance(e, dict):
        return True
    if e.get('tries', 0) >= MAX_TRIES:
        return False
    return now - (e.get('last') or 0) >= RETRY_AFTER


def note_resolved(name: str, icon: int, src: str = 'wiki') -> bool:
    """Record a lookup that landed. Range-gated here as well as at the call site."""
    key = _norm(name)
    if not key or sprite(icon) is None:
        return False
    c = load_cache()
    with _lock:
        c['resolved'][key] = {'icon': int(icon), 'src': src}
        c['unresolved'].pop(key, None)
    return True


def note_failed(name: str, now: float):
    """Record a lookup that found nothing usable, and burn one of its three tries."""
    key = _norm(name)
    if not key:
        return
    c = load_cache()
    with _lock:
        e = c['unresolved'].get(key)
        if not isinstance(e, dict):
            e = c['unresolved'][key] = {'tries': 0, 'last': 0.0}
        e['tries'] = int(e.get('tries', 0)) + 1
        e['last'] = now


def is_unresolved(name: str) -> bool:
    """True once a name has spent its retry budget — the client's 'unresolved' tile."""
    e = load_cache()['unresolved'].get(_norm(name))
    return isinstance(e, dict) and e.get('tries', 0) >= MAX_TRIES


def payload(enabled: bool = False, extra: dict | None = None) -> dict:
    """Everything /api/icons hands the client.

    `icons` maps item name -> the sprite it should draw, with the PNG already on disk;
    `unresolved` is the list that has given up. Anything the client holds that appears in
    neither is 'pending' when lookup is on and 'lookup-off' when it is not — four
    never-empty states, none of which needs a network round-trip to render.
    """
    c = load_cache()
    # Snapshot the key sets under the lock and let it go before the loop. The icon worker
    # inserts into these dicts from its own thread, so iterating them live is the same
    # `dictionary changed size during iteration` that once killed the push loop — and
    # materialize() takes this same non-reentrant lock, so it cannot be called while holding it.
    with _lock:
        names = sorted(set(SEED_OVERRIDES) | set(c['overrides']) | set(c['resolved']))
        unresolved = sorted(k for k, v in c['unresolved'].items()
                            if isinstance(v, dict) and v.get('tries', 0) >= MAX_TRIES)
    icons = {}
    for name in names:
        num = icon_for(name)
        sp = materialize(num) if num is not None else None
        if sp:
            icons[name] = {'icon': sp['icon'], 'sheet': sp['sheet'], 'url': sp['url'],
                           'x': sp['x'], 'y': sp['y'], 'size': sp['size']}
    with _lock:                              # read AFTER the loop, or it is always one behind
        converted = len(_converted)
    stats = {'resolved': len(icons), 'overrides': len(c['overrides']),
             'unresolved': len(unresolved), 'converted': converted}
    stats.update(extra or {})
    return {'enabled': bool(enabled), 'icons': icons, 'unresolved': unresolved,
            'stats': stats}

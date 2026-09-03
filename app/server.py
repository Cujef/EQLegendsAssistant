"""EQ Legends Assistant — FastAPI app.

Serves the static shell, the JSON API, and a 1 Hz full-snapshot WebSocket
(parser pattern: push everything every second; detail views fetch on demand).
"""
import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import characters, db, inventory, naming, state
from .config import CONFIG, ROOT

from vendor.eqlparser import icons

STATIC_DIR = ROOT / 'static'
VENDOR_ICON_DIR = Path(icons.ICON_DIR)  # vendor/eqlparser/static/icons

app = FastAPI(title='EQ Legends Assistant')


LOCAL_HOSTS = ('127.0.0.1', 'localhost', '::1')


def is_local_origin(origin: str) -> bool:
    """True when an Origin header belongs to this machine.

    No Origin at all is allowed: non-browser clients (curl, the selftest, a
    script) do not send one, and they are not the threat here. `urlsplit` does
    the parsing because hand-splitting on ':' gets IPv6 (`http://[::1]:8766`)
    wrong — it did, and the tests caught it.
    """
    if not origin:
        return True
    return urlsplit(origin).hostname in LOCAL_HOSTS


@app.middleware('http')
async def _same_origin_only(request, call_next):
    """Refuse state-changing calls from another site's page.

    The app has no auth by design (single user, loopback only), and its POST
    endpoints read local files — so any page open in the same browser could
    otherwise POST here in the background. Browsers always attach Origin to
    cross-site POSTs, which is all this needs to say no.
    """
    if request.method not in ('GET', 'HEAD', 'OPTIONS') \
            and not is_local_origin(request.headers.get('origin', '')):
        return JSONResponse({'detail': 'cross-origin request refused'}, status_code=403)
    return await call_next(request)


@app.middleware('http')
async def _revalidate_static(request, call_next):
    """Make the browser revalidate /static assets instead of heuristically
    caching them. Chrome will happily serve a stale app.js for hours after an
    update otherwise; StaticFiles already sends ETag/Last-Modified, so this
    costs one conditional request that answers 304 on localhost."""
    response = await call_next(request)
    if request.url.path.startswith('/static/') or request.url.path == '/':
        response.headers['Cache-Control'] = 'no-cache'
    return response


@app.on_event('startup')
def _startup():
    db.init()
    characters.seed()
    # Later milestones start their workers here (tailer, etc.).
    from .logscan import tailer  # noqa: WPS433 - deferred so M0-M2 run without it
    tailer.start()


# ── shell + static ────────────────────────────────────────────────────────────
@app.get('/')
def index():
    return FileResponse(STATIC_DIR / 'index.html')


# ── characters ────────────────────────────────────────────────────────────────
@app.get('/api/characters')
def api_characters():
    active = characters.get()
    return {'characters': characters.list_all(),
            'active': active,
            'needs_setup': characters.needs_setup(),
            'readiness': characters.readiness(active)}


@app.post('/api/characters/{char_id}/select')
def api_select_character(char_id: int):
    if not characters.get(char_id):
        raise HTTPException(404, 'no such character')
    characters.select(char_id)
    return {'ok': True, 'active': characters.get()}


@app.get('/api/setup/scan')
def api_setup_scan(dir: str = ''):
    """Characters discoverable in a folder (install root or its Logs), no writes."""
    try:
        return characters.scan(dir or None)
    except OSError as e:
        raise HTTPException(400, f'cannot read that folder: {e}')


@app.post('/api/characters')
def api_add_character(body: dict):
    """Add (or update) a character by name + paths, and make it active."""
    try:
        row = characters.add(
            body.get('name', ''), body.get('server', ''),
            body.get('log_path'), body.get('inventory_path'),
            activate=body.get('activate', True))
    except ValueError as e:
        raise HTTPException(422, str(e))
    if not row:
        raise HTTPException(500, 'character was not stored')
    # a newly added character means a different log: let the pipeline pick it up
    from .logscan import tailer
    tailer.start()
    return {'ok': True, 'character': row}


@app.delete('/api/characters/{char_id}')
def api_remove_character(char_id: int):
    if not characters.get(char_id):
        raise HTTPException(404, 'no such character')
    characters.remove(char_id)
    return {'ok': True, 'characters': characters.list_all(), 'active': characters.get()}


def _char_or_404(char: int = None) -> dict:
    c = characters.get(char)
    if not c:
        raise HTTPException(404, 'no character')
    return c


# ── inventory ─────────────────────────────────────────────────────────────────
@app.get('/api/inventory')
def api_inventory(char: int = None):
    c = _char_or_404(char)
    return inventory.get_view(c['id'])


def _import_target(body: dict, char: int, expected_suffix: str) -> tuple:
    """(character row, detected (name, server) | None) for an import request.

    No /outputfile export carries a character header; the game's filename
    (<Name>_<server>-Inventory.txt / -Faction.txt / -<Skill>-Recipes.txt) is the
    only owner hint. `target: 'detected'` imports for THAT character (created if
    needed, activated only when `activate` is true — or when there is no
    character at all yet) instead of the active one, so one install can hold
    several characters' files without hand-switching first.
    """
    filename = str(body.get('filename') or '')
    path = body.get('path') or ''
    detected = characters.parse_outputfile_owner(filename or path)
    target = str(body.get('target') or 'active')
    if target == 'detected':
        if not detected:
            raise HTTPException(422, 'could not read a character name from the file name '
                                     f'(expected <Name>_<server>{expected_suffix})')
        try:
            c = characters.add(detected[0], detected[1], None, None,
                               activate=bool(body.get('activate')) or not characters.get())
        except ValueError as e:
            raise HTTPException(422, str(e))
    elif target == 'active':
        c = _char_or_404(char)
    else:
        raise HTTPException(422, 'target must be "active" or "detected"')
    return c, detected


def _owner_fields(result: dict, c: dict, detected) -> dict:
    result['character'] = {'id': c['id'], 'name': c['name'], 'server': c['server']}
    result['detected'] = ({'name': detected[0], 'server': detected[1]} if detected else None)
    result['mismatch'] = bool(detected and (
        detected[0].lower(), detected[1].lower()) != (c['name'].lower(), c['server'].lower()))
    return result


@app.post('/api/import')
def api_import_any(body: dict, char: int = None):
    """Import ANY /outputfile export — inventory, faction, or recipes — telling
    them apart by filename, then by content. `{content, filename}` from the
    browser picker or `{path}` on this computer; owner handling as above."""
    from . import gamefiles
    body = body or {}
    c, detected = _import_target(body, char, '-Inventory.txt / -Faction.txt / -<Skill>-Recipes.txt')
    content = body.get('content')
    filename = str(body.get('filename') or '')
    path = body.get('path') or ''
    try:
        if content:
            result = gamefiles.import_any(c['id'], str(content).encode('utf-8'), filename=filename)
        else:
            if not path or not Path(path).is_file():
                raise HTTPException(404, f'file not found: {path or "(no path given)"}')
            result = gamefiles.import_any(c['id'], Path(path).read_bytes(), path=path)
            if result.get('kind') == 'inventory' and path != c.get('inventory_path'):
                db.execute('UPDATE characters SET inventory_path=? WHERE id=?', (path, c['id']))
    except ValueError as e:
        raise HTTPException(422, str(e))
    return _owner_fields(result, c, detected)


@app.post('/api/inventory/import')
def api_inventory_import(body: dict = None, char: int = None):
    """Import a dump.

    Body is optional: `{content, filename}` imports text the browser read from a
    file the server cannot see (the file picker gives no real path), `{path}`
    points at a new server-side file and remembers it. With no body, re-read the
    stored path. Owner detection: see _import_target.
    """
    body = body or {}
    c, detected = _import_target(body, char, '-Inventory.txt')
    content = body.get('content')
    filename = str(body.get('filename') or '')
    path = body.get('path') or ''
    try:
        if content:
            result = inventory.import_bytes(
                c['id'], str(content).encode('utf-8'),
                source_path=filename or 'uploaded')
        else:
            path = path or c.get('inventory_path')
            if not path or not Path(path).is_file():
                raise HTTPException(404, f'inventory dump not found for {c["name"]} '
                                         f'(run /outputfile inventory in game, or '
                                         f'pick the file in Import Inventory)')
            result = inventory.import_file(c['id'], path)
            if path != c.get('inventory_path'):
                db.execute('UPDATE characters SET inventory_path=? WHERE id=?',
                           (path, c['id']))
    except ValueError as e:
        raise HTTPException(422, str(e))
    result['kind'] = 'inventory'
    return _owner_fields(result, c, detected)


# ── icons ─────────────────────────────────────────────────────────────────────
@app.get('/api/sprite/{icon}')
def api_sprite(icon: int):
    sp = icons.materialize(icon)
    if not sp:
        raise HTTPException(404, 'no such icon (or Pillow not installed)')
    return sp


@app.get('/api/sprites')
def api_sprites(icons_csv: str = Query('', alias='icons')):
    """Batch sprite lookup: /api/sprites?icons=507,579 -> {icon: sprite}.
    Materializes each sheet PNG on demand; unknown/failed icons are omitted."""
    out = {}
    for tok in icons_csv.split(','):
        try:
            n = int(tok)
        except ValueError:
            continue
        sp = icons.materialize(n)
        if sp:
            out[n] = {'url': sp['url'], 'x': sp['x'], 'y': sp['y'], 'size': sp['size']}
    return out


# ── log import + fights ──────────────────────────────────────────────────────
@app.post('/api/log/import')
def api_log_import(char: int = None):
    c = _char_or_404(char)
    if not c.get('log_path'):
        raise HTTPException(404, f'no log file found for {c["name"]}')
    from .logscan import importer
    res = importer.start(c)
    if not res.get('ok'):
        raise HTTPException(409, res.get('error', 'import failed to start'))
    return res


@app.get('/api/fights')
def api_fights(char: int = None, limit: int = 50):
    c = _char_or_404(char)
    return {'fights': db.query(
        'SELECT id, start, name, duration, dps, total_damage, total_healing, '
        'total_tanking, xp, coin FROM fights WHERE character_id=? '
        'ORDER BY start DESC LIMIT ?', (c['id'], limit))}


@app.get('/api/fights/{fight_id}')
def api_fight(fight_id: int):
    row = db.query_one('SELECT data, character_id FROM fights WHERE id=?', (fight_id,))
    if not row:
        raise HTTPException(404, 'no such fight')
    owner = characters.get(row['character_id'])
    return naming.humanize_fight(json.loads(row['data']),
                                 owner['name'] if owner else None)


# ── overview (M8) ────────────────────────────────────────────────────────────
@app.get('/api/overview')
def api_overview(char: int = None):
    from . import stats
    c = _char_or_404(char)
    return stats.overview(c['id'])


@app.post('/api/manual-stat')
def api_manual_stat(body: dict, char: int = None):
    from . import stats
    c = _char_or_404(char)
    stats.set_manual(c['id'], str(body.get('key', '')), str(body.get('value', '')))
    return {'ok': True}


# ── quests (M7) ──────────────────────────────────────────────────────────────
@app.get('/api/quests')
def api_quests(char: int = None, cls: str = '', race: str = '',
               level_min: int = None, level_max: int = None, zone: str = '',
               q: str = '', hide_completed: bool = False):
    from . import quests
    c = _char_or_404(char)
    return {'quests': quests.list_quests(c['id'], cls, race, level_min, level_max,
                                         zone, q, hide_completed),
            'classes': quests.CLASSES, 'races': quests.RACES}


@app.get('/api/quest-progress')
def api_quest_progress(char: int = None):
    from . import quests
    c = _char_or_404(char)
    return quests.progress_view(c['id'])


@app.get('/api/quests/{quest_id}')
def api_quest_detail(quest_id: int, char: int = None):
    from . import quests
    c = _char_or_404(char)
    detail = quests.quest_detail(c['id'], quest_id)
    if not detail:
        raise HTTPException(404, 'no such quest')
    return detail


@app.post('/api/quests/{quest_id}/status')
def api_quest_status(quest_id: int, body: dict, char: int = None):
    from . import quests
    c = _char_or_404(char)
    status = str(body.get('status', ''))
    if status not in ('tracked', 'completed', 'dismissed', 'untracked'):
        raise HTTPException(422, 'bad status')
    quests.set_status(c['id'], quest_id, status)
    return {'ok': True}


@app.post('/api/quests/{quest_id}/steps/{step_index}/toggle')
def api_quest_step(quest_id: int, step_index: int, char: int = None):
    from . import quests
    c = _char_or_404(char)
    return {'done': quests.toggle_step(c['id'], quest_id, step_index)}


# ── what to do / exaltations / tradeskills (M9-M10) ──────────────────────────
@app.get('/api/whattodo')
def api_whattodo(char: int = None):
    from . import quests
    c = _char_or_404(char)
    return quests.whattodo(c['id'])


@app.get('/api/exaltations')
def api_exaltations(char: int = None):
    from . import exaltation
    c = _char_or_404(char)
    return exaltation.view(c['id'])


@app.get('/api/tradeskills')
def api_tradeskills(char: int = None):
    from . import tradeskills
    c = _char_or_404(char)
    return tradeskills.view(c['id'])


@app.get('/api/factions')
def api_factions(char: int = None):
    from . import factions
    c = _char_or_404(char)
    return factions.view(c['id'])


# ── sync ─────────────────────────────────────────────────────────────────────
@app.post('/api/sync/start')
def api_sync_start(body: dict):
    from .sync import engine
    res = engine.start(str(body.get('source', '')))
    if not res.get('ok'):
        raise HTTPException(409, res.get('error', 'sync failed to start'))
    return res


@app.post('/api/sync/cancel')
def api_sync_cancel():
    from .sync import engine
    return engine.cancel()


@app.get('/api/sync/status')
def api_sync_status():
    from .sync import engine
    return engine.status()


# ── websocket: 1 Hz full snapshot ────────────────────────────────────────────
def _snapshot() -> dict:
    active = characters.get()
    snap = {'type': 'state',
            'characters': characters.list_all(),
            'active': active,
            'needs_setup': characters.needs_setup(),
            'readiness': characters.readiness(active)}
    snap.update(state.snapshot_extras())
    return snap


@app.websocket('/ws')
async def ws(sock: WebSocket):
    await sock.accept()
    try:
        while True:
            try:
                payload = await asyncio.to_thread(lambda: json.dumps(_snapshot()))
            except Exception:
                # a bad frame must cost one tick, not the socket — and loudly:
                # the parser project once swallowed exactly this into silence
                import traceback
                traceback.print_exc()
                await asyncio.sleep(1)
                continue
            await sock.send_text(payload)
            await asyncio.sleep(1)
    except (WebSocketDisconnect, RuntimeError):
        # RuntimeError covers send-on-closed-socket during shutdown
        pass


@app.get('/api/health')
def health():
    from . import __version__
    return {'ok': True, 'version': __version__, 'port': CONFIG['port']}


# Mounted last so API routes win. /static/icons serves the vendored module's
# on-demand PNG sheets (its ICON_URL constant matches this path).
VENDOR_ICON_DIR.mkdir(parents=True, exist_ok=True)
app.mount('/static/icons', StaticFiles(directory=VENDOR_ICON_DIR), name='icons')
app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')

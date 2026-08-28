"""EQ Legends Assistant — FastAPI app.

Serves the static shell, the JSON API, and a 1 Hz full-snapshot WebSocket
(parser pattern: push everything every second; detail views fetch on demand).
"""
import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import characters, db, inventory, state
from .config import CONFIG, ROOT

from vendor.eqlparser import icons

STATIC_DIR = ROOT / 'static'
VENDOR_ICON_DIR = Path(icons.ICON_DIR)  # vendor/eqlparser/static/icons

app = FastAPI(title='EQ Legends Assistant')


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
    return {'characters': characters.list_all(),
            'active': characters.get()}


@app.post('/api/characters/{char_id}/select')
def api_select_character(char_id: int):
    if not characters.get(char_id):
        raise HTTPException(404, 'no such character')
    characters.select(char_id)
    return {'ok': True, 'active': characters.get()}


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


@app.post('/api/inventory/import')
def api_inventory_import(char: int = None):
    c = _char_or_404(char)
    path = c.get('inventory_path')
    if not path or not Path(path).is_file():
        raise HTTPException(404, f'inventory dump not found for {c["name"]} '
                                 f'(run /outputfile inventory in game)')
    try:
        result = inventory.import_file(c['id'], path)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return result


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
    row = db.query_one('SELECT data FROM fights WHERE id=?', (fight_id,))
    if not row:
        raise HTTPException(404, 'no such fight')
    return json.loads(row['data'])


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
    snap = {'type': 'state',
            'characters': characters.list_all(),
            'active': characters.get()}
    snap.update(state.snapshot_extras())
    return snap


@app.websocket('/ws')
async def ws(sock: WebSocket):
    await sock.accept()
    try:
        while True:
            payload = await asyncio.to_thread(lambda: json.dumps(_snapshot()))
            await sock.send_text(payload)
            await asyncio.sleep(1)
    except (WebSocketDisconnect, RuntimeError):
        pass


@app.get('/api/health')
def health():
    return {'ok': True, 'port': CONFIG['port']}


# Mounted last so API routes win. /static/icons serves the vendored module's
# on-demand PNG sheets (its ICON_URL constant matches this path).
VENDOR_ICON_DIR.mkdir(parents=True, exist_ok=True)
app.mount('/static/icons', StaticFiles(directory=VENDOR_ICON_DIR), name='icons')
app.mount('/static', StaticFiles(directory=STATIC_DIR), name='static')

/* Tile grid for the Parser page — draggable / resizable / lockable panels on a
   12-column grid with localStorage layout persistence. Port of the proven
   implementation in J:\_EQLegendsParser\static\app.js (single page, no tabs).

   Public contract used by pages/parserpage.js:
     Tiles.mount(container, {
       storageKey: 'eqa.parserLayout.v1',
       defs: [{id, title, span, height, minSpan, build(bodyEl, tileApi)}],
     }) -> {refresh(), locked}

   Layout blob: {order: [ids], spans: {id: n}, heights: {id: px},
                 closed: [ids], locked: bool}.
   All chrome CSS is injected here (id='tiles-css') using themes.css tokens only
   — app.css stays untouched. Zero rounded corners; same bevels as .panel. */
'use strict';

const TILES_CSS = `
.tiles-toolbar { display:flex; align-items:center; gap:6px; margin-bottom:10px;
  user-select:none; }
.tiles-grid { display:grid; grid-template-columns:repeat(12, 1fr); gap:10px;
  align-items:start; }
.tile { position:relative; display:flex; flex-direction:column; overflow:hidden;
  border:1px solid var(--edge);
  background:
    repeating-linear-gradient(90deg, transparent 0 2px, var(--brush-line) 2px 3px),
    linear-gradient(180deg, var(--panel-hi), var(--panel-lo));
  box-shadow: inset 1px 1px 0 var(--bevel-hi), inset -1px -1px 0 var(--bevel-lo),
    0 2px 6px var(--shadow); }
.tile.tile-closed { display:none; }
.tile-hdr { display:flex; align-items:center; gap:7px; padding:4px 8px; flex:none;
  border-bottom:1px solid var(--edge);
  background: linear-gradient(180deg, var(--panel-hi), var(--panel-flat));
  user-select:none; }
.tile-title { flex:1; font:700 11px var(--font-display); letter-spacing:0.13em;
  text-transform:uppercase; color:var(--text-dim); white-space:nowrap;
  overflow:hidden; text-overflow:ellipsis; }
.tile-drag { cursor:grab; color:var(--text-faint); font-size:13px; line-height:1; }
.tile-drag:hover { color:var(--accent); }
.tile-x { cursor:pointer; color:var(--text-faint); background:none; border:none;
  font:700 11px var(--font-display); padding:0 2px; }
.tile-x:hover { color:var(--bad); }
.tile-body { flex:1; overflow:auto; padding:8px; font-size:12px; min-height:0; }
.tile-grip { position:absolute; z-index:5; }
.tile-grip-e  { top:0; right:0; width:7px; height:100%; cursor:ew-resize; }
.tile-grip-s  { left:0; bottom:0; width:100%; height:7px; cursor:ns-resize; }
.tile-grip-se { right:0; bottom:0; width:13px; height:13px; cursor:nwse-resize;
  border-right:2px solid var(--edge-strong); border-bottom:2px solid var(--edge-strong); }
.tile-grip:hover { background: var(--sel-bg); }
.tiles-grid.locked .tile-drag, .tiles-grid.locked .tile-grip,
.tiles-grid.locked .tile-x { display:none; }
.tile.dragging { opacity:0.88; box-shadow: 0 6px 18px var(--shadow); }
.tile-placeholder { border:1px dashed var(--edge-strong); background:var(--sel-bg);
  box-shadow:none; }
.tiles-panel { position:fixed; z-index:60; display:none; min-width:180px;
  padding:8px 10px; border:1px solid var(--edge-strong);
  background: linear-gradient(180deg, var(--panel-hi), var(--panel-lo));
  box-shadow: inset 1px 1px 0 var(--bevel-hi), inset -1px -1px 0 var(--bevel-lo),
    0 4px 14px var(--shadow); }
.tiles-panel.open { display:block; }
.tiles-panel .tp-title { font:700 10px var(--font-display); letter-spacing:0.14em;
  text-transform:uppercase; color:var(--text-dim); margin-bottom:6px; }
.tiles-panel label { display:flex; align-items:center; gap:6px; padding:2px 0;
  font-size:12px; color:var(--text); cursor:pointer; white-space:nowrap; }
`;

const Tiles = {
  mount(container, opts) {
    if (!document.getElementById('tiles-css')) {
      const st = document.createElement('style');
      st.id = 'tiles-css';
      st.textContent = TILES_CSS;
      document.head.append(st);
    }
    return _mountGrid(container, opts);
  },
};

function _mountGrid(container, opts) {
  const KEY = opts.storageKey || 'eqa.tiles.v1';
  const defs = opts.defs || [];
  const byId = {};
  for (const d of defs) byId[d.id] = d;

  // ── layout state ────────────────────────────────────────────────────────
  let layout = loadLayout();
  function loadLayout() {
    let raw = null;
    try { raw = JSON.parse(localStorage.getItem(KEY)); } catch (e) {}
    const l = raw && typeof raw === 'object' ? raw : {};
    const known = new Set(defs.map((d) => d.id));
    // drop stale ids, append registry newcomers at the end (their def order)
    const order = (Array.isArray(l.order) ? l.order : []).filter((id) => known.has(id));
    for (const d of defs) if (!order.includes(d.id)) order.push(d.id);
    return {
      order,
      spans:   l.spans   || {},
      heights: l.heights || {},
      closed:  (Array.isArray(l.closed) ? l.closed : []).filter((id) => known.has(id)),
      locked:  l.locked !== false,          // locked by default: safe first-run
    };
  }
  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(layout)); } catch (e) {}
  }
  const GRID_COLS = 12, GRID_GAP = 10, MIN_TILE_HEIGHT = 72;
  const spanOf = (id) => layout.spans[id] || byId[id].span || 4;
  const heightOf = (id) => layout.heights[id] || byId[id].height || 300;

  // ── chrome ──────────────────────────────────────────────────────────────
  container.replaceChildren();
  const toolbar = el('div', { class: 'tiles-toolbar' });
  const panelBtn = el('button', { class: 'metal-btn', title: 'Show or hide tiles' }, '⊞ Tiles');
  const lockBtn = el('button', { class: 'metal-btn', title: '' }, '🔒');
  const panel = el('div', { class: 'tiles-panel' });
  toolbar.append(panelBtn, lockBtn);
  const grid = el('div', { class: 'tiles-grid' });
  container.append(toolbar, grid, panel);

  const api = {
    refresh() {          // rebuild every open tile body from its def
      for (const id of layout.order) {
        const t = tileEl(id);
        if (!t || t.classList.contains('tile-closed')) continue;
        const body = t.querySelector('.tile-body');
        body.replaceChildren();
        try { byId[id].build(body, api); } catch (e) { body.textContent = 'tile error: ' + e.message; }
      }
    },
    get locked() { return layout.locked; },
  };

  function updateLockUI() {
    grid.classList.toggle('locked', layout.locked);
    lockBtn.textContent = layout.locked ? '🔒' : '🔓';
    lockBtn.title = layout.locked
      ? 'Layout locked — click to unlock dragging & resizing'
      : 'Layout unlocked — drag by ⠿, resize from the edges; click to lock';
  }
  lockBtn.addEventListener('click', () => {
    layout.locked = !layout.locked;
    save();
    updateLockUI();
  });

  panelBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    const opening = !panel.classList.contains('open');
    panel.classList.toggle('open', opening);
    if (opening) {
      renderPanel();
      const r = panelBtn.getBoundingClientRect();
      panel.style.top = (r.bottom + 6) + 'px';
      panel.style.left = Math.max(8, Math.min(r.left, innerWidth - panel.offsetWidth - 8)) + 'px';
    }
  });
  document.addEventListener('click', (e) => {
    if (!panel.contains(e.target) && e.target !== panelBtn) panel.classList.remove('open');
  });

  function renderPanel() {
    panel.replaceChildren(el('div', { class: 'tp-title' }, 'Tiles'));
    for (const id of layout.order) {
      const cb = el('input', { type: 'checkbox' });
      cb.checked = !layout.closed.includes(id);
      cb.addEventListener('change', () => (cb.checked ? openTile(id) : closeTile(id)));
      panel.append(el('label', {}, cb, byId[id].title));
    }
  }

  // ── tile build ──────────────────────────────────────────────────────────
  function tileEl(id) { return grid.querySelector(`.tile[data-tile="${id}"]`); }

  function buildTile(id) {
    const def = byId[id];
    const tile = el('section', { class: 'tile', 'data-tile': id });
    tile.style.gridColumn = `span ${spanOf(id)}`;
    tile.style.height = heightOf(id) + 'px';
    tile.classList.toggle('tile-closed', layout.closed.includes(id));

    const drag = el('span', { class: 'tile-drag', title: 'Drag to move' }, '⠿');
    const x = el('button', { class: 'tile-x', title: 'Close this tile — reopen from ⊞ Tiles' }, '✕');
    x.addEventListener('click', (e) => { e.stopPropagation(); closeTile(id); });
    tile.append(el('div', { class: 'tile-hdr' }, drag,
      el('span', { class: 'tile-title' }, def.title), x));

    const body = el('div', { class: 'tile-body' });
    tile.append(body);

    // three grips: E = width (snaps to grid columns), S = height, SE = both
    for (const axis of ['e', 's', 'se']) {
      const grip = el('div', { class: `tile-grip tile-grip-${axis}` });
      grip.title = axis === 'e' ? 'Drag to set width'
                 : axis === 's' ? 'Drag to set height' : 'Drag to resize';
      grip.addEventListener('pointerdown', (ev) => startResize(ev, tile, grip, axis));
      tile.append(grip);
    }
    drag.addEventListener('pointerdown', (e) => startDrag(e, tile, drag));

    grid.append(tile);
    try { def.build(body, api); } catch (e) { body.textContent = 'tile error: ' + e.message; }
    return tile;
  }

  function closeTile(id) {
    if (!layout.closed.includes(id)) layout.closed.push(id);
    const t = tileEl(id);
    if (t) t.classList.add('tile-closed');
    save();
    renderPanel();
  }
  function openTile(id) {
    layout.closed = layout.closed.filter((x) => x !== id);
    const t = tileEl(id);
    if (t) {
      t.classList.remove('tile-closed');
      const body = t.querySelector('.tile-body');
      body.replaceChildren();
      try { byId[id].build(body, api); } catch (e) { body.textContent = 'tile error: ' + e.message; }
    }
    save();
    renderPanel();
  }

  // ── drag reorder (pointer events; parser's placeholder pattern) ─────────
  let dragState = { active: false };
  function startDrag(e, tile, handle) {
    if (layout.locked || e.button !== 0) return;
    e.preventDefault();
    const rect = tile.getBoundingClientRect();
    const ph = el('section', { class: 'tile tile-placeholder' });
    ph.style.gridColumn = tile.style.gridColumn;
    ph.style.height = tile.style.height;
    tile.parentNode.insertBefore(ph, tile);
    tile.classList.add('dragging');
    Object.assign(tile.style, {
      position: 'fixed', left: rect.left + 'px', top: rect.top + 'px',
      width: rect.width + 'px', zIndex: '50',
    });
    dragState = { active: true, tile, ph, dx: e.clientX - rect.left, dy: e.clientY - rect.top };
    handle.setPointerCapture(e.pointerId);
    const move = (ev) => onDragMove(ev);
    const up = () => {
      handle.removeEventListener('pointermove', move);
      handle.removeEventListener('pointerup', up);
      handle.removeEventListener('pointercancel', up);
      endDrag();
    };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', up);
    handle.addEventListener('pointercancel', up);
  }

  function onDragMove(e) {
    if (!dragState.active) return;
    const { tile, ph, dx, dy } = dragState;
    tile.style.left = (e.clientX - dx) + 'px';
    tile.style.top = (e.clientY - dy) + 'px';
    // nearest-center insertion: same row decides by x, different row by y
    const others = [...grid.children].filter((t) => t !== tile && t !== ph
      && !t.classList.contains('tile-closed'));
    let best = null, bestD = Infinity;
    for (const t of others) {
      const r = t.getBoundingClientRect();
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const d = Math.hypot(e.clientX - cx, e.clientY - cy);
      if (d < bestD) { bestD = d; best = { t, r, cx, cy }; }
    }
    if (best) {
      const after = (e.clientY >= best.r.top && e.clientY <= best.r.bottom)
        ? e.clientX > best.cx
        : e.clientY > best.cy;
      grid.insertBefore(ph, after ? best.t.nextSibling : best.t);
    } else {
      grid.appendChild(ph);
    }
  }

  function endDrag() {
    const { tile, ph } = dragState;
    if (!tile) return;
    ph.parentNode.insertBefore(tile, ph);
    ph.remove();
    tile.classList.remove('dragging');
    Object.assign(tile.style, { position: '', left: '', top: '', width: '', zIndex: '' });
    dragState = { active: false };
    layout.order = [...grid.children].map((t) => t.dataset.tile).filter(Boolean);
    save();
  }

  // ── resize (width snaps to grid columns; height is free px) ─────────────
  function startResize(e, tile, grip, axis) {
    if (layout.locked || e.button !== 0) return;
    e.preventDefault();
    e.stopPropagation();
    const rect = tile.getBoundingClientRect();
    const id = tile.dataset.tile;
    const minSpan = Math.max(1, byId[id].minSpan || 1);
    const colW = (grid.clientWidth - (GRID_COLS - 1) * GRID_GAP) / GRID_COLS;
    const wide = axis === 'e' || axis === 'se';
    const tall = axis === 's' || axis === 'se';
    grip.setPointerCapture(e.pointerId);

    const move = (ev) => {
      if (wide) {
        const w = Math.max(colW * 0.5, ev.clientX - rect.left);
        const span = Math.min(GRID_COLS,
          Math.max(minSpan, Math.round((w + GRID_GAP) / (colW + GRID_GAP))));
        tile.style.gridColumn = `span ${span}`;
      }
      if (tall) {
        tile.style.height = Math.round(Math.max(MIN_TILE_HEIGHT, ev.clientY - rect.top)) + 'px';
      }
    };
    const up = () => {
      grip.removeEventListener('pointermove', move);
      grip.removeEventListener('pointerup', up);
      grip.removeEventListener('pointercancel', up);
      layout.spans[id] = parseInt(tile.style.gridColumn.replace(/\D/g, ''), 10) || spanOf(id);
      layout.heights[id] = parseInt(tile.style.height, 10) || heightOf(id);
      save();
    };
    grip.addEventListener('pointermove', move);
    grip.addEventListener('pointerup', up);
    grip.addEventListener('pointercancel', up);
  }

  // ── boot ────────────────────────────────────────────────────────────────
  for (const id of layout.order) buildTile(id);
  updateLockUI();
  return api;
}

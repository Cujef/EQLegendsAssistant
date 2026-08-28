/* Tile grid for the Parser page — draggable / resizable / lockable panels on a
   12-column grid with localStorage layout persistence.

   PORT TARGET (M4): the proven implementation in
   J:\_EQLegendsParser\static\app.js (~lines 59–800): TILE_DEFS registry,
   pointer-event drag via a ⠿ handle, E/S/SE resize grips snapping to grid
   columns, 🔒 lock toggle, ⊞ reopen panel, per-page tabs.

   Public contract used by pages/parserpage.js:
     Tiles.mount(container, {
       storageKey: 'eqa.parserLayout.v1',
       defs: [{id, title, span, height, minSpan, build(bodyEl, tileApi)}],
     }) -> {refresh(), locked}
   Until M4 lands this renders the tiles as a static grid (no drag/resize). */
'use strict';

const Tiles = {
  mount(container, opts) {
    container.replaceChildren();
    const grid = el('div', { class: 'row', style: 'align-items:flex-start' });
    const api = { refresh() {} };
    for (const d of opts.defs) {
      const body = el('div', { class: 'panel-body' });
      const tile = el('div', {
        class: 'panel',
        style: `flex:${d.span || 3};min-width:260px;max-height:${d.height || 400}px;overflow:auto`,
      }, el('h2', {}, d.title), body);
      grid.append(tile);
      try { d.build(body, api); } catch (e) { body.textContent = 'tile error: ' + e.message; }
    }
    container.append(grid);
    return api;
  },
};

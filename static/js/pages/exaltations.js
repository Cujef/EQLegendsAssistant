/* Exaltations: owned focus/proc/worn/click effects, sockets, move candidates.

   Layout is the draggable / resizable / lockable tile grid (tiles.js). The
   assumed-rules warning stays in the page header, above the grid, because it
   qualifies every "Could move to" cell on the page. Every render* guards on its
   body still being connected, so close → reopen → drag is safe. */
'use strict';

(() => {
  const SKEY = 'eqa.layout.exaltations.v1';
  const els = {};        // tile body elements, set by each build
  let data = null;       // /api/exaltations payload
  let loadedFor = null;  // character id `data` belongs to
  let loading = false;
  let error = '';

  function effCell(effs) {
    if (!effs || !effs.length) return el('span', { class: 'faint' }, 'unknown effect');
    return el('span', {}, effs.map((e, i) =>
      el('span', {}, i ? ' · ' : '', e.effect_name,
        el('span', { class: 'faint' }, ' (' + e.effect_type + ')'))));
  }

  function candCell(entry) {
    if (!entry.candidate_count) return el('span', { class: 'faint' }, 'none');
    const s = el('details', {},
      el('summary', { style: 'cursor:pointer' }, entry.candidate_count + ' possible'),
      el('div', { style: 'padding:4px 0 0 12px' },
        ...entry.candidates.map((c) => el('div', { class: c.host_equipped ? '' : 'muted', style: 'font-size:12px' },
          (c.host_equipped ? '● ' : '○ ') + c.host_item + ' — ' + c.location))));
    return s;
  }

  function wornCol() {
    return {
      key: 'host_equipped', label: 'Worn', num: true,
      render: (r) => r.host_equipped ? el('span', { class: 'good' }, 'yes') : el('span', { class: 'faint' }, 'no'),
    };
  }

  const cols = (extra) => [
    { key: 'item', label: 'Exaltation item' },
    { key: 'effects', label: 'Effect', sortVal: (r) => (r.effects[0] || {}).effect_name || '', render: (r) => effCell(r.effects) },
    ...extra,
    { key: 'candidates', label: 'Could move to', sortVal: (r) => r.candidate_count, render: candCell },
  ];

  /* Tiles can be built before the fetch lands, or after it fails / finds no
     inventory snapshot: every render* funnels through here first. */
  function noData(box) {
    if (data && data.snapshot) return false;
    box.replaceChildren(el('div', { class: 'empty-note' + (error ? ' bad' : '') },
      error || (loading ? 'Loading…' : 'Import your inventory first (Inventory page).')));
    return true;
  }

  function tableTile(bodyKey, opts) {
    const b = els[bodyKey];
    if (!b || !b.isConnected) return;
    if (noData(b)) return;
    b.replaceChildren();
    const host = el('div', {});
    b.append(host);
    renderTable(host, opts);
  }

  // ── tile: socketed exaltations ──────────────────────────────────────────
  function buildSocketed(body) { els.socketed = body; renderSocketed(); }
  function renderSocketed() {
    tableTile('socketed', {
      id: 'ex.sock',
      columns: cols([{ key: 'host_item', label: 'Socketed in' }, wornCol()]),
      rows: (data && data.socketed) || [],
      defaultSort: null,
      empty: 'No socketed exaltations found.',
    });
  }

  // ── tile: loose exaltations ─────────────────────────────────────────────
  function buildLoose(body) { els.loose = body; renderLoose(); }
  function renderLoose() {
    tableTile('loose', {
      id: 'ex.loose',
      columns: cols([{ key: 'where', label: 'Where' }]),
      rows: (data && data.loose) || [],
      defaultSort: null,
      empty: 'No loose exaltations.',
    });
  }

  // ── tile: open sockets ──────────────────────────────────────────────────
  function buildSockets(body) { els.sockets = body; renderSockets(); }
  function renderSockets() {
    tableTile('sockets', {
      id: 'ex.sockets',
      columns: [
        { key: 'host_item', label: 'Item with open socket' },
        { key: 'location', label: 'Socket' },
        wornCol(),
      ],
      rows: (data && data.open_sockets) || [],
      defaultSort: { key: 'host_equipped', dir: -1 },
      empty: 'No open sockets.',
    });
  }

  // ── tile: all known effects ─────────────────────────────────────────────
  function buildEffects(body) { els.effects = body; renderEffects(); }
  function renderEffects() {
    tableTile('effects', {
      id: 'ex.all',
      columns: [
        { key: 'effect_type', label: 'Type' },
        { key: 'effect_name', label: 'Effect' },
        { key: 'description', label: 'Description' },
      ],
      rows: (data && data.all_effects) || [],
      defaultSort: { key: 'effect_type', dir: 1 },
      empty: 'Effect reference is empty - run a Data Sync.',
    });
  }

  // ── tile: unknown exaltations (always a tile, even when empty) ──────────
  function buildUnknown(body) { els.unknown = body; renderUnknown(); }
  function renderUnknown() {
    if (!els.unknown || !els.unknown.isConnected) return;
    const b = els.unknown;
    if (noData(b)) return;
    b.replaceChildren();
    const unknown = data.unknown || [];
    if (!unknown.length) {
      b.append(el('div', { class: 'faint' },
        'None — every exaltation you own is in the item DB.'));
      return;
    }
    b.append(
      el('div', { class: 'muted', style: 'margin-bottom:4px' },
        unknown.length + ' item(s) are not in the item DB yet (run a Data Sync):'),
      el('div', {}, unknown.map((u) => u.item).join(', ')));
  }

  // ── tile registry ───────────────────────────────────────────────────────
  const DEFS = [
    { id: 'socketed', title: 'Socketed (In Your Gear)',              span: 6,  height: 340, minSpan: 4, build: buildSocketed },
    { id: 'loose',    title: 'Loose (Augmentation / Activated)',     span: 6,  height: 340, minSpan: 4, build: buildLoose },
    { id: 'sockets',  title: 'Open Sockets',                         span: 4,  height: 300, minSpan: 3, build: buildSockets },
    { id: 'effects',  title: 'All Known Effects',                    span: 8,  height: 300, minSpan: 3, build: buildEffects },
    { id: 'unknown',  title: 'Unknown Exaltations',                  span: 12, height: 130, minSpan: 3, build: buildUnknown },
  ];

  function renderAll() {
    renderSocketed();
    renderLoose();
    renderSockets();
    renderEffects();
    renderUnknown();
  }

  async function reload() {
    const cid = App.charId();
    if (loadedFor !== cid) { data = null; loadedFor = cid; }
    loading = true;
    error = '';
    renderAll();
    try {
      data = await API.get('/api/exaltations' + App.q());
      loadedFor = cid;
    } catch (e) {
      data = null;
      error = e.message;
    }
    loading = false;
    renderAll();
  }

  Pages.register({
    id: 'exaltations',
    title: 'Exaltations',
    icon: '💠',
    render(container) {
      container.append(
        el('h1', { class: 'page-title' }, 'Exaltations'),
        el('div', { class: 'muted', style: 'margin-bottom:10px' },
          '⚠ Move suggestions use assumed compatibility rules (open Slot7-10 socket; ' +
          'procs prefer weapons) - the game\'s real transfer rules are not fully documented.'));
      const host = el('div', {});
      container.append(host);
      Tiles.mount(host, { storageKey: SKEY, defs: DEFS });
      reload();
    },
  });
})();

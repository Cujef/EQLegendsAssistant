/* Inventory page: import the /outputfile inventory dump, browse it.

   Layout is the draggable / resizable / lockable tile grid (tiles.js). Import
   stays a PAGE action (it acts on the whole page, not one tile); the item
   filters live inside the items tile, above its table. Every render* guards on
   its body still being connected, so close → reopen → drag is safe. */
'use strict';

(() => {
  const SKEY = 'eqa.layout.inventory.v1';
  const els = {};       // tile body elements + the items table host
  let view = null;      // /api/inventory payload, fetched once per load
  let loadedFor = null; // character id `view` belongs to
  let loading = false;
  let error = '';
  let filter = { q: '', section: 'all' };
  let spriteCache = {}; // icon -> {url,x,y}

  function section(row) {
    if (row.is_equipped) return 'worn';
    if (row.root.startsWith('SharedBank')) return 'shared';
    if (row.root.startsWith('Bank')) return 'bank';
    if (row.root.startsWith('General')) return 'bags';
    return 'other';
  }

  function iconCell(row) {
    if (!row.icon || !spriteCache[row.icon]) return null;
    const sp = spriteCache[row.icon];
    return el('span', {
      class: 'item-icon small',
      style: `background-image:url(${sp.url});background-position:-${sp.x}px -${sp.y}px`,
      title: 'icon ' + row.icon,
    });
  }

  async function loadSprites(rows) {
    // Never re-request an icon: failures are negative-cached as null, otherwise a
    // single unmaterializable icon turns render->load->render into an infinite loop.
    const want = [...new Set(rows.map((r) => r.icon).filter((n) => n && !(n in spriteCache)))];
    if (!want.length) return 0;
    let fresh = 0;
    try {
      const got = await API.get('/api/sprites?icons=' + want.join(','));
      for (const n of want) {
        spriteCache[n] = got[n] || null;
        if (got[n]) fresh++;
      }
    } catch (e) {
      for (const n of want) spriteCache[n] = null;
    }
    return fresh;
  }

  function rowsFiltered() {
    const q = filter.q.toLowerCase();
    return ((view && view.items) || []).filter((r) => {
      if (filter.section !== 'all' && section(r) !== filter.section) return false;
      return !q || r.name.toLowerCase().includes(q) || r.location.toLowerCase().includes(q);
    });
  }

  /* Tiles can be built before the first fetch lands, or after an import error. */
  function noData(box) {
    if (view && view.snapshot) return false;
    box.replaceChildren(el('div', { class: 'empty-note' + (error ? ' bad' : '') },
      error || (loading ? 'Loading…'
        : 'No inventory imported yet. In game: /outputfile inventory — then press Import.')));
    return true;
  }

  function statRow(label, value, cls) {
    return el('div', { style: 'display:flex;gap:10px;justify-content:space-between;' +
      'padding:3px 0;border-bottom:1px solid var(--edge)' },
      el('span', { class: 'muted' }, label),
      el('span', { class: 'num' + (cls ? ' ' + cls : '') }, value));
  }

  // ── tile: items (filters + table) ───────────────────────────────────────
  function buildItems(body) { els.items = body; renderItems(); }
  function renderItems() {
    if (!els.items || !els.items.isConnected) return;
    const b = els.items;
    els.itemsTable = null;
    if (noData(b)) return;
    b.replaceChildren();

    const search = el('input', { type: 'search', placeholder: 'Filter items…', value: filter.q });
    search.addEventListener('input', () => { filter.q = search.value; renderItemsTable(); });
    const sect = el('select', {},
      el('option', { value: 'all' }, 'All locations'),
      el('option', { value: 'worn' }, 'Worn'),
      el('option', { value: 'bags' }, 'Bags'),
      el('option', { value: 'bank' }, 'Bank'),
      el('option', { value: 'shared' }, 'Shared bank'),
      el('option', { value: 'other' }, 'Other'));
    for (const o of sect.options) if (o.value === filter.section) o.selected = true;
    sect.addEventListener('change', () => { filter.section = sect.value; renderItemsTable(); });

    // The filter row is built once per tile build: re-rendering only the table
    // below it keeps the search box's focus and caret while you type.
    const table = el('div', {});
    els.itemsTable = table;
    b.append(el('div', { class: 'row', style: 'align-items:center;margin-bottom:8px' },
      search, sect), table);
    renderItemsTable();
  }

  function renderItemsTable() {
    if (!els.itemsTable || !els.itemsTable.isConnected) return;
    renderTable(els.itemsTable, {
      id: 'inventory',
      columns: [
        { key: 'icon', label: '', render: iconCell },
        { key: 'name', label: 'Item' },
        { key: 'location', label: 'Location' },
        {
          key: 'flags', label: 'Notes',
          sortVal: (r) => (r.is_exaltation ? 2 : 0) + (r.upgrade_tier ? 1 : 0),
          render: (r) => {
            const bits = [];
            if (r.is_exaltation) bits.push('Exaltation');
            if (r.upgrade_tier) bits.push('+' + r.upgrade_tier);
            // `Slots` on equipment means augment capacity; it is a bag only when
            // it sits directly in a General/Bank/SharedBank slot.
            if (r.slots && !r.parent_location && /^(General|Bank|SharedBank)/.test(r.root)) {
              bits.push(r.slots + '-slot bag');
            }
            if (!r.in_item_db) bits.push('no item data');
            return bits.join(' · ') || null;
          },
        },
        { key: 'count', label: 'Count', num: true },
        { key: 'item_id', label: 'ID', num: true },
      ],
      rows: rowsFiltered(),
      defaultSort: null,
      empty: 'No items match.',
    });
  }

  // ── tile: summary ───────────────────────────────────────────────────────
  function buildSummary(body) { els.summary = body; renderSummary(); }
  function renderSummary() {
    if (!els.summary || !els.summary.isConnected) return;
    const b = els.summary;
    if (noData(b)) return;
    b.replaceChildren();
    const items = view.items || [];
    const exalts = items.filter((r) => r.is_exaltation).length;
    const nodb = items.filter((r) => !r.in_item_db).length;
    b.append(
      statRow('Items', fmt(items.length)),
      statRow('Exaltations', fmt(exalts)),
      statRow('Open sockets', fmt((view.open_sockets || []).length)),
      statRow('No item-DB match', fmt(nodb), nodb ? 'warn' : ''),
      statRow('Imported', new Date(view.snapshot.imported_at * 1000).toLocaleString()));
    if (nodb) {
      b.append(el('div', { class: 'faint', style: 'margin-top:6px;font-size:12px' },
        'Items with no item-DB match have no stats or effects — run a Data Sync.'));
    }
  }

  // ── tile: open sockets ──────────────────────────────────────────────────
  function buildSockets(body) { els.sockets = body; renderSockets(); }
  function socketRows() {
    const byLoc = {};
    for (const r of (view.items || [])) byLoc[r.location] = r;
    return (view.open_sockets || []).map((s) => ({
      location: s.location,
      host: (byLoc[s.parent_location] || {}).name || null,
    }));
  }
  function renderSockets() {
    if (!els.sockets || !els.sockets.isConnected) return;
    const b = els.sockets;
    if (noData(b)) return;
    b.replaceChildren();
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'inv.sockets',
      columns: [
        { key: 'location', label: 'Socket' },
        { key: 'host', label: 'On item' },
      ],
      rows: socketRows(),
      defaultSort: { key: 'host', dir: 1 },
      empty: 'No open sockets.',
    });
  }

  // ── tile registry ───────────────────────────────────────────────────────
  const DEFS = [
    { id: 'items',   title: 'Items',        span: 8, height: 520, minSpan: 4, build: buildItems },
    { id: 'summary', title: 'Summary',      span: 4, height: 240, minSpan: 3, build: buildSummary },
    { id: 'sockets', title: 'Open Sockets', span: 4, height: 270, minSpan: 3, build: buildSockets },
  ];

  function renderAll() {
    renderItems();
    renderSummary();
    renderSockets();
  }

  async function reload() {
    const cid = App.charId();
    if (loadedFor !== cid) { view = null; loadedFor = cid; }
    loading = true;
    error = '';
    renderAll();
    try {
      view = await API.get('/api/inventory' + App.q());
      loadedFor = cid;
    } catch (e) {
      view = null;
      error = e.message;
    }
    loading = false;
    renderAll();
    if (view && view.items) {
      // sprite fetch happens once per data load, never from a render function
      const fresh = await loadSprites(view.items);
      if (fresh) renderItemsTable();
    }
  }

  Pages.register({
    id: 'inventory',
    title: 'Inventory',
    icon: '🎒',
    render(container) {
      const importBtn = el('button', { class: 'metal-btn primary' }, 'Import inventory file');
      const status = el('span', { class: 'muted', style: 'margin-left:10px' });
      importBtn.addEventListener('click', async () => {
        importBtn.disabled = true;
        status.className = 'muted';          // clear a previous failure's red
        status.textContent = 'importing…';
        try {
          const res = await API.post('/api/inventory/import' + App.q());
          status.textContent = res.unchanged
            ? 'File unchanged since last import.'
            : `Imported ${res.items} items (${res.exaltations} exaltations).`;
          await reload();
        } catch (e) {
          status.textContent = e.message;
          status.className = 'bad';
        } finally { importBtn.disabled = false; }
      });

      container.append(
        el('h1', { class: 'page-title' }, 'Inventory'),
        el('div', { class: 'row', style: 'align-items:center;margin-bottom:10px' },
          importBtn, status));
      const host = el('div', {});
      container.append(host);
      Tiles.mount(host, { storageKey: SKEY, defs: DEFS });
      reload();
    },
  });
})();

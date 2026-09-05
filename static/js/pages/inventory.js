/* Inventory page: browse the imported /outputfile inventory dump.

   Import is a PAGE action that opens the shared Import Inventory dialog (the
   same one the sidebar offers). Layout is the draggable / resizable / lockable
   tile grid (tiles.js); the item filters live inside the items tile, above its
   table. Every render* guards on its body still being connected, so close →
   reopen → drag is safe.

   Server-side facts this page leans on (app/inventory.py): rows carry
   `section` (worn/bags/bank/shared/lists/depot), `host_name` (the item a socket
   or pocket sits in — resolved by row order, since paired slots repeat their
   Location string), `is_pocket`; `containers` lists every bag incl. nested ones;
   `ladder` groups +N tiers and duplicate copies; `lists` are the trailing
   Augmentation / Activated / Equipment sections. */
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
    if (row.section) return row.section;
    if (row.is_equipped) return 'worn';
    if (row.root.startsWith('SharedBank')) return 'shared';
    if (row.root.startsWith('Bank')) return 'bank';
    if (row.root.startsWith('General')) return 'bags';
    return 'other';
  }
  function bagSeqs() {
    return new Set((view && view.containers || []).map((c) => c.seq).filter((s) => s !== null && s !== undefined));
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
      return !q || r.name.toLowerCase().includes(q) || r.location.toLowerCase().includes(q)
        || (r.host_name && r.host_name.toLowerCase().includes(q));
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

  // ── tile: items (filters + table) ───────────────────────────────────────
  function buildItems(body, api) {
    els.items = body;
    if (api && api.addAction) Tiles.addExport(api, 'inventory');
    renderItems();
  }
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
      el('option', { value: 'lists' }, 'Keyring lists'),
      el('option', { value: 'depot' }, 'Depot'),
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
    const bags = bagSeqs();
    renderTable(els.itemsTable, {
      id: 'inventory',
      columns: [
        { key: 'icon', label: '', render: iconCell },
        { key: 'name', label: 'Item' },
        {
          key: 'location', label: 'Location',
          render: (r) => r.host_name
            ? el('span', { title: r.location }, r.location, ' ',
                el('span', { class: 'faint' }, r.is_pocket ? `in ${r.host_name}` : `on ${r.host_name}`))
            : r.location,
        },
        {
          key: 'flags', label: 'Notes',
          sortVal: (r) => (r.is_exaltation ? 2 : 0) + (r.upgrade_tier ? 1 : 0),
          render: (r) => {
            const bits = [];
            if (r.is_exaltation) bits.push('Exaltation');
            if (r.upgrade_tier) bits.push('+' + r.upgrade_tier);
            // bag-ness comes from the server's container detection (nested bags included)
            if (bags.has(r.seq)) bits.push(r.slots + '-slot bag');
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
    const bags = (view.containers || []).length;
    const nested = (view.containers || []).filter((c) => c.nested).length;
    b.append(
      statRow('Items', fmt(items.length)),
      statRow('Exaltations', fmt(exalts)),
      statRow('Open sockets', fmt((view.open_sockets || []).length)),
      statRow('Bags', fmt(bags) + (nested ? ` (${nested} inside other bags)` : '')),
      statRow('No item-DB match', fmt(nodb), nodb ? 'warn' : ''),
      statRow('Imported', new Date(view.snapshot.imported_at * 1000).toLocaleString()));
    if (nodb) {
      b.append(el('div', { class: 'faint', style: 'margin-top:6px;font-size:12px' },
        'Items with no item-DB match have no stats or effects — run a Data Sync.'));
    }
  }

  // ── tile: open sockets ──────────────────────────────────────────────────
  function buildSockets(body) { els.sockets = body; renderSockets(); }
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
        { key: 'host_name', label: 'On item' },
        {
          key: 'host_equipped', label: 'Worn', num: true,
          render: (r) => r.host_equipped ? 'yes' : el('span', { class: 'faint' }, 'no'),
        },
      ],
      rows: view.open_sockets || [],
      defaultSort: { key: 'host_name', dir: 1 },
      empty: 'No open sockets.',
    });
  }

  // ── tile: bag & bank space ──────────────────────────────────────────────
  function buildSpace(body) { els.space = body; renderSpace(); }
  function renderSpace() {
    if (!els.space || !els.space.isConnected) return;
    const b = els.space;
    if (noData(b)) return;
    b.replaceChildren();
    const sp = view.space || {};
    const line = el('div', { class: 'row', style: 'gap:18px;margin-bottom:8px;font-size:12px' });
    for (const [key, label] of [['bags', 'Bags'], ['bank', 'Bank'], ['shared', 'Shared bank']]) {
      const s = sp[key];
      line.append(el('span', {}, el('span', { class: 'muted' }, label + ': '),
        s ? el('span', { class: s.free ? '' : 'warn' }, `${fmt(s.free)} free of ${fmt(s.capacity)}`)
          : el('span', { class: 'faint' }, 'no bags')));
    }
    b.append(line);
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'inv.space',
      columns: [
        {
          key: 'location', label: 'Slot',
          render: (r) => r.nested ? el('span', { title: 'a bag inside another bag' }, r.location, ' ', el('span', { class: 'faint' }, '(nested)')) : r.location,
        },
        { key: 'name', label: 'Bag' },
        { key: 'capacity', label: 'Size', num: true },
        { key: 'used', label: 'Used', num: true },
        {
          key: 'free', label: 'Free', num: true,
          render: (r) => el('span', { class: r.free ? (r.free === r.capacity ? 'faint' : '') : 'warn' }, String(r.free)),
        },
      ],
      rows: view.containers || [],
      defaultSort: { key: 'free', dir: 1 },
      empty: 'No bags found in the dump.',
    });
  }

  // ── tile: upgrade ladder ────────────────────────────────────────────────
  function buildLadder(body) { els.ladder = body; renderLadder(); }
  function renderLadder() {
    if (!els.ladder || !els.ladder.isConnected) return;
    const b = els.ladder;
    if (noData(b)) return;
    b.replaceChildren();
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'inv.ladder',
      columns: [
        {
          key: 'name', label: 'Item',
          render: (r) => r.upgrade_available
            ? el('span', {}, r.name, ' ', el('span', { class: 'good', title: 'a higher +N copy than the one you wear' }, '▲ better copy owned'))
            : r.name,
        },
        {
          key: 'worn_tier', label: 'Worn', num: true,
          render: (r) => r.worn_tier === null ? el('span', { class: 'faint' }, 'not worn') : '+' + r.worn_tier,
        },
        {
          key: 'tiers', label: 'Copies (+N)',
          sortVal: (r) => r.best_tier,
          render: (r) => `${r.copies}× ` + r.tiers.map((t) => '+' + t).join(', '),
        },
        {
          key: 'exalt_copies', label: 'Exaltations', num: true,
          render: (r) => r.exalt_copies ? String(r.exalt_copies) : el('span', { class: 'faint' }, '-'),
        },
        {
          key: 'merges', label: 'Merges (log)', num: true,
          render: (r) => r.merges
            ? el('span', { title: 'times the log saw two copies merged into this item' },
                String(r.merges) + (r.merge_max_tier ? ` → +${r.merge_max_tier}` : ''))
            : el('span', { class: 'faint' }, '-'),
        },
        {
          key: 'locations', label: 'Where',
          render: (r) => r.locations.map((l) => l.location + (l.tier ? ` +${l.tier}` : '') + (l.exaltation ? ' (ex)' : '')).join(', '),
        },
      ],
      rows: view.ladder || [],
      defaultSort: { key: 'worn_tier', dir: -1 },
      empty: 'No upgraded (+N) items, duplicates, or exaltation copies to compare.',
    });
  }

  // ── tile: loot history (from the log) ───────────────────────────────────
  let lootData = null, lootQuery = '', lootTimer = null;
  function buildLoot(body, api) {
    els.loot = body;
    if (api && api.addAction) Tiles.addExport(api, 'loot');
    body.replaceChildren();
    const search = el('input', { type: 'search', placeholder: 'Where did … drop? Filter by item', value: lootQuery });
    search.addEventListener('input', () => {
      lootQuery = search.value;
      clearTimeout(lootTimer);
      lootTimer = setTimeout(fetchLoot, 250);      // debounced; the box is built once so focus survives
    });
    const table = el('div', {});
    els.lootTable = table;
    body.append(el('div', { class: 'row', style: 'align-items:center;margin-bottom:8px' }, search), table);
    if (lootData) renderLoot(); else fetchLoot();
  }
  async function fetchLoot() {
    if (!App.active) return;
    try { lootData = await API.get('/api/loot' + App.q({ q: lootQuery })); }
    catch (e) { lootData = { items: [], recent: [], total_events: 0, error: e.message }; }
    renderLoot();
  }
  function renderLoot() {
    if (!els.lootTable || !els.lootTable.isConnected) return;
    const host = els.lootTable;
    if (!lootData) { host.replaceChildren(el('div', { class: 'empty-note' }, 'Loading…')); return; }
    if (lootData.error) { host.replaceChildren(el('div', { class: 'empty-note bad' }, lootData.error)); return; }
    renderTable(host, {
      id: 'inv.loot',
      columns: [
        {
          key: 'item', label: 'Item',
          render: (r) => r.in_item_db ? r.item : el('span', { title: 'not in the item database' }, r.item, ' ', el('span', { class: 'faint' }, '?')),
        },
        { key: 'count', label: 'Drops', num: true },
        { key: 'qty', label: 'Qty', num: true, render: (r) => r.qty !== r.count ? fmt(r.qty) : el('span', { class: 'faint' }, '-') },
        {
          key: 'sources', label: 'Dropped by', sortVal: (r) => (r.sources[0] && r.sources[0].source) || '',
          render: (r) => r.sources.length
            ? r.sources.map((s) => `${s.source}${s.zone ? ' (' + s.zone + ')' : ''} ×${s.n}`).join(', ')
            : null,
        },
        { key: 'first_ts', label: 'First', num: true, render: (r) => r.first_ts ? new Date(r.first_ts * 1000).toLocaleDateString() : null },
        { key: 'last_ts', label: 'Last', num: true, render: (r) => r.last_ts ? new Date(r.last_ts * 1000).toLocaleDateString() : null },
      ],
      rows: lootData.items || [],
      defaultSort: { key: 'count', dir: -1 },
      empty: lootQuery ? 'Nothing looted matches that.' : 'No loot lines in the log yet.',
    });
    if (lootData.total_events) {
      host.append(el('div', { class: 'faint', style: 'margin-top:6px;font-size:11px' },
        `${fmt(lootData.total_events)} loot lines in the log · zone is the one you were in when it dropped`));
    }
  }

  // ── tile: merge history (from the log) ──────────────────────────────────
  function buildMerges(body, api) {
    els.merges = body;
    if (api && api.addAction) Tiles.addExport(api, 'merges');
    renderMerges();
  }
  function renderMerges() {
    if (!els.merges || !els.merges.isConnected) return;
    const b = els.merges;
    b.replaceChildren();
    const rows = (view && view.merge_history) || [];
    const t = (view && view.merge_totals) || {};
    if (t.merges) {
      b.append(el('div', { class: 'muted', style: 'font-size:12px;margin-bottom:6px' },
        `${fmt(t.merges)} merges across ${fmt(t.items)} items — from "You have successfully merged two items" log lines`));
    }
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'inv.merges',
      columns: [
        { key: 'ts', label: 'When', num: true, render: (r) => new Date(r.ts * 1000).toLocaleString() },
        { key: 'item', label: 'Result' },
        {
          key: 'tier', label: 'Tier', num: true,
          render: (r) => r.tier === null || r.tier === undefined
            ? el('span', { class: 'faint', title: 'a rank merge, not a +N upgrade' }, 'rank') : '+' + r.tier,
        },
      ],
      rows,
      defaultSort: { key: 'ts', dir: -1 },
      empty: 'No item merges in the log yet.',
    });
  }

  // ── tile: keyring lists ─────────────────────────────────────────────────
  function buildLists(body) { els.lists = body; renderLists(); }
  function renderLists() {
    if (!els.lists || !els.lists.isConnected) return;
    const b = els.lists;
    if (noData(b)) return;
    b.replaceChildren();
    const lists = view.lists || {};
    const rows = [];
    for (const [cat, label, note] of [
      ['augmentation', 'Augmentation', 'unsocketed exaltations you own'],
      ['activated', 'Activated', 'activated exaltations'],
      ['equipment', 'Equipment', 'meaning not confirmed — shown, never counted as worn'],
    ]) {
      for (const r of lists[cat] || []) rows.push({ category: label, note, name: r.name, item_id: r.item_id, in_item_db: r.in_item_db });
    }
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'inv.lists',
      columns: [
        { key: 'category', label: 'List', render: (r) => el('span', { title: r.note }, r.category) },
        { key: 'name', label: 'Item' },
        { key: 'item_id', label: 'ID', num: true },
      ],
      rows,
      defaultSort: { key: 'category', dir: 1 },
      empty: 'The dump had no trailing keyring sections.',
    });
    b.append(el('div', { class: 'faint', style: 'margin-top:6px;font-size:11px' },
      'These are the 3-column lists after the main body. "Equipment" is undocumented — '
      + 'its items appear nowhere else in the dump, so they are listed but not counted.'));
  }

  // ── tile registry ───────────────────────────────────────────────────────
  const DEFS = [
    { id: 'items',   title: 'Items',            span: 8, height: 520, minSpan: 4, build: buildItems },
    { id: 'summary', title: 'Summary',          span: 4, height: 250, minSpan: 3, build: buildSummary },
    { id: 'sockets', title: 'Open Sockets',     span: 4, height: 260, minSpan: 3, build: buildSockets },
    { id: 'space',   title: 'Bag & Bank Space', span: 6, height: 330, minSpan: 3, build: buildSpace },
    { id: 'ladder',  title: 'Upgrade Ladder',   span: 6, height: 330, minSpan: 3, build: buildLadder },
    { id: 'lists',   title: 'Keyring Lists',    span: 6, height: 260, minSpan: 3, build: buildLists },
    { id: 'merges',  title: 'Merge History (From The Log)', span: 6, height: 260, minSpan: 3, build: buildMerges },
    { id: 'loot',    title: 'Loot History (From The Log)',  span: 12, height: 360, minSpan: 4, build: buildLoot },
  ];

  function renderAll() {
    renderItems();
    renderSummary();
    renderSockets();
    renderSpace();
    renderLadder();
    renderLists();
    renderMerges();
  }

  async function reload() {
    const cid = App.charId();
    if (loadedFor !== cid) { view = null; loadedFor = cid; lootData = null; }
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
      const importBtn = el('button', { class: 'metal-btn primary' }, '⤓ Import inventory…');
      importBtn.addEventListener('click', () => ImportInventory.open({ onDone: () => reload() }));
      const hint = el('span', { class: 'muted', style: 'margin-left:10px;font-size:12px' },
        view && view.snapshot
          ? 'Last import ' + new Date(view.snapshot.imported_at * 1000).toLocaleString()
          : 'In game: /outputfile inventory');
      container.append(
        el('h1', { class: 'page-title' }, 'Inventory'),
        el('div', { class: 'row', style: 'align-items:center;margin-bottom:10px' },
          importBtn, hint));
      const host = el('div', {});
      container.append(host);
      Tiles.mount(host, { storageKey: SKEY, defs: DEFS });
      reload();
    },
  });
})();

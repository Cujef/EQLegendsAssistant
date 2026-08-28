/* Inventory page: import the /outputfile inventory dump, browse it. */
'use strict';

(() => {
  let view = null;      // /api/inventory payload
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
    return (view.items || []).filter((r) => {
      if (filter.section !== 'all' && section(r) !== filter.section) return false;
      return !q || r.name.toLowerCase().includes(q) || r.location.toLowerCase().includes(q);
    });
  }

  function renderBody(container) {
    const body = container.querySelector('.inv-body');
    if (!view || !view.snapshot) {
      body.replaceChildren(el('div', { class: 'empty-note' },
        'No inventory imported yet. In game: /outputfile inventory — then press Import.'));
      return;
    }
    const meta = container.querySelector('.inv-meta');
    const dt = new Date(view.snapshot.imported_at * 1000).toLocaleString();
    const exalts = view.items.filter((r) => r.is_exaltation).length;
    meta.textContent = `${view.items.length} items · ${exalts} exaltations · ` +
      `${(view.open_sockets || []).length} open sockets · imported ${dt}`;

    const rows = rowsFiltered();
    renderTable(body, {
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
      rows,
      defaultSort: null,
      empty: 'No items match.',
    });
  }

  async function reload(container) {
    try {
      view = await API.get('/api/inventory' + App.q());
    } catch (e) {
      view = null;
    }
    renderBody(container);
    if (view && view.items) {
      // sprite fetch happens once per data load, never from renderBody itself
      const fresh = await loadSprites(view.items);
      if (fresh && container.isConnected) renderBody(container);
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
        status.textContent = 'importing…';
        try {
          const res = await API.post('/api/inventory/import' + App.q());
          status.textContent = res.unchanged
            ? 'File unchanged since last import.'
            : `Imported ${res.items} items (${res.exaltations} exaltations).`;
          await reload(container);
        } catch (e) {
          status.textContent = e.message;
          status.className = 'bad';
        } finally { importBtn.disabled = false; }
      });

      const search = el('input', { type: 'search', placeholder: 'Filter items…' });
      search.addEventListener('input', () => { filter.q = search.value; renderBody(container); });
      const sect = el('select', {},
        el('option', { value: 'all' }, 'All locations'),
        el('option', { value: 'worn' }, 'Worn'),
        el('option', { value: 'bags' }, 'Bags'),
        el('option', { value: 'bank' }, 'Bank'),
        el('option', { value: 'shared' }, 'Shared bank'),
        el('option', { value: 'other' }, 'Other'));
      sect.addEventListener('change', () => { filter.section = sect.value; renderBody(container); });

      container.append(
        el('h1', { class: 'page-title' }, 'Inventory'),
        el('div', { class: 'row', style: 'align-items:center;margin-bottom:10px' },
          importBtn, status, el('span', { class: 'grow' }), search, sect),
        el('div', { class: 'muted inv-meta', style: 'margin-bottom:8px' }),
        el('div', { class: 'panel' },
          el('div', { class: 'panel-body inv-body', style: 'max-height:calc(100vh - 240px);overflow:auto' })),
      );
      reload(container);
    },
  });
})();

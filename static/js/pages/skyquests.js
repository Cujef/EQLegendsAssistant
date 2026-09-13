/* Sky Quests: every Plane of Sky class test for all 16 classes, joined to the
   imported /outputfile inventory dump.

   Server facts this page leans on (app/skyquests.py): each test has one Wind
   Rune plus one to three quest items; a need is `ok` when a tradeable copy is
   in the dump (+N copies count, Exaltation copies and the keyring lists never
   do); a test is done when its reward is anywhere in the dump (auto) or when
   you tick it (manual — a manual tick beats the dump either way, ↺ clears it).
   "Turn in now" allocates shared runes once, your own classes first, so it is
   never larger than the raw "ready" count. Your classes (Overview: class 1–3)
   are pinned to the top of the class list and the table. */
'use strict';

(() => {
  const SQ_CSS = `
.sq-badge { display:inline-block; margin-left:6px; padding:0 5px; vertical-align:1px;
  font:700 9px var(--font-display); letter-spacing:0.1em; text-transform:uppercase;
  border:1px solid var(--edge-strong); color:var(--text-dim); white-space:nowrap; }
.sq-badge.good { color:var(--good); border-color:var(--good); }
.sq-badge.warn { color:var(--warn); border-color:var(--warn); }
.sq-badge.info { color:var(--info); border-color:var(--info); }
.sq-need { display:inline-flex; align-items:center; gap:4px; margin:1px 10px 1px 0; white-space:nowrap; }
.sq-need input { margin:0; }
.sq-need.miss { color:var(--text-dim); }
.sq-src { color:var(--text-faint); font-size:10px; }
.sq-say { color:var(--text-faint); font-size:11px; }
.sq-pin { color:var(--accent); }
.sq-done-cell { display:inline-flex; align-items:center; gap:2px; white-space:nowrap; }
.sq-done-cell input { margin:0 2px 0 0; }
.sq-undo { padding:0 5px; font-size:12px; line-height:16px; margin-left:4px; }
tr.sq-done td, tr.sq-done td a { color:var(--text-faint); }
tr.sq-done td .sq-need.miss { color:var(--text-faint); }
tr.sq-ready td { background:var(--sel-bg); }
.sq-filters { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:8px; }
.sq-toggle { display:flex; align-items:center; gap:6px; font-size:12px; color:var(--text-dim);
  cursor:pointer; user-select:none; }
.sq-classes { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:2px 18px; }
.sq-class { display:grid; grid-template-columns:120px minmax(0, 1fr) 56px 60px; align-items:center;
  gap:8px; cursor:pointer; padding:2px 4px; font-size:12px; }
.sq-class:hover { background:var(--table-hover); }
.sq-class.sel { outline:1px solid var(--accent); }
.sq-class .sq-cname { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.sq-class.pinned .sq-cname { color:var(--accent); font-weight:700; }
.sq-class .bar-track { height:12px; }
.sq-class .bar-label { line-height:12px; font-size:9px; }
.sq-overall .bar-track { height:22px; margin:4px 0 10px; }
.sq-overall .bar-label { line-height:22px; font-size:12px; }
.sq-note { color:var(--text-faint); font-size:11px; line-height:1.5; margin-top:8px; }
`;
  const SKEY = 'eqa.layout.skyquests.v1';
  const els = {};
  let data = null;
  let loadedFor = null;
  let error = '';
  let filter = { cls: 'all', hideDone: false, q: '' };
  let spriteCache = {};
  let lastAutoReload = 0;

  function pending(box) {
    if (data) return false;
    box.replaceChildren(el('div', { class: 'empty-note' + (error ? ' bad' : '') },
      error || 'Loading…'));
    return true;
  }
  function pinRank(cls) {
    const i = (data && data.pinned_classes || []).indexOf(cls);
    return i < 0 ? 99 : i;
  }

  // ── icons (same sprite sheet + negative cache as the Inventory page) ────
  function iconCell(icon) {
    if (!icon || !spriteCache[icon]) return null;
    const sp = spriteCache[icon];
    return el('span', {
      class: 'item-icon small',
      style: `background-image:url(${sp.url});background-position:-${sp.x}px -${sp.y}px`,
    });
  }
  async function loadSprites() {
    if (!data) return 0;
    const icons = [];
    for (const r of data.quests || []) {
      icons.push(r.reward.icon);
      for (const n of r.needs) icons.push(n.icon);
    }
    const want = [...new Set(icons.filter((n) => n && !(n in spriteCache)))];
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

  // ── bars ────────────────────────────────────────────────────────────────
  function bar(pct, label) {
    return el('div', { class: 'bar-track' },
      el('div', { class: 'bar-fill', style: `width:${Math.max(0, Math.min(100, pct || 0))}%` }),
      el('div', { class: 'bar-label' }, label));
  }

  // ── tile: overview ──────────────────────────────────────────────────────
  function buildOverview(body) { els.overview = body; renderOverview(); }
  function renderOverview() {
    if (!els.overview || !els.overview.isConnected) return;
    const b = els.overview;
    if (pending(b)) return;
    const t = data.totals || {};
    const src = data.source || {};
    const turnIn = el('span', {}, fmt(t.covered || 0));
    if ((t.ready || 0) > (t.covered || 0)) {
      turnIn.append(el('span', { class: 'faint', title: data.notes && data.notes.ready },
        ` of ${fmt(t.ready)} ready`));
    }
    const inv = data.snapshot
      ? el('span', { title: 'the inventory dump these ticks come from' }, timeCell(data.snapshot.imported_at))
      : el('span', { class: 'warn' }, 'none imported');
    const list = src.kind === 'wiki'
      ? el('span', { title: src.url || '' }, 'wiki, synced ' + (dateCell(src.fetched_at) || '—'))
      : src.kind === 'bundled' ? el('span', { title: 'the snapshot shipped with the app' }, 'bundled snapshot')
        : el('span', { class: 'bad' }, 'none');
    b.replaceChildren(el('div', {},
      el('div', { class: 'sq-overall' },
        bar(t.pct, `${fmt(t.done || 0)} / ${fmt(t.total || 0)} tests · ${(t.pct || 0).toFixed(1)}%`)),
      statRow('Completed', fmt(t.done || 0), 'good'),
      statRow('Turn in now', turnIn, (t.covered || 0) > 0 ? 'good' : ''),
      statRow('Auto-detected', fmt(t.auto || 0)),
      statRow('Manual marks', fmt(t.manual || 0)),
      statRow('Runes short', fmt(t.runes_short || 0), (t.runes_short || 0) > 0 ? 'bad' : 'good'),
      statRow('Inventory dump', inv),
      statRow('Test list', list),
      src.warning ? el('div', { class: 'bad', style: 'margin-top:8px;font-size:12px' }, src.warning) : null,
      el('div', { class: 'sq-note' }, (data.notes && data.notes.auto) || '')));
  }

  // ── tile: classes ───────────────────────────────────────────────────────
  function buildClasses(body) { els.classes = body; renderClasses(); }
  function renderClasses() {
    if (!els.classes || !els.classes.isConnected) return;
    const b = els.classes;
    if (pending(b)) return;
    const grid = el('div', { class: 'sq-classes' });
    for (const c of data.classes || []) {
      const row = el('div', {
        class: 'sq-class' + (c.pinned ? ' pinned' : '') + (filter.cls === c.name ? ' sel' : ''),
        title: c.pinned ? 'one of your classes (Overview: class 1–3) — click to filter the table'
          : 'click to filter the table to this class',
      },
      el('span', { class: 'sq-cname' }, c.pinned ? '★ ' : '', c.name),
      bar(c.pct, `${c.pct.toFixed(0)}%`),
      el('span', { class: 'num' }, `${c.done}/${c.total}`),
      el('span', { class: 'num ' + (c.covered ? 'good' : 'faint'),
        title: 'tests you can turn in now' }, c.covered ? `${c.covered} ready` : '—'));
      row.addEventListener('click', () => {
        filter.cls = filter.cls === c.name ? 'all' : c.name;
        if (els.clsSelect) els.clsSelect.value = filter.cls;
        renderClasses();
        renderQuestsTable();
      });
      grid.append(row);
    }
    b.replaceChildren(grid,
      el('div', { class: 'sq-note' },
        'Finish every test of a class to unlock it as a primary class. Your classes are pinned first.'));
  }

  // ── tile: runes ─────────────────────────────────────────────────────────
  function buildRunes(body) { els.runes = body; renderRunes(); }
  function renderRunes() {
    if (!els.runes || !els.runes.isConnected) return;
    const b = els.runes;
    if (pending(b)) return;
    const host = el('div', {});
    b.replaceChildren(host);
    renderTable(host, {
      id: 'sq.runes',
      columns: [
        { key: 'name', label: 'Wind Rune', render: (r) => el('span', {}, iconCell(r.icon), ' ', r.name) },
        {
          key: 'supply', label: 'Have', num: true,
          render: (r) => el('span', { class: r.supply ? '' : 'faint' }, fmt(r.supply),
            r.supply && !r.supply_base ? el('span', { class: 'faint', title: 'only +N copies' }, ' +N') : ''),
        },
        { key: 'demand_open', label: 'Open tests want', num: true },
        {
          key: 'short', label: 'Short', num: true,
          render: (r) => el('span', { class: r.short ? 'bad' : 'good' }, r.short ? fmt(r.short) : '✔'),
        },
      ],
      rows: data.runes || [],
      defaultSort: { key: 'short', dir: -1 },
      empty: 'No runes in the list.',
    });
    if (!data.snapshot) {
      b.append(el('div', { class: 'sq-note' }, 'Import your inventory (sidebar) to see what you hold.'));
    }
  }

  // ── tile: tests table ───────────────────────────────────────────────────
  function needChip(n) {
    const cb = el('input', { type: 'checkbox', disabled: '' });
    cb.checked = !!n.ok;
    const bits = [`${n.have}/${n.qty} in the dump`];
    if (n.have_upgraded) bits.push(`${n.have_upgraded} as +N`);
    if (n.no_drop) bits.push('no drop');
    if (n.src) bits.push('island/boss: ' + n.src);
    if (n.demand_open > 1) bits.push(`${n.demand_open} open tests want this`);
    const chip = el('span', { class: 'sq-need' + (n.ok ? '' : ' miss'), title: bits.join(' · ') },
      cb, iconCell(n.icon), el('span', {}, n.display));
    if (n.have > 1) chip.append(el('span', { class: 'faint' }, ' ×' + n.have));
    if (n.upgraded_only) chip.append(el('span', { class: 'faint', title: 'you only hold an upgraded (+N) copy' }, ' +N'));
    if (n.src) chip.append(el('span', { class: 'sq-src' }, ' (' + n.src + ')'));
    if (n.no_drop) chip.append(el('span', { class: 'sq-src', title: 'no drop' }, ' ND'));
    if (n.contended) {
      chip.append(el('span', { class: 'sq-badge warn',
        title: `${n.demand_open} open tests want this, you have ${n.have}` }, 'shared'));
    }
    return chip;
  }

  async function setDone(r, done) {
    const prev = { status: r.status, source: r.source, manual: r.manual };
    r.status = (done === null ? r.auto_done : done) ? 'done' : 'open';
    r.source = done === null ? (r.auto_done ? 'auto' : 'none') : 'manual';
    r.manual = done === null ? null : { done: done ? 1 : 0 };
    renderQuestsTable();
    try {
      await API.post(`/api/skyquests/${encodeURIComponent(r.key)}/done` + App.q(), { done });
    } catch (e) {
      Object.assign(r, prev);
      error = e.message;
      renderQuestsTable();
      return;
    }
    await reload();   // totals, class bars and the rune allocation all move
  }

  function doneCell(r) {
    const cb = el('input', { type: 'checkbox', title: 'tick when you have handed this test in' });
    cb.checked = r.status === 'done';
    cb.addEventListener('change', () => setDone(r, cb.checked));
    const wrap = el('span', { class: 'sq-done-cell' }, cb);
    if (r.source === 'auto') {
      wrap.append(el('span', { class: 'sq-badge good', title: 'reward found in your inventory dump' }, 'auto'));
    } else if (r.source === 'manual') {
      wrap.append(el('span', { class: 'sq-badge info',
        title: r.auto_done && r.status === 'open' ? 'your tick overrides the dump (the reward IS in it)'
          : 'marked by hand' }, 'manual'));
      const undo = el('button', { class: 'metal-btn sq-undo', title: 'clear the manual mark — back to what the dump says' }, '↺');
      undo.addEventListener('click', () => setDone(r, null));
      wrap.append(undo);
    }
    return wrap;
  }

  function rowsFiltered() {
    const q = filter.q.toLowerCase();
    const mine = data.pinned_classes || [];
    return (data.quests || []).filter((r) => {
      if (filter.cls === 'mine' && !mine.includes(r.cls)) return false;
      if (filter.cls !== 'all' && filter.cls !== 'mine' && r.cls !== filter.cls) return false;
      if (filter.hideDone && r.status === 'done') return false;
      if (!q) return true;
      return r.name.toLowerCase().includes(q) || r.reward.name.toLowerCase().includes(q)
        || (r.giver || '').toLowerCase().includes(q)
        || r.needs.some((n) => n.display.toLowerCase().includes(q) || n.name.toLowerCase().includes(q));
    });
  }

  function buildQuests(body, api) {
    els.quests = body;
    if (api && api.addAction) Tiles.addExport(api, 'skyquests');
    renderQuests();
  }
  function renderQuests() {
    if (!els.quests || !els.quests.isConnected) return;
    const b = els.quests;
    if (pending(b)) return;
    b.replaceChildren();
    const sel = el('select', {});
    sel.append(el('option', { value: 'all' }, 'All classes'));
    const mine = data.pinned_classes || [];
    const mineOpt = el('option', { value: 'mine' }, 'My classes' + (mine.length ? ` (${mine.join(', ')})` : ''));
    if (!mine.length) {
      mineOpt.disabled = true;
      mineOpt.title = 'set class 1–3 on the Overview page';
    }
    sel.append(mineOpt);
    for (const c of data.classes || []) sel.append(el('option', { value: c.name }, (c.pinned ? '★ ' : '') + c.name));
    if (filter.cls === 'mine' && !mine.length) filter.cls = 'all';
    sel.value = filter.cls;
    sel.addEventListener('change', () => { filter.cls = sel.value; renderClasses(); renderQuestsTable(); });
    els.clsSelect = sel;
    const hide = el('input', { type: 'checkbox' });
    hide.checked = filter.hideDone;
    hide.addEventListener('change', () => { filter.hideDone = hide.checked; renderQuestsTable(); });
    const search = el('input', { type: 'search', placeholder: 'test, reward, item, NPC…', style: 'width:220px' });
    search.value = filter.q;
    search.addEventListener('input', () => { filter.q = search.value; renderQuestsTable(); });
    // The filter row is built once per tile build: re-rendering only the table
    // below it keeps the search box's focus and caret while you type.
    const table = el('div', {});
    els.questsTable = table;
    b.append(el('div', { class: 'sq-filters' }, sel,
      el('label', { class: 'sq-toggle' }, hide, 'hide completed'), search,
      el('span', { class: 'faint', style: 'font-size:11px', title: data.notes && data.notes.needs },
        'ticks come from the inventory dump; the ✔ column is yours')), table);
    renderQuestsTable();
  }
  function renderQuestsTable() {
    if (!els.questsTable || !els.questsTable.isConnected || !data) return;
    const columns = [
      {
        key: 'done', label: '✔', render: doneCell,
        sortVal: (r) => (r.status === 'done' ? 1 : 0) + (r.source === 'manual' ? 0.5 : 0),
      },
      {
        key: 'cls', label: 'Class',
        render: (r) => r.pinned ? el('span', { class: 'sq-pin', title: 'one of your classes' }, '★ ' + r.cls) : r.cls,
        sortVal: (r) => pinRank(r.cls) * 1000 + r.order,
      },
      {
        key: 'name', label: 'Test',
        render: (r) => el('span', { title: r.giver ? `hand in to ${r.giver}` : '' },
          el('a', { href: r.wiki_url, target: '_blank', rel: 'noopener' }, r.name),
          r.phrase ? el('span', { class: 'sq-say' }, ` say "${r.phrase}"`) : ''),
      },
      {
        key: 'reward', label: 'Reward',
        render: (r) => {
          const s = el('span', {}, iconCell(r.reward.icon), ' ',
            el('a', { href: r.reward.wiki_url, target: '_blank', rel: 'noopener' }, r.reward.name));
          if (r.reward.evidence) {
            const how = { base: 'in the dump', upgraded: 'in the dump as +N',
              exaltation: 'an Exaltation cut from it is in the dump', list: 'in the dump\'s keyring lists' };
            s.append(el('span', { class: 'sq-badge good', title: how[r.reward.evidence] || '' }, 'owned'));
          }
          return s;
        },
        sortVal: (r) => r.reward.name,
      },
      {
        key: 'rune', label: 'Wind Rune',
        render: (r) => el('span', {}, r.needs.filter((n) => n.kind === 'rune').map(needChip)),
        sortVal: (r) => (r.needs.some((n) => n.kind === 'rune' && n.ok) ? 1 : 0),
      },
      {
        key: 'items', label: 'Quest items',
        render: (r) => el('span', {}, r.needs.filter((n) => n.kind === 'item').map(needChip)),
        sortVal: (r) => -r.missing,
      },
      { key: 'missing', label: 'Missing', num: true, render: (r) => r.missing ? fmt(r.missing) : el('span', { class: 'good' }, '0') },
      {
        key: 'ready', label: 'Ready', num: true,
        render: (r) => r.covered ? el('span', { class: 'good', title: 'every need is in the dump and nothing else claims them' }, 'READY')
          : r.ready ? el('span', { class: 'warn', title: 'ready, but another open test is allocated the shared item first' }, 'shared')
            : r.status === 'done' ? el('span', { class: 'faint' }, 'done') : el('span', { class: 'faint' }, '—'),
        sortVal: (r) => (r.covered ? 2 : r.ready ? 1 : 0),
      },
    ];
    renderTable(els.questsTable, {
      id: 'sq.quests',
      columns,
      rows: rowsFiltered(),
      defaultSort: { key: 'cls', dir: 1 },
      empty: (data.quests || []).length ? 'Nothing matches the filter.'
        : 'No test list — run a Data Sync (the bundled list should have loaded; see the Overview tile).',
      onRow: (r, tr) => {
        if (r.status === 'done') tr.classList.add('sq-done');
        else if (r.covered) tr.classList.add('sq-ready');
      },
    });
  }

  // ── tile registry ───────────────────────────────────────────────────────
  const DEFS = [
    { id: 'overview', title: 'Completion',   span: 4,  height: 300, minSpan: 3, build: buildOverview },
    { id: 'classes',  title: 'By Class',     span: 8,  height: 300, minSpan: 5, build: buildClasses },
    { id: 'runes',    title: 'Wind Runes',   span: 12, height: 260, minSpan: 4, build: buildRunes },
    { id: 'quests',   title: 'Class Tests',  span: 12, height: 700, minSpan: 6, build: buildQuests },
  ];

  function renderAll() { renderOverview(); renderClasses(); renderRunes(); renderQuests(); }

  async function reload() {
    const cid = App.charId();
    if (loadedFor !== cid) { data = null; loadedFor = cid; }
    error = '';
    if (!data) renderAll();
    try {
      data = await API.get('/api/skyquests' + App.q());
      loadedFor = cid;
    } catch (e) {
      data = null;
      error = e.message;
    }
    renderAll();
    if (await loadSprites() > 0) renderAll();
  }

  Pages.register({
    id: 'skyquests',
    title: 'Sky Quests',
    icon: '☁',
    render(container) {
      if (!document.getElementById('skyquests-css')) {
        const st = document.createElement('style');
        st.id = 'skyquests-css';
        st.textContent = SQ_CSS;
        document.head.append(st);
      }
      container.append(el('h1', { class: 'page-title' }, 'Sky Quests'));
      const host = el('div', {});
      container.append(host);
      Tiles.mount(host, { storageKey: SKEY, defs: DEFS });
      reload();
    },
    onSnapshot(snap) {
      // a dump picked up by the exports watcher refreshes the ticks in place
      const r = snap && snap.readiness;
      if (!data || !r || !r.inventory_imported_at) return;
      const have = data.snapshot ? data.snapshot.imported_at : 0;
      const now = Date.now();
      if (r.inventory_imported_at > have + 0.5 && now - lastAutoReload > 10000) {
        lastAutoReload = now;
        reload();
      }
    },
  });
})();

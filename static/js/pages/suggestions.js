/* Quest Suggestions — the synced quest index, filterable, trackable, on the
   draggable / resizable tile grid (tiles.js).

   The filter row used to live in the page header; it is now the `filters` tile
   so it can be hidden/resized like anything else. The controls are built once
   per page render and re-appended by the tile build, so the search debounce and
   the lazily-populated class/race dropdowns survive a tile rebuild. */
'use strict';

(() => {
  const SKEY = 'eqa.layout.suggestions.v1';
  const F = { cls: '', race: '', level_min: '', level_max: '', q: '', hide_completed: false };
  const els = {};             // tile body elements, set by each build
  let ctl = null;             // persistent filter controls
  let data = null;            // GET /api/quests
  let err = null;
  let debounce = null;

  // ── filter controls (created once per page render, reused by the tile) ───
  function makeControls() {
    const clsSel = el('select', {}, el('option', { value: '' }, 'Any class'));
    const raceSel = el('select', {}, el('option', { value: '' }, 'Any race'));
    const lmin = el('input', { type: 'number', placeholder: 'min lvl', style: 'width:72px' });
    const lmax = el('input', { type: 'number', placeholder: 'max lvl', style: 'width:72px' });
    const search = el('input', { type: 'search', placeholder: 'Search quests...' });
    const hideCb = el('input', { type: 'checkbox' });
    const status = el('span', { class: 'muted' });

    lmin.value = F.level_min;               // keep the controls honest about F
    lmax.value = F.level_max;
    search.value = F.q;
    hideCb.checked = F.hide_completed;

    clsSel.addEventListener('change', () => { F.cls = clsSel.value; reload(); });
    raceSel.addEventListener('change', () => { F.race = raceSel.value; reload(); });
    lmin.addEventListener('change', () => { F.level_min = lmin.value; reload(); });
    lmax.addEventListener('change', () => { F.level_max = lmax.value; reload(); });
    search.addEventListener('input', () => {
      clearTimeout(debounce);
      debounce = setTimeout(() => { F.q = search.value; reload(); }, 250);
    });
    hideCb.addEventListener('change', () => { F.hide_completed = hideCb.checked; reload(); });

    const row = el('div', { class: 'row', style: 'align-items:center' },
      clsSel, raceSel, lmin, lmax, search,
      el('label', { style: 'display:flex;align-items:center;gap:5px' }, hideCb, 'hide completed'),
      el('span', { class: 'grow' }), status);
    return { clsSel, raceSel, status, row };
  }

  // ── tile: filters ───────────────────────────────────────────────────────
  function buildFilters(body) { els.filters = body; renderFilters(); }
  function renderFilters() {
    if (!els.filters || !els.filters.isConnected) return;
    els.filters.replaceChildren(ctl ? ctl.row : el('div', { class: 'faint' }, 'Loading…'));
  }

  // ── tile: quest index ───────────────────────────────────────────────────
  function buildIndex(body) { els.index = body; renderIndex(); }
  function renderIndex() {
    if (!els.index || !els.index.isConnected) return;
    const b = els.index;
    b.replaceChildren();
    if (err) { b.append(el('div', { class: 'empty-note bad' }, err)); return; }
    if (!data) { b.append(el('div', { class: 'empty-note' }, 'Loading…')); return; }
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'questidx',
      columns: [
        { key: 'name', label: 'Quest' },
        {
          key: 'classes', label: 'Classes',
          sortVal: (r) => (r.classes || []).join(','),
          render: (r) => (r.classes || []).join(', ') || null,
        },
        { key: 'start_zone', label: 'Zone' },
        {
          key: 'level_min', label: 'Level', num: true,
          render: (r) => r.level_min ? r.level_min + (r.level_max ? '-' + r.level_max : '+') : null,
        },
        { key: 'steps', label: 'Steps', num: true },
        {
          key: 'status', label: '',
          sortVal: (r) => r.status || '',
          render: (r) => {
            if (r.status === 'completed') return el('span', { class: 'good' }, 'done');
            if (r.status === 'tracked') return el('span', { class: 'warn' }, 'tracked');
            const b2 = el('button', { class: 'metal-btn', style: 'font-size:11px;padding:2px 8px' }, 'Track');
            b2.addEventListener('click', async (ev) => {
              ev.stopPropagation();
              b2.disabled = true;
              try { await API.post('/api/quests/' + r.id + '/status' + App.q(), { status: 'tracked' }); }
              catch (e) { b2.disabled = false; return; }
              reload();
            });
            return b2;
          },
        },
      ],
      rows: data.quests || [],
      defaultSort: { key: 'name', dir: 1 },
      empty: 'No quests in the local database yet - run a Data Sync first.',
      onRow: (r, tr) => {
        tr.style.cursor = 'pointer';
        tr.title = 'open on EQLWiki';
        tr.addEventListener('click', () => window.open(r.wiki_url, '_blank'));
      },
    });
  }

  // ── data ────────────────────────────────────────────────────────────────
  async function reload() {
    const params = {};
    for (const [k, v] of Object.entries(F)) if (v !== '' && v !== false) params[k] = v;
    try { data = await API.get('/api/quests' + App.q(params)); err = null; }
    catch (e) { data = null; err = e.message; }
    if (ctl) {
      ctl.status.textContent = data ? (data.quests || []).length + ' quests' : '';
      if (data && ctl.clsSel.options.length === 1) {   // lazy: first response only
        for (const c of data.classes || []) ctl.clsSel.append(el('option', { value: c }, c));
        for (const r of data.races || []) ctl.raceSel.append(el('option', { value: r }, r));
        if (F.cls) ctl.clsSel.value = F.cls;
        if (F.race) ctl.raceSel.value = F.race;
      }
    }
    renderIndex();
  }

  const DEFS = [
    { id: 'filters', title: 'Filters',     span: 12, height: 110, minSpan: 4, build: buildFilters },
    { id: 'index',   title: 'Quest Index', span: 12, height: 520, minSpan: 4, build: buildIndex },
  ];

  Pages.register({
    id: 'suggestions',
    title: 'Quest Ideas',
    icon: '🗺',
    render(container) {
      data = null; err = null;
      ctl = makeControls();
      container.append(el('h1', { class: 'page-title' }, 'Quest Suggestions'));
      const host = el('div', {});
      container.append(host);
      Tiles.mount(host, { storageKey: SKEY, defs: DEFS });
      reload();
    },
  });
})();

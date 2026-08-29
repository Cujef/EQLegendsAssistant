/* What to do? — quests your inventory unlocks + leveling suggestions, on the
   draggable / resizable tile grid (tiles.js).

   /api/whattodo is fetched once per page render into module scope; both tiles
   render from that cache, so closing/reopening/dragging a tile never refetches.
   reload() is the refetch, used after a Track. */
'use strict';

(() => {
  const SKEY = 'eqa.layout.whattodo.v1';
  const els = {};             // tile body elements, set by each build
  let data = null;            // GET /api/whattodo
  let err = null;

  // ── tile: quests your items unlock ──────────────────────────────────────
  function buildQuests(body) { els.quests = body; renderQuests(); }
  function renderQuests() {
    if (!els.quests || !els.quests.isConnected) return;
    const b = els.quests;
    b.replaceChildren();
    if (err) { b.append(el('div', { class: 'empty-note bad' }, err)); return; }
    if (!data) { b.append(el('div', { class: 'empty-note' }, 'Loading…')); return; }
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'wtd.quests',
      columns: [
        { key: 'name', label: 'Quest' },
        { key: 'matched_items', label: 'You have' },
        { key: 'start_zone', label: 'Zone' },
        {
          key: 'level_min', label: 'Level', num: true,
          render: (r) => r.level_min ? r.level_min + (r.level_max ? '-' + r.level_max : '+') : null,
        },
        {
          key: 'status', label: '',
          render: (r) => {
            if (r.status === 'completed') return el('span', { class: 'good' }, 'done');
            if (r.status === 'tracked') return el('span', { class: 'warn' }, 'tracked');
            const btn = el('button', { class: 'metal-btn', style: 'font-size:11px;padding:2px 8px' }, 'Track');
            btn.addEventListener('click', async (ev) => {
              ev.stopPropagation();
              btn.disabled = true;
              try { await API.post('/api/quests/' + r.id + '/status' + App.q(), { status: 'tracked' }); }
              catch (e) { btn.disabled = false; return; }
              r.status = 'tracked';      // keep the cache honest until reload lands
              btn.replaceWith(el('span', { class: 'warn' }, 'tracked'));
              reload();
            });
            return btn;
          },
        },
      ],
      rows: data.quest_matches || [],
      defaultSort: { key: 'name', dir: 1 },
      empty: 'No quest-item matches. Import inventory and run a Data Sync first.',
      onRow: (r, tr) => {
        tr.style.cursor = 'pointer';
        tr.addEventListener('click', () => window.open(r.wiki_url, '_blank'));
      },
    });
  }

  // ── tile: where to hunt ─────────────────────────────────────────────────
  function buildLeveling(body) { els.leveling = body; renderLeveling(); }
  function renderLeveling() {
    if (!els.leveling || !els.leveling.isConnected) return;
    const b = els.leveling;
    b.replaceChildren();
    if (err) { b.append(el('div', { class: 'empty-note bad' }, err)); return; }
    if (!data) { b.append(el('div', { class: 'empty-note' }, 'Loading…')); return; }
    const lv = data.leveling || {};
    if (lv.level) {
      b.append(el('div', { class: 'muted', style: 'margin-bottom:6px' }, 'Level ' + lv.level));
    }
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'wtd.zem',
      columns: [
        { key: 'zone', label: 'Zone' },
        {
          key: 'level_min', label: 'Levels', num: true,
          render: (r) => (r.level_min ?? '?') + '-' + (r.level_max ?? '?'),
        },
        { key: 'zem', label: 'ZEM', num: true },
      ],
      rows: lv.zem_rows || [],
      defaultSort: { key: 'zem', dir: -1 },
      empty: lv.level
        ? 'ZEM guide not synced yet - run a Data Sync.'
        : 'Import your log first so your level is known, then run a Data Sync.',
    });
  }

  // ── data ────────────────────────────────────────────────────────────────
  async function reload() {
    try { data = await API.get('/api/whattodo' + App.q()); err = null; }
    catch (e) { data = null; err = e.message; }
    renderQuests();
    renderLeveling();
  }

  const DEFS = [
    { id: 'quests',   title: 'Quests Your Items Unlock', span: 7, height: 480, minSpan: 3, build: buildQuests },
    { id: 'leveling', title: 'Where to Hunt',            span: 5, height: 480, minSpan: 3, build: buildLeveling },
  ];

  Pages.register({
    id: 'whattodo',
    title: 'What to do?',
    icon: '❓',
    render(container) {
      data = null; err = null;
      container.append(el('h1', { class: 'page-title' }, 'What to do?'));
      const host = el('div', {});
      container.append(host);
      Tiles.mount(host, { storageKey: SKEY, defs: DEFS });
      reload();
    },
  });
})();

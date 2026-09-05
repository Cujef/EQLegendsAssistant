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
  let zonesData = null;       // GET /api/zones
  let zonesErr = null;

  // ── tile: where you actually leveled (from the log) ────────────────────
  function buildLeveled(body, api) {
    els.leveled = body;
    if (api && api.addAction) Tiles.addExport(api, 'zones');
    renderLeveled();
  }
  function renderLeveled() {
    if (!els.leveled || !els.leveled.isConnected) return;
    const b = els.leveled;
    b.replaceChildren();
    if (zonesErr) { b.append(el('div', { class: 'empty-note bad' }, zonesErr)); return; }
    if (!zonesData) { b.append(el('div', { class: 'empty-note' }, 'Loading…')); return; }
    const t = zonesData.totals || {};
    if (t.zones) {
      b.append(el('div', { class: 'muted', style: 'font-size:12px;margin-bottom:6px' },
        `${t.zones} zones · ${fmt(t.hours)} active hours · ${fmt(t.kills)} kills · ${fmt(t.xp_pct)}% XP`
        + (zonesData.current_zone ? ` · now in ${zonesData.current_zone}` : '')));
    }
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'wtd.leveled',
      columns: [
        {
          key: 'zone', label: 'Zone',
          render: (r) => r.guide && r.guide.level_min
            ? el('span', { title: `guide levels ${r.guide.level_min}-${r.guide.level_max ?? '?'}` }, r.zone)
            : r.zone,
        },
        { key: 'hours', label: 'Active hrs', num: true, render: (r) => r.hours.toFixed(1) },
        { key: 'xp_pct', label: 'XP %', num: true, render: (r) => r.xp_pct ? r.xp_pct.toFixed(1) : el('span', { class: 'faint' }, '-') },
        {
          key: 'xp_per_hour', label: 'XP % / hr', num: true,
          render: (r) => r.xp_per_hour === null ? el('span', { class: 'faint', title: 'under 6 minutes of activity' }, '-') : r.xp_per_hour.toFixed(1),
        },
        { key: 'kills', label: 'Kills', num: true },
        {
          key: 'kills_per_hour', label: 'Kills / hr', num: true,
          render: (r) => r.kills_per_hour === null ? el('span', { class: 'faint' }, '-') : r.kills_per_hour.toFixed(1),
        },
        {
          key: 'guide', label: 'Guide', sortVal: (r) => (r.guide && (r.guide.rating || r.guide.zem)) || '',
          render: (r) => !r.guide ? el('span', { class: 'faint', title: 'no matching zone in the synced ZEM guide' }, '-')
            : r.guide.zem !== null && r.guide.zem !== undefined ? String(r.guide.zem)
            : r.guide.rating ? el('span', { title: 'rating for your level bracket, from the ZEM guide' }, r.guide.rating)
            : el('span', { class: 'faint' }, 'no rating'),
        },
        { key: 'last_ts', label: 'Last', num: true, render: (r) => dateCell(r.last_ts) },
      ],
      rows: zonesData.zones || [],
      defaultSort: { key: 'xp_per_hour', dir: -1 },
      empty: 'No zone lines in the log yet — every "You have entered" is recorded from now on '
        + '(and your existing log is read once for them).',
    });
    b.append(el('div', { class: 'faint', style: 'margin-top:6px;font-size:11px;line-height:1.5' },
      'Active time = gaps of at most 30 minutes between your own zone / kill / XP / loot lines. '
      + 'Guide ratings come from the synced ZEM guide for your level bracket (it publishes no numbers).'));
  }

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
    try { zonesData = await API.get('/api/zones' + App.q()); zonesErr = null; }
    catch (e) { zonesData = null; zonesErr = e.message; }
    renderLeveled();
  }

  const DEFS = [
    { id: 'quests',   title: 'Quests Your Items Unlock', span: 7, height: 480, minSpan: 3, build: buildQuests },
    { id: 'leveling', title: 'Where to Hunt',            span: 5, height: 480, minSpan: 3, build: buildLeveling },
    { id: 'leveled',  title: 'Where You Actually Leveled (From The Log)', span: 12, height: 420, minSpan: 4, build: buildLeveled },
  ];

  Pages.register({
    id: 'whattodo',
    title: 'What to do?',
    icon: '❓',
    render(container) {
      data = null; err = null; zonesData = null; zonesErr = null;
      container.append(el('h1', { class: 'page-title' }, 'What to do?'));
      const host = el('div', {});
      container.append(host);
      Tiles.mount(host, { storageKey: SKEY, defs: DEFS });
      reload();
    },
  });
})();

/* Parser page — M4: compact live combat tiles (drag/resize/lock via tiles.js).
   Data: the 1 Hz WS snapshot's `live` object + on-demand GET /api/fights.
   No polling loops: everything renders from 'snapshot' events and clicks.

   Fight ids come in two spaces: snapshot fights carry in-memory tracker ids,
   the DB rows carry their own. The history tile therefore keys on (start, name)
   to marry the two, and full meter detail is fetched from /api/fights/{id}
   (DB id) — completed fights are persisted by the pipeline the moment they end. */
'use strict';

(() => {
  const PP_CSS = `
.pp-kv { display:flex; gap:14px; flex-wrap:wrap; margin-bottom:6px; }
.pp-kv .k { font:600 9px var(--font-display); letter-spacing:0.1em;
  text-transform:uppercase; color:var(--text-faint); display:block; }
.pp-kv .v { font:600 13px var(--font-mono); color:var(--text); }
.pp-kv .v.accent { color:var(--accent); }
.pp-meter { margin-top:4px; }
.pp-mrow { display:grid; grid-template-columns:minmax(60px,110px) 1fr auto;
  gap:6px; align-items:center; padding:1px 0; font-size:11px; }
.pp-mname { white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.pp-mtrack { background:var(--bg-alt); border:1px solid var(--edge); height:11px; }
.pp-mfill { height:100%; background:linear-gradient(180deg, var(--accent-hi), var(--accent)); }
.pp-mrow:nth-child(2n) .pp-mfill { background:linear-gradient(180deg, var(--info), var(--bar-b)); }
.pp-mval { font-family:var(--font-mono); white-space:nowrap; color:var(--text-dim); }
.pp-tabs { display:flex; gap:2px; margin-bottom:6px; align-items:center; }
.pp-tab { padding:2px 9px; cursor:pointer; font:600 10px var(--font-display);
  letter-spacing:0.09em; text-transform:uppercase; color:var(--text-dim);
  border:1px solid var(--edge);
  background:linear-gradient(180deg, var(--panel-hi), var(--panel-lo)); }
.pp-tab.active { color:var(--accent); border-color:var(--accent); background:var(--sel-bg); }
.pp-selname { margin-left:auto; font:600 10px var(--font-mono); color:var(--text-faint);
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:45%; }
.pp-feed { font-size:11px; line-height:1.5; }
.pp-feed .t { color:var(--text-faint); font-family:var(--font-mono); margin-right:6px; }
.pp-feed .ico { display:inline-block; width:14px; text-align:center; margin-right:3px; }
.pp-live-dot { display:inline-block; width:8px; height:8px; background:var(--good);
  margin-right:6px; vertical-align:baseline; }
.pp-status-line { display:flex; align-items:center; gap:10px; font-size:12px; }
.pp-status-line .bar-track { flex:1; }
table.data.pp-compact { font-size:11px; }
table.data.pp-compact th, table.data.pp-compact td { padding:2px 6px; }
tr.pp-sel td { background:var(--sel-bg); }
`;

  const SKEY = 'eqa.parserLayout.v1';
  const els = {};                 // tile body elements, set by each build
  let sel = { mode: 'active', id: null, name: null, data: null };
  let tab = 'damage';
  let apiFights = [];             // GET /api/fights rows (DB ids)
  let fightSig = '';              // completed-fight signature -> refetch trigger
  const detailCache = {};         // db id -> full Fight.to_dict

  function live() { return (App.snapshot && App.snapshot.live) || {}; }

  // ── helpers ─────────────────────────────────────────────────────────────
  function fmtDur(s) {
    s = Math.max(0, Math.round(s || 0));
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }
  function fmtTime(ts) {
    if (!ts) return '—';
    const d = new Date(ts * 1000);
    return [d.getHours(), d.getMinutes(), d.getSeconds()]
      .map((n) => String(n).padStart(2, '0')).join(':');
  }
  function fmtMB(n) { return (n / 1048576).toFixed(1) + ' MB'; }
  function kv(label, value, accent) {
    return el('div', {}, el('span', { class: 'k' }, label),
      el('span', { class: 'v' + (accent ? ' accent' : '') }, value));
  }
  function meterRows(dict, perKey) {
    const rows = Object.entries(dict || {})
      .map(([name, d]) => ({ name, total: d.total || 0, per: d[perKey] || 0, pct: d.pct || 0 }))
      .sort((a, b) => b.total - a.total);
    const max = rows.length ? rows[0].total : 1;
    const box = el('div', { class: 'pp-meter' });
    for (const r of rows) {
      box.append(el('div', { class: 'pp-mrow' },
        el('span', { class: 'pp-mname', title: r.name }, r.name),
        el('div', { class: 'pp-mtrack' },
          el('div', { class: 'pp-mfill', style: `width:${Math.max(2, 100 * r.total / max)}%` })),
        el('span', { class: 'pp-mval' }, `${fmt(r.total)} (${r.per}/s)`)));
    }
    if (!rows.length) box.append(el('div', { class: 'faint' }, 'nothing yet'));
    return box;
  }

  // ── tile: live fight ────────────────────────────────────────────────────
  function buildFight(body) { els.fight = body; renderFight(); }
  function renderFight() {
    if (!els.fight || !els.fight.isConnected) return;
    const l = live();
    const f = l.active_fight || (l.fights && l.fights[0]) || null;
    const b = els.fight;
    b.replaceChildren();
    if (!f) { b.append(el('div', { class: 'empty-note' }, 'No combat seen yet.')); return; }
    const you = (f.damage && f.damage.player) || {};
    b.append(
      el('div', { class: 'pp-kv' },
        kv(f.is_active ? 'Fighting' : 'Last fight', f.name, true),
        kv('Dur', fmtDur(f.duration)),
        kv('Your DPS', String(you.dps ?? 0)),
        kv('Dmg', fmt(f.total_damage)),
        kv('Taken', fmt(f.total_tanking))),
      meterRows(f.damage, 'dps'));
  }

  // ── tile: meters (damage / healing / tanking of the selected fight) ─────
  function selData() {
    const l = live();
    if (sel.mode === 'db') return sel.data;                       // fetched detail
    if (sel.mode === 'active') return l.active_fight || (l.fights && l.fights[0]) || null;
    return null;
  }
  function buildMeters(body) { els.meters = body; renderMeters(); }
  function renderMeters() {
    if (!els.meters || !els.meters.isConnected) return;
    const b = els.meters;
    const f = selData();
    b.replaceChildren();
    const tabs = el('div', { class: 'pp-tabs' });
    for (const t of ['damage', 'healing', 'tanking']) {
      const btn = el('span', { class: 'pp-tab' + (tab === t ? ' active' : '') }, t);
      btn.addEventListener('click', () => { tab = t; renderMeters(); });
      tabs.append(btn);
    }
    if (sel.mode === 'db') {
      const back = el('span', { class: 'pp-tab', title: 'Back to the live fight' }, '▶ live');
      back.addEventListener('click', () => { sel = { mode: 'active' }; renderMeters(); renderHistory(); });
      tabs.append(back);
    }
    tabs.append(el('span', { class: 'pp-selname' },
      f ? `${f.name} · ${fmtDur(f.duration)}` : ''));
    b.append(tabs);
    if (!f) { b.append(el('div', { class: 'empty-note' }, 'No fight selected.')); return; }
    const perKey = tab === 'damage' ? 'dps' : tab === 'healing' ? 'hps' : 'dtps';
    const host = el('div', {});
    b.append(host);
    const rows = Object.entries(f[tab] || {}).map(([name, d]) => ({
      name, total: d.total || 0, per: d[perKey] || 0, pct: d.pct || 0,
    }));
    renderTable(host, {
      id: 'pp-meters-' + tab,
      columns: [
        { key: 'name', label: 'Actor' },
        { key: 'total', label: 'Total', num: true, render: (r) => fmt(r.total) },
        { key: 'per', label: '/s', num: true },
        { key: 'pct', label: '%', num: true },
      ],
      rows,
      defaultSort: { key: 'total', dir: -1 },
      empty: 'Nothing in this meter.',
    });
    host.querySelector('table')?.classList.add('pp-compact');
  }

  // ── tile: fight history ─────────────────────────────────────────────────
  function buildHistory(body, api) {
    els.history = body;
    if (api && api.addAction) Tiles.addExport(api, 'fights');
    renderHistory();
  }
  function historyRows() {
    const l = live();
    const snaps = l.fights || [];
    const lootOf = {};            // "start|name" -> loot count (snapshot-only info)
    for (const f of snaps) lootOf[`${Math.round(f.start)}|${f.name}`] = (f.loot || []).length;
    const seen = new Set();
    const rows = [];
    for (const r of apiFights) {
      const key = `${Math.round(r.start)}|${r.name}`;
      seen.add(key);
      rows.push({ id: r.id, name: r.name, start: r.start, duration: r.duration,
                  dps: r.dps, dmg: r.total_damage, lootn: lootOf[key] ?? null });
    }
    for (const f of snaps) {      // completed but not yet fetched from the DB
      const key = `${Math.round(f.start)}|${f.name}`;
      if (seen.has(key)) continue;
      rows.push({ id: null, name: f.name, start: f.start, duration: f.duration,
                  dps: f.dps, dmg: f.total_damage, lootn: (f.loot || []).length });
    }
    rows.sort((a, b) => b.start - a.start);
    return rows.slice(0, 50);
  }
  function renderHistory() {
    if (!els.history || !els.history.isConnected) return;
    const host = els.history;
    host.replaceChildren();
    const inner = el('div', {});
    host.append(inner);
    renderTable(inner, {
      id: 'pp-history',
      columns: [
        { key: 'name', label: 'Fight' },
        { key: 'start', label: 'When', num: true, render: (r) => fmtTime(r.start) },
        { key: 'duration', label: 'Dur', num: true, render: (r) => fmtDur(r.duration) },
        { key: 'dps', label: 'DPS', num: true },
        { key: 'dmg', label: 'Dmg', num: true, render: (r) => fmt(r.dmg) },
        { key: 'lootn', label: 'Loot', num: true, render: (r) => r.lootn ?? '—' },
      ],
      rows: historyRows(),
      defaultSort: { key: 'start', dir: -1 },
      empty: 'No completed fights yet.',
      onRow(r, tr) {
        tr.style.cursor = 'pointer';
        if (sel.mode === 'db' && sel.id === r.id) tr.classList.add('pp-sel');
        tr.addEventListener('click', () => selectFight(r));
      },
    });
    inner.querySelector('table')?.classList.add('pp-compact');
  }
  async function selectFight(row) {
    if (!row.id) return;                       // not persisted yet; next snapshot will have it
    sel = { mode: 'db', id: row.id, name: row.name, data: detailCache[row.id] || null };
    renderHistory();
    renderMeters();
    if (!sel.data) {
      try {
        const d = await API.get('/api/fights/' + row.id);
        detailCache[row.id] = d;
        if (sel.mode === 'db' && sel.id === row.id) { sel.data = d; renderMeters(); }
      } catch (e) { /* row vanished or server hiccup; leave the empty state */ }
    }
  }
  async function fetchFights() {
    if (!App.active) return;
    try {
      const r = await API.get('/api/fights' + App.q({ limit: 50 }));
      apiFights = r.fights || [];
      renderHistory();
    } catch (e) { /* offline / no char: history stays as-is */ }
  }

  // ── tile: feed ──────────────────────────────────────────────────────────
  function buildFeed(body) { els.feed = body; renderFeed(); }
  function renderFeed() {
    if (!els.feed || !els.feed.isConnected) return;
    const s = live().session || {};
    const items = [];
    for (const x of s.skill_ups || []) items.push({ ts: x.ts, ico: '⚒', text: `${x.skill} → ${x.level}` });
    for (const x of s.aa || []) {
      items.push(x.kind === 'gain'
        ? { ts: x.ts, ico: '★', text: `AA point gained (${x.balance_after} banked)` }
        : { ts: x.ts, ico: '★', text: `AA: ${x.ability} (−${x.points})` });
    }
    for (const x of s.deaths_recent || []) items.push({ ts: x.ts, ico: '☠', text: `Died to ${x.killer}`, cls: 'bad' });
    for (const x of s.loot || []) items.push({ ts: x.ts, ico: '◆', text: x.item + (x.source ? ` (${x.source})` : '') });
    for (const x of s.levels || []) items.push({ ts: x.ts, ico: '▲', text: `Level ${x.level}!`, cls: 'good' });
    for (const x of s.crafts || []) {
      items.push(x.ok
        ? { ts: x.ts, ico: '⚗', text: `Made ${x.item}` + (x.capped ? ' · CAP (no longer trains)' : '') }
        : { ts: x.ts, ico: '✗', text: `Failed to make ${x.item}`, cls: 'bad' });
    }
    for (const x of s.craft_errors || []) {
      const why = { missing_materials: 'missing materials', unusable_result: 'unusable result',
                    wrong_container: 'wrong container' }[x.reason] || x.reason;
      items.push({ ts: x.ts, ico: '✗', text: `Combine refused: ${why}`, cls: 'warn' });
    }
    for (const x of s.upgrades || []) items.push({ ts: x.ts, ico: '▲', text: `Merged into ${x.item}`, cls: 'good' });
    for (const x of s.zones || []) items.push({ ts: x.ts, ico: '⇢', text: `Entered ${x.zone}` });
    for (const x of s.faction || []) {
      items.push(x.capped
        ? { ts: x.ts, ico: '⚖', text: `${x.faction}: already at ${x.capped === 'better' ? 'MAX' : 'MIN'}` }
        : { ts: x.ts, ico: '⚖', text: `${x.faction} ${x.delta > 0 ? '+' : ''}${x.delta}`,
            cls: x.delta < 0 ? 'bad' : '' });
    }
    items.sort((a, b) => b.ts - a.ts);
    const b = els.feed;
    b.replaceChildren();
    if (!items.length) { b.append(el('div', { class: 'empty-note' }, 'Nothing notable yet.')); return; }
    const box = el('div', { class: 'pp-feed' });
    for (const it of items.slice(0, 30)) {
      box.append(el('div', { class: it.cls || '' },
        el('span', { class: 't' }, fmtTime(it.ts)),
        el('span', { class: 'ico' }, it.ico), it.text));
    }
    b.append(box);
  }

  // ── tile: log status ────────────────────────────────────────────────────
  function buildStatus(body) { els.status = body; renderStatus(); }
  function renderStatus() {
    if (!els.status || !els.status.isConnected) return;
    const b = els.status;
    const t = live().tail || { status: 'off' };
    b.replaceChildren();
    if (t.status === 'import') {
      const pct = t.size ? Math.min(100, 100 * t.offset / t.size) : 0;
      b.append(el('div', { class: 'pp-status-line' },
        el('span', { class: 'warn' }, 'IMPORTING'),
        el('div', { class: 'bar-track' },
          el('div', { class: 'bar-fill', style: `width:${pct}%` }),
          el('div', { class: 'bar-label' }, pct.toFixed(1) + '%')),
        el('span', { class: 'num muted' }, `${fmtMB(t.offset || 0)} / ${fmtMB(t.size || 0)}`)));
    } else if (t.status === 'backfill') {
      const pct = t.size ? Math.min(100, 100 * t.offset / t.size) : 0;
      b.append(el('div', { class: 'pp-status-line' },
        el('span', { class: 'warn', title: 'reading your existing log once for newly tracked events' }, 'BACKFILL'),
        el('div', { class: 'bar-track' },
          el('div', { class: 'bar-fill', style: `width:${pct}%` }),
          el('div', { class: 'bar-label' }, pct.toFixed(1) + '%')),
        el('span', { class: 'num muted' }, `${fmtMB(t.offset || 0)} / ${fmtMB(t.size || 0)}`)));
    } else if (t.status === 'live') {
      const age = t.line_ts ? Math.max(0, Date.now() / 1000 - t.line_ts) : null;
      const zone = (live().session || {}).zone;
      b.append(el('div', { class: 'pp-status-line' },
        el('span', {}, el('span', { class: 'pp-live-dot' }), 'LIVE'),
        el('span', { class: 'muted' },
          age === null ? 'no lines yet'
            : age < 90 ? `last line ${Math.round(age)}s ago`
            : `last line ${fmtTime(t.line_ts)}`),
        zone ? el('span', { class: 'muted' }, '⇢ ' + zone) : null,
        el('span', { class: 'num faint' }, fmtMB(t.offset || 0) + ' read')));
    } else {
      b.append(el('div', { class: 'pp-status-line faint' },
        'Not tailing — no character log found.'));
    }
  }

  // ── page registration ───────────────────────────────────────────────────
  const DEFS = [
    { id: 'fight',   title: 'Live Fight',    span: 4,  height: 260, minSpan: 2, build: buildFight },
    { id: 'meters',  title: 'Meters',        span: 8,  height: 260, minSpan: 3, build: buildMeters },
    { id: 'history', title: 'Fight History', span: 6,  height: 300, minSpan: 3, build: buildHistory },
    { id: 'feed',    title: 'Feed',          span: 6,  height: 300, minSpan: 2, build: buildFeed },
    { id: 'status',  title: 'Log Status',    span: 12, height: 84,  minSpan: 3, build: buildStatus },
  ];

  function renderAll() {
    renderFight();
    if (sel.mode === 'active') renderMeters();   // a pinned fight doesn't churn at 1 Hz
    renderFeed();
    renderStatus();
    const l = live();
    const f = l.fights || [];
    const sig = f.length + '|' + (f[0] ? f[0].start : '');
    if (sig !== fightSig) { fightSig = sig; fetchFights(); }
    else renderHistory();
  }

  Pages.register({
    id: 'parser',
    title: 'Parser',
    icon: '📊',
    render(container) {
      if (!document.getElementById('parserpage-css')) {
        const st = document.createElement('style');
        st.id = 'parserpage-css';
        st.textContent = PP_CSS;
        document.head.append(st);
      }
      container.append(el('h1', { class: 'page-title' }, 'Parser'));
      const host = el('div', {});
      container.append(host);
      Tiles.mount(host, { storageKey: SKEY, defs: DEFS });
      fetchFights();
      renderAll();
    },
    onSnapshot() { renderAll(); },
  });
})();

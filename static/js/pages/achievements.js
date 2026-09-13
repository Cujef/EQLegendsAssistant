/* Achievements: what your log says you earned ("You have completed
   achievement: X"), joined to what the wiki says each one takes.

   Server facts this page leans on (app/achievements.py): `unlocks` holds the
   race / class / deity lists with an earned date or a requirement tally;
   `achievements` is every wiki-defined achievement plus the log-only ones
   (Traveler, Hunter, faction, events) the wiki does not list; requirement
   `done` is true / false / null (null = the app has no data for it). Race,
   class and deity unlocks auto-complete for what you chose at creation and
   can be bought with tokens, so an unlock is the game's verdict, not proof of
   the work — the page says so. */
'use strict';

(() => {
  const AC_CSS = `
.ac-badge { display:inline-block; margin-left:6px; padding:0 5px; vertical-align:1px;
  font:700 9px var(--font-display); letter-spacing:0.1em; text-transform:uppercase;
  border:1px solid var(--edge-strong); color:var(--text-dim); white-space:nowrap; }
.ac-badge.good { color:var(--good); border-color:var(--good); }
.ac-badge.info { color:var(--info); border-color:var(--info); }
.ac-unlocks { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:0 16px; }
.ac-col h4 { margin:0 0 4px; font:700 11px var(--font-display); letter-spacing:0.09em;
  text-transform:uppercase; color:var(--text-dim); border-bottom:1px solid var(--edge); padding-bottom:3px; }
.ac-u { display:grid; grid-template-columns:minmax(0,1fr) 62px; align-items:center; gap:6px;
  padding:1px 3px; font-size:12px; cursor:default; white-space:nowrap; }
.ac-u.earned { color:var(--good); }
.ac-u.ready { color:var(--warn); }
.ac-u .num { font-size:11px; }
.ac-req { display:block; font-size:11px; line-height:1.35; }
.ac-req.yes { color:var(--good); }
.ac-req.no { color:var(--text-dim); }
.ac-req.unk { color:var(--text-faint); }
.ac-filters { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:8px; }
.ac-toggle { display:flex; align-items:center; gap:6px; font-size:12px; color:var(--text-dim);
  cursor:pointer; user-select:none; }
tr.ac-earned td { color:var(--text-faint); }
tr.ac-earned td .ac-req { color:var(--text-faint); }
.ac-cats { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:1px 16px; }
.ac-cat { display:grid; grid-template-columns:110px minmax(0,1fr) 56px; align-items:center; gap:8px;
  font-size:12px; padding:1px 3px; cursor:pointer; }
.ac-cat:hover { background:var(--table-hover); }
.ac-cat.sel { outline:1px solid var(--accent); }
.ac-cat .bar-track { height:11px; }
.ac-cat .bar-label { line-height:11px; font-size:9px; }
.ac-note { color:var(--text-faint); font-size:11px; line-height:1.5; margin-top:8px; }
`;
  const SKEY = 'eqa.layout.achievements.v1';
  const els = {};
  let data = null;
  let loadedFor = null;
  let error = '';
  let filter = { cat: 'all', earned: 'all', q: '' };

  function pending(box) {
    if (data) return false;
    box.replaceChildren(el('div', { class: 'empty-note' + (error ? ' bad' : '') },
      error || 'Loading…'));
    return true;
  }
  function bar(pct, label) {
    return el('div', { class: 'bar-track' },
      el('div', { class: 'bar-fill', style: `width:${Math.max(0, Math.min(100, pct || 0))}%` }),
      el('div', { class: 'bar-label' }, label));
  }
  function reqLine(r) {
    const cls = r.done === true ? 'yes' : r.done === false ? 'no' : 'unk';
    const mark = r.done === true ? '✔ ' : r.done === false ? '✘ ' : '· ';
    const title = r.done === null ? 'the app has no data for this requirement'
      : r.source === 'export' ? 'per your achievements export' : 'derived by the app';
    return el('span', { class: 'ac-req ' + cls, title }, mark + r.text,
      r.progress_text ? el('span', { class: 'faint' }, ` ${r.progress_text}`) : '');
  }
  function unlockTitle(u) {
    const bits = u.reqs.map((r) => (r.done === true ? '✔ ' : r.done === false ? '✘ ' : '· ') + r.text);
    if (u.earned) bits.unshift('earned ' + timeCell(u.earned_at));
    return bits.concat(u.notes || []).join('\n');
  }

  // ── tile: summary ───────────────────────────────────────────────────────
  function buildSummary(body) { els.summary = body; renderSummary(); }
  function renderSummary() {
    if (!els.summary || !els.summary.isConnected) return;
    const b = els.summary;
    if (pending(b)) return;
    const t = data.totals;
    const src = data.source || {};
    const pair = (p) => `${p[0]} / ${p[1]}`;
    b.replaceChildren(el('div', {},
      el('div', { style: 'margin:4px 0 10px' },
        bar(t.in_wiki ? 100 * t.wiki_earned / t.in_wiki : 0,
          `${fmt(t.wiki_earned)} / ${fmt(t.in_wiki)} listed achievements · ${fmt(t.points_earned)} / ${fmt(t.points)} points`)),
      statRow(data.export ? 'Earned (log + export)' : 'Earned (from the log)', fmt(t.earned), 'good'),
      statRow('Races unlocked', pair(t.races), t.races[0] ? 'good' : ''),
      statRow('Classes unlocked', pair(t.classes), t.classes[0] ? 'good' : ''),
      statRow('Deities unlocked', pair(t.deities), t.deities[0] ? 'good' : ''),
      statRow('Listed', fmt(t.listed)),
      statRow('Log begins', data.has_log ? dateCell(data.log_first_ts)
        : el('span', { class: 'warn' }, 'no log — nothing can be earned yet')),
      statRow('Achievements export', data.export
        ? el('span', { title: data.export.path || '' }, `${dateCell(data.export.imported_at)} · ${fmt(data.export.complete)} of ${fmt(data.export.count)} complete`)
        : el('span', { class: 'warn', title: 'in game: /outputfile achievements — the folder watcher imports it' }, 'none — type /outputfile achievements')),
      t.export_only_earned ? statRow('Earned before the log', fmt(t.export_only_earned), 'good') : null,
      statRow('Definitions', src.kind === 'wiki' ? 'wiki, synced ' + (dateCell(src.fetched_at) || '—')
        : src.kind === 'bundled' ? 'bundled snapshot' : el('span', { class: 'bad' }, 'none')),
      src.warning ? el('div', { class: 'bad', style: 'margin-top:8px;font-size:12px' }, src.warning) : null,
      el('div', { class: 'ac-note' }, data.notes.source),
      el('div', { class: 'ac-note' }, data.notes.unlock)));
  }

  // ── tile: unlocks ───────────────────────────────────────────────────────
  function buildUnlocks(body) { els.unlocks = body; renderUnlocks(); }
  function renderUnlocks() {
    if (!els.unlocks || !els.unlocks.isConnected) return;
    const b = els.unlocks;
    if (pending(b)) return;
    const col = (title, list) => {
      const c = el('div', { class: 'ac-col' }, el('h4', {}, title));
      for (const u of list) {
        const p = u.progress;
        const ready = !u.earned && p.known > 0 && p.done === p.known && p.known === p.total;
        const row = el('div', { class: 'ac-u' + (u.earned ? ' earned' : ready ? ' ready' : ''),
          title: unlockTitle(u) },
        el('span', {}, (u.earned ? '✔ ' : ready ? '◆ ' : '') + u.name),
        el('span', { class: 'num' }, u.earned ? (u.earned_at ? dateCell(u.earned_at) : 'export')
          : p.known ? `${p.done}/${p.known}` + (p.known < p.total ? '?' : '')
            : el('span', { class: 'faint' }, '—')));
        c.append(row);
      }
      return c;
    };
    const u = data.unlocks;
    b.replaceChildren(
      el('div', { class: 'ac-unlocks' },
        col(`Races ${data.totals.races[0]}/${data.totals.races[1]}`, u.race),
        col(`Classes ${data.totals.classes[0]}/${data.totals.classes[1]}`, u.class),
        col(`Deities ${data.totals.deities[0]}/${data.totals.deities[1]}`, u.deity)),
      el('div', { class: 'ac-note' },
        '✔ earned per the log · ◆ every known requirement met but no achievement line yet · '
        + 'n/m = requirements the app can check (? = some it cannot). Hover for the list. '
        + data.notes.progress));
  }

  // ── tile: categories ────────────────────────────────────────────────────
  function buildCats(body) { els.cats = body; renderCats(); }
  function renderCats() {
    if (!els.cats || !els.cats.isConnected) return;
    const b = els.cats;
    if (pending(b)) return;
    const grid = el('div', { class: 'ac-cats' });
    for (const c of data.categories) {
      const row = el('div', { class: 'ac-cat' + (filter.cat === c.name ? ' sel' : ''),
        title: `${c.group} · ${c.points_earned}/${c.points} points — click to filter the table` },
      el('span', { style: 'white-space:nowrap;overflow:hidden;text-overflow:ellipsis' }, c.name),
      bar(c.total ? 100 * c.earned / c.total : 0, `${c.total ? Math.round(100 * c.earned / c.total) : 0}%`),
      el('span', { class: 'num' }, `${c.earned}/${c.total}`));
      row.addEventListener('click', () => {
        filter.cat = filter.cat === c.name ? 'all' : c.name;
        if (els.catSelect) els.catSelect.value = filter.cat;
        renderCats();
        renderTableOnly();
      });
      grid.append(row);
    }
    b.replaceChildren(grid);
  }

  // ── tile: recent ────────────────────────────────────────────────────────
  function buildRecent(body) { els.recent = body; renderRecent(); }
  function renderRecent() {
    if (!els.recent || !els.recent.isConnected) return;
    const b = els.recent;
    if (pending(b)) return;
    const host = el('div', {});
    b.replaceChildren(host);
    renderTable(host, {
      id: 'ac.recent',
      columns: [
        { key: 'ts', label: 'When', num: true, render: (r) => r.ts ? timeCell(r.ts) : el('span', { class: 'faint' }, 'export') },
        { key: 'name', label: 'Achievement' },
        { key: 'sub', label: 'Category' },
        { key: 'points', label: 'Pts', num: true, render: (r) => r.points ? fmt(r.points) : null },
      ],
      rows: data.recent || [],
      defaultSort: { key: 'ts', dir: -1 },
      empty: data.has_log ? 'No achievement lines in the log yet.' : 'Set a log path first (Setup).',
    });
  }

  // ── tile: all achievements ──────────────────────────────────────────────
  function rowsFiltered() {
    const q = filter.q.toLowerCase();
    return (data.achievements || []).filter((r) => {
      if (filter.cat !== 'all' && r.sub !== filter.cat) return false;
      if (filter.earned === 'earned' && !r.earned) return false;
      if (filter.earned === 'open' && r.earned) return false;
      if (!q) return true;
      return r.name.toLowerCase().includes(q) || r.sub.toLowerCase().includes(q)
        || r.reqs.some((x) => x.text.toLowerCase().includes(q));
    });
  }
  function buildAll(body, api) {
    els.all = body;
    if (api && api.addAction) Tiles.addExport(api, 'achievements');
    renderAll_();
  }
  function renderAll_() {
    if (!els.all || !els.all.isConnected) return;
    const b = els.all;
    if (pending(b)) return;
    b.replaceChildren();
    const sel = el('select', {});
    sel.append(el('option', { value: 'all' }, 'All categories'));
    for (const c of data.categories) sel.append(el('option', { value: c.name }, `${c.name} (${c.earned}/${c.total})`));
    sel.value = filter.cat;
    sel.addEventListener('change', () => { filter.cat = sel.value; renderCats(); renderTableOnly(); });
    els.catSelect = sel;
    const st = el('select', {});
    for (const [v, l] of [['all', 'Earned + open'], ['open', 'Open only'], ['earned', 'Earned only']]) {
      st.append(el('option', { value: v }, l));
    }
    st.value = filter.earned;
    st.addEventListener('change', () => { filter.earned = st.value; renderTableOnly(); });
    const search = el('input', { type: 'search', placeholder: 'achievement, category, requirement…', style: 'width:240px' });
    search.value = filter.q;
    search.addEventListener('input', () => { filter.q = search.value; renderTableOnly(); });
    // filter row built once; only the table below re-renders (keeps the caret)
    const table = el('div', {});
    els.allTable = table;
    b.append(el('div', { class: 'ac-filters' }, sel, st, search), table);
    renderTableOnly();
  }
  function renderTableOnly() {
    if (!els.allTable || !els.allTable.isConnected || !data) return;
    renderTable(els.allTable, {
      id: 'ac.all',
      columns: [
        {
          key: 'earned', label: '✔',
          render: (r) => r.earned ? el('span', { class: 'good', title: 'earned ' + timeCell(r.earned_at) }, '✔')
            : el('span', { class: 'faint' }, '—'),
          sortVal: (r) => (r.earned ? 1 : 0),
        },
        {
          key: 'name', label: 'Achievement',
          render: (r) => el('span', {}, r.name,
            r.in_wiki ? '' : el('span', { class: 'ac-badge', title: r.in_export
              ? 'from your achievements export; the wiki has no entry for it'
              : 'in your log; neither the wiki nor the export lists it' }, r.in_export ? 'game' : 'log only')),
        },
        { key: 'sub', label: 'Category', sortVal: (r) => r.group + ' ' + r.sub },
        { key: 'points', label: 'Pts', num: true, render: (r) => r.points ? fmt(r.points) : null },
        {
          key: 'progress', label: 'Requirements',
          render: (r) => r.reqs.length ? el('span', {}, r.reqs.map(reqLine))
            : el('span', { class: 'faint' }, r.desc || '—'),
          sortVal: (r) => (r.progress.known ? r.progress.done / r.progress.known : -1),
        },
        {
          key: 'earned_at', label: 'Earned', num: true,
          render: (r) => r.earned ? (r.earned_at ? dateCell(r.earned_at)
            : el('span', { class: 'faint', title: 'complete in your achievements export; no date (before the log began, or auto-completed)' }, 'export')) : null,
          sortVal: (r) => (r.earned ? (r.earned_at || 1) : 0),
        },
      ],
      rows: rowsFiltered(),
      defaultSort: { key: 'sub', dir: 1 },
      empty: 'Nothing matches the filter.',
      onRow: (r, tr) => { if (r.earned) tr.classList.add('ac-earned'); },
    });
  }

  const DEFS = [
    { id: 'summary', title: 'Summary',            span: 4,  height: 330, minSpan: 3, build: buildSummary },
    { id: 'unlocks', title: 'Unlocks',            span: 8,  height: 330, minSpan: 5, build: buildUnlocks },
    { id: 'cats',    title: 'By Category',        span: 6,  height: 300, minSpan: 4, build: buildCats },
    { id: 'recent',  title: 'Recently Earned',    span: 6,  height: 300, minSpan: 4, build: buildRecent },
    { id: 'all',     title: 'All Achievements',   span: 12, height: 640, minSpan: 6, build: buildAll },
  ];

  function renderAll() { renderSummary(); renderUnlocks(); renderCats(); renderRecent(); renderAll_(); }

  async function reload() {
    const cid = App.charId();
    if (loadedFor !== cid) { data = null; loadedFor = cid; }
    error = '';
    if (!data) renderAll();
    try {
      data = await API.get('/api/achievements' + App.q());
      loadedFor = cid;
    } catch (e) {
      data = null;
      error = e.message;
    }
    renderAll();
  }

  Pages.register({
    id: 'achievements',
    title: 'Achievements',
    icon: '🏆',
    render(container) {
      if (!document.getElementById('achievements-css')) {
        const st = document.createElement('style');
        st.id = 'achievements-css';
        st.textContent = AC_CSS;
        document.head.append(st);
      }
      container.append(el('h1', { class: 'page-title' }, 'Achievements'));
      const host = el('div', {});
      container.append(host);
      Tiles.mount(host, { storageKey: SKEY, defs: DEFS, defaultLocked: false });
      reload();
    },
  });
})();

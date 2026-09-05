/* Factions: standing changes from the log (parser v1.6.0 faction events).

   The log only ever reports CHANGES and the two pinned states, never an absolute
   standing — so "Net" is the movement since logging began, and MAX / MIN say
   the game's last word on that faction was "could not possibly get any better /
   worse". Tile grid, same conventions as the other pages. */
'use strict';

(() => {
  const FX_CSS = `
.fx-badge { display:inline-block; margin-left:6px; padding:0 5px; vertical-align:1px;
  font:700 9px var(--font-display); letter-spacing:0.1em; text-transform:uppercase;
  border:1px solid var(--edge-strong); color:var(--text-dim); }
.fx-badge.good { color:var(--good); border-color:var(--good); }
.fx-badge.bad { color:var(--bad); border-color:var(--bad); }
.fx-toggle { display:flex; align-items:center; gap:6px; font-size:12px; color:var(--text-dim);
  margin-bottom:8px; cursor:pointer; user-select:none; }
`;
  const SKEY = 'eqa.layout.factions.v1';
  const els = {};
  let data = null;
  let loadedFor = null;
  let error = '';
  let movedOnly = true;

  function pending(box) {
    if (data) return false;
    box.replaceChildren(el('div', { class: 'empty-note' + (error ? ' bad' : '') },
      error || 'Loading…'));
    return true;
  }
  function signed(n) {
    if (n === null || n === undefined) return null;
    const cls = n > 0 ? 'good' : n < 0 ? 'bad' : 'faint';
    return el('span', { class: cls }, (n > 0 ? '+' : '') + fmt(n));
  }
  function nameCell(r) {
    const span = el('span', {}, r.faction);
    if (r.capped === 'better') span.append(el('span', { class: 'fx-badge good', title: 'already as high as it goes' }, 'MAX'));
    if (r.capped === 'worse') span.append(el('span', { class: 'fx-badge bad', title: 'already as low as it goes' }, 'MIN'));
    return span;
  }

  // ── tile: standing changes ──────────────────────────────────────────────
  function buildStanding(body, api) {
    els.standing = body;
    if (api && api.addAction) Tiles.addExport(api, 'factions');
    renderStanding();
  }
  function renderStanding() {
    if (!els.standing || !els.standing.isConnected) return;
    const b = els.standing;
    if (pending(b)) return;
    b.replaceChildren();
    const cb = el('input', { type: 'checkbox' });
    cb.checked = movedOnly;
    cb.addEventListener('change', () => { movedOnly = cb.checked; renderStanding(); });
    b.append(el('label', { class: 'fx-toggle' }, cb,
      'only factions that moved (hide ones that only reported MAX / MIN)'));
    const host = el('div', {});
    b.append(host);
    const rows = (data.factions || []).filter((r) => !movedOnly || r.events > 0
      || r.standing !== null);
    const hasFile = !!data.standings_imported_at;
    const columns = [
      { key: 'faction', label: 'Faction', render: nameCell },
    ];
    if (hasFile) {
      columns.push(
        {
          key: 'standing', label: 'Standing (file)', num: true,
          render: (r) => r.standing === null ? el('span', { class: 'faint' }, '—')
            : el('span', { title: `from /outputfile faction, ${new Date(data.standings_imported_at * 1000).toLocaleString()}` },
                fmt(r.standing), ' ', el('span', { class: 'fx-badge', title: 'EverQuest standing band — assumed for EQL' }, r.standing_label || '')),
        },
        {
          key: 'est_now', label: 'Est. now', num: true,
          render: (r) => r.est_now === null ? el('span', { class: 'faint' }, '—')
            : el('span', { title: 'file value plus the log\'s movement since the import (estimate)' },
                fmt(r.est_now),
                r.moved_since_import ? el('span', { class: 'faint' }, ` (${r.moved_since_import > 0 ? '+' : ''}${r.moved_since_import})`) : ''),
        });
    }
    columns.push(
      { key: 'delta', label: 'Net (log)', num: true, render: (r) => signed(r.delta) },
      { key: 'events', label: 'Changes', num: true },
      { key: 'gained', label: 'Gained', num: true, render: (r) => r.gained ? fmt(r.gained) : null },
      { key: 'lost', label: 'Lost', num: true, render: (r) => r.lost ? fmt(r.lost) : null },
      { key: 'last_ts', label: 'Last', num: true, render: (r) => dateCell(r.last_ts) });
    renderTable(host, {
      id: 'fx.standing',
      columns,
      rows,
      defaultSort: { key: 'last_ts', dir: -1 },
      empty: 'No faction lines in the log yet — kill something, or hand in a quest.',
    });
    if (!hasFile) {
      b.append(el('div', { class: 'faint', style: 'margin-top:8px;font-size:11px;line-height:1.5' },
        'The log only reports movement. For absolute standings, type /outputfile faction in game '
        + 'and import the <Name>_<server>-Faction.txt it writes (Import Inventory in the sidebar).'));
    }
  }

  // ── tile: recent ────────────────────────────────────────────────────────
  function buildRecent(body) { els.recent = body; renderRecent(); }
  function renderRecent() {
    if (!els.recent || !els.recent.isConnected) return;
    const b = els.recent;
    if (pending(b)) return;
    b.replaceChildren();
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'fx.recent',
      columns: [
        { key: 'ts', label: 'When', num: true, render: (r) => timeCell(r.ts) },
        { key: 'faction', label: 'Faction' },
        { key: 'delta', label: 'Change', num: true, render: (r) => signed(r.delta) },
      ],
      rows: data.recent || [],
      defaultSort: { key: 'ts', dir: -1 },
      empty: 'Nothing yet.',
    });
  }

  // ── tile: summary ───────────────────────────────────────────────────────
  function buildSummary(body) { els.summary = body; renderSummary(); }
  function renderSummary() {
    if (!els.summary || !els.summary.isConnected) return;
    const b = els.summary;
    if (pending(b)) return;
    const t = data.totals || {};
    b.replaceChildren(
      statRow('Factions seen', fmt(t.factions || 0)),
      statRow('Standing changes', fmt(t.events || 0)),
      statRow('Net positive', fmt(t.raised || 0), 'good'),
      statRow('Net negative', fmt(t.lowered || 0), 'bad'),
      statRow('At maximum', fmt(t.maxed || 0)),
      statRow('At minimum', fmt(t.bottomed || 0)),
      statRow('With a file standing', data.standings_imported_at
        ? fmt(t.with_standing || 0) : el('span', { class: 'faint' }, 'no faction file yet')),
      el('div', { class: 'faint', style: 'margin-top:8px;font-size:12px;line-height:1.5' },
        'The log never states an absolute standing, only how much it moved — '
        + 'these are movements since your log began.'));
  }

  // ── tile registry ───────────────────────────────────────────────────────
  const DEFS = [
    { id: 'standing', title: 'Standing Changes', span: 8, height: 480, minSpan: 4, build: buildStanding },
    { id: 'summary',  title: 'Summary',          span: 4, height: 230, minSpan: 3, build: buildSummary },
    { id: 'recent',   title: 'Recent Changes',   span: 4, height: 250, minSpan: 3, build: buildRecent },
  ];

  function renderAll() { renderStanding(); renderSummary(); renderRecent(); }

  async function reload() {
    const cid = App.charId();
    if (loadedFor !== cid) { data = null; loadedFor = cid; }
    error = '';
    renderAll();
    try {
      data = await API.get('/api/factions' + App.q());
      loadedFor = cid;
    } catch (e) {
      data = null;
      error = e.message;
    }
    renderAll();
  }

  Pages.register({
    id: 'factions',
    title: 'Factions',
    icon: '⚖',
    render(container) {
      if (!document.getElementById('factions-css')) {
        const st = document.createElement('style');
        st.id = 'factions-css';
        st.textContent = FX_CSS;
        document.head.append(st);
      }
      container.append(el('h1', { class: 'page-title' }, 'Factions'));
      const host = el('div', {});
      container.append(host);
      Tiles.mount(host, { storageKey: SKEY, defs: DEFS });
      reload();
    },
  });
})();

/* Data Sync — start/cancel eqlwiki + EQL Tools syncs, live progress from the WS
   snapshot, recent runs + unparsed-pages report from /api/sync/status, on the
   draggable / resizable tile grid (tiles.js).

   The 1 Hz snapshot handler renders through the tile-body pattern (els.progress
   + an isConnected guard) instead of reaching for #content, because the progress
   tile may be closed, moved, or rebuilt at any time. /api/sync/status is fetched
   into module scope; the runs/unparsed tiles rebuild from that cache. */
'use strict';

(() => {
  const SKEY = 'eqa.layout.sync.v1';
  const els = {};             // tile body elements, set by each build
  let status = null;          // GET /api/sync/status
  let statusErr = null;
  let note = null;            // {text, bad} — feedback from a failed start
  let lastStatus = null;      // last snapshot.sync.status (for done-detection)
  let lastRunning = null;     // last running-ness (to re-render the Start buttons)

  const SOURCES = [
    {
      id: 'wiki', name: 'eqlwiki.com',
      desc: 'Quests, items, guides via the MediaWiki API (~19k pages fetched ' +
        '50-per-request, ~10 min first run; re-syncs only fetch changed pages).',
    },
    {
      id: 'tools', name: 'EQL Tools',
      desc: 'eqlegendstools.com item/zone pages via sitemap.xml ' +
        '(~995 pages, ~17 min first run; re-syncs follow lastmod).',
    },
  ];

  function fmtTs(ts) {
    return ts ? new Date(ts * 1000).toLocaleString() : '—';
  }
  function syncOf() {
    return (App.snapshot && App.snapshot.sync) || { status: 'idle' };
  }

  // ── tile: sources ───────────────────────────────────────────────────────
  function buildSources(body) { els.sources = body; renderSources(); }
  function renderSources() {
    if (!els.sources || !els.sources.isConnected) return;
    const b = els.sources;
    b.replaceChildren();
    const running = syncOf().status === 'running';
    for (const s of SOURCES) {
      const btn = el('button', { class: 'metal-btn primary' }, 'Start sync');
      btn.disabled = running;
      btn.addEventListener('click', () => start(s.id));
      b.append(el('div', { style: 'margin-bottom:12px' },
        el('div', { style: 'font-weight:700;margin-bottom:3px' }, s.name),
        el('div', { class: 'muted', style: 'margin-bottom:7px' }, s.desc),
        btn));
    }
    if (note) b.append(el('div', { class: note.bad ? 'bad' : 'muted' }, note.text));
  }

  async function start(source) {
    note = null;
    renderSources();
    try {
      await API.post('/api/sync/start', { source });
    } catch (e) {
      note = { text: e.message, bad: true };
      renderSources();
      return;
    }
    loadStatus();                // pick the new run row up right away
  }

  // ── tile: live progress ─────────────────────────────────────────────────
  function buildProgress(body) { els.progress = body; renderProgress(); }
  function renderProgress() {
    if (!els.progress || !els.progress.isConnected) return;
    const b = els.progress;
    const sync = syncOf();
    const running = sync.status === 'running';
    const pct = sync.total ? Math.round(100 * (sync.done || 0) / sync.total) : 0;
    const label = running
      ? `${sync.source === 'wiki' ? 'eqlwiki' : sync.source} · ${sync.phase || ''}` +
        (sync.total ? ` · ${fmt(sync.done)} / ${fmt(sync.total)}` : '')
      : `status: ${sync.status || 'idle'}`;
    const cancel = el('button', { class: 'metal-btn' }, 'Cancel');
    cancel.disabled = !running;
    cancel.addEventListener('click', () => API.post('/api/sync/cancel').catch(() => {}));
    b.replaceChildren(
      el('div', { class: 'row', style: 'align-items:baseline;margin-bottom:6px' },
        el('span', {}, label),
        el('span', { class: 'grow' }),
        el('span', { class: (sync.errors ? 'bad' : 'muted') },
          sync.errors ? `${sync.errors} errors` : '')),
      el('div', { class: 'bar-track' },
        el('div', { class: 'bar-fill', style: `width:${running ? pct : 0}%` })),
      el('div', { class: 'muted', style: 'margin-top:6px;min-height:16px' },
        running && sync.current ? String(sync.current) : ''),
      el('div', { class: 'row', style: 'margin-top:10px;align-items:center' }, cancel));
  }

  // ── tile: recent runs ───────────────────────────────────────────────────
  function buildRuns(body) { els.runs = body; renderRuns(); }
  function renderRuns() {
    if (!els.runs || !els.runs.isConnected) return;
    const b = els.runs;
    b.replaceChildren();
    if (!status) {
      b.append(el('div', { class: 'empty-note' + (statusErr ? ' bad' : '') },
        statusErr || 'Loading…'));
      return;
    }
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'sync-runs',
      columns: [
        { key: 'id', label: '#', num: true },
        { key: 'source', label: 'Source' },
        { key: 'started_at', label: 'Started', render: (r) => fmtTs(r.started_at) },
        { key: 'finished_at', label: 'Finished', render: (r) => fmtTs(r.finished_at) },
        {
          key: 'status', label: 'Status',
          render: (r) => el('span', {
            class: r.status === 'done' ? 'good'
              : (r.status === 'error' ? 'bad' : 'muted'),
          }, r.status),
        },
        {
          key: 'pages_done', label: 'Pages', num: true,
          render: (r) => `${fmt(r.pages_done)} / ${fmt(r.pages_total)}`,
          sortVal: (r) => r.pages_done,
        },
        { key: 'errors', label: 'Errors', num: true },
      ],
      rows: status.runs || [],
      defaultSort: { key: 'id', dir: -1 },
      empty: 'No sync runs yet.',
    });
  }

  // ── tile: unparsed pages ────────────────────────────────────────────────
  function buildUnparsed(body) { els.unparsed = body; renderUnparsed(); }
  function renderUnparsed() {
    if (!els.unparsed || !els.unparsed.isConnected) return;
    const b = els.unparsed;
    b.replaceChildren();
    if (!status) {
      b.append(el('div', { class: 'empty-note' + (statusErr ? ' bad' : '') },
        statusErr || 'Loading…'));
      return;
    }
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'sync-unparsed',
      columns: [
        {
          key: 'url', label: 'Page',
          render: (r) => el('a', { href: r.url, target: '_blank', rel: 'noopener' },
            decodeURIComponent(String(r.url).split('/').pop() || r.url).replace(/_/g, ' ')),
        },
        { key: 'kind', label: 'Kind' },
        { key: 'parse_error', label: 'Error' },
      ],
      rows: status.unparsed || [],
      defaultSort: null,
      empty: 'All fetched pages parsed cleanly.',
    });
  }

  // ── data ────────────────────────────────────────────────────────────────
  async function loadStatus() {
    let st;
    try {
      st = await API.get('/api/sync/status');
    } catch (e) {
      if (status) return;              // keep the tables we already show
      statusErr = e.message;
      renderRuns();
      renderUnparsed();
      return;
    }
    status = st;
    statusErr = null;
    renderRuns();
    renderUnparsed();
  }

  const DEFS = [
    { id: 'sources',  title: 'Sources',        span: 5,  height: 260, minSpan: 3, build: buildSources },
    { id: 'progress', title: 'Progress',       span: 7,  height: 260, minSpan: 3, build: buildProgress },
    { id: 'runs',     title: 'Recent Runs',    span: 12, height: 300, minSpan: 4, build: buildRuns },
    { id: 'unparsed', title: 'Unparsed Pages', span: 12, height: 320, minSpan: 4, build: buildUnparsed },
  ];

  Pages.register({
    id: 'sync',
    title: 'Data Sync',
    icon: '⟳',
    render(container) {
      status = null; statusErr = null; note = null;
      lastStatus = syncOf().status || null;
      lastRunning = lastStatus === 'running';
      container.append(el('h1', { class: 'page-title' }, 'Data Sync'));
      const host = el('div', {});
      container.append(host);
      Tiles.mount(host, { storageKey: SKEY, defs: DEFS });
      loadStatus();
    },
    onSnapshot(snap) {
      renderProgress();
      const s = snap && snap.sync ? snap.sync.status : null;
      const running = s === 'running';
      if (running !== lastRunning) { lastRunning = running; renderSources(); }
      // refresh the tables when a run transitions into or out of 'running'
      if (lastStatus === 'running' && s !== 'running') loadStatus();
      if (s === 'running' && lastStatus !== 'running') loadStatus();
      lastStatus = s;
    },
  });
})();

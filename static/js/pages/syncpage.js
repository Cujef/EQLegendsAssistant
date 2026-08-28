/* Data Sync page — start/cancel eqlwiki + EQL Tools syncs, live progress from
   the WS snapshot, recent runs + unparsed-pages report from /api/sync/status. */
'use strict';

(() => {
  let lastStatus = null;   // last snapshot.sync we rendered (for done-detection)

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

  function renderProgress(container, sync) {
    const box = container.querySelector('.sync-progress');
    if (!box) return;
    sync = sync || { status: 'idle' };
    const running = sync.status === 'running';

    for (const btn of container.querySelectorAll('.sync-start')) btn.disabled = running;
    const cancelBtn = container.querySelector('.sync-cancel');
    if (cancelBtn) cancelBtn.disabled = !running;

    const pct = sync.total ? Math.round(100 * (sync.done || 0) / sync.total) : 0;
    const label = running
      ? `${sync.source === 'wiki' ? 'eqlwiki' : sync.source} · ${sync.phase || ''}` +
        (sync.total ? ` · ${fmt(sync.done)} / ${fmt(sync.total)}` : '')
      : `status: ${sync.status || 'idle'}`;
    box.replaceChildren(
      el('div', { class: 'row', style: 'align-items:baseline;margin-bottom:6px' },
        el('span', {}, label),
        el('span', { class: 'grow' }),
        el('span', { class: (sync.errors ? 'bad' : 'muted') },
          sync.errors ? `${sync.errors} errors` : '')),
      el('div', { class: 'bar-track' },
        el('div', { class: 'bar-fill', style: `width:${running ? pct : 0}%` })),
      el('div', { class: 'muted', style: 'margin-top:6px;min-height:16px' },
        running && sync.current ? String(sync.current) : ''),
    );
  }

  async function loadStatus(container) {
    let st;
    try {
      st = await API.get('/api/sync/status');
    } catch (e) {
      return;
    }
    if (!container.isConnected) return;

    renderTable(container.querySelector('.sync-runs'), {
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
      rows: st.runs || [],
      defaultSort: { key: 'id', dir: -1 },
      empty: 'No sync runs yet.',
    });

    renderTable(container.querySelector('.sync-unparsed'), {
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
      rows: st.unparsed || [],
      defaultSort: null,
      empty: 'All fetched pages parsed cleanly.',
    });
  }

  async function start(container, source) {
    const note = container.querySelector('.sync-note');
    note.textContent = '';
    note.className = 'muted sync-note';
    try {
      await API.post('/api/sync/start', { source });
    } catch (e) {
      note.textContent = e.message;
      note.className = 'bad sync-note';
    }
  }

  Pages.register({
    id: 'sync',
    title: 'Data Sync',
    icon: '⟳',
    render(container) {
      const cards = SOURCES.map((s) =>
        el('div', { class: 'panel grow', style: 'min-width:260px' },
          el('h2', {}, s.name),
          el('div', { class: 'panel-body' },
            el('div', { class: 'muted', style: 'margin-bottom:10px' }, s.desc),
            el('button', {
              class: 'metal-btn primary sync-start',
              onclick: () => start(container, s.id),
            }, 'Start sync'))));

      container.append(
        el('h1', { class: 'page-title' }, 'Data Sync'),
        el('div', { class: 'row', style: 'margin-bottom:12px' }, cards),
        el('div', { class: 'panel', style: 'margin-bottom:12px' },
          el('h2', {}, 'Progress'),
          el('div', { class: 'panel-body' },
            el('div', { class: 'sync-progress' }),
            el('div', { class: 'row', style: 'margin-top:10px;align-items:center' },
              el('button', {
                class: 'metal-btn sync-cancel',
                onclick: () => API.post('/api/sync/cancel').catch(() => {}),
              }, 'Cancel'),
              el('span', { class: 'muted sync-note' })))),
        el('div', { class: 'panel', style: 'margin-bottom:12px' },
          el('h2', {}, 'Recent runs'),
          el('div', { class: 'panel-body sync-runs' })),
        el('div', { class: 'panel' },
          el('h2', {}, 'Unparsed pages'),
          el('div', {
            class: 'panel-body sync-unparsed',
            style: 'max-height:320px;overflow:auto',
          })),
      );

      lastStatus = App.snapshot && App.snapshot.sync ? App.snapshot.sync.status : null;
      renderProgress(container, App.snapshot ? App.snapshot.sync : null);
      loadStatus(container);
    },
    onSnapshot(snap) {
      const container = document.getElementById('content');
      renderProgress(container, snap.sync);
      // refresh the tables when a run transitions out of 'running'
      const status = snap.sync ? snap.sync.status : null;
      if (lastStatus === 'running' && status !== 'running') loadStatus(container);
      if (status === 'running' && lastStatus !== 'running') loadStatus(container);
      lastStatus = status;
    },
  });
})();

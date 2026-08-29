/* Quest Progress — tracked quests + the selected quest's step checklist on the
   draggable / resizable tile grid (tiles.js).

   The detail panel used to be created below the list on click; it is now a
   permanent tile that says "Select a quest above" until a row is clicked.
   Data is fetched once per page render into module scope, so a tile that is
   closed/reopened/dragged rebuilds from the cache without refetching. */
'use strict';

(() => {
  const QP_CSS = `
tr.qp-sel td { background: var(--sel-bg); }
.qp-name { font:700 13px var(--font-display); letter-spacing:0.06em; margin-bottom:4px; }
.qp-step { display:flex; gap:8px; padding:3px 0; align-items:flex-start; cursor:pointer; }
.qp-step .done { color:var(--text-faint); text-decoration:line-through; }
`;

  const SKEY = 'eqa.layout.quests.v1';
  const els = {};             // tile body elements, set by each build
  let progress = null;        // GET /api/quest-progress -> {quests:[...]}
  let progressErr = null;
  let selId = null;           // quest id shown in the detail tile
  let detail = null;          // GET /api/quests/{id}
  let detailErr = null;

  // ── tile: tracked quests ────────────────────────────────────────────────
  function buildTracked(body) { els.tracked = body; renderTracked(); }
  function renderTracked() {
    if (!els.tracked || !els.tracked.isConnected) return;
    const b = els.tracked;
    b.replaceChildren();
    if (progressErr) { b.append(el('div', { class: 'empty-note bad' }, progressErr)); return; }
    if (!progress) { b.append(el('div', { class: 'empty-note' }, 'Loading…')); return; }
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'questprog',
      columns: [
        { key: 'name', label: 'Quest' },
        { key: 'start_zone', label: 'Zone' },
        { key: 'quest_giver', label: 'Giver' },
        {
          key: 'level_min', label: 'Level', num: true,
          render: (r) => r.level_min ? `${r.level_min}${r.level_max ? '-' + r.level_max : '+'}` : null,
        },
        {
          key: 'steps_done', label: 'Steps', num: true,
          render: (r) => r.steps ? `${r.steps_done}/${r.steps}` : '—',
        },
        {
          key: 'status', label: 'Status',
          render: (r) => r.status === 'completed'
            ? el('span', { class: 'good' }, '✔ done') : el('span', { class: 'warn' }, 'tracked'),
        },
      ],
      rows: progress.quests || [],
      defaultSort: { key: 'status', dir: 1 },
      empty: 'Nothing tracked. Add quests from the Quest Suggestions page (after a Data Sync).',
      onRow: (r, tr) => {
        tr.style.cursor = 'pointer';
        if (r.id === selId) tr.classList.add('qp-sel');
        tr.addEventListener('click', () => selectQuest(r.id));
      },
    });
  }

  // ── tile: selected quest detail ─────────────────────────────────────────
  function buildDetail(body) { els.detail = body; renderDetail(); }
  function renderDetail() {
    if (!els.detail || !els.detail.isConnected) return;
    const b = els.detail;
    b.replaceChildren();
    if (selId === null) { b.append(el('div', { class: 'empty-note' }, 'Select a quest above.')); return; }
    if (detailErr) { b.append(el('div', { class: 'empty-note bad' }, detailErr)); return; }
    if (!detail) { b.append(el('div', { class: 'empty-note' }, 'Loading…')); return; }

    const d = detail;
    const steps = el('div', {});
    const stepRows = d.steps || [];
    for (const s of stepRows) {
      const cb = el('input', { type: 'checkbox' });
      cb.checked = !!s.done;
      cb.addEventListener('change', async () => {
        try {
          const r = await API.post(
            `/api/quests/${d.id}/steps/${s.step_index}/toggle` + App.q());
          s.done = r.done ? 1 : 0;
        } catch (e) { cb.checked = !!s.done; return; }
        renderDetail();      // refresh the strike-through from the cached detail
        reload();            // steps_done in the tracked table
      });
      steps.append(el('label', { class: 'qp-step' },
        cb, el('span', { class: s.done ? 'done' : '' }, s.text)));
    }
    if (!stepRows.length) {
      steps.append(el('div', { class: 'empty-note' }, 'No parsed steps — use the wiki link.'));
    }

    const btn = (label, status, cls) => {
      const bt = el('button', { class: 'metal-btn ' + (cls || '') }, label);
      bt.addEventListener('click', async () => {
        bt.disabled = true;
        try { await API.post(`/api/quests/${d.id}/status` + App.q(), { status }); }
        catch (e) { bt.disabled = false; return; }
        selId = null; detail = null; detailErr = null;
        renderDetail();
        reload();
      });
      return bt;
    };

    b.append(
      el('div', { class: 'qp-name' }, d.name),
      el('div', { class: 'muted', style: 'margin-bottom:8px' },
        `${d.start_zone || '?'} · ${d.quest_giver || '?'} · level ` +
        `${d.level_min ?? '?'}${d.level_max ? '-' + d.level_max : '+'} · `,
        el('a', { href: d.wiki_url, target: '_blank', rel: 'noopener' }, 'open on EQLWiki ↗')),
      steps,
      el('div', { class: 'row', style: 'margin-top:10px' },
        btn('Mark completed', 'completed', 'primary'), btn('Untrack', 'untracked')));
  }

  async function selectQuest(id) {
    selId = id; detail = null; detailErr = null;
    renderTracked();                       // move the row highlight
    renderDetail();                        // 'Loading…'
    try {
      const d = await API.get(`/api/quests/${id}` + App.q());
      if (selId !== id) return;            // user clicked something else meanwhile
      detail = d;
    } catch (e) {
      if (selId !== id) return;
      detailErr = e.message;
    }
    renderDetail();
  }

  // ── data ────────────────────────────────────────────────────────────────
  async function reload() {
    try { progress = await API.get('/api/quest-progress' + App.q()); progressErr = null; }
    catch (e) { progressErr = e.message; }
    renderTracked();
  }

  const DEFS = [
    { id: 'tracked', title: 'Tracked Quests', span: 12, height: 380, minSpan: 4, build: buildTracked },
    { id: 'detail',  title: 'Quest Detail',   span: 12, height: 420, minSpan: 4, build: buildDetail },
  ];

  Pages.register({
    id: 'quests',
    title: 'Quest Progress',
    icon: '📜',
    render(container) {
      if (!document.getElementById('questspage-css')) {
        const st = document.createElement('style');
        st.id = 'questspage-css';
        st.textContent = QP_CSS;
        document.head.append(st);
      }
      progress = null; progressErr = null;
      selId = null; detail = null; detailErr = null;
      container.append(el('h1', { class: 'page-title' }, 'Quest Progress'));
      const host = el('div', {});
      container.append(host);
      Tiles.mount(host, { storageKey: SKEY, defs: DEFS });
      reload();
    },
  });
})();

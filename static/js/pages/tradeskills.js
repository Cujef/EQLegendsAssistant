/* Tradeskills: current levels from log skill-ups, guide links, craftables.

   Layout is the draggable / resizable / lockable tile grid (tiles.js). Every
   render* guards on its body still being connected before replaceChildren(), so
   close → reopen → drag is safe, and each reads the cached payload. */
'use strict';

(() => {
  const SKEY = 'eqa.layout.tradeskills.v1';
  const els = {};        // tile body elements, set by each build
  let data = null;       // /api/tradeskills payload
  let loadedFor = null;  // character id `data` belongs to
  let error = '';

  /* A tile's build() can run before the fetch lands (and again after a failure). */
  function pending(box) {
    if (data) return false;
    box.replaceChildren(el('div', { class: 'empty-note' + (error ? ' bad' : '') },
      error || 'Loading…'));
    return true;
  }

  const dateCell = (r) => r.last_ts ? new Date(r.last_ts * 1000).toLocaleDateString() : null;

  // ── tile: tradeskills ───────────────────────────────────────────────────
  function buildTradeskills(body) { els.tradeskills = body; renderTradeskills(); }
  function renderTradeskills() {
    if (!els.tradeskills || !els.tradeskills.isConnected) return;
    const b = els.tradeskills;
    if (pending(b)) return;
    b.replaceChildren();
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'ts.main',
      columns: [
        { key: 'skill', label: 'Tradeskill' },
        {
          key: 'level', label: 'Skill', num: true,
          render: (r) => r.level === null
            ? el('span', { class: 'faint', title: 'no skill-up lines in the log yet' }, 'unknown')
            : String(r.level),
        },
        { key: 'last_ts', label: 'Last skill-up', num: true, render: dateCell },
        {
          key: 'craftables', label: 'Craftable now', num: true,
          sortVal: (r) => r.craftables.length,
          render: (r) => r.craftables.length ? String(r.craftables.length) : el('span', { class: 'faint' }, '-'),
        },
        {
          key: 'wiki_url', label: 'Guide',
          render: (r) => el('a', { href: r.wiki_url, target: '_blank', rel: 'noopener' }, 'wiki guide'),
        },
      ],
      rows: data.tradeskills || [],
      defaultSort: { key: 'level', dir: -1 },
    });
  }

  // ── tile: other skills ──────────────────────────────────────────────────
  function buildOther(body) { els.other = body; renderOther(); }
  function renderOther() {
    if (!els.other || !els.other.isConnected) return;
    const b = els.other;
    if (pending(b)) return;
    b.replaceChildren();
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'ts.other',
      columns: [
        { key: 'skill', label: 'Skill' },
        { key: 'level', label: 'Level', num: true },
        { key: 'last_ts', label: 'Last skill-up', num: true, render: dateCell },
      ],
      rows: data.other_skills || [],
      defaultSort: { key: 'level', dir: -1 },
      empty: 'No skill-ups found yet - import your log on the Inventory page.',
    });
  }

  // ── tile: note ──────────────────────────────────────────────────────────
  function buildNote(body) { els.note = body; renderNote(); }
  function renderNote() {
    if (!els.note || !els.note.isConnected) return;
    els.note.replaceChildren(el('div', { class: 'muted' },
      'Levels come from "You have become better at X!" log lines - a skill you have ' +
      'not raised since logging began shows as unknown.'));
  }

  // ── tile registry ───────────────────────────────────────────────────────
  const DEFS = [
    { id: 'tradeskills', title: 'Tradeskills',                     span: 7,  height: 420, minSpan: 4, build: buildTradeskills },
    { id: 'other',       title: 'All Other Skills Seen In The Log', span: 5, height: 420, minSpan: 3, build: buildOther },
    { id: 'note',        title: 'Where These Levels Come From',     span: 12, height: 90, minSpan: 3, build: buildNote },
  ];

  function renderAll() {
    renderTradeskills();
    renderOther();
    renderNote();
  }

  async function reload() {
    const cid = App.charId();
    if (loadedFor !== cid) { data = null; loadedFor = cid; }
    error = '';
    renderAll();
    try {
      data = await API.get('/api/tradeskills' + App.q());
      loadedFor = cid;
    } catch (e) {
      data = null;
      error = e.message;
    }
    renderAll();
  }

  Pages.register({
    id: 'tradeskills',
    title: 'Tradeskills',
    icon: '⚒',
    render(container) {
      container.append(el('h1', { class: 'page-title' }, 'Tradeskills'));
      const host = el('div', {});
      container.append(host);
      Tiles.mount(host, { storageKey: SKEY, defs: DEFS });
      reload();
    },
  });
})();

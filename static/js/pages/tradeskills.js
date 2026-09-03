/* Tradeskills: skill levels from log skill-ups, per-recipe combine history,
   depot materials cross-referenced with the inventory dump, guide links.

   Layout is the draggable / resizable / lockable tile grid (tiles.js). Every
   render* guards on its body still being connected before replaceChildren(), so
   close → reopen → drag is safe, and each reads the cached payload.

   Honesty: a recipe's Skill column is INFERRED (a skill-up within 1 s of the
   combine); "In depot" is an estimate from the log; "On hand" is the last
   imported dump. The payload's `notes` say the same and the tiles repeat it. */
'use strict';

(() => {
  const TS_CSS = `
.ts-badge { display:inline-block; margin-left:6px; padding:0 5px; vertical-align:1px;
  font:700 9px var(--font-display); letter-spacing:0.1em; text-transform:uppercase;
  border:1px solid var(--warn); color:var(--warn); }
.ts-infer { color:var(--text-faint); font-size:10px; margin-left:4px; }
`;
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

  const dateCell = (ts) => ts ? new Date(ts * 1000).toLocaleDateString() : null;
  function rateCell(r) {
    if (r.rate === null || r.rate === undefined) return null;
    const cls = r.rate >= 90 ? 'good' : r.rate < 50 ? 'bad' : '';
    return el('span', { class: cls }, r.rate.toFixed(0) + '%');
  }

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
        { key: 'last_ts', label: 'Last skill-up', num: true, render: (r) => dateCell(r.last_ts) },
        {
          key: 'combines', label: 'Combines', num: true,
          render: (r) => r.combines ? fmt(r.combines) : el('span', { class: 'faint' }, '-'),
        },
        {
          key: 'recipes', label: 'Recipes', num: true,
          render: (r) => r.recipes
            ? String(r.recipes) + (r.capped_recipes ? ` (${r.capped_recipes} capped)` : '')
            : el('span', { class: 'faint' }, '-'),
        },
        {
          key: 'known_recipes', label: 'Known (file)', num: true,
          render: (r) => r.known_recipes === null || r.known_recipes === undefined
            ? el('span', { class: 'faint', title: 'import /outputfile recipes <skill>' }, '-')
            : String(r.known_recipes),
        },
        {
          key: 'craftables', label: 'Guide craftables', num: true,
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

  // ── tile: recipes ───────────────────────────────────────────────────────
  function buildRecipes(body) { els.recipes = body; renderRecipes(); }
  function renderRecipes() {
    if (!els.recipes || !els.recipes.isConnected) return;
    const b = els.recipes;
    if (pending(b)) return;
    b.replaceChildren();
    const t = data.totals || {};
    if (t.attempts) {
      b.append(el('div', { class: 'muted', style: 'font-size:12px;margin-bottom:6px' },
        `${fmt(t.attempts)} combines · ${fmt(t.made)} made · ${fmt(t.failed)} failed · `
        + `${fmt(t.recipes)} recipes` + (t.capped ? ` · ${t.capped} no longer train` : '')));
    }
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'ts.recipes',
      columns: [
        {
          key: 'item', label: 'Recipe',
          render: (r) => {
            const s = el('span', {}, r.item);
            if (r.capped) s.append(el('span', { class: 'ts-badge', title: 'the game said this recipe no longer raises your skill' }, 'CAP'));
            if (r.known === false) s.append(el('span', { class: 'ts-infer', title: 'not in any imported /outputfile recipes list (a different skill\'s list, or not learned)' }, 'not in file'));
            return s;
          },
        },
        {
          key: 'skill', label: 'Skill',
          render: (r) => r.skill
            ? el('span', {}, r.skill, el('span', { class: 'ts-infer', title: `inferred from ${r.skill_votes} skill-up line(s) within 1 s of a combine` }, 'inferred'))
            : el('span', { class: 'faint', title: 'no skill-up landed next to a combine of this recipe' }, '?'),
        },
        { key: 'made', label: 'Made', num: true },
        { key: 'failed', label: 'Failed', num: true, render: (r) => r.failed ? String(r.failed) : el('span', { class: 'faint' }, '0') },
        { key: 'rate', label: 'Rate', num: true, render: rateCell },
        { key: 'last_ts', label: 'Last', num: true, render: (r) => dateCell(r.last_ts) },
      ],
      rows: data.recipes || [],
      defaultSort: { key: 'last_ts', dir: -1 },
      empty: 'No combines in the log yet — "You have fashioned…" and "You lacked the skills…" lines land here.',
    });
  }

  // ── tile: materials ─────────────────────────────────────────────────────
  function buildMaterials(body) { els.materials = body; renderMaterials(); }
  function renderMaterials() {
    if (!els.materials || !els.materials.isConnected) return;
    const b = els.materials;
    if (pending(b)) return;
    b.replaceChildren();
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'ts.materials',
      columns: [
        { key: 'item', label: 'Material' },
        { key: 'used', label: 'Used', num: true, render: (r) => fmt(r.used) },
        {
          key: 'est_depot', label: 'In depot (est.)', num: true,
          render: (r) => r.est_depot === null || r.est_depot === undefined
            ? el('span', { class: 'faint', title: 'no "(leaving N)" line seen yet' }, '?')
            : fmt(r.est_depot),
        },
        {
          key: 'on_hand', label: 'On hand (dump)', num: true,
          render: (r) => r.on_hand_source ? fmt(r.on_hand)
            : el('span', { class: 'faint', title: 'import an inventory dump' }, '—'),
        },
        { key: 'last_ts', label: 'Last used', num: true, render: (r) => dateCell(r.last_used_ts || r.last_ts) },
      ],
      rows: data.materials || [],
      defaultSort: { key: 'used', dir: -1 },
      empty: 'No depot activity in the log yet.',
    });
  }

  // ── tile: known recipes (from /outputfile recipes) ──────────────────────
  function buildKnown(body) { els.known = body; renderKnown(); }
  function renderKnown() {
    if (!els.known || !els.known.isConnected) return;
    const b = els.known;
    if (pending(b)) return;
    b.replaceChildren();
    const t = data.known_totals || {};
    if (t.recipes) {
      b.append(el('div', { class: 'muted', style: 'font-size:12px;margin-bottom:6px' },
        `${fmt(t.recipes)} learned recipes across ${t.skills} skill file(s) · ${fmt(t.never_made)} never combined in the log`));
    }
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'ts.known',
      columns: [
        { key: 'skill', label: 'Skill' },
        { key: 'name', label: 'Recipe' },
        {
          key: 'made', label: 'Made (log)', num: true,
          render: (r) => r.attempts ? `${r.made}/${r.attempts}` : el('span', { class: 'faint' }, 'never'),
        },
        { key: 'last_ts', label: 'Last', num: true, render: (r) => dateCell(r.last_ts) },
      ],
      rows: data.known_recipes || [],
      defaultSort: { key: 'name', dir: 1 },
      empty: 'No recipe file imported. In game: /outputfile recipes <skill> (e.g. /outputfile recipes Baking), '
        + 'then import the <Name>_<server>-<Skill>-Recipes.txt it writes via Import Inventory.',
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
        { key: 'last_ts', label: 'Last skill-up', num: true, render: (r) => dateCell(r.last_ts) },
      ],
      rows: data.other_skills || [],
      defaultSort: { key: 'level', dir: -1 },
      empty: 'No skill-ups found yet - point the app at your log (＋ Characters).',
    });
  }

  // ── tile: note ──────────────────────────────────────────────────────────
  function buildNote(body) { els.note = body; renderNote(); }
  function renderNote() {
    if (!els.note || !els.note.isConnected) return;
    els.note.replaceChildren(el('div', { class: 'muted', style: 'line-height:1.55' },
      'Levels come from "You have become better at X!" log lines - a skill you have not raised '
      + 'since logging began shows as unknown. Combines come from "You have fashioned…" / '
      + '"You lacked the skills…" lines; CAP means the game said the recipe no longer trains. '
      + 'A recipe\'s skill is inferred from a skill-up landing within a second of the combine. '
      + '"In depot" is estimated from "(leaving N)" plus later deposits and withdrawals; '
      + '"On hand" is the last imported inventory dump. "Known" recipes come from '
      + '/outputfile recipes <skill> files you import (learned recipes only).'));
  }

  // ── tile registry ───────────────────────────────────────────────────────
  const DEFS = [
    { id: 'tradeskills', title: 'Tradeskills',                     span: 7,  height: 420, minSpan: 4, build: buildTradeskills },
    { id: 'other',       title: 'All Other Skills Seen In The Log', span: 5, height: 420, minSpan: 3, build: buildOther },
    { id: 'recipes',     title: 'Recipes (From The Log)',           span: 7,  height: 420, minSpan: 4, build: buildRecipes },
    { id: 'materials',   title: 'Materials: Depot vs On Hand',      span: 5,  height: 420, minSpan: 3, build: buildMaterials },
    { id: 'known',       title: 'Known Recipes (From /outputfile recipes)', span: 12, height: 320, minSpan: 4, build: buildKnown },
    { id: 'note',        title: 'Where These Numbers Come From',    span: 12, height: 110, minSpan: 3, build: buildNote },
  ];

  function renderAll() {
    renderTradeskills();
    renderOther();
    renderRecipes();
    renderMaterials();
    renderKnown();
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
      if (!document.getElementById('tradeskills-css')) {
        const st = document.createElement('style');
        st.id = 'tradeskills-css';
        st.textContent = TS_CSS;
        document.head.append(st);
      }
      container.append(el('h1', { class: 'page-title' }, 'Tradeskills'));
      const host = el('div', {});
      container.append(host);
      Tiles.mount(host, { storageKey: SKEY, defs: DEFS });
      reload();
    },
  });
})();

/* Overview: computed stats vs caps, AA ledger, focus effects, log highlights.
   Every value is labeled computed/manual/fallback — no fake certainty.

   Layout is the draggable / resizable / lockable tile grid (tiles.js). The
   parser page's pattern applies: build* stashes the tile body in `els` and calls
   render*, and every render* bails when its body is gone (closed tile) before
   replaceChildren() — that is what makes close → reopen → drag safe. Data is
   fetched once per page render into `data`; rebuilt tiles read the cache. */
'use strict';

(() => {
  const SKEY = 'eqa.layout.overview.v1';
  const els = {};            // tile body elements, set by each build
  let data = null;           // /api/overview payload
  let loadedFor = null;      // character id `data` belongs to
  let error = '';

  function prov(kind) {
    return el('span', { class: 'prov ' + kind, title: 'source: ' + kind }, kind);
  }

  /* A tile's build() can run before the fetch lands (and again after it fails),
     so every render* funnels through here first. */
  function pending(box) {
    if (data) return false;
    box.replaceChildren(el('div', { class: 'empty-note' + (error ? ' bad' : '') },
      error || 'Loading…'));
    return true;
  }

  function statLine(label, value) {
    return el('div', { style: 'display:flex;gap:10px;justify-content:space-between;' +
      'padding:2px 0;border-bottom:1px solid var(--edge)' },
      el('span', { class: 'muted' }, label), el('span', { class: 'num' }, value));
  }

  // ── tile: character (name/level, class + race selects, manual chip) ──────
  function buildChar(body) { els.char = body; renderChar(); }
  function renderChar() {
    if (!els.char || !els.char.isConnected) return;
    const b = els.char;
    if (pending(b)) return;
    b.replaceChildren();
    const m = data.manual || {};
    const push = async (key, value) => {
      m[key] = value;                       // keep the cache honest for rebuilds
      await API.post('/api/manual-stat' + App.q(), { key, value });
    };
    const clsSel = (slot) => {
      const sel = el('select', {}, el('option', { value: '' }, `class ${slot}…`));
      for (const c of ['Bard', 'Beastlord', 'Berserker', 'Cleric', 'Druid', 'Enchanter',
        'Magician', 'Monk', 'Necromancer', 'Paladin', 'Ranger', 'Rogue',
        'Shadow Knight', 'Shaman', 'Warrior', 'Wizard']) {
        const o = el('option', { value: c }, c);
        if (m['class' + slot] === c) o.selected = true;
        sel.append(o);
      }
      sel.addEventListener('change', () => push('class' + slot, sel.value));
      return sel;
    };
    const raceSel = el('select', {}, el('option', { value: '' }, 'race…'));
    for (const r of ['Barbarian', 'Dark Elf', 'Dwarf', 'Erudite', 'Froglok', 'Gnome',
      'Half-Elf', 'Halfling', 'High Elf', 'Human', 'Iksar', 'Kerran', 'Ogre', 'Troll', 'Wood Elf']) {
      const o = el('option', { value: r }, r);
      if (m.race === r) o.selected = true;
      raceSel.append(o);
    }
    raceSel.addEventListener('change', () => push('race', raceSel.value));

    b.append(
      el('div', { style: 'margin-bottom:8px' },
        el('b', {}, App.active ? App.active.name : '?'),
        el('span', { class: 'muted' }, ` — level ${data.level ?? '?'}`)),
      el('div', { class: 'row', style: 'align-items:center' },
        clsSel(1), clsSel(2), clsSel(3), raceSel, prov('manual')));
  }

  // ── tile: AA (ledger line + purchases) ──────────────────────────────────
  function buildAA(body) { els.aa = body; renderAA(); }
  function renderAA() {
    if (!els.aa || !els.aa.isConnected) return;
    const b = els.aa;
    if (pending(b)) return;
    b.replaceChildren();
    const aa = data.aa || {};
    b.append(el('div', { style: 'margin-bottom:6px' },
      el('b', {}, 'AA: '),
      (aa.unspent === null || aa.unspent === undefined)
        ? el('span', { class: 'muted' }, 'no AA lines found in the log yet ')
        : el('span', {}, `${fmt(aa.earned)} earned · ${fmt(aa.spent)} spent · ${fmt(aa.unspent)} unspent `),
      prov('computed')));
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'ov.aa',
      columns: [
        { key: 'ability_name', label: 'Ability' },
        { key: 'points', label: 'Cost', num: true },
        {
          key: 'ts', label: 'When', num: true,
          render: (r) => r.ts ? new Date(r.ts * 1000).toLocaleDateString() : null,
        },
      ],
      rows: aa.abilities || [], defaultSort: null,
      empty: 'No AA purchases found in the log yet.',
    });
  }

  // ── tile: stats vs caps ─────────────────────────────────────────────────
  function buildStats(body) { els.stats = body; renderStats(); }
  function renderStats() {
    if (!els.stats || !els.stats.isConnected) return;
    const b = els.stats;
    if (pending(b)) return;
    b.replaceChildren();
    const caps = {};
    for (const c of data.caps || []) caps[c.stat] = c;
    const c = data.computed || {};
    const rows = [];
    const capRow = (k, v) => {
      const cap = caps[k];
      return { stat: k, val: v, cap: cap ? cap.cap : null,
               capSrc: cap ? cap.source : null, soft: cap ? cap.soft : null };
    };
    for (const [k, v] of Object.entries(c.stats || {})) rows.push(capRow(k, v));
    for (const [k, v] of Object.entries(c.resists || {})) rows.push(capRow(k, v));
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'ov.stats',
      columns: [
        { key: 'stat', label: 'Stat' },
        { key: 'val', label: 'Gear total', num: true },
        {
          key: 'cap', label: 'Cap', num: true,
          render: (r) => r.cap === null ? null
            : el('span', {},
              (r.soft ? r.soft + ' soft / ' : '') + r.cap,
              r.capSrc === 'fallback' ? prov('fallback') : null),
        },
      ],
      rows, defaultSort: null,
    });
    b.append(el('div', { class: 'muted',
      style: 'margin-top:6px;padding-top:6px;border-top:1px solid var(--edge)' },
      `AC ${fmt(c.ac)} · HP +${fmt(c.hp)} · Mana +${fmt(c.mana)} · worn haste ${c.worn_haste}%`));
  }

  // ── tile: best focus / proc / worn per family ───────────────────────────
  function buildFocus(body) { els.focus = body; renderFocus(); }
  function renderFocus() {
    if (!els.focus || !els.focus.isConnected) return;
    const b = els.focus;
    if (pending(b)) return;
    b.replaceChildren();
    const host = el('div', {});
    b.append(host);
    renderTable(host, {
      id: 'ov.focus',
      columns: [
        { key: 'effect_type', label: 'Type' },
        { key: 'effect_name', label: 'Best effect' },
        { key: 'item_name', label: 'On item' },
        {
          key: 'is_equipped', label: 'Active', num: true,
          render: (r) => r.is_equipped ? el('span', { class: 'good' }, '● worn') : el('span', { class: 'faint' }, 'owned'),
        },
      ],
      rows: data.focus || [], defaultSort: { key: 'effect_type', dir: 1 },
      empty: 'No effects known yet — run a Data Sync so items get effect data.',
    });
  }

  // ── tile: log highlights ────────────────────────────────────────────────
  function buildHighlights(body) { els.highlights = body; renderHighlights(); }
  function renderHighlights() {
    if (!els.highlights || !els.highlights.isConnected) return;
    const b = els.highlights;
    if (pending(b)) return;
    b.replaceChildren();
    const H = data.highlights || {};
    const ctx = (k) => {
      try {
        const c = JSON.parse((H[k] || {}).context_json || 'null');
        return c ? ` (${c.target || c.spell || ''})` : '';
      } catch (e) { return ''; }
    };
    const li = (label, k, suffix) => {
      const h = H[k];
      return el('div', { style: 'padding:2px 0' },
        el('span', { class: 'muted' }, label + ': '),
        h ? el('b', {}, fmt(h.value_num) + (suffix || '') + ctx(k)) : el('span', { class: 'faint' }, '—'));
    };
    b.append(
      li('Highest melee hit', 'max_melee_hit'),
      li('Highest melee crit', 'max_melee_crit'),
      li('Highest spell hit', 'max_spell_hit'),
      li('Biggest DoT tick', 'max_dot_tick'),
      li('Biggest hit taken', 'biggest_hit_taken'),
      li('Total kills', 'total_kills'),
      li('Total crits', 'total_crits'),
      li('Total deaths', 'total_deaths'),
      li('Playtime', 'playtime_seconds', ' s'));
  }

  // ── tile: nemesis (died most to) ────────────────────────────────────────
  function buildNemesis(body) { els.nemesis = body; renderNemesis(); }
  function renderNemesis() {
    if (!els.nemesis || !els.nemesis.isConnected) return;
    const b = els.nemesis;
    if (pending(b)) return;
    b.replaceChildren();
    const nem = data.nemesis || [];
    if (!nem.length) { b.append(el('div', { class: 'faint' }, '—')); return; }
    for (const n of nem) {
      b.append(el('div', { style: 'padding:2px 0' },
        el('span', { class: 'bad' }, `☠ ${n.killer}`),
        el('span', { class: 'muted' }, ` × ${n.n}`)));
    }
  }

  // ── tile: caveats ───────────────────────────────────────────────────────
  function buildCaveats(body) { els.caveats = body; renderCaveats(); }
  function renderCaveats() {
    if (!els.caveats || !els.caveats.isConnected) return;
    const b = els.caveats;
    if (pending(b)) return;
    b.replaceChildren();
    const list = data.caveats || [];
    if (!list.length) {
      b.append(el('div', { class: 'faint' }, 'No caveats — every number above came from matched data.'));
      return;
    }
    for (const t of list) {
      b.append(el('div', { class: 'muted', style: 'font-size:12px' }, '· ' + t));
    }
  }

  // ── tile registry ───────────────────────────────────────────────────────
  const DEFS = [
    { id: 'character',  title: 'Character',                    span: 4,  height: 190, minSpan: 3, build: buildChar },
    { id: 'aa',         title: 'Alternate Advancement',        span: 4,  height: 300, minSpan: 3, build: buildAA },
    { id: 'stats',      title: 'Stats vs Caps',                span: 4,  height: 300, minSpan: 3, build: buildStats },
    { id: 'focus',      title: 'Best Focus / Proc / Worn',     span: 6,  height: 340, minSpan: 3, build: buildFocus },
    { id: 'highlights', title: 'Log Highlights',               span: 3,  height: 340, minSpan: 2, build: buildHighlights },
    { id: 'nemesis',    title: 'Died Most To',                 span: 3,  height: 340, minSpan: 2, build: buildNemesis },
    { id: 'caveats',    title: 'Caveats',                      span: 12, height: 110, minSpan: 3, build: buildCaveats },
  ];

  function renderAll() {
    renderChar();
    renderAA();
    renderStats();
    renderFocus();
    renderHighlights();
    renderNemesis();
    renderCaveats();
  }

  async function reload() {
    const cid = App.charId();
    if (loadedFor !== cid) { data = null; loadedFor = cid; }   // never show another char's numbers
    error = '';
    renderAll();
    try {
      data = await API.get('/api/overview' + App.q());
      loadedFor = cid;
    } catch (e) {
      data = null;
      error = e.message;
    }
    renderAll();
  }

  Pages.register({
    id: 'overview',
    title: 'Overview',
    icon: '⚔',
    render(container) {
      container.append(el('h1', { class: 'page-title' }, 'Overview'));
      const host = el('div', {});
      container.append(host);
      Tiles.mount(host, { storageKey: SKEY, defs: DEFS });
      reload();
    },
  });
})();

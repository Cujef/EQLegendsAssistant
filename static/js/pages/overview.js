/* Overview: computed stats vs caps, AA ledger, focus effects, log highlights.
   Every value is labeled computed/manual/fallback — no fake certainty. */
'use strict';

(() => {
  let data = null;

  function prov(kind) {
    return el('span', { class: 'prov ' + kind, title: 'source: ' + kind }, kind);
  }

  function statPanel() {
    const caps = {};
    for (const c of data.caps) caps[c.stat] = c;
    const rows = [];
    const st = data.computed.stats;
    const capRow = (k, v) => {
      const cap = caps[k];
      return { stat: k, val: v, cap: cap ? cap.cap : null,
               capSrc: cap ? cap.source : null, soft: cap ? cap.soft : null };
    };
    for (const k of Object.keys(st)) rows.push(capRow(k, st[k]));
    for (const [k, v] of Object.entries(data.computed.resists)) rows.push(capRow(k, v));
    const body = el('div', { class: 'panel-body' });
    renderTable(body, {
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
    const c = data.computed;
    const line = el('div', { class: 'panel-body muted', style: 'border-top:1px solid var(--edge)' },
      `AC ${fmt(c.ac)} · HP +${fmt(c.hp)} · Mana +${fmt(c.mana)} · worn haste ${c.worn_haste}%`);
    return el('div', { class: 'panel grow', style: 'min-width:300px' },
      el('h2', {}, 'Stats vs caps'), body, line);
  }

  function charPanel() {
    const m = data.manual;
    const clsSel = (slot) => {
      const sel = el('select', {}, el('option', { value: '' }, `class ${slot}…`));
      for (const c of ['Bard', 'Beastlord', 'Berserker', 'Cleric', 'Druid', 'Enchanter',
        'Magician', 'Monk', 'Necromancer', 'Paladin', 'Ranger', 'Rogue',
        'Shadow Knight', 'Shaman', 'Warrior', 'Wizard']) {
        const o = el('option', { value: c }, c);
        if (m['class' + slot] === c) o.selected = true;
        sel.append(o);
      }
      sel.addEventListener('change', async () => {
        await API.post('/api/manual-stat' + App.q(), { key: 'class' + slot, value: sel.value });
      });
      return sel;
    };
    const raceSel = el('select', {}, el('option', { value: '' }, 'race…'));
    for (const r of ['Barbarian', 'Dark Elf', 'Dwarf', 'Erudite', 'Froglok', 'Gnome',
      'Half-Elf', 'Halfling', 'High Elf', 'Human', 'Iksar', 'Kerran', 'Ogre', 'Troll', 'Wood Elf']) {
      const o = el('option', { value: r }, r);
      if (m.race === r) o.selected = true;
      raceSel.append(o);
    }
    raceSel.addEventListener('change', async () => {
      await API.post('/api/manual-stat' + App.q(), { key: 'race', value: raceSel.value });
    });

    const aa = data.aa;
    const abilities = el('div', { style: 'max-height:160px;overflow:auto;margin-top:6px' });
    renderTable(abilities, {
      id: 'ov.aa',
      columns: [
        { key: 'ability_name', label: 'Ability' },
        { key: 'points', label: 'Cost', num: true },
        {
          key: 'ts', label: 'When', num: true,
          render: (r) => r.ts ? new Date(r.ts * 1000).toLocaleDateString() : null,
        },
      ],
      rows: aa.abilities || [], defaultSort: null, empty: 'No AA purchases found in the log yet.',
    });
    return el('div', { class: 'panel', style: 'flex:1;min-width:300px' },
      el('h2', {}, `${App.active ? App.active.name : '?'} — level ${data.level ?? '?'}`),
      el('div', { class: 'panel-body' },
        el('div', { class: 'row', style: 'align-items:center;margin-bottom:8px' },
          clsSel(1), clsSel(2), clsSel(3), raceSel, prov('manual')),
        el('div', {},
          el('b', {}, 'AA: '),
          aa.unspent === null
            ? el('span', { class: 'muted' }, 'no AA lines found in the log yet ')
            : el('span', {}, `${fmt(aa.earned)} earned · ${fmt(aa.spent)} spent · ${fmt(aa.unspent)} unspent `),
          prov('computed')),
        abilities));
  }

  function focusPanel() {
    const body = el('div', { class: 'panel-body' });
    renderTable(body, {
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
    return el('div', { class: 'panel grow', style: 'min-width:320px' },
      el('h2', {}, 'Best focus / proc / worn per family'), body);
  }

  function highlightsPanel() {
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
    const nem = (data.nemesis || []).map((n) =>
      el('div', { style: 'padding:2px 0' },
        el('span', { class: 'bad' }, `☠ ${n.killer}`), el('span', { class: 'muted' }, ` × ${n.n}`)));
    return el('div', { class: 'panel grow', style: 'min-width:300px' },
      el('h2', {}, 'Log highlights'),
      el('div', { class: 'panel-body' },
        li('Highest melee hit', 'max_melee_hit'),
        li('Highest melee crit', 'max_melee_crit'),
        li('Highest spell hit', 'max_spell_hit'),
        li('Biggest DoT tick', 'max_dot_tick'),
        li('Biggest hit taken', 'biggest_hit_taken'),
        li('Total kills', 'total_kills'),
        li('Total crits', 'total_crits'),
        li('Total deaths', 'total_deaths'),
        li('Playtime', 'playtime_seconds', ' s'),
        el('div', { style: 'margin-top:8px;border-top:1px solid var(--edge);padding-top:6px' },
          el('b', { class: 'muted' }, 'Died most to:'), ...(nem.length ? nem : [el('div', { class: 'faint' }, '—')]))));
  }

  Pages.register({
    id: 'overview',
    title: 'Overview',
    icon: '⚔',
    render(container) {
      container.append(el('h1', { class: 'page-title' }, 'Overview'));
      const host = el('div', {});
      container.append(host);
      API.get('/api/overview' + App.q()).then((d) => {
        data = d;
        host.replaceChildren(
          el('div', { class: 'row' }, charPanel(), statPanel()),
          el('div', { class: 'row', style: 'margin-top:12px' }, focusPanel(), highlightsPanel()),
          el('div', { class: 'muted', style: 'margin-top:10px;font-size:12px' },
            ...(d.caveats || []).map((t) => el('div', {}, '· ' + t))));
      }).catch((e) => {
        host.replaceChildren(el('div', { class: 'empty-note bad' }, e.message));
      });
    },
  });
})();

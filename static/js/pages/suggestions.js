/* Quest Suggestions: the synced quest index, filterable, trackable. */
'use strict';

(() => {
  const F = { cls: '', race: '', level_min: '', level_max: '', q: '', hide_completed: false };

  Pages.register({
    id: 'suggestions',
    title: 'Quest Ideas',
    icon: '🗺',
    render(container) {
      const listBox = el('div', { class: 'panel-body' });
      const status = el('span', { class: 'muted' });
      const clsSel = el('select', {}, el('option', { value: '' }, 'Any class'));
      const raceSel = el('select', {}, el('option', { value: '' }, 'Any race'));

      const refresh = async () => {
        const params = {};
        for (const [k, v] of Object.entries(F)) if (v !== '' && v !== false) params[k] = v;
        let data;
        try { data = await API.get('/api/quests' + App.q(params)); }
        catch (e) { listBox.replaceChildren(el('div', { class: 'empty-note bad' }, e.message)); return; }
        status.textContent = data.quests.length + ' quests';
        if (clsSel.options.length === 1) {
          for (const c of data.classes) clsSel.append(el('option', { value: c }, c));
          for (const r of data.races) raceSel.append(el('option', { value: r }, r));
        }
        renderTable(listBox, {
          id: 'questidx',
          columns: [
            { key: 'name', label: 'Quest' },
            {
              key: 'classes', label: 'Classes',
              sortVal: (r) => (r.classes || []).join(','),
              render: (r) => (r.classes || []).join(', ') || null,
            },
            { key: 'start_zone', label: 'Zone' },
            {
              key: 'level_min', label: 'Level', num: true,
              render: (r) => r.level_min ? r.level_min + (r.level_max ? '-' + r.level_max : '+') : null,
            },
            { key: 'steps', label: 'Steps', num: true },
            {
              key: 'status', label: '',
              sortVal: (r) => r.status || '',
              render: (r) => {
                if (r.status === 'completed') return el('span', { class: 'good' }, 'done');
                if (r.status === 'tracked') return el('span', { class: 'warn' }, 'tracked');
                const b = el('button', { class: 'metal-btn', style: 'font-size:11px;padding:2px 8px' }, 'Track');
                b.addEventListener('click', async (ev) => {
                  ev.stopPropagation();
                  await API.post('/api/quests/' + r.id + '/status' + App.q(), { status: 'tracked' });
                  refresh();
                });
                return b;
              },
            },
          ],
          rows: data.quests,
          defaultSort: { key: 'name', dir: 1 },
          empty: 'No quests in the local database yet - run a Data Sync first.',
          onRow: (r, tr) => {
            tr.style.cursor = 'pointer';
            tr.title = 'open on EQLWiki';
            tr.addEventListener('click', () => window.open(r.wiki_url, '_blank'));
          },
        });
      };

      clsSel.addEventListener('change', () => { F.cls = clsSel.value; refresh(); });
      raceSel.addEventListener('change', () => { F.race = raceSel.value; refresh(); });
      const lmin = el('input', { type: 'number', placeholder: 'min lvl', style: 'width:72px' });
      const lmax = el('input', { type: 'number', placeholder: 'max lvl', style: 'width:72px' });
      lmin.addEventListener('change', () => { F.level_min = lmin.value; refresh(); });
      lmax.addEventListener('change', () => { F.level_max = lmax.value; refresh(); });
      const search = el('input', { type: 'search', placeholder: 'Search quests...' });
      let t = null;
      search.addEventListener('input', () => {
        clearTimeout(t);
        t = setTimeout(() => { F.q = search.value; refresh(); }, 250);
      });
      const hideCb = el('input', { type: 'checkbox' });
      hideCb.addEventListener('change', () => { F.hide_completed = hideCb.checked; refresh(); });

      container.append(
        el('h1', { class: 'page-title' }, 'Quest Suggestions'),
        el('div', { class: 'row', style: 'align-items:center;margin-bottom:10px' },
          clsSel, raceSel, lmin, lmax, search,
          el('label', { style: 'display:flex;align-items:center;gap:5px' }, hideCb, 'hide completed'),
          el('span', { class: 'grow' }), status),
        el('div', { class: 'panel' }, listBox));
      refresh();
    },
  });
})();

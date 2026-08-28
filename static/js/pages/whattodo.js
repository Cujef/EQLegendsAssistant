/* What to do?: quests your inventory unlocks + leveling suggestions. */
'use strict';

(() => {
  Pages.register({
    id: 'whattodo',
    title: 'What to do?',
    icon: '❓',
    render(container) {
      container.append(el('h1', { class: 'page-title' }, 'What to do?'));
      const host = el('div', {});
      container.append(host);
      API.get('/api/whattodo' + App.q()).then((d) => {
        const qBody = el('div', { class: 'panel-body' });
        renderTable(qBody, {
          id: 'wtd.quests',
          columns: [
            { key: 'name', label: 'Quest' },
            { key: 'matched_items', label: 'You have' },
            { key: 'start_zone', label: 'Zone' },
            {
              key: 'level_min', label: 'Level', num: true,
              render: (r) => r.level_min ? r.level_min + (r.level_max ? '-' + r.level_max : '+') : null,
            },
            {
              key: 'status', label: '',
              render: (r) => {
                if (r.status === 'completed') return el('span', { class: 'good' }, 'done');
                if (r.status === 'tracked') return el('span', { class: 'warn' }, 'tracked');
                const b = el('button', { class: 'metal-btn', style: 'font-size:11px;padding:2px 8px' }, 'Track');
                b.addEventListener('click', async (ev) => {
                  ev.stopPropagation();
                  await API.post('/api/quests/' + r.id + '/status' + App.q(), { status: 'tracked' });
                  b.replaceWith(el('span', { class: 'warn' }, 'tracked'));
                });
                return b;
              },
            },
          ],
          rows: d.quest_matches,
          defaultSort: { key: 'name', dir: 1 },
          empty: 'No quest-item matches. Import inventory and run a Data Sync first.',
          onRow: (r, tr) => {
            tr.style.cursor = 'pointer';
            tr.addEventListener('click', () => window.open(r.wiki_url, '_blank'));
          },
        });

        const lv = d.leveling || {};
        const zemBody = el('div', { class: 'panel-body' });
        renderTable(zemBody, {
          id: 'wtd.zem',
          columns: [
            { key: 'zone', label: 'Zone' },
            {
              key: 'level_min', label: 'Levels', num: true,
              render: (r) => (r.level_min ?? '?') + '-' + (r.level_max ?? '?'),
            },
            { key: 'zem', label: 'ZEM', num: true },
          ],
          rows: lv.zem_rows || [],
          defaultSort: { key: 'zem', dir: -1 },
          empty: lv.level
            ? 'ZEM guide not synced yet - run a Data Sync.'
            : 'Import your log first so your level is known, then run a Data Sync.',
        });

        host.replaceChildren(
          el('div', { class: 'panel', style: 'margin-bottom:12px' },
            el('h2', {}, 'Quests your items unlock'), qBody),
          el('div', { class: 'panel' },
            el('h2', {}, 'Where to hunt' + (lv.level ? ' (level ' + lv.level + ')' : '')), zemBody));
      }).catch((e) => {
        host.replaceChildren(el('div', { class: 'empty-note bad' }, e.message));
      });
    },
  });
})();

/* Tradeskills: current levels from log skill-ups, guide links, craftables. */
'use strict';

(() => {
  Pages.register({
    id: 'tradeskills',
    title: 'Tradeskills',
    icon: '⚒',
    render(container) {
      container.append(el('h1', { class: 'page-title' }, 'Tradeskills'));
      const host = el('div', {});
      container.append(host);
      API.get('/api/tradeskills' + App.q()).then((d) => {
        const tsBody = el('div', { class: 'panel-body' });
        renderTable(tsBody, {
          id: 'ts.main',
          columns: [
            { key: 'skill', label: 'Tradeskill' },
            {
              key: 'level', label: 'Skill', num: true,
              render: (r) => r.level === null
                ? el('span', { class: 'faint', title: 'no skill-up lines in the log yet' }, 'unknown')
                : String(r.level),
            },
            {
              key: 'last_ts', label: 'Last skill-up', num: true,
              render: (r) => r.last_ts ? new Date(r.last_ts * 1000).toLocaleDateString() : null,
            },
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
          rows: d.tradeskills,
          defaultSort: { key: 'level', dir: -1 },
        });

        const otherBody = el('div', { class: 'panel-body' });
        renderTable(otherBody, {
          id: 'ts.other',
          columns: [
            { key: 'skill', label: 'Skill' },
            { key: 'level', label: 'Level', num: true },
            {
              key: 'last_ts', label: 'Last skill-up', num: true,
              render: (r) => r.last_ts ? new Date(r.last_ts * 1000).toLocaleDateString() : null,
            },
          ],
          rows: d.other_skills,
          defaultSort: { key: 'level', dir: -1 },
          empty: 'No skill-ups found yet - import your log on the Inventory page.',
        });

        host.replaceChildren(
          el('div', { class: 'muted', style: 'margin-bottom:10px' },
            'Levels come from "You have become better at X!" log lines - a skill you have not raised since logging began shows as unknown.'),
          el('div', { class: 'panel', style: 'margin-bottom:12px' }, el('h2', {}, 'Tradeskills'), tsBody),
          el('div', { class: 'panel' }, el('h2', {}, 'All other skills seen in the log'), otherBody));
      }).catch((e) => {
        host.replaceChildren(el('div', { class: 'empty-note bad' }, e.message));
      });
    },
  });
})();

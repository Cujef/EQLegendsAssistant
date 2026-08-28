/* Quest Progress: tracked quests with per-step checklists. */
'use strict';

(() => {
  let detailBox = null;

  async function openDetail(questId, refresh) {
    const d = await API.get(`/api/quests/${questId}` + App.q());
    const steps = el('div', { style: 'max-height:320px;overflow:auto' });
    const renderSteps = () => {
      steps.replaceChildren(...d.steps.map((s) => {
        const cb = el('input', { type: 'checkbox' });
        cb.checked = !!s.done;
        cb.addEventListener('change', async () => {
          const r = await API.post(`/api/quests/${questId}/steps/${s.step_index}/toggle` + App.q());
          s.done = r.done ? 1 : 0;
          if (refresh) refresh();
        });
        return el('label', { style: 'display:flex;gap:8px;padding:3px 0;align-items:flex-start;cursor:pointer' },
          cb, el('span', { class: s.done ? 'faint' : '', style: s.done ? 'text-decoration:line-through' : '' }, s.text));
      }));
      if (!d.steps.length) steps.append(el('div', { class: 'empty-note' }, 'No parsed steps — use the wiki link.'));
    };
    renderSteps();
    const btn = (label, status, cls) => {
      const b = el('button', { class: 'metal-btn ' + (cls || '') }, label);
      b.addEventListener('click', async () => {
        await API.post(`/api/quests/${questId}/status` + App.q(), { status });
        if (refresh) refresh();
        detailBox.replaceChildren();
      });
      return b;
    };
    detailBox.replaceChildren(el('div', { class: 'panel' },
      el('h2', {}, d.name),
      el('div', { class: 'panel-body' },
        el('div', { class: 'muted', style: 'margin-bottom:8px' },
          `${d.start_zone || '?'} · ${d.quest_giver || '?'} · level ${d.level_min ?? '?'}${d.level_max ? '-' + d.level_max : '+'} · `,
          el('a', { href: d.wiki_url, target: '_blank', rel: 'noopener' }, 'open on EQLWiki ↗')),
        steps,
        el('div', { class: 'row', style: 'margin-top:10px' },
          btn('Mark completed', 'completed', 'primary'), btn('Untrack', 'untracked')))));
    detailBox.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }

  Pages.register({
    id: 'quests',
    title: 'Quest Progress',
    icon: '📜',
    render(container) {
      const listBox = el('div', { class: 'panel' },
        el('h2', {}, 'Tracked quests'), el('div', { class: 'panel-body q-list' }));
      detailBox = el('div', { style: 'margin-top:12px' });
      container.append(
        el('h1', { class: 'page-title' }, 'Quest Progress'),
        listBox, detailBox);

      const refresh = async () => {
        let data;
        try { data = await API.get('/api/quest-progress' + App.q()); }
        catch (e) {
          listBox.querySelector('.q-list').replaceChildren(el('div', { class: 'empty-note bad' }, e.message));
          return;
        }
        renderTable(listBox.querySelector('.q-list'), {
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
          rows: data.quests,
          defaultSort: { key: 'status', dir: 1 },
          empty: 'Nothing tracked. Add quests from the Quest Suggestions page (after a Data Sync).',
          onRow: (r, tr) => {
            tr.style.cursor = 'pointer';
            tr.addEventListener('click', () => openDetail(r.id, refresh));
          },
        });
      };
      refresh();
    },
  });
})();

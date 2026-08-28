/* Quest Progress page — M7: tracked quests with per-step checklists.
   Data: GET /api/quest-progress?char=, POST /api/quests/{id}/... */
'use strict';

Pages.register({
  id: 'quests',
  title: 'Quest Progress',
  icon: '📜',
  render(container) {
    container.append(
      el('h1', { class: 'page-title' }, 'Quest Progress'),
      el('div', { class: 'empty-note' },
        'Quest tracking arrives in milestone M7 (after the wiki sync in M5).'));
  },
});

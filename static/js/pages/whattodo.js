/* What to do? page — M10: quests unlocked by inventory items + leveling ideas.
   Data: GET /api/whattodo?char= */
'use strict';

Pages.register({
  id: 'whattodo',
  title: 'What to do?',
  icon: '❓',
  render(container) {
    container.append(
      el('h1', { class: 'page-title' }, 'What to do?'),
      el('div', { class: 'empty-note' },
        'Inventory-driven quest matches and leveling suggestions arrive in milestone M10.'));
  },
});

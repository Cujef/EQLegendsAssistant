/* Quest Suggestions page — M7: full quest index, filter by class/race/level/completed.
   Data: GET /api/quests?class=&race=&... */
'use strict';

Pages.register({
  id: 'suggestions',
  title: 'Quest Ideas',
  icon: '🗺',
  render(container) {
    container.append(
      el('h1', { class: 'page-title' }, 'Quest Suggestions'),
      el('div', { class: 'empty-note' },
        'The quest index arrives in milestone M7 (after the wiki sync in M5).'));
  },
});

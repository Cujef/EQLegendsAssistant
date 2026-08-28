/* Overview page — M8 fills this in: computed stats vs caps, AA earned/spent,
   haste %, best focus per family, log highlights. Data: GET /api/overview?char= */
'use strict';

Pages.register({
  id: 'overview',
  title: 'Overview',
  icon: '⚔',
  render(container) {
    container.append(
      el('h1', { class: 'page-title' }, 'Overview'),
      el('div', { class: 'empty-note' },
        'Character overview arrives in milestone M8 — stats, caps, AA, haste, focus effects, and log highlights.'));
  },
});

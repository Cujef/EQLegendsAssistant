/* Exaltations page — M9: socketed effects, open sockets, movable candidates.
   Data: GET /api/exaltations?char= */
'use strict';

Pages.register({
  id: 'exaltations',
  title: 'Exaltations',
  icon: '💠',
  render(container) {
    container.append(
      el('h1', { class: 'page-title' }, 'Exaltations'),
      el('div', { class: 'empty-note' },
        'Exaltation matching arrives in milestone M9 (after inventory + item sync).'));
  },
});

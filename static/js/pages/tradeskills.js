/* Tradeskills page — M10: current levels from the log, wiki guides, craftables.
   Data: GET /api/tradeskills?char= */
'use strict';

Pages.register({
  id: 'tradeskills',
  title: 'Tradeskills',
  icon: '⚒',
  render(container) {
    container.append(
      el('h1', { class: 'page-title' }, 'Tradeskills'),
      el('div', { class: 'empty-note' },
        'Tradeskill overview arrives in milestone M10 (after the log scan in M3).'));
  },
});

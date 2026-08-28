/* Parser page — M4: compact live combat tiles (drag/resize/lock via tiles.js).
   Data: the 1 Hz WS snapshot's `live` object + GET /api/fights. */
'use strict';

Pages.register({
  id: 'parser',
  title: 'Parser',
  icon: '📊',
  render(container) {
    container.append(
      el('h1', { class: 'page-title' }, 'Parser'),
      el('div', { class: 'empty-note' },
        'Live combat tiles arrive in milestone M4.'));
  },
});

/* Data Sync page — M5/M6: start/cancel wiki + tools-site syncs, progress,
   unparsed report. Data: POST /api/sync/start, WS snapshot `sync` object. */
'use strict';

Pages.register({
  id: 'sync',
  title: 'Data Sync',
  icon: '⟳',
  render(container) {
    container.append(
      el('h1', { class: 'page-title' }, 'Data Sync'),
      el('div', { class: 'empty-note' },
        'eqlwiki + eqlegendstools sync controls arrive in milestones M5–M6.'));
  },
});

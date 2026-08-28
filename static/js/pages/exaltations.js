/* Exaltations: owned focus/proc/worn/click effects, sockets, move candidates. */
'use strict';

(() => {
  function effCell(effs) {
    if (!effs || !effs.length) return el('span', { class: 'faint' }, 'unknown effect');
    return el('span', {}, effs.map((e, i) =>
      el('span', {}, i ? ' · ' : '', e.effect_name,
        el('span', { class: 'faint' }, ' (' + e.effect_type + ')'))));
  }

  function candCell(entry) {
    if (!entry.candidate_count) return el('span', { class: 'faint' }, 'none');
    const s = el('details', {},
      el('summary', { style: 'cursor:pointer' }, entry.candidate_count + ' possible'),
      el('div', { style: 'padding:4px 0 0 12px' },
        ...entry.candidates.map((c) => el('div', { class: c.host_equipped ? '' : 'muted', style: 'font-size:12px' },
          (c.host_equipped ? '● ' : '○ ') + c.host_item + ' — ' + c.location))));
    return s;
  }

  Pages.register({
    id: 'exaltations',
    title: 'Exaltations',
    icon: '💠',
    render(container) {
      container.append(el('h1', { class: 'page-title' }, 'Exaltations'));
      const host = el('div', {});
      container.append(host);
      API.get('/api/exaltations' + App.q()).then((d) => {
        if (!d.snapshot) {
          host.replaceChildren(el('div', { class: 'empty-note' },
            'Import your inventory first (Inventory page).'));
          return;
        }
        const cols = (extra) => [
          { key: 'item', label: 'Exaltation item' },
          { key: 'effects', label: 'Effect', sortVal: (r) => (r.effects[0] || {}).effect_name || '', render: (r) => effCell(r.effects) },
          ...extra,
          { key: 'candidates', label: 'Could move to', sortVal: (r) => r.candidate_count, render: candCell },
        ];
        const mkPanel = (title, rows, extraCols, tableId, emptyMsg) => {
          const body = el('div', { class: 'panel-body' });
          renderTable(body, { id: tableId, columns: cols(extraCols), rows, defaultSort: null, empty: emptyMsg });
          return el('div', { class: 'panel', style: 'margin-bottom:12px' }, el('h2', {}, title), body);
        };

        const socketsBody = el('div', { class: 'panel-body' });
        renderTable(socketsBody, {
          id: 'ex.sockets',
          columns: [
            { key: 'host_item', label: 'Item with open socket' },
            { key: 'location', label: 'Socket' },
            {
              key: 'host_equipped', label: 'Worn', num: true,
              render: (r) => r.host_equipped ? el('span', { class: 'good' }, 'yes') : el('span', { class: 'faint' }, 'no'),
            },
          ],
          rows: d.open_sockets, defaultSort: { key: 'host_equipped', dir: -1 },
          empty: 'No open sockets.',
        });

        const fxBody = el('div', { class: 'panel-body' });
        renderTable(fxBody, {
          id: 'ex.all',
          columns: [
            { key: 'effect_type', label: 'Type' },
            { key: 'effect_name', label: 'Effect' },
            { key: 'description', label: 'Description' },
          ],
          rows: d.all_effects, defaultSort: { key: 'effect_type', dir: 1 },
          empty: 'Effect reference is empty - run a Data Sync.',
        });

        host.replaceChildren(
          el('div', { class: 'muted', style: 'margin-bottom:10px' },
            '⚠ Move suggestions use assumed compatibility rules (open Slot7-10 socket; procs prefer weapons) - the game\'s real transfer rules are not fully documented.'),
          mkPanel('Socketed (in your gear)', d.socketed,
            [{ key: 'host_item', label: 'Socketed in' },
             { key: 'host_equipped', label: 'Worn', num: true, render: (r) => r.host_equipped ? el('span', { class: 'good' }, 'yes') : el('span', { class: 'faint' }, 'no') }],
            'ex.sock', 'No socketed exaltations found.'),
          mkPanel('Loose (Augmentation / Activated lists)', d.loose,
            [{ key: 'where', label: 'Where' }],
            'ex.loose', 'No loose exaltations.'),
          el('div', { class: 'row' },
            el('div', { class: 'panel grow', style: 'min-width:320px' }, el('h2', {}, 'Open sockets'), socketsBody),
            el('div', { class: 'panel grow', style: 'min-width:320px' }, el('h2', {}, 'All known effects'), fxBody)),
          d.unknown.length ? el('div', { class: 'panel', style: 'margin-top:12px' },
            el('h2', {}, 'Unknown exaltations (' + d.unknown.length + ')'),
            el('div', { class: 'panel-body muted' },
              'These items are not in the item DB yet (run a Data Sync): ',
              d.unknown.map((u) => u.item).join(', '))) : null);
      }).catch((e) => {
        host.replaceChildren(el('div', { class: 'empty-note bad' }, e.message));
      });
    },
  });
})();

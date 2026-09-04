/* First-open suggestion box: what to feed the app so it becomes YOUR
   assistant — inventory dump, log file, community data sync.

   Renders into #suggest (between the title bar and the shell) from the
   `readiness` object the server puts on GET /api/characters and on every 1 Hz
   snapshot. Re-renders only when that signature changes, so the 1 Hz push does
   not flicker it. ✕ remembers the dismissal per browser; when every row is
   satisfied the box goes away on its own. */
'use strict';

const SUGGEST_CSS = `
#suggest .sg-card { display:flex; align-items:stretch; margin:8px 12px 0;
  border:1px solid var(--edge-strong);
  background:
    repeating-linear-gradient(90deg, transparent 0 2px, var(--brush-line) 2px 3px),
    linear-gradient(180deg, var(--panel-hi), var(--panel-lo));
  box-shadow: inset 1px 1px 0 var(--bevel-hi), inset -1px -1px 0 var(--bevel-lo),
    0 2px 6px var(--shadow); }
#suggest .sg-head { flex:none; width:176px; padding:10px 12px; border-right:1px solid var(--edge);
  border-left:3px solid var(--accent); }
#suggest .sg-title { font:800 12px var(--font-display); letter-spacing:0.16em;
  text-transform:uppercase; color:var(--accent); }
#suggest .sg-sub { font-size:11px; color:var(--text-dim); margin-top:4px; line-height:1.45; }
#suggest .sg-items { flex:1; display:grid; grid-template-columns:repeat(auto-fit, minmax(230px, 1fr)); }
#suggest .sg-item { display:flex; flex-direction:column; gap:3px; padding:9px 12px;
  border-right:1px solid var(--edge); min-width:0; }
#suggest .sg-item .t { font:700 12px var(--font-body); color:var(--text); }
#suggest .sg-item.done .t { color:var(--text-dim); }
#suggest .sg-item .s { font-size:11px; color:var(--text-faint); }
#suggest .sg-item .s.good { color:var(--good); }
#suggest .sg-item .metal-btn { align-self:flex-start; font-size:12px; padding:3px 9px; margin-top:3px; }
#suggest .sg-x { flex:none; align-self:flex-start; margin:6px; padding:2px 7px; }
`;

const Suggest = (() => {
  const KEY = 'eqa.suggest.dismissed.v1';
  let host = null;
  let sig = '';
  let dismissed = false;
  let last;

  function init(readiness) {
    host = document.getElementById('suggest');
    if (!host) return;
    if (!document.getElementById('suggest-css')) {
      const st = document.createElement('style');
      st.id = 'suggest-css';
      st.textContent = SUGGEST_CSS;
      document.head.append(st);
    }
    try { dismissed = localStorage.getItem(KEY) === '1'; } catch (e) { dismissed = false; }
    window.addEventListener('snapshot', (ev) => {
      update(ev.detail ? ev.detail.readiness : undefined);
    });
    update(readiness);
  }

  /* readiness: {inventory_imported_at, log_path_set, log_lines_parsed, items_in_db}
     or null (no active character). undefined = not known yet, keep what we have. */
  function update(readiness) {
    if (!host || readiness === undefined) return;
    last = readiness;
    const s = JSON.stringify([dismissed, App.active ? App.active.id : null, readiness]);
    if (s === sig) return;
    sig = s;
    render(readiness);
  }

  function dismiss() {
    dismissed = true;
    try { localStorage.setItem(KEY, '1'); } catch (e) { /* private mode */ }
    update(last);
  }

  function syncPageId() {
    const d = Pages.byId('sync') || Pages.defs.find((p) => /sync/i.test(p.id));
    return d ? d.id : null;
  }

  function items(r) {
    r = r || {};
    const who = App.active ? App.active.name : 'your character';
    const inv = r.inventory_imported_at;
    const lines = r.log_lines_parsed || 0;
    return [
      {
        ok: !!inv,
        title: `Import ${who}'s inventory`,
        status: inv ? 'imported ' + new Date(inv * 1000).toLocaleString()
                    : 'not imported yet — type /outputfile inventory in game and the app picks the file up '
                      + 'by itself, or import one by hand',
        action: 'Import Inventory…',
        run: () => ImportInventory.open({}),
      },
      {
        ok: !!r.log_path_set,
        title: 'Point the app at your log file',
        status: r.log_path_set
          ? (lines ? `reading it — ${fmt(lines)} lines so far` : 'log file set — reading…')
          : 'no log file set — the parser, AA, skills, tradeskills and factions all come from it (/log on in game)',
        action: 'Characters…',
        run: () => Setup.open({}),
      },
      {
        ok: (r.items_in_db || 0) > 0,
        title: 'Sync the community item & quest data',
        status: (r.items_in_db || 0) > 0
          ? `${fmt(r.items_in_db)} items in the local database`
          : 'never synced — item stats, quests and effects need one run',
        action: 'Data Sync',
        run: () => { const id = syncPageId(); if (id) location.hash = '#/' + id; },
      },
    ];
  }

  function render(r) {
    host.replaceChildren();
    if (dismissed) return;
    const rows = items(r);
    if (rows.every((x) => x.ok)) return;       // nothing left to suggest
    const list = el('div', { class: 'sg-items' });
    for (const x of rows) {
      const item = el('div', { class: 'sg-item' + (x.ok ? ' done' : '') },
        el('span', { class: 't' }, (x.ok ? '✓ ' : '') + x.title),
        el('span', { class: 's' + (x.ok ? ' good' : '') }, x.status));
      if (!x.ok) {
        const b = el('button', { class: 'metal-btn primary' }, x.action);
        b.addEventListener('click', x.run);
        item.append(b);
      }
      list.append(item);
    }
    const x = el('button', { class: 'metal-btn sg-x', title: 'Hide these suggestions' }, '✕');
    x.addEventListener('click', dismiss);
    host.append(el('div', { class: 'sg-card' },
      el('div', { class: 'sg-head' },
        el('div', { class: 'sg-title' }, 'Make it yours'),
        el('div', { class: 'sg-sub' },
          'The Assistant is only as good as what it reads. Feed it these and every page fills in.')),
      list, x));
  }

  return { init, update, dismiss };
})();

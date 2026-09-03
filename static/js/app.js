/* Bootstrap: theme toggle, character selector, sidebar, WS, initial route. */
'use strict';

function initTheme() {
  const btn = document.getElementById('theme-toggle');
  btn.addEventListener('click', () => {
    const root = document.documentElement;
    const next = root.dataset.theme === 'light' ? 'dark' : 'light';
    root.dataset.theme = next;
    try { localStorage.setItem('eqa.theme.v1', next); } catch (e) {}
  });
}

function renderCharSelect() {
  const host = document.getElementById('char-select');
  if (!App.characters.length) { host.replaceChildren(); return; }
  const sel = el('select', {});
  for (const c of App.characters) {
    const o = el('option', { value: c.id }, `${c.name} (${c.server})`);
    if (App.active && c.id === App.active.id) o.selected = true;
    sel.append(o);
  }
  sel.addEventListener('change', async () => {
    await API.post(`/api/characters/${sel.value}/select`);
    navigate();  // re-render current page for the new character
  });
  host.replaceChildren(sel);
}

let _charsRendered = '';
window.addEventListener('snapshot', () => {
  // re-render the selector only when the character list/active actually changes
  const sig = JSON.stringify([App.characters.map((c) => c.id), App.charId()]);
  if (sig !== _charsRendered) { _charsRendered = sig; renderCharSelect(); }
});

document.addEventListener('DOMContentLoaded', async () => {
  initTheme();
  buildSidebar();
  document.getElementById('chars-btn')
    .addEventListener('click', () => Setup.open({}));
  // characters must be known before the first page render (pages read
  // App.active for their ?char= param and titles)
  let needsSetup = false;
  let readiness;
  try {
    const d = await API.get('/api/characters');
    App.characters = d.characters || [];
    App.active = d.active || null;
    needsSetup = !!d.needs_setup;
    readiness = d.readiness;
    renderCharSelect();
  } catch (e) { /* server will still push via WS */ }
  navigate();
  connectWS();
  // the suggestion box: what to feed the app next (inventory, log, sync) —
  // sits above the pages and follows the 1 Hz readiness on the snapshot
  Suggest.init(readiness);
  // nothing to show yet — a fresh install lands in the wizard, not an empty app
  if (needsSetup) Setup.open({ firstRun: true });
});

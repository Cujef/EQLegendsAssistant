/* Hash router + page registry (TILE_DEFS-style registry, but for pages).

   Pages.register({
     id: 'overview',            // route: #/overview
     title: 'Overview',
     icon: '⚔',
     render(container) {},      // called on navigation; container is #content
     onSnapshot?(snap) {},      // called on every 1 Hz push while the page is visible
     onLeave?() {},
   })
   Registration order = sidebar order. */
'use strict';

const Pages = {
  defs: [],
  current: null,
  register(def) { Pages.defs.push(def); },
  byId(id) { return Pages.defs.find((d) => d.id === id); },
};

function buildSidebar() {
  const nav = document.getElementById('sidebar');
  nav.replaceChildren();
  for (const d of Pages.defs) {
    const item = el('div', { class: 'nav-item', 'data-page': d.id },
      el('span', { class: 'ico' }, d.icon || '•'),
      el('span', {}, d.title));
    item.addEventListener('click', () => { location.hash = '#/' + d.id; });
    nav.append(item);
  }
}

function navigate() {
  const id = (location.hash || '').replace(/^#\/?/, '') || Pages.defs[0].id;
  const def = Pages.byId(id) || Pages.defs[0];
  if (Pages.current && Pages.current.onLeave) {
    try { Pages.current.onLeave(); } catch (e) { console.error(e); }
  }
  Pages.current = def;
  for (const n of document.querySelectorAll('#sidebar .nav-item')) {
    n.classList.toggle('active', n.dataset.page === def.id);
  }
  const content = document.getElementById('content');
  content.replaceChildren();
  try {
    def.render(content);
  } catch (e) {
    console.error(e);
    content.replaceChildren(el('div', { class: 'empty-note bad' }, 'Page error: ' + e.message));
  }
}

window.addEventListener('hashchange', navigate);
window.addEventListener('snapshot', (ev) => {
  if (Pages.current && Pages.current.onSnapshot) {
    try { Pages.current.onSnapshot(ev.detail); } catch (e) { console.error(e); }
  }
});

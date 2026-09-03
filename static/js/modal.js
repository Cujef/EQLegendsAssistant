/* Shared modal chrome — the one dialog frame every overlay in the app uses
   (first-run setup / Characters, Import Inventory).

   Modal.create({ title, closable = true, onClose })
     -> { backdrop, body, titleEl, closeBtn,
          open(), close(force), setTitle(t), setClosable(b), onClose, isOpen }

   Loaded right after api.js and before setup.js: a brand-new install must be
   able to reach the setup dialog before any page has data to render, so this
   file has no dependencies beyond el() and injects its own CSS once. The
   `.su-*` class names predate the split (they were setup.js's) and are kept so
   nothing else had to move. Escape closes the topmost open dialog; a click on
   the backdrop closes that dialog. Zero rounded corners, same bevels as .panel. */
'use strict';

const MODAL_CSS = `
.su-backdrop { position:fixed; inset:0; z-index:100; display:none;
  background:rgba(0,0,0,0.55); }
.su-backdrop.open { display:flex; align-items:flex-start; justify-content:center;
  overflow:auto; padding:40px 16px; }
.su-modal { width:min(760px, 100%); border:1px solid var(--edge-strong);
  background:
    repeating-linear-gradient(90deg, transparent 0 2px, var(--brush-line) 2px 3px),
    linear-gradient(180deg, var(--panel-hi), var(--panel-lo));
  box-shadow: inset 1px 1px 0 var(--bevel-hi), inset -1px -1px 0 var(--bevel-lo),
    0 10px 40px rgba(0,0,0,0.6); }
.su-hdr { display:flex; align-items:center; gap:10px; padding:10px 14px;
  border-bottom:2px solid var(--edge-strong);
  background:linear-gradient(180deg, var(--panel-hi), var(--panel-flat)); }
.su-hdr h2 { margin:0; flex:1; font:800 13px var(--font-display);
  letter-spacing:0.18em; text-transform:uppercase; color:var(--accent); }
.su-body { padding:14px; }
.su-lead { color:var(--text-dim); font-size:13px; margin-bottom:14px; line-height:1.6; }
.su-lead code, .su-callout code { font-family:var(--font-mono); color:var(--text);
  background:var(--bg-alt); padding:0 4px; border:1px solid var(--edge); }
.su-callout { margin:0 0 14px; padding:10px 12px; font-size:13px; line-height:1.6;
  color:var(--text); border:1px solid var(--edge-strong); border-left:3px solid var(--accent);
  background:linear-gradient(180deg, var(--panel-hi), var(--panel-lo)); }
.su-sec { margin-bottom:16px; border:1px solid var(--edge); }
.su-sec > h3 { margin:0; padding:5px 10px; font:700 10px var(--font-display);
  letter-spacing:0.14em; text-transform:uppercase; color:var(--text-dim);
  border-bottom:1px solid var(--edge);
  background:linear-gradient(180deg, var(--panel-hi), var(--panel-flat)); }
.su-sec > div { padding:10px; }
.su-row { display:flex; gap:8px; align-items:center; flex-wrap:wrap; }
.su-row input[type=text] { flex:1; min-width:220px; }
.su-cand { display:flex; align-items:center; gap:10px; padding:7px 8px;
  border:1px solid var(--edge); margin-bottom:6px;
  background:linear-gradient(180deg, var(--panel-hi), var(--panel-lo)); }
.su-cand .nm { font:700 13px var(--font-body); color:var(--text); }
.su-cand .meta { flex:1; font-size:11px; color:var(--text-dim); }
.su-cand .meta b { color:var(--text); font-weight:600; }
.su-grid { display:grid; grid-template-columns:repeat(auto-fit, minmax(200px, 1fr));
  gap:8px; }
.su-note { font-size:11px; color:var(--text-faint); margin-top:8px; line-height:1.5; }
.su-msg { margin-top:10px; font-size:12px; min-height:16px; }
.su-label { display:block; font:600 10px var(--font-display); letter-spacing:0.1em;
  text-transform:uppercase; color:var(--text-faint); margin-bottom:3px; }
.su-chip { display:inline-block; padding:1px 7px; font:600 10px var(--font-display);
  letter-spacing:0.08em; text-transform:uppercase; border:1px solid var(--edge-strong);
  color:var(--text-dim); vertical-align:middle; }
.su-chip.good { color:var(--good); border-color:var(--good); }
.su-chip.warn { color:var(--warn); border-color:var(--warn); }
.su-check { display:flex; align-items:center; gap:6px; font-size:12px; color:var(--text-dim);
  cursor:pointer; user-select:none; }
`;

const Modal = (() => {
  const stack = [];          // open dialogs, topmost last

  function ensureCss() {
    if (document.getElementById('modal-css')) return;
    const st = document.createElement('style');
    st.id = 'modal-css';
    st.textContent = MODAL_CSS;
    document.head.append(st);
  }

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && stack.length) stack[stack.length - 1].close();
  });

  function create(opts) {
    ensureCss();
    opts = opts || {};
    let onClose = opts.onClose || null;
    let closable = opts.closable !== false;

    const body = el('div', { class: 'su-body' });
    const titleEl = el('h2', {}, opts.title || '');
    const closeBtn = el('button', { class: 'metal-btn', title: 'Close' }, '✕');
    const backdrop = el('div', { class: 'su-backdrop' },
      el('div', { class: 'su-modal' },
        el('div', { class: 'su-hdr' }, titleEl, closeBtn),
        body));

    const api = {
      backdrop, body, titleEl, closeBtn,
      open() {
        backdrop.style.zIndex = String(100 + stack.length);
        backdrop.classList.add('open');
        if (!stack.includes(api)) stack.push(api);
        return api;
      },
      close(force) {
        if (!closable && !force) return false;
        if (!backdrop.classList.contains('open')) return true;
        backdrop.classList.remove('open');
        const i = stack.indexOf(api);
        if (i >= 0) stack.splice(i, 1);
        if (onClose) onClose();
        return true;
      },
      setTitle(t) { titleEl.textContent = t; },
      setClosable(b) { closable = !!b; closeBtn.style.display = closable ? '' : 'none'; },
      get onClose() { return onClose; },
      set onClose(f) { onClose = f || null; },
      get isOpen() { return backdrop.classList.contains('open'); },
    };
    closeBtn.addEventListener('click', () => api.close());
    backdrop.addEventListener('click', (e) => { if (e.target === backdrop) api.close(); });
    document.body.append(backdrop);
    api.setClosable(closable);
    return api;
  }

  return { create };
})();

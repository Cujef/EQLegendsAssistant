/* First-run setup + character manager.

   Opens automatically when the server reports `needs_setup` (no character, or
   an active character with neither a log nor an inventory dump), and on demand
   from the title bar. Everything here is self-contained: its own CSS, its own
   modal, no page registration — a brand-new install must be able to reach it
   before any page has data to render.

   Why a folder path and not a file picker for the log: the browser's picker
   hands back file CONTENT, not a path, and the log is ~100 MB and is tailed
   continuously — the server has to open it itself. The inventory dump is small
   and read once, so that one DOES accept a picked file. */
'use strict';

const SETUP_CSS = `
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
`;

const Setup = (() => {
  let backdrop = null, bodyEl = null, titleEl = null, closeBtn = null;
  let lastScan = null;
  let onDone = null;

  function ensureDom() {
    if (backdrop) return;
    const st = document.createElement('style');
    st.id = 'setup-css';
    st.textContent = SETUP_CSS;
    document.head.append(st);

    bodyEl = el('div', { class: 'su-body' });
    titleEl = el('h2', {}, 'Set up your character');
    closeBtn = el('button', { class: 'metal-btn' }, '✕');
    closeBtn.addEventListener('click', () => close());
    backdrop = el('div', { class: 'su-backdrop' },
      el('div', { class: 'su-modal' },
        el('div', { class: 'su-hdr' }, titleEl, closeBtn),
        bodyEl));
    backdrop.addEventListener('click', (e) => { if (e.target === backdrop) close(); });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && backdrop.classList.contains('open')) close();
    });
    document.body.append(backdrop);
  }

  function close() {
    if (!backdrop) return;
    backdrop.classList.remove('open');
    if (onDone) { const f = onDone; onDone = null; f(); }
  }

  async function open(opts) {
    ensureDom();
    opts = opts || {};
    onDone = opts.onDone || null;
    titleEl.textContent = opts.firstRun ? 'Welcome — set up your character' : 'Characters';
    closeBtn.style.display = opts.firstRun ? 'none' : '';   // first run needs a choice
    backdrop.classList.add('open');
    await render(opts);
  }

  // ── rendering ───────────────────────────────────────────────────────────
  async function render(opts) {
    opts = opts || {};
    bodyEl.replaceChildren(el('div', { class: 'su-lead' }, 'Loading…'));
    let chars = { characters: [], active: null };
    try { chars = await API.get('/api/characters'); } catch (e) { /* fresh install */ }
    if (!lastScan) {
      try { lastScan = await API.get('/api/setup/scan'); } catch (e) { lastScan = null; }
    }
    const msg = el('div', { class: 'su-msg muted' });

    const lead = opts.firstRun || !chars.characters.length
      ? el('div', { class: 'su-lead' },
        'Point the app at your EverQuest Legends folder and pick your character. ',
        'It reads your log and inventory files — it never writes to them or touches the game.')
      : el('div', { class: 'su-lead' },
        'Add another character, switch which one the app is showing, or re-point a file.');

    bodyEl.replaceChildren(lead,
      sectionScan(msg), sectionExisting(chars, msg), sectionManual(msg),
      sectionInventoryUpload(chars, msg), msg);

    // never trap someone in the wizard — they can look around and come back
    // via ＋ Characters in the title bar
    if (closeBtn.style.display === 'none') {
      const skip = el('button', { class: 'metal-btn', style: 'margin-top:4px' },
        'Skip for now');
      skip.addEventListener('click', () => {
        closeBtn.style.display = '';
        close();
      });
      bodyEl.append(el('div', { class: 'su-note' },
        'You can set this up later from ＋ Characters in the title bar.'), skip);
    }
  }

  function sectionScan(msg) {
    const dirInput = el('input', {
      type: 'text', value: (lastScan && lastScan.game_dir) || '',
      placeholder: 'e.g. J:\\EQLegends',
    });
    const results = el('div', {});
    const scanBtn = el('button', { class: 'metal-btn' }, 'Scan folder');

    const renderResults = () => {
      results.replaceChildren();
      if (!lastScan) {
        results.append(el('div', { class: 'faint' }, 'Enter your game folder and press Scan.'));
        return;
      }
      if (!lastScan.logs_dir_exists && !lastScan.game_dir_exists) {
        results.append(el('div', { class: 'bad' },
          'That folder does not exist. Enter the folder EverQuest Legends is installed in.'));
        return;
      }
      const cands = lastScan.candidates || [];
      if (!cands.length) {
        results.append(el('div', { class: 'warn' },
          'No characters found there. Check the path, or add one by hand below.'),
          el('div', { class: 'su-note' },
            'Looked for a _characters.ini and for Logs\\eqlog_<Name>_<server>.txt. ' +
            'If you have never enabled logging, type /log on in game first.'));
        return;
      }
      for (const c of cands) {
        const bits = [];
        bits.push(c.log_path
          ? el('span', {}, 'log ', el('b', {}, fmtMB(c.log_size)))
          : el('span', { class: 'warn' }, 'no log file'));
        bits.push(el('span', {}, ' · '));
        bits.push(c.inventory_path
          ? el('span', {}, 'inventory ', el('b', {}, 'found'))
          : el('span', { class: 'faint' }, 'no inventory dump'));
        const btn = el('button', { class: 'metal-btn' + (c.already_added ? '' : ' primary') },
          c.already_added ? 'Use this one' : 'Add character');
        btn.addEventListener('click', async () => {
          btn.disabled = true;
          try {
            await API.post('/api/characters', {
              name: c.name, server: c.server,
              log_path: c.log_path, inventory_path: c.inventory_path, activate: true,
            });
            if (c.inventory_path) {
              try { await API.post('/api/inventory/import' + App.q()); } catch (e) {}
            }
            msg.className = 'su-msg good';
            msg.textContent = `${c.name} added — reading the log now.`;
            lastScan = null;
            await afterChange();
          } catch (e) {
            msg.className = 'su-msg bad';
            msg.textContent = e.message;
            btn.disabled = false;
          }
        });
        results.append(el('div', { class: 'su-cand' },
          el('span', { class: 'nm' }, c.name),
          el('span', { class: 'meta' }, `(${c.server}) `, ...bits), btn));
      }
    };

    scanBtn.addEventListener('click', async () => {
      scanBtn.disabled = true;
      results.replaceChildren(el('div', { class: 'muted' }, 'Scanning…'));
      try {
        lastScan = await API.get('/api/setup/scan?dir=' + encodeURIComponent(dirInput.value));
      } catch (e) {
        lastScan = null;
        results.replaceChildren(el('div', { class: 'bad' }, e.message));
        scanBtn.disabled = false;
        return;
      }
      renderResults();
      scanBtn.disabled = false;
    });

    const sec = el('div', { class: 'su-sec' },
      el('h3', {}, '1 — Find your character'),
      el('div', {},
        el('div', { class: 'su-row', style: 'margin-bottom:10px' },
          el('span', { class: 'muted' }, 'Game folder'), dirInput, scanBtn),
        results,
        el('div', { class: 'su-note' },
          'Either the install folder or its Logs folder works.')));
    renderResults();
    return sec;
  }

  function sectionExisting(chars, msg) {
    const rows = el('div', {});
    if (!chars.characters.length) {
      rows.append(el('div', { class: 'faint' }, 'No characters yet.'));
    }
    for (const c of chars.characters) {
      const active = chars.active && chars.active.id === c.id;
      const use = el('button', { class: 'metal-btn' }, active ? '● active' : 'Use');
      use.disabled = !!active;
      use.addEventListener('click', async () => {
        await API.post(`/api/characters/${c.id}/select`);
        await afterChange();
      });
      const del = el('button', { class: 'metal-btn', title: 'Remove this character and its imported data' }, '🗑');
      del.addEventListener('click', async () => {
        if (!confirm(`Remove ${c.name} and all of its imported data?\n\n`
          + 'Your game files are not touched — only this app\'s copy.')) return;
        try {
          await API.del(`/api/characters/${c.id}`);
          msg.className = 'su-msg muted';
          msg.textContent = `${c.name} removed.`;
          await afterChange();
        } catch (e) {
          msg.className = 'su-msg bad';
          msg.textContent = e.message;
        }
      });
      rows.append(el('div', { class: 'su-cand' },
        el('span', { class: 'nm' }, c.name),
        el('span', { class: 'meta' }, `(${c.server}) `,
          c.log_path ? el('span', {}, 'log ✓') : el('span', { class: 'warn' }, 'no log'),
          ' · ',
          c.inventory_path ? el('span', {}, 'inventory ✓')
            : el('span', { class: 'faint' }, 'no inventory')),
        use, del));
    }
    return el('div', { class: 'su-sec' }, el('h3', {}, '2 — Your characters'),
      el('div', {}, rows));
  }

  function sectionManual(msg) {
    const name = el('input', { type: 'text', placeholder: 'Character name' });
    const server = el('input', { type: 'text', placeholder: 'Server (e.g. halas)' });
    const logp = el('input', { type: 'text', placeholder: 'Full path to eqlog_<Name>_<server>.txt' });
    const invp = el('input', { type: 'text', placeholder: 'Full path to <Name>_<server>-Inventory.txt (optional)' });
    const add = el('button', { class: 'metal-btn primary' }, 'Add character');
    add.addEventListener('click', async () => {
      add.disabled = true;
      try {
        await API.post('/api/characters', {
          name: name.value, server: server.value,
          log_path: logp.value, inventory_path: invp.value, activate: true,
        });
        msg.className = 'su-msg good';
        msg.textContent = `${name.value} added.`;
        lastScan = null;
        await afterChange();
      } catch (e) {
        msg.className = 'su-msg bad';
        msg.textContent = e.message;
        add.disabled = false;
      }
    });
    return el('div', { class: 'su-sec' },
      el('h3', {}, 'Or add one by hand'),
      el('div', {},
        el('div', { class: 'su-grid', style: 'margin-bottom:8px' },
          el('div', {}, el('span', { class: 'su-label' }, 'Name'), name),
          el('div', {}, el('span', { class: 'su-label' }, 'Server'), server)),
        el('div', { style: 'margin-bottom:8px' },
          el('span', { class: 'su-label' }, 'Log file'), logp),
        el('div', { style: 'margin-bottom:10px' },
          el('span', { class: 'su-label' }, 'Inventory file (optional)'), invp),
        add,
        el('div', { class: 'su-note' },
          'The log stays where it is — the app only reads it, and never writes to it.')));
  }

  function sectionInventoryUpload(chars, msg) {
    const file = el('input', { type: 'file', accept: '.txt' });
    const btn = el('button', { class: 'metal-btn' }, 'Import this file');
    btn.addEventListener('click', async () => {
      const f = file.files && file.files[0];
      if (!f) { msg.className = 'su-msg warn'; msg.textContent = 'Pick a file first.'; return; }
      if (!chars.active) { msg.className = 'su-msg warn'; msg.textContent = 'Add a character first.'; return; }
      btn.disabled = true;
      try {
        const text = await f.text();
        const r = await API.post('/api/inventory/import' + App.q(),
          { content: text, filename: f.name });
        msg.className = 'su-msg good';
        msg.textContent = r.unchanged ? 'That file was already imported.'
          : `Imported ${r.items} items (${r.exaltations} exaltations).`;
        await afterChange({ keepOpen: true });
      } catch (e) {
        msg.className = 'su-msg bad';
        msg.textContent = e.message;
      }
      btn.disabled = false;
    });
    return el('div', { class: 'su-sec' },
      el('h3', {}, 'Inventory dump'),
      el('div', {},
        el('div', { class: 'su-lead', style: 'margin:0 0 8px' },
          'In game: ', el('b', {}, '/outputfile inventory'),
          ' — then either rescan above, or pick the file here.'),
        el('div', { class: 'su-row' }, file, btn)));
  }

  function fmtMB(n) {
    if (!n) return '0 MB';
    return (n / 1048576).toFixed(1) + ' MB';
  }

  /* After anything that changes characters: refresh the app's cached identity,
     repaint the header + current page, and either close (setup satisfied) or
     re-render the modal. */
  async function afterChange(opts) {
    opts = opts || {};
    let chars = null;
    try { chars = await API.get('/api/characters'); } catch (e) {}
    if (chars) {
      App.characters = chars.characters || [];
      App.active = chars.active || null;
      if (typeof renderCharSelect === 'function') renderCharSelect();
      if (typeof navigate === 'function') navigate();
      if (!opts.keepOpen && !chars.needs_setup && closeBtn.style.display === 'none') {
        close();          // first-run flow: the requirement is met, get out of the way
        return;
      }
    }
    await render({ firstRun: closeBtn.style.display === 'none' });
  }

  return { open, close, get isOpen() { return !!backdrop && backdrop.classList.contains('open'); } };
})();

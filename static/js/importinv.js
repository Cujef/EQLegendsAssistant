/* Import Inventory — the sidebar action and its dialog. It takes every
   /outputfile export the app understands:

     /outputfile inventory          <Name>_<server>-Inventory.txt
     /outputfile faction            <Name>_<server>-Faction.txt
     /outputfile recipes <skill>    <Name>_<server>-<Skill>-Recipes.txt

   Three ways in: pick the file in the browser (the picker hands us CONTENT, no
   path), type a path on this computer, or re-read the remembered inventory
   path. The filename is the ONLY thing that says whose a file is and what kind
   it is, so it is parsed here (and again on the server); a file named for
   someone other than the active character offers to import for that character
   (created if needed). POST /api/import tells the kinds apart server-side.

   Registered as a nav ACTION (router.js Pages.registerAction), so it sits below
   the divider at the bottom of the sidebar and never becomes the active page. */
'use strict';

const ImportInventory = (() => {
  const RE_NAME = /^(\w+)_(\w+)-(?:(Inventory)|(Faction)|(?:([A-Za-z ]+)-)?(Recipes))\.txt$/i;
  const SKILL_TOKENS = { jewelcrafting: 'Jewelry Making', poisonmaking: 'Make Poison' };
  let dlg = null, onDone = null, msg = null;

  /* {name, server, kind, skill} from an export filename or path, else null.
     Mirrors gamefiles.parse_outputfile_name on the server. */
  function detect(filename) {
    const base = String(filename || '').split(/[\\/]/).pop();
    const m = RE_NAME.exec(base);
    if (!m) return null;
    const kind = m[3] ? 'inventory' : m[4] ? 'faction' : 'recipes';
    let skill = null;
    if (kind === 'recipes' && m[5]) {
      const t = m[5].trim();
      skill = SKILL_TOKENS[t.toLowerCase()] || t;
    }
    return { name: m[1], server: m[2], kind, skill };
  }
  function sameChar(who, c) {
    return !!(who && c && who.name.toLowerCase() === String(c.name).toLowerCase()
      && who.server.toLowerCase() === String(c.server).toLowerCase());
  }
  function kindLabel(who) {
    if (!who) return 'kind unknown — decided by content';
    if (who.kind === 'recipes') return 'recipes' + (who.skill ? ` · ${who.skill}` : '');
    return who.kind;
  }
  function describe(r) {
    if (r.kind === 'faction') return `${r.rows} faction standings`;
    if (r.kind === 'recipes') return `${r.rows} ${r.skill && r.skill !== 'unknown' ? r.skill + ' ' : ''}recipes`;
    return `${r.items} items (${r.exaltations} exaltations)`;
  }

  function setMsg(cls, text) {
    if (!msg) return;
    msg.className = 'su-msg ' + cls;
    msg.textContent = text;
  }

  async function refreshApp() {
    try {
      const d = await API.get('/api/characters');
      App.characters = d.characters || [];
      App.active = d.active || null;
      if (typeof renderCharSelect === 'function') renderCharSelect();
      if (typeof Suggest !== 'undefined') Suggest.update(d.readiness);
    } catch (e) { /* the WS snapshot will catch up */ }
    if (typeof navigate === 'function') navigate();
  }

  async function doImport(body, route) {
    const r = await API.post((route || '/api/import') + App.q(), body);
    const who = r.character ? `${r.character.name} (${r.character.server})` : 'the active character';
    let text = r.unchanged
      ? `Already imported for ${who} — the file has not changed.`
      : `Imported ${describe(r)} for ${who}.`;
    if (r.skipped_count) text += ` ${r.skipped_count} line(s) did not fit the format and were skipped.`;
    setMsg('good', text);
    await refreshApp();
    if (onDone) onDone(r);
    return r;
  }

  async function guarded(btn, fn) {
    btn.disabled = true;
    setMsg('muted', 'Importing…');
    try {
      await fn();
    } catch (e) {
      setMsg('bad', e.message);
    } finally {
      btn.disabled = false;
    }
  }

  // ── sections ────────────────────────────────────────────────────────────
  function sectionFile() {
    const file = el('input', { type: 'file', accept: '.txt' });
    const info = el('div', { style: 'margin-top:8px' });

    const render = () => {
      info.replaceChildren();
      const f = file.files && file.files[0];
      if (!f) return;
      const who = detect(f.name);
      const active = App.active;
      const read = () => f.text();
      info.append(el('div', { class: 'su-row', style: 'margin-bottom:8px' },
        el('span', { class: 'muted' }, f.name),
        who ? el('span', { class: 'su-chip good' }, `${who.name} · ${who.server}`)
            : el('span', { class: 'su-chip warn' }, 'owner not in file name'),
        el('span', { class: 'su-chip' + (who ? '' : ' warn') }, kindLabel(who))));
      const buttons = el('div', { class: 'su-row' });
      if (who && !sameChar(who, active)) {
        // the file says whose it is, and it is not the active character
        const sw = el('input', { type: 'checkbox' });
        sw.checked = true;
        const b1 = el('button', { class: 'metal-btn primary' },
          `Import for ${who.name} (${who.server})`);
        b1.addEventListener('click', () => guarded(b1, async () => doImport({
          content: await read(), filename: f.name, target: 'detected', activate: sw.checked,
        })));
        buttons.append(b1, el('label', { class: 'su-check' }, sw, 'switch to this character'));
        if (active) {
          const b2 = el('button', { class: 'metal-btn' }, `Import for ${active.name} anyway`);
          b2.addEventListener('click', () => guarded(b2, async () => doImport({
            content: await read(), filename: f.name,
          })));
          buttons.append(b2);
        }
        info.append(el('div', { class: 'su-note', style: 'margin:0 0 8px' },
          `This file is named for ${who.name} on ${who.server}`
          + (active ? `; ${active.name} is the active character.` : '.')
          + (App.characters.some((c) => sameChar(who, c))
            ? '' : ' Importing for them adds the character to this app.')));
      } else if (active) {
        const b = el('button', { class: 'metal-btn primary' }, `Import for ${active.name}`);
        b.addEventListener('click', () => guarded(b, async () => doImport({
          content: await read(), filename: f.name,
        })));
        buttons.append(b);
      } else {
        info.append(el('div', { class: 'warn' },
          'No character yet, and the file name does not say whose it is. Add a character '
          + 'first (＋ Characters), or keep the game\'s file name (<Name>_<server>-Inventory.txt).'));
      }
      info.append(buttons);
    };
    file.addEventListener('change', render);

    return el('div', { class: 'su-sec' },
      el('h3', {}, '1 — Pick the file'),
      el('div', {},
        el('div', { class: 'su-row' }, file),
        info,
        el('div', { class: 'su-note' },
          'The same picker takes the other two exports: ',
          el('code', {}, '/outputfile faction'), ' → ', el('code', {}, '<Name>_<server>-Faction.txt'),
          ' (absolute standings for the Factions page) and ',
          el('code', {}, '/outputfile recipes <skill>'), ' → ',
          el('code', {}, '<Name>_<server>-<Skill>-Recipes.txt'),
          ' (your learned recipes for the Tradeskills page). Files are read once and stored '
          + 'in this app; your game files are never written to.')));
  }

  function sectionPath() {
    const active = App.active;
    const input = el('input', {
      type: 'text',
      value: (active && active.inventory_path) || '',
      placeholder: 'C:\\Users\\Public\\Daybreak Game Company\\Installed Games\\EverQuest Legends\\'
        + '<Name>_<server>-Inventory.txt',
    });
    const btn = el('button', { class: 'metal-btn' }, 'Import from this path');
    btn.addEventListener('click', () => guarded(btn, async () => {
      const p = input.value.trim();
      if (!p) throw new Error('Enter the full path to the file.');
      const who = detect(p);
      const body = { path: p };
      if (who && !sameChar(who, App.active)) {
        body.target = 'detected';     // the path names its owner: import for them
        body.activate = true;
      }
      await doImport(body);
    }));
    return el('div', { class: 'su-sec' },
      el('h3', {}, '2 — Or point at the file on this computer'),
      el('div', {},
        el('div', { class: 'su-row' }, input, btn),
        el('div', { class: 'su-note' },
          'Any of the three exports works here. An inventory path is remembered, so later '
          + 'imports are one click. A path named for another character imports for that '
          + 'character and switches to them.')));
  }

  function sectionStored() {
    const active = App.active;
    if (!active || !active.inventory_path) return null;
    const btn = el('button', { class: 'metal-btn' }, 'Re-read the remembered file');
    btn.addEventListener('click', () => guarded(btn, async () => doImport({}, '/api/inventory/import')));
    return el('div', { class: 'su-sec' },
      el('h3', {}, `3 — ${active.name}'s remembered inventory file`),
      el('div', {},
        el('div', { class: 'su-row' },
          el('span', { class: 'muted', style: 'font-family:var(--font-mono);font-size:12px' },
            active.inventory_path),
          btn),
        el('div', { class: 'su-note' },
          'Run /outputfile inventory again in game, then press this to pick up the new dump. '
          + 'An unchanged file is detected and skipped.')));
  }

  // ── dialog ──────────────────────────────────────────────────────────────
  function open(opts) {
    opts = opts || {};
    onDone = opts.onDone || null;
    if (!dlg) dlg = Modal.create({ title: 'Import Inventory', onClose: () => { onDone = null; } });
    msg = el('div', { class: 'su-msg muted' });
    dlg.body.replaceChildren(
      el('div', { class: 'su-callout' },
        "To upload your character's gear file from EQL, type ",
        el('code', {}, '/outputfile inventory'),
        ' while in-game. This will produce an ',
        el('code', {}, 'inventory.txt'),
        ' file in ',
        el('code', {}, 'C:\\Users\\Public\\Daybreak Game Company\\Installed Games\\EverQuest Legends'),
        ' (or wherever EQ Legends is installed).'),
      sectionFile(), sectionPath(), sectionStored(), msg);
    dlg.open();
  }

  function close() { if (dlg) dlg.close(true); }

  Pages.registerAction({
    id: 'import-inventory',
    title: 'Import Inventory',
    icon: '⤓',
    onClick: () => open({}),
  });

  return { open, close, detect };
})();

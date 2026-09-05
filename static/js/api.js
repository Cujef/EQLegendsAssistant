/* Fetch wrapper + reconnecting WebSocket snapshot bus.
   App.snapshot holds the latest 1 Hz server snapshot; 'snapshot' events fire on
   window for pages that render live data. */
'use strict';

const App = {
  snapshot: null,       // latest WS state push
  characters: [],
  active: null,         // active character row
  charId() { return App.active ? App.active.id : null; },
  /* The parser's internal actor key is 'player'; the server substitutes the
     real name on the way out (app/naming.py). Pages that label "you" use this
     so the two never disagree. */
  playerName() {
    const live = App.snapshot && App.snapshot.live;
    return (live && live.player_name) || (App.active && App.active.name) || 'player';
  },
  q(extra) {            // query-string with the active char id
    const p = new URLSearchParams(extra || {});
    if (App.active) p.set('char', App.active.id);
    const s = p.toString();
    return s ? '?' + s : '';
  },
};

const API = {
  async get(path) {
    const r = await fetch(path);
    if (!r.ok) throw new Error(await API._err(r));
    return r.json();
  },
  async post(path, body) {
    const r = await fetch(path, {
      method: 'POST',
      headers: body !== undefined ? { 'Content-Type': 'application/json' } : {},
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!r.ok) throw new Error(await API._err(r));
    return r.json();
  },
  async del(path) {
    const r = await fetch(path, { method: 'DELETE' });
    if (!r.ok) throw new Error(await API._err(r));
    return r.json();
  },
  async _err(r) {
    try {
      const j = await r.json();
      return j.detail || JSON.stringify(j);
    } catch (e) { return r.status + ' ' + r.statusText; }
  },
};

function connectWS() {
  const dot = document.getElementById('conn-dot');
  let ws;
  const open = () => {
    ws = new WebSocket(`ws://${location.host}/ws`);
    ws.onopen = () => { if (dot) { dot.classList.add('on'); dot.title = 'Live'; } };
    ws.onmessage = (ev) => {
      try {
        const data = JSON.parse(ev.data);
        App.snapshot = data;
        App.characters = data.characters || [];
        App.active = data.active || null;
        window.dispatchEvent(new CustomEvent('snapshot', { detail: data }));
      } catch (e) { /* malformed frame: skip */ }
    };
    ws.onclose = () => {
      if (dot) { dot.classList.remove('on'); dot.title = 'Reconnecting…'; }
      setTimeout(open, 2000);
    };
    ws.onerror = () => ws.close();
  };
  open();
}

/* tiny DOM helpers used across pages */
function el(tag, attrs, ...children) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === 'class') n.className = v;
    else if (k.startsWith('on') && typeof v === 'function') n.addEventListener(k.slice(2), v);
    else if (v !== null && v !== undefined) n.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined) continue;
    n.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return n;
}
function fmt(n) {
  if (n === null || n === undefined) return '—';
  return Number(n).toLocaleString();
}

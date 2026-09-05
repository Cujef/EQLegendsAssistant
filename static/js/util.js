/* Shared page helpers.

   Every page is its own IIFE, so before this file each one carried its own copy
   of the same few helpers — statRow, pending, dateCell and friends were
   byte-identical across three files apiece. They live here now, as globals,
   the way api.js already exposes el/fmt. Loaded straight after api.js so every
   page and tile can rely on them.

   Coin: EverQuest counts in copper, 10 copper to a silver, 10 silver to a gold,
   10 gold to a platinum. Whole sums read as "1,234p 5g" rather than 12,345,067. */
'use strict';

/* A label/value row for the small stat lists in tiles. */
function statRow(label, value, cls) {
  return el('div', { style: 'display:flex;gap:10px;justify-content:space-between;' +
    'padding:3px 0;border-bottom:1px solid var(--edge)' },
    el('span', { class: 'muted' }, label),
    el('span', { class: 'num' + (cls ? ' ' + cls : '') }, value));
}

/* Tiles build before their fetch lands, and again after a failure: both states
   need a body, not an exception. Returns true when the caller should stop. */
function pendingBox(box, data, error, loadingText) {
  if (data) return false;
  box.replaceChildren(el('div', { class: 'empty-note' + (error ? ' bad' : '') },
    error || loadingText || 'Loading…'));
  return true;
}

const dateCell = (ts) => (ts ? new Date(ts * 1000).toLocaleDateString() : null);
const timeCell = (ts) => (ts ? new Date(ts * 1000).toLocaleString() : null);

/* m:ss for a fight, h:mm for anything session-length. */
function fmtDur(s) {
  s = Math.max(0, Math.round(s || 0));
  if (s >= 3600) {
    return Math.floor(s / 3600) + ':' + String(Math.floor((s % 3600) / 60)).padStart(2, '0')
      + ':' + String(s % 60).padStart(2, '0');
  }
  return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
}

function fmtHours(s) {
  const h = (s || 0) / 3600;
  return h >= 10 ? h.toFixed(0) + ' h' : h.toFixed(1) + ' h';
}

function fmtTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((n) => String(n).padStart(2, '0')).join(':');
}

function fmtMB(n) {
  if (!n) return '0 MB';
  return (n / 1048576).toFixed(1) + ' MB';
}

/* Copper -> "1,234p 5g 6s 7c", trimmed to the two largest non-zero units. */
function fmtCoin(copper) {
  const c = Math.max(0, Math.round(copper || 0));
  if (!c) return '0';
  const parts = [
    [Math.floor(c / 1000), 'p'],
    [Math.floor(c / 100) % 10, 'g'],
    [Math.floor(c / 10) % 10, 's'],
    [c % 10, 'c'],
  ].filter(([n]) => n > 0);
  return parts.slice(0, 2).map(([n, u]) => fmt(n) + u).join(' ');
}

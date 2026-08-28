/* Sortable data tables (parser's delegated-sort pattern, generalized).

   renderTable(container, {
     id: 'quests',                       // sort-state key
     columns: [{key, label, num?, render?(row), sortVal?(row)}],
     rows: [...],
     defaultSort: {key, dir},            // dir: 1 asc, -1 desc
     empty: 'No rows.',
     onRow?(row, tr),
   })
   Re-render with the same id keeps the user's sort. */
'use strict';

const _sortState = {};   // id -> {key, dir}

function renderTable(container, opts) {
  const st = _sortState[opts.id] || opts.defaultSort || null;
  let rows = opts.rows.slice();
  if (st) {
    const col = opts.columns.find((c) => c.key === st.key);
    if (col) {
      const val = col.sortVal || ((r) => r[col.key]);
      rows.sort((a, b) => {
        const va = val(a), vb = val(b);
        if (va === vb) return 0;
        if (va === null || va === undefined) return 1;
        if (vb === null || vb === undefined) return -1;
        return (va < vb ? -1 : 1) * st.dir;
      });
    }
  }
  const table = el('table', { class: 'data' });
  const thead = el('thead', {});
  const hr = el('tr', {});
  for (const c of opts.columns) {
    const th = el('th', { class: (c.num ? 'num ' : '') + (st && st.key === c.key ? 'sorted' : '') },
      c.label + (st && st.key === c.key ? (st.dir > 0 ? ' ▲' : ' ▼') : ''));
    th.addEventListener('click', () => {
      const cur = _sortState[opts.id];
      _sortState[opts.id] = (cur && cur.key === c.key)
        ? { key: c.key, dir: -cur.dir }
        : { key: c.key, dir: c.num ? -1 : 1 };
      renderTable(container, opts);
    });
    hr.append(th);
  }
  thead.append(hr);
  table.append(thead);
  const tbody = el('tbody', {});
  for (const r of rows) {
    const tr = el('tr', {});
    for (const c of opts.columns) {
      const td = el('td', { class: c.num ? 'num' : '' });
      const v = c.render ? c.render(r) : r[c.key];
      if (v === null || v === undefined) td.textContent = '—';
      else if (v.nodeType) td.append(v);
      else td.textContent = v;
      tr.append(td);
    }
    if (opts.onRow) opts.onRow(r, tr);
    tbody.append(tr);
  }
  table.append(tbody);
  container.replaceChildren(table);
  if (!rows.length) {
    container.append(el('div', { class: 'empty-note' }, opts.empty || 'Nothing here yet.'));
  }
}

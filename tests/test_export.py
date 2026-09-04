"""CSV / JSON export: the pure functions (the route is covered by test_api)."""


def run(check):
    from app import export

    cols = [('name', 'Item'), ('count', 'Count'), ('note', 'Note'), ('ts', 'When')]
    rows = [
        {'name': 'Rusty Dagger', 'count': 3, 'note': 'has, a comma', 'ts': '2026-09-04 10:00:00'},
        {'name': 'Quote "Blade"', 'count': None, 'note': None, 'ts': None},
    ]
    out = export.to_csv(cols, rows)
    check('csv: UTF-8 BOM first', out.startswith('﻿'.encode('utf-8')), out[:6])
    text = out.decode('utf-8')[1:]
    lines = text.split('\r\n')
    check('csv: CRLF line ends, trailing terminator', text.endswith('\r\n') and len(lines) == 4, lines)
    check('csv: header row from labels', lines[0] == 'Item,Count,Note,When', lines[0])
    check('csv: minimal quoting for a comma', lines[1] == 'Rusty Dagger,3,"has, a comma",2026-09-04 10:00:00', lines[1])
    check('csv: quotes doubled, None -> empty', lines[2] == '"Quote ""Blade""",,,', lines[2])

    fn = export.filename({'name': 'Fizzwick', 'server': 'halas'}, 'zones', 'csv')
    check('csv: filename shape', fn.startswith('Fizzwick_halas-zones-') and fn.endswith('.csv')
          and len(fn) == len('Fizzwick_halas-zones-YYYYMMDD.csv'), fn)

    check('csv: every view names columns as (key, label) pairs',
          all(isinstance(c, tuple) and len(c) == 2 for cols_, _ in export.VIEWS.values() for c in cols_)
          and {'inventory', 'recipes', 'materials', 'known_recipes', 'factions', 'fights', 'merges',
               'loot', 'zones'} <= set(export.VIEWS))
    try:
        export.rows('nope', 1)
        check('csv: unknown view raises KeyError', False)
    except KeyError:
        check('csv: unknown view raises KeyError', True)
    import re
    check('csv: timestamp formatting', bool(re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d', export._ts(1_000_000)))
          and export._ts(None) is None and export._ts('') is None and export._ts('x') == 'x')

"""Regenerate the bundled achievement list from the wiki's Category:Achievements.

The app reads the synced `achievements` guide at run time; app/data/
achievements.json is the fallback for a fresh install (no sync yet) and for a
wiki edit that breaks the parse. Source, in order: the synced guide's raw
wikitext, the raw_pages cache, or a file passed with --from (the page's raw
wikitext, e.g. saved from api.php?action=parse&page=Category:Achievements&prop=wikitext).

    python tools/gen_achievements.py                 # rewrite app/data/achievements.json
    python tools/gen_achievements.py --check         # compare, no write
    python tools/gen_achievements.py --from page.txt # parse a saved wikitext file
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import achievements, db  # noqa: E402
from app.sync import wiki_parse  # noqa: E402

PAGE_URL = 'https://eqlwiki.com/Category:Achievements'


def main(argv) -> int:
    check = '--check' in argv
    src = None
    if '--from' in argv:
        src = Path(argv[argv.index('--from') + 1]).read_text('utf-8')
        fetched_at, revid = None, None
    else:
        db.init()
        row = db.query_one("SELECT raw_wikitext, fetched_at FROM guides WHERE slug='achievements'")
        if row and row['raw_wikitext']:
            src, fetched_at = row['raw_wikitext'], row['fetched_at']
        else:
            row = db.query_one('SELECT content, fetched_at FROM raw_pages WHERE url=?', (PAGE_URL,))
            if row:
                src, fetched_at = row['content'], row['fetched_at']
        sync = db.query_one('SELECT revid FROM sync_pages WHERE url=?', (PAGE_URL,))
        revid = sync['revid'] if sync else None
    if not src:
        print('no cached copy of Category:Achievements — run a Data Sync first, or pass --from <file>')
        return 2
    defs = wiki_parse.parse_achievements(src)
    problems = []
    if len(defs) < achievements.MIN_DEFS:
        problems.append(f'only {len(defs)} achievements parsed (min {achievements.MIN_DEFS})')
    keys = Counter(d['key'] for d in defs)
    dupes = [k for k, n in keys.items() if n > 1]
    if dupes:
        problems.append(f'duplicate keys: {dupes}')
    kinds = Counter(d['unlock']['kind'] for d in defs if d['unlock'])
    for kind, want in (('race', 16), ('class', 16), ('deity', 17)):
        if kinds.get(kind, 0) < want:
            problems.append(f'{kind} unlocks: {kinds.get(kind, 0)} (expected {want})')
    print(f'{len(defs)} achievements; unlocks {dict(kinds)}; groups '
          + ', '.join(f'{g}/{s} {n}' for (g, s), n in sorted(Counter((d["group"], d["sub"]) for d in defs).items())))
    for p in problems:
        print('PROBLEM: ' + p)
    if problems:
        return 1
    out = {'source_url': PAGE_URL, 'fetched_at': fetched_at, 'revid': revid,
           'generated_at': time.time(), 'count': len(defs), 'achievements': defs}
    path = achievements.BUNDLED
    if check:
        if not path.is_file():
            print(f'{path} is missing')
            return 1
        cur = json.loads(path.read_text('utf-8')).get('achievements')
        if cur != defs:
            print(f'DRIFT: {path.name} differs from the wiki page — rerun without --check')
            return 1
        print(f'{path.name} matches the wiki page')
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True) + '\n',
                    encoding='utf-8')
    print(f'wrote {path} ({path.stat().st_size} bytes)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

"""Regenerate the bundled Plane of Sky class-test list from the wiki cache.

The app parses https://eqlwiki.com/Plane_of_Sky straight out of raw_pages at
run time; app/data/sky_quests.json is the fallback for a fresh install (no
sync yet) and for a wiki edit that breaks the parse. Re-run after a Data Sync
when the wiki changes; --check only compares and exits 1 on drift.

    python tools/gen_sky_quests.py            # rewrite app/data/sky_quests.json
    python tools/gen_sky_quests.py --check    # compare, no write
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, skyquests  # noqa: E402
from app.quests import CLASSES  # noqa: E402


def main(argv) -> int:
    check = '--check' in argv
    db.init()
    row = db.query_one('SELECT content, fetched_at FROM raw_pages WHERE url=?',
                       (skyquests.PAGE_URL,))
    if not row:
        print(f'no cached copy of {skyquests.PAGE_URL} — run a Data Sync first')
        return 2
    quests = skyquests.parse_wikitext(row['content'])
    problems = []
    if len(quests) < skyquests.MIN_QUESTS:
        problems.append(f'only {len(quests)} tests parsed (min {skyquests.MIN_QUESTS})')
    missing = set(CLASSES) - {q['cls'] for q in quests}
    extra = {q['cls'] for q in quests} - set(CLASSES)
    if missing:
        problems.append(f'classes without a table: {sorted(missing)}')
    if extra:
        problems.append(f'unknown class headings: {sorted(extra)}')
    keys = Counter(q['key'] for q in quests)
    dupes = [k for k, n in keys.items() if n > 1]
    if dupes:
        problems.append(f'duplicate keys: {dupes}')
    for q in quests:
        if not q['runes'] or not q['items']:
            problems.append(f"{q['name']}: runes={len(q['runes'])} items={len(q['items'])}")
    per_class = Counter(q['cls'] for q in quests)
    print(f'{len(quests)} tests, {len(per_class)} classes: '
          + ', '.join(f'{c} {n}' for c, n in sorted(per_class.items())))
    print('source tags: ' + ', '.join(sorted({it['src'] for q in quests for it in q['items']
                                               if it['src']})))
    for p in problems:
        print('PROBLEM: ' + p)
    if problems:
        return 1
    sync = db.query_one('SELECT revid FROM sync_pages WHERE url=?', (skyquests.PAGE_URL,))
    out = {
        'source_url': skyquests.PAGE_URL,
        'fetched_at': row['fetched_at'],
        'revid': sync['revid'] if sync else None,
        'generated_at': time.time(),
        'count': len(quests),
        'quests': quests,
    }
    path = skyquests.BUNDLED
    if check:
        if not path.is_file():
            print(f'{path} is missing')
            return 1
        cur = json.loads(path.read_text('utf-8')).get('quests')
        if cur != quests:
            print(f'DRIFT: {path.name} differs from the cached wiki page — rerun without --check')
            return 1
        print(f'{path.name} matches the cached wiki page')
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1, ensure_ascii=False, sort_keys=True) + '\n',
                    encoding='utf-8')
    print(f'wrote {path} ({path.stat().st_size} bytes)')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

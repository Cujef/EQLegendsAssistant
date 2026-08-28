"""Re-parse wiki item pages from the raw_pages cache — no refetching.

Use after a wiki_parse upgrade (e.g. the Haste line fix) so 10k+ item rows
pick up the better parse without hitting the wiki again. is_quest_item is
preserved from the existing rows (its source, Category:Quest_Items membership,
is only known during a live sync).

Run with the server STOPPED: python tools/reparse_items.py
"""
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db  # noqa: E402
from app.sync import wiki_api, wiki_parse  # noqa: E402


def main():
    db.init()
    pages = db.query(
        "SELECT s.url, r.content FROM sync_pages s JOIN raw_pages r ON r.url=s.url "
        "WHERE s.source='wiki' AND s.kind='item' AND s.parse_ok=1")
    quest_flags = {r['name_norm'] for r in db.query(
        'SELECT name_norm FROM items WHERE is_quest_item=1')}
    done = parsed = 0
    batch = []
    for p in pages:
        title = urllib.parse.unquote(
            p['url'].rsplit('/', 1)[-1]).replace('_', ' ')
        batch.append((title, p['content'], p['url']))
        if len(batch) >= 500:
            parsed += _apply(batch, quest_flags)
            done += len(batch)
            batch = []
            print(f'  {done}/{len(pages)}', flush=True)
    parsed += _apply(batch, quest_flags)
    done += len(batch)
    print(f'reparsed {parsed} items from {done} cached pages')
    db.close()


def _apply(batch, quest_flags) -> int:
    n = 0
    with db.tx() as c:
        for title, content, url in batch:
            parsed = wiki_parse.parse_itempage(content)
            if parsed is None:
                continue
            unit = {'title': title, 'kind': 'item'}
            wiki_api._upsert_item(c, unit, parsed, url, db.now(), set())
            from app.inventory import normalize_name
            key = normalize_name(parsed['itemname'] or title)
            if key in quest_flags:
                c.execute('UPDATE items SET is_quest_item=1 WHERE name_norm=?', (key,))
            n += 1
    return n


if __name__ == '__main__':
    main()

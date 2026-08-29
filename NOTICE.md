# Notices

## Trademarks and affiliation

This is an unofficial, fan-made tool. It is **not affiliated with, endorsed by,
or sponsored by Daybreak Game Company**. EverQuest and EverQuest Legends are
trademarks of Daybreak Game Company LLC.

## Scope of the MIT license

[LICENSE](LICENSE) covers the **source code** in this repository, including the
files in `vendor/eqlparser/` (copied from the same author's
[EQLegendsParser](https://github.com/Cujef/EQLegendsParser) project — see
[vendor/eqlparser/PROVENANCE.md](vendor/eqlparser/PROVENANCE.md)).

It does **not** cover game data, artwork, or item icons. Those are read from
your own game installation at runtime and are never distributed with this
software:

- Item icons are decoded on demand from `uifiles/default/dragitem*.dds` in your
  own EverQuest Legends install. The converted PNGs live in your working copy
  and are gitignored.
- Spell, item, and zone data come from your own game files and from the
  community sites you choose to sync.

## Community data

The Data Sync feature fetches from two community-run sites, throttled, and
caches the results locally in `data/assistant.db` (gitignored):

- [eqlwiki.com](https://eqlwiki.com/) — via its public MediaWiki API.
- [eqlegendstools.com](https://eqlegendstools.com/) — via its published
  `sitemap.xml`. Paths disallowed by its `robots.txt` are refused in code
  (`app/sync/engine.py`).

Both are volunteer projects. Please be considerate if you change the sync
throttle.

The test suites (`tests/test_wiki_parse.py`, `tests/test_tools_site.py`) embed
small trimmed excerpts of pages from those two sites, used solely as fixtures to
pin the parsers against real-world markup.

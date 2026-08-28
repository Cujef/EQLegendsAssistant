# EQ Legends Assistant

A local web app that supplements playing **EverQuest Legends**: character
overview, inventory analysis, quest tracking and suggestions, a compact live
combat parser, exaltation (focus/proc/worn/click effect) matching, "what to
do next" suggestions, and tradeskill progress — all fed by your own log file,
your `/outputfile inventory` dumps, and a locally-synced copy of the community
databases ([eqlwiki.com](https://eqlwiki.com/) and
[eqlegendstools.com](https://eqlegendstools.com/)).

Companion project to [EQLegendsParser](https://github.com/Cujef/EQLegendsParser)
(the full combat-parser dashboard). This app vendors that project's pure
parsing modules — see `vendor/eqlparser/PROVENANCE.md`.

## Requirements

- Python 3.10+ (`pip install -r requirements.txt` — FastAPI, uvicorn, optional Pillow for item icons)
- EverQuest Legends installed (default `J:\EQLegends`, configurable in `config.json`)
- In game: `/log on` (the app reads `Logs\eqlog_<Char>_<server>.txt`)
- For inventory features: `/outputfile inventory` in game (writes to the install root)

## Run

```bash
python run.py
```

Opens http://127.0.0.1:8766 (the parser project uses 8765; both can run together).

## First-time setup

1. **Inventory page** → *Import inventory file* (after `/outputfile inventory` in game).
2. The **log pipeline** starts automatically and scans your full log once
   (progress shows on the Parser page); after that it tails live.
3. **Data Sync page** → run *eqlwiki* and *EQL Tools* syncs (throttled to
   ~1 request/second out of respect for the community sites; the first wiki
   sync takes ~25 minutes, re-syncs only fetch changed pages).
4. **Overview page** → pick your class(es)/race (they exist in no local file,
   so they're manual).

## Pages

| Page | What it shows |
|---|---|
| Overview | Gear stat totals vs caps, AA earned/spent/unspent (from the log), worn haste, best focus/proc/worn effect per family, log highlights (biggest hits, nemesis mobs) |
| Inventory | The parsed dump: worn/bags/bank/depot, exaltations, open aug sockets |
| Quest Progress | Tracked quests with per-step checklists |
| Quest Ideas | The synced quest index — filter by class/race/level/completed |
| Parser | Compact live combat tiles (drag/resize/lock) + import progress |
| Exaltations | Every effect you own, where it's socketed, where it could move |
| What to do? | Quests your inventory items unlock + where to hunt at your level |
| Tradeskills | Skill levels from log skill-ups, wiki guide links |
| Data Sync | Run/cancel syncs, progress, unparsed-page report |

## Honesty rules

- Every Overview number is labeled **computed** (derived), **manual**
  (you typed it), or **fallback** (hardcoded default).
- Gear totals use *base* item stats — the item DB doesn't know `+N` upgrade
  scaling. Unmatched items are counted and shown, never silently dropped.
- Exaltation move suggestions use **assumed** compatibility rules
  (`app/exaltation.py: COMPATIBILITY_RULES`) — the game's real transfer rules
  aren't authoritatively documented.

## Network behavior

The app makes **no network requests** except when you press a Sync button:
eqlwiki via its public MediaWiki API, eqlegendstools via its sitemap pages
(its robots.txt-disallowed `/api/` path is refused in code:
`app/sync/engine.py`). Everything is cached permanently in
`data/assistant.db`; re-syncs fetch only changed pages.

## Development

```bash
python selftest.py            # regression gate (auto-discovers tests/test_*.py)
python selftest.py core       # one suite
python tools/check_vendor_drift.py   # compare vendor/eqlparser vs upstream
```

Layout: `app/` (FastAPI backend: `server.py`, `db.py` single-writer SQLite,
`logscan/` log pipeline, `sync/` site crawlers), `static/` (zero-build vanilla
JS: `js/pages/*` one file per page), `vendor/eqlparser/` (vendored, never
edited), `data/` (SQLite + icon cache, gitignored).

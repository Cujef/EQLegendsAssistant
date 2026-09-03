# EQ Legends Assistant

*An unofficial, fan-made companion tool. Not affiliated with, endorsed by, or
sponsored by Daybreak Game Company. It reads your own log and inventory files
and never modifies the game. MIT licensed — see [LICENSE](LICENSE) and
[NOTICE.md](NOTICE.md).*

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

On first run the app opens a **setup prompt**: point it at your EverQuest
Legends folder (either the install root or its `Logs` folder), press *Scan*,
and add your character. It finds characters from the game's `_characters.ini`
and from `Logs\eqlog_<Name>_<server>.txt`, shows which ones have a log and an
inventory dump, and imports the inventory automatically when it finds one.

If nothing is found you can add a character by hand (name, server, full path to
the log). The log stays where it is — the app only ever reads it. An inventory
dump anywhere on disk can also be picked with the file browser.

Add or switch characters later from **＋ Characters** in the title bar; each
character keeps its own imported data, and removing one removes only this app's
copy.

A **suggestion box** above the pages then lists what the app still needs from
you — your inventory dump, your log file, a community-data sync — with a button
for each; it goes away once all three are done (or when you dismiss it).

Then:
1. The **log pipeline** starts automatically and scans your full log once
   (progress shows on the Parser page); after that it tails live.
2. **Data Sync page** → run *eqlwiki* and *EQL Tools* syncs (throttled out of
   respect for the community sites; the first run takes ~10–20 minutes each,
   re-syncs only fetch changed pages).
3. **Overview page** → pick your class(es)/race (they exist in no local file,
   so they're manual).

### Import Inventory

**Import Inventory** sits at the bottom of the left navigation. To upload your
character's gear file from EQL, type `/outputfile inventory` while in-game. This
produces `<Name>_<server>-Inventory.txt` in the game's install folder — by
default `C:\Users\Public\Daybreak Game Company\Installed Games\EverQuest Legends`
(or wherever EQ Legends is installed). Pick that file in the dialog, or type its
path so the app can re-read it with one click after your next `/outputfile`.

The file carries no character name inside it, only in its filename, so the
dialog reads the name from there: a dump named for a character other than the
active one offers to import for that character instead (adding them to the app
if needed). Nothing about a character is hard-coded — every name comes from the
game's `_characters.ini`, from log and dump filenames, or from what you type.

The same dialog takes the game's other two exports:

| In game | File written | What it adds |
|---|---|---|
| `/outputfile faction` | `<Name>_<server>-Faction.txt` | absolute standings on the Factions page (the log only ever reports movement), plus an estimate of where you are now |
| `/outputfile recipes <skill>` (e.g. `Baking`, or `all`) | `<Name>_<server>-<Skill>-Recipes.txt` | your learned recipes on the Tradeskills page, joined to how often the log saw you combine each |

These two formats follow the EverQuest client's documented output (faction: id,
name, standing, points to max; recipes: id, name). No EQ Legends sample existed
when this was written, so the parsers are tolerant and report lines they could
not place — if one of your files does not import, please open an issue with it.

## Layout

Every page is a grid of tiles. The 🔒 button unlocks the page for editing:
drag a tile by its ⠿ handle to reorder, drag its right/bottom edge to resize,
✕ to hide one, and **⊞ Tiles** to bring hidden ones back or reset the layout.
Each page remembers its own arrangement and lock state.

## Pages

| Page | What it shows |
|---|---|
| Overview | Gear stat totals vs caps, AA earned/spent/unspent (from the log), worn haste, best focus/proc/worn effect per family, log highlights (biggest hits, nemesis mobs) |
| Inventory | The parsed dump: worn/bags/bank/depot, exaltations, open aug sockets, bag & bank space (nested bags included), the +N upgrade ladder with merge history from the log, the trailing keyring lists |
| Quest Progress | Tracked quests with per-step checklists |
| Quest Ideas | The synced quest index — filter by class/race/level/completed |
| Parser | Compact live combat tiles (drag/resize/lock) + import progress |
| Exaltations | Every effect you own, where it's socketed, where it could move |
| What to do? | Quests your inventory items unlock + where to hunt at your level |
| Tradeskills | Skill levels from log skill-ups; per-recipe combines, failures, success rate and CAP notices; depot materials vs what the dump says you have on hand; learned recipes from `/outputfile recipes`; wiki guide links |
| Factions | Every faction standing change from the log: net movement, counts, MAX/MIN badges; absolute standings and an estimate of now once `/outputfile faction` is imported |
| Data Sync | Run/cancel syncs, progress, unparsed-page report |

## Honesty rules

- Every Overview number is labeled **computed** (derived), **manual**
  (you typed it), or **fallback** (hardcoded default).
- Gear totals use *base* item stats — the item DB doesn't know `+N` upgrade
  scaling. Unmatched items are counted and shown, never silently dropped.
- Exaltation move suggestions use **assumed** compatibility rules
  (`app/exaltation.py: COMPATIBILITY_RULES`) — the game's real transfer rules
  aren't authoritatively documented.
- A recipe's tradeskill is **inferred** (a skill-up within one second of the
  combine) and labeled so; the depot count is an **estimate** from the log; the
  two `Any Slot` items are counted as worn with a caveat; the dump's trailing
  `Equipment` list is shown but never counted.
- Faction standing bands (Ally, Warmly, … Ready to Attack) are EverQuest's
  published thresholds, **assumed** for EQ Legends; "Est. now" is the imported
  value plus the log's movement since the import.

## Network behavior

The app makes **no network requests** except when you press a Sync button:
eqlwiki via its public MediaWiki API, eqlegendstools via its sitemap pages
(its robots.txt-disallowed `/api/` path is refused in code:
`app/sync/engine.py`). Everything is cached permanently in
`data/assistant.db`; re-syncs fetch only changed pages.

## Security note — this is a localhost tool

The server binds `127.0.0.1` only and has no authentication, by design: it is a
single-user app running on the machine that has the game installed.

It reads local files you point it at — the setup endpoints accept a folder to
scan and a log/inventory path to open — so **do not expose it to a network or
put it behind a public reverse proxy**. Anyone who can reach the port can ask it
to read files as your user. It never writes to your game files, and never sends
your character data anywhere.

`data/`, `config.json`, and the item icons converted from your game client are
gitignored and stay on your machine.

## Development

```bash
python selftest.py            # regression gate (auto-discovers tests/test_*.py)
python selftest.py core       # one suite
python tools/check_vendor_drift.py   # compare vendor/eqlparser vs upstream (EOL-insensitive)
python tools/renormalize_keys.py     # after a normalize_name rule change, server stopped
```

Upgrading from 1.0.0: the first start migrates `data/assistant.db` forward and
runs a one-time backfill of tradeskill / faction history from the start of your
log (the Parser page's Log Status shows BACKFILL, then LIVE). Run
`tools/renormalize_keys.py` once so backtick-apostrophe item names join the
item database.

Layout: `app/` (FastAPI backend: `server.py`, `db.py` single-writer SQLite,
`logscan/` log pipeline, `sync/` site crawlers), `static/` (zero-build vanilla
JS: `js/pages/*` one file per page), `vendor/eqlparser/` (vendored, never
edited), `data/` (SQLite + icon cache, gitignored).

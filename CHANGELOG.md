# Changelog

All notable changes to EQ Legends Assistant are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-09-03

The parser's tradeskill and faction tracking arrive, the inventory dump is read
correctly (nested bags, paired slots), every `/outputfile` export the game
offers can be imported, and a first-open box tells a new user what to feed the
app.

### Added

- **`/outputfile faction` and `/outputfile recipes <skill>` imports** — the
  Import Inventory dialog now takes all three exports the game writes and tells
  them apart by filename, then content. The faction file gives what the log
  never can, an absolute standing: the Factions page shows it with its
  EverQuest standing band (Ally … Ready to Attack — thresholds assumed for EQL
  and labeled so) and an "Est. now" of file value plus the log's movement since
  the import. The recipes file lists your learned recipes; the Tradeskills page
  shows them per skill, joined to how often the log saw you combine each one.
  No EQ Legends sample of these two files existed when this shipped, so the
  parsers accept an optional header, tabs or aligned spaces, CRLF and BOMs, and
  report lines they could not fit instead of guessing.
- **Parser v1.6.0 re-vendored** (clean tag, `1cf1243`): faction standing events,
  tradeskill combine / failure / cap / depot-consume events, and group members'
  misses and damage shields — the last two flow straight into the fight meters.
  `vendor/eqlparser/PROVENANCE.md` records both the CRLF working-tree and LF
  blob hashes; the drift check is now line-ending-insensitive.
- **Tradeskills page** — a *Recipes* tile (made / failed / success rate per
  recipe, a CAP badge when the game said the recipe no longer trains, and the
  skill each recipe belongs to — inferred from a skill-up within one second of
  the combine, and labeled as such) and a *Materials* tile (what your combines
  pulled from the depot, an estimated depot count from the "(leaving N)" lines
  plus later deposits and withdrawals, and how many you have on hand in the
  imported inventory dump). The main table gains combine and recipe counts.
- **Factions page** — every standing change per faction with the net movement,
  change count, gained/lost split, and MAX / MIN badges when the game's last
  word on a faction was "could not possibly get any better / worse".
- **Import Inventory** in the left navigation (below a divider) — a dialog that
  explains `/outputfile inventory` and where the file lands, then imports it
  from the browser's file picker, from a path on this computer, or by
  re-reading the remembered path. The game's `<Name>_<server>-Inventory.txt`
  name is read on both sides: a dump named for another character offers to
  import for that character (created on the spot if needed), so one install can
  hold everyone's dumps. The Inventory page's own button opens the same dialog.
- **First-open suggestion box** above the pages: import your inventory, point
  the app at your log, sync the community data — each with its status (from a
  new `readiness` object on `/api/characters` and the 1 Hz snapshot) and a
  button that takes you there. Dismissible per browser; disappears on its own
  once all three are done.
- **Inventory tiles** — *Bag & Bank Space* (every bag including bags inside
  bags, used / free, per-section totals), *Upgrade Ladder* (worn +N tier
  against every owned copy and exaltation copy, flagging a better copy you are
  not wearing), and *Keyring Lists* (the trailing Augmentation / Activated /
  Equipment sections; Equipment is listed but never counted, its meaning being
  unconfirmed). Item rows now say which item or bag they sit in.
- **Item merge history** — the "You have successfully merged two items together
  to create a new item: X +N" line is parsed (336 on the reference log; rank
  merges like "Sprouting Heal II" too). The Upgrade Ladder shows how many merges
  the log saw per item and the highest tier reached; a *Merge History* tile lists
  them. Backfill is revisioned, so an install that already has the v1.1 history
  picks up only the merge rows.
- **Parser feed** shows combines, refused combines, merges, and faction hits live.
- One-time **event backfill**: an existing install's log was already consumed to
  EOF, so the new tradeskill / depot / faction tables are filled once from the
  start of the log (only the matching lines are re-read; nothing additive is
  touched). Fresh installs skip it.
- Depot deposit / withdrawal lines and the three combine-error lines are parsed
  in `app/logscan/ext_parser.py` (upstream does not handle them).
- Shared dialog frame (`static/js/modal.js`) used by Characters and Import
  Inventory; `Pages.registerAction` for sidebar entries that are actions, not
  pages.

### Changed

- `normalize_name` also strips the backtick apostrophe the game writes in some
  item names (`Kavruul`s Mystic Pouch`), so they join the item database. Run
  `python tools/renormalize_keys.py` once with the server stopped (inventory
  snapshots re-import themselves on the next page view).
- `PARSE_REV` 3 → 4: inventory rows carry `seq`, `parent_seq`, and
  `parent_is_container`; a snapshot from an older parse is re-imported from its
  file automatically when the file still exists.

### Fixed

- **Bags inside bags were read as items with open sockets** — their pockets
  showed up in Open Sockets and as exaltation destinations. Container detection
  now uses the bag's capacity and the pocket indices a socket never uses.
- **Paired slots shadowed each other**: `Fingers`, `Ear`, `Wrist` and `Any Slot`
  repeat their Location string verbatim in the dump, so a socket on the first
  ring resolved to the second. Hosts are now resolved by row order.
- The two **`Any Slot`** items were excluded from gear stat totals (now counted,
  with a caveat that the dump does not say whether they are worn).

## [1.0.0] - 2026-08-28

First release. A local companion web app for EverQuest Legends that reads your
own log and inventory files plus a locally-cached copy of the community
databases, and never writes to the game.

### Added

- **Setup & characters** — a first-run prompt when there is no usable character:
  scan a game folder (install root or its `Logs`), pick a discovered character,
  or add one by hand. Inventory is imported automatically when found. Add,
  switch, and remove characters any time from ＋ Characters; removing one clears
  only this app's derived data, never the game files. `EQA_GAME_DIR` /
  `EQA_DATA_DIR` env overrides for a second install.
- **Overview** — gear stat totals against stat caps, AA earned/spent/unspent
  with the purchase ledger, worn haste, best focus/proc/worn effect per family,
  all-time log highlights, and most-frequent killers. Every value is labeled
  computed, manual, or fallback.
- **Inventory** — imports the `/outputfile inventory` dump (server-side path or
  a file picked in the browser), including the trailing KeyRing / Augmentation /
  Activated sections, tradeskill depot rows, augment sockets, `(Exaltation)` and
  `+N` markers, with item icons decoded from the client's own DDS sheets.
- **Parser** — a live combat view fed by a single log pipeline per character:
  byte-offset checkpoint resume, truncation detection, full-history import, then
  live tailing. Fight meters, history, notable-event feed, and import progress.
- **Quest Progress / Quest Ideas** — quests synced from eqlwiki with per-step
  checklists, tracking, and filtering by class, race, level, zone, and completion.
- **Exaltations** — every focus, proc, worn, and click effect you own, where it
  is socketed, which open sockets could receive it, and what is not yet known.
  Move suggestions are explicitly labeled as assumed rules.
- **What to do?** — quests unlocked by items already in your inventory, plus
  hunting recommendations for your current level.
- **Tradeskills** — skill levels derived from log skill-ups, with wiki guide links.
- **Data Sync** — throttled, resumable, cancellable crawls of eqlwiki (MediaWiki
  API, batched 50 pages per request, revision-diffed re-syncs) and
  eqlegendstools (sitemap-driven, `lastmod`-diffed) into local SQLite, with a
  progress view and an unparsed-page report. Honors HTTP 429 backoff and refuses
  robots-disallowed paths.
- **Interface** — a metallic, sharp-edged theme in light and dark; every page is
  a grid of tiles that can be dragged, resized, hidden, restored, reset, and
  locked, with each page remembering its own arrangement.
- **Log-derived AA** — three real AA line shapes parsed, including rank upgrades
  the vendored parser does not handle.
- `selftest.py` regression gate (344 checks) with auto-discovered suites, plus
  `tools/check_vendor_drift.py`, `tools/renormalize_keys.py`, and
  `tools/reparse_items.py`.

### Notes

- Combat parsing reuses `parser.py`, `tracker.py`, and `icons.py` vendored
  unmodified from [EQLegendsParser](https://github.com/Cujef/EQLegendsParser);
  see `vendor/eqlparser/PROVENANCE.md`.
- Known limits, surfaced in the UI rather than hidden: a few owned items exist
  on neither community site, `+N` upgrade stat scaling is in no item database,
  and exaltation transfer rules are assumed until confirmed.

[Unreleased]: https://github.com/Cujef/EQLegendsAssistant/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/Cujef/EQLegendsAssistant/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/Cujef/EQLegendsAssistant/releases/tag/v1.0.0

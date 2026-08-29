# Changelog

All notable changes to EQ Legends Assistant are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/Cujef/EQLegendsAssistant/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/Cujef/EQLegendsAssistant/releases/tag/v1.0.0

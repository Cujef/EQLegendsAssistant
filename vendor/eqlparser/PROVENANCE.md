# Vendored code provenance

These files are **byte-for-byte copies** from the EQLegendsParser project and must
never be edited here — with one documented exception, see "Deviations from
upstream" below. New log events or behavior changes belong in
`app/logscan/ext_parser.py` (which wraps `parse_line`) or elsewhere in `app/`.

- Upstream repo: https://github.com/Cujef/EQLegendsParser.git
- Upstream local checkout: a sibling clone of that repo. `tools/check_vendor_drift.py`
  looks for it via the `EQA_UPSTREAM_PARSER_DIR` env var, defaulting to
  `../EQLegendsParser` next to this repo; the check is a no-op when it isn't found.
- Copied: 2026-09-03 from a **clean** working tree at tag `v1.6.0`
  (commit `1cf1243`, 2026-09-03, "Add group accuracy, allies' damage shields, and
  faction/tradeskill tracking").
- Previous copy (2026-08-28) came from a dirty tree at `4d73697`; only `parser.py`
  changed since (+87 lines, nothing modified or deleted): faction, tradeskill
  (craft / craft_capped / depot_consume) and group-member miss / damage-shield events.

Line endings: the upstream checkout has `core.autocrlf=true`, so its working-tree
files are CRLF while the git blobs are LF. The copies here are the working-tree
bytes; both hashes are recorded so either form can be verified.
`tools/check_vendor_drift.py` compares EOL-insensitively.

SHA-256 at copy time (working tree, CRLF):

```
7278f23d32f607abdb885c1f650eb6f3664132776ee1ce2770a1e827ac9bb7c4  parser.py
d266f7eb54714ab97da5b16674b18a0ff8acbe4483c592094e8334e65cc6c517  tracker.py
b6c61ea7da28481ba077f54a96302f59a8830b1441a4441f55cbe7d619db3128  icons.py  (superseded — see below)
```

SHA-256 of the LF-normalized content (== `git show v1.6.0:<file> | sha256sum`):

```
eaff19c027b83c57fc518e6234be855c765e5c1d8567529581bf61846e726552  parser.py
d266f7eb54714ab97da5b16674b18a0ff8acbe4483c592094e8334e65cc6c517  tracker.py
b6c61ea7da28481ba077f54a96302f59a8830b1441a4441f55cbe7d619db3128  icons.py  (superseded — see below)
```

## Deviations from upstream

`icons.py` carries one deliberate, permanent patch made ahead of the public
release of this repo, and is excluded from `tools/check_vendor_drift.py`'s
automated comparison for that reason (it would otherwise show as drift forever).
Two lines changed:

- The Windows fallback install path (used only when env `EQ_UIFILES_DIR` is
  unset — dead code here, since `app/config.py` always sets it before this
  module is imported) was a developer's personal local path; it now reads the
  game's real default install location instead:
  `C:/Users/Public/Daybreak Game Company/Installed Games/EverQuest Legends`.
- A code comment naming a specific person was made second-person/generic.

SHA-256 of the patched `icons.py` (LF, matches the working copy here):

```
4f978c379e0350bc8281672a1fb67250cfae66896816c8c1fc11689730641d22  icons.py
```

When re-vendoring after an upstream change to `icons.py`: diff upstream's new
version against the hash recorded above (not against upstream HEAD directly),
reapply the same two edits, and update this hash.

Path notes for `icons.py` (why no other edits are needed):
- `UIFILES_DIR` reads env `EQ_UIFILES_DIR`, defaulting to `<install>/uifiles/default`.
- `CACHE_PATH` reads env `EQ_ICONS_PATH`; the app sets it to `data/icons.json` before import.
- `ICON_DIR` is `vendor/eqlparser/static/icons` (relative to the module); the app mounts
  that directory at `/static/icons`, matching the module's `ICON_URL`.

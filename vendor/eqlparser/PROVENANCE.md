# Vendored code provenance

These files are **byte-for-byte copies** from the EQLegendsParser project and must
never be edited here. New log events or behavior changes belong in
`app/logscan/ext_parser.py` (which wraps `parse_line`) or elsewhere in `app/`.

- Upstream repo: https://github.com/Cujef/EQLegendsParser.git
- Upstream local checkout: `J:\_EQLegendsParser`
- Copied: 2026-08-28
- Upstream HEAD at copy time: `4d73697` (2026-08-21, "Add table sorting, a configurable
  header, a Group meter, and CSV/JSON export") — **but the working tree was dirty
  (14 modified/untracked paths, unreleased v1.5.0 work)**, and the copy was taken from
  the working tree, not from HEAD. Re-vendor from a clean tag when upstream ships v1.5.0.

SHA-256 at copy time:

```
1d2b80f85798a89a3d46d3aa964be3e2ccce7e83a2e589b799c596e8a2885e09  parser.py
d266f7eb54714ab97da5b16674b18a0ff8acbe4483c592094e8334e65cc6c517  tracker.py
b6c61ea7da28481ba077f54a96302f59a8830b1441a4441f55cbe7d619db3128  icons.py
```

`python tools/check_vendor_drift.py` compares these copies against
`J:\_EQLegendsParser` and reports drift (warning only; selftest.py runs it).

Path notes for `icons.py` (why no edits are needed):
- `UIFILES_DIR` reads env `EQ_UIFILES_DIR`, defaulting to `J:/EQLegends/uifiles/default` — correct here.
- `CACHE_PATH` reads env `EQ_ICONS_PATH`; the app sets it to `data/icons.json` before import.
- `ICON_DIR` is `vendor/eqlparser/static/icons` (relative to the module); the app mounts
  that directory at `/static/icons`, matching the module's `ICON_URL`.

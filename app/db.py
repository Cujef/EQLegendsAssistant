"""SQLite persistence for EQ Legends Assistant (data/assistant.db).

Threading contract (adapted from the parser's db.py, simplified):
- ONE write connection, module-owned, guarded by _write_lock. All writers -
  request handlers, the importer thread, the sync worker, the tailer's fight
  persistence - go through execute()/executemany()/tx().
- tx() is the invariant carrier: bulk ingest flushes rows AND their
  log_source/sync checkpoint in the SAME transaction, so a crash can only leave
  a checkpoint *behind* its data, never ahead of it.
- Reads use short-lived read-only URI connections (reader()) so they never
  block on the writer. WAL + synchronous=NORMAL.

The parser uses a queue + dedicated writer thread because its tailer flushes at
1 Hz forever; our bulk writers flush in large chunks (seconds apart), so a lock
is enough and read-after-write CRUD stays trivial.
"""
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from .config import DATA_DIR

DB_PATH = DATA_DIR / 'assistant.db'

_write_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None
_tx_depth = 0  # guarded by _write_lock (RLock: same-thread nesting only)

# ── schema ────────────────────────────────────────────────────────────────────
# Forward-only migrations; PRAGMA user_version tracks the last applied index + 1.
MIGRATIONS = [
    """
    CREATE TABLE characters(
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        server TEXT NOT NULL,
        log_path TEXT,
        inventory_path TEXT,
        is_active INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL,
        UNIQUE(name, server)
    );
    CREATE TABLE manual_stats(
        character_id INTEGER NOT NULL REFERENCES characters(id),
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        updated_at REAL NOT NULL,
        PRIMARY KEY(character_id, key)
    );
    CREATE TABLE log_source(
        id INTEGER PRIMARY KEY,
        character_id INTEGER REFERENCES characters(id),
        path TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        first_ts REAL,
        byte_offset INTEGER NOT NULL DEFAULT 0,
        updated_at REAL,
        UNIQUE(path, fingerprint)
    );

    CREATE TABLE inventory_snapshots(
        id INTEGER PRIMARY KEY,
        character_id INTEGER NOT NULL REFERENCES characters(id),
        imported_at REAL NOT NULL,
        source_path TEXT,
        file_mtime REAL,
        raw_sha256 TEXT,
        parse_rev INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE inventory_items(
        id INTEGER PRIMARY KEY,
        snapshot_id INTEGER NOT NULL REFERENCES inventory_snapshots(id),
        location TEXT NOT NULL,          -- full dump string, e.g. "General 8-Slot3-Slot7"
        root TEXT NOT NULL,              -- before the first "-Slot", e.g. "General 8"
        parent_location TEXT,            -- location minus the last "-SlotN"; NULL for top level
        sub_slot INTEGER,                -- the last SlotN number; NULL for top level
        name TEXT NOT NULL,
        name_norm TEXT NOT NULL,         -- lowercased, "(Exaltation)"/"+N" stripped
        item_id INTEGER NOT NULL,
        count INTEGER NOT NULL,
        slots INTEGER NOT NULL,          -- container capacity (0 = not a container)
        is_empty INTEGER NOT NULL,
        is_exaltation INTEGER NOT NULL,
        upgrade_tier INTEGER NOT NULL DEFAULT 0,  -- the +N suffix, 0 if none
        is_equipped INTEGER NOT NULL
    );
    CREATE INDEX idx_inv_snapshot ON inventory_items(snapshot_id);
    CREATE INDEX idx_inv_name ON inventory_items(name_norm);

    CREATE TABLE items(
        name_norm TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        wiki_url TEXT,
        tools_url TEXT,
        source TEXT NOT NULL DEFAULT '',     -- 'wiki', 'tools', 'wiki+tools'
        icon INTEGER,                        -- drag-item icon number (wiki lucy_img_ID)
        slot_text TEXT, class_text TEXT, race_text TEXT,
        ac INTEGER, dmg INTEGER, delay INTEGER, haste_pct INTEGER,
        hp INTEGER, mana INTEGER,
        stats_json TEXT, resists_json TEXT,
        is_quest_item INTEGER NOT NULL DEFAULT 0,
        lore_flag INTEGER NOT NULL DEFAULT 0,
        magic_flag INTEGER NOT NULL DEFAULT 0,
        drops_json TEXT,                     -- [{zone, mob}] (tools site)
        raw_statsblock TEXT,
        parsed_ok INTEGER NOT NULL DEFAULT 0,
        conflict TEXT,
        fetched_at REAL
    );
    CREATE TABLE item_effects(
        name_norm TEXT NOT NULL,
        effect_type TEXT NOT NULL CHECK(effect_type IN ('focus','proc','worn','click')),
        effect_name TEXT NOT NULL,
        effect_family TEXT,
        effect_tier INTEGER,
        raw_line TEXT,
        PRIMARY KEY(name_norm, effect_type, effect_name)
    );
    CREATE TABLE effects(
        effect_name TEXT PRIMARY KEY,
        effect_type TEXT NOT NULL,
        description TEXT,
        source_url TEXT
    );

    CREATE TABLE quests(
        id INTEGER PRIMARY KEY,              -- wiki pageid when known
        name TEXT NOT NULL UNIQUE,
        wiki_url TEXT,
        start_zone TEXT, quest_giver TEXT,
        level_min INTEGER, level_max INTEGER,
        classes_json TEXT, races_json TEXT, categories_json TEXT,
        raw_wikitext TEXT,
        parsed_ok INTEGER NOT NULL DEFAULT 0,
        fetched_at REAL
    );
    CREATE TABLE quest_steps(
        quest_id INTEGER NOT NULL REFERENCES quests(id),
        step_index INTEGER NOT NULL,
        text TEXT NOT NULL,
        PRIMARY KEY(quest_id, step_index)
    );
    CREATE TABLE quest_item_mentions(
        quest_id INTEGER NOT NULL REFERENCES quests(id),
        item_name_norm TEXT NOT NULL,
        PRIMARY KEY(quest_id, item_name_norm)
    );
    CREATE TABLE quest_progress(
        character_id INTEGER NOT NULL REFERENCES characters(id),
        quest_id INTEGER NOT NULL REFERENCES quests(id),
        status TEXT NOT NULL CHECK(status IN ('tracked','completed','dismissed')),
        added_at REAL NOT NULL,
        completed_at REAL,
        PRIMARY KEY(character_id, quest_id)
    );
    CREATE TABLE quest_step_progress(
        character_id INTEGER NOT NULL,
        quest_id INTEGER NOT NULL,
        step_index INTEGER NOT NULL,
        done INTEGER NOT NULL DEFAULT 0,
        done_at REAL,
        PRIMARY KEY(character_id, quest_id, step_index)
    );

    CREATE TABLE guides(
        slug TEXT PRIMARY KEY,
        title TEXT,
        kind TEXT NOT NULL CHECK(kind IN ('leveling','zem','statistics','haste','tradeskill','exaltation','reference','other')),
        raw_wikitext TEXT,
        parsed_json TEXT,
        parsed_ok INTEGER NOT NULL DEFAULT 0,
        fetched_at REAL
    );
    CREATE TABLE stat_caps(
        stat TEXT NOT NULL,
        level INTEGER NOT NULL DEFAULT 0,    -- 0 = any level
        cap INTEGER NOT NULL,
        source TEXT NOT NULL CHECK(source IN ('wiki','fallback')),
        fetched_at REAL,
        PRIMARY KEY(stat, level, source)
    );

    CREATE TABLE skill_levels(
        character_id INTEGER NOT NULL,
        skill TEXT NOT NULL,
        level INTEGER NOT NULL,
        ts REAL NOT NULL,
        PRIMARY KEY(character_id, skill, level)
    );
    CREATE TABLE level_history(
        character_id INTEGER NOT NULL,
        level INTEGER NOT NULL,
        ts REAL NOT NULL,
        PRIMARY KEY(character_id, level)
    );
    CREATE TABLE aa_ledger(
        character_id INTEGER NOT NULL,
        ts REAL NOT NULL,
        kind TEXT NOT NULL CHECK(kind IN ('gain','spend')),
        ability_name TEXT,
        points INTEGER NOT NULL,
        balance_after INTEGER,
        PRIMARY KEY(character_id, ts, kind, ability_name)
    );
    CREATE TABLE deaths(
        character_id INTEGER NOT NULL,
        ts REAL NOT NULL,
        killer TEXT NOT NULL,
        PRIMARY KEY(character_id, ts)
    );
    CREATE TABLE highlights(
        character_id INTEGER NOT NULL,
        key TEXT NOT NULL,
        value_num REAL,
        value_text TEXT,
        ts REAL,
        context_json TEXT,
        PRIMARY KEY(character_id, key)
    );
    CREATE TABLE fights(
        id INTEGER PRIMARY KEY,
        character_id INTEGER NOT NULL,
        start REAL NOT NULL,
        name TEXT NOT NULL,
        duration REAL NOT NULL,
        dps REAL, total_damage INTEGER, total_healing INTEGER, total_tanking INTEGER,
        xp REAL, coin INTEGER,
        data TEXT NOT NULL,                  -- full Fight.to_dict() JSON
        UNIQUE(character_id, start, name)
    );

    CREATE TABLE sync_runs(
        id INTEGER PRIMARY KEY,
        source TEXT NOT NULL,
        started_at REAL NOT NULL,
        finished_at REAL,
        status TEXT NOT NULL DEFAULT 'running',
        pages_total INTEGER DEFAULT 0,
        pages_done INTEGER DEFAULT 0,
        errors INTEGER DEFAULT 0
    );
    CREATE TABLE sync_pages(
        url TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        kind TEXT NOT NULL,
        etag TEXT, lastmod TEXT, revid INTEGER, content_sha TEXT,
        fetched_at REAL,
        parse_ok INTEGER NOT NULL DEFAULT 0,
        parse_error TEXT
    );
    CREATE TABLE raw_pages(
        url TEXT PRIMARY KEY,
        content TEXT NOT NULL,
        fetched_at REAL NOT NULL
    );
    """,
    # the wiki worklist proved to be ~19k pages; every sync scans sync_pages by
    # source, which was a full-table scan
    """
    CREATE INDEX idx_sync_pages_source ON sync_pages(source);
    """,
]


def _connect_rw() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # isolation_level=None = autocommit; tx() manages BEGIN/COMMIT explicitly so
    # nested tx() (via the RLock) can no-op instead of double-BEGINning.
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def init() -> None:
    """Open the write connection and apply pending migrations. Idempotent."""
    global _conn
    with _write_lock:
        if _conn is not None:
            return
        conn = _connect_rw()
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        # executescript force-commits any open transaction, so migrations are not
        # crash-atomic; acceptable for a local app (recovery: delete data/assistant.db).
        for i, ddl in enumerate(MIGRATIONS[version:], start=version):
            conn.executescript(ddl)
            conn.execute(f'PRAGMA user_version = {i + 1}')
        _conn = conn


def close() -> None:
    global _conn
    with _write_lock:
        if _conn is not None:
            _conn.close()
            _conn = None


class tx:
    """Write transaction: `with db.tx() as c: c.execute(...)`. Commits on success.

    Nestable on the same thread: only the outermost level BEGINs/COMMITs, so
    helpers like execute() work both standalone and inside a larger tx().
    """

    def __enter__(self) -> sqlite3.Connection:
        global _tx_depth
        _write_lock.acquire()
        # if init()/BEGIN raises, __exit__ never runs — release or the lock
        # leaks and every writer in the app blocks forever
        try:
            if _conn is None:
                init()
            if _tx_depth == 0:
                _conn.execute('BEGIN')
            _tx_depth += 1
            return _conn
        except BaseException:
            _write_lock.release()
            raise

    def __exit__(self, exc_type, exc, tb):
        global _tx_depth
        try:
            _tx_depth -= 1
            if _tx_depth == 0:
                _conn.execute('COMMIT' if exc_type is None else 'ROLLBACK')
        finally:
            _write_lock.release()
        return False


def execute(sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    with tx() as c:
        return c.execute(sql, tuple(params))


def executemany(sql: str, rows: Iterable[Iterable[Any]]) -> None:
    with tx() as c:
        c.executemany(sql, [tuple(r) for r in rows])


def reader() -> sqlite3.Connection:
    """Short-lived read-only connection; caller closes (or use query helpers)."""
    conn = sqlite3.connect(f'file:{DB_PATH}?mode=ro', uri=True, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def query(sql: str, params: Iterable[Any] = ()) -> list:
    conn = reader()
    try:
        return [dict(r) for r in conn.execute(sql, tuple(params)).fetchall()]
    finally:
        conn.close()


def query_one(sql: str, params: Iterable[Any] = ()) -> Optional[dict]:
    rows = query(sql, params)
    return rows[0] if rows else None


def now() -> float:
    return time.time()

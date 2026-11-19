import os
import sqlite3

DATA = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
os.makedirs(DATA, exist_ok=True)
DB_PATH = os.path.join(DATA, "votes.db")


def conn():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA busy_timeout=15000")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def now():
    import time
    return time.strftime("%Y-%m-%d %H:%M:%S")


def init_db():
    with conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS rounds(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            closed_at TEXT
        );

        CREATE TABLE IF NOT EXISTS images(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id INTEGER NOT NULL,
            account_id TEXT NOT NULL,
            key TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            width INTEGER NOT NULL DEFAULT 0,
            height INTEGER NOT NULL DEFAULT 0,
            bytes INTEGER NOT NULL DEFAULT 0,
            sha256 TEXT NOT NULL DEFAULT '',
            title TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS votes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id INTEGER NOT NULL,
            image_id INTEGER NOT NULL,
            voter TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(round_id, voter)
        );

        CREATE TABLE IF NOT EXISTS accounts(
            key TEXT PRIMARY KEY,
            name TEXT NOT NULL DEFAULT '',
            active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            detail TEXT NOT NULL,
            t INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS meta(
            k TEXT PRIMARY KEY,
            v TEXT NOT NULL
        );
        """)
        # voter_id cookie shard
        cols = [r["name"] for r in con.execute("PRAGMA table_info(votes)").fetchall()]
        if "voter_id" not in cols:
            con.execute("ALTER TABLE votes ADD COLUMN voter_id TEXT DEFAULT ''")
        con.commit()

    # seed a demo round if empty (admin page depends on a round existing to show upload)
    with conn() as con:
        n = con.execute("SELECT COUNT(*) c FROM rounds").fetchone()["c"]
        if n == 0:
            con.execute("INSERT INTO rounds(title,status,created_at) VALUES(?, 'open', ?)",
                        ("第一轮 · 示例", now()))
            con.commit()

    # force a checkpoint now so no WAL file is left behind at import time
    with conn() as con:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.commit()


def get_meta(k, default=None):
    with conn() as con:
        r = con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r["v"] if r else default


def set_meta(k, v):
    with conn() as con:
        con.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, v))
        con.commit()


def get_or_create_admin_key():
    import secrets
    k = get_meta("admin_key")
    if not k:
        k = secrets.token_urlsafe(12)
        set_meta("admin_key", k)
    return k


init_db()

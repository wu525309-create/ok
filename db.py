import json
import os
import secrets
import sqlite3
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.environ.get("DATA_DIR", os.path.join(ROOT, "data"))
os.makedirs(DATA, exist_ok=True)
DB_PATH = os.path.join(DATA, "votes.db")
SEED_PATH = os.path.join(ROOT, "data", "seed.json")


def conn():
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA busy_timeout=15000")
    return con


def now():
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
            key TEXT NOT NULL UNIQUE,
            title TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS votes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            round_id INTEGER NOT NULL,
            image_id INTEGER NOT NULL,
            voter TEXT NOT NULL,
            voter_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            UNIQUE(round_id, voter)
        );

        CREATE TABLE IF NOT EXISTS meta(
            k TEXT PRIMARY KEY,
            v TEXT NOT NULL
        );
        """)
        con.commit()

    seed_if_empty()

    with conn() as con:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.commit()


def seed_if_empty():
    """从仓库里的 data/seed.json 载入初始轮次和作品。

    Vercel serverless 的文件系统是临时的，冷启动会重建 DB，所以这里每次
    启动都要确保数据库里有这一轮的图片清单。
    """
    with conn() as con:
        n = con.execute("SELECT COUNT(*) c FROM rounds").fetchone()["c"]
        if n:
            return
        seed = {"title": "第一轮 · 示例", "images": []}
        if os.path.isfile(SEED_PATH):
            try:
                with open(SEED_PATH, encoding="utf-8") as f:
                    seed = json.load(f)
            except Exception:
                pass
        cur = con.execute("INSERT INTO rounds(title,status,created_at) VALUES(?, 'open', ?)",
                          (seed.get("title") or "第一轮 · 示例", now()))
        rid = cur.lastrowid
        for im in seed.get("images", []):
            key = (im.get("key") or "").strip()
            if not key:
                continue
            con.execute("INSERT OR IGNORE INTO images(round_id,key,title,created_at) VALUES(?,?,?,?)",
                        (rid, key, im.get("title") or key, now()))
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
    k = get_meta("admin_key")
    if not k:
        k = secrets.token_urlsafe(12)
        set_meta("admin_key", k)
    return k


init_db()

import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi.testclient import TestClient

import app as app_module


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # isolate data dir so tests don't touch the real DB
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_KEY", "testadminkey123")

    import db
    db.DATA = str(tmp_path)
    db.DB_PATH = os.path.join(str(tmp_path), "votes.db")
    importlib.reload(db)
    importlib.reload(app_module)

    with TestClient(app_module.app) as c:
        yield c


def test_index_loads(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "图片投票" in r.text


def test_index_shows_seeded_image(client):
    # seed.json 里的 IMG_2478 应作为作品出现，且指向静态路径
    r = client.get("/")
    assert r.status_code == 200
    assert "/static/images/IMG_2478.jpg" in r.text


def test_static_image_is_served(client):
    r = client.get("/static/images/IMG_2478.jpg")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/")


def test_archive_loads(client):
    r = client.get("/archive")
    assert r.status_code == 200


def test_admin_requires_key(client):
    r = client.get("/admin")
    assert r.status_code == 200
    assert "作者入口" in r.text


def test_admin_login_wrong_key(client):
    r = client.post("/admin/login", data={"key": "wrong"})
    assert r.status_code == 200
    assert "密钥不对" in r.text


def test_admin_login_right_key_redirects(client):
    r = client.post("/admin/login", data={"key": "testadminkey123"}, follow_redirects=False)
    assert r.status_code in (302, 303)
    assert "/admin" in r.headers.get("location", "")


def test_admin_console_shows_image_management_hint(client):
    r = client.get("/admin", params={"key": "testadminkey123"})
    assert r.status_code == 200
    assert "static/images" in r.text


def test_vote_dedupe(client):
    import db
    con = db.conn()
    rnd = con.execute("SELECT * FROM rounds WHERE status='open' ORDER BY id DESC LIMIT 1").fetchone()
    img = con.execute("SELECT id FROM images WHERE round_id=? LIMIT 1", (rnd["id"],)).fetchone()
    img_id = img["id"]
    con.close()

    client.cookies.set("voter", "abcdefghijklmnop1234")
    r = client.post("/api/vote", json={"image_id": img_id})
    assert r.json()["ok"] is True
    # same voter again -> rejected
    r = client.post("/api/vote", json={"image_id": img_id})
    assert r.json()["ok"] is False


def test_vote_invalid_image(client):
    client.cookies.set("voter", "abcdefghijklmnop9999")
    r = client.post("/api/vote", json={"image_id": 999999})
    assert r.json()["ok"] is False

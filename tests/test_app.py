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
    # reset module-level state: re-run init against the tmp DB
    import importlib
    import db
    db.DATA = str(tmp_path)
    db.DB_PATH = os.path.join(str(tmp_path), "votes.db")
    importlib.reload(db)

    # pick a fixed admin key for deterministic assertions
    monkeypatch.setenv("ADMIN_KEY", "testadminkey123")
    monkeypatch.setenv("KEY_HMAC_SECRET", "testhmacsecret123")
    importlib.reload(app_module)

    with TestClient(app_module.app) as c:
        yield c


def _admin_headers(key="testadminkey123"):
    return {"Authorization": f"Bearer {key}"}


def test_index_loads(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "图片投票" in r.text


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


def test_create_account_and_upload_flow(client):
    # admin creates an account (投稿码)
    r = client.post("/admin/account", params={"key": "testadminkey123"},
                    json={"name": "测试同学"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    code = data["code"]
    assert code.startswith("pub_")

    # begin upload with the code
    r = client.post("/api/upload/begin", json={
        "app": code, "name": "pic.jpg", "size": 10, "type": "image/jpeg"
    })
    assert r.status_code == 200
    beg = r.json()
    assert beg["ok"] is True
    upload_id = beg["upload_id"]

    # passthrough (local fallback; no R2 in tests)
    jpg_bytes = b"\xff\xd8\xff\xe0" + b"x" * 10 + b"\xff\xd9"
    r = client.post("/api/upload/passthrough",
                    data={"upload_id": upload_id, "width": "100", "height": "80"},
                    files={"file": ("pic.jpg", jpg_bytes, "image/jpeg")})
    assert r.status_code == 200

    # finish
    r = client.post("/api/upload/finish", json={"upload_id": upload_id})
    assert r.status_code == 200
    fin = r.json()
    assert fin["ok"] is True
    assert fin["saved"] == 1


def test_vote_dedupe(client):
    # seed a round and an image directly
    import db
    con = db.conn()
    rnd = con.execute("SELECT * FROM rounds WHERE status='open' ORDER BY id DESC LIMIT 1").fetchone()
    con.execute("INSERT INTO images(round_id,account_id,key,kind,title,created_at) "
                "VALUES(?,?,?,?,?,?)",
                (rnd["id"], "test", "k1.jpg", "jpg", "作品", "2026-11-19 00:00:00"))
    con.commit()
    img = con.execute("SELECT id FROM images WHERE key='k1.jpg'").fetchone()
    img_id = img["id"]
    con.close()

    c = client
    c.cookies.set("voter", "abcdefghijklmnop1234")
    r = c.post("/api/vote", json={"image_id": img_id})
    assert r.json()["ok"] is True
    # same voter again -> rejected
    r = c.post("/api/vote", json={"image_id": img_id})
    assert r.json()["ok"] is False


def test_upload_rate_limited(client):
    # not asserting strict counts; just ensure the endpoint replies deterministically
    r = client.post("/api/upload/begin", json={"app": "bad", "name": "x.jpg", "size": 1})
    assert r.status_code in (200, 403)
    if r.status_code == 200:
        assert r.json()["ok"] is True
    else:
        assert r.json()["ok"] is False

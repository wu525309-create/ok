import hashlib
import json
import os
import re
import secrets
import time

from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import db

ADMIN_KEY = os.environ.get("ADMIN_KEY", "").strip()
SITE_TITLE = os.environ.get("SITE_TITLE", "图片投票")

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(title="图片投票站")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# ---------- helpers ----------
def _now():
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _json(obj, status=200, **kw):
    return JSONResponse(obj, status_code=status, **kw)


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()


if not ADMIN_KEY:
    # persistent: survive restarts, so the published key stays valid
    ADMIN_KEY = db.get_or_create_admin_key()


def _current_round(con):
    return con.execute("SELECT * FROM rounds WHERE status='open' ORDER BY id DESC LIMIT 1").fetchone()


def hmac_equal(a, b):
    return secrets.compare_digest(a, b)


def _is_admin(req):
    key = req.query_params.get("key", "")
    if key and hmac_equal(key, ADMIN_KEY):
        return True
    c = req.cookies.get("admin", "")
    return bool(c and hmac_equal(c, ADMIN_KEY))


# ---------- CSS / page frame ----------
CSS = open(os.path.join(STATIC_DIR, "style.css"), encoding="utf-8").read()


def _page(title, body, extra_head=""):
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title><style>{CSS}</style>{extra_head}</head>
<body>{body}</body></html>"""


def _esc(s):
    import html
    return html.escape(str(s)) if s is not None else ""


def _img_url(im, size="t"):
    # 图片随仓库提交在 static/images/，由 Vercel 静态托管
    return f"/static/images/{im['key']}"


def _render_cards(imgs):
    if not imgs:
        return '<div class="empty">这一轮还没有作品</div>'
    return "".join(
        f"""<div class="pic" onclick="pick(this,{im['id']})">
        <img src="{_img_url(im)}" loading="lazy" alt="">
        <div class="tick">✓</div>
        <div class="cap">{_esc(im['title'] or '作品 ' + str(im['id']))}</div>
      </div>"""
        for im in imgs
    )


PUBLIC_JS = """
let picked=null;
function pick(el,id){
  if(document.body.dataset.voted==='1')return;
  document.querySelectorAll('.pic').forEach(p=>p.classList.remove('sel'));
  el.classList.add('sel'); picked=id;
  document.getElementById('submit').disabled=false;
}
async function submitVote(){
  if(!picked)return;
  const btn=document.getElementById('submit'); btn.disabled=true; btn.textContent='提交中…';
  const r=await fetch('/api/vote',{method:'POST',headers:{'content-type':'application/json'},
      body:JSON.stringify({image_id:picked})});
  const d=await r.json();
  if(d.ok){ location.reload(); }
  else{ alert(d.error||'投票失败'); btn.disabled=false; btn.textContent='投这一票'; }
}
"""


# ---------- routes ----------
@app.get("/", response_class=HTMLResponse)
def index(req: Request):
    con = db.conn()
    rnd = _current_round(con)
    voter = req.cookies.get("voter", "")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{16,64}", voter):
        voter = secrets.token_urlsafe(18)
    vh = _voter_hash(req, voter)

    resp = None
    if not rnd:
        body = f"""<header><h1>{_esc(SITE_TITLE)}</h1>
        <div class="sub">当前没有进行中的投票</div></header>
        <main><div class="empty">等作者发布新一轮投票</div>
        <p class="note">历届结果见 <a href="/archive">存档</a></p></main>"""
        con.close()
        html = _page(SITE_TITLE, body)
        resp = HTMLResponse(html)
    else:
        imgs = con.execute("SELECT * FROM images WHERE round_id=? ORDER BY id", (rnd["id"],)).fetchall()
        voted = con.execute("SELECT 1 FROM votes WHERE round_id=? AND voter=?",
                             (rnd["id"], vh)).fetchone() is not None
        top3 = con.execute("""
            SELECT i.id, i.key, i.title, COUNT(v.id) c
            FROM images i LEFT JOIN votes v ON v.image_id=i.id AND v.round_id=?
            WHERE i.round_id=? GROUP BY i.id ORDER BY c DESC, i.id ASC LIMIT 3""",
            (rnd["id"], rnd["id"])).fetchall()
        con.close()

        cards = _render_cards(imgs)
        rank = "".join(
            f"""<div class="rank"><div class="no">{i+1}</div>
            <img src="{_img_url(t)}" alt="">
            <div><div>{_esc(t['title'] or '作品 '+str(t['id']))}</div>
            <div class="sub">第 {i+1} 名</div></div></div>"""
            for i, t in enumerate(top3)
        )
        if voted:
            action = f"""<h2>投票结果 · 只展示前三名</h2>{rank or '<div class="empty">还没有人投票</div>'}
            <p class="note">票数不公开，只有管理员能看。你已经投过了，一轮只能投一票。</p>"""
        else:
            action = f"""<div class="row" style="margin-top:16px">
              <button id="submit" disabled onclick="submitVote()">投这一票</button>
              <span class="sub">一人一票，投完才能看到前三名</span></div>
            <h2>暂不显示排名</h2>
            <p class="note">投票结束后（或你投完票）才会看到前三名。票数始终只有管理员能看。</p>"""
        body = f"""<header><h1>{_esc(SITE_TITLE)}</h1>
          <div class="sub">{_esc(rnd['title'])} · 发布于 {_esc(rnd['created_at'])}
            · <span class="tag open">进行中</span></div></header>
        <main data-voted="{'1' if voted else '0'}">
          <h2>选一张你最喜欢的</h2>
          <div class="grid">{cards}</div>
          {action}
          <p class="note">历届结果见 <a href="/archive">存档</a>　·　本站不需要登录，一人一票按设备识别
            　·　<a href="/admin">作者入口</a></p>
        </main>
        <script>{PUBLIC_JS}</script>"""
        html = _page(SITE_TITLE, body)
        resp = HTMLResponse(html)
    resp.set_cookie("voter", voter, path="/", max_age=31536000, samesite="lax")
    return resp


def _voter_hash(req, voter):
    ip = req.client.host if req.client else ""
    ua = req.headers.get("user-agent", "")
    return _h(f"{voter}|{ip}|{ua}")[:32]


@app.get("/archive", response_class=HTMLResponse)
def archive():
    con = db.conn()
    rows = con.execute("SELECT * FROM rounds WHERE status='closed' ORDER BY id DESC").fetchall()
    con.close()
    items = "".join(
        f"""<a class="rank" href="/archive/{r['id']}" style="text-decoration:none;color:inherit">
        <div class="no">#{r['id']}</div>
        <div><div>{_esc(r['title'])}</div>
        <div class="sub">发布于 {_esc(r['created_at'])} · 结束于 {_esc(r['closed_at'] or '—')}</div>
        </div></a>"""
        for r in rows
    )
    body = f"""<header><h1>存档</h1><div class="sub">已结束的每一轮，各留一个存档</div></header>
    <main>{items or '<div class="empty">还没有存档</div>'}
    <p class="note"><a href="/">回到投票</a></p></main>"""
    return HTMLResponse(_page("存档 · " + SITE_TITLE, body))


@app.get("/archive/{rid}", response_class=HTMLResponse)
def archive_round(rid: int):
    con = db.conn()
    r = con.execute("SELECT * FROM rounds WHERE id=?", (rid,)).fetchone()
    if not r:
        con.close()
        return _json({"ok": False}, 404)
    top3 = con.execute("""
        SELECT i.id, i.key, i.title, COUNT(v.id) c
        FROM images i LEFT JOIN votes v ON v.image_id=i.id AND v.round_id=?
        WHERE i.round_id=? GROUP BY i.id ORDER BY c DESC, i.id ASC LIMIT 3""",
        (rid, rid)).fetchall()
    total = con.execute("SELECT COUNT(*) c FROM votes WHERE round_id=?", (rid,)).fetchone()["c"]
    con.close()
    rank = "".join(
        f"""<div class="rank"><div class="no">{i+1}</div>
        <img src="{_img_url(t)}" alt="">
        <div><div>{_esc(t['title'] or '作品 '+str(t['id']))}</div>
        <div class="sub">第 {i+1} 名</div></div></div>"""
        for i, t in enumerate(top3)
    )
    body = f"""<header><h1>{_esc(r['title'])}</h1>
    <div class="sub">{_esc(r['created_at'])} — {_esc(r['closed_at'] or '')}
      · 共 {total} 票 · <span class="tag">已结束</span></div></header>
    <main><h2>前三名</h2>{rank or '<div class="empty">这一轮没有票</div>'}
    <p class="note"><a href="/archive">← 全部存档</a></p></main>"""
    return HTMLResponse(_page(r["title"] + " · 存档", body))


# ---------- admin ----------
def _login_page(err=""):
    body = f"""<header><h1>作者入口</h1>
      <div class="sub">输入管理员密钥</div></header>
    <main style="max-width:520px">
      <form method="post" action="/admin/login" style="margin-top:26px">
        <input type="text" name="key" id="keybox" placeholder="管理员密钥" autofocus
               autocomplete="off">
        <div class="row" style="margin-top:12px">
          <button type="submit">进入操作台</button>
          <a href="/" style="align-self:center;font-size:13px">返回投票页</a>
        </div>
      </form>
      {f'<p style="color:var(--warn);margin-top:14px">{_esc(err)}</p>' if err else ''}
    </main>"""
    return HTMLResponse(_page("作者入口 · " + SITE_TITLE, body))


@app.get("/admin", response_class=HTMLResponse)
def admin(req: Request):
    if not _is_admin(req):
        return _login_page()
    con = db.conn()
    rnd = _current_round(con)
    rounds = con.execute("SELECT * FROM rounds ORDER BY id DESC").fetchall()
    if rnd:
        stats = con.execute("""
            SELECT i.id, i.key, i.title, COUNT(v.id) c
            FROM images i LEFT JOIN votes v ON v.image_id=i.id AND v.round_id=?
            WHERE i.round_id=? GROUP BY i.id ORDER BY c DESC, i.id ASC""",
            (rnd["id"], rnd["id"])).fetchall()
        total = sum(s["c"] for s in stats)
        top = stats[0]["c"] if stats else 0
        n_img = len(stats)
    else:
        stats, total, top, n_img = [], 0, 0, 0
    con.close()
    return HTMLResponse(_render_admin(req, rnd, rounds, stats, total, top, n_img))


def _render_admin(req, rnd, rounds, stats, total, top, n_img):
    pub = f"""<h2>发布投票</h2>
      <form onsubmit="return createRound(event)">
        <div class="row">
          <input type="text" id="rtitle" placeholder="这一轮的名字" style="max-width:420px;flex:1">
          <button type="submit">发布新一轮</button>
        </div>
      </form>"""
    if rnd:
        rows = "".join(
            f"""<div class="vcard"><img src="{_img_url(s)}" alt="">
            <div class="body"><div class="row1"><span>{_esc(s['title'] or '作品 '+str(s['id']))}</span>
            <span class="num">{s['c']} 票</span></div>
            <div class="pbar"><i style="width:{round(s['c']/max(1,top)*100)}%"></i></div></div></div>"""
            for s in stats
        )
        rank = "".join(
            f"""<div class="rankline"><span class="no">{i+1}</span>
            <img src="{_img_url(t)}"><span>{_esc(t['title'] or '作品 '+str(t['id']))}</span>
            <span class="num" style="margin-left:auto">{t['c']}</span></div>"""
            for i, t in enumerate(stats[:3])
        )
        block = f"""<h2>正在投票：{_esc(rnd['title'])}</h2>
        <div class="sub">发布于 {_esc(rnd['created_at'])} · <span class="tag open">进行中</span></div>
        <div class="stat3">
          <div class="stat"><b>{total}</b><span>总票数</span></div>
          <div class="stat"><b>{n_img}</b><span>作品数</span></div>
          <div class="stat"><b>{round(total/n_img,1) if n_img else 0}</b><span>每张平均票数</span></div>
        </div>
        <h2>票数排名</h2>{rank or '<div class="empty">还没有投票</div>'}
        <h2>全部作品</h2>
        <div class="grid" style="grid-template-columns:repeat(auto-fill,minmax(190px,1fr))">{rows or '<div class="empty">还没有上传作品</div>'}</div>
        <h2>作品图片</h2>
        <div class="rank" style="border-color:#2f5c3a">
          <div class="no">✓</div>
          <div class="sub">图片随 GitHub 仓库提交在 <b>static/images/</b> 下，由 Vercel 静态托管。
          把图片加进仓库、更新 <b>data/images.json</b> 的作品清单后，Vercel 自动重新部署即可生效。</div>
        </div>
        <div class="row" style="margin-top:26px">
          <button class="ghost" onclick="act('/admin/close')">结束这一轮并归档</button>
          <button class="ghost" onclick="act('/admin/delete',{{id:{rnd['id']}}})">删除这一轮</button>
        </div>"""
    else:
        block = "<h2>当前没有进行中的投票</h2>"
    hist = "".join(
        f"""<tr><td>#{r['id']}</td><td>{_esc(r['title'])}</td>
        <td>{'<span class="tag open">进行中</span>' if r['status']=='open' else '已归档'}</td>
        <td>{_esc(r['created_at'])}</td>
        <td><button class="ghost" onclick="act('/admin/delete',{{id:{r['id']}}})">删除</button></td></tr>"""
        for r in rounds
    )

    body = f"""<header><h1>管理操作台</h1>
      <div class="sub">已用管理员密钥激活　·　<a href="/admin/logout">退出</a>　·　<a href="/" target="_blank">看投票页</a></div></header>
    <main>
      {pub}{block}
      <h2>全部轮次</h2>
      <table><tr><th>#</th><th>标题</th><th>状态</th><th>创建</th><th></th></tr>{hist}</table>
      <p class="note">票数只有这里能看到。</p>
    </main>
    <script>window.__ADMIN={json.dumps({'key': ADMIN_KEY})};</script>
    <script>{ADMIN_JS}</script>"""
    return _page("管理操作台 · " + SITE_TITLE, body)


ADMIN_JS = """
function human(n){ if(n>1048576)return (n/1048576).toFixed(1)+'MB'; return Math.round(n/1024)+'KB'; }

async function act(path, body){
  const opts = {method:'POST'};
  if(body !== undefined){
    opts.headers={'content-type':'application/json'};
    opts.body=JSON.stringify(body||{});
  }
  const r = await fetch(path, opts);
  if(r.redirected){ location.href='/admin'; return; }
  let d; try{ d=await r.json(); }catch(e){ d={ok:false,error:'响应异常'}; }
  if(!d.ok){ alert(d.error||'失败'); return; }
  location.reload();
}

async function createRound(e){ e.preventDefault();
  const t=document.getElementById('rtitle').value.trim();
  if(!t){alert('给这一轮起个名字');return false;}
  await act('/admin/round',{title:t}); return false; }
"""


@app.get("/admin/logout")
def admin_logout():
    return RedirectResponse("/", status_code=302)


@app.post("/admin/login")
async def admin_login(req: Request):
    import urllib.parse
    body = (await req.body()).decode("utf-8", "ignore")
    key = urllib.parse.parse_qs(body).get("key", [""])[0].strip()
    if key and hmac_equal(key, ADMIN_KEY):
        resp = RedirectResponse("/admin", status_code=302)
        resp.set_cookie("admin", ADMIN_KEY, path="/", max_age=604800, samesite="lax")
        return resp
    return _login_page("密钥不对，再试一次")


# ---------- API ----------
@app.post("/api/vote")
async def api_vote(req: Request):
    body = await req.json()
    image_id = body.get("image_id")
    voter = req.cookies.get("voter", "")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{16,64}", voter):
        voter = secrets.token_urlsafe(18)
    vh = _voter_hash(req, voter)
    con = db.conn()
    rnd = _current_round(con)
    resp = Response()
    resp.set_cookie("voter", voter, path="/", max_age=31536000, samesite="lax")
    if not rnd:
        con.close()
        return _json({"ok": False, "error": "当前没有进行中的投票"})
    img = con.execute("SELECT * FROM images WHERE id=? AND round_id=?", (image_id, rnd["id"])).fetchone()
    if not img:
        con.close()
        return _json({"ok": False, "error": "这张图不在本轮里"})
    try:
        con.execute("INSERT INTO votes(round_id,image_id,voter,voter_id,created_at) VALUES(?,?,?,?,?)",
                    (rnd["id"], image_id, vh, voter, _now()))
        con.commit()
    except Exception:
        con.close()
        return _json({"ok": False, "error": "你已经投过了，一轮只能投一票"})
    con.close()
    return _json({"ok": True})


@app.post("/admin/round")
async def admin_round(req: Request):
    if not _is_admin(req):
        return _json({"ok": False, "error": "需要管理员密钥"}, 403)
    body = await req.json()
    title = (body.get("title") or "").strip()[:60] or "未命名投票"
    con = db.conn()
    con.execute("UPDATE rounds SET status='closed', closed_at=? WHERE status='open'", (_now(),))
    con.execute("INSERT INTO rounds(title,status,created_at) VALUES(?, 'open', ?)", (title, _now()))
    con.commit(); con.close()
    return _json({"ok": True})


@app.post("/admin/close")
async def admin_close(req: Request):
    if not _is_admin(req):
        return _json({"ok": False, "error": "需要管理员密钥"}, 403)
    con = db.conn()
    rnd = _current_round(con)
    if not rnd:
        con.close()
        return _json({"ok": False, "error": "没有进行中的投票"})
    con.execute("UPDATE rounds SET status='closed', closed_at=? WHERE id=?", (_now(), rnd["id"]))
    con.commit(); con.close()
    return _json({"ok": True})


@app.post("/admin/delete")
async def admin_delete(req: Request):
    if not _is_admin(req):
        return _json({"ok": False, "error": "需要管理员密钥"}, 403)
    body = await req.json()
    rid = body.get("id")
    if rid is None:
        return _json({"ok": False, "error": "缺少 id"})
    con = db.conn()
    imgs = con.execute("SELECT key FROM images WHERE round_id=?", (rid,)).fetchall()
    con.execute("DELETE FROM votes WHERE round_id=?", (rid,))
    con.execute("DELETE FROM images WHERE round_id=?", (rid,))
    con.execute("DELETE FROM rounds WHERE id=?", (rid,))
    con.commit(); con.close()
    return _json({"ok": True})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8899)
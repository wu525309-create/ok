# 图片投票站

一个不需要登录、不需要密钥就能投票的小站。投票结果只显示前三名，**具体票数只有管理员能看到**。

图片随 GitHub 仓库提交，由 Vercel 静态托管 —— **无需任何对象存储、无需绑卡**，Vercel 免费档即可跑。

---

## 架构

```
图片文件  → static/images/*.jpg   （随仓库提交，Vercel 静态托管）
作品清单  → data/seed.json        （随仓库提交，冷启动时载入数据库）
投票数据  → SQLite                （临时，见下文「关于持久化」）
页面/接口 → Vercel serverless（app.py, FastAPI）
```

---

## 本地运行

需要 Python 3.9+。

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --host 0.0.0.0 --port 8899
```

- 公开页：http://127.0.0.1:8899/
- 管理员：http://127.0.0.1:8899/admin?key=你的密钥

首次启动若未设置 `ADMIN_KEY`，会**自动生成一个**并写入 `data/votes.db`。查看：

```bash
sqlite3 data/votes.db "select v from meta where k='admin_key';"
```

---

## 怎么加作品图片

因为图片是静态资源，加图 = 改仓库：

1. 把图片放进 `static/images/`（jpg / png / gif / webp，建议长边压到 1400px 以内、每张 ≤ 300 KB）。
2. 编辑 `data/seed.json`，把文件名加到 `images` 列表：

```json
{
  "title": "第一轮 · 作品征集",
  "images": [
    { "key": "IMG_2478.jpg", "title": "作品名字" },
    { "key": "photo2.jpg",  "title": "另一个名字" }
  ]
}
```

3. 提交并推送，Vercel 自动重新部署，新图片即生效。

> `seed.json` 只在**数据库为空时**载入一次。已经在运行、想换一批作品，最省事的做法是注册一个新的部署环境或清空数据库，再推送新的 `seed.json`。

---

## 部署到 Vercel（免费，不用绑卡）

1. 代码推到 GitHub（仓库已在 `origin`）。
2. 打开 [vercel.com](https://vercel.com)，用 GitHub 账号登录 → **Add New → Project** → 导入本仓库。
3. Framework 选 **Other**（会自动识别 Python）。
4. 在 **Environment Variables** 里填：

   | 变量 | 说明 |
   |---|---|
   | `ADMIN_KEY` | 管理员密钥（自己设一段强随机串，以后登录操作台用它） |
   | `SITE_TITLE` | 站点标题（可选） |

5. **Deploy** 即可。

部署完成后访问 `https://<你的项目>.vercel.app/admin?key=<ADMIN_KEY>` 进入操作台。

---

## 关于持久化（重要）

Vercel serverless 的文件系统是**临时**的：每次冷启动或重新部署，`data/votes.db` 会重建。

- **图片**在仓库里，永远在，不受影响。
- **票数**在本次运行期间正常累计；长时间闲置后冷启动可能**清零**。

对「一轮投票、几小时内投完」的班级活动，这通常不是问题。若要长期保存票数，可把 `db.py` 换成外部数据库（如 Neon Postgres 免费档，不需要绑卡）。告诉我即可改。

---

## 管理员能做什么

- 发布新一轮、结束归档、删除轮次
- 查看实时票数排名（票数只有这里看得到）
- 投票页只展示前三名，不显示数字

---

## 测试

```bash
.venv/bin/python -m pytest tests/ -q
```

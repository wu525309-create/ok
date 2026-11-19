# 图片投票站 v2

一个不需要登录、不需要密钥就能投票的小站。作者用微信就能发图，投票结果只显示前三名，**具体票数只有管理员能看到**。

相比 v1（单机 `server.py` + trycloudflare 隧道）的重写：

- **投稿与投票彻底分离** —— 每位投稿人（如 26 位同学）各拿一个「投稿码」，只能传图，不能看票数、不能删轮次（旧版是所有人共用管理员密钥）。
- **图片存 Cloudflare R2** 免费对象存储，浏览器直传 R2，Vercel 只签 URL，不经过 Vercel 转发。
- **本地压缩** —— 手机端先把图片压到 1400px 再传，小流量公网也能稳定传。
- **本地缓存 + 断点续传** —— 上传进度写 localStorage，中断后刷新可接着传。
- **上传限流** —— 每个投稿码按时间窗口限流，防刷。
- **SQLite 入库 + 显式 WAL checkpoint** —— 修复旧版 `with db() as con` 只提交不关闭、`-wal` 残留导致断电丢投票的问题。

---

## 架构

```
浏览器(微信) ──压缩图片──> /api/upload/begin  (Vercel 签一个 R2 预签名 URL)
        └─────────────────> PUT 直传 Cloudflare R2
        └─────────────────> /api/upload/finish (Vercel 落库)
投票/首页 ─────────────────> Vercel (读 SQLite + R2 公开 URL)
```

- 请求都打到 **Vercel**（serverless）。
- 图片二进制不经过 Vercel，直接进 **R2**，省带宽、稳。
- 元数据 + 票数存 **SQLite**（`/tmp` 或用 Vercel KV/Neon，见下文「生产环境」）。

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

首次启动若未设置 `ADMIN_KEY`，会**自动生成一个**并写入 `data/votes.db`。查看密钥：

```bash
sqlite3 data/votes.db "select v from meta where k='admin_key';"
```

> 不设置 R2 环境变量时，图片走本地磁盘回退（`data/images/`），方便开发测试。

---

## 配置 Cloudflare R2（存图）

1. 登录 [Cloudflare](https://dash.cloudflare.com/) → 左侧 **R2 Object Storage** → **Create bucket**（名字如 `vote-images`）。
2. 在 bucket 页签 **Settings**，记下 **Account ID**。
3. **Manage R2 API Tokens** → 创建 token，权限选对象读写，记下 **Access Key ID** 和 **Secret Access Key**。
4. 让图片能公开访问，二选一：
   - **自定义域**：bucket Settings → **Custom Domains** → 绑定一个你自己的域名（如 `files.你的域名.com`），开启 public access。
   - 或 **Cloudflare Worker** 反代 R2 提供公开 URL。

把上述值填进环境变量（见 `.env.example`）。

> R2 免费额度：10 GB 存储 / 每月，出网流量免费。26 人各传几张压缩后的图（每张约 100–300 KB），完全够。

---

## 一键部署到 Vercel

### 1. 推代码到 GitHub

> 下面命令需要本机有 `git` 身份和 GitHub 凭据（本仓库当前未配置）。请先：
>
> ```bash
> git config --global user.name  "你的名字"
> git config --global user.email "你的邮箱"
> gh auth login   # 或配置 SSH key / personal access token
> ```

```bash
cd 图片投票站-v2
git init
git add .
git commit -m "图片投票站 v2：R2 存图 + 投稿码 + 断点续传"
git branch -M main
git remote add origin https://github.com/<你的用户名>/vote-site.git
git push -u origin main
```

### 2. 在 Vercel 部署

1. 打开 [vercel.com](https://vercel.com)，用 GitHub 账号登录。
2. **Add New → Project** → 导入刚推送的仓库。
3. Framework 选 **Other**（或识别为 Python）。
4. 在 **Environment Variables** 里填（照着 `.env.example`）：

   | 变量 | 说明 |
   |---|---|
   | `ADMIN_KEY` | 管理员密钥（自己设一个强随机串） |
   | `KEY_HMAC_SECRET` | 投稿码签名密钥（强随机串） |
   | `R2_ACCOUNT_ID` / `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` / `R2_BUCKET` | R2 配置 |
   | `R2_PUBLIC_URL` | R2 公开前缀，如 `https://files.你的域名.com` |

5. **Deploy**。

完成后再按需回填 `R2_PUBLIC_URL`（部署前可先留空，用本地磁盘回退测试跑通，再切 R2）。

### 关于 SQLite 的注意点

Vercel serverless 的文件系统是**临时**的，重启会清空。小流量场景（26 人 + 一轮投票几小时）通常没问题，但若要**持久化**票数和图片元数据，任选其一：

- 换成 **Vercel KV** 或 **Neon (Postgres)**，把 `db.py` 的 SQLite 调用替换为对应客户端；
- 或把 `DATA_DIR` 指向一个挂载的持久卷（Vercel 目前不直接提供，推荐 Neon）。

图片本身在 R2，不受影响；只有 SQLite 需要持久化策略。

---

## 管理员怎么发投稿码

1. 打开 `/admin`（带密钥登录）。
2. 拉到「投稿人 · 投稿码」→ **+ 新增投稿码**，填名字（可选）。
3. 表格里出现一行 `pub_xxx_yyy` 的投稿码，把它发给对应的同学。
4. 同学在手机打开对应带上投稿码的上传入口，只能传图、不能看票数；你可随时「禁用」某个码。

---

## API 摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/` | 投票页 |
| GET | `/archive` `/archive/{id}` | 存档 |
| GET/POST | `/admin` 及 `/admin/login` | 管理台登录 |
| GET | `/admin` | 操作台（票数、投稿码、发布轮次） |
| POST | `/admin/account` | 新建投稿码 |
| POST | `/admin/round` `/admin/close` `/admin/delete` | 轮次管理 |
| POST | `/api/vote` | 投票 |
| POST | `/api/upload/begin` | 领取 R2 预签名上传 URL |
| POST | `/api/upload/passthrough` | （无 R2 时的本地回退接收） |
| POST | `/api/upload/finish` | 确认上传、落库 |

---

## 测试

```bash
.venv/bin/python -m pytest tests/ -q
```

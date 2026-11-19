import hashlib
import hmac
import os

# 图片随仓库提交，放在 static/images/ 下，由 Vercel 静态托管。
IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "images")

MAX_NAME_LEN = 128
ALLOWED = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def canonical_name(filename):
    """把原始文件名规整成项目内的安全文件名（保留扩展名）。"""
    base, ext = os.path.splitext(os.path.basename(filename or ""))
    ext = ext.lower()
    if ext not in ALLOWED:
        ext = ".jpg"
    slug = "".join(c for c in base if c.isalnum() or c in "-_.")[:40] or "img"
    return f"{slug}{ext}"


def hmac_token(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

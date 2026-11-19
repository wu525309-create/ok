import hashlib
import hmac
import os
import time
import uuid

import boto3

ACCOUNT_ID = os.environ.get("R2_ACCOUNT_ID", "")
ACCESS_KEY = os.environ.get("R2_ACCESS_KEY_ID", "")
SECRET_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
BUCKET = os.environ.get("R2_BUCKET", "")
PUBLIC_PREFIX = os.environ.get("R2_PUBLIC_URL", "").rstrip("/")
# For caching presign requests; None = disabled, else a boto3-compatible client
_cache_client = None

MAX_NAME_LEN = 128
ALLOWED = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif"}


def configured():
    return bool(ACCOUNT_ID and ACCESS_KEY and SECRET_KEY and BUCKET)


def _client():
    global _cache_client
    if _cache_client is None:
        _cache_client = boto3.client(
            "s3",
            endpoint_url=f"https://{ACCOUNT_ID}.r2.cloudflarestorage.com",
            aws_access_key_id=ACCESS_KEY,
            aws_secret_access_key=SECRET_KEY,
            region_name="auto",
        )
    return _cache_client


def canonical_name(account_id, filename):
    base, ext = os.path.splitext(filename)
    extl = ext.lower()
    if extl not in ALLOWED:
        extl = ".jpg"
    slug = "".join(c for c in base if c.isalnum() or c in "-_.")[:40] or "img"
    return f"{account_id}/{uuid.uuid4().hex[:12]}-{slug}{extl}"


def presign_upload(name, content_type, size_hint, expires=1800):
    return _client().generate_presigned_post(
        Bucket=BUCKET,
        Key=name,
        Fields={"Content-Type": content_type},
        Conditions=[
            {"Content-Type": content_type},
            ["content-length-range", 1, size_hint or 25 * 1024 * 1024],
        ],
        ExpiresIn=expires,
    )


def presign_complete(name, expires=1800):
    return _client().generate_presigned_url(
        "head_object", Params={"Bucket": BUCKET, "Key": name}, ExpiresIn=expires
    )


def delete(name):
    _client().delete_object(Bucket=BUCKET, Key=name)


def key_bucket_name(name):
    return BUCKET


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_signature(secret: str, d: dict) -> str:
    """HMAC-SHA256 over a stable canonical string of all non-empty scalar fields."""
    parts = []
    for k in sorted(d.keys()):
        v = d[k]
        if v is None or v == "":
            continue
        if isinstance(v, bool):
            v = "1" if v else "0"
        parts.append(f"{k}={v}")
    return hmac.new(secret.encode(), "&".join(parts).encode(), hashlib.sha256).hexdigest()


def hmac_token(secret: str, message: str) -> str:
    return hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()

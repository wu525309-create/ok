import collections
import json
import os
import time

_CONF_PATH = os.path.join(os.path.dirname(__file__), "rate_config.json")


def _conf():
    try:
        with open(_CONF_PATH, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _get(dotted, default):
    node = _conf()
    for k in dotted.split("."):
        node = node[k]
    return node


UPLOAD = _get("upload", {"recent": 18, "byte_burst": 96 * 1024 * 1024, "freeze": 5400})

# fixed-window rate limiter, keyed by account app_key
_events = collections.defaultdict(collections.deque)


def allow_upload(app_key):
    """Allow up to `recent` uploads per `freeze` seconds per account id.

    Returns (allowed, message). In-memory: resets on cold start, which is fine
    for a small-traffic event (26 uploaders, one round).
    """
    if not app_key:
        return True, ""
    window = _events[f"up:{app_key}"]
    t = time.time()
    while window and t - window[0] > UPLOAD.get("freeze", 5400):
        window.popleft()
    if len(window) >= UPLOAD.get("recent", 18):
        return False, "上传太频繁，请稍候再试"
    window.append(t)
    return True, ""

import os
import sys

# 把项目根目录加入模块搜索路径，才能 import 到根目录下的 app / db / storage
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402  (Vercel 查找名为 `app` 的 ASGI 实例)

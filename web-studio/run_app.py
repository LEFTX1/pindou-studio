# -*- coding: utf-8 -*-
"""
豆绘工坊（Pindou Studio）本地启动入口。
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

WEB_STUDIO_ROOT = Path(__file__).resolve().parent
if str(WEB_STUDIO_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_STUDIO_ROOT))


def _find_available_port(preferred: int) -> int:
    """优先使用首选端口，若被其他进程占用则向后探测可用端口。"""
    for candidate in [preferred, 8787, 8788, 8789, 8790]:
        s = socket.socket()
        try:
            s.bind(("127.0.0.1", candidate))
            return candidate
        except OSError:
            continue
        finally:
            s.close()
    return preferred


def main() -> None:
    parser = argparse.ArgumentParser(description="启动 豆绘工坊 Pindou Studio")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    port = _find_available_port(args.port)
    url = f"http://{args.host}:{port}"
    print(f"[豆绘工坊] 正在启动本地工坊服务: {url}")

    if not args.no_browser:
        def _open() -> None:
            time.sleep(1.2)
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    uvicorn.run("app.server:app", host=args.host, port=port, reload=False)


if __name__ == "__main__":
    main()

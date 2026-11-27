# -*- coding: utf-8 -*-
"""
一键生成豆绘工坊云端自更新配置文件 `update/version.json`：
自动计算已签名 Release APK 的 SHA-256 校验码并组装国内多镜像容灾直链。

用法示例:
  python scripts/publish_update_manifest.py ^
    --apk android-app/app/build/outputs/apk/release/app-release.apk ^
    --version-code 2 ^
    --version-name 1.1.0 ^
    --changelog "修复眼部对齐并提升渲染速度" ^
    --github-url "https://github.com/myuser/pindou/releases/download/v1.1.0/app-release.apk" ^
    --china-direct-url "https://dl.example.cn/pindou-v1.1.0.apk" ^
    --fallback-page "https://www.123pan.com/s/xxxxxx"
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def compute_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().lower()


def main() -> None:
    ap = argparse.ArgumentParser(description="生成国内多镜像免服务器更新清单 version.json")
    ap.add_argument("--apk", required=True, help="APK 文件路径")
    ap.add_argument("--version-code", type=int, required=True, help="递增整数版本号")
    ap.add_argument("--version-name", required=True, help="展示版本名，如 1.1.0")
    ap.add_argument("--changelog", default="日常性能优化与体验提升", help="更新日志")
    ap.add_argument("--china-direct-url", action="append", default=[], help="国内直连或免费对象存储直链（可多次指定）")
    ap.add_argument("--github-url", default="", help="GitHub Release 下载地址（自动生成国内 ghfast 镜像前缀 + 原链）")
    ap.add_argument("--fallback-page", default="", help="免登录网盘/发布页兜底链接（如 123云盘 / 蒲公英 / GitCode Release）")
    ap.add_argument("--force", action="store_true", help="是否强制升级弹窗")
    ap.add_argument("--out", default="update/version.json", help="输出 manifest 路径")
    args = ap.parse_args()

    apk_path = Path(args.apk)
    if not apk_path.is_file():
        raise SystemExit(f"找不到 APK 文件: {apk_path}")

    mirrors: list[str] = [u.strip() for u in args.china_direct_url if u.strip()]
    gh = args.github_url.strip()
    if gh:
        mirrors.append(f"https://ghfast.top/{gh}")
        mirrors.append(f"https://gh-proxy.com/{gh}")
        mirrors.append(gh)

    payload = {
        "versionCode": args.version_code,
        "versionName": args.version_name,
        "forceUpdate": bool(args.force),
        "sha256": compute_sha256(apk_path),
        "sizeBytes": apk_path.stat().st_size,
        "changelog": args.changelog,
        "apkMirrors": mirrors,
        "fallbackPageUrl": args.fallback_page.strip(),
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已生成: {out_path} (SHA-256={payload['sha256']}, size={payload['sizeBytes']} bytes)")


if __name__ == "__main__":
    main()

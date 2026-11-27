# -*- coding: utf-8 -*-
"""
一键生成豆绘工坊云端自更新配置文件 `update/version.json`：
- 自动计算已签名 Release APK 的 SHA-256 校验码并组装国内多镜像容灾直链；
- 自动累积 `releaseHistory` 版本历史，跨多个未升级版本时客户端一次安装最新包即可合并展示中间全部更新日志。
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
    ap.add_argument("--version-name", required=True, help="展示版本名，如 1.2.5")
    ap.add_argument("--changelog", default="日常性能优化与体验提升", help="更新日志")
    ap.add_argument("--china-direct-url", action="append", default=[], help="国内直连或免费对象存储直链（可多次指定）")
    ap.add_argument("--github-url", default="", help="GitHub Release 下载地址（自动生成国内 ghfast 镜像前缀 + 原链）")
    ap.add_argument("--repo-url", default="https://github.com/LEFTX1/pindou-studio", help="GitHub 仓库主页地址")
    ap.add_argument("--fallback-page", default="https://github.com/LEFTX1/pindou-studio/releases", help="发布页兜底链接")
    ap.add_argument("--force", action="store_true", help="是否强制升级弹窗")
    ap.add_argument("--out", default="update/version.json", help="输出 manifest 路径")
    args = ap.parse_args()

    apk_path = Path(args.apk)
    if not apk_path.is_file():
        raise SystemExit(f"找不到 APK 文件: {apk_path}")

    out_path = Path(args.out)
    existing_history: dict[int, dict] = {}
    if out_path.is_file():
        try:
            prev = json.loads(out_path.read_text(encoding="utf-8"))
            for item in prev.get("releaseHistory", []):
                vc = int(item.get("versionCode", 0))
                if vc > 0:
                    existing_history[vc] = {
                        "versionCode": vc,
                        "versionName": str(item.get("versionName", vc)),
                        "notes": str(item.get("notes", "")).strip(),
                    }
            prev_vc = int(prev.get("versionCode", 0))
            if prev_vc > 0 and prev_vc not in existing_history:
                existing_history[prev_vc] = {
                    "versionCode": prev_vc,
                    "versionName": str(prev.get("versionName", prev_vc)),
                    "notes": str(prev.get("changelog", "")).strip(),
                }
        except Exception:
            pass

    existing_history[args.version_code] = {
        "versionCode": args.version_code,
        "versionName": args.version_name,
        "notes": args.changelog.strip(),
    }
    ordered_history = [existing_history[k] for k in sorted(existing_history.keys(), reverse=True)][:20]

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
        "repoUrl": args.repo_url.strip(),
        "changelog": args.changelog,
        "releaseHistory": ordered_history,
        "apkMirrors": mirrors,
        "fallbackPageUrl": args.fallback_page.strip(),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已生成: {out_path} (SHA-256={payload['sha256']}, history={len(ordered_history)} versions)")


if __name__ == "__main__":
    main()

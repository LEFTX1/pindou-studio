import json
import os
import shutil
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE_DIR = Path(r"C:\Users\Administrator\.gemini\antigravity\scratch\pindou-project\repos")
BASE_DIR.mkdir(parents=True, exist_ok=True)

HEADERS = {"User-Agent": "antigravity-pindou-downloader/1.0"}


def fetch_json(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_raw(owner: str, repo: str, branch: str, remote_path: str, local_path: Path) -> str:
    url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{remote_path}"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = resp.read()
    local_path.write_bytes(data)
    return str(local_path)


def collect_repo_files(owner: str, repo: str, target_subdir: Path, path_prefixes: list[str] | None, extra_files: list[str] | None = None):
    info = fetch_json(f"https://api.github.com/repos/{owner}/{repo}")
    branch = info.get("default_branch", "main")
    tree_resp = fetch_json(f"https://api.github.com/repos/{owner}/{repo}/git/trees/{branch}?recursive=1")
    blobs = [item["path"] for item in tree_resp.get("tree", []) if item.get("type") == "blob"]

    selected = []
    for p in blobs:
        if path_prefixes is None:
            selected.append((p, p))
        else:
            matched = False
            for pref in path_prefixes:
                if p.startswith(pref):
                    # If pref ends with / strip prefix up to last folder? No, keep clean mapping
                    selected.append((p, p))
                    matched = True
                    break
            if not matched and extra_files and p in extra_files:
                selected.append((p, p))
    return branch, selected


def main():
    jobs = [
        # (owner, repo, target_name, strip_prefix, prefixes, extra_files)
        ("kuizuo", "pin-dou", "image-to-pindou", "skills/image-to-pindou/", ["skills/image-to-pindou/"], None),
        ("Zippland", "perler-beads", "Zippland_perler-beads", "", ["src/"], ["package.json", "README.md"]),
        ("Jett-Wu", "Perler_Beads_Generator", "JettWu_Perler_Beads_Generator", "", ["src/"], ["package.json", "README.md"]),
        ("saratran", "bead-tune", "saratran_bead-tune", "", ["src/lib/"], ["package.json", "README.md"]),
        ("Ibook000", "beadforge", "Ibook000_beadforge", "", ["src/color/", "src/pipeline/", "src/palette/"], ["package.json", "README.md"]),
        ("cornelk", "beadmachine", "beadmachine", "", None, None),
        ("KerroKapple", "Perler", "KerroKapple_Perler", "", None, None),
    ]

    download_tasks = []
    for owner, repo, target_name, strip_prefix, prefixes, extras in jobs:
        print(f"Inspecting {owner}/{repo}...")
        branch, selected = collect_repo_files(owner, repo, BASE_DIR / target_name, prefixes, extras)
        print(f"  branch={branch}, files={len(selected)}")
        for remote_path, rel_path in selected:
            if strip_prefix and rel_path.startswith(strip_prefix):
                rel_path = rel_path[len(strip_prefix):]
            local_path = BASE_DIR / target_name / rel_path
            download_tasks.append((owner, repo, branch, remote_path, local_path))

    print(f"Downloading {len(download_tasks)} files...")
    ok = 0
    errors = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        futs = {
            pool.submit(download_raw, o, r, b, rp, lp): (o, r, rp)
            for (o, r, b, rp, lp) in download_tasks
        }
        for fut in as_completed(futs):
            meta = futs[fut]
            try:
                fut.result()
                ok += 1
            except Exception as e:
                errors.append((meta, str(e)))
    print(f"Downloaded {ok}/{len(download_tasks)} files.")
    if errors:
        print("Errors:", errors[:10])
        raise SystemExit(1)

    # Copy image-to-pindou to global skills dir
    global_skill_dir = Path(r"C:\Users\Administrator\.gemini\config\skills\image-to-pindou")
    if global_skill_dir.exists():
        shutil.rmtree(global_skill_dir)
    shutil.copytree(BASE_DIR / "image-to-pindou", global_skill_dir)
    print(f"Copied skill to {global_skill_dir}")


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""创建 GitHub Release 并上传 zip 资产（Windows 兼容版）。

用 git-credential-manager 取已有凭据，不在脚本中留存 token。
"""
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error

REPO = "microsnow/pick-text"
GCM = ("C:/Users/microsnow/AppData/Local/Programs/WorkBuddy/resources/"
       "vendor/PortableGit/mingw64/bin/git-credential-manager.exe")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TAG = "v2.0.1"
ZIP = os.path.join(ROOT, "dist", "PickText-win64-v2.0.1.zip")


def get_token():
    proc = subprocess.run([GCM, "get"], input="protocol=https\nhost=github.com\n\n",
                          capture_output=True, text=True, timeout=60)
    for line in proc.stdout.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("未能获取 GitHub 凭据")


TOKEN = get_token()
print(f"凭据已获取（长度 {len(TOKEN)}）")


def api(method, url, data=None, raw=None, content_type=None):
    hdrs = {"Authorization": f"Bearer {TOKEN}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "picktext-release"}
    body = None
    if raw is not None:
        body = raw
        hdrs["Content-Type"] = content_type
    elif data is not None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


# 1) 创建 Release（正文取自 RELEASE_v2.0.1.md，去掉顶部 H1）
text = open(os.path.join(ROOT, "RELEASE_v2.0.1.md"), encoding="utf-8").read()
lines = text.split("\n")
if lines and lines[0].startswith("# "):
    lines = lines[1:]
body = "\n".join(lines).lstrip("\n")

status, raw = api("POST", f"https://api.github.com/repos/{REPO}/releases",
                  data={"tag_name": TAG, "name": "拾字 PickText v2.0.1",
                        "body": body, "draft": False, "prerelease": False})
print(f"[1] 创建 Release: HTTP {status}")
rel = json.loads(raw)
if status not in (200, 201):
    raise SystemExit(f"创建失败: {rel.get('message')} {rel.get('errors')}")
rel_id = rel["id"]
print("✅", rel["html_url"])

# 2) 上传 zip 资产（97.9 MB，走 uploads 接口并带 Content-Length）
size = os.path.getsize(ZIP)
url = (f"https://uploads.github.com/repos/{REPO}/releases/{rel_id}/assets"
       f"?name={os.path.basename(ZIP)}")
print(f"[2] 上传资产 {os.path.basename(ZIP)} ({size/1024/1024:.1f} MB) …")
with open(ZIP, "rb") as f:
    data = f.read()
hdrs = {"Authorization": f"Bearer {TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "picktext-release",
        "Content-Type": "application/zip",
        "Content-Length": str(len(data))}
req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
try:
    with urllib.request.urlopen(req, timeout=1800) as r:
        asset = json.loads(r.read())
    print("✅ 上传成功:", asset["browser_download_url"])
except urllib.error.HTTPError as e:
    print(f"❌ 上传失败 HTTP {e.code}: {e.read()[:300]}")
    raise SystemExit(1)
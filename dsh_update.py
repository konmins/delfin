# -*- coding: utf-8 -*-
"""
dsh 版本检查 / 本地受管运行时安装（纯逻辑，无 GUI 依赖，便于单独测试）
被 dsh-tray.py 引用。
"""
import json
import os
import shutil
import subprocess
import time
import urllib.request

PKG_NAME = "@deepseek-ai/dsh"
REGISTRY_URL = "https://registry.npmjs.org/" + PKG_NAME.replace("/", "%2f")
CHANNELS = ("latest", "next", "alpha")

CREATE_NO_WINDOW = 0x08000000


# ---------- semver ----------
def ver_key(v):
    """semver 比较键：正式版 > 预发布版，逐段比较"""
    core, _, pre = (v or "0").partition("-")
    nums = [int(x) if x.isdigit() else 0 for x in core.split(".")]
    while len(nums) < 3:
        nums.append(0)
    if not pre:
        return (tuple(nums), 1, ())
    ids = [(0, int(p)) if p.isdigit() else (1, p) for p in pre.split(".")]
    return (tuple(nums), 0, tuple(ids))


def is_newer(new, old):
    return ver_key(new) > ver_key(old)


# ---------- 版本查询 ----------
def local_version(runtime_pkg):
    """读取本地受管运行时的版本；未安装返回 None"""
    try:
        with open(runtime_pkg, encoding="utf-8") as f:
            return json.load(f).get("version")
    except Exception:
        return None


def fetch_dist_tags(timeout=15):
    """查询 npm registry 的 dist-tags"""
    req = urllib.request.Request(REGISTRY_URL, headers={
        "User-Agent": "dsh-tray",
        "Accept": "application/vnd.npm.install-v1+json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    tags = data.get("dist-tags", {})
    if not tags:
        raise RuntimeError("registry 未返回 dist-tags")
    return tags


def resolve_remote(channel="latest"):
    """返回指定通道的最新版本号"""
    tags = fetch_dist_tags()
    return tags.get(channel) or tags.get("latest")


# ---------- 本机 npm / node ----------
def npm_cmd():
    for name in ("npm.cmd", "npm"):
        p = shutil.which(name)
        if p:
            return p
    node = shutil.which("node") or shutil.which("node.exe")
    if node:
        cand = os.path.join(os.path.dirname(node), "npm.cmd")
        if os.path.exists(cand):
            return cand
    return None


def node_cmd():
    p = shutil.which("node") or shutil.which("node.exe")
    if p:
        return p
    npm = npm_cmd()
    if npm:
        cand = os.path.join(os.path.dirname(npm), "node.exe")
        if os.path.exists(cand):
            return cand
    return None


# ---------- 本地受管运行时 ----------
MANIFEST = {
    "name": "dsh-runtime",
    "private": True,
    "version": "1.0.0",
    "description": "本地受管 dsh 运行时（由 dsh-tray 更新/维护）",
    "dependencies": {},
}


def ensure_manifest(runtime_dir):
    """确保受管运行时目录与 package.json 存在"""
    os.makedirs(runtime_dir, exist_ok=True)
    path = os.path.join(runtime_dir, "package.json")
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(MANIFEST, f, ensure_ascii=False, indent=2)
    return path


def install(runtime_dir, version, log_path=None, timeout=1800):
    """把指定版本装进本地运行时的 node_modules；返回 (是否成功, 错误信息)"""
    npm = npm_cmd()
    if not npm:
        return False, "未找到 npm，请确认 Node.js 已加入 PATH"
    ensure_manifest(runtime_dir)
    cmd = [npm, "install", "%s@%s" % (PKG_NAME, version), "--prefix", runtime_dir,
           "--save-exact", "--no-audit", "--no-fund", "--loglevel=error"]
    try:
        if log_path:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "a", encoding="utf-8") as log:
                log.write("\n=== %s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), " ".join(cmd)))
                log.flush()
                p = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=CREATE_NO_WINDOW, timeout=timeout)
        else:
            p = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                               creationflags=CREATE_NO_WINDOW, timeout=timeout)
        if p.returncode != 0:
            return False, "npm 退出码 %s%s" % (p.returncode, "，详见 logs\\update.log" if log_path else "")
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "安装超时（%d 分钟）" % (timeout // 60)
    except Exception as e:
        return False, str(e)

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
PKG_URL_PATH = "/" + PKG_NAME.replace("/", "%2f")
DEFAULT_REGISTRY = "https://registry.npmjs.org"
CHANNELS = ("latest", "next", "alpha")

CREATE_NO_WINDOW = 0x08000000

# ---------------------------------------------------------------------------
# 为什么不能硬编码 registry.npmjs.org
#
# 2026-09-18 本机实测（每源 4 次，超时 15s）：
#   registry.npmjs.org        3/4 成功，成功时 1.4s，失败时撞满 15s 超时
#   registry.npmmirror.com    4/4 成功，0.2s
#
# 原实现硬编码官方源 + 单次请求 + 零重试，于是「点更新 → 最长 15 秒毫无反应
# → 提示检查更新失败」。更隐蔽的是：`npm install` 走的是用户 npm 配置里的
# registry（本机是 npmmirror），查询却走官方源 —— 两边不一致时就会出现
# 「查得到却装不上」或「装得上却查不到」的错位。
# 所以这里跟随 npm 自己配置的 registry，官方源仅作回退。
# ---------------------------------------------------------------------------
_registry = {"done": False, "value": None}


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
    # 兜底：PATH 里没有（双击 exe 启动时 PATH 可能不完整）就去常见位置找
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                 os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                 os.path.join(os.environ.get("LOCALAPPDATA") or "", "Programs"),
                 os.environ.get("APPDATA") or ""):
        if not base:
            continue
        for rel in (("nodejs", "npm.cmd"), ("npm", "npm.cmd")):
            cand = os.path.join(base, *rel)
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


# ---------- registry 探测 ----------
def _npmrc_registry():
    """从 .npmrc 读 registry（不启子进程，最快路径）"""
    cands = []
    for key in ("NPM_CONFIG_USERCONFIG", "npm_config_userconfig"):
        v = os.environ.get(key)
        if v:
            cands.append(v)
    cands.append(os.path.join(os.path.expanduser("~"), ".npmrc"))
    npm = npm_cmd()
    if npm:
        # 全局 npmrc：<node 目录>/../etc/npmrc
        cands.append(os.path.normpath(
            os.path.join(os.path.dirname(npm), "..", "etc", "npmrc")))
    for path in cands:
        try:
            with open(path, encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.split("#", 1)[0].split(";", 1)[0].strip()
                    if "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    if key.strip().lower() != "registry":
                        continue
                    val = val.strip().strip('"').strip("'")
                    if val.startswith("http"):
                        return val.rstrip("/")
        except Exception:
            continue
    return None


def _ask_npm_registry():
    """读不到 .npmrc 时问 npm 自己（较慢，仅兜底）"""
    npm = npm_cmd()
    if not npm:
        return None
    try:
        p = subprocess.run([npm, "config", "get", "registry"],
                           capture_output=True, text=True, timeout=8,
                           creationflags=CREATE_NO_WINDOW)
        v = (p.stdout or "").strip()
        return v.rstrip("/") if v.startswith("http") else None
    except Exception:
        return None


def configured_registry():
    """npm 当前生效的 registry（进程内缓存）。环境变量 DSH_NPM_REGISTRY 可强制覆盖。"""
    if not _registry["done"]:
        val = (os.environ.get("DSH_NPM_REGISTRY")
               or _npmrc_registry()
               or _ask_npm_registry())
        _registry["value"] = val.rstrip("/") if val else None
        _registry["done"] = True
    return _registry["value"]


def registry_candidates():
    """查询顺序：npm 配置的 registry（通常本地化、更快）→ 官方源"""
    out, seen = [], set()
    for reg in (configured_registry(), DEFAULT_REGISTRY):
        if not reg:
            continue
        reg = reg.rstrip("/")
        if reg.lower() in seen:
            continue
        seen.add(reg.lower())
        out.append(reg)
    return out


# ---------- 版本查询 ----------
def local_version(runtime_pkg):
    """读取本地受管运行时的版本；未安装返回 None"""
    try:
        with open(runtime_pkg, encoding="utf-8") as f:
            return json.load(f).get("version")
    except Exception:
        return None


def _fetch_tags_once(registry, timeout):
    req = urllib.request.Request(registry + PKG_URL_PATH, headers={
        "User-Agent": "delfin",
        "Accept": "application/vnd.npm.install-v1+json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    tags = data.get("dist-tags") or {}
    if not tags:
        raise RuntimeError("registry 未返回 dist-tags")
    return tags


def fetch_dist_tags(timeout=10, tries=2, registry=None):
    """查询 dist-tags：按候选源顺序试，任一成功即返回。

    失败时把**每个源各自的错误**合并抛出 —— 否则用户只会看到一句
    「urlopen error」，既不知道卡在哪，也不知道下一步该做什么。

    registry=None（默认）时走 registry_candidates()；显式传入则只查该源。
    """
    cands = [registry.rstrip("/")] if registry else registry_candidates()
    errors = []
    for reg in cands:
        last = None
        for attempt in range(tries):
            try:
                return _fetch_tags_once(reg, timeout)
            except Exception as e:
                last = "%s: %s" % (type(e).__name__, e)
                if attempt + 1 < tries:
                    time.sleep(1.0)
        errors.append("%s → %s" % (reg, last))
    raise RuntimeError("；".join(errors) or "没有可用的 registry")


def resolve_remote(channel="latest"):
    """返回指定通道的最新版本号"""
    tags = fetch_dist_tags()
    return tags.get(channel) or tags.get("latest")


# ---------- 本地受管运行时 ----------
MANIFEST = {
    "name": "dsh-runtime",
    "private": True,
    "version": "1.0.0",
    "description": "本地受管 dsh 运行时（由 Delfin 更新/维护）",
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
    """把指定版本装进本地运行时的 node_modules；返回 (是否成功, 错误信息)

    日志从**第一行**就开始写：旧实现在 `npm_cmd()` 返回 None 或
    `ensure_manifest()` 抛异常时直接 return，什么都不留 ——
    用户看到「更新失败」却翻不到任何日志，等于断案无据。
    """
    npm = npm_cmd()
    log = None
    if log_path:
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            log = open(log_path, "a", encoding="utf-8")
        except Exception:
            log = None

    def _log(line):
        if log:
            try:
                log.write(line + "\n")
                log.flush()
            except Exception:
                pass

    try:
        _log("\n=== %s  install dsh@%s" % (time.strftime("%Y-%m-%d %H:%M:%S"), version))
        _log("    npm        = %s" % (npm or "未找到"))
        _log("    registry   = %s" % (configured_registry() or "(默认官方源)"))
        if not npm:
            msg = "未找到 npm，请先安装 Node.js（默认路径 C:\\Program Files\\nodejs）"
            _log("    失败：%s" % msg)
            return False, msg

        ensure_manifest(runtime_dir)
        cmd = [npm, "install", "%s@%s" % (PKG_NAME, version), "--prefix", runtime_dir,
               "--save-exact", "--no-audit", "--no-fund", "--loglevel=error"]
        _log("    cmd        = %s" % " ".join(cmd))
        p = subprocess.run(cmd, stdout=(log or subprocess.DEVNULL),
                           stderr=subprocess.STDOUT,
                           creationflags=CREATE_NO_WINDOW, timeout=timeout)
        _log("    退出码     = %s" % p.returncode)
        if p.returncode != 0:
            return False, "npm 退出码 %s%s" % (
                p.returncode, "，详见 logs\\update.log" if log_path else "")
        return True, ""
    except subprocess.TimeoutExpired:
        _log("    失败：安装超时（%d 分钟）" % (timeout // 60))
        return False, "安装超时（%d 分钟）" % (timeout // 60)
    except Exception as e:
        _log("    失败：%s: %s" % (type(e).__name__, e))
        return False, "%s: %s" % (type(e).__name__, e)
    finally:
        if log:
            try:
                log.close()
            except Exception:
                pass

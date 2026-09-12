# -*- coding: utf-8 -*-
# ============================================================
# DeepSeek Harness (dsh) 系统托盘监视器
# 功能：状态显示 / 启动 / 停止 / 重启 / 打开 Web 界面 / 查看日志 / 版本检查与更新
# 图标：DeepSeek 小海豚（dsh_icons.py，由 make_icon.py 生成）
# 打包：pyinstaller --onefile --noconsole --name dsh-tray --icon assets\dsh-tray.ico dsh-tray.py
# 依赖：同目录下的 dsh-runner.cmd（启动器）
# ============================================================
import ctypes
import json
import logging
import os
import re
import socket
import subprocess
import sys
import threading
import time
import traceback

import pystray
from PIL import Image  # noqa: F401  (供 PyInstaller 打包 Pillow)

import dsh_icons
import dsh_update

# ---------- 配置 ----------
APP_DIR = os.path.dirname(os.path.abspath(sys.executable if getattr(sys, "frozen", False) else __file__))
PORT = int(os.environ.get("DSH_PORT", "3080"))
LOG_DIR = os.path.join(APP_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "dsh.log")
PID_FILE = os.path.join(APP_DIR, ".dsh.pid")
RUNNER = os.path.join(APP_DIR, "dsh-runner.cmd")
URL = "http://127.0.0.1:%d" % PORT

# 本地受管运行时（由托盘自己安装/更新，版本可控）
RUNTIME_DIR = os.path.join(APP_DIR, "runtime")
RUNTIME_PKG = os.path.join(RUNTIME_DIR, "node_modules", "@deepseek-ai", "dsh", "package.json")
SETTINGS_FILE = os.path.join(APP_DIR, "settings.json")
UPDATE_LOG = os.path.join(LOG_DIR, "update.log")

CHANNELS = dsh_update.CHANNELS
CHANNEL_DEFAULT = "latest"

CREATE_NO_WINDOW = 0x08000000

# ---------- 单实例锁 ----------
def acquire_single_instance():
    """获取单实例互斥锁；已有实例在运行时返回 None

    注意：CreateMutexW 在互斥体已存在时仍返回有效句柄，必须靠
    GetLastError()==ERROR_ALREADY_EXISTS(183) 判断，且句柄要按指针宽度读取。
    """
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW.restype = ctypes.c_void_p
    handle = k32.CreateMutexW(None, False, "dsh-tray-single-instance")
    if not handle or ctypes.get_last_error() == 183:
        return None
    return handle

# ---------- 图标（DeepSeek 小海豚 + 右下角状态点） ----------
ICON_GREEN = dsh_icons.load(True)    # 运行中（绿点）
ICON_RED = dsh_icons.load(False)     # 已停止（红点）

# ---------- 状态 ----------
def is_running():
    try:
        s = socket.create_connection(("127.0.0.1", PORT), timeout=1)
        s.close()
        return True
    except OSError:
        return False

def find_listener_pid():
    """netstat 解析 3080 端口监听进程 PID"""
    try:
        out = subprocess.check_output(["netstat", "-ano"], timeout=10,
                                      creationflags=CREATE_NO_WINDOW).decode("utf-8", errors="ignore")
        for line in out.splitlines():
            m = re.search(r"TCP\s+[^:]+:%d\s+\S+\s+LISTENING\s+(\d+)" % PORT, line)
            if m:
                return int(m.group(1))
    except Exception:
        pass
    return 0

def read_pid_file():
    try:
        with open(PID_FILE, "r") as f:
            pid = f.read().strip()
            return int(pid) if pid.isdigit() else 0
    except Exception:
        return 0

def run_hidden(cmd):
    try:
        subprocess.run(cmd, timeout=10, creationflags=CREATE_NO_WINDOW,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass

# ---------- 崩溃日志（打包后 --noconsole 看不到任何输出，必须落盘） ----------
TRAY_LOG = os.path.join(LOG_DIR, "tray.log")

def log_exc(exc_type, exc, tb, where=""):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(TRAY_LOG, "a", encoding="utf-8") as f:
            f.write("=== %s  %s ===\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), where))
            traceback.print_exception(exc_type, exc, tb, file=f)
    except Exception:
        pass

def log_msg(msg):
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(TRAY_LOG, "a", encoding="utf-8") as f:
            f.write("%s  %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass

def install_excepthooks():
    sys.excepthook = lambda t, e, tb: log_exc(t, e, tb, "main")
    threading.excepthook = lambda a: log_exc(a.exc_type, a.exc_value, a.exc_traceback,
                                             "thread:%s" % a.thread.name)

def setup_logging():
    """pystray 内部异常只写 logger（--noconsole 下无处可见），落到 tray.log"""
    os.makedirs(LOG_DIR, exist_ok=True)

    class _F(logging.Handler):
        def emit(self, record):
            try:
                with open(TRAY_LOG, "a", encoding="utf-8") as f:
                    f.write("%s  [%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                               record.levelname, self.format(record)))
                    if record.exc_info:
                        traceback.print_exception(*record.exc_info, file=f)
            except Exception:
                pass

    root = logging.getLogger()
    root.setLevel(logging.INFO)          # DEBUG 会把 PIL 各插件导入刷满日志
    logging.getLogger("PIL").setLevel(logging.WARNING)
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(_F())

# ---------- 服务控制 ----------
def _pid_alive(pid):
    """Windows 下用 os.kill(pid, 0) 探测进程是否存在"""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False

def start_service():
    if is_running():
        return True
    pid = read_pid_file()
    if pid > 0 and _pid_alive(pid):
        return True  # 启动中，避免重复拉起
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        if not os.path.exists(RUNNER):
            icon.notify("未找到 dsh-runner.cmd", "DeepSeek Harness")
            return False
        p = subprocess.Popen([RUNNER], creationflags=CREATE_NO_WINDOW)
        with open(PID_FILE, "w") as f:
            f.write(str(p.pid))
        return True
    except Exception as e:
        icon.notify("启动失败: %s" % e, "DeepSeek Harness")
        return False

def stop_service():
    pid = read_pid_file()
    if pid > 0:
        run_hidden(["taskkill.exe", "/PID", str(pid), "/T", "/F"])
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
    lp = find_listener_pid()
    if lp > 0:
        run_hidden(["taskkill.exe", "/PID", str(lp), "/T", "/F"])
    time.sleep(0.3)

def restart_service():
    stop_service()
    time.sleep(0.8)
    start_service()

# ---------- 版本 / 更新 ----------
def load_settings():
    try:
        with open(SETTINGS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_settings(d):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

_settings = load_settings()

def channel():
    ch = _settings.get("channel", CHANNEL_DEFAULT)
    return ch if ch in CHANNELS else CHANNEL_DEFAULT

def local_version():
    return dsh_update.local_version(RUNTIME_PKG)

def is_newer(new, old):
    return dsh_update.is_newer(new, old)

# 更新相关共享状态（供菜单渲染）
_updating = threading.Event()
_latest_cache = {"tag": None, "version": None}

def update_available():
    """有可用新版则返回版本号，否则 None"""
    v = _latest_cache.get("version")
    cur = local_version()
    if not v:
        return None
    if not cur or is_newer(v, cur):
        return v
    return None

def _check_task(verbose=True):
    """verbose=True：无论结果都提示；False：仅在发现新版本时提示（供启动自动检查用）"""
    ch = channel()
    try:
        tags = dsh_update.fetch_dist_tags()
        remote = tags.get(ch) or tags.get("latest")
    except Exception as e:
        if verbose:
            icon.notify("检查失败：%s" % e, "DeepSeek Harness")
        return
    _latest_cache["tag"] = ch
    _latest_cache["version"] = remote
    cur = local_version()
    if cur and not is_newer(remote, cur):
        if verbose:
            icon.notify("已是最新版本 v%s（通道 %s）" % (cur, ch), "DeepSeek Harness")
    else:
        icon.notify("发现新版本 v%s（当前 %s）\n通道 %s · 右键托盘 → 更新" % (remote, cur or "未安装", ch),
                    "DeepSeek Harness")
    refresh()

def _update_task():
    if _updating.is_set():
        return
    _updating.set()
    refresh()
    try:
        ch = channel()
        try:
            target = dsh_update.resolve_remote(ch)
        except Exception as e:
            icon.notify("检查更新失败：%s" % e, "DeepSeek Harness")
            return
        cur = local_version()
        if cur and not is_newer(target, cur):
            icon.notify("当前已是最新版本 v%s（通道 %s）" % (cur, ch), "DeepSeek Harness")
            return
        _latest_cache["tag"] = ch
        _latest_cache["version"] = target
        icon.notify("正在下载并更新到 v%s…\n（体积较大，请耐心等待）" % target, "DeepSeek Harness")
        was_running = is_running()
        if was_running:
            stop_service()
        ok, err = dsh_update.install(RUNTIME_DIR, target, UPDATE_LOG)
        if not ok:
            icon.notify("更新失败：%s" % err, "DeepSeek Harness")
            if was_running:
                start_service()
            return
        ver = local_version() or target
        if was_running:
            start_service()
        _latest_cache["version"] = None
        icon.notify("已更新到 v%s%s" % (ver, "，服务已重启" if was_running else ""), "DeepSeek Harness")
    finally:
        _updating.clear()
        refresh()

# ---------- 托盘 ----------
def web_url():
    """带 token 的访问地址：新版 dsh 首次访问需带 ?token=…（从服务日志最后一条抓取）"""
    try:
        with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-400:]
        for line in reversed(lines):
            m = re.search(r"http://127\.0\.0\.1:%d/\?token=[A-Za-z0-9_\-]+" % PORT, line)
            if m:
                return m.group(0)
    except Exception:
        pass
    return URL

def on_open(icon, item):
    os.startfile(web_url())

def on_start(icon, item):
    start_service()
    refresh()

def on_stop(icon, item):
    stop_service()
    refresh()

def on_restart(icon, item):
    restart_service()
    refresh()

def on_log(icon, item):
    if os.path.exists(LOG_FILE):
        os.startfile(LOG_FILE)
    else:
        icon.notify("日志文件尚不存在", "DeepSeek Harness")

def on_update_log(icon, item):
    if os.path.exists(UPDATE_LOG):
        os.startfile(UPDATE_LOG)
    else:
        icon.notify("暂无更新日志", "DeepSeek Harness")

def on_check(icon, item):
    threading.Thread(target=_check_task, daemon=True).start()

def on_update(icon, item):
    threading.Thread(target=_update_task, daemon=True).start()

def on_channel(icon, item):
    ch = item.text.lstrip("&")
    if ch in CHANNELS:
        _settings["channel"] = ch
        save_settings(_settings)
        _latest_cache["version"] = None
        threading.Thread(target=_check_task, args=(False,), daemon=True).start()
        refresh()

def on_exit(icon, item):
    _exit_requested.set()
    icon.stop()

def _update_item():
    cur = local_version()
    new = update_available()
    if _updating.is_set():
        return pystray.MenuItem("正在更新…", None, enabled=False)
    if new:
        return pystray.MenuItem("更新到 v%s（通道 %s）" % (new, channel()), on_update)
    if not cur:
        return pystray.MenuItem("安装 dsh（通道 %s）" % channel(), on_update)
    return pystray.MenuItem("已是最新（v%s）" % cur, on_check)

def _channel_menu():
    ch = channel()
    return pystray.Menu(*[
        pystray.MenuItem(c, on_channel, radio=True, checked=(lambda item, c=c: c == ch))
        for c in CHANNELS
    ])

def build_menu():
    running = is_running()
    cur = local_version()
    status = "状态: 运行中" if running else "状态: 已停止"
    if cur:
        status += "  ·  v%s" % cur
    return pystray.Menu(
        pystray.MenuItem(status, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("打开 Web 界面 (%s)" % URL, on_open, enabled=running),
        pystray.MenuItem("启动服务", on_start, enabled=not running and not _updating.is_set()),
        pystray.MenuItem("停止服务", on_stop, enabled=running and not _updating.is_set()),
        pystray.MenuItem("重启服务", on_restart, enabled=running and not _updating.is_set()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("检查更新", on_check, enabled=not _updating.is_set()),
        _update_item(),
        pystray.MenuItem("更新通道", _channel_menu(), enabled=not _updating.is_set()),
        pystray.MenuItem("查看更新日志", on_update_log),
        pystray.MenuItem("查看服务日志", on_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出托盘", on_exit),
    )

icon = None  # 由 main() 创建；菜单回调通过模块全局引用
_exit_requested = threading.Event()

# ---------- 状态轮询（3 秒一次） ----------
_last_state = None

def poll_loop():
    global _last_state
    while True:
        try:
            running = is_running()
            if running != _last_state:
                if _last_state is not None:  # 首次不弹气泡
                    if running:
                        icon.notify("服务已启动 (%s)" % URL, "DeepSeek Harness")
                    else:
                        icon.notify("服务已停止", "DeepSeek Harness")
                _last_state = running
                icon.icon = ICON_GREEN if running else ICON_RED
                pid = read_pid_file() if running else 0
                ver = local_version()
                ver_txt = " v%s" % ver if ver else ""
                icon.title = ("DeepSeek Harness 运行中%s (PID %d)" % (ver_txt, pid)) if running \
                    else "DeepSeek Harness 已停止%s" % ver_txt
                icon.menu = build_menu()  # 状态变化时重建菜单（刷新启用/禁用状态）
        except Exception:  # 轮询线程绝不能因单次异常退出
            log_exc(*sys.exc_info(), where="poll")
        time.sleep(3)

def refresh():
    global _last_state
    _last_state = None  # 强制下一次轮询刷新图标/标题/菜单


def main():
    global icon
    install_excepthooks()
    setup_logging()
    if acquire_single_instance() is None:
        return  # 已有托盘实例在运行（句柄由本进程持有到退出）
    log_msg("--- 托盘启动 v%s ---" % (local_version() or "未安装"))

    threading.Thread(target=poll_loop, name="poll", daemon=True).start()
    # 启动后自动静默检查一次更新（仅发现新版本时才提示）
    threading.Thread(target=lambda: (time.sleep(8), _check_task(False)), name="autocheck",
                     daemon=True).start()

    # 消息循环若意外结束（WM_QUIT / 底层异常），重建图标继续驻留，避免托盘悄悄消失
    attempts = 0
    while not _exit_requested.is_set() and attempts < 5:
        icon = pystray.Icon("dsh-tray", ICON_RED, "DeepSeek Harness 已停止")
        icon.menu = build_menu()
        try:
            icon.run()
        except Exception:
            log_exc(*sys.exc_info(), where="icon.run")
        if _exit_requested.is_set():
            break
        attempts += 1
        log_msg("消息循环意外结束，重建托盘（第 %d 次）" % attempts)
        time.sleep(2)
    log_msg("--- 托盘退出 ---")


def selftest():
    """菜单/图标构建自检（--selftest，不启动托盘，供打包后排查用）"""
    global icon
    icon = pystray.Icon("dsh-tray", ICON_RED, "selftest")
    problems = []
    log_path = os.path.join(APP_DIR, "selftest.log")

    def emit(msg):
        """打包为 --noconsole 时 sys.stdout 为 None，改写入 selftest.log"""
        if sys.stdout is None:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(msg + "\n")
        else:
            print(msg)

    if sys.stdout is None:
        try:
            os.remove(log_path)
        except OSError:
            pass
    emit("APP_DIR=%s" % APP_DIR)
    emit("local_version=%s" % local_version())
    emit("npm=%s" % dsh_update.npm_cmd())

    def dump(menu, indent=0):
        for it in menu:
            if it is pystray.Menu.SEPARATOR:
                continue
            try:
                txt, en, rd = it.text, it.enabled, it.radio
                if callable(it.checked):
                    it.checked(it)
                emit("%s%s | enabled=%s radio=%s" % ("  " * indent, txt, en, rd))
                sub = it.submenu
                if sub is not None:
                    dump(sub, indent + 1)
            except Exception as e:
                problems.append("%r: %s" % (it, e))

    scenarios = [
        ("默认", {"ver": None}, False),
        ("有新版", {"ver": "9.9.9"}, False),
        ("更新中", {"ver": None}, True),
    ]
    for name, cache, updating in scenarios:
        emit("\n--- 菜单场景: %s ---" % name)
        _latest_cache["version"] = cache["ver"]
        if updating:
            _updating.set()
        else:
            _updating.clear()
        try:
            dump(build_menu())
        except Exception as e:
            problems.append("build_menu(%s): %s" % (name, e))
    _updating.clear()
    _latest_cache["version"] = None

    for st in (True, False):
        im = dsh_icons.load(st)
        emit("图标 running=%s -> %s %s" % (st, im.size, im.mode))
        if im.size != (64, 64):
            problems.append("icon size %s" % (im.size,))

    try:
        tags = dsh_update.fetch_dist_tags()
        emit("registry dist-tags=%s" % tags)
    except Exception as e:
        problems.append("registry: %s" % e)

    emit("=== %s ===" % ("SELFTEST OK" if not problems else "PROBLEMS: %s" % problems))
    return 1 if problems else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    main()

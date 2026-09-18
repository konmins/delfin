# -*- coding: utf-8 -*-
# ============================================================
# DeepSeek Harness (dsh) 系统托盘监视器
# 功能：状态显示 / 启动 / 停止 / 重启 / 打开 Web 界面 / 查看日志 / 版本检查与更新
# 图标：DeepSeek 小海豚（dsh_icons.py，由 make_icon.py 生成）
# 界面：中英双语（dsh_i18n.py），默认跟随系统语言，可在托盘菜单里切换
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

import dsh_i18n
import dsh_icons
import dsh_update
from dsh_i18n import t

# --lang zh|en 强制界面语言（也供自检与自动化验证使用）
FORCE_LANG = None
for _i, _a in enumerate(sys.argv):
    if _a == "--lang" and _i + 1 < len(sys.argv):
        FORCE_LANG = dsh_i18n.normalize(sys.argv[_i + 1])
    elif _a.startswith("--lang="):
        FORCE_LANG = dsh_i18n.normalize(_a.split("=", 1)[1])

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
            icon.notify(t("runner_missing"), "DeepSeek Harness")
            return False
        p = subprocess.Popen([RUNNER], creationflags=CREATE_NO_WINDOW)
        with open(PID_FILE, "w") as f:
            f.write(str(p.pid))
        return True
    except Exception as e:
        icon.notify(t("start_failed", e), "DeepSeek Harness")
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

def lang():
    """界面语言：--lang 强制 > settings.json > 系统检测"""
    if FORCE_LANG:
        return FORCE_LANG
    saved = dsh_i18n.normalize(_settings.get("language"))
    return saved or dsh_i18n.detect()

# 尽早确定语言，后续所有 t() 取值都依赖它
dsh_i18n.set_lang(lang())

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
    if verbose:
        # 先给反馈：网络查询最慢要十几秒，不发提示用户会以为「点了没反应」
        icon.notify(t("checking_update"), "DeepSeek Harness")
    try:
        tags = dsh_update.fetch_dist_tags()
        remote = tags.get(ch) or tags.get("latest")
    except Exception as e:
        log_msg("检查更新失败: %s" % e)
        if verbose:
            icon.notify(t("check_failed", e), "DeepSeek Harness")
        return
    _latest_cache["tag"] = ch
    _latest_cache["version"] = remote
    cur = local_version()
    if cur and not is_newer(remote, cur):
        if verbose:
            icon.notify(t("up_to_date", cur, ch), "DeepSeek Harness")
    else:
        icon.notify(t("found_new", remote, cur or t("not_installed"), ch), "DeepSeek Harness")
    refresh()

def _update_task():
    if _updating.is_set():
        return
    _updating.set()
    refresh()
    try:
        ch = channel()
        # 立刻回执：解析远端版本要走网络（最坏十几秒），中间不给反馈就是「点了没反应」
        icon.notify(t("checking_update"), "DeepSeek Harness")
        log_msg("更新开始（通道 %s，当前 v%s）" % (ch, local_version() or "未安装"))
        try:
            target = dsh_update.resolve_remote(ch)
        except Exception as e:
            log_msg("更新中止：解析远端版本失败: %s" % e)
            icon.notify(t("check_update_failed", e), "DeepSeek Harness")
            return
        cur = local_version()
        if cur and not is_newer(target, cur):
            log_msg("更新跳过：已是最新 v%s（远端 %s）" % (cur, target))
            icon.notify(t("already_latest", cur, ch), "DeepSeek Harness")
            return
        _latest_cache["tag"] = ch
        _latest_cache["version"] = target
        log_msg("准备更新：v%s → v%s" % (cur or "未安装", target))
        icon.notify(t("downloading", target), "DeepSeek Harness")
        was_running = is_running()
        if was_running:
            stop_service()
        ok, err = dsh_update.install(RUNTIME_DIR, target, UPDATE_LOG)
        if not ok:
            log_msg("更新失败: %s" % err)
            icon.notify(t("update_failed", err), "DeepSeek Harness")
            if was_running:
                start_service()
            return
        ver = local_version() or target
        if was_running:
            start_service()
        _latest_cache["version"] = None
        log_msg("更新完成：v%s" % ver)
        icon.notify(t("updated", ver) + (t("service_restarted") if was_running else ""),
                    "DeepSeek Harness")
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
        icon.notify(t("log_missing"), "DeepSeek Harness")

def on_update_log(icon, item):
    if os.path.exists(UPDATE_LOG):
        os.startfile(UPDATE_LOG)
    else:
        icon.notify(t("update_log_missing"), "DeepSeek Harness")

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

def set_language(code):
    """切换界面语言：存设置 + 立即重建菜单与悬停标题（本回调在主线程，可安全重建）"""
    if code not in dsh_i18n.LANGS or code == lang():
        return
    _settings["language"] = code
    save_settings(_settings)
    dsh_i18n.set_lang(code)
    log_msg(t("log_language", code))
    if icon is not None:
        try:
            icon.title = tray_title()
            icon.menu = build_menu()
        except Exception:
            log_exc(*sys.exc_info(), where="set_language")
        try:
            icon.notify(t("lang_switched"), "DeepSeek Harness")
        except Exception:
            pass
    refresh()

def on_exit(icon, item):
    _exit_requested.set()
    icon.stop()

def _update_item():
    cur = local_version()
    new = update_available()
    if _updating.is_set():
        return pystray.MenuItem(t("menu_updating"), None, enabled=False)
    if new:
        return pystray.MenuItem(t("menu_update_to", new, channel()), on_update)
    if not cur:
        return pystray.MenuItem(t("menu_install", channel()), on_update)
    return pystray.MenuItem(t("menu_latest", cur), on_check)

def _channel_menu():
    ch = channel()
    return pystray.Menu(*[
        pystray.MenuItem(c, on_channel, radio=True, checked=(lambda item, c=c: c == ch))
        for c in CHANNELS
    ])

def _lang_menu():
    """语言子菜单：语言名一律用母语显示，猜错语言时也找得到出口"""
    def action_for(code):
        def _action(icon, item):
            set_language(code)
        return _action

    return pystray.Menu(*[
        pystray.MenuItem(dsh_i18n.NAMES[c], action_for(c), radio=True,
                         checked=(lambda item, c=c: c == lang()))
        for c in dsh_i18n.LANGS
    ])

def build_menu():
    running = is_running()
    cur = local_version()
    status = t("status_running") if running else t("status_stopped")
    if cur:
        status += "  ·  v%s" % cur
    return pystray.Menu(
        pystray.MenuItem(status, None, enabled=False),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(t("menu_open_web", URL), on_open, enabled=running),
        pystray.MenuItem(t("menu_start"), on_start, enabled=not running and not _updating.is_set()),
        pystray.MenuItem(t("menu_stop"), on_stop, enabled=running and not _updating.is_set()),
        pystray.MenuItem(t("menu_restart"), on_restart, enabled=running and not _updating.is_set()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(t("menu_check"), on_check, enabled=not _updating.is_set()),
        _update_item(),
        pystray.MenuItem(t("menu_channel"), _channel_menu(), enabled=not _updating.is_set()),
        pystray.MenuItem(t("menu_update_log"), on_update_log),
        pystray.MenuItem(t("menu_service_log"), on_log),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(t("menu_language"), _lang_menu()),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem(t("menu_exit"), on_exit),
    )

icon = None  # 由 main() 创建；菜单回调通过模块全局引用
_exit_requested = threading.Event()

def tray_title(running=None):
    """悬停提示文案；running 已知时传入可省一次端口探测"""
    if running is None:
        running = is_running()
    ver = local_version()
    ver_txt = " v%s" % ver if ver else ""
    if running:
        return t("tray_running", ver_txt, read_pid_file())
    return t("tray_stopped", ver_txt)

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
                        icon.notify(t("notify_started", URL), "DeepSeek Harness")
                    else:
                        icon.notify(t("notify_stopped"), "DeepSeek Harness")
                _last_state = running
                icon.icon = ICON_GREEN if running else ICON_RED
                icon.title = tray_title(running)
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
    log_msg(t("log_start", local_version() or t("not_installed")))
    log_msg("lang=%s (ui=%s, forced=%s)" % (lang(), dsh_i18n.detect(), FORCE_LANG or "-"))

    threading.Thread(target=poll_loop, name="poll", daemon=True).start()
    # 启动后自动静默检查一次更新（仅发现新版本时才提示）
    threading.Thread(target=lambda: (time.sleep(8), _check_task(False)), name="autocheck",
                     daemon=True).start()

    # 消息循环若意外结束（WM_QUIT / 底层异常），重建图标继续驻留，避免托盘悄悄消失
    attempts = 0
    while not _exit_requested.is_set() and attempts < 5:
        icon = pystray.Icon("dsh-tray", ICON_RED, tray_title(False))
        icon.menu = build_menu()
        try:
            icon.run()
        except Exception:
            log_exc(*sys.exc_info(), where="icon.run")
        if _exit_requested.is_set():
            break
        attempts += 1
        log_msg(t("log_rebuild", attempts))
        time.sleep(2)
    log_msg(t("log_exit"))


def selftest():
    """菜单/图标/文案自检（--selftest，不启动托盘，供打包后排查用）

    覆盖两种语言：逐语言转储菜单，并自动校验英文模式下菜单与悬停提示
    不含中文字符，避免漏翻的条目混进英文界面（语言子菜单里的母语名按设计豁免）。
    """
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
    emit("detected_lang=%s  forced_lang=%s" % (dsh_i18n.detect(), FORCE_LANG or "-"))

    def _T(key, lc, *args):
        """按指定语言取值（临时切换后还原）"""
        cur = dsh_i18n.get_lang()
        dsh_i18n.set_lang(lc)
        try:
            return dsh_i18n.t(key, *args)
        finally:
            dsh_i18n.set_lang(cur)

    def walk(menu, depth=0):
        """展平菜单，产出 (层级, 菜单项)，跳过分隔线"""
        for it in menu:
            if it is pystray.Menu.SEPARATOR:
                continue
            yield depth, it
            if it.submenu is not None:
                for x in walk(it.submenu, depth + 1):
                    yield x

    # --- 文案表完整性 ---
    bad = list(dsh_i18n.missing_keys())
    for k in dsh_i18n.keys():
        zh, en = _T(k, "zh"), _T(k, "en")
        if not zh or not en:
            bad.append(k)
        elif k != "menu_language" and zh == en and re.search(r"[\u4e00-\u9fff]", zh):
            bad.append(k)          # 英文侧没翻，直接沿用了中文
    emit("\ntranslation keys=%d  untranslated=%s" % (len(dsh_i18n.keys()), bad or "none"))
    if bad:
        problems.append("以下条目中英文不完整: %s" % bad)

    # 带参数的格式化是否生效
    probe = _T("menu_update_to", "en", "9.9.9", "latest")
    emit("format probe -> %s" % probe)
    if "%s" in probe or "9.9.9" not in probe:
        problems.append("t() 参数格式化异常: %s" % probe)

    # 语言子菜单的语言名与「语言 / Language」标题按设计始终含中文，豁免校验
    native = set(dsh_i18n.NAMES.values())
    native.update({_T("menu_language", "zh"), _T("menu_language", "en")})
    han = re.compile(r"[\u4e00-\u9fff]")
    scenarios = [
        ("default", {"ver": None}, False),
        ("update-available", {"ver": "9.9.9"}, False),
        ("updating", {"ver": None}, True),
    ]

    for lc in dsh_i18n.LANGS:
        dsh_i18n.set_lang(lc)
        emit("\n########## language = %s ##########" % lc)
        for name, cache, updating in scenarios:
            emit("\n--- menu scenario: %s ---" % name)
            _latest_cache["version"] = cache["ver"]
            if updating:
                _updating.set()
            else:
                _updating.clear()
            try:
                menu = build_menu()
            except Exception as e:
                problems.append("build_menu(%s/%s): %s" % (lc, name, e))
                continue
            for depth, it in walk(menu):
                try:
                    txt, en, rd = it.text, it.enabled, it.radio
                    if callable(it.checked):
                        it.checked(it)
                    emit("%s%s | enabled=%s radio=%s" % ("  " * depth, txt, en, rd))
                    if lc == "en" and txt not in native and han.search(txt):
                        problems.append("英文菜单混入中文: %s" % txt)
                except Exception as e:
                    problems.append("%r: %s" % (it, e))
        for st in (True, False):
            tip = tray_title(st)
            emit("\ntooltip running=%s -> %s" % (st, tip))
            if lc == "en" and han.search(tip):
                problems.append("英文悬停提示混入中文: %s" % tip)

    dsh_i18n.set_lang(lang())      # 还原真实语言
    _updating.clear()
    _latest_cache["version"] = None

    for st in (True, False):
        im = dsh_icons.load(st)
        emit("\n图标 running=%s -> %s %s" % (st, im.size, im.mode))
        if im.size != (64, 64):
            problems.append("icon size %s" % (im.size,))

    try:
        tags = dsh_update.fetch_dist_tags()
        emit("registry dist-tags=%s" % tags)
    except Exception as e:
        problems.append("registry: %s" % e)

    emit("\n=== %s ===" % ("SELFTEST OK" if not problems else "PROBLEMS: %s" % problems))
    return 1 if problems else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    main()

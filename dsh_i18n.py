# -*- coding: utf-8 -*-
"""Delfin 界面文案的双语支持

设计要点：
- 文案集中在一张表里，每条为 (中文, English)，取值用 t("key", ...args)。
- 默认语言按 Windows 界面语言推断（主语言 ID 为中文则中文，否则英文）。
- 语言子菜单里始终用**各自母语**显示语言名（简体中文 / English），
  这样即使自动检测猜错了，用户也能在自己看得懂的那份文案里找到切换入口。
- 语言取值优先级：--lang 强制 > settings.json > 系统检测 > 兜底。

本模块不依赖 pystray / PIL，可单独 import 做单测。
"""
import ctypes
import locale

LANGS = ("zh", "en")
DEFAULT_LANG = "en"

# 语言名用母语书写，不参与翻译
NAMES = {"zh": "简体中文", "en": "English"}

# key: (中文, English)
_STRINGS = {
    # ---- 气泡通知 ----
    "runner_missing": ("未找到 dsh-runner.cmd", "dsh-runner.cmd not found"),
    "start_failed": ("启动失败: %s", "Failed to start: %s"),
    "check_failed": ("检查失败：%s", "Check failed: %s"),
    "up_to_date": ("已是最新版本 v%s（通道 %s）", "Already on the latest version, v%s (channel %s)"),
    "found_new": ("发现新版本 v%s（当前 %s）\n通道 %s · 右键托盘 → 更新",
                  "New version available: v%s (current: %s)\nChannel %s · right-click the tray icon to update"),
    "not_installed": ("未安装", "not installed"),
    "checking_update": ("正在检查更新…", "Checking for updates…"),
    "check_update_failed": ("检查更新失败：%s", "Update check failed: %s"),
    "already_latest": ("当前已是最新版本 v%s（通道 %s）",
                       "You are already on the latest version, v%s (channel %s)"),
    "downloading": ("正在下载并更新到 v%s…\n（体积较大，请耐心等待）",
                    "Downloading and updating to v%s…\n(this is a large package, please wait)"),
    "update_failed": ("更新失败：%s", "Update failed: %s"),
    "updated": ("已更新到 v%s", "Updated to v%s"),
    "service_restarted": ("，服务已重启", " — the service has been restarted"),
    "log_missing": ("日志文件尚不存在", "The log file does not exist yet"),
    "update_log_missing": ("暂无更新日志", "No update log yet"),
    "notify_started": ("服务已启动 (%s)", "Service started (%s)"),
    "notify_stopped": ("服务已停止", "Service stopped"),
    "lang_switched": ("界面语言已切换为中文", "UI language switched to English"),

    # ---- 托盘菜单 ----
    "status_running": ("状态: 运行中", "Status: running"),
    "status_stopped": ("状态: 已停止", "Status: stopped"),
    "menu_open_web": ("打开 Web 界面 (%s)", "Open Web UI (%s)"),
    "menu_start": ("启动服务", "Start service"),
    "menu_stop": ("停止服务", "Stop service"),
    "menu_restart": ("重启服务", "Restart service"),
    "menu_check": ("检查更新", "Check for updates"),
    "menu_updating": ("正在更新…", "Updating…"),
    "menu_update_to": ("更新到 v%s（通道 %s）", "Update to v%s (channel %s)"),
    "menu_install": ("安装 dsh（通道 %s）", "Install dsh (channel %s)"),
    "menu_latest": ("已是最新（v%s）", "Up to date (v%s)"),
    "menu_channel": ("更新通道", "Update channel"),
    "menu_update_log": ("查看更新日志", "View update log"),
    "menu_service_log": ("查看服务日志", "View service log"),
    "menu_exit": ("退出托盘", "Quit tray"),
    # 用双语固定显示，保证任何语言下都找得到
    "menu_language": ("语言 / Language", "语言 / Language"),

    # ---- 悬停提示 ----
    "tray_running": ("DeepSeek Harness 运行中%s (PID %d)", "DeepSeek Harness running%s (PID %d)"),
    "tray_stopped": ("DeepSeek Harness 已停止%s", "DeepSeek Harness stopped%s"),

    # ---- 日志 ----
    "log_start": ("--- 托盘启动 v%s ---", "--- tray started, v%s ---"),
    "log_exit": ("--- 托盘退出 ---", "--- tray exited ---"),
    "log_rebuild": ("消息循环意外结束，重建托盘（第 %d 次）",
                    "message loop ended unexpectedly, rebuilding tray (attempt %d)"),
    "log_language": ("界面语言切换为 %s", "UI language switched to %s"),
}

_lang = DEFAULT_LANG


def detect():
    """按 Windows 界面语言推断：主语言 ID 为中文(0x04)则中文，否则英文"""
    try:
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        langid = k32.GetUserDefaultUILanguage()
        # LANGID 的低 10 位是主语言 ID
        return "zh" if (langid & 0x3FF) == 0x04 else "en"
    except Exception:
        pass
    try:
        code = (locale.getdefaultlocale()[0] or "").lower()
        if code:
            return "zh" if code.startswith("zh") else "en"
    except Exception:
        pass
    return DEFAULT_LANG


def normalize(code):
    """把 zh-CN / en-US / 中文 这类写法归一成 zh / en，认不出返回 None"""
    if not code:
        return None
    c = str(code).strip().lower().replace("_", "-")
    if c.startswith("zh") or c in ("chinese", "chinese-simplified", "中文"):
        return "zh"
    if c.startswith("en") or c in ("english", "英文"):
        return "en"
    return None


def set_lang(code):
    """设置当前语言；无法识别时保持不变，返回是否生效"""
    global _lang
    norm = normalize(code)
    if norm is None:
        return False
    _lang = norm
    return True


def get_lang():
    return _lang


def t(key, *args):
    """取当前语言的文案；带参数时做 % 格式化

    取不到 key 时原样返回 key，方便在界面/日志里看出漏配的条目。
    格式化失败也退回未格式化的原文，避免一条文案把菜单整块搞崩。
    """
    entry = _STRINGS.get(key)
    if entry is None:
        return key
    s = entry[1] if _lang == "en" else entry[0]
    if args:
        try:
            s = s % args
        except Exception:
            pass
    return s


def keys():
    return tuple(_STRINGS)


def missing_keys():
    """返回中英文任一侧缺失的 key（自检用）"""
    bad = []
    for k, v in _STRINGS.items():
        if not isinstance(v, tuple) or len(v) != 2 or not v[0] or not v[1]:
            bad.append(k)
    return bad

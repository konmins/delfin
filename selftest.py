# -*- coding: utf-8 -*-
"""Delfin 纯逻辑自检（不启动托盘）
输出一律用英文：本脚本也会在 Windows CI runner 上跑，那边的控制台 code page
不是 UTF-8，中文 print 会抛 UnicodeEncodeError，报错形似断言失败还把后续断言全盖掉。
"""
import importlib.util
import os
import sys
import tempfile

# 兜底：不改 encoding（本地 CMD 下中文才不会变乱码），只放宽错误处理，
# 实在编不出的字符降级成 '?'，断言结果不受影响。
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import dsh_i18n
import dsh_icons
import dsh_update as u

fails = []

# 1) semver 比较
cases = [
    ("0.1.5-rc.1", "0.1.1-rc.2", True),
    ("0.1.1-rc.2", "0.1.5-rc.1", False),
    ("0.1.1-rc.2", "0.1.1-rc.2", False),
    ("0.1.5-rc.2", "0.1.5-rc.1", True),
    ("0.2.0", "0.1.9", True),
    ("0.1.5", "0.1.5-rc.2", True),      # 正式版 > 预发布版
    ("1.0.0-alpha.2", "1.0.0-alpha.10", False),
]
for new, old, exp in cases:
    got = u.is_newer(new, old)
    print("%-14s > %-14s -> %-5s %s" % (new, old, got, "OK" if got == exp else "FAIL"))
    if got != exp:
        fails.append((new, old, exp, got))

# 2) registry 查询
try:
    tags = u.fetch_dist_tags()
    print("\ndist-tags:", tags)
    for ch in u.CHANNELS:
        print("  channel %-6s -> %s" % (ch, u.resolve_remote(ch)))
except Exception as e:
    fails.append(("registry", str(e)))
    print("registry FAIL:", e)

# 3) npm / node 定位
print("\nnpm  =", u.npm_cmd())
print("node =", u.node_cmd())
if not u.npm_cmd():
    fails.append(("npm", "未找到"))

# 4) 本地版本读取
HERE = os.path.dirname(os.path.abspath(__file__))
pkg = os.path.join(HERE, "runtime", "node_modules", "@deepseek-ai", "dsh", "package.json")
print("local_version(runtime) =", u.local_version(pkg))

# 5) 图标解码
for state in (True, False):
    im = dsh_icons.load(state)
    print("icon running=%s -> %s %s" % (state, im.size, im.mode))
    if im.size != (64, 64) or im.mode != "RGBA":
        fails.append(("icon", state, im.size, im.mode))

# 6) 内嵌启动器
#    发布包是 exe + cmd 两个文件，用户只拿了 exe（或在 dist\ 里直接双击构建产物）
#    时，托盘会自动生成一份 dsh-runner.cmd。生成的字节必须能被 cmd.exe 正确解析
#    —— 有 BOM 或 \r\r\n 都会让 @echo off 那行报错，用户点了「启动」还是毫无反应。
_spec = importlib.util.spec_from_file_location(
    "dsh_tray_app", os.path.join(HERE, "dsh-tray.py"))
tray = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tray)


def _effective_lines(text):
    """去掉空行和 rem 注释后的有效命令"""
    return [l.strip() for l in text.replace("\r\n", "\n").split("\n")
            if l.strip() and not l.strip().lower().startswith("rem")]


with open(os.path.join(HERE, "dsh-runner.cmd"), encoding="utf-8") as f:
    repo_lines = _effective_lines(f.read())
same = repo_lines == _effective_lines(tray.RUNNER_TEXT)
print("\nembedded runner matches dsh-runner.cmd:", same)
if not same:
    fails.append(("runner_text", repo_lines, _effective_lines(tray.RUNNER_TEXT)))

with tempfile.TemporaryDirectory() as td:
    tray.RUNNER = os.path.join(td, "dsh-runner.cmd")
    got = tray.ensure_runner()
    raw = open(got, "rb").read() if got else b""
    fmt_ok = (raw.startswith(b"@echo off\r\n")
              and not raw.startswith(b"\xef\xbb\xbf")
              and b"\r\r" not in raw
              and raw.count(b"\n") == raw.count(b"\r\n"))
    print("generated on demand = %s, bytes well-formed = %s" % (bool(got), fmt_ok))
    if not (got and fmt_ok):
        fails.append(("runner_bytes", raw[:80]))

    # 已存在的文件不得被覆盖（那可能是用户改过的）
    with open(got, "w", encoding="ascii") as f:
        f.write("SENTINEL")
    tray.ensure_runner()
    kept = open(got, encoding="ascii").read() == "SENTINEL"
    print("existing runner left untouched:", kept)
    if not kept:
        fails.append(("runner_overwrite", "overwritten"))

# 7) 生成失败时不能抛异常，要能返回 None 让调用方给出提示
tray.RUNNER = os.path.join(HERE, "no-such-dir", "sub", "dsh-runner.cmd")
none_ok = tray.ensure_runner() is None
print("unwritable folder -> None instead of raising:", none_ok)
if not none_ok:
    fails.append(("runner_fail_path", "did not return None"))

# 8) 报错文案要带上目录，否则用户不知道该把文件放哪儿
msg = dsh_i18n.t("runner_missing", r"C:\demo")
print("runner_missing carries the folder path:", r"C:\demo" in msg)
if r"C:\demo" not in msg:
    fails.append(("runner_missing_i18n", "folder path missing"))

print("\n=== %s ===" % ("ALL OK" if not fails else "FAILURES: %s" % fails))

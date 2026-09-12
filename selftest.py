# -*- coding: utf-8 -*-
"""dsh-tray 纯逻辑自检（不启动托盘）"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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

print("\n=== %s ===" % ("ALL OK" if not fails else "FAILURES: %s" % fails))

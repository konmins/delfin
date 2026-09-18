# -*- coding: utf-8 -*-
"""PE 产物断言 —— 把「打包约定」变成 CI 能自动发现的错误。

背景：Delfin 曾被 Defender 的 ML 启发式判成 `Trojan:Win32/Sabsik.FL.A!ml` 并直接隔离。
根因里有两项是**可以直接从 PE 里查出来的**，本脚本把这两项做成硬断言，
避免以后改 spec / 换构建机时悄悄回归。

检查项：
  1. **禁止 UPX**：节表里不能出现 `UPX0` / `UPX1` / `UPX2`。
     UPX 压缩改变二进制结构、带自解压特征，是启发式的头号触发点。
     更阴的地方在于：本机没装 upx 时 PyInstaller 会**静默跳过**，
     测试期毫无症状，换台装了 upx 的机器就中招 —— 所以必须显式检查。
  2. **必须带版本资源**：`VS_VERSION_INFO` 里要有 CompanyName / ProductName / FileVersion。
     「未签名 + 无公司名/产品名/版本号」的 PE 是启发式引擎最爱的形态。
  3. **必须是 GUI 子系统**：`console=False` 应落成 Subsystem=2（Windows GUI），
     否则双击会弹黑框。

用法：
    python .github/scripts/verify_pe.py dist/dsh-tray.exe

退出码 0 = 全部通过；1 = 有断言失败（CI 里直接 fail）。
"""

import os
import struct
import sys

# Windows CI runner 的 stdout 默认走 cp1252 / cp936，本脚本输出含中文，
# 不强制 UTF-8 会在 print 阶段就抛 UnicodeEncodeError —— 断言还没跑就挂了。
# 而且报错信息本身会被吞掉，很容易误判成「PE 不合格」。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

UPX_SECTION_PREFIXES = ("UPX0", "UPX1", "UPX2", "UPX!")

# 版本资源里必须存在的键
REQUIRED_VERSION_KEYS = ("CompanyName", "ProductName", "FileVersion")

SUBSYSTEM_NAMES = {2: "Windows GUI", 3: "Windows Console"}


def read_sections(data, pe_offset, num_sections, size_of_optional_header):
    """返回节名列表。"""
    section_table = pe_offset + 4 + 20 + size_of_optional_header
    names = []
    for i in range(num_sections):
        entry = section_table + i * 40
        if entry + 8 > len(data):
            break
        raw = data[entry:entry + 8]
        names.append(raw.rstrip(b"\x00").decode("ascii", "replace"))
    return names


def main(argv):
    if len(argv) < 2:
        print("用法: python verify_pe.py <path-to-exe>")
        return 2

    path = argv[1]
    if not os.path.isfile(path):
        print("FAIL: 文件不存在 -> %s" % path)
        return 1

    with open(path, "rb") as f:
        data = f.read()

    failures = []
    size = len(data)
    print("检查对象 : %s" % path)
    print("文件大小 : %s bytes" % format(size, ","))

    # --- DOS / PE 头 ---
    if data[:2] != b"MZ":
        print("FAIL: 不是有效的 PE 文件（缺少 MZ 头）")
        return 1

    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe_offset:pe_offset + 4] != b"PE\x00\x00":
        print("FAIL: 不是有效的 PE 文件（缺少 PE 签名）")
        return 1

    num_sections, size_of_optional_header = struct.unpack_from("<HH", data, pe_offset + 6)[0], \
        struct.unpack_from("<H", data, pe_offset + 20)[0]
    subsystem = struct.unpack_from("<H", data, pe_offset + 24 + 68)[0]

    sections = read_sections(data, pe_offset, num_sections, size_of_optional_header)
    print("节表     : %s" % ", ".join(sections))
    print("子系统   : %d (%s)" % (subsystem, SUBSYSTEM_NAMES.get(subsystem, "未知")))

    # --- 1) 禁止 UPX ---
    upx = [s for s in sections if s.upper().startswith(UPX_SECTION_PREFIXES)]
    if upx:
        failures.append(
            "发现 UPX 压缩节 %s —— 说明 upx 被真的启用了。"
            "请确认 dsh-tray.spec 里 upx=False 且构建机上可能存在的 upx 没有被重新打开。" % upx
        )
    else:
        print("OK       : 未发现 UPX 节")

    # --- 2) 必须带版本资源 ---
    # VS_VERSION_INFO 以 UTF-16LE 形式存在资源里，直接按字节搜同名键
    missing = []
    for key in REQUIRED_VERSION_KEYS:
        if data.find(key.encode("utf-16-le")) < 0:
            missing.append(key)

    has_block = data.find("VS_VERSION_INFO".encode("utf-16-le")) >= 0
    if not has_block:
        failures.append(
            "PE 里找不到 VS_VERSION_INFO 资源块 —— "
            "确认 dsh-tray.spec 的 EXE(...) 传了 version=os.path.join(HERE, 'version_info.txt')。"
        )
    elif missing:
        failures.append(
            "版本资源里缺少字段 %s —— 检查 version_info.txt 的 StringTable。" % missing
        )
    else:
        print("OK       : 版本资源完整（%s）" % ", ".join(REQUIRED_VERSION_KEYS))

    # --- 3) 必须为 GUI 子系统 ---
    if subsystem == 3:
        failures.append(
            "子系统是 Console(3) —— 双击会弹出黑色命令行窗口。"
            "检查 dsh-tray.spec 的 EXE(...) 是否为 console=False。"
        )
    elif subsystem != 2:
        failures.append("子系统为 %d，预期 2 (Windows GUI)。" % subsystem)
    else:
        print("OK       : 子系统为 Windows GUI")

    print("-" * 56)
    if failures:
        print("结果: 失败 %d 项" % len(failures))
        for i, msg in enumerate(failures, 1):
            print("  %d) %s" % (i, msg))
        return 1

    print("结果: 全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))

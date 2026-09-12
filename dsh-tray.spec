# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：Delfin -> 单文件、无控制台窗口的 exe

用法：
    pyinstaller dsh-tray.spec --noconfirm

路径全部相对 spec 文件所在目录解析，clone 到任何位置都能直接打包。
"""
import os

# SPECPATH 由 PyInstaller 注入（可能是目录，也可能指向 spec 文件本身，两种都兼容）
_spec = globals().get('SPECPATH') or '.'
HERE = _spec if os.path.isdir(_spec) else os.path.dirname(os.path.abspath(_spec))

a = Analysis(
    [os.path.join(HERE, 'dsh-tray.py')],
    pathex=[HERE],
    binaries=[],
    datas=[],
    hiddenimports=['dsh_icons', 'dsh_update', 'dsh_i18n'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='dsh-tray',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=[os.path.join(HERE, 'assets', 'dsh-tray.ico')],
)

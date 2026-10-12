# -*- mode: python ; coding: utf-8 -*-
# 屏幕 OCR 客户端 · Windows 单文件夹打包配置（onedir）
# 用法：pyinstaller -y ocrclient.spec
#
# 关键点：
#   1) RapidOCR 的 ONNX 模型在包内的 models/ 子目录，必须用 collect_data_files 收集，
#      否则打包后运行会报“找不到模型”。
#   2) pywin32 / pynput / pystray 需要显式 hiddenimports，否则运行时 ImportError。
#   3) console=False → 无黑框控制台，配合系统托盘常驻（桌面应用形态）。

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# RapidOCR 模型 + config.yaml 等数据文件（相对路径结构在打包后保持不变）
rapidocr_datas = collect_data_files("rapidocr_onnxruntime")

# 需要收集子模块的库（确保内部模块被打包进去）
hidden_imports = (
    collect_submodules("pynput")
    + collect_submodules("pystray")
)

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=rapidocr_datas,
    hiddenimports=hidden_imports
    + [
        "win32gui",
        "win32con",
        "win32api",
        "win32file",
        "pywintypes",
        "PIL",
        "PIL._imaging",
        "PIL._imagingtk",
        "numpy",
        "onnxruntime",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 仅在 Linux/macOS 下需要的托盘后端，Windows 不需要，去掉避免误收集
        "pystray._gtk",
        "pystray._darwin",
        "pystray._appindicator",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OCRClient",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/icon.ico",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="OCRClient",
)

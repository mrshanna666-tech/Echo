# PyInstaller build configuration for the Windows desktop executable.
from PyInstaller.utils.hooks import collect_submodules


hiddenimports = collect_submodules("PySide6")


a = Analysis(
    ["main.py"],
    pathex=["."],
    binaries=[],
    datas=[("assets/icons", "assets/icons")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="EchoRecorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon="assets/icons/echo.ico",
)

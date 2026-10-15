# PyInstaller build configuration for the Windows desktop executable.
# PyInstaller's PySide6 hooks discover the Qt modules imported by Echo.
# Avoid collecting every optional Qt module so the judge build stays compact.
hiddenimports = ["win32cred", "win32crypt", "sqlcipher3", "cryptography"]


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

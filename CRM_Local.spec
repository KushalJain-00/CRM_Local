# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec — build: pyinstaller CRM_Local.spec --noconfirm --clean
a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=[],
    datas=[("static", "static")],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
    ],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter.test", "test"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CRM_Local",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX triggers AV false positives on distributable exes
    console=False,  # windowed app — the browser opens itself
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for Finora (Apple Silicon macOS .app directory bundle)."""

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH)

datas = [
    (str(PROJECT_ROOT / "app" / "templates"), "app/templates"),
    (str(PROJECT_ROOT / "app" / "static"), "app/static"),
    (str(PROJECT_ROOT / "app" / "migrations" / "sql"), "app/migrations/sql"),
    (str(PROJECT_ROOT / "assets" / "branding" / "Finora.icns"), "assets/branding"),
    (str(PROJECT_ROOT / "assets" / "branding" / "finora-mark-light.svg"), "assets/branding"),
    (str(PROJECT_ROOT / "assets" / "branding" / "finora-mark-dark.svg"), "assets/branding"),
    (str(PROJECT_ROOT / "assets" / "branding" / "finora-wordmark-light.svg"), "assets/branding"),
    (str(PROJECT_ROOT / "assets" / "branding" / "finora-wordmark-dark.svg"), "assets/branding"),
]

hiddenimports = [
    "webview.platforms.cocoa",
    "objc",
    "AppKit",
    "Foundation",
    "WebKit",
    "Quartz",
    "Security",
    "UniformTypeIdentifiers",
    "PyObjCTools",
    "PyObjCTools.AppHelper",
]

excludes = [
    "tkinter",
    "pytest",
    "playwright",
    "ruff",
    "bandit",
    "pip_audit",
    "PIL",
]

a = Analysis(
    ["main.py"],
    pathex=[str(PROJECT_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Finora",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch="arm64",
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="Finora",
)

app = BUNDLE(
    coll,
    name="Finora.app",
    icon=str(PROJECT_ROOT / "assets" / "branding" / "Finora.icns"),
    bundle_identifier="app.finora.desktop",
    info_plist={
        "CFBundleName": "Finora",
        "CFBundleDisplayName": "Finora",
        "CFBundleIdentifier": "app.finora.desktop",
        "CFBundleVersion": "0.9.0-rc.2",
        "CFBundleShortVersionString": "0.9.0-rc.2",
        "NSHighResolutionCapable": True,
        "LSMinimumSystemVersion": "13.0",
        "NSRequiresAquaSystemAppearance": False,
    },
)

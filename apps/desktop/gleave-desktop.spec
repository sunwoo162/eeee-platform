from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules


spec_dir = Path(SPECPATH).resolve()
eeee_root = spec_dir.parent / "eeee"
static_dir = eeee_root / "app" / "static"
pet_assets_dir = eeee_root / "app" / "desktop" / "assets"
chatgpt_runtime_dir = spec_dir.parent / ".." / "packages" / "iseol" / "dist"
chatgpt_playwright_core_dir = spec_dir.parent / ".." / "packages" / "iseol" / "node_modules" / "playwright-core"
chatgpt_package_json = spec_dir.parent / ".." / "packages" / "iseol" / "package.json"

hiddenimports = [
    "app.desktop.__main__",
    "app.main",
    "plugins.eeee_chat_history.main",
    "plugins.eeee_chat_history.window",
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
]
hiddenimports.extend(collect_submodules("pydantic_settings"))

pyside_binaries = collect_dynamic_libs("PySide6")
shiboken_binaries = collect_dynamic_libs("shiboken6")
shiboken_dll = next(source for source, _ in shiboken_binaries if Path(source).name == "shiboken6.abi3.dll")
binaries = [*pyside_binaries, *shiboken_binaries, (shiboken_dll, "PySide6")]

a = Analysis(
    [str(eeee_root / "app" / "desktop" / "__main__.py")],
    pathex=[str(eeee_root)],
    binaries=binaries,
    datas=[
        (str(static_dir), "app/static"),
        (str(pet_assets_dir), "app/desktop/assets"),
        (str(eeee_root / "plugins" / "eeee_chat_history"), "plugins/eeee_chat_history"),
        (str(chatgpt_runtime_dir), "chatgpt-runtime"),
        (str(chatgpt_playwright_core_dir), "chatgpt-runtime/node_modules/playwright-core"),
        (str(chatgpt_package_json), "chatgpt-runtime"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)

# Qt6Core imports the unversioned ``icuuc.dll`` name.  PyInstaller resolves
# that name from PATH and can accidentally collect Poppler's ICU build, which
# exports a different ABI and makes QtWidgets fail with WinError 127.  The
# PySide6 wheel uses the Windows ICU installation at runtime, so keep those
# unrelated Poppler binaries out of the desktop bundle.
_foreign_runtime_binaries = {"icuuc.dll", "icudt78.dll"}
a.binaries = [
    entry
    for entry in a.binaries
    if Path(entry[0]).name.lower() not in _foreign_runtime_binaries
]

pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GleaveDesktop",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

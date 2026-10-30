# Windows one-folder release. Runtime dependencies are collected by Qt hooks.
from pathlib import Path

root = Path(SPECPATH)
app_name = "\u6572\u6572"
a = Analysis(
    [str(root / "run.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["PySide6.QtTest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=app_name,
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon=str(root / "assets" / "qiaoqiao.ico"),
    version=str(Path(workpath) / "version-info.txt"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Qiaoqiao",
)

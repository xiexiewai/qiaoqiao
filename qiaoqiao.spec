# Windows one-folder release. Runtime dependencies are collected by Qt hooks.
from pathlib import Path

root = Path(SPECPATH)
app_name = "\u6572\u6572"
a = Analysis(
    [str(root / "run.py")],
    pathex=[str(root)],
    binaries=[],
    datas=[
        (str(root / "assets" / "qiaoqiao.ico"), "assets"),
        (str(root / "assets" / "qiaoqiao-pixel.png"), "assets"),
        (str(root / "assets" / "pet" / "qiaoqiao-v2" / "atlas.png"), "assets/pet/qiaoqiao-v2"),
        (str(root / "assets" / "pet" / "qiaoqiao-v2" / "atlas.json"), "assets/pet/qiaoqiao-v2"),
    ],
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

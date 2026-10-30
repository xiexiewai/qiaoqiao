"""Build and archive an immutable release without copying any user data."""

import hashlib
import importlib.metadata
import json
import os
import platform
import runpy
import shutil
import struct
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_NAME = "\u6572\u6572"


def run(*args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_files():
    files = [
        ROOT / name for name in (
            "run.py", "start.cmd", "qiaoqiao.spec", "requirements.txt",
            "requirements-build.txt", "README.md", "DEVELOPMENT.md", ".gitignore",
        )
    ]
    for folder, pattern in (
        ("qiaoqiao", "*.py"), ("tests", "*.py"), ("assets", "*.ico"), ("assets", "*.png"),
    ):
        files.extend((ROOT / folder).rglob(pattern))
    files.extend(path for path in (ROOT / "tools").iterdir() if path.suffix in (".py", ".ps1", ".txt"))
    return sorted(files)


def isolated_environment(include_python=True):
    environment = {
        key: value for key, value in os.environ.items()
        if not key.upper().startswith(("PYTHON", "QT_", "QML_"))
    }
    windows = Path(os.environ["SystemRoot"])
    paths = [windows / "System32", windows]
    if include_python:
        paths = [Path(sys.executable).parent, Path(sys.base_prefix)] + paths
    # Unrelated tools can supply incompatible same-name DLLs, such as icuuc.dll.
    environment["PATH"] = os.pathsep.join(str(path) for path in paths)
    environment["QT_QPA_PLATFORM"] = "windows"
    return environment


def main():
    if sys.platform != "win32" or struct.calcsize("P") != 8 or platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("Build this release on Windows x64 using 64-bit Python.")
    version = runpy.run_path(str(ROOT / "qiaoqiao" / "__init__.py"))["__version__"]
    parts = version.split(".")
    if len(parts) != 3 or not all(part.isdigit() and int(part) <= 65535 for part in parts):
        raise RuntimeError("Use a numeric major.minor.patch version before building.")
    stem = f"Qiaoqiao-{version}-windows-x64"
    releases = ROOT / "releases"
    outputs = [releases / f"{stem}{suffix}" for suffix in (".zip", ".sha256", "-source.zip")]
    if any(path.exists() for path in outputs):
        raise RuntimeError(f"Release {version} already exists. Increase __version__ before publishing again.")

    # Use a fresh staging directory so neither an installed version nor an old build is overwritten.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    staging = ROOT / "work" / "build" / stamp
    work = staging / "pyinstaller" / "qiaoqiao"
    work.mkdir(parents=True)
    environment = isolated_environment()
    run(sys.executable, str(ROOT / "tools" / "build_icon.py"), env=environment)
    files = source_files()
    hashes = {path.relative_to(ROOT).as_posix(): sha256(path) for path in files}
    # Raw Input tests need real HWNDs; Qt's offscreen plugin cannot register WTS notifications.
    run(sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v", env=environment)

    from PyInstaller.utils.win32.versioninfo import (
        FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
    )
    numeric_version = tuple(int(part) for part in parts) + (0,)
    info = VSVersionInfo(
        ffi=FixedFileInfo(
            filevers=numeric_version, prodvers=numeric_version, mask=0x3F,
            flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0),
        ),
        kids=[
            StringFileInfo([StringTable("080404b0", [
                StringStruct("FileDescription", APP_NAME),
                StringStruct("FileVersion", version),
                StringStruct("ProductName", APP_NAME),
                StringStruct("ProductVersion", version),
                StringStruct("OriginalFilename", APP_NAME + ".exe"),
            ])]),
            VarFileInfo([VarStruct("Translation", [2052, 1200])]),
        ],
    )
    (work / "version-info.txt").write_text(str(info), encoding="utf-8")
    run(
        sys.executable, "-m", "PyInstaller", "--noconfirm",
        "--distpath", str(staging / "dist"), "--workpath", str(work.parent),
        str(ROOT / "qiaoqiao.spec"), env=environment,
    )
    if hashes != {path.relative_to(ROOT).as_posix(): sha256(path) for path in source_files()}:
        raise RuntimeError("Source changed while building. Retry with a consistent source snapshot.")

    package = staging / "dist" / "Qiaoqiao"
    executable = package / (APP_NAME + ".exe")
    if not executable.is_file():
        raise RuntimeError("The packaged executable was not produced.")
    # The entry point imports Qt, SQLite and native input code before parsing --version.
    # Run outside the source tree with no Python/tool directories on PATH.
    smoke_directory = staging / "smoke"
    smoke_directory.mkdir()
    subprocess.run(
        [str(executable), "--version"], cwd=smoke_directory,
        env=isolated_environment(include_python=False), check=True, timeout=30,
    )
    shutil.copy2(ROOT / "tools" / "create_release_shortcut.ps1", package / "Create-Desktop-Shortcut.ps1")
    (package / "Create-Desktop-Shortcut.cmd").write_text(
        '@echo off\npowershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Create-Desktop-Shortcut.ps1"\n'
        'if errorlevel 1 pause\n', encoding="ascii",
    )
    shutil.copy2(ROOT / "tools" / "release_readme.txt", package / "README.txt")
    try:
        commit = run("git", "rev-parse", "HEAD", capture_output=True, text=True).stdout.strip()
        dirty = bool(run("git", "status", "--porcelain", capture_output=True, text=True).stdout.strip())
    except (FileNotFoundError, subprocess.CalledProcessError):
        commit, dirty = None, None
    metadata = {
        "version": version,
        "built_at_utc": stamp,
        "git_commit": commit,
        "git_dirty": dirty,
        "python": platform.python_version(),
        "validation": {"unit_tests": "passed", "packaged_import_smoke": "passed"},
        "dependencies": {
            dist.metadata["Name"]: dist.version for dist in importlib.metadata.distributions()
        },
        "source_sha256": hashes,
    }
    manifest = json.dumps(metadata, indent=2, ensure_ascii=True) + "\n"
    (package / "release.json").write_text(manifest, encoding="utf-8")
    with zipfile.ZipFile(staging / outputs[2].name, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(ROOT).as_posix())
        archive.writestr("release.json", manifest)
    with zipfile.ZipFile(staging / outputs[0].name, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                archive.write(path, Path(stem, path.relative_to(package)).as_posix())
    (staging / outputs[1].name).write_text(
        "".join(f"{sha256(staging / path.name)}  {path.name}\n" for path in (outputs[0], outputs[2])),
        encoding="ascii",
    )
    releases.mkdir(exist_ok=True)
    for path in outputs:
        # Exclusive creation also protects against concurrent builds of the same version.
        with (staging / path.name).open("rb") as source, path.open("xb") as target:
            shutil.copyfileobj(source, target)
        print(path)


if __name__ == "__main__":
    main()

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.build_release import ROOT, isolated_environment, source_files


class BuildEnvironmentTests(unittest.TestCase):
    def test_build_excludes_unrelated_dll_and_python_plugin_paths(self):
        overrides = {
            "PATH": r"C:\unrelated-tools",
            "PYTHONPATH": r"C:\unrelated-python",
            "PYTHONHOME": r"C:\unrelated-runtime",
            "QT_PLUGIN_PATH": r"C:\unrelated-qt",
            "QML_IMPORT_PATH": r"C:\unrelated-qml",
            "QT_QPA_PLATFORM": "offscreen",
        }
        with patch.dict(os.environ, overrides):
            environment = isolated_environment()
            self.assertEqual(os.environ["PATH"], overrides["PATH"])
            self.assertEqual(environment["LOCALAPPDATA"], os.environ["LOCALAPPDATA"])
        self.assertNotIn(overrides["PATH"], environment["PATH"])
        self.assertIn(str(Path(sys.executable).parent), environment["PATH"].split(os.pathsep))
        for key in ("PYTHONPATH", "PYTHONHOME", "QT_PLUGIN_PATH", "QML_IMPORT_PATH"):
            self.assertNotIn(key, environment)
        self.assertEqual(environment["QT_QPA_PLATFORM"], "windows")

    def test_packaged_smoke_has_only_windows_directories_on_path(self):
        environment = isolated_environment(include_python=False)
        windows = Path(os.environ["SystemRoot"])
        self.assertEqual(
            environment["PATH"].split(os.pathsep), [str(windows / "System32"), str(windows)],
        )


@unittest.skipUnless(sys.platform == "win32", "The double-click launcher uses Windows cmd.")
class BuildLauncherTests(unittest.TestCase):
    def test_launcher_is_in_source_snapshot(self):
        self.assertIn(ROOT / "build.cmd", source_files())

    def test_launcher_forwards_arguments_and_preserves_exit_code(self):
        # Exercise the real launcher against a stub builder, without installing or publishing.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "project space (check)!"
            (root / "tools").mkdir(parents=True)
            shutil.copy2(ROOT / "build.cmd", root / "build.cmd")
            (root / "tools" / "build.ps1").write_text(
                "param([string]$Python, [string]$IndexUrl)\n"
                "@{ directory = $PWD.Path; python = $Python; index = $IndexUrl } "
                "| ConvertTo-Json -Compress\n"
                "exit ([int]$env:QIAOQIAO_TEST_BUILD_EXIT)\n",
                encoding="ascii",
            )
            python = r"C:\Python Tools\python.exe"
            index = "https://packages.example.test/simple"
            command = (
                f'"{os.environ["ComSpec"]}" /d /s /c '
                f'""{root / "build.cmd"}" -Python "{python}" -IndexUrl "{index}""'
            )
            for code, message in ((0, "[SUCCESS]"), (23, "[ERROR]")):
                with self.subTest(exit_code=code):
                    result = subprocess.run(
                        command, cwd=directory,
                        env={**os.environ, "QIAOQIAO_TEST_BUILD_EXIT": str(code)},
                        input=b"\n", capture_output=True, timeout=30,
                    )
                    self.assertEqual(result.returncode, code, result.stdout + result.stderr)
                    output = result.stdout.decode("ascii", errors="replace")
                    self.assertIn(message, output)
                    payload = json.loads(next(line for line in output.splitlines() if line.startswith("{")))
                    self.assertEqual(payload, {"directory": str(root), "python": python, "index": index})
                    if code:
                        self.assertNotIn("[SUCCESS]", output)


if __name__ == "__main__":
    unittest.main()

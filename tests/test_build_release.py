import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.build_release import isolated_environment


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


if __name__ == "__main__":
    unittest.main()

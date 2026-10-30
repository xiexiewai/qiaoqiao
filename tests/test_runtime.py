import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qiaoqiao import __version__
from qiaoqiao.runtime import parse_runtime


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.local = Path(self.temp.name).resolve()
        self.environment = patch.dict(os.environ, {"LOCALAPPDATA": str(self.local)})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temp.cleanup()

    def parse(self, args=(), frozen=False):
        with patch.object(sys, "frozen", frozen, create=True):
            return parse_runtime(list(args))

    def assert_invalid(self, args, frozen=False):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            self.parse(args, frozen)
        self.assertEqual(error.exception.code, 2)

    def test_source_defaults_to_development_without_creating_production_data(self):
        runtime = self.parse()
        self.assertTrue(runtime.development)
        self.assertEqual(runtime.directory, self.local / "Qiaoqiao-dev")
        self.assertFalse((self.local / "Qiaoqiao").exists())
        self.assertIn("\u5f00\u53d1\u7248", runtime.title)
        self.assertIn(__version__, runtime.title)

    def test_release_keeps_existing_production_database_location(self):
        runtime = self.parse(frozen=True)
        self.assertFalse(runtime.development)
        self.assertEqual(runtime.directory, self.local / "Qiaoqiao")
        self.assertNotIn("\u5f00\u53d1\u7248", runtime.title)

    def test_packaged_development_mode_uses_separate_data(self):
        self.assertEqual(self.parse(["--dev"], frozen=True), self.parse())

    def test_custom_development_directory(self):
        directory = self.local / "acceptance test"
        self.assertEqual(
            self.parse(["--dev", "--data-dir", str(directory)], frozen=True).directory, directory,
        )

    def test_packaged_production_cannot_override_directory(self):
        self.assert_invalid(["--data-dir", str(self.local / "other")], frozen=True)

    def test_source_cannot_point_at_production_directory(self):
        self.assert_invalid(["--data-dir", str(self.local / "Qiaoqiao")])

    def test_packaged_dev_cannot_point_at_production_even_through_relative_components(self):
        self.assert_invalid(
            ["--dev", "--data-dir", str(self.local / "other" / ".." / "QIAOQIAO")], frozen=True,
        )


if __name__ == "__main__":
    unittest.main()

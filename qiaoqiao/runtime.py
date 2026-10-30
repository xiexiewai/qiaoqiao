"""Select isolated application data before starting any Qt or database work."""

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from . import __version__

APP_NAME = "\u6572\u6572"


@dataclass(frozen=True)
class Runtime:
    development: bool
    directory: Path

    @property
    def name(self) -> str:
        return APP_NAME + (" \u5f00\u53d1\u7248" if self.development else "")

    @property
    def title(self) -> str:
        return f"{self.name} {__version__}"


def parse_runtime(argv=None) -> Runtime:
    parser = argparse.ArgumentParser(description="Qiaoqiao keyboard statistics")
    parser.add_argument("--dev", action="store_true", help="Use isolated development data")
    parser.add_argument("--data-dir", type=Path, help="Override the development data directory")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args(argv)
    # Source runs must never inherit the user's production database by default.
    development = args.dev or not getattr(sys, "frozen", False)
    local = Path(os.environ["LOCALAPPDATA"])
    production = (local / "Qiaoqiao").resolve()
    directory = (local / ("Qiaoqiao-dev" if development else "Qiaoqiao")).resolve()
    if args.data_dir is not None:
        if not development:
            parser.error("--data-dir requires --dev in a packaged application")
        directory = args.data_dir.expanduser().resolve()
        if directory == production:
            parser.error("Development mode cannot use the production data directory")
    return Runtime(development, directory)

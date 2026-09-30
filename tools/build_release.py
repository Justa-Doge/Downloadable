#!/usr/bin/env python3
"""Build a clean cross-platform Downloadable release archive."""

from __future__ import annotations

import argparse
import stat
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FIXED_FILES = [
    ".gitignore",
    "README.md",
    "com.downloadable.helper.plist",
    "setup.command",
    "start.command",
    "setup.ps1",
    "start.ps1",
    "setup.cmd",
    "start.cmd",
    "helper/helper.py",
]


def package_files() -> list[Path]:
    files = [ROOT / name for name in FIXED_FILES]
    files.extend(path for path in (ROOT / "extension").rglob("*") if path.is_file())
    return sorted(
        (path for path in files if path.name != "config.js" and not path.name.startswith(".!") and path.name != ".DS_Store"),
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )


def build(output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in package_files():
            relative = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo.from_file(path, relative)
            info.create_system = 3
            executable = path.suffix == ".command" or relative == "helper/helper.py"
            mode = stat.S_IFREG | (0o755 if executable else 0o644)
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as source, archive.open(info, "w") as destination:
                destination.write(source.read())
    print(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", type=Path, default=ROOT / "personal-media-downloader-1.0.zip")
    args = parser.parse_args()
    build(args.output.resolve())


if __name__ == "__main__":
    main()

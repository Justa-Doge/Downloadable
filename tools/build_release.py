#!/usr/bin/env python3
"""Build clean platform-specific Downloadable release archives."""

from __future__ import annotations

import argparse
import stat
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FIXED_FILES = [
    ".gitignore",
    "README.md",
    "CHANGELOG.md",
    "com.downloadable.helper.plist",
    "Downloadable.cmd",
    "launchers/macos/setup.command",
    "launchers/windows/setup.ps1",
    "launchers/windows/start.ps1",
    "launchers/windows/setup.cmd",
    "launchers/windows/start.cmd",
    "launchers/linux/setup.sh",
    "launchers/linux/start.sh",
    "helper/helper.py",
]

PLATFORM_FILES = {
    "windows": {
        "Downloadable.cmd",
        "launchers/windows/setup.ps1",
        "launchers/windows/start.ps1",
        "launchers/windows/setup.cmd",
        "launchers/windows/start.cmd",
    },
    "macos": {
        "com.downloadable.helper.plist",
        "launchers/macos/setup.command",
    },
    "linux": {
        "launchers/linux/setup.sh",
        "launchers/linux/start.sh",
    },
    "linux-chromeos": {
        "launchers/linux/setup.sh",
        "launchers/linux/start.sh",
    },
}


def package_files(platform: str = "all") -> list[Path]:
    allowed = PLATFORM_FILES.get(platform)
    files = [
        ROOT / name
        for name in FIXED_FILES
        if allowed is None or name not in PLATFORM_FILES["windows"] | PLATFORM_FILES["macos"] | PLATFORM_FILES["linux"] or name in allowed
    ]
    files.extend(path for path in (ROOT / "extension").rglob("*") if path.is_file())
    return sorted(
        (path for path in files if path.name != "config.js" and not path.name.startswith(".!") and path.name != ".DS_Store"),
        key=lambda path: path.relative_to(ROOT).as_posix(),
    )


def build(output: Path, platform: str = "all") -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in package_files(platform):
            relative = path.relative_to(ROOT).as_posix()
            info = zipfile.ZipInfo.from_file(path, relative)
            info.create_system = 3
            executable = path.suffix in {".command", ".sh"} or relative == "helper/helper.py"
            mode = stat.S_IFREG | (0o755 if executable else 0o644)
            info.external_attr = mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            with path.open("rb") as source, archive.open(info, "w") as destination:
                destination.write(source.read())
    print(output)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", nargs="?", type=Path)
    parser.add_argument("--platform", choices=("all", "windows", "macos", "linux", "linux-chromeos"), default="all")
    args = parser.parse_args()
    if args.output is None:
        # Keep the extracted install folder stable across updates. The
        # manifest and GitHub release tag carry the version; the archive
        # filename should not create a new `...-1.5.x` folder each time.
        suffix = "" if args.platform == "all" else f"-{args.platform}"
        args.output = ROOT / f"personal-media-downloader{suffix}.zip"
    build(args.output.resolve(), args.platform)


if __name__ == "__main__":
    main()

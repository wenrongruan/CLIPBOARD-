"""Merge application settings without replacing PyInstaller's bundle metadata."""

from __future__ import annotations

import argparse
import plistlib
from pathlib import Path


def merge_bundle_plist(bundle: Path, overrides: Path) -> None:
    destination = bundle / "Contents" / "Info.plist"
    with destination.open("rb") as stream:
        generated = plistlib.load(stream)
    with overrides.open("rb") as stream:
        settings = plistlib.load(stream)

    executable = generated.get("CFBundleExecutable")
    if not isinstance(executable, str) or not executable or Path(executable).name != executable:
        raise ValueError("Generated bundle has no valid CFBundleExecutable")
    if not (bundle / "Contents" / "MacOS" / executable).is_file():
        raise ValueError("Bundle executable does not exist")

    # These values identify resources actually emitted by the packager.
    protected = {"CFBundleExecutable", "CFBundleIconFile", "CFBundleIconName"}
    generated.update({key: value for key, value in settings.items() if key not in protected})
    with destination.open("wb") as stream:
        plistlib.dump(generated, stream)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bundle", type=Path)
    parser.add_argument("overrides", type=Path)
    args = parser.parse_args()
    merge_bundle_plist(args.bundle, args.overrides)

"""Check the real merge operation used by local and CI macOS builds."""

import plistlib
from pathlib import Path

import pytest

from scripts.merge_bundle_plist import merge_bundle_plist


def test_merge_preserves_packaged_executable_and_icon(tmp_path):
    bundle = tmp_path / "SharedClipboard.app"
    contents = bundle / "Contents"
    (contents / "MacOS").mkdir(parents=True)
    executable = contents / "MacOS" / "共享剪贴板"
    executable.write_bytes(b"test executable")
    original = {
        "CFBundleExecutable": executable.name,
        "CFBundleIconFile": "packaged.icns",
        "NSPrincipalClass": "NSApplication",
    }
    with (contents / "Info.plist").open("wb") as stream:
        plistlib.dump(original, stream)
    overrides = Path(__file__).resolve().parents[1] / "Info.plist"

    merge_bundle_plist(bundle, overrides)

    with (contents / "Info.plist").open("rb") as stream:
        merged = plistlib.load(stream)
    assert merged["CFBundleExecutable"] == executable.name
    assert merged["CFBundleIconFile"] == "packaged.icns"
    assert merged["NSPrincipalClass"] == "NSApplication"
    assert merged["LSUIElement"] is True
    assert merged["CFBundleVersion"]


def test_merge_rejects_bundle_without_executable(tmp_path):
    bundle = tmp_path / "broken.app"
    contents = bundle / "Contents"
    contents.mkdir(parents=True)
    destination = contents / "Info.plist"
    with destination.open("wb") as stream:
        plistlib.dump({"CFBundleExecutable": "missing"}, stream)
    before = destination.read_bytes()
    overrides = Path(__file__).resolve().parents[1] / "Info.plist"

    with pytest.raises(ValueError, match="does not exist"):
        merge_bundle_plist(bundle, overrides)
    assert destination.read_bytes() == before

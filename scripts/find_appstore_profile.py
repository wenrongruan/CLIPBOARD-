#!/usr/bin/env python3
"""Locate the best matching Mac App Store provisioning profile."""

from __future__ import annotations

import argparse
import json
import plistlib
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Iterable


def _extract_plist_bytes(raw: bytes) -> bytes | None:
    xml_start = raw.find(b"<?xml")
    xml_end = raw.rfind(b"</plist>")
    if xml_start != -1 and xml_end != -1 and xml_end > xml_start:
        xml_end += len(b"</plist>")
        return raw[xml_start:xml_end]

    bin_start = raw.find(b"bplist00")
    if bin_start != -1:
        return raw[bin_start:]
    return None


def _load_profile(path: Path) -> dict | None:
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    payload = _extract_plist_bytes(raw)
    if payload is None:
        return None
    try:
        return plistlib.loads(payload)
    except Exception:
        return None


def _coerce_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC)
    return None


def _platforms(profile: dict) -> list[str]:
    values = profile.get("Platform")
    if isinstance(values, list):
        return [str(v) for v in values]
    if isinstance(values, str):
        return [values]
    return []


def _is_macos_profile(platforms: Iterable[str]) -> bool:
    norm = {p.lower() for p in platforms}
    return any(token in norm for token in ("macos", "macosx", "osx"))


@dataclass
class Candidate:
    path: Path
    name: str
    app_identifier: str
    team_id: str
    platforms: list[str]
    expiration: datetime | None
    get_task_allow: bool | None
    has_devices: bool

    @property
    def expired(self) -> bool:
        return self.expiration is not None and self.expiration < datetime.now(UTC)

    @property
    def store_like(self) -> bool:
        return (self.get_task_allow is False) and (not self.has_devices)

    def score(self, expected_app_id: str) -> tuple[int, int, int, int, int]:
        return (
            int(self.app_identifier == expected_app_id),
            int(_is_macos_profile(self.platforms)),
            int(not self.expired),
            int(self.store_like),
            int(self.expiration.timestamp()) if self.expiration else 0,
        )

    def to_dict(self) -> dict:
        return {
            "path": str(self.path),
            "name": self.name,
            "app_identifier": self.app_identifier,
            "team_id": self.team_id,
            "platforms": self.platforms,
            "expiration": self.expiration.isoformat() if self.expiration else None,
            "expired": self.expired,
            "get_task_allow": self.get_task_allow,
            "has_devices": self.has_devices,
            "store_like": self.store_like,
        }


def _iter_candidate_files(roots: list[Path]) -> Iterable[Path]:
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            files = [root]
        else:
            files = [
                *root.glob("*.provisionprofile"),
                *root.glob("*.mobileprovision"),
            ]
        for file in files:
            resolved = file.resolve()
            if resolved not in seen:
                seen.add(resolved)
                yield resolved


def _collect_candidates(bundle_id: str, team_id: str, roots: list[Path]) -> list[Candidate]:
    expected_app_id = f"{team_id}.{bundle_id}"
    candidates: list[Candidate] = []
    for file in _iter_candidate_files(roots):
        profile = _load_profile(file)
        if not profile:
            continue
        entitlements = profile.get("Entitlements") or {}
        if not isinstance(entitlements, dict):
            entitlements = {}
        app_identifier = (
            entitlements.get("com.apple.application-identifier")
            or entitlements.get("application-identifier")
            or ""
        )
        if not isinstance(app_identifier, str):
            continue
        if app_identifier != expected_app_id:
            continue
        candidate = Candidate(
            path=file,
            name=str(profile.get("Name") or file.name),
            app_identifier=app_identifier,
            team_id=str(
                entitlements.get("com.apple.developer.team-identifier")
                or (profile.get("TeamIdentifier") or [""])[0]
            ),
            platforms=_platforms(profile),
            expiration=_coerce_datetime(profile.get("ExpirationDate")),
            get_task_allow=entitlements.get("get-task-allow")
            if isinstance(entitlements.get("get-task-allow"), bool)
            else None,
            has_devices=bool(profile.get("ProvisionedDevices")),
        )
        candidates.append(candidate)
    candidates.sort(key=lambda item: item.score(expected_app_id), reverse=True)
    return candidates


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--all", action="store_true", help="print all matching candidates")
    parser.add_argument("roots", nargs="*")
    args = parser.parse_args()

    default_roots = [
        Path.cwd(),
        Path.cwd() / "profiles",
        Path.home() / "Library/Developer/Xcode/UserData/Provisioning Profiles",
        Path.home() / "Library/MobileDevice/Provisioning Profiles",
    ]
    roots = [Path(p).expanduser() for p in args.roots] if args.roots else default_roots

    candidates = _collect_candidates(args.bundle_id, args.team_id, roots)
    if args.json:
        if args.all:
            print(json.dumps([c.to_dict() for c in candidates], ensure_ascii=False, indent=2))
        else:
            print(json.dumps(candidates[0].to_dict() if candidates else {}, ensure_ascii=False, indent=2))
        return 0 if candidates else 1

    if args.all:
        for item in candidates:
            print(item.path)
        return 0 if candidates else 1

    if not candidates:
        return 1
    print(candidates[0].path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

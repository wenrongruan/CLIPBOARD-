# SharedClipboard Release Checklist

Date: 2026-05-21

Use this checklist before tagging or packaging a v1.0-style release.

## 1. Workspace Hygiene

- Review `git status --short`.
- Separate unrelated local changes from release changes.
- Confirm newly added files are intentionally tracked.
- Do not ship with debug-only files, local logs, or generated build artifacts unless they are expected release inputs.
- Review `RISK_REGISTER.md` and confirm every P0 gate is satisfied.

## 2. Automated Tests

Run the full suite:

```powershell
pytest -q
```

Run the local main-path E2E explicitly:

```powershell
pytest tests/test_clipboard_e2e_local.py -vv
```

Run startup and health guardrails:

```powershell
pytest tests/test_startup_metrics.py tests/test_health_reporter.py tests/test_smoke.py -q
```

Expected release gate: all tests pass.

## 3. Startup Performance Baseline

Collect startup metrics:

```powershell
$env:SC_STARTUP_METRICS='1'
python main.py
```

Record the emitted `[startup-metrics]` line in the release notes or internal build log.

Check that:

- `qt_app_init`, `init_components`, and `create_main_window` are visible.
- `plugin_load_deferred` is not part of blocking startup.
- `cloud_sync_start_deferred` and `file_sync_start_deferred` occur only after delay when enabled.
- No network-only feature blocks local startup.

Clear the environment variable after testing:

```powershell
Remove-Item Env:\SC_STARTUP_METRICS
```

## 4. Manual Main-Path Smoke Test

On a clean or disposable profile:

1. Launch the app.
2. Copy a short text snippet.
3. Open the window with the hotkey or tray/menu-bar action.
4. Confirm the copied snippet appears.
5. Search for a word inside the snippet.
6. Click/copy the history item back.
7. Copy the same snippet again.
8. Confirm the list does not create obvious duplicate rows.
9. Favorite the item and confirm the favorite state persists after restart.

## 5. Degradation Checks

Verify the app remains useful when enhancements fail:

- Start while logged out: local history still works.
- Disable or break network access: local capture and search still work.
- Disable plugin loading or use an empty plugin directory: main window still opens.
- Use unavailable global hotkey dependencies/permissions: tray/menu-bar opening still works.
- If MySQL is misconfigured: app falls back to local SQLite with a health warning.
- If keyring is unavailable: app records degraded credential storage status.

## 6. Optional Feature Checks

Only run these when the corresponding feature is enabled for the release:

- Cloud login succeeds and logout returns to local mode.
- Cloud sync starts after the delay and does not freeze the UI.
- File sync creates services on demand and fails safely.
- Team tab opens without blocking startup.
- Plugin tab opens, refreshes installed plugin state, and reload works.
- Plugin store network failure shows an error state rather than crashing.

## 7. Packaging Checks

Windows:

- Build from a clean virtual environment.
- Confirm tray icon is visible.
- Confirm global hotkey behavior.
- Confirm SQLite database is created under `%APPDATA%\SharedClipboard\`.

macOS:

- Confirm menu-bar/tray behavior.
- Confirm input monitoring/accessibility permission handling.
- Confirm app quits cleanly.
- Confirm data directory is under `~/Library/Application Support/SharedClipboard/`.

Linux:

- Confirm clipboard polling works under the target desktop environment.
- Confirm Wayland/X11 behavior where supported.
- Confirm data directory is under `~/.config/SharedClipboard/`.

## 8. Release Notes Minimum

Release notes should include:

- What changed in the local clipboard core.
- Known limitations for cloud/file/team/plugin features.
- Any required permission steps for hotkeys or clipboard access.
- Startup metrics summary for the build.
- Test command and pass count from the release candidate.

## 9. Final Gate

Do not release if any of these are true:

- Local text copy does not reliably enter history.
- Search cannot find newly copied text.
- Startup depends on cloud/network availability.
- Plugin failure prevents main window creation.
- Cloud/file sync failure breaks local capture.
- The full automated suite is failing without an explicit, documented reason.

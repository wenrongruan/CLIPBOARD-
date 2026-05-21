# SharedClipboard Risk Register

Date: 2026-05-21

This register tracks release risk for the local-first v1.0 boundary defined in `PRODUCT_V1.md`.

## Severity Model

- P0: Blocks release. The local clipboard main path is broken or data safety is at risk.
- P1: Must be verified before release. Acceptable only with a clear fallback or documented limitation.
- P2: Can ship with known limitation. Track for a later version.

## P0 Release Blockers

| Risk | Impact | Current Mitigation | Release Gate |
| --- | --- | --- | --- |
| Local text copy is not persisted | Product promise fails | `tests/test_clipboard_e2e_local.py` covers fake clipboard -> real monitor -> real SQLite | E2E passes and manual smoke passes |
| Search cannot find newly copied content | User cannot recover copied items | E2E covers `search_by_keyword`; query parser tests cover search behavior | E2E and query tests pass |
| Duplicate copy creates uncontrolled duplicate rows | History becomes noisy and trust drops | Monitor/repository duplicate tests cover hash and touch behavior | E2E confirms same item id and one row |
| Startup depends on cloud/network/plugin availability | App becomes unusable offline | Cloud/file/plugin are delayed or optional; health reporter records degraded states | Logged-out/offline startup works |
| Plugin failure prevents main window creation | Optional enhancement breaks core app | Plugin loading is deferred; plugin store auto-load is disabled in smoke tests | `tests/test_smoke.py` passes |
| Database handle leaks break shutdown or temp cleanup | Data loss or flaky releases | Tests close DB; monitor stop shuts down executor | Full suite passes on Windows |

## P1 Release Verification Risks

| Risk | Impact | Current Mitigation | Required Check |
| --- | --- | --- | --- |
| Global hotkey unavailable due to dependency or OS permission | User cannot summon app quickly | Runtime health warning; tray/menu-bar fallback | Manual check hotkey + tray/menu-bar opening |
| macOS input monitoring/accessibility permission flow is unclear | App appears broken on first run | Permission prompt path exists | Manual macOS permission smoke before release |
| Keyring unavailable or degraded | Credentials may use weaker fallback storage | `core/health_reporter.py` aggregates degraded credential warning | Simulate unavailable keyring or inspect degraded warning |
| MySQL misconfiguration | User expects sync but app is local-only | MySQL fallback health warning | Misconfigure MySQL and confirm local SQLite still works |
| Cloud sync startup failure | User may think data is synced when it is not | Delayed startup wrapper records runtime warning | Disable network and verify local capture continues |
| File sync startup failure | File feature fails noisily or blocks UI | File sync service is built on demand and failure-isolated | Enable file sync with network unavailable |
| Plugin tab stale after deferred load | Settings page shows empty/incorrect state | `PluginManager.plugins_changed` refreshes plugin tab | Open settings before/after plugin load |
| Startup performance regresses | Main path feels slow | `core/startup_metrics.py` and `SC_STARTUP_METRICS=1` | Record startup metrics for release candidate |

## P2 Known Limitations

| Risk | Why It Can Ship | Follow-Up |
| --- | --- | --- |
| Plugin marketplace governance is immature | Plugins are optional and deferred | Add plugin signing/review/version policy later |
| Complex team permissions are not fully defined | Team is optional enhancement | Define role matrix after real team usage is validated |
| Advanced cloud conflict resolution UI is limited | Local history remains authoritative | Add user-facing conflict tools after sync telemetry/manual reports |
| Large-file auto-download policy needs tuning | File sync is optional and gated | Add explicit per-device download settings |
| Linux Wayland clipboard behavior varies by desktop | Cross-platform support can document limitations | Build targeted Wayland compatibility matrix |
| Full telemetry is absent | v1.0 can ship without analytics | Add privacy-preserving local metrics proposal later |

## Operational Risks Before Commit

The current worktree contains multiple modified files and new files. Before creating a release branch or commit:

- Split unrelated pre-existing changes from the v1.0 hardening changes.
- Group commits by intent: product docs, health reporting, startup metrics, lazy optional services, main-path tests.
- Re-run `pytest -q` after each split if commits are rearranged.
- Avoid reverting user changes in `config.py`, cloud sync, tag sync, or cloud login files unless explicitly requested.

## Manual Release Decision

Release is acceptable only when all P0 gates pass and each P1 item has one of:

- Verified in the release candidate.
- Documented as an expected limitation.
- Disabled from the default path.

When uncertain, protect the local clipboard path first and postpone the enhancement.

# SharedClipboard v1.0 Product Boundary

Date: 2026-05-21

## Positioning

SharedClipboard v1.0 is a local-first clipboard history manager.

The primary promise is simple: copied content should be easy to find again. Cloud, files, teams, sharing, and plugins remain valuable, but they are optional enhancements. They must not block local clipboard capture, search, or restore.

## v1.0 Default Experience

These capabilities are part of the default product path and should work without login:

- Local text and image clipboard history.
- Fast list browsing and keyword search.
- Favorite/starred items.
- Tags and source-app metadata where available.
- Global hotkey and tray/menu-bar access.
- Local SQLite storage.
- Settings for retention, filters, hotkey, language, and database mode.
- Graceful degradation when hotkey, keyring, MySQL, or cloud services are unavailable.

Default behavior should be quiet. The app should run in the background, capture safely, and appear only when the user asks for it.

## v1.0 Optional Enhancements

These capabilities may ship in v1.0, but they are not required for the core experience:

- Cloud sync for clipboard history.
- File cloud sync.
- Team spaces.
- Share links.
- Plugin loading and plugin execution.
- Plugin store access.
- MySQL/self-hosted sync mode.

Optional enhancements must follow these rules:

- They are lazy-loaded or delayed where possible.
- Failure must degrade to local clipboard history.
- They should surface errors through health/status messaging, not repeated blocking dialogs.
- They must not make local startup, capture, search, or restore depend on network availability.

## Explicit Non-Goals For v1.0

The following should not be treated as v1.0 release blockers:

- Mature plugin marketplace governance.
- Complex team permission models.
- Advanced multi-device conflict resolution UI.
- Large-file automatic download policy tuning.
- Enterprise admin controls.
- Full telemetry or growth analytics.
- Complete cloud-first onboarding.

These can be planned after the local-first product path is stable in real use.

## Release Quality Bar

v1.0 is releasable only if the local main path is protected:

- Startup reaches the event loop without loading plugins synchronously.
- Copying text creates a local record.
- Re-copying the same text does not duplicate rows and can move the existing item to the top.
- Search can find newly copied content.
- Cloud/file/plugin startup failures do not break local history.
- Tests pass in a clean environment.

## Current Technical Guardrails

The current codebase includes guardrails that should remain in place:

- `core/health_reporter.py` aggregates degraded states.
- `core/startup_metrics.py` records startup phase timings.
- `tests/test_clipboard_e2e_local.py` protects the local clipboard main path.
- Plugin loading is deferred.
- Cloud sync and file sync startup are delayed and failure-isolated.
- File sync worker construction is on demand.

## Product Rule

When there is tension between core clipboard reliability and an enhancement feature, choose core reliability. Enhancements can wait; losing copied content cannot.

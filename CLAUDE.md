# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

SharedClipboard (共享剪贴板) is a Windows desktop application for clipboard history management and cross-device synchronization. Built with PySide6 (Qt for Python), it runs as a system tray application with an edge-docking slide-out window.

## Running the Application

```bash
python main.py
```

## Dependencies

Install dependencies with:
```bash
pip install -r requirements.txt
```

Key dependencies: PySide6 (>=6.6.0), Pillow (>=10.0.0)

## Architecture

### Core Layer (`core/`)
- **models.py**: `ClipboardItem` dataclass with `ContentType` enum (TEXT/IMAGE)
- **database.py**: `DatabaseManager` with SQLite/WAL mode, FTS5 full-text search, retry logic for database locks
- **repository.py**: `ClipboardRepository` for CRUD operations with pagination and search
- **clipboard_monitor.py**: `ClipboardMonitor` polls system clipboard every 500ms, detects text/image changes via content hash deduplication
- **sync_service.py**: `SyncService` polls database for new items from other devices (default 1s interval)

### UI Layer (`ui/`)
- **edge_window.py**: `EdgeHiddenWindow` base class - frameless window that docks to screen edges (left/right/top/bottom) with slide-in/out animations
- **main_window.py**: `MainWindow` extends `EdgeHiddenWindow` - search, pagination, settings dialog
- **clipboard_item.py**: `ClipboardItemWidget` for rendering individual clipboard entries
- **styles.py**: Dark theme QSS stylesheets

### Configuration (`config.py`)
- `Config` class provides static methods for settings (stored in `%APPDATA%/SharedClipboard/settings.json`)
- Device ID generated from MAC address hash
- Database defaults to `clipboard.db` in project root

### Utils (`utils/`)
- **hash_utils.py**: SHA-256 content hashing (truncated to 32 chars)
- **image_utils.py**: Pillow-based thumbnail generation

## Key Design Patterns

1. **Signal-based communication**: Qt Signals connect clipboard changes and sync events to UI updates
2. **Polling over events**: Clipboard monitoring uses QTimer polling (more reliable on Windows than Qt's dataChanged signal)
3. **Database deduplication**: Content hash prevents duplicate entries
4. **Lazy image loading**: Thumbnail stored separately; full image loaded only when copying back to clipboard

## Database Schema

SQLite database with FTS5 search. Main table `clipboard_items`:
- id, content_type, text_content, image_data, image_thumbnail
- content_hash (unique), preview, device_id, device_name
- created_at (timestamp ms), is_starred

## Multi-device Sync

Devices share the same database file (e.g., via network drive). Each device has a unique `device_id`. The sync service queries for items with `id > last_sync_id AND device_id != this_device`.

## Cross-Platform Support

The application supports both Windows and macOS:

### Platform-specific Adjustments
- **config.py**: `Config.IS_WINDOWS`, `Config.IS_MACOS`, `Config.IS_LINUX` flags
- **styles.py**: Platform-specific fonts (Microsoft YaHei on Windows, SF Pro on macOS)
- **edge_window.py**: Uses `availableGeometry()` to respect macOS menu bar and Dock
- **main.py**: macOS menu bar icon with template image support for dark mode

### Building for macOS

Using py2app:
```bash
pip install py2app
python build_macos.py py2app
```

The built app will be in `dist/共享剪贴板.app`

Using PyInstaller (cross-platform):
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "SharedClipboard" main.py
```

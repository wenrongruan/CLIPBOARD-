"""core.source_app 测试。

所有底层 API（pywin32、AppKit、Xlib、jeepney）全部 mock，
保证在任何平台 / CI 环境都能跑绿。
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from core import source_app as sa_pkg
from core.source_app.base import SourceApp, SourceAppProvider
from core.source_app.noop import NoopSourceAppProvider


# ---------------------------------------------------------------------------
# SourceApp dataclass
# ---------------------------------------------------------------------------


class TestSourceAppDataclass(unittest.TestCase):
    def test_default_is_empty(self):
        self.assertTrue(SourceApp().is_empty)

    def test_only_title_is_still_empty(self):
        # window_title 不算身份信息
        self.assertTrue(SourceApp(window_title="Hello").is_empty)

    def test_any_identity_field_not_empty(self):
        self.assertFalse(SourceApp(app_name="Chrome").is_empty)
        self.assertFalse(SourceApp(bundle_id="chrome.exe").is_empty)
        self.assertFalse(SourceApp(exe_path="/usr/bin/chrome").is_empty)

    def test_frozen(self):
        sa = SourceApp(app_name="x")
        with self.assertRaises(Exception):
            sa.app_name = "y"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Noop provider
# ---------------------------------------------------------------------------


class TestNoopProvider(unittest.TestCase):
    def test_always_available(self):
        self.assertTrue(NoopSourceAppProvider().is_available)

    def test_returns_empty(self):
        app = NoopSourceAppProvider().get_current()
        self.assertTrue(app.is_empty)


# ---------------------------------------------------------------------------
# Factory 按平台选择
# ---------------------------------------------------------------------------


class TestFactory(unittest.TestCase):
    def setUp(self):
        sa_pkg.reset_provider()

    def tearDown(self):
        sa_pkg.reset_provider()

    def test_get_provider_is_singleton(self):
        with patch.object(sa_pkg, "_create_provider", return_value=NoopSourceAppProvider()) as m:
            p1 = sa_pkg.get_provider()
            p2 = sa_pkg.get_provider()
            self.assertIs(p1, p2)
            self.assertEqual(m.call_count, 1)

    def test_factory_windows(self):
        fake = MagicMock(spec=SourceAppProvider)
        fake.is_available = True
        fake_module = types.SimpleNamespace(
            WindowsSourceAppProvider=MagicMock(return_value=fake)
        )
        with patch.object(sys, "platform", "win32"):
            with patch.dict(sys.modules, {"core.source_app.windows": fake_module}):
                got = sa_pkg._create_provider()
                self.assertIs(got, fake)

    def test_factory_macos(self):
        fake = MagicMock(spec=SourceAppProvider)
        fake.is_available = True
        fake_module = types.SimpleNamespace(
            MacOSSourceAppProvider=MagicMock(return_value=fake)
        )
        with patch.object(sys, "platform", "darwin"):
            with patch.dict(sys.modules, {"core.source_app.macos": fake_module}):
                got = sa_pkg._create_provider()
                self.assertIs(got, fake)

    def test_factory_linux_x11(self):
        fake = MagicMock(spec=SourceAppProvider)
        fake.is_available = True
        fake_module = types.SimpleNamespace(
            X11SourceAppProvider=MagicMock(return_value=fake)
        )
        with patch.object(sys, "platform", "linux"):
            with patch.dict("os.environ", {"DISPLAY": ":0"}, clear=False):
                # 确保没有 WAYLAND_DISPLAY
                import os
                os.environ.pop("WAYLAND_DISPLAY", None)
                with patch.dict(sys.modules, {"core.source_app.linux_x11": fake_module}):
                    got = sa_pkg._create_provider()
                    self.assertIs(got, fake)

    def test_factory_linux_wayland_preferred(self):
        fake_wayland = MagicMock(spec=SourceAppProvider)
        fake_wayland.is_available = True
        fake_module = types.SimpleNamespace(
            WaylandSourceAppProvider=MagicMock(return_value=fake_wayland)
        )
        with patch.object(sys, "platform", "linux"):
            with patch.dict("os.environ", {"WAYLAND_DISPLAY": "wayland-0"}, clear=False):
                with patch.dict(sys.modules, {"core.source_app.linux_wayland": fake_module}):
                    got = sa_pkg._create_provider()
                    self.assertIs(got, fake_wayland)

    def test_factory_falls_back_to_noop_on_exception(self):
        with patch.object(sys, "platform", "win32"):
            def _boom():
                raise RuntimeError("boom")
            # 让 _create_provider 在 win32 分支抛异常
            fake_module = types.SimpleNamespace(
                WindowsSourceAppProvider=MagicMock(side_effect=RuntimeError("boom"))
            )
            with patch.dict(sys.modules, {"core.source_app.windows": fake_module}):
                got = sa_pkg._create_provider()
                self.assertIsInstance(got, NoopSourceAppProvider)

    def test_get_current_source_app_swallows_errors(self):
        bad = MagicMock(spec=SourceAppProvider)
        bad.get_current.side_effect = RuntimeError("boom")
        with patch.object(sa_pkg, "_provider", bad):
            result = sa_pkg.get_current_source_app()
            self.assertTrue(result.is_empty)


# ---------------------------------------------------------------------------
# Windows provider
# ---------------------------------------------------------------------------


class TestWindowsProvider(unittest.TestCase):
    def _make_fake_modules(self, hwnd=1234, title="Tab - Chrome", pid=999,
                           exe_name="chrome.exe", exe_path=r"C:\Program Files\Chrome\chrome.exe"):
        win32gui = MagicMock()
        win32gui.GetForegroundWindow.return_value = hwnd
        win32gui.GetWindowText.return_value = title

        win32process = MagicMock()
        win32process.GetWindowThreadProcessId.return_value = (0, pid)

        psutil = MagicMock()
        proc = MagicMock()
        proc.name.return_value = exe_name
        proc.exe.return_value = exe_path
        psutil.Process.return_value = proc
        return win32gui, win32process, psutil

    def test_get_current_via_pywin32(self):
        w, p, ps = self._make_fake_modules()
        with patch.dict(sys.modules, {"win32gui": w, "win32process": p, "psutil": ps}):
            from core.source_app.windows import WindowsSourceAppProvider
            provider = WindowsSourceAppProvider()
            self.assertTrue(provider.is_available)
            app = provider.get_current()
            self.assertEqual(app.bundle_id, "chrome.exe")
            self.assertEqual(app.app_name, "Chrome")
            self.assertEqual(app.exe_path, r"C:\Program Files\Chrome\chrome.exe")
            self.assertEqual(app.window_title, "Tab - Chrome")

    def test_unavailable_returns_empty(self):
        # 强制 import 失败
        with patch.dict(sys.modules, {"win32gui": None, "win32process": None}):
            from core.source_app.windows import WindowsSourceAppProvider
            provider = WindowsSourceAppProvider()
            # win32gui=None 时 import 会抛 ImportError
            if not provider.is_available:
                self.assertTrue(provider.get_current().is_empty)

    def test_no_foreground_window_returns_empty(self):
        w, p, ps = self._make_fake_modules(hwnd=0)
        with patch.dict(sys.modules, {"win32gui": w, "win32process": p, "psutil": ps}):
            from core.source_app.windows import WindowsSourceAppProvider
            provider = WindowsSourceAppProvider()
            app = provider.get_current()
            self.assertTrue(app.is_empty)


# ---------------------------------------------------------------------------
# macOS provider
# ---------------------------------------------------------------------------


class TestMacOSProvider(unittest.TestCase):
    def test_returns_app_info(self):
        fake_app = MagicMock()
        fake_app.localizedName.return_value = "Google Chrome"
        fake_app.bundleIdentifier.return_value = "com.google.Chrome"
        fake_url = MagicMock()
        fake_url.path.return_value = "/Applications/Google Chrome.app"
        fake_app.bundleURL.return_value = fake_url

        fake_workspace = MagicMock()
        fake_workspace.frontmostApplication.return_value = fake_app

        NSWorkspace = MagicMock()
        NSWorkspace.sharedWorkspace.return_value = fake_workspace

        fake_appkit = types.SimpleNamespace(NSWorkspace=NSWorkspace)
        with patch.dict(sys.modules, {"AppKit": fake_appkit}):
            from core.source_app.macos import MacOSSourceAppProvider
            provider = MacOSSourceAppProvider()
            self.assertTrue(provider.is_available)
            app = provider.get_current()
            self.assertEqual(app.app_name, "Google Chrome")
            self.assertEqual(app.bundle_id, "com.google.Chrome")
            self.assertEqual(app.exe_path, "/Applications/Google Chrome.app")
            self.assertEqual(app.window_title, "")

    def test_unavailable_returns_empty(self):
        with patch.dict(sys.modules, {"AppKit": None}):
            from core.source_app.macos import MacOSSourceAppProvider
            provider = MacOSSourceAppProvider()
            if not provider.is_available:
                self.assertTrue(provider.get_current().is_empty)

    def test_no_frontmost_returns_empty(self):
        fake_workspace = MagicMock()
        fake_workspace.frontmostApplication.return_value = None
        NSWorkspace = MagicMock()
        NSWorkspace.sharedWorkspace.return_value = fake_workspace
        fake_appkit = types.SimpleNamespace(NSWorkspace=NSWorkspace)
        with patch.dict(sys.modules, {"AppKit": fake_appkit}):
            from core.source_app.macos import MacOSSourceAppProvider
            provider = MacOSSourceAppProvider()
            self.assertTrue(provider.is_available)
            app = provider.get_current()
            self.assertTrue(app.is_empty)


# ---------------------------------------------------------------------------
# Linux X11 provider
# ---------------------------------------------------------------------------


class TestX11Provider(unittest.TestCase):
    def _make_xlib(self, window_id=0x1000001, wm_class=b"chrome\x00Chrome\x00",
                   title=b"Tab Title", pid=4242):
        Xlib = MagicMock()
        X = types.SimpleNamespace(AnyPropertyType=0)
        Xlib.X = X

        # root.get_full_property(_NET_ACTIVE_WINDOW, ...) -> prop.value = [window_id]
        root = MagicMock()
        root_prop = MagicMock()
        root_prop.value = [window_id]
        root.get_full_property.return_value = root_prop

        screen = MagicMock()
        screen.root = root

        display_instance = MagicMock()
        display_instance.screen.return_value = screen
        display_instance.intern_atom.side_effect = lambda name: name  # 用 name 当 atom

        # win.get_full_property 按 atom 返回不同内容
        win = MagicMock()

        def _get_full_property(atom, _type):
            prop = MagicMock()
            if atom == "WM_CLASS":
                prop.value = wm_class
            elif atom in ("_NET_WM_NAME", "WM_NAME"):
                prop.value = title
            elif atom == "_NET_WM_PID":
                prop.value = [pid]
            else:
                return None
            return prop

        win.get_full_property.side_effect = _get_full_property
        display_instance.create_resource_object.return_value = win

        display_module = MagicMock()
        display_module.Display.return_value = display_instance
        Xlib.display = display_module

        return Xlib, X, display_instance

    def test_get_current(self):
        Xlib, X, _disp = self._make_xlib()
        with patch.dict("os.environ", {"DISPLAY": ":0"}, clear=False):
            with patch.dict(sys.modules, {
                "Xlib": Xlib,
                "Xlib.display": Xlib.display,
                "Xlib.X": types.SimpleNamespace(**X.__dict__) if hasattr(X, "__dict__") else X,
            }):
                # from Xlib import X 会找 Xlib.X
                sys.modules["Xlib"].X = X
                with patch("os.readlink", return_value="/usr/bin/chrome"):
                    from core.source_app.linux_x11 import X11SourceAppProvider
                    provider = X11SourceAppProvider()
                    self.assertTrue(provider.is_available)
                    app = provider.get_current()
                    self.assertEqual(app.app_name, "Chrome")
                    self.assertEqual(app.bundle_id, "chrome")
                    self.assertEqual(app.exe_path, "/usr/bin/chrome")
                    self.assertEqual(app.window_title, "Tab Title")

    def test_unavailable_no_display(self):
        import os as _os
        saved = _os.environ.pop("DISPLAY", None)
        try:
            from core.source_app.linux_x11 import X11SourceAppProvider
            provider = X11SourceAppProvider()
            self.assertFalse(provider.is_available)
            self.assertTrue(provider.get_current().is_empty)
        finally:
            if saved is not None:
                _os.environ["DISPLAY"] = saved


# ---------------------------------------------------------------------------
# Linux Wayland provider
# ---------------------------------------------------------------------------


class TestWaylandProvider(unittest.TestCase):
    def _install_fake_jeepney(self):
        jeepney = MagicMock()
        DBusAddress = MagicMock()
        new_method_call = MagicMock()
        open_dbus_connection = MagicMock()

        # jeepney.io.blocking.open_dbus_connection
        io_mod = types.SimpleNamespace(blocking=types.SimpleNamespace(
            open_dbus_connection=open_dbus_connection))
        sys.modules["jeepney"] = jeepney
        sys.modules["jeepney.io"] = io_mod
        sys.modules["jeepney.io.blocking"] = io_mod.blocking
        jeepney.DBusAddress = DBusAddress
        jeepney.new_method_call = new_method_call
        return jeepney, DBusAddress, new_method_call, open_dbus_connection

    def test_unavailable_without_wayland_display(self):
        import os as _os
        saved = _os.environ.pop("WAYLAND_DISPLAY", None)
        try:
            from core.source_app.linux_wayland import WaylandSourceAppProvider
            provider = WaylandSourceAppProvider()
            self.assertFalse(provider.is_available)
            self.assertTrue(provider.get_current().is_empty)
        finally:
            if saved is not None:
                _os.environ["WAYLAND_DISPLAY"] = saved

    def test_fallback_when_both_dbus_fail(self):
        with patch.dict("os.environ",
                        {"WAYLAND_DISPLAY": "wayland-0", "XDG_CURRENT_DESKTOP": "GNOME"},
                        clear=False):
            _, _, _, open_conn = self._install_fake_jeepney()
            conn = MagicMock()
            conn.send_and_get_reply.side_effect = RuntimeError("no such service")
            open_conn.return_value = conn

            from core.source_app.linux_wayland import WaylandSourceAppProvider
            provider = WaylandSourceAppProvider()
            self.assertTrue(provider.is_available)
            app = provider.get_current()
            self.assertEqual(app.app_name, "Wayland")
            self.assertEqual(app.bundle_id, "gnome")

    def test_gnome_eval_success(self):
        with patch.dict("os.environ",
                        {"WAYLAND_DISPLAY": "wayland-0", "XDG_CURRENT_DESKTOP": "GNOME"},
                        clear=False):
            _, _, _, open_conn = self._install_fake_jeepney()
            # 第一次调用（GNOME）返回成功
            reply = MagicMock()
            reply.body = (True, "firefox\nMozilla Firefox")
            conn = MagicMock()
            conn.send_and_get_reply.return_value = reply
            open_conn.return_value = conn

            from core.source_app.linux_wayland import WaylandSourceAppProvider
            provider = WaylandSourceAppProvider()
            app = provider.get_current()
            self.assertEqual(app.app_name, "firefox")
            self.assertEqual(app.bundle_id, "firefox")
            self.assertEqual(app.window_title, "Mozilla Firefox")


if __name__ == "__main__":
    unittest.main()

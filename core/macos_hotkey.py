"""macOS 全局热键：用 NSEvent global+local monitor 替代 pynput.GlobalHotKeys。

Why
----
pynput 1.8.x 用 CGEventTap 在后台线程接收键盘事件，回调里调用
``+[NSEvent eventWithCGEvent:]`` 把 CGEvent 转 NSEvent。在 macOS 26 (Tahoe) 上，
当用户按下涉及 CapsLock 状态切换的键时（CapsLock 本身、或长按某些字母触发
TSM 输入法切换的场景），转换路径会走到 ``TSMCreateInputSourceForRomanSwitchAction``，
这个函数里有 ``dispatch_assert_queue`` 断言要求在 dispatch_main 队列上调用，
非主线程触发就直接 ``_dispatch_assert_queue_fail`` → SIGTRAP（Trace/BPT trap: 5），
整个 Python 进程被杀掉。

``NSEvent.addGlobalMonitorForEventsMatchingMask:handler:`` 的 handler 在主 run loop
上被回调，不走 CGEventTap，从根本上避开了上面那条崩溃链路。

权限和能力
----------
- 需要 macOS 的「输入监控」权限（和 pynput 一样）。
- 是只读监听，无法拦截事件。对"全局热键唤出窗口"够用。
- 全局 monitor 看到的是发到 **其他 app** 的事件；本 app 处于前台时按热键走 local。
  所以两边都装才能覆盖所有情形。
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Optional, Tuple

logger = logging.getLogger(__name__)


# AppKit NSEvent modifier flag 位（CGEventFlags 同位）。
# 文档：https://developer.apple.com/documentation/appkit/nseventmodifierflags
_NS_SHIFT = 1 << 17
_NS_CTRL = 1 << 18
_NS_ALT = 1 << 19  # Option
_NS_CMD = 1 << 20

# 关心的位掩码，比较时屏蔽掉 CapsLock / NumericPad / Function 等噪声位
_MOD_RELEVANT_MASK = _NS_SHIFT | _NS_CTRL | _NS_ALT | _NS_CMD

# pynput 风格的 token → NSEvent 修饰键位
_MOD_MAP = {
    "cmd": _NS_CMD,
    "command": _NS_CMD,
    "super": _NS_CMD,
    "win": _NS_CMD,
    "ctrl": _NS_CTRL,
    "control": _NS_CTRL,
    "shift": _NS_SHIFT,
    "alt": _NS_ALT,
    "option": _NS_ALT,
    "opt": _NS_ALT,
}

# 一些特殊字符键的字面值（charactersIgnoringModifiers 返回值）
_SPECIAL_CHARS = {
    "space": " ",
    "tab": "\t",
    "enter": "\r",
    "return": "\r",
    "esc": "\x1b",
    "escape": "\x1b",
    "backspace": "\x7f",
    "delete": "\x7f",
}


def _parse_hotkey(spec: str) -> Tuple[int, str]:
    """把 ``<cmd>+<shift>+v`` 这种 pynput 风格的串解析成 ``(mask, char_lower)``。

    支持的 token：``<cmd>``/``<shift>``/``<ctrl>``/``<alt>`` 或不带尖括号的同名。
    剩余的非修饰 token 视为目标键，统一转小写。
    """
    pairs = re.findall(r"<([^>]+)>|([^+<>\s]+)", spec)
    mask = 0
    key: Optional[str] = None
    for tag, plain in pairs:
        token = (tag or plain).strip().lower()
        if not token:
            continue
        if token in _MOD_MAP:
            mask |= _MOD_MAP[token]
            continue
        if key is not None:
            raise ValueError(f"hotkey {spec!r} 出现多个非修饰键: {key!r} 与 {token!r}")
        key = _SPECIAL_CHARS.get(token, token)
    if key is None:
        raise ValueError(f"hotkey {spec!r} 没有非修饰键")
    return mask, key


class MacOSGlobalHotkey:
    """单热键版本：注册时给一个 hotkey 字符串和回调。

    线程：handler 在主线程上同步回调；如果回调可能耗时（例如点亮窗口动画），
    建议在内部用 ``QMetaObject.invokeMethod(..., Qt.QueuedConnection)`` 投递到事件循环。
    """

    def __init__(self, spec: str, callback: Callable[[], None]):
        self._mask, self._key = _parse_hotkey(spec)
        self._callback = callback
        self._global_monitor = None
        self._local_monitor = None
        # 给 main.py 的健康检查用：和 pynput Listener 的 running 字段语义对齐
        self.running: bool = False

    # NSEvent local monitor handler 必须返回 NSEvent（或 None 吃掉），
    # global monitor 不关心返回值。两个 handler 共享比较逻辑。
    def _matches(self, event) -> bool:
        try:
            if (event.modifierFlags() & _MOD_RELEVANT_MASK) != self._mask:
                return False
            chars = event.charactersIgnoringModifiers()
            return bool(chars) and chars.lower() == self._key
        except Exception:
            logger.debug("hotkey 比对异常", exc_info=True)
            return False

    def _on_match(self):
        try:
            self._callback()
        except Exception:
            logger.exception("hotkey 回调异常")

    def start(self) -> bool:
        if self.running:
            return True
        try:
            from AppKit import NSEvent, NSEventMaskKeyDown
        except ImportError:
            logger.error("AppKit 不可用（pyobjc-framework-Cocoa 未装），无法注册全局热键")
            return False

        def global_handler(event):
            if self._matches(event):
                self._on_match()

        def local_handler(event):
            # local monitor 必须把 event 原样返回，否则按键会被吞掉影响其他控件
            if self._matches(event):
                self._on_match()
            return event

        self._global_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown, global_handler
        )
        self._local_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown, local_handler
        )
        # macOS 在缺「输入监控」权限时 addGlobalMonitor 返回 None，但不抛异常。
        # 这里把 global 没拿到当作"未真正生效"的信号，让上层走权限引导。
        self.running = self._global_monitor is not None
        return self.running

    def stop(self) -> None:
        try:
            from AppKit import NSEvent
        except ImportError:
            return
        for m in (self._global_monitor, self._local_monitor):
            if m is not None:
                try:
                    NSEvent.removeMonitor_(m)
                except Exception:
                    logger.debug("移除 NSEvent monitor 失败", exc_info=True)
        self._global_monitor = None
        self._local_monitor = None
        self.running = False

    # 兼容 pynput.Listener 接口（main.py 里有 is_alive 检测）
    def is_alive(self) -> bool:
        return self.running

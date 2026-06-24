"""pytest 全局配置。

唯一职责：规避 PySide6 worker QThread 在解释器关闭阶段触发的 abort。

core.cloud_sync_service / core.file_sync_service 各自持有一个 worker QThread
（`self._worker_thread = QThread(self)`）。测试用例创建这些 service 后，worker
线程可能在用例结束时仍 isRunning()；而对象 __del__ 里的兜底停止并不可靠——解释器
退出阶段 Python 不保证调用 __del__。于是进程在「所有测试已 PASSED」之后、解释器
关闭执行 ~QThread 时，Qt 抛出
    qFatal("QThread: Destroyed while thread is still running")
直接 abort（SIGABRT，退出码 134），导致 CI 的 mac / linux job 在测试全部通过的
情况下仍被判定失败（Windows 不 abort，所以此前只有它能通过）。

到 pytest_sessionfinish 时测试结论已经确定，这里直接以「真实退出码」结束进程，
跳过后续 Qt 析构链：既不再触发 abort，也保留对测试失败的检测（exitstatus 非 0
仍以非 0 退出）。
"""

import os
import sys

import pytest


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    sys.stdout.flush()
    sys.stderr.flush()
    # 留痕：CI/本地日志可据此确认是本 hook 接管了退出，而非自然退出或 abort。
    os.write(2, b"[conftest] sessionfinish: exiting to skip Qt QThread teardown abort\n")
    # exitstatus 为 pytest 的 ExitCode：0 表示全部通过，其余一律视为失败。
    os._exit(0 if int(exitstatus) == 0 else 1)

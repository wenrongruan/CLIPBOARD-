"""PluginActionController 构造 smoke test。"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sys
from pathlib import Path

import pytest
from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication, QWidget

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ui.controllers.plugin_action_controller import PluginActionController


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_controller_constructs(qapp):
    parent = QWidget()
    ctx = MagicMock()
    c = PluginActionController(parent, ctx)
    assert c is not None
    parent.close()
    parent.deleteLater()

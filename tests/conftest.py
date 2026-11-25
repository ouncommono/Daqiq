"""Global pytest safeguards for headless Qt runs (Trap 7 fail-fast modal guard)."""

from __future__ import annotations

import faulthandler
import os

import pytest


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PYTHONFAULTHANDLER", "1")

try:
    faulthandler.enable()
except Exception:
    pass


def _fail_fast_exec(self, *args, **kwargs):
    title = ""
    if hasattr(self, "windowTitle"):
        try:
            title = self.windowTitle() or ""
        except Exception:
            title = ""
    raise AssertionError(
        f"Unexpected blocking modal .exec() call on {type(self).__name__}"
        + (f" ({title!r})" if title else "")
        + " in headless test run. Mock .exec() or QMessageBox helper explicitly."
    )


def _fail_fast_static_box(kind: str):
    def _blocker(*args, **kwargs):
        title = args[1] if len(args) > 1 else ""
        raise AssertionError(
            f"Unexpected blocking QMessageBox.{kind}({title!r}) call in headless test run. "
            "Patch QMessageBox in the test."
        )
    return _blocker


@pytest.fixture(autouse=True)
def _prevent_blocking_modal_exec(monkeypatch, request):
    """Fail fast instead of hanging if any test triggers an unmocked modal event loop."""
    if request.node.get_closest_marker("allow_modal_exec"):
        return

    from PySide6.QtWidgets import (
        QColorDialog,
        QDialog,
        QFileDialog,
        QFontDialog,
        QInputDialog,
        QMessageBox,
    )

    for cls in (QDialog, QMessageBox, QFileDialog, QInputDialog, QColorDialog, QFontDialog):
        monkeypatch.setattr(cls, "exec", _fail_fast_exec)
        if hasattr(cls, "exec_"):
            monkeypatch.setattr(cls, "exec_", _fail_fast_exec)

    for static_name in ("information", "warning", "critical", "question", "about"):
        if hasattr(QMessageBox, static_name):
            monkeypatch.setattr(QMessageBox, static_name, staticmethod(_fail_fast_static_box(static_name)))

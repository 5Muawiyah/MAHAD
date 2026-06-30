from __future__ import annotations

from decimal import Decimal
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from mahad.ui import theme
from mahad.ui.glass_dialog import GlassDialog


class ResetDialog(GlassDialog):

    reset_requested = Signal(object)            # {also_clear_log, export_succeeded}

    def __init__(self, starting_cash, export_succeeded: bool,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__("Reset portfolio?", warn=True, width=460, parent=parent)
        self._export_ok = bool(export_succeeded)
        start = f"{Decimal(starting_cash):,.2f}"
        b = self.body()

        msg = QLabel(
            f"This clears all open positions and returns cash to {start} USD. "
            "The trade log is retained. The value-history re-bases and the all-time "
            "peak re-seeds now - the risk panel returns to warming-up.")
        msg.setWordWrap(True)
        msg.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_2}; font-size: 13px; background: transparent; }}")
        b.addWidget(msg)

        rows = QVBoxLayout(); rows.setSpacing(theme.S2)
        self._row(rows, "Positions", "cleared")
        self._row(rows, "Cash", f"-> {start}")
        self._row(rows, "Trade log", "retained", good=True)
        b.addLayout(rows)

        box = QWidget(); box.setObjectName("ReadoutBox")
        bl = QHBoxLayout(box)
        bl.setContentsMargins(theme.S3, theme.S2, theme.S3, theme.S2)
        self._chk = QCheckBox("Also clear trade log")
        self._chk.setEnabled(self._export_ok)
        self._chk.setStyleSheet(
            f"QCheckBox {{ color: {theme.TEXT_2}; font-size: 13px; }}"
            f"QCheckBox:disabled {{ color: {theme.TEXT_3}; }}"
            f"QCheckBox::indicator {{ width: 15px; height: 15px;"
            f" border: 1px solid {theme.DIVIDER}; border-radius: 4px;"
            f" background: {theme.NESTED}; }}"
            f"QCheckBox::indicator:checked {{ background: {theme.ACCENT};"
            f" border: 1px solid {theme.ACCENT}; }}"
            f"QCheckBox::indicator:disabled {{ border: 1px solid {theme.HAIRLINE};"
            f" background: transparent; }}")
        bl.addWidget(self._chk)
        bl.addStretch(1)
        if not self._export_ok:
            warn = QLabel("Export the log before clearing")
            warn.setObjectName("InlineWarn")
            bl.addWidget(warn)
        b.addWidget(box)

        foot = QHBoxLayout()
        foot.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setProperty("variant", "ghost")
        cancel.clicked.connect(self.reject)
        self._confirm = QPushButton("Reset portfolio")
        self._confirm.setProperty("variant", "danger")
        self._confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        self._confirm.clicked.connect(self._on_reset)
        cancel.setDefault(True)                            # Enter must NOT wipe the portfolio
        cancel.setAutoDefault(True)
        self._confirm.setAutoDefault(False)
        foot.addWidget(cancel)
        foot.addWidget(self._confirm)
        self.add_footer(foot)

    def _row(self, parent: QVBoxLayout, label: str, value: str, good: bool = False) -> None:
        row = QHBoxLayout()
        lab = QLabel(label)
        lab.setStyleSheet(f"QLabel {{ color: {theme.TEXT_3}; font-size: 13px; background: transparent; }}")
        val = QLabel(value)
        colour = theme.GREEN if good else theme.TEXT_1
        val.setStyleSheet(
            f"QLabel {{ font-family: {theme.FONT_MONO}; color: {colour};"
            f" font-size: 13px; background: transparent; }}")
        row.addWidget(lab)
        row.addStretch(1)
        row.addWidget(val)
        parent.addLayout(row)

    def _on_reset(self) -> None:
        if getattr(self, "_submitted", False):             # single-flight
            return
        self._submitted = True
        self._confirm.setEnabled(False)
        self.reset_requested.emit({
            "also_clear_log": bool(self._chk.isChecked() and self._export_ok),
            "export_succeeded": self._export_ok})
        self.accept()

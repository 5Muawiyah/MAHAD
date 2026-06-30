from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QWidget

from mahad import config
from mahad.ui import theme
from mahad.ui.glass_dialog import GlassDialog
from mahad.ui.widgets import SegmentedControl


class SettingsDialog(GlassDialog):
    risk_timeframe_changed = Signal(str)

    def __init__(self, risk_timeframe: str = "1d",
                 parent: Optional[QWidget] = None) -> None:
        super().__init__("Settings", width=540, parent=parent)  # footer width
        self._initial = risk_timeframe if risk_timeframe in config.VALID_RISK_TIMEFRAMES else "1d"
        self._picked = self._initial
        b = self.body()

        b.addWidget(self.field_label("RISK TIMEFRAME"))
        sub = QLabel("Value-history sampling cadence. Use 1m or 1h to accrue volatility "
                     "and drawdown quickly (1d is the default).")
        sub.setWordWrap(True)
        sub.setStyleSheet(f"QLabel {{ color: {theme.TEXT_2}; font-size: 12px;"
                          f" background: transparent; }}")
        b.addWidget(sub)
        seg_row = QHBoxLayout()
        self._seg = SegmentedControl(["1m", "1h", "1d"], self._initial)
        self._seg.changed.connect(self._on_pick)
        seg_row.addWidget(self._seg)
        seg_row.addStretch(1)
        b.addLayout(seg_row)

        warn = QLabel("Changing the risk timeframe re-bases the value-history and "
                      "re-seeds the all-time peak. The risk panel returns to warming-up.")
        warn.setWordWrap(True)
        warn.setContentsMargins(theme.S3, theme.S2, theme.S3, theme.S2)
        warn.setStyleSheet(
            f"QLabel {{ color: {theme.AMBER}; background: {theme.AMBER_SOFT};"
            f" border: 1px solid rgba(217,165,33,0.28); border-radius: {theme.R_ATOM}px;"
            f" font-size: 11.5px; }}")
        b.addWidget(warn)

        defaults = QLabel(
            f"Other settings use committed defaults: poll {int(config.POLL_INTERVAL_S)}s "
            f"· timeframe {config.DEFAULT_TIMEFRAME} · SMA {config.SMA_PERIOD} / "
            f"EMA {config.EMA_PERIOD} / RSI {config.RSI_PERIOD} · base currency USD "
            f"(fixed) · volatility window {config.VOLATILITY_WINDOW}.")
        defaults.setWordWrap(True)
        defaults.setStyleSheet(f"QLabel {{ color: {theme.TEXT_3}; font-family: {theme.FONT_MONO};"
                               f" font-size: 11px; background: transparent; }}")
        b.addWidget(defaults)

        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"QFrame {{ background: {theme.HAIRLINE}; }}")
        b.addWidget(rule)
        self._reset_clicked = False
        reset_btn = QPushButton("Reset portfolio...")
        reset_btn.setObjectName("DangerGhost")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.setStyleSheet(
            f"QPushButton#DangerGhost {{ color: {theme.RED}; background: transparent;"
            f" border: 1px solid {theme.RED_SOFT}; border-radius: {theme.R_ATOM}px;"
            f" padding: 7px 14px; font-size: 13px; font-weight: 500; }}"
            f"QPushButton#DangerGhost:hover {{ background: {theme.RED_SOFT};"
            f" border-color: rgba(248,81,73,0.45); }}")
        reset_btn.clicked.connect(self._request_reset)
        b.addWidget(reset_btn, 0, Qt.AlignmentFlag.AlignLeft)

        footer = QHBoxLayout()
        footer.addStretch(1)
        restore = QPushButton("Restore defaults")
        restore.setProperty("variant", "ghost")
        restore.setCursor(Qt.CursorShape.PointingHandCursor)
        restore.clicked.connect(self._restore)
        cancel = QPushButton("Cancel")
        cancel.setProperty("variant", "ghost")
        cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel.clicked.connect(self.reject)
        # only filled button in the dialog
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setProperty("variant", "primary")
        self._apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_btn.clicked.connect(self._apply)
        footer.addWidget(restore)
        footer.addWidget(cancel)
        footer.addWidget(self._apply_btn)
        self.add_footer(footer)

    def _request_reset(self) -> None:
        # set the flag and close; the window pops the reset-confirm afterwards
        self._reset_clicked = True
        self.accept()

    def _on_pick(self, tf: str) -> None:
        self._picked = tf

    def _restore(self) -> None:
        self._seg.set_active(config.RISK_TIMEFRAME)
        self._picked = config.RISK_TIMEFRAME

    def _apply(self) -> None:
        if getattr(self, "_applied", False):               # single-flight
            return
        self._applied = True
        self._apply_btn.setEnabled(False)
        if self._picked != self._initial:
            self.risk_timeframe_changed.emit(self._picked)
        self.accept()

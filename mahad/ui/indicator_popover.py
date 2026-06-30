from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer, Signal, Slot
from PySide6.QtGui import QPainterPath, QRegion
from PySide6.QtWidgets import (QAbstractSpinBox, QFrame, QHBoxLayout, QLabel,
                               QSpinBox, QVBoxLayout, QWidget)

from mahad.config import EMA_PERIOD, RSI_PERIOD, SMA_PERIOD
from mahad.engine.indicators import (EMA, MAX_PERIOD, MIN_PERIOD, RSI, SMA,
                                     IndicatorSettings)
from mahad.engine.snapshot import RenderSnapshot
from mahad.ui import theme
from mahad.ui.widgets import ToggleSwitch


class IndicatorPopover(QFrame):
    # anchored under the Indicators toolbar button

    settings_changed = Signal(object)            # IndicatorSettings
    _DEBOUNCE_MS = 120                           # coalesce a burst of toggles/edits

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setFixedWidth(320)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("GlassSoftCard")
        # near-opaque so rows stay legible over the chart
        card.setStyleSheet(
            f"#GlassSoftCard {{ background: {theme.POPOVER_FILL};"
            f" border: 1px solid {theme.HAIRLINE}; border-top: 1px solid {theme.RIM_SOFT};"
            f" border-radius: {theme.R_CARD}px; }}")
        outer.addWidget(card)

        root = QVBoxLayout(card)
        root.setContentsMargins(theme.S5, theme.S4, theme.S5, theme.S4)
        root.setSpacing(theme.S2)

        head = QHBoxLayout()
        title = QLabel("Indicators")
        title.setObjectName("PanelTitle")
        head.addWidget(title)
        head.addStretch(1)
        root.addLayout(head)

        self._toggles: dict[str, ToggleSwitch] = {}
        self._spins: dict[str, QSpinBox] = {}
        self._notes: dict[str, QLabel] = {}
        self._names: dict[str, QLabel] = {}
        self._pending_settings: IndicatorSettings | None = None   # debounce
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.timeout.connect(self._flush_settings)

        root.addWidget(self._make_row(SMA, "SMA", theme.SMA_COLOR, SMA_PERIOD))
        root.addWidget(self._make_row(EMA, "EMA", theme.EMA_COLOR, EMA_PERIOD))
        root.addWidget(self._make_row(RSI, "RSI", theme.RSI_COLOR, RSI_PERIOD))

        self._hint = QLabel("Toggle an indicator to overlay it")
        self._hint.setProperty("tier", "3")
        self._hint.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_3}; font-size: 12px; padding-top: {theme.S2}px; }}")
        root.addWidget(self._hint)

    # -- rounded-corner mask -------------------------------------- #
    def _apply_rounded_mask(self) -> None:
        # mask to a rounded rect so the corners read as transparent
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), theme.R_CARD, theme.R_CARD)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        self._apply_rounded_mask()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._apply_rounded_mask()

    def _make_row(self, kind: str, name: str, color, default_period: int) -> QWidget:
        row = QWidget()
        outer = QVBoxLayout(row)
        outer.setContentsMargins(0, theme.S2, 0, theme.S2)
        outer.setSpacing(theme.S2)

        line = QHBoxLayout()
        line.setSpacing(theme.S3)
        toggle = ToggleSwitch()
        toggle.toggled.connect(self._emit)
        self._toggles[kind] = toggle
        line.addWidget(toggle)

        if color is not None:
            swatch = QFrame()
            swatch.setFixedSize(10, 10)
            swatch.setStyleSheet(
                f"QFrame {{ background: {color}; border-radius: 3px; }}")
            line.addWidget(swatch)
        else:
            spacer = QFrame()                             # keep the swatch column aligned
            spacer.setFixedSize(10, 10)
            spacer.setStyleSheet("QFrame { background: transparent; }")
            line.addWidget(spacer)

        label = QLabel(name)
        label.setStyleSheet(
            f"QLabel {{ font-size: 13px; font-weight: 500; color: {theme.TEXT_2}; }}")
        self._names[kind] = label
        line.addWidget(label)
        line.addStretch(1)

        spin = QSpinBox()
        spin.setRange(MIN_PERIOD, MAX_PERIOD)
        spin.setValue(default_period)
        spin.setKeyboardTracking(False)               # emit on commit, not per keystroke
        spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        spin.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        spin.valueChanged.connect(self._emit)
        self._spins[kind] = spin
        line.addWidget(spin)
        outer.addLayout(line)

        note = QLabel("")
        note.setStyleSheet(
            f"QLabel {{ color: {theme.AMBER}; font-family: {theme.FONT_MONO};"
            f" font-size: 11px; padding-left: 50px; }}")
        note.hide()
        self._notes[kind] = note
        outer.addWidget(note)

        # transparent so the frosted card shows through
        row.setObjectName("IndRow")
        row.setStyleSheet("QWidget#IndRow { background: transparent; }")
        return row

    # -- state in/out -------------------------------------------------------- #
    def current_settings(self) -> IndicatorSettings:
        return IndicatorSettings(
            sma_enabled=self._toggles[SMA].isChecked(), sma_period=self._spins[SMA].value(),
            ema_enabled=self._toggles[EMA].isChecked(), ema_period=self._spins[EMA].value(),
            rsi_enabled=self._toggles[RSI].isChecked(), rsi_period=self._spins[RSI].value(),
        )

    def _emit(self, *_args) -> None:
        s = self.current_settings()
        self._refresh_name_colours(s)
        self._hint.setVisible(not (s.sma_enabled or s.ema_enabled or s.rsi_enabled))
        self._pending_settings = s
        self._debounce.start(self._DEBOUNCE_MS)

    def _flush_settings(self) -> None:
        if self._pending_settings is not None:
            self.settings_changed.emit(self._pending_settings)
            self._pending_settings = None

    def _refresh_name_colours(self, s: IndicatorSettings) -> None:
        for kind, on in ((SMA, s.sma_enabled), (EMA, s.ema_enabled), (RSI, s.rsi_enabled)):
            colour = theme.TEXT_1 if on else theme.TEXT_2
            self._names[kind].setStyleSheet(
                f"QLabel {{ font-size: 13px; font-weight: 500; color: {colour}; }}")

    @Slot(object)
    def set_settings(self, settings: object) -> None:
        # load persisted state without echoing a change back to the worker
        if not isinstance(settings, IndicatorSettings):
            return
        pairs = ((SMA, settings.sma_enabled, settings.sma_period),
                 (EMA, settings.ema_enabled, settings.ema_period),
                 (RSI, settings.rsi_enabled, settings.rsi_period))
        for kind, enabled, period in pairs:
            self._toggles[kind].blockSignals(True)
            self._spins[kind].blockSignals(True)
            self._toggles[kind].setChecked(enabled)
            self._spins[kind].setValue(period)
            self._toggles[kind].blockSignals(False)
            self._spins[kind].blockSignals(False)
        self._refresh_name_colours(settings)
        self._hint.setVisible(
            not (settings.sma_enabled or settings.ema_enabled or settings.rsi_enabled))

    @Slot(object)
    def sync_warnings(self, snap: RenderSnapshot) -> None:
        # warn on rows whose period needs more bars than the history has
        for kind, line in ((SMA, snap.sma), (EMA, snap.ema), (RSI, snap.rsi)):
            note = self._notes[kind]
            if line is not None and line.needs_more > 0:
                note.setText(f"needs {line.needs_more} more bars")
                note.show()
            else:
                note.hide()

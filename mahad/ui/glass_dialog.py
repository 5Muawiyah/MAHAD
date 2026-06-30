from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from mahad.ui import theme


class GlassDialog(QDialog):

    def __init__(self, title: str, icon: str = "", warn: bool = False,
                 width: int = 460, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)
        # translucent so only the inner frame paints
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._drag = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self._card = QFrame()
        self._card.setObjectName("GlassDialog")    # object name keys the QSS chrome
        self._card.setMinimumWidth(width)
        outer.addWidget(self._card)

        self._root = QVBoxLayout(self._card)
        self._root.setContentsMargins(theme.S6, theme.S5, theme.S6, theme.S5)
        self._root.setSpacing(theme.S4)

        del icon  # accepted for call-site compatibility, never drawn
        head = QHBoxLayout()
        head.setSpacing(theme.S3)
        self._title = QLabel(title)
        self._title.setObjectName("DialogTitleWarn" if warn else "DialogTitle")
        head.addWidget(self._title)
        head.addStretch(1)
        close = QPushButton("✕")
        close.setObjectName("DialogClose")
        close.setAutoDefault(False)                 # keep Enter off the X
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # avoids a focus ring on open
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.reject)
        head.addWidget(close)
        self._root.addLayout(head)

        self._body = QVBoxLayout()
        self._body.setContentsMargins(0, 0, 0, 0)
        self._body.setSpacing(theme.S3)
        self._root.addLayout(self._body)

    # -- subclass hooks ------------------------------------------------------ #
    def body(self) -> QVBoxLayout:
        return self._body

    def add_footer(self, footer: QHBoxLayout) -> None:
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"QFrame {{ background: {theme.HAIRLINE}; }}")
        self._root.addSpacing(theme.S2)
        self._root.addWidget(sep)
        self._root.addLayout(footer)

    def field_label(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("FieldLabel")
        return lab

    # -- draggable by the header (frameless) --------------------------------- #
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 56:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag)
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._drag = None
        super().mouseReleaseEvent(e)

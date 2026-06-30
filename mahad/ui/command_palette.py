from __future__ import annotations

from typing import Callable, Optional, Sequence

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QLineEdit, QListWidget, QListWidgetItem,
                               QStyledItemDelegate, QWidget)

from mahad.ui import theme
from mahad.ui.glass_dialog import GlassDialog

Command = tuple[str, str, Callable[[], None]]   # (label, shortcut hint, handler)
_HINT_ROLE = Qt.ItemDataRole.UserRole


class _HintDelegate(QStyledItemDelegate):

    def paint(self, painter, option, index) -> None:
        super().paint(painter, option, index)         # draws background and label
        shortcut = index.data(_HINT_ROLE)
        if not shortcut:
            return
        painter.save()
        painter.setFont(option.font)
        painter.setPen(theme._qcolor(theme.TEXT_3))
        rect = option.rect.adjusted(0, 0, -14, 0)
        painter.drawText(rect, int(Qt.AlignmentFlag.AlignRight
                                   | Qt.AlignmentFlag.AlignVCenter), shortcut)
        painter.restore()


class CommandPalette(GlassDialog):

    def __init__(self, commands: Sequence[Command],
                 parent: Optional[QWidget] = None) -> None:
        super().__init__("Command palette", width=520, parent=parent)
        self._commands: list[Command] = list(commands)
        self._filtered: list[Callable[[], None]] = []
        self.chosen: Optional[Callable[[], None]] = None

        b = self.body()
        self._search = QLineEdit()
        self._search.setObjectName("CmdSearch")
        self._search.setPlaceholderText("Type to filter commands ...")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._refilter)
        b.addWidget(self._search)

        self._list = QListWidget()
        self._list.setObjectName("CmdList")
        self._list.setUniformItemSizes(True)
        self._list.setMinimumHeight(320)
        self._list.setItemDelegate(_HintDelegate(self._list))
        self._list.itemActivated.connect(lambda _i: self._run_current())
        b.addWidget(self._list)

        self._refilter("")
        self._search.installEventFilter(self)   # route keys to the list
        self._search.setFocus()

    def _refilter(self, text: str) -> None:
        q = (text or "").strip().lower()
        self._list.clear()
        self._filtered = []
        for label, shortcut, handler in self._commands:
            if q and q not in label.lower():
                continue
            item = QListWidgetItem(label)
            item.setData(_HINT_ROLE, shortcut)
            item.setToolTip(f"{label}  ({shortcut})" if shortcut else label)
            self._list.addItem(item)
            self._filtered.append(handler)
        if self._list.count():
            self._list.setCurrentRow(0)
        else:
            empty = QListWidgetItem("No commands match")
            empty.setFlags(Qt.ItemFlag.NoItemFlags)    # placeholder, must not be selectable
            self._list.addItem(empty)

    def _run_current(self) -> None:
        row = self._list.currentRow()
        if 0 <= row < len(self._filtered):
            self.chosen = self._filtered[row]
            self.accept()

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        if obj is self._search and ev.type() == QEvent.Type.KeyPress:
            key = ev.key()
            if key in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self._list.count():
                row = self._list.currentRow()
                step = 1 if key == Qt.Key.Key_Down else -1
                self._list.setCurrentRow((row + step) % self._list.count())
                return True
            if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._run_current()
                return True
        return super().eventFilter(obj, ev)

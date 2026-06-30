from __future__ import annotations

import logging
import re
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from mahad import config
from mahad.ui import theme
from mahad.ui.main_window import MainWindow


class _RedactQueryStrings(logging.Filter):
    # query strings can carry API keys; strip them before anything hits disk

    _pat = re.compile(r"(https?://[^\s'\"?]+)\?\S+")

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 (logging API)
        try:
            msg = record.getMessage()
            redacted = self._pat.sub(r"\1?REDACTED", msg)
            if redacted != msg:
                record.msg = redacted
                record.args = ()
        except Exception:  # nosec B110 - log filtering must never raise
            pass
        return True


def _setup_logging() -> None:
    try:
        logdir = config.data_dir()
        logdir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(logdir / "mahad.log", maxBytes=512_000,
                                      backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        handler.addFilter(_RedactQueryStrings())
        lg = logging.getLogger("mahad")
        lg.setLevel(logging.INFO)
        lg.addHandler(handler)
    except Exception:  # nosec B110 - logging must never block the launch
        pass


def _apply_app_icon(app: QApplication) -> None:
    try:
        ico = Path(__file__).resolve().parents[1] / "assets" / "mahad.ico"
        if ico.exists():
            icon = QIcon(str(ico))
            if not icon.isNull():
                app.setWindowIcon(icon)
    except Exception:  # nosec B110 - documented degrade boundary
        pass


def main() -> int:
    _setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("MAHAD")
    app.setApplicationDisplayName("MAHAD")
    theme.apply(app)
    _apply_app_icon(app)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

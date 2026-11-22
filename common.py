"""Video Downloader - costanti e utilità condivise."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QSettings

APP_NAME = "Video Downloader"
APP_VERSION = "1.0.1"
APP_AUTHOR = "Cesa028"
APP_URL = "https://github.com/Cesa028/video-downloader"
FROZEN = bool(getattr(sys, "frozen", False))
# Cartella dei file distribuiti con il programma (LICENSE.txt, licenses\): sorgenti = cartella del
# progetto, installato = accanto all'exe.
APP_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent
PROFILE = os.environ.get("VD_PROFILE", "VideoDownloader")
DATA_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "VideoDownloader" / \
    ("" if PROFILE == "VideoDownloader" else PROFILE)

NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

log = logging.getLogger("videodownloader")


def settings() -> QSettings:
    return QSettings("VideoDownloader", PROFILE)


def setup_logging():
    """Log su file in %APPDATA%\\VideoDownloader\\log.txt (dettagli tecnici, mai mostrati come traceback)."""
    if log.handlers:
        return
    log.setLevel(logging.INFO)
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        h = RotatingFileHandler(DATA_DIR / "log.txt", maxBytes=300_000, backupCount=1, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s"))
        log.addHandler(h)
    except OSError:
        log.addHandler(logging.NullHandler())


def open_path(path):
    if path and os.path.exists(path):
        os.startfile(os.path.abspath(path))


def reveal(path):
    """Mostra il file in Esplora risorse (o apre la cartella)."""
    from PySide6.QtCore import QUrl
    from PySide6.QtGui import QDesktopServices
    p = Path(path)
    if os.name == "nt" and p.exists():
        subprocess.Popen(["explorer", "/select,", os.path.normpath(str(p))], creationflags=NO_WINDOW)
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p.parent)))


def fmt_time(sec: float) -> str:
    sec = int(round(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_size(mb: float) -> str:
    if mb >= 1024:
        return f"{mb / 1024:.2f} GB".replace(".", ",")
    return (f"{mb:.1f} MB" if mb >= 1 else f"{mb * 1024:.0f} KB").replace(".", ",")


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    i = 1
    while (q := p.with_name(f"{p.stem} ({i}){p.suffix}")).exists():
        i += 1
    return q

"""
Video Downloader — scarica video (MP4) e audio (MP3, M4A, Opus, FLAC, WAV) da YouTube, TikTok, Instagram,
Facebook, X e centinaia di altri siti, con yt-dlp e ffmpeg.
Requisiti (solo per eseguire il sorgente): Python 3.10+, PySide6, yt-dlp, truststore, ffmpeg.
La versione installata include già tutto.

Moduli: common (costanti), theme (token e temi), icons (icone SVG), engine (yt-dlp, formati, thread),
widgets (componenti), dialogs (Informazioni, licenze, errori), ui (finestra principale).
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile
import traceback
from pathlib import Path

_missing = [m for m in ("PySide6", "yt_dlp", "truststore") if importlib.util.find_spec(m) is None]
if _missing:
    _msg = (f"Mancano dei moduli per questo Python:\n{sys.executable}\n\nInstallali con:\n"
            f"\"{sys.executable}\" -m pip install PySide6 yt-dlp truststore")
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, _msg, "Video Downloader", 0x10)
    print(_msg, file=sys.stderr)
    sys.exit(1)

from PySide6.QtWidgets import QApplication

import icons
from common import APP_NAME, APP_VERSION, log, setup_logging
from dialogs import ErrorDialog
from engine import find_ffmpeg
from ui import MainWindow, apply_theme, read_theme_pref


def _excepthook(exc_type, exc, tb):
    """Nessun traceback nudo all'utente: messaggio chiaro, dettaglio copiabile, log su file."""
    detail = "".join(traceback.format_exception(exc_type, exc, tb))
    log.error("Errore non gestito:\n%s", detail)
    try:
        ErrorDialog(QApplication.activeWindow(), "Qualcosa è andato storto",
                    "Si è verificato un errore imprevisto. Puoi continuare a usare il programma; "
                    "se il problema si ripete, copia i dettagli e inviali a chi mantiene l'app.", detail).exec()
    except Exception:  # noqa: BLE001
        print(detail, file=sys.stderr)


def selftest(url: str, out: Path) -> int:
    """Prova da riga di comando (`VideoDownloader.exe --selftest URL`): scarica video 720p + audio MP3 e scrive
    l'esito in selftest.txt nella cartella dei dati. Serve a verificare un'installazione."""
    from common import DATA_DIR
    import engine
    lines = [f"node: {engine.find_node()}", f"ffmpeg: {engine.find_ffmpeg()}"]
    try:
        info, _ = engine.fetch_info(url)
        lines.append(f"info: {info.title} {info.heights[:3]}")
        for mode in ("video", "audio"):
            job = engine.Job(info=info, mode=mode, height=720, acodec="mp3", bitrate="192", embed=True, out_dir=out)
            th = engine.DownloadThread(job)
            th.done.connect(lambda p: lines.append(f"ok: {p}"))
            th.failed.connect(lambda m, d: lines.append(f"ERRORE: {m} | {d[:200]}"))
            th.run()
    except Exception as e:  # noqa: BLE001
        lines.append(f"ERRORE: {e}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "selftest.txt").write_text("\n".join(lines), encoding="utf-8")
    return 0


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--selftest":
        setup_logging()
        return selftest(sys.argv[2], Path(sys.argv[3]) if len(sys.argv) > 3 else Path(tempfile.mkdtemp()))
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("VideoDownloader.App")
        except Exception:  # noqa: BLE001
            pass
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    app.setWindowIcon(icons.app_icon())
    tmp = Path(tempfile.mkdtemp(prefix="videodownloader_"))
    app.aboutToQuit.connect(lambda: shutil.rmtree(tmp, ignore_errors=True))
    apply_theme(app, read_theme_pref(), tmp / "ui")
    sys.excepthook = _excepthook
    log.info("Avvio %s %s", APP_NAME, APP_VERSION)
    if not find_ffmpeg():
        log.error("ffmpeg non trovato")
        ErrorDialog(None, "ffmpeg non trovato",
                    "Video Downloader ha bisogno di ffmpeg per unire video e audio e per convertire in MP3 e "
                    "altri formati, ma non l'ho trovato. Reinstalla il programma, oppure metti ffmpeg.exe nel "
                    "PATH, in C:\ffmpeg o accanto a questo programma.",
                    "Percorsi controllati:\n  accanto al programma\n  C:\ffmpeg\ffmpeg.exe\n"
                    "  C:\ffmpeg\bin\ffmpeg.exe\n  PATH di sistema").exec()
        return 1
    w = MainWindow(tmp)
    w.show()
    code = app.exec()
    # i thread di rete in corso non devono bloccare la chiusura
    os._exit(code)


if __name__ == "__main__":
    sys.exit(main())

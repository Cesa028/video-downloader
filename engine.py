"""Video Downloader - motore: analisi dei link e download con yt-dlp + ffmpeg (nessuna dipendenza da Qt qui,
tranne i thread di lavoro in fondo)."""
from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

import truststore
import yt_dlp
from yt_dlp.utils import DownloadCancelled

from PySide6.QtCore import QThread, Signal

from common import DATA_DIR, log

# usa i certificati di Windows (necessario con antivirus/proxy che ispezionano il traffico HTTPS)
truststore.inject_into_ssl()

URL_RE = re.compile(r"https?://[^\s<>\"']+", re.I)
VIDEO_QUALITIES = [None, 2160, 1440, 1080, 720, 480, 360, 240]      # None = la migliore disponibile
# etichetta, codec yt-dlp, estensione, supporta copertina incorporata
AUDIO_FORMATS = [("MP3", "mp3", "mp3", True), ("M4A (AAC)", "m4a", "m4a", True), ("Opus", "opus", "opus", True),
                 ("FLAC (senza perdita)", "flac", "flac", True), ("WAV (senza perdita)", "wav", "wav", False)]
AUDIO_BITRATES = ["320", "256", "192", "128"]
LOSSLESS = {"flac", "wav"}
BROWSERS = ["", "firefox", "edge", "chrome", "brave"]
SITES = ["YouTube", "TikTok", "Instagram", "Facebook", "X (Twitter)", "Vimeo", "Reddit", "Twitch", "SoundCloud",
         "Dailymotion", "Pinterest", "Bilibili"]


def extract_url(text: str) -> str | None:
    """Primo link http(s) trovato nel testo incollato."""
    m = URL_RE.search(text or "")
    return m.group(0).rstrip(".,;)") if m else None


def find_ffmpeg() -> str | None:
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for c in (here / exe, Path(sys.executable).parent / exe, Path(r"C:\ffmpeg\ffmpeg.exe"),
              Path(r"C:\ffmpeg\bin\ffmpeg.exe")):
        if c.is_file():
            return str(c)
    return shutil.which("ffmpeg")


def find_node() -> str | None:
    """Runtime JavaScript (Node) richiesto da YouTube per decifrare i link dei flussi video."""
    here = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    for c in (here / "node.exe", Path(sys.executable).parent / "node.exe"):
        if c.is_file():
            return str(c)
    return shutil.which("node")


def fmt_dur(sec) -> str:
    if not sec:
        return ""
    sec = int(sec)
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def friendly_error(text: str) -> str:
    """Messaggio comprensibile (italiano); il testo originale resta nel dettaglio."""
    t = text.lower()
    rules = [
        ("unsupported url", "Questo link non è supportato. Controlla che sia l'indirizzo di un video (non di una "
                            "pagina generica) di un sito supportato."),
        ("is not a valid url", "Questo non sembra un link valido."),
        ("sign in to confirm", "Il sito sospetta un accesso automatico. Riprova più tardi oppure, da Impostazioni, "
                               "usa i cookie del browser in cui hai fatto l'accesso."),
        ("private video", "Il video è privato: serve un account con i permessi per vederlo."),
        ("logged-in", "Per vedere questo contenuto serve il login. Da Impostazioni puoi usare i cookie del browser "
                      "in cui hai già fatto l'accesso."),
        ("requiring login", "Per vedere questo contenuto serve il login. Da Impostazioni puoi usare i cookie del "
                            "browser in cui hai già fatto l'accesso."),
        ("no video could be found", "In questo post non c'è nessun video da scaricare."),
        ("http error 404", "La pagina non esiste (errore 404): controlla il link."),
        ("login required", "Per vedere questo contenuto serve il login. Da Impostazioni puoi usare i cookie del "
                           "browser in cui hai già fatto l'accesso."),
        ("age-restricted", "Il video ha limiti di età: da Impostazioni usa i cookie del browser in cui hai fatto l'accesso."),
        ("confirm your age", "Il video ha limiti di età: da Impostazioni usa i cookie del browser in cui hai fatto l'accesso."),
        ("not available in your country", "Il video non è disponibile nel tuo Paese."),
        ("geo", "Il video non è disponibile nel tuo Paese."),
        ("video unavailable", "Il video non è più disponibile (rimosso o reso privato)."),
        ("has been removed", "Il video è stato rimosso."),
        ("live event will begin", "È una diretta non ancora iniziata: riprova quando sarà in onda."),
        ("is live", "Le dirette in corso non si possono scaricare finché non terminano."),
        ("429", "Il sito ha limitato le richieste. Aspetta qualche minuto e riprova."),
        ("too many requests", "Il sito ha limitato le richieste. Aspetta qualche minuto e riprova."),
        ("getaddrinfo", "Nessuna connessione a Internet, o il sito non è raggiungibile."),
        ("timed out", "Il sito non risponde: controlla la connessione e riprova."),
        ("urlopen error", "Nessuna connessione a Internet, o il sito non è raggiungibile."),
        ("unable to download webpage", "Non riesco a raggiungere la pagina: controlla la connessione e il link."),
        ("ffmpeg", "Manca ffmpeg, necessario per unire o convertire i file. Reinstalla il programma."),
        ("not found", "Il video non esiste più o il link non è corretto."),
        ("no space left", "Spazio su disco esaurito nella cartella di destinazione."),
        ("permission denied", "Non ho il permesso di scrivere nella cartella di destinazione."),
        ("requested format is not available", "La qualità scelta non è disponibile per questo video: prova un'altra."),
        ("no video formats", "In questo link non c'è un video scaricabile."),
    ]
    for key, msg in rules:
        if key in t:
            return msg
    return "Non sono riuscito a scaricare questo contenuto. Il sito potrebbe averlo protetto o cambiato."


@dataclass
class Info:
    url: str
    title: str
    uploader: str
    site: str
    duration: float
    thumb_url: str
    heights: list[int]           # altezze video disponibili (decrescenti); vuoto = solo audio
    has_video: bool = True


@dataclass(eq=False)
class Job:
    info: Info
    mode: str                    # "video" | "audio"
    height: int | None           # solo video
    acodec: str                  # solo audio (mp3, m4a, ...)
    bitrate: str
    embed: bool
    out_dir: Path
    browser: str = ""
    state: str = "queued"        # queued | run | ok | err | cancelled
    progress: float = 0.0
    status: str = "In attesa"
    path: Path | None = None
    error: str = ""
    detail: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)

    @property
    def label(self) -> str:
        if self.mode == "video":
            return f"MP4 · {'migliore' if not self.height else f'{self.height}p'}"
        name = next(a[0] for a in AUDIO_FORMATS if a[1] == self.acodec)
        return name.split(" ")[0] + ("" if self.acodec in LOSSLESS else f" · {self.bitrate} kbps")


def _base_opts(browser: str) -> dict:
    o = {"quiet": True, "no_warnings": True, "noplaylist": True, "socket_timeout": 20, "retries": 5,
         "windowsfilenames": True, "noprogress": True, "logger": _Log()}
    if (ff := find_ffmpeg()):
        o["ffmpeg_location"] = ff
    if (node := find_node()):
        o["js_runtimes"] = {"node": {"path": node}}
    if browser:
        o["cookiesfrombrowser"] = (browser,)
    return o


class _Log:
    def debug(self, m):
        pass

    info = debug

    def warning(self, m):
        log.info("yt-dlp: %s", m)

    def error(self, m):
        log.error("yt-dlp: %s", m)


def fetch_info(url: str, browser: str = "") -> tuple[Info, bytes]:
    """Legge titolo, miniatura e qualità disponibili senza scaricare. Può sollevare eccezioni di yt-dlp."""
    with yt_dlp.YoutubeDL(_base_opts(browser)) as ydl:
        d = ydl.extract_info(url, download=False)
    if d.get("_type") == "playlist":
        entries = [e for e in (d.get("entries") or []) if e]
        if len(entries) != 1:
            raise ValueError("Questo link è una playlist o un profilo: incolla il link di un singolo video.")
        d = entries[0]
    fmts = d.get("formats") or []
    heights = sorted({f["height"] for f in fmts if f.get("height") and f.get("vcodec") not in (None, "none")},
                     reverse=True)
    thumb = d.get("thumbnail") or ""
    has_video = not fmts or any(f.get("vcodec") != "none" for f in fmts)
    info = Info(url=d.get("webpage_url") or url, title=d.get("title") or "Senza titolo",
                uploader=d.get("uploader") or d.get("channel") or "", site=d.get("extractor_key") or "",
                duration=d.get("duration") or 0, thumb_url=thumb, heights=heights, has_video=has_video)
    data = b""
    if thumb:
        try:
            req = urllib.request.Request(thumb, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as r:
                data = r.read(4_000_000)
        except Exception:  # noqa: BLE001 - la miniatura e' solo estetica
            log.info("miniatura non scaricata")
    return info, data


def build_opts(job: Job, tmp: Path, hook) -> dict:
    o = _base_opts(job.browser)
    o.update({"outtmpl": "%(title).150B.%(ext)s", "paths": {"home": str(job.out_dir), "temp": str(tmp)},
              "progress_hooks": [hook], "overwrites": False, "continuedl": False})
    if job.mode == "video":
        h = f"[height<={job.height}]" if job.height else ""
        o["format"] = f"bv*{h}+ba/b{h}/b"
        o["format_sort"] = ["res", "vcodec:h264", "acodec:m4a"]     # a parita' di risoluzione preferisce H.264/AAC
        o["merge_output_format"] = "mp4"
        o["postprocessors"] = [{"key": "FFmpegMetadata", "add_metadata": True}]
    else:
        o["format"] = "ba/b"
        pp = [{"key": "FFmpegExtractAudio", "preferredcodec": job.acodec,
               "preferredquality": "0" if job.acodec in LOSSLESS else job.bitrate},
              {"key": "FFmpegMetadata", "add_metadata": True}]
        if job.embed and next(a[3] for a in AUDIO_FORMATS if a[1] == job.acodec):
            o["writethumbnail"] = True
            pp.insert(0, {"key": "FFmpegThumbnailsConvertor", "format": "jpg", "when": "before_dl"})
            pp.append({"key": "EmbedThumbnail"})
        o["postprocessors"] = pp
    return o


class InfoThread(QThread):
    done = Signal(object, bytes)
    failed = Signal(str, str)

    def __init__(self, url: str, browser: str, parent=None):
        super().__init__(parent)
        self.url, self.browser = url, browser

    def run(self):
        try:
            info, thumb = fetch_info(self.url, self.browser)
            self.done.emit(info, thumb)
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            log.error("analisi fallita: %s", msg)
            self.failed.emit(msg if isinstance(e, ValueError) else friendly_error(msg), msg)


class DownloadThread(QThread):
    progress = Signal(float, str)       # 0..1, testo di stato
    done = Signal(str)                  # percorso finale
    failed = Signal(str, str)           # messaggio, dettaglio
    cancelled = Signal()

    def __init__(self, job: Job, parent=None):
        super().__init__(parent)
        self.job = job
        self._stream = 0

    def _hook(self, d):
        if self.job.cancel.is_set():
            raise DownloadCancelled("annullato")
        n = max(len((d.get("info_dict") or {}).get("requested_formats") or []), 1)
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            frac = (d.get("downloaded_bytes") or 0) / total if total else 0.0
            sp = d.get("speed")
            eta = d.get("eta")
            txt = "Download"
            if sp:
                txt += f" · {sp / 1_048_576:.1f} MB/s".replace(".", ",")
            if eta is not None:
                txt += f" · {fmt_dur(eta) or '0:00'} rimasti"
            self.progress.emit(min((self._stream + frac) / n, 0.99) * 0.97, txt)
        elif d["status"] == "finished":
            self._stream += 1
            if self._stream >= n:
                self.progress.emit(0.97, "Elaborazione in corso…")

    def run(self):
        j = self.job
        tmp = DATA_DIR / "tmp" / f"{id(j):x}"
        try:
            j.out_dir.mkdir(parents=True, exist_ok=True)
            tmp.mkdir(parents=True, exist_ok=True)
            with yt_dlp.YoutubeDL(build_opts(j, tmp, self._hook)) as ydl:
                d = ydl.extract_info(j.info.url, download=True)
            rd = (d.get("requested_downloads") or [{}])[0]
            path = rd.get("filepath") or d.get("filepath") or ""
            if not path or not Path(path).exists():
                raise RuntimeError("Il file finale non è stato creato.")
            self.done.emit(path)
        except DownloadCancelled:
            self.cancelled.emit()
        except Exception as e:  # noqa: BLE001
            msg = str(e)
            if j.cancel.is_set():
                self.cancelled.emit()
            else:
                log.error("download fallito: %s", msg)
                self.failed.emit(friendly_error(msg), msg)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

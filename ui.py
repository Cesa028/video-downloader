"""Video Downloader - finestra principale: link, scelta formato, coda di download, tema e scorciatoie."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import (
    QAction, QActionGroup, QGuiApplication, QKeySequence, QPainter, QPainterPath, QPixmap, QShortcut,
)
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMenu,
    QMessageBox, QProgressBar, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

import icons
import theme
from common import APP_NAME, fmt_size, log, open_path, reveal, settings
from dialogs import AboutDialog, ErrorDialog
from engine import (
    AUDIO_BITRATES, AUDIO_FORMATS, BROWSERS, LOSSLESS, SITES, DownloadThread, Info, InfoThread, Job, extract_url,
    fmt_dur,
)
from theme import THEME_LABELS, THEMES, titlebar
from widgets import ElidedLabel, IconLabel, Badge, Segmented, Toast, Toggle, a11y_pass, label, repolish

THUMB_W, THUMB_H = 224, 126
BROWSER_LABELS = {"": "Nessuno", "firefox": "Firefox (consigliato)", "edge": "Microsoft Edge (spesso non funziona)",
                  "chrome": "Google Chrome (spesso non funziona)", "brave": "Brave (spesso non funziona)"}


def write_ui_assets(folder: Path) -> str:
    """Freccia dei menu a tendina (usata dal foglio di stile), una per tema."""
    folder.mkdir(parents=True, exist_ok=True)
    for name in ("dark", "light"):
        color = theme.DARK["muted"] if name == "dark" else theme.LIGHT["muted"]
        (folder / f"chev-{name}.svg").write_text(icons.svg("chevron-down", color, 2.4), encoding="utf-8")
    return folder.as_posix()


def apply_theme(app: QApplication, pref: str, asset_dir: Path) -> str:
    """Applica il tema ('system' | 'dark' | 'light') a tutta l'applicazione, senza riavvio."""
    name = theme.apply(pref)
    app.setPalette(theme.app_palette())
    app.setStyleSheet(theme.stylesheet(write_ui_assets(asset_dir)))
    for w in app.topLevelWidgets():
        if w.isVisible():
            titlebar(w)
    for w in app.allWidgets():
        w.update()
    return name


def read_theme_pref() -> str:
    v = settings().value("theme", "system")
    return v if v in THEMES else "system"


def rounded_thumb(data: bytes, w: int, h: int, radius: int = 10) -> QPixmap | None:
    """Miniatura ritagliata al centro (riempie il riquadro) con angoli arrotondati, nitida su schermi HiDPI."""
    src = QPixmap()
    if not data or not src.loadFromData(data):
        return None
    dpr = 2
    src = src.scaled(w * dpr, h * dpr, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
    out = QPixmap(w * dpr, h * dpr)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w * dpr, h * dpr), radius * dpr, radius * dpr)
    p.setClipPath(path)
    p.drawPixmap((w * dpr - src.width()) // 2, (h * dpr - src.height()) // 2, src)
    p.end()
    out.setDevicePixelRatio(dpr)
    return out


def icon_btn(name, tip, role="text2", danger=False) -> QPushButton:
    b = QPushButton(icons.icon(name, role), "")
    b.setObjectName("iconBtn")
    b.setProperty("danger", danger)
    b.setToolTip(tip)
    b.setAccessibleName(tip)
    b.setFixedSize(34, 34)
    b.setIconSize(b.size() * 0.55)
    b.setCursor(Qt.PointingHandCursor)
    return b


class DlRow(QFrame):
    """Una riga della lista download: titolo, stato, progresso e azioni."""
    act = Signal(str, object)           # azione, job

    def __init__(self, job: Job):
        super().__init__(objectName="card")
        self.job = job
        self.setProperty("row", True)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 10, 12)
        lay.setSpacing(12)
        self.kind = IconLabel("video" if job.mode == "video" else "music", "accent_text", 24, 1.8)
        lay.addWidget(self.kind)
        col = QVBoxLayout()
        col.setSpacing(3)
        self.title = ElidedLabel(job.info.title, Qt.ElideRight, objectName="rowTitle")
        self.meta = ElidedLabel("", Qt.ElideRight, objectName="rowMeta")
        self.bar = QProgressBar(objectName="dlBar")
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setAccessibleName("Avanzamento del download")
        self.pct = label("", "estimate")
        self.pct.setMinimumWidth(44)
        self.pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.bar_row = QWidget()
        br = QHBoxLayout(self.bar_row)
        br.setContentsMargins(0, 2, 0, 0)
        br.setSpacing(10)
        br.addWidget(self.bar, 1)
        br.addWidget(self.pct)
        for w in (self.title, self.meta, self.bar_row):
            col.addWidget(w)
        lay.addLayout(col, 1)
        self.badge = Badge()
        lay.addWidget(self.badge)
        self.b_cancel = icon_btn("x", "Annulla download", danger=True)
        self.b_retry = icon_btn("undo", "Riprova")
        self.b_detail = icon_btn("info", "Dettagli dell'errore")
        self.b_open = icon_btn("play", "Apri il file")
        self.b_reveal = icon_btn("folder-open", "Mostra nella cartella")
        self.b_remove = icon_btn("trash", "Rimuovi dalla lista", danger=True)
        for name, b in (("cancel", self.b_cancel), ("retry", self.b_retry), ("detail", self.b_detail),
                        ("open", self.b_open), ("reveal", self.b_reveal), ("remove", self.b_remove)):
            b.clicked.connect(lambda _=False, n=name: self.act.emit(n, self.job))
            lay.addWidget(b)
        self.refresh()

    def refresh(self):
        j = self.job
        st = {"queued": ("", "In coda"), "run": ("run", "In corso"), "ok": ("ok", "Completato"),
              "err": ("err", "Errore"), "cancelled": ("warn", "Annullato")}[j.state]
        self.badge.set_state(*st)
        busy = j.state == "run" and j.progress >= 0.97      # conversione/unione finale: durata non stimabile
        self.bar.setRange(0, 0 if busy else 1000)
        self.bar.setValue(int(j.progress * 1000))
        self.pct.setText("" if busy or j.state == "queued" else f"{int(j.progress * 100)}%")
        self.bar_row.setVisible(j.state in ("queued", "run"))
        self.meta.setFullText(f"{j.label}  ·  {j.status}")
        self.meta.setToolTip(j.error if j.state == "err" else "")
        self.b_cancel.setVisible(j.state in ("queued", "run"))
        self.b_retry.setVisible(j.state in ("err", "cancelled"))
        self.b_detail.setVisible(j.state == "err" and bool(j.detail))
        self.b_open.setVisible(j.state == "ok")
        self.b_reveal.setVisible(j.state == "ok")
        self.b_remove.setVisible(j.state != "run")
        a11y_pass(self)

    def contextMenuEvent(self, e):
        if self.job.state != "ok":
            return
        m = QMenu(self)
        for text, name in (("Apri il file", "open"), ("Mostra nella cartella", "reveal"),
                           ("Copia il percorso", "copy"), ("Rimuovi dalla lista", "remove")):
            m.addAction(text, lambda n=name: self.act.emit(n, self.job))
        m.exec(e.globalPos())


class MainWindow(QMainWindow):
    def __init__(self, tmp: Path):
        super().__init__()
        self.tmp = tmp
        self.settings = settings()
        self.theme_pref = read_theme_pref()
        self.info: Info | None = None
        self.jobs: list[Job] = []
        self.rows: dict[Job, DlRow] = {}
        self.cur: DownloadThread | None = None
        self.threads: set = set()
        self._token = 0
        self._prev_len = 0
        self._err_detail = ""
        self.browser = self.settings.value("browser", "")
        if self.browser not in BROWSERS:
            self.browser = ""
        self.out_dir = Path(self.settings.value("out_dir", str(Path.home() / "Downloads" / "Video Downloader")))

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(icons.app_icon())
        self.setMinimumSize(760, 680)
        self.setAcceptDrops(True)
        self._build()
        self._shortcuts()
        if not self.restoreGeometry(self.settings.value("geometry", QByteArray())):
            self.resize(900, 780)
        self._set_view("empty")
        self._load_prefs()
        clip = extract_url(QGuiApplication.clipboard().text())
        if clip:
            self.url.setText(clip)
            self._prev_len = len(clip)
        a11y_pass(self)
        self.url.setFocus()

    # ------------------------------------------------------------------ costruzione
    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        body = QVBoxLayout()
        body.setContentsMargins(24, 20, 24, 16)
        body.setSpacing(14)
        outer.addLayout(body, 1)

        # intestazione
        head = QHBoxLayout()
        head.setSpacing(12)
        logo = QLabel()
        logo.setPixmap(icons.svg_pixmap(icons.ICON_SVG, 40))
        logo.setAccessibleName("Logo")
        head.addWidget(logo)
        col = QVBoxLayout()
        col.setSpacing(0)
        col.addWidget(label(APP_NAME, "appTitle"))
        col.addWidget(label("Scarica video e audio da YouTube, TikTok, Instagram e molti altri siti", "appSub"))
        head.addLayout(col, 1)
        self.btn_menu = QPushButton(icons.icon("settings"), "  Impostazioni", objectName="ghost")
        self.btn_menu.setCursor(Qt.PointingHandCursor)
        self.btn_menu.setMenu(self._build_menu())
        head.addWidget(self.btn_menu)
        body.addLayout(head)

        # barra del link
        row = QHBoxLayout()
        row.setSpacing(8)
        self.url = QLineEdit(objectName="url")
        self.url.setPlaceholderText("Incolla qui il link del video (YouTube, TikTok, Instagram…)")
        self.url.setAccessibleName("Link del video")
        self.url.setClearButtonEnabled(True)
        self.url.returnPressed.connect(self.analyze)
        self.url.textEdited.connect(self._url_edited)
        row.addWidget(self.url, 1)
        self.btn_paste = QPushButton(icons.icon("paste"), "  Incolla")
        self.btn_paste.setToolTip("Incolla il link dagli appunti e analizzalo  (Ctrl+Maiusc+V)")
        self.btn_paste.setCursor(Qt.PointingHandCursor)
        self.btn_paste.clicked.connect(self.paste)
        row.addWidget(self.btn_paste)
        self.btn_go = QPushButton(icons.icon("search", "on_accent"), "  Analizza", objectName="primary")
        self.btn_go.setToolTip("Leggi il link e mostra le opzioni  (Invio)")
        self.btn_go.setCursor(Qt.PointingHandCursor)
        self.btn_go.clicked.connect(self.analyze)
        row.addWidget(self.btn_go)
        body.addLayout(row)

        # stato: vuoto / caricamento / errore / risultato
        self.empty = self._build_empty()
        body.addWidget(self.empty)
        self.loading = QFrame(objectName="card")
        ll = QVBoxLayout(self.loading)
        ll.setContentsMargins(20, 18, 20, 18)
        ll.setSpacing(10)
        ll.addWidget(label("Sto leggendo il link…"))
        bar = QProgressBar(objectName="overall")
        bar.setRange(0, 0)
        bar.setTextVisible(False)
        bar.setAccessibleName("Analisi del link in corso")
        ll.addWidget(bar)
        body.addWidget(self.loading)
        self.errbox = QFrame()
        el = QHBoxLayout(self.errbox)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(8)
        self.err_label = label("", "warn", True)
        self.err_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        el.addWidget(self.err_label, 1)
        self.err_detail = QPushButton("Dettagli")
        self.err_detail.clicked.connect(lambda: ErrorDialog(self, "Non è andata a buon fine", self.err_label.text(),
                                                            self._err_detail).exec())
        el.addWidget(self.err_detail, 0, Qt.AlignTop)
        body.addWidget(self.errbox)
        self.card = self._build_card()
        body.addWidget(self.card)
        self.filler = QWidget()      # tiene le schede in alto quando non ci sono download
        body.addWidget(self.filler, 1)

        # download
        dh = QHBoxLayout()
        self.dl_title = label("DOWNLOAD", "sectionTitle")
        dh.addWidget(self.dl_title)
        dh.addStretch()
        self.btn_clear = QPushButton(icons.icon("trash", "muted"), "  Rimuovi completati", objectName="ghost")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.clicked.connect(self.clear_done)
        dh.addWidget(self.btn_clear)
        self.dl_head = QWidget()
        self.dl_head.setLayout(dh)
        dh.setContentsMargins(0, 0, 0, 0)
        body.addWidget(self.dl_head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setAccessibleName("Elenco dei download")
        inner = QWidget(objectName="sideInner")
        self.list = QVBoxLayout(inner)
        self.list.setContentsMargins(0, 0, 4, 0)
        self.list.setSpacing(8)
        self.list.addStretch()
        scroll.setWidget(inner)
        self.scroll = scroll
        body.addWidget(scroll, 1)

        # barra inferiore: cartella di salvataggio
        bar = QFrame(objectName="actionBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(24, 10, 24, 10)
        bl.setSpacing(10)
        bl.addWidget(IconLabel("folder", "muted", 18))
        self.out_label = ElidedLabel("", Qt.ElideMiddle, objectName="statusText")
        bl.addWidget(self.out_label, 1)
        b = QPushButton("Cambia cartella…")
        b.setToolTip("Scegli dove salvare i file  (Ctrl+Maiusc+O)")
        b.clicked.connect(self.choose_dir)
        bl.addWidget(b)
        self.btn_open_dir = QPushButton(icons.icon("folder-open"), "  Apri cartella")
        self.btn_open_dir.setToolTip("Apri la cartella dei download  (Ctrl+O)")
        self.btn_open_dir.clicked.connect(self.open_dir)
        bl.addWidget(self.btn_open_dir)
        outer.addWidget(bar)
        self._refresh_out()
        self.toast = Toast(root)

    def _build_menu(self) -> QMenu:
        m = QMenu(self)
        tm = m.addMenu(icons.icon("sun"), "Tema")
        self.theme_group = QActionGroup(self)
        for key in THEMES:
            a = QAction(THEME_LABELS[key], self, checkable=True, checked=key == self.theme_pref)
            a.triggered.connect(lambda _=False, k=key: self.set_theme(k))
            self.theme_group.addAction(a)
            tm.addAction(a)
        cm = m.addMenu(icons.icon("globe"), "Cookie del browser (video privati o con limiti di età)")
        self.browser_group = QActionGroup(self)
        for key in BROWSERS:
            a = QAction(BROWSER_LABELS[key], self, checkable=True, checked=key == self.browser)
            a.triggered.connect(lambda _=False, k=key: self.set_browser(k))
            self.browser_group.addAction(a)
            cm.addAction(a)
        m.addSeparator()
        m.addAction(icons.icon("info"), "Informazioni, licenza e crediti   F1", lambda: AboutDialog(self).exec())
        return m

    def _build_empty(self) -> QFrame:
        f = QFrame(objectName="dropZone")
        lay = QVBoxLayout(f)
        lay.setContentsMargins(24, 28, 24, 28)
        lay.setSpacing(12)
        ic = IconLabel("download", "drop_icon", 44, 1.6)
        lay.addWidget(ic, 0, Qt.AlignHCenter)
        t = label("Incolla un link per iniziare", "dropTitle")
        t.setAlignment(Qt.AlignCenter)
        lay.addWidget(t)
        steps = QHBoxLayout()
        steps.setSpacing(18)
        steps.addStretch()
        for n, text in enumerate(("Incolla il link", "Scegli video o audio", "Scarica"), 1):
            s = QHBoxLayout()
            s.setSpacing(8)
            num = label(str(n), "stepNum")
            num.setFixedSize(22, 22)
            num.setAlignment(Qt.AlignCenter)
            s.addWidget(num)
            s.addWidget(label(text, "step"))
            steps.addLayout(s)
        steps.addStretch()
        lay.addLayout(steps)
        lay.addSpacing(4)
        sub = label("Funziona con:", "dropSub")
        sub.setAlignment(Qt.AlignCenter)
        lay.addWidget(sub)
        chips = QGridLayout()
        chips.setHorizontalSpacing(8)
        chips.setVerticalSpacing(8)
        per_row = 6
        for i, s in enumerate(SITES + ["e molti altri"]):
            chips.addWidget(label(s, "chip"), i // per_row, i % per_row, Qt.AlignCenter)
        lay.addLayout(chips)
        return f

    def _build_card(self) -> QFrame:
        c = QFrame(objectName="card")
        lay = QHBoxLayout(c)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(16)
        self.thumb = QLabel(objectName="thumb")
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setAccessibleName("Miniatura del video")
        lay.addWidget(self.thumb, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(8)
        self.c_title = label("", "rowTitle", True)
        self.c_title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.c_meta = ElidedLabel("", Qt.ElideRight, objectName="rowMeta")
        col.addWidget(self.c_title)
        col.addWidget(self.c_meta)
        col.addSpacing(2)
        self.mode = Segmented(["Video (MP4)", "Solo audio"], "Tipo di file")
        self.mode.changed.connect(self._mode_changed)
        col.addWidget(self.mode)

        # opzioni video
        self.opt_video = QWidget()
        ov = QHBoxLayout(self.opt_video)
        ov.setContentsMargins(0, 0, 0, 0)
        ov.setSpacing(8)
        ov.addWidget(label("Qualità", "fieldLabel"))
        self.cb_quality = QComboBox()
        self.cb_quality.setMinimumWidth(190)
        ov.addWidget(self.cb_quality)
        ov.addStretch()
        col.addWidget(self.opt_video)

        # opzioni audio
        self.opt_audio = QWidget()
        oa = QHBoxLayout(self.opt_audio)
        oa.setContentsMargins(0, 0, 0, 0)
        oa.setSpacing(8)
        oa.addWidget(label("Formato", "fieldLabel"))
        self.cb_afmt = QComboBox()
        for name, codec, _ext, _cover in AUDIO_FORMATS:
            self.cb_afmt.addItem(name, codec)
        self.cb_afmt.currentIndexChanged.connect(self._afmt_changed)
        oa.addWidget(self.cb_afmt)
        oa.addSpacing(6)
        oa.addWidget(label("Qualità", "fieldLabel"))
        self.cb_abr = QComboBox()
        for b in AUDIO_BITRATES:
            self.cb_abr.addItem(f"{b} kbps", b)
        self.cb_abr.setCurrentIndex(2)
        oa.addWidget(self.cb_abr)
        oa.addSpacing(6)
        self.tg_embed = Toggle(True, "Incorpora copertina e informazioni")
        self.tg_embed.setToolTip("Aggiunge nel file la copertina e il titolo (non disponibile per WAV)")
        oa.addWidget(self.tg_embed)
        oa.addWidget(label("Con copertina", "fieldLabel"))
        oa.addStretch()
        col.addWidget(self.opt_audio)

        row = QHBoxLayout()
        self.c_summary = label("", "small")
        row.addWidget(self.c_summary, 1)
        self.btn_dl = QPushButton(icons.icon("download", "on_accent"), "  Scarica", objectName="primary")
        self.btn_dl.setToolTip("Aggiungi ai download  (Ctrl+Invio)")
        self.btn_dl.setCursor(Qt.PointingHandCursor)
        self.btn_dl.clicked.connect(self.enqueue)
        row.addWidget(self.btn_dl)
        col.addLayout(row)
        lay.addLayout(col, 1)
        return c

    def _shortcuts(self):
        def sc(keys, fn):
            QShortcut(QKeySequence(keys), self, activated=fn)
        sc("Ctrl+L", lambda: (self.url.setFocus(), self.url.selectAll()))
        sc("Ctrl+Shift+V", self.paste)
        sc("Ctrl+Return", lambda: self.card.isVisible() and self.enqueue())
        sc("Ctrl+O", self.open_dir)
        sc("Ctrl+Shift+O", self.choose_dir)
        sc("F1", lambda: AboutDialog(self).exec())
        self.btn_menu.setToolTip("Tema, cookie del browser e informazioni")

    # ------------------------------------------------------------------ preferenze
    def _load_prefs(self):
        s = self.settings
        self.mode.set_index(1 if s.value("mode", "video") == "audio" else 0)
        i = self.cb_afmt.findData(s.value("afmt", "mp3"))
        self.cb_afmt.setCurrentIndex(max(i, 0))
        i = self.cb_abr.findData(s.value("abr", "192"))
        self.cb_abr.setCurrentIndex(max(i, 0))
        self.tg_embed.setChecked(str(s.value("embed", "true")).lower() == "true")
        self._mode_changed()

    def _save_prefs(self):
        s = self.settings
        s.setValue("mode", "audio" if self.mode.index() else "video")
        s.setValue("afmt", self.cb_afmt.currentData())
        s.setValue("abr", self.cb_abr.currentData())
        s.setValue("embed", self.tg_embed.isChecked())
        s.setValue("out_dir", str(self.out_dir))
        s.setValue("browser", self.browser)
        s.setValue("theme", self.theme_pref)

    def set_theme(self, pref: str):
        self.theme_pref = pref
        apply_theme(QApplication.instance(), pref, self.tmp / "ui")
        self._save_prefs()

    def set_browser(self, key: str):
        self.browser = key
        self._save_prefs()
        self.toast.show_msg("Cookie del browser: " + BROWSER_LABELS[key])

    # ------------------------------------------------------------------ viste
    def _set_view(self, v: str):
        self._view = v
        self.loading.setVisible(v == "loading")
        self.errbox.setVisible(v == "error")
        self.card.setVisible(v == "result")
        self._sync_empty()
        busy = v == "loading"
        self.btn_go.setEnabled(not busy)
        self.btn_go.setText("  Analizzo…" if busy else "  Analizza")
        self.btn_go.setToolTip("Sto leggendo il link…" if busy else "Leggi il link e mostra le opzioni  (Invio)")

    def _sync_empty(self):
        self.empty.setVisible(self._view == "empty" and not self.jobs)
        has = bool(self.jobs)
        self.filler.setVisible(not has)
        self.dl_head.setVisible(has)
        self.scroll.setVisible(has)
        self.dl_title.setText(f"DOWNLOAD ({len(self.jobs)})")
        self.btn_clear.setEnabled(any(j.state in ("ok", "err", "cancelled") for j in self.jobs))
        self.btn_clear.setToolTip("" if self.btn_clear.isEnabled() else "Nessun download terminato da rimuovere")

    def _show_error(self, msg: str, detail: str = ""):
        self.err_label.setText(msg)
        self._err_detail = detail
        self.err_detail.setVisible(bool(detail))
        self._set_view("error")

    # ------------------------------------------------------------------ analisi del link
    def _url_edited(self, text: str):
        """Un incolla (testo che cresce di colpo) avvia subito l'analisi; scrivendo a mano si preme Invio."""
        grew = len(text) - self._prev_len
        self._prev_len = len(text)
        if grew > 8 and extract_url(text):
            self.analyze()

    def paste(self):
        url = extract_url(QGuiApplication.clipboard().text())
        if not url:
            self.toast.show_msg("Negli appunti non c'è nessun link.")
            return
        self.url.setText(url)
        self._prev_len = len(url)
        self.analyze()

    def analyze(self):
        text = self.url.text().strip()
        url = extract_url(text) or (extract_url("https://" + text) if "." in text and " " not in text else None)
        if not url:
            self._show_error("Incolla il link di un video: deve iniziare con http:// o https://")
            self.url.setFocus()
            return
        self._token += 1
        tok = self._token
        self.info = None
        self._set_view("loading")
        th = InfoThread(url, self.browser, self)
        th.done.connect(lambda info, data, t=tok: self._info_ok(t, info, data))
        th.failed.connect(lambda msg, det, t=tok: self._token == t and self._show_error(msg, det))
        self._run_thread(th)

    def _run_thread(self, th):
        self.threads.add(th)
        th.finished.connect(lambda t=th: (self.threads.discard(t), t.deleteLater()))
        th.start()

    def _info_ok(self, tok: int, info: Info, data: bytes):
        if tok != self._token:
            return
        self.info = info
        pm = rounded_thumb(data, THUMB_W, THUMB_H)
        if pm:
            self.thumb.setPixmap(pm)
        else:
            self.thumb.setPixmap(QPixmap())
            self.thumb.setPixmap(icons.icon("video", "dim").pixmap(48, 48))
        self.c_title.setText(info.title)
        self.c_meta.setFullText("  ·  ".join(x for x in (info.uploader, info.site.replace("Youtube", "YouTube"),
                                                           fmt_dur(info.duration)) if x))
        self.cb_quality.clear()
        if info.has_video:
            self.cb_quality.addItem("Migliore disponibile", None)
            for h in info.heights:
                tag = {2160: " (4K)", 1440: " (2K)", 1080: " (Full HD)", 720: " (HD)"}.get(h, "")
                self.cb_quality.addItem(f"{h}p{tag}", h)
            # di default Full HD (o la migliore sotto): file piu' leggeri, ottimi su ogni schermo
            pick = next((i for i in range(1, self.cb_quality.count()) if self.cb_quality.itemData(i) <= 1080), 0)
            self.cb_quality.setCurrentIndex(pick)
        self.mode.group.button(0).setEnabled(info.has_video)
        self.mode.group.button(0).setToolTip("" if info.has_video else "Questo link contiene solo audio")
        if not info.has_video:
            self.mode.set_index(1)
        self._mode_changed()
        self._set_view("result")
        self.btn_dl.setFocus()

    def _mode_changed(self, *_):
        audio = self.mode.index() == 1
        self.opt_video.setVisible(not audio)
        self.opt_audio.setVisible(audio)
        self.btn_dl.setText("  Scarica audio" if audio else "  Scarica video")
        self._afmt_changed()
        self._save_prefs()

    def _afmt_changed(self, *_):
        codec = self.cb_afmt.currentData()
        lossless = codec in LOSSLESS
        self.cb_abr.setEnabled(not lossless)
        self.cb_abr.setToolTip("Non serve: questo formato non perde qualità" if lossless else "")
        can_cover = next(a[3] for a in AUDIO_FORMATS if a[1] == codec)
        self.tg_embed.setEnabled(can_cover)
        self.tg_embed.setToolTip("Aggiunge nel file la copertina e il titolo" if can_cover
                                 else "Il formato WAV non supporta la copertina")
        if self.mode.index() == 1:
            self.c_summary.setText("Salva come " + (self.cb_afmt.currentText().split(" ")[0]) +
                                   ("" if lossless else f", {self.cb_abr.currentData()} kbps"))
        else:
            self.c_summary.setText("Salva come file MP4 compatibile con quasi tutti i dispositivi")
        if hasattr(self, "settings"):
            self._save_prefs()

    # ------------------------------------------------------------------ download
    def enqueue(self):
        if not self.info:
            return
        audio = self.mode.index() == 1
        job = Job(info=self.info, mode="audio" if audio else "video",
                  height=None if audio else self.cb_quality.currentData(),
                  acodec=self.cb_afmt.currentData(), bitrate=self.cb_abr.currentData(),
                  embed=self.tg_embed.isChecked() and self.tg_embed.isEnabled(), out_dir=self.out_dir,
                  browser=self.browser)
        self.jobs.append(job)
        row = DlRow(job)
        row.act.connect(self._row_action)
        self.rows[job] = row
        self.list.insertWidget(0, row)
        self.toast.show_msg("Aggiunto ai download")
        self._set_view("empty")
        self.url.clear()
        self._prev_len = 0
        self.url.setFocus()
        self._pump()

    def _pump(self):
        """Avvia il prossimo download in coda (uno alla volta, per non saturare la connessione)."""
        if self.cur:
            return
        job = next((j for j in self.jobs if j.state == "queued"), None)
        if not job:
            self.setWindowTitle(APP_NAME)
            return
        job.state, job.status, job.progress = "run", "Avvio…", 0.0
        self.rows[job].refresh()
        th = DownloadThread(job, self)
        self.cur = th
        th.progress.connect(lambda f, s, j=job: self._progress(j, f, s))
        th.done.connect(lambda p, j=job: self._finished(j, "ok", path=p))
        th.failed.connect(lambda m, d, j=job: self._finished(j, "err", err=m, detail=d))
        th.cancelled.connect(lambda j=job: self._finished(j, "cancelled"))
        self._run_thread(th)

    def _progress(self, job: Job, frac: float, text: str):
        job.progress, job.status = frac, text
        if job in self.rows:
            self.rows[job].refresh()
        self.setWindowTitle(f"{int(frac * 100)}% · {APP_NAME}")

    def _finished(self, job: Job, state: str, path: str = "", err: str = "", detail: str = ""):
        job.state = state
        if state == "ok":
            job.path = Path(path)
            job.progress = 1.0
            mb = job.path.stat().st_size / 1_048_576 if job.path.exists() else 0
            job.status = f"Salvato · {fmt_size(mb)}" + (" · qualità ridotta: YouTube blocca quella scelta" if job.downgraded else "")
            self.toast.show_msg("Download completato: " + (job.info.title[:44] + "…" if len(job.info.title) > 44 else job.info.title))
        elif state == "err":
            job.error, job.detail, job.status = err, detail, err
        else:
            job.status = "Annullato dall'utente"
        self.cur = None
        if job in self.rows:
            self.rows[job].refresh()
        self._sync_empty()
        self._pump()

    def _row_action(self, name: str, job: Job):
        if name == "cancel":
            job.cancel.set()
            if job.state == "queued":
                job.state, job.status = "cancelled", "Annullato dall'utente"
            else:
                job.status = "Annullamento…"
            self.rows[job].refresh()
            self._sync_empty()
        elif name == "retry":
            job.cancel.clear()
            job.state, job.status, job.progress, job.error, job.detail = "queued", "In attesa", 0.0, "", ""
            self.rows[job].refresh()
            self._sync_empty()
            self._pump()
        elif name == "remove":
            self.jobs.remove(job)
            self.rows.pop(job).deleteLater()
            self._sync_empty()
        elif name == "open":
            open_path(str(job.path))
        elif name == "reveal":
            reveal(job.path)
        elif name == "copy":
            QGuiApplication.clipboard().setText(str(job.path))
            self.toast.show_msg("Percorso copiato")
        elif name == "detail":
            ErrorDialog(self, "Download non riuscito", job.error, job.detail).exec()

    def clear_done(self):
        for j in [j for j in self.jobs if j.state in ("ok", "err", "cancelled")]:
            self._row_action("remove", j)

    # ------------------------------------------------------------------ cartella
    def _refresh_out(self):
        self.out_label.setFullText(f"Salvataggio in:  {self.out_dir}")
        self.out_label.setToolTip(str(self.out_dir))

    def choose_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Scegli la cartella dei download", str(self.out_dir))
        if d:
            self.out_dir = Path(d)
            self._refresh_out()
            self._save_prefs()

    def open_dir(self):
        self.out_dir.mkdir(parents=True, exist_ok=True)
        open_path(str(self.out_dir))

    # ------------------------------------------------------------------ eventi finestra
    def showEvent(self, e):
        titlebar(self)
        super().showEvent(e)

    def _drag_zone(self, on: bool):
        self.empty.setProperty("drag", on)
        repolish(self.empty)

    def dragEnterEvent(self, e):
        md = e.mimeData()
        if md.hasText() or md.hasUrls():
            e.acceptProposedAction()
            self._drag_zone(True)

    def dragLeaveEvent(self, e):
        self._drag_zone(False)

    def dropEvent(self, e):
        self._drag_zone(False)
        md = e.mimeData()
        url = extract_url(md.text()) or (md.urls()[0].toString() if md.hasUrls() and md.urls()[0].scheme().startswith("http")
                                         else None)
        if url:
            self.url.setText(url)
            self._prev_len = len(url)
            self.analyze()
        else:
            self.toast.show_msg("Trascina un link, non un file.")

    def closeEvent(self, e):
        busy = [j for j in self.jobs if j.state in ("run", "queued")]
        if busy:
            r = QMessageBox.question(self, APP_NAME, "Ci sono download in corso o in coda. Se chiudi ora verranno "
                                     "annullati. Vuoi chiudere?", QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                e.ignore()
                return
            for j in busy:
                j.cancel.set()
            if self.cur:
                self.cur.wait(5000)
        self.settings.setValue("geometry", self.saveGeometry())
        self._save_prefs()
        log.info("Chiusura")
        super().closeEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.toast.isVisible():
            self.toast.move((self.width() - self.toast.width()) // 2, self.height() - self.toast.height() - 28)

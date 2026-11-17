"""Video Downloader - widget riutilizzabili. Tutto cio' che e' disegnato a mano legge la palette
corrente `P` al momento del paint, quindi segue il cambio di tema dal vivo."""
from __future__ import annotations

import re

from PySide6.QtCore import QPropertyAnimation, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QButtonGroup, QComboBox, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLayout,
    QLineEdit, QPushButton, QSizePolicy, QSlider, QWidget,
)

import icons
from theme import DUR_BASE, P, qcolor


def repolish(w: QWidget):
    w.style().unpolish(w)
    w.style().polish(w)
    w.update()


def label(text, obj=None, wrap=False) -> QLabel:
    lab = QLabel(text)
    if obj:
        lab.setObjectName(obj)
    lab.setWordWrap(wrap)
    return lab


def sep() -> QFrame:
    f = QFrame()
    f.setObjectName("sep")
    return f


def a11y_pass(root: QWidget):
    """Rifinitura di accessibilita' su un'intera finestra: i pulsanti prendono il focus solo da tastiera,
    quelli con la sola icona usano il suggerimento come nome accessibile e i campi prendono il nome
    dall'etichetta che li precede."""
    for b in root.findChildren(QPushButton):
        if b.focusPolicy() != Qt.NoFocus:
            b.setFocusPolicy(Qt.TabFocus)
        if not b.text().strip() and not b.accessibleName():
            tip = b.toolTip().split("  (")[0].strip()
            if tip:
                b.setAccessibleName(tip)
    layouts = ([root.layout()] if root.layout() else []) + root.findChildren(QLayout)
    for lay in layouts:
        last = ""
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if isinstance(w, QLabel):
                txt = re.sub(r"<[^>]+>", "", w.text()).strip()
                if txt:
                    last = txt
            elif isinstance(w, (QComboBox, QSlider, QLineEdit)) and not w.accessibleName():
                name = last or w.toolTip()
                if name:
                    w.setAccessibleName(name)


def paint_focus_ring(p: QPainter, rect: QRectF, radius: float):
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(qcolor(P.focus), 2))
    p.drawRoundedRect(rect, radius, radius)


def arrow_nav(btn: QAbstractButton, e) -> bool:
    """Frecce sinistra/destra/su/giu': sposta la selezione tra i pulsanti dello stesso gruppo esclusivo."""
    d = {Qt.Key_Left: -1, Qt.Key_Up: -1, Qt.Key_Right: 1, Qt.Key_Down: 1}.get(e.key())
    grp = btn.group()
    if d is None or grp is None:
        return False
    en = [b for b in grp.buttons() if b.isEnabled()]
    if btn not in en:
        return False
    nb = en[(en.index(btn) + d) % len(en)]
    nb.setFocus(Qt.TabFocusReason)
    nb.click()
    return True


class ElidedLabel(QLabel):
    def __init__(self, text="", mode=Qt.ElideMiddle, **kw):
        super().__init__(**kw)
        self._full, self._mode = text, mode
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(30)
        self._refresh()

    def setFullText(self, t: str):
        self._full = t
        self._refresh()

    def fullText(self) -> str:
        return self._full

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._refresh()

    def _refresh(self):
        QLabel.setText(self, self.fontMetrics().elidedText(self._full, self._mode, max(self.width(), 30)))


class IconLabel(QWidget):
    """Icona vettoriale che si ricolora col tema. Trasparente al mouse."""

    def __init__(self, name="check", role="text2", size=16, width=2.0, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._w = width
        self.set_icon(name, role)

    def set_icon(self, name, role=None):
        if role:
            self._role = role
        self._name = name
        self._ic = icons.icon(name, self._role, width=self._w)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self._ic.paint(p, self.rect())


class Toggle(QAbstractButton):
    def __init__(self, checked=False, name=""):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        self.setFixedSize(42, 26)
        if name:
            self.setAccessibleName(name)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        on, en = self.isChecked(), self.isEnabled()
        track = qcolor(P.accent if on else P.control)
        if not en:
            track.setAlpha(90)
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(2, 2, 38, 22), 11, 11)
        p.setBrush(qcolor("#ffffff" if en else P.dim))
        p.drawEllipse(QRectF(21 if on else 5, 5, 16, 16))
        if self.hasFocus():
            paint_focus_ring(p, QRectF(1, 1, 40, 24), 12)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            return self.click()
        super().keyPressEvent(e)


class SegButton(QPushButton):
    def keyPressEvent(self, e):
        if not arrow_nav(self, e):
            super().keyPressEvent(e)


class Segmented(QWidget):
    changed = Signal(int)

    def __init__(self, labels: list[str], name: str = ""):
        super().__init__()
        self.name = name
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.group.idClicked.connect(self.changed.emit)
        self.set_labels(labels)

    def set_labels(self, labels: list[str]):
        for b in self.group.buttons():
            self.group.removeButton(b)
            self.lay.removeWidget(b)
            b.hide()
            b.deleteLater()
        n = len(labels)
        for i, text in enumerate(labels):
            b = SegButton(text, objectName="seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.TabFocus)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setProperty("pos", "only" if n == 1 else "first" if i == 0 else "last" if i == n - 1 else "mid")
            if self.name:
                b.setAccessibleName(f"{self.name}: {text}")
            self.group.addButton(b, i)
            self.lay.addWidget(b)
        if n:
            self.group.button(0).setChecked(True)

    def index(self) -> int:
        return max(self.group.checkedId(), 0)

    def set_index(self, i: int):
        b = self.group.button(i)
        if b:
            b.setChecked(True)


class Badge(QFrame):
    """Etichetta di stato con icona opzionale (colori dal tema tramite il foglio di stile)."""
    ICONS = {"ok": ("check", "ok"), "err": ("alert", "err"), "warn": ("alert", "warn")}

    def __init__(self):
        super().__init__(objectName="badge")
        h = QHBoxLayout(self)
        h.setContentsMargins(9, 3, 10, 3)
        h.setSpacing(5)
        self.ic = IconLabel("check", "ok", 12, 2.6)
        self.lbl = QLabel()
        h.addWidget(self.ic)
        h.addWidget(self.lbl)

    def set_state(self, state: str, text: str):
        self.lbl.setText(text)
        self.setProperty("state", state)
        ic = self.ICONS.get(state)
        self.ic.setVisible(bool(ic))
        if ic:
            self.ic.set_icon(*ic)
        self.setAccessibleName(text)
        repolish(self)
        for c in self.findChildren(QLabel):
            repolish(c)

    def state(self) -> str:
        return self.property("state") or ""

    def setText(self, text: str):
        self.lbl.setText(text)
        self.setAccessibleName(text)


class Toast(QLabel):
    """Messaggio non invasivo che compare in basso e svanisce da solo."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("toast")
        self.setTextFormat(Qt.PlainText)
        self.setAccessibleName("Notifica")
        self.eff = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.eff)
        self.anim = QPropertyAnimation(self.eff, b"opacity", self)
        self.anim.setDuration(DUR_BASE)
        self.timer = QTimer(self, singleShot=True)
        self.timer.timeout.connect(self._fade_out)
        self._fading = False
        self.anim.finished.connect(lambda: self._fading and self.hide())
        self.hide()

    def show_msg(self, text, ms=3200):
        self.setText(text)
        self.setMaximumWidth(max(240, self.parentWidget().width() - 80))
        self.setWordWrap(False)
        self.adjustSize()
        if self.width() > self.maximumWidth():
            self.setWordWrap(True)
            self.adjustSize()
        par = self.parentWidget()
        self.move((par.width() - self.width()) // 2, par.height() - self.height() - 28)
        self.raise_()
        self.show()
        self.anim.stop()
        self._fading = False
        self.anim.setStartValue(self.eff.opacity() if self.isVisible() else 0.0)
        self.anim.setEndValue(1.0)
        self.anim.start()
        self.timer.start(ms)

    def _fade_out(self):
        self.anim.stop()
        self.anim.setStartValue(1.0)
        self.anim.setEndValue(0.0)
        self._fading = True
        self.anim.start()

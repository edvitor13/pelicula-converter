"""Tela de boas-vindas (versão, projetos recentes, atalhos) e janela de novidades."""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

from PySide6.QtCore import QDate, QLocale, QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QImage, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QTextBrowser,
                               QVBoxLayout, QWidget)

from .. import __date__, __version__, i18n, project, updater
from ..i18n import _
from . import icons, theme

MAX_RECENT = 12


# ------------------------------------------------------------------ utilidades
def long_date(iso: str) -> str:
    """Data por extenso no idioma atual (16 de outubro de 2026 / October 16, 2026)."""
    d = QDate.fromString(iso[:10], "yyyy-MM-dd")
    if not d.isValid():
        return iso
    lang = i18n.language()
    if lang == "en":
        return QLocale(QLocale.Language.English).toString(d, "MMMM d, yyyy")
    loc = QLocale(QLocale.Language.Spanish) if lang == "es" else QLocale(QLocale.Language.Portuguese, QLocale.Country.Brazil)
    return loc.toString(d, "d 'de' MMMM 'de' yyyy")


def short_datetime(ts: float) -> str:
    if not ts:
        return ""
    fmt = "%m/%d/%Y %H:%M" if i18n.language() == "en" else "%d/%m/%Y %H:%M"
    return time.strftime(fmt, time.localtime(ts))


def recent_projects(settings) -> list[str]:
    raw = settings.value("recent_projects", []) or []
    if isinstance(raw, str):
        raw = [raw]
    return [p for p in raw if isinstance(p, str)]


def add_recent(settings, path: str) -> None:
    path = str(Path(path).resolve())
    items = [p for p in recent_projects(settings) if os.path.normcase(p) != os.path.normcase(path)]
    settings.setValue("recent_projects", [path] + items[: MAX_RECENT - 1])


def remove_recent(settings, path: str) -> None:
    settings.setValue("recent_projects", [p for p in recent_projects(settings) if p != path])


def novidades_text(lang: str | None = None) -> str:
    lang = lang or i18n.language()
    base = Path(__file__).resolve().parents[1] / "novidades"
    for code in (lang, "en", "pt_BR"):
        f = base / f"{code}.md"
        if f.is_file():
            return f.read_text(encoding="utf-8")
    return ""


# ------------------------------------------------------------------ novidades
class WhatsNewDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Novidades"))
        self.resize(640, 620)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        k = QLabel(_("NOVIDADES"))
        k.setObjectName("Kicker")
        lay.addWidget(k)
        t = QLabel(_("O que há de novo no PeliculaConverter"))
        t.setObjectName("PanelTitle")
        t.setStyleSheet("font-size: 14pt;")
        lay.addWidget(t)
        view = QTextBrowser()
        view.setOpenExternalLinks(True)
        view.setStyleSheet(f"QTextBrowser {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; "
                           f"border-radius: 10px; padding: 12px; font-size: 10pt; }}")
        view.setMarkdown(novidades_text())
        lay.addWidget(view, 1)
        row = QHBoxLayout()
        row.addStretch(1)
        ok = QPushButton(_("Fechar"))
        ok.setObjectName("Primary")
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)


# ------------------------------------------------------------------ boas-vindas
class RecentItem(QWidget):
    clicked = Signal(str)
    removed = Signal(str)

    def __init__(self, info: dict, parent=None):
        super().__init__(parent)
        self.info = info
        self.setFixedHeight(76)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hover = False
        self.thumb = None
        if info.get("thumb"):
            img = QImage.fromData(info["thumb"])
            if not img.isNull():
                self.thumb = img
        tip = info.get("path", "")
        if not info.get("media_ok"):
            tip += "\n" + _("O vídeo deste projeto não foi encontrado; o app vai pedir para localizá-lo.")
        self.setToolTip(tip)

    def enterEvent(self, _e):
        self._hover = True
        self.update()

    def leaveEvent(self, _e):
        self._hover = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.info["path"])
        elif e.button() == Qt.MouseButton.RightButton:
            self.removed.emit(self.info["path"])

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(theme.ACCENT_DIM if self._hover else theme.BORDER), 1))
        p.setBrush(QColor(theme.PANEL3 if self._hover else theme.PANEL2))
        p.drawRoundedRect(r, 10, 10)
        tr = QRectF(r.left() + 8, r.top() + 8, 104, r.height() - 16)
        path = QPainterPath()
        path.addRoundedRect(tr, 6, 6)
        p.save()
        p.setClipPath(path)
        if self.thumb is not None:
            p.drawImage(tr, self.thumb.scaled(int(tr.width() * 2), int(tr.height() * 2),
                                              Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                              Qt.TransformationMode.SmoothTransformation))
        else:
            p.fillRect(tr, QColor(theme.PANEL))
            p.drawPixmap(int(tr.center().x()) - 12, int(tr.center().y()) - 12, icons.icon("film", theme.FAINT, 24).pixmap(24, 24))
        p.restore()
        x = tr.right() + 12
        w = r.right() - x - 10
        p.setPen(QColor(theme.TEXT))
        f = theme.font(10, theme.QFont.Weight.DemiBold)
        p.setFont(f)
        p.drawText(QRectF(x, r.top() + 10, w, 20), Qt.AlignmentFlag.AlignLeft,
                   QFontMetrics(f).elidedText(self.info.get("name", ""), Qt.TextElideMode.ElideRight, int(w)))
        f2 = theme.font(8.5)
        p.setFont(f2)
        p.setPen(QColor(theme.MUTED))
        media = os.path.basename(self.info.get("media", "")) or _("sem vídeo")
        if not self.info.get("media_ok"):
            p.setPen(QColor(theme.DANGER))
            media = _("vídeo não encontrado: {nome}").format(nome=media)
        p.drawText(QRectF(x, r.top() + 32, w, 18), Qt.AlignmentFlag.AlignLeft,
                   QFontMetrics(f2).elidedText(media, Qt.TextElideMode.ElideMiddle, int(w)))
        p.setPen(QColor(theme.FAINT))
        p.drawText(QRectF(x, r.top() + 50, w, 18), Qt.AlignmentFlag.AlignLeft,
                   _("salvo em {data}").format(data=short_datetime(self.info.get("saved_at", 0))))
        p.end()


class _UpdateBridge(QObject):
    found = Signal(object)


class WelcomeDialog(QDialog):
    """Mostra a versão, os projetos recentes e os atalhos para começar.

    Depois de fechado, `action` diz o que fazer: ("media", caminho), ("project", caminho),
    ("open_media", None), ("open_project", None), ("test", None), ("update", release) ou None.
    """

    def __init__(self, parent, settings, check_updates: bool = True):
        super().__init__(parent)
        self.settings = settings
        self.action = None
        self.setWindowTitle(_("Bem-vindo ao PeliculaConverter"))
        self.setWindowIcon(icons.app_icon())
        self.resize(900, 640)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        banner = QLabel()
        banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bpath = icons.assets_dir() / "banner.png"
        if bpath.is_file():
            pm = QPixmap(str(bpath))
            banner.setPixmap(pm.scaledToWidth(900, Qt.TransformationMode.SmoothTransformation))
        banner.setStyleSheet(f"background: {theme.BG};")
        lay.addWidget(banner)

        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(26, 18, 26, 10)
        bl.setSpacing(24)
        lay.addWidget(body, 1)

        left = QVBoxLayout()
        left.setSpacing(8)
        ver = QLabel(_("Versão {versao}").format(versao=__version__))
        ver.setObjectName("PanelTitle")
        ver.setStyleSheet("font-size: 15pt;")
        left.addWidget(ver)
        date = QLabel(long_date(__date__))
        date.setObjectName("Muted")
        left.addWidget(date)
        self.update_box = QPushButton()
        self.update_box.setObjectName("Primary")
        self.update_box.setVisible(False)
        self.update_box.clicked.connect(self._go_update)
        left.addWidget(self.update_box)
        left.addSpacing(10)
        for text, icon, act, primary in (
            (_("Abrir vídeo ou imagem…"), "open", ("open_media", None), True),
            (_("Abrir projeto (.plc)…"), "folder", ("open_project", None), False),
            (_("Usar a cena de teste"), "image", ("test", None), False),
        ):
            b = QPushButton("  " + text)
            b.setIcon(icons.icon(icon, "#1b1205" if primary else theme.TEXT, 18))
            b.setIconSize(QSize(18, 18))
            if primary:
                b.setObjectName("Primary")
            b.setMinimumHeight(38)
            b.clicked.connect(lambda _=False, a=act: self._finish(a))
            left.addWidget(b)
        news = QPushButton("  " + _("Novidades desta versão"))
        news.setIcon(icons.icon("more", theme.TEXT, 18))
        news.setMinimumHeight(38)
        news.clicked.connect(lambda: WhatsNewDialog(self).exec())
        left.addWidget(news)
        left.addStretch(1)
        bl.addLayout(left, 0)

        right = QVBoxLayout()
        right.setSpacing(8)
        k = QLabel(_("CONTINUAR EDITANDO"))
        k.setObjectName("Kicker")
        right.addWidget(k)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        right.addWidget(self.scroll, 1)
        hint = QLabel(_("Clique para abrir • botão direito remove da lista"))
        hint.setObjectName("Faint")
        right.addWidget(hint)
        bl.addLayout(right, 1)

        foot = QWidget()
        fl = QHBoxLayout(foot)
        fl.setContentsMargins(26, 6, 26, 16)
        self.show_again = QCheckBox(_("Mostrar esta tela ao abrir o app"))
        self.show_again.setChecked(str(settings.value("show_welcome", "true")) != "false")
        fl.addWidget(self.show_again)
        fl.addStretch(1)
        close = QPushButton(_("Ir para o app"))
        close.clicked.connect(lambda: self._finish(None))
        fl.addWidget(close)
        lay.addWidget(foot)
        self._fill_recent()

        self._bridge = _UpdateBridge()
        self._bridge.found.connect(self._show_update)
        self.release = None
        if check_updates:
            threading.Thread(target=self._check, daemon=True).start()

    def _fill_recent(self) -> None:
        inner = QWidget()
        vl = QVBoxLayout(inner)
        vl.setContentsMargins(0, 0, 6, 0)
        vl.setSpacing(6)
        count = 0
        for path in recent_projects(self.settings):
            if not os.path.isfile(path):
                continue
            info = project.peek(path)
            if not info:
                continue
            item = RecentItem(info)
            item.clicked.connect(lambda p: self._finish(("project", p)))
            item.removed.connect(self._remove)
            vl.addWidget(item)
            count += 1
        if not count:
            empty = QLabel(_("Nenhum projeto ainda. Abra um vídeo, ajuste o look e use Projeto > Salvar "
                             "para continuar depois de onde parou."))
            empty.setObjectName("Muted")
            empty.setWordWrap(True)
            vl.addWidget(empty)
        vl.addStretch(1)
        self.scroll.setWidget(inner)

    def _remove(self, path: str) -> None:
        remove_recent(self.settings, path)
        self._fill_recent()

    def _check(self) -> None:
        try:
            rel = updater.check(timeout=6)
        except updater.UpdateError:
            return
        if updater.is_newer(rel):
            self._bridge.found.emit(rel)

    def _show_update(self, rel) -> None:
        self.release = rel
        self.update_box.setText("  " + _("Nova versão {versao} disponível — atualizar").format(versao=rel.tag.lstrip("v")))
        self.update_box.setIcon(icons.icon("export", "#1b1205", 16))
        self.update_box.setVisible(True)

    def _go_update(self) -> None:
        self._finish(("update", self.release))

    def _finish(self, action) -> None:
        self.action = action
        self.settings.setValue("show_welcome", "true" if self.show_again.isChecked() else "false")
        self.accept()

    def reject(self) -> None:
        self.settings.setValue("show_welcome", "true" if self.show_again.isChecked() else "false")
        super().reject()

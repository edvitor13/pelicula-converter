"""Configurações › Componentes: ferramentas externas (baixadas pelo app) e programas do sistema.

Um cartão por componente do registro `tools.TOOLS`: ícone, para que serve, versão, espaço em disco,
local (com "Abrir pasta"), fonte oficial, licença, selo "verificado (SHA-256)", que módulos usam e os
botões Baixar / Atualizar / Remover. No fim, o espaço total e a seção Sistema (placa de vídeo,
OpenGL, processador e bibliotecas Python), que antes ficava na janela "Dependências e atualizações".

Downloads e remoções rodam na fila de tarefas (`jobs.py`, pela ponte `ui/job_bridge.py`): continuam
se a janela fechar e reaparecem com o progresso ao reabrir. O que precisa acontecer mesmo com a
janela fechada (o ffmpeg novo passar a valer) fica em `_after_job`, chamado na thread principal.

`MainWindow.show_deps(reason, auto_download)` abre esta página com um aviso (`set_reason`) e, se
pedido, já começa a baixar o ffmpeg (`download("ffmpeg")`).
"""

from __future__ import annotations

import html
import platform
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from ... import deps, jobs, media, modules, system, tools
from ...i18n import _
from .. import icons, theme
from ..flow import ElideLabel, FlowLayout
from ..job_bridge import bridge
from ._base import PageBase

KEY_PREFIX = "componente:"     # chave dos trabalhos de cada componente: "componente:<id>"
LATEST_KEY = "consulta:ffmpeg"  # consulta da versão mais nova do ffmpeg (só quando o usuário pede)
PIP_KEY = "sistema:pip"

_CHIP = {
    "ok": (theme.OK, "#16261d", "#2c5a40"),
    "accent": (theme.ACCENT_HI, "#2a1f10", theme.ACCENT_DIM),
    "danger": (theme.DANGER, "#2a1514", "#5c2a27"),
    "muted": (theme.MUTED, theme.PANEL3, theme.BORDER),
}

CARD_QSS = (
    f"QFrame#ToolCard {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; border-radius: 12px; }}"
    f"QLabel#ToolIcon {{ background: {theme.PANEL3}; border-radius: 11px; }}"
    f"QLabel#ToolName {{ font-size: 11.5pt; font-weight: 600; }}"
    f"QFrame#Badge {{ background: #16261d; border: 1px solid #2c5a40; border-radius: 9px; }}"
    f"QLabel#BadgeText {{ color: {theme.OK}; font-size: 8.5pt; font-weight: 600; }}"
    f"QFrame#Reason {{ background: #2a1f10; border: 1px solid {theme.ACCENT_DIM}; border-radius: 10px; }}"
)


def ffmpeg_manual_text() -> str:
    """Sem download automático neste sistema: como instalar o ffmpeg por conta própria."""
    return _("O download automático ainda não está disponível neste sistema. Instale o ffmpeg pelo gerenciador "
             "de pacotes e use \"Usar outra pasta…\" se precisar.")


def job_key(tool_id: str) -> str:
    return KEY_PREFIX + tool_id


def latest_ffmpeg() -> str:
    """Versão mais nova do ffmpeg já consultada nesta sessão (pela checagem ao abrir o app ou pelo botão
    "Procurar versão nova"); a página nunca consulta a rede sozinha."""
    return deps.cached_latest_version()


def _store_latest(job: jobs.Job) -> None:
    if job.state == jobs.CONCLUIDO and job.result:
        deps.remember_latest_version(str(job.result))


def can_check_latest() -> bool:
    """Se a fonte do ffmpeg deste sistema publica a versão mais nova (hoje só o gyan.dev, no Windows)."""
    src = deps.SOURCES.get(deps.platform_key()) or {}
    return deps.platform_supported() and bool(src.get("version_url"))


def _after_job(job: jobs.Job) -> None:
    """Na thread principal, com ou sem a página aberta: o ffmpeg novo (ou a falta dele) passa a valer."""
    data = job.data or {}
    if data.get("tool") != "ffmpeg" or job.state != jobs.CONCLUIDO:
        return
    settings = data.get("settings")
    if data.get("acao") == "baixar" and settings is not None:
        settings.remove("ffmpeg_dir")  # o ffmpeg baixado pelo app passa na frente da pasta escolhida
    folder = settings.value("ffmpeg_dir", "") if settings is not None else ""
    media.configure(folder or None)


def _download_fn(tool: tools.Tool):
    def run(job: jobs.Job):
        return tools.download(tool, job.progress_callback(), job.cancel_event)
    return run


def _remove_fn(tool: tools.Tool):
    def run(job: jobs.Job):
        job.report(_("Removendo…"))
        return tools.remove(tool)
    return run


def _gpu_text(main) -> str:
    eng = getattr(main, "engine", None)
    if eng is None:
        return ""
    try:
        return f"{eng.renderer} • OpenGL {eng.ctx.info.get('GL_VERSION', '?')}"
    except Exception:  # noqa: BLE001
        return ""


def breakable(text: str) -> str:
    """Permite quebrar a linha depois de "\\" e "/" (um caminho comprido não alarga a página)."""
    return text.replace("\\", "\\\u200b").replace("/", "/\u200b")


def _version_text(version: str) -> str:
    """ "Versão 8.0.1"; textos como "build de desenvolvimento de 07/12/2023" aparecem como estão."""
    if version[:1].isdigit():
        return _("Versão {versao}").format(versao=version)
    return version[:1].upper() + version[1:]


def _link(url: str, text: str) -> str:
    return (f"<a style='color:{theme.ACCENT_HI}; text-decoration:none' href='{html.escape(url, quote=True)}'>"
            f"{html.escape(text)}</a>")


class PathLabel(ElideLabel):
    """Caminho numa linha, cortado no meio (o caminho inteiro vai na dica)."""

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        r = self.contentsRect()
        text = self.fontMetrics().elidedText(self.text(), Qt.TextElideMode.ElideMiddle, r.width())
        p.drawText(r, int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter), text)
        p.end()


class Badge(QFrame):
    """Selo "verificado (SHA-256)" com o hash na dica."""

    def __init__(self):
        super().__init__()
        self.setObjectName("Badge")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(7, 2, 9, 2)
        lay.setSpacing(4)
        ic = QLabel()
        ic.setPixmap(icons.icon("shield", theme.OK, 14).pixmap(14, 14))
        lay.addWidget(ic)
        self.text = QLabel(_("verificado (SHA-256)"))
        self.text.setObjectName("BadgeText")
        lay.addWidget(self.text)


class ToolCard(QFrame):
    """Cartão de um componente. `refresh(status)` atualiza tudo; `show_job(job)` mostra o progresso."""

    def __init__(self, page: "Page", tool: tools.Tool):
        super().__init__()
        self.page = page
        self.tool = tool
        self.status: tools.Status | None = None
        self.job: jobs.Job | None = None
        self._shown_busy: bool | None = None
        self.setObjectName("ToolCard")
        self.setStyleSheet(CARD_QSS)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(14)
        self.icon = QLabel()
        self.icon.setObjectName("ToolIcon")
        self.icon.setFixedSize(44, 44)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon.setPixmap(icons.icon(tool.icon, theme.ACCENT, 26).pixmap(26, 26))
        lay.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)

        col = QVBoxLayout()
        col.setSpacing(5)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.name = QLabel(_(tool.name))
        self.name.setObjectName("ToolName")
        head.addWidget(self.name)
        self.chip = QLabel()
        head.addWidget(self.chip)
        head.addStretch(1)
        self.badge = Badge()
        head.addWidget(self.badge)
        col.addLayout(head)

        self.desc = QLabel(_(tool.description))
        self.desc.setObjectName("Muted")
        self.desc.setWordWrap(True)
        col.addWidget(self.desc)
        self.info = QLabel()
        self.info.setWordWrap(True)
        info_row = QHBoxLayout()
        info_row.setSpacing(8)
        info_row.addWidget(self.info, 1)
        self.btn_check = None
        if tool.backend == "ffmpeg":
            self.btn_check = QPushButton(_("Procurar versão nova"))
            self.btn_check.setObjectName("Flat")
            self.btn_check.setToolTip(_("Consulta a fonte oficial do ffmpeg; nada é enviado além do pedido de "
                                        "versão"))
            self.btn_check.clicked.connect(self.page.check_latest)
            self.btn_check.setVisible(can_check_latest())
            info_row.addWidget(self.btn_check)
        col.addLayout(info_row)

        self.where_row = QWidget()
        wr = QHBoxLayout(self.where_row)
        wr.setContentsMargins(0, 0, 0, 0)
        wr.setSpacing(6)
        self.where = PathLabel()
        self.where.setObjectName("Faint")
        wr.addWidget(self.where, 1)
        self.btn_folder = QPushButton(_("Abrir pasta"))
        self.btn_folder.setObjectName("Flat")
        self.btn_folder.setIcon(icons.icon("folder", theme.TEXT, 14))
        self.btn_folder.clicked.connect(self._open_folder)
        wr.addWidget(self.btn_folder)
        col.addWidget(self.where_row)

        self.links = QLabel()
        self.links.setObjectName("Faint")
        self.links.setWordWrap(True)
        self.links.setTextFormat(Qt.TextFormat.RichText)
        self.links.setOpenExternalLinks(True)
        self.links.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        col.addWidget(self.links)
        self.used = QLabel()
        self.used.setObjectName("Faint")
        self.used.setWordWrap(True)
        col.addWidget(self.used)
        self.notes = QLabel()
        self.notes.setObjectName("Muted")
        self.notes.setWordWrap(True)
        col.addWidget(self.notes)
        self.message = QLabel()
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.message.setVisible(False)
        col.addWidget(self.message)

        self.progress_row = QWidget()
        pr = QVBoxLayout(self.progress_row)
        pr.setContentsMargins(0, 2, 0, 0)
        pr.setSpacing(3)
        bar_row = QHBoxLayout()
        bar_row.setSpacing(8)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        bar_row.addWidget(self.bar, 1)
        self.btn_cancel = QPushButton(_("Cancelar"))
        self.btn_cancel.clicked.connect(self._cancel)
        bar_row.addWidget(self.btn_cancel)
        pr.addLayout(bar_row)
        self.stage = QLabel()
        self.stage.setObjectName("Muted")
        pr.addWidget(self.stage)
        self.progress_row.setVisible(False)
        col.addWidget(self.progress_row)

        # Botões numa FlowLayout: numa janela estreita eles quebram a linha em vez de alargar a página.
        self.buttons = QWidget()
        buttons = FlowLayout(self.buttons, 8, 6, center_rows=False)
        buttons.setContentsMargins(0, 2, 0, 0)
        self.btn_main = QPushButton()
        self.btn_main.clicked.connect(lambda: self.page.download(self.tool.id))
        buttons.addWidget(self.btn_main)
        self.btn_remove = QPushButton("  " + _("Remover"))
        self.btn_remove.setIcon(icons.icon("trash", theme.TEXT, 15))
        self.btn_remove.clicked.connect(lambda: self.page.remove(self.tool.id))
        buttons.addWidget(self.btn_remove)
        self.btn_other = None
        if tool.backend == "ffmpeg":
            self.btn_other = QPushButton(_("Usar outra pasta…"))
            self.btn_other.setIcon(icons.icon("folder", theme.TEXT, 15))
            self.btn_other.clicked.connect(self.page.pick_ffmpeg_folder)
        elif tool.id == "davinci_resolve":
            self.btn_other = QPushButton(_("Plugin do DaVinci…"))
            self.btn_other.setIcon(icons.icon("davinci", theme.TEXT, 15))
            self.btn_other.clicked.connect(self.page.open_resolve_plugin)
        if self.btn_other is not None:
            buttons.addWidget(self.btn_other)
        buttons.add_stretch()
        sp = self.buttons.sizePolicy()
        sp.setHeightForWidth(True)
        self.buttons.setSizePolicy(sp)
        col.addWidget(self.buttons)
        lay.addLayout(col, 1)

    # ------------------------------------------------------------ estado
    @property
    def busy(self) -> bool:
        return self.job is not None and self.job.active

    def _set_chip(self, text: str, tone: str) -> None:
        fg, bg, border = _CHIP[tone]
        self.chip.setText(text)
        self.chip.setStyleSheet(f"color: {fg}; background: {bg}; border: 1px solid {border}; border-radius: 9px; "
                                f"padding: 1px 9px; font-size: 8.5pt; font-weight: 600;")

    def refresh(self, st: tools.Status) -> None:
        self.status = st
        t = self.tool
        system_tool = t.kind == tools.SISTEMA
        # selo de estado
        if self.busy:
            removing = (self.job.data or {}).get("acao") == "remover"
            self._set_chip(_("Removendo…") if removing else _("Baixando…"), "accent")
        elif system_tool:
            self._set_chip(_("No sistema") if st.installed else _("Não encontrado"), "ok" if st.installed else "muted")
        elif st.state == tools.INDISPONIVEL:
            self._set_chip(_("Indisponível neste sistema"), "muted")
        elif st.state == tools.AUSENTE:
            self._set_chip(_("Não instalado"), "danger" if t.core else "muted")
        elif st.state == tools.DESATUALIZADO:
            self._set_chip(_("Desatualizado"), "accent")
        elif st.update_available:
            self._set_chip(_("Atualização disponível"), "accent")
        else:
            self._set_chip(_("Instalado"), "ok")
        self.badge.setVisible(st.verified)
        if st.verified:
            self.badge.setToolTip(_("Conferido com o SHA-256 antes de instalar:\n{hash}").format(hash=st.sha256))
        # versão e espaço
        parts = []
        if st.version:
            parts.append(_version_text(st.version))
        elif not system_tool and st.state == tools.AUSENTE and st.available and t.backend != "ffmpeg":
            parts.append(_("Versão {versao} para baixar ({tamanho})").format(
                versao=st.available, tamanho=tools.fmt_size(st.download_size)))
        if st.size:
            parts.append(_("{tamanho} no disco").format(tamanho=tools.fmt_size(st.size)))
        if st.installed and st.update_available and st.available:
            parts.append(_("versão {versao} disponível").format(versao=st.available))
        if not parts:
            if system_tool:
                parts.append(_("Não encontrado neste computador. Instale pelo site oficial: o PeliculaConverter só "
                               "detecta, não baixa."))
            elif t.backend == "ffmpeg" and not st.installed:
                parts.append(_("Não encontrado.") + " " + _("Sem o ffmpeg o app não consegue abrir nem exportar "
                                                            "vídeos."))
            elif st.state == tools.INDISPONIVEL:
                parts.append(_("{nome} ainda não tem download para este sistema.").format(nome=_(t.name)))
        self.info.setText(" • ".join(parts))
        # local
        shown = st.path or st.folder
        note = st.where_note
        chosen = str(self.page.settings.value("ffmpeg_dir", "") or "") if t.backend == "ffmpeg" else ""
        if chosen and st.path and not st.in_use_managed and Path(st.path).parent == Path(chosen):
            note = _("(pasta escolhida)")
        self.where_row.setVisible(bool(shown))
        self.where.setText(f"{shown} {note}".strip() if shown else "")
        self.btn_folder.setEnabled(bool(st.folder))
        # links
        links = [_link(t.homepage, _("Site oficial")),
                 _("Licença: {licenca}").format(licenca=_link(t.license_url, _(t.license)))]
        if t.backend == "ffmpeg" and st.source_name:
            links.append(_("Fonte do download: {fonte}").format(
                fonte=_link(st.source_url, st.source_name) if st.source_url else html.escape(st.source_name)))
        elif t.kind == tools.BAIXADO and st.origin == tools.CI:
            links.append(_link(st.source_url or t.homepage,
                               _("Compilado pelo PeliculaConverter a partir do código oficial")))
        elif t.kind == tools.BAIXADO and st.origin == tools.OFICIAL:
            links.append(html.escape(_("Binário oficial do autor")))
        self.links.setText(" &nbsp;•&nbsp; ".join(links))
        # quem usa
        if t.core:
            self.used.setText(_("Usado por: núcleo do app (abrir, prévia e exportação)"))
        else:
            names = [_(modules.get(m).name) for m in tools.used_by(t) if modules.exists(m)]
            self.used.setText(_("Usado por: {lista}").format(lista=", ".join(names)) if names else "")
        self.used.setVisible(bool(self.used.text()))
        notes = list(st.notes)
        if t.backend == "ffmpeg" and not st.downloadable:
            notes.append(ffmpeg_manual_text())
        self.notes.setText("\n".join(notes))
        self.notes.setVisible(bool(notes))
        # botões
        self.btn_main.setVisible(not system_tool and st.downloadable)
        ffmpeg = t.backend == "ffmpeg"  # o aviso de "ffmpeg ausente" ao abrir o app fala em "Baixar ffmpeg"
        if st.state == tools.AUSENTE:
            self._main_button(_("Baixar ffmpeg") if ffmpeg else _("Baixar"), primary=True)
        elif st.update_available or st.state == tools.DESATUALIZADO:
            self._main_button(_("Atualizar ffmpeg") if ffmpeg else _("Atualizar"), primary=True)
        else:
            self._main_button(_("Baixar de novo"), primary=False)
        self.btn_main.setEnabled(not self.busy)
        self.btn_remove.setVisible(st.managed and not system_tool)
        self.btn_remove.setEnabled(not self.busy)
        if self.btn_other is not None:
            if t.id == "davinci_resolve":
                main = self.page.main
                self.btn_other.setVisible(st.installed and main is not None and hasattr(main, "show_resolve")
                                          and modules.is_enabled(self.page.settings, "davinci"))
            else:
                self.btn_other.setEnabled(not self.busy)

    def _main_button(self, text: str, primary: bool) -> None:
        self.btn_main.setText("  " + text)
        self.btn_main.setObjectName("Primary" if primary else "")
        self.btn_main.setIcon(icons.icon("download", "#1b1205" if primary else theme.TEXT, 15))
        self.btn_main.style().unpolish(self.btn_main)
        self.btn_main.style().polish(self.btn_main)

    def show_message(self, text: str, tone: str = "muted") -> None:
        color = {"ok": theme.OK, "danger": theme.DANGER, "accent": theme.ACCENT_HI}.get(tone, theme.MUTED)
        self.message.setStyleSheet(f"color: {color};")
        self.message.setText(breakable(text))
        self.message.setVisible(bool(text))

    def show_job(self, job: jobs.Job) -> None:
        """Mostra o trabalho em andamento (ou esconde a barra quando ele termina)."""
        self.job = job
        active = job.active
        if active != self._shown_busy:  # começou ou terminou: o resto do cartão muda junto
            self._shown_busy = active
            self.progress_row.setVisible(active)
            if active:
                self.show_message("")
                self.btn_cancel.setVisible((job.data or {}).get("acao") != "remover")  # remover é instantâneo
            if self.status is not None:
                self.refresh(self.status)
        if not active:
            return
        frac = job.progress
        if frac is None:
            self.bar.setRange(0, 0)
        else:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(frac * 1000))
        if job.cancelled:
            stage = _("Cancelando…")
        else:
            stage = job.stage or _("Na fila…")
            if job.total > 1:
                stage += " " + _("{feito} de {total}").format(feito=tools.fmt_size(job.done),
                                                               total=tools.fmt_size(job.total))
        self.stage.setText(stage)
        self.btn_cancel.setEnabled(not job.cancelled)

    def _cancel(self) -> None:
        if self.job is not None and self.job.active:
            self.job.cancel()
            self.show_job(self.job)

    def _open_folder(self) -> None:
        if self.status is not None and self.status.folder:
            system.open_path(self.status.folder)


class Page(PageBase):
    def __init__(self, dialog):
        super().__init__(dialog, _("Componentes"),
                         _("Programas externos que o PeliculaConverter usa. Os downloads vêm só da fonte oficial, "
                           "são conferidos com SHA-256 antes de instalar e ficam na pasta do app, só para o seu "
                           "usuário (sem administrador)."))
        self.main = dialog.main
        self.reason_box = QFrame()
        self.reason_box.setObjectName("Reason")
        self.reason_box.setStyleSheet(CARD_QSS)
        rl = QVBoxLayout(self.reason_box)
        rl.setContentsMargins(12, 9, 12, 9)
        self.reason = QLabel()
        self.reason.setWordWrap(True)
        self.reason.setStyleSheet(f"color: {theme.ACCENT_HI};")
        rl.addWidget(self.reason)
        self.reason_box.setVisible(False)
        self.body.addWidget(self.reason_box)

        self.cards: dict[str, ToolCard] = {}
        groups = ((tools.BAIXADO, _("Baixados pelo app")), (tools.SISTEMA, _("Instalados no sistema")))
        for kind, title in groups:
            items = [t for t in tools.all_tools() if t.kind == kind]
            if not items:
                continue
            self.kicker(title)
            for t in items:
                card = ToolCard(self, t)
                self.cards[t.id] = card
                self.body.addWidget(card)

        total_row = QHBoxLayout()
        total_col = QVBoxLayout()
        total_col.setSpacing(2)
        self.total = QLabel()
        self.total.setWordWrap(True)
        total_col.addWidget(self.total)
        self.data_dir = PathLabel()
        self.data_dir.setObjectName("Faint")
        total_col.addWidget(self.data_dir)
        total_row.addLayout(total_col, 1)
        self.btn_data = QPushButton(_("Abrir a pasta dos componentes"))
        self.btn_data.setIcon(icons.icon("folder", theme.TEXT, 15))
        self.btn_data.clicked.connect(lambda: system.open_path(deps.app_data_dir()))
        total_row.addWidget(self.btn_data)
        self.body.addLayout(total_row)

        self.kicker(_("Sistema"))
        self.body.addWidget(self._system_box())
        self.finish()

        b = bridge()
        b.changed.connect(self._on_job_changed)
        b.finished.connect(self._on_job_finished)
        self.refresh()
        for tid, card in self.cards.items():
            job = b.queue.find(job_key(tid))
            if job is not None:
                card.show_job(job)

    # ------------------------------------------------------------ partes
    def _system_box(self) -> QFrame:
        box = QFrame()
        box.setObjectName("ToolCard")
        box.setStyleSheet(CARD_QSS)
        lay = QHBoxLayout(box)
        lay.setContentsMargins(14, 12, 14, 12)
        lay.setSpacing(14)
        ic = QLabel()
        ic.setObjectName("ToolIcon")
        ic.setFixedSize(44, 44)
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic.setPixmap(icons.icon("chip", theme.ACCENT, 26).pixmap(26, 26))
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(5)
        title = QLabel(_("Placa de vídeo e bibliotecas"))
        title.setObjectName("ToolName")
        col.addWidget(title)
        total, _avail = system.ram()
        frozen = " " + _("(executável)") if getattr(sys, "frozen", False) else ""
        pk = "  •  ".join(f"{n} {ver}" for n, ver in deps.python_packages())
        self.gpu = QLabel(_("Efeitos na GPU: {placa}").format(placa=_gpu_text(self.main) or _("não detectada")))
        self.gpu.setWordWrap(True)
        col.addWidget(self.gpu)
        self.sysinfo = QLabel("\n".join([
            _("Sistema: {sistema} • Python {python}").format(
                sistema=f"{platform.system()} {platform.release()}", python=platform.python_version()) + frozen,
            _("Processador: {cpu} • {n} núcleos • memória {ram}").format(
                cpu=system.cpu_name(), n=system.cpu_threads(), ram=system.gb(total)),
            _("Bibliotecas: {lista}").format(lista=pk),
        ]))
        self.sysinfo.setObjectName("Muted")
        self.sysinfo.setWordWrap(True)
        self.sysinfo.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        col.addWidget(self.sysinfo)
        self.btn_pip = None
        missing = deps.missing_python_modules()
        if missing and not getattr(sys, "frozen", False):
            self.btn_pip = QPushButton(_("Instalar bibliotecas que faltam ({lista})").format(lista=", ".join(missing)))
            self.btn_pip.clicked.connect(lambda: self.install_libraries(missing))
            col.addWidget(self.btn_pip)
        self.pip_status = QLabel()
        self.pip_status.setWordWrap(True)
        self.pip_status.setVisible(False)
        col.addWidget(self.pip_status)
        tip = QLabel(_("Se os efeitos não aparecerem, atualize o driver da placa de vídeo (NVIDIA, AMD ou Intel). "
                       "O app precisa de OpenGL 3.3."))
        tip.setObjectName("Faint")
        tip.setWordWrap(True)
        col.addWidget(tip)
        lay.addLayout(col, 1)
        return box

    # ------------------------------------------------------------ estado
    def set_reason(self, text: str) -> None:
        """Aviso no topo (ex.: ffmpeg ausente ao abrir o app)."""
        self.reason.setText(text or "")
        self.reason_box.setVisible(bool(text))

    def refresh(self, tool_id: str | None = None) -> None:
        if tool_id in (None, "ffmpeg"):
            media.configure(self.settings.value("ffmpeg_dir", "") or None)
        for tid, card in self.cards.items():
            if tool_id is None or tid == tool_id:
                card.refresh(tools.status(card.tool, latest=latest_ffmpeg()))
        self._refresh_total()

    def _refresh_total(self) -> None:
        used = tools.disk_usage()
        self.total.setText(_("Espaço usado pelos componentes: {tamanho}").format(tamanho=tools.fmt_size(used)))
        self.data_dir.setText(_("Pasta: {pasta}").format(pasta=deps.app_data_dir()))
        self.btn_data.setEnabled(deps.app_data_dir().is_dir())

    def check_latest(self) -> jobs.Job | None:
        """Botão "Procurar versão nova": consulta a fonte do ffmpeg (só quando o usuário pede)."""
        if not can_check_latest():
            return None
        b = bridge()
        job = b.queue.find(LATEST_KEY)
        if job is None:
            job = b.submit(lambda j: deps.latest_version(), _("Consultar a versão mais recente do ffmpeg"),
                           kind=jobs.REDE, key=LATEST_KEY, on_finished=_store_latest)
            card = self.cards.get("ffmpeg")
            if card is not None and card.btn_check is not None:
                card.btn_check.setEnabled(False)
                card.show_message(_("Consultando a versão mais recente…"))
        return job

    # ------------------------------------------------------------ ações
    def download(self, tool_id: str) -> jobs.Job | None:
        """Baixa (ou atualiza) um componente pela fila de tarefas. Devolve o trabalho (ou None)."""
        card = self.cards.get(tool_id)
        if card is None:
            return None
        b = bridge()
        running = b.queue.find(job_key(tool_id))
        if running is not None:
            card.show_job(running)
            return running
        tool = card.tool
        st = card.status or tools.status(tool, latest=latest_ffmpeg())
        if not st.downloadable:
            card.show_message(ffmpeg_manual_text() if tool.backend == "ffmpeg" else
                              _("{nome} ainda não tem download para este sistema.").format(nome=_(tool.name)),
                              "danger")
            return None
        if tool.consent and not self._consent(tool):
            return None
        job = b.submit(_download_fn(tool), _("Baixar {nome}").format(nome=_(tool.name)), kind=jobs.REDE,
                       key=job_key(tool_id), data={"tool": tool_id, "acao": "baixar", "settings": self.settings},
                       on_finished=_after_job)
        card.show_job(job)
        return job

    def remove(self, tool_id: str) -> jobs.Job | None:
        card = self.cards.get(tool_id)
        if card is None or card.busy or card.status is None or not card.status.managed:
            return None
        tool, size = card.tool, tools.fmt_size(card.status.size)
        if tool.backend == "ffmpeg":
            text = _("Remover o ffmpeg baixado pelo app ({tamanho})? Se não houver outro ffmpeg no computador, o app "
                     "não vai conseguir abrir nem exportar vídeos até baixar de novo.").format(tamanho=size)
        else:
            text = _("Remover {nome} ({tamanho})? Dá para baixar de novo quando quiser.").format(
                nome=_(tool.name), tamanho=size)
        if not self._confirm(_("Remover componente"), text):
            return None
        job = bridge().submit(_remove_fn(tool), _("Remover {nome}").format(nome=_(tool.name)), kind=jobs.CPU,
                              key=job_key(tool_id), data={"tool": tool_id, "acao": "remover",
                                                          "settings": self.settings},
                              on_finished=_after_job)
        card.show_job(job)
        return job

    def pick_ffmpeg_folder(self) -> None:
        d = QFileDialog.getExistingDirectory(self, _("Pasta que contém o ffmpeg e o ffprobe"), media.tool_dir())
        if d:
            self.use_ffmpeg_folder(d)

    def use_ffmpeg_folder(self, folder: str) -> bool:
        """Usa o ffmpeg e o ffprobe de uma pasta (os dois precisam estar nela: `media.configure` sozinho
        cairia no PATH e aceitaria qualquer pasta)."""
        card = self.cards["ffmpeg"]
        exe = ".exe" if sys.platform == "win32" else ""
        found = all((Path(folder) / f"{name}{exe}").is_file() for name in ("ffmpeg", "ffprobe"))
        if found and media.configure(folder):
            self.settings.setValue("ffmpeg_dir", folder)
            card.refresh(tools.status(card.tool, latest=latest_ffmpeg()))
            card.show_message("")
            self.dialog.settings_changed.emit("ffmpeg")
            return True
        media.configure(self.settings.value("ffmpeg_dir", "") or None)
        card.show_message(_("Não encontrei o ffmpeg e o ffprobe nessa pasta."), "danger")
        return False

    def open_resolve_plugin(self) -> None:
        if self.main is not None and hasattr(self.main, "show_resolve"):
            self.main.show_resolve()
            self.refresh("davinci_resolve")

    def install_libraries(self, packages: list[str]) -> jobs.Job | None:
        if bridge().queue.find(PIP_KEY) is not None:
            return None
        if self.btn_pip is not None:
            self.btn_pip.setEnabled(False)
        self.pip_status.setText(_("Instalando bibliotecas…"))
        self.pip_status.setStyleSheet(f"color: {theme.MUTED};")
        self.pip_status.setVisible(True)
        return bridge().submit(lambda j: deps.pip_install(packages), _("Instalar bibliotecas"), kind=jobs.REDE,
                               key=PIP_KEY)

    # ------------------------------------------------------------ diálogos (substituíveis nos testes)
    def _confirm(self, title: str, text: str) -> bool:
        r = QMessageBox.question(self, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                 QMessageBox.StandardButton.No)
        return r == QMessageBox.StandardButton.Yes

    def _consent(self, tool: tools.Tool) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle(_("Licença de {nome}").format(nome=_(tool.name)))
        box.setText(_(tool.consent))
        box.setInformativeText(_("Licença: {licenca} — {url}").format(licenca=_(tool.license), url=tool.license_url))
        ok = box.addButton(_("Aceitar e baixar"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(_("Cancelar"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is ok

    # ------------------------------------------------------------ fila de tarefas
    def _card_for(self, job: jobs.Job) -> ToolCard | None:
        if not job.key.startswith(KEY_PREFIX):
            return None
        return self.cards.get(job.key[len(KEY_PREFIX):])

    def _on_job_changed(self, job: jobs.Job) -> None:
        card = self._card_for(job)
        if card is not None:
            card.show_job(job)

    def _on_job_finished(self, job: jobs.Job) -> None:
        if job.key == LATEST_KEY:
            card = self.cards.get("ffmpeg")
            if card is not None:
                self.refresh("ffmpeg")
                if card.btn_check is not None:
                    card.btn_check.setEnabled(True)
                if job.state == jobs.CONCLUIDO and job.result:
                    card.show_message(_("Versão mais recente publicada: {versao}.").format(versao=job.result))
                else:
                    card.show_message(_("Não foi possível consultar a versão mais recente agora."), "danger")
            return
        if job.key == PIP_KEY:
            self._pip_finished(job)
            return
        card = self._card_for(job)
        if card is None:
            return
        card.job = None
        card.show_job(job)
        self.refresh(card.tool.id)
        name = _(card.tool.name)
        removing = (job.data or {}).get("acao") == "remover"
        if job.state == jobs.CONCLUIDO:
            if removing:
                card.show_message(_("{nome} removido: {tamanho} liberados.").format(
                    nome=name, tamanho=tools.fmt_size(int(job.result or 0))), "ok")
            elif card.tool.backend == "ffmpeg" and media.tool_dir():
                card.show_message(_("ffmpeg instalado e pronto para uso:\n{caminho}").format(
                    caminho=media.tool_dir()), "ok")
            else:
                card.show_message(_("{nome} instalado e pronto para uso.").format(nome=name), "ok")
        elif job.state == jobs.CANCELADO:
            card.show_message(_("Download cancelado."), "muted")
        else:
            card.show_message(job.error or _("Não foi possível concluir."), "danger")
        if card.tool.backend == "ffmpeg" and job.state == jobs.CONCLUIDO:
            self.dialog.settings_changed.emit("ffmpeg")

    def _pip_finished(self, job: jobs.Job) -> None:
        ok, out = job.result if (job.state == jobs.CONCLUIDO and job.result) else (False, job.error)
        if ok:
            self.pip_status.setText(_("Instaladas. Feche e abra o app de novo."))
            self.pip_status.setStyleSheet(f"color: {theme.OK};")
        else:
            self.pip_status.setText(_("Não foi possível instalar.") + "\n\n" + breakable(str(out)[-1500:]))
            self.pip_status.setStyleSheet(f"color: {theme.DANGER};")
            if self.btn_pip is not None:
                self.btn_pip.setEnabled(True)

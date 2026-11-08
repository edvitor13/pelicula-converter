"""A janela "Buscar sons (CC0)…" (1.8, módulo Beta "efeitos_sonoros"; `pelicula/sons_cc0.py`, ARQUITETURA §47).

Aberta pelo "Novo ▸ Buscar sons (CC0)…" da Mídia. Nada vai para a rede até a pessoa clicar em "Buscar". A busca, o
"Ouvir" (baixa a prévia num temporário e toca com o QMediaPlayer) e o "Adicionar à Mídia" (baixa para
`sons_cc0.target_dir`, abre com o ffprobe e põe na Mídia com o crédito na fonte) rodam numa thread de trabalho; a
resposta volta pela ponte de sinais (`_Bridge`) para a thread da interface. `opener` troca o `urlopen` nos testes.
"""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout)

from .. import sons_cc0
from ..i18n import _
from .pages.sons import freesound_key

PREVIEW_DIR = "pelicula_sons_cc0_previa"


def fmt_duration(seconds: float) -> str:
    if seconds <= 0:
        return "–"
    s = int(round(seconds))
    return f"{s // 60}:{s % 60:02d}"


class _Bridge(QObject):
    found = Signal(object, object)          # (resultados, erros)
    fetched = Signal(str, str, object)      # (para quê: "ouvir" | "adicionar", caminho, resultado)
    failed = Signal(str, str)               # (para quê, texto do erro)


class SearchDialog(QDialog):
    """Busca, ouve e põe na Mídia sons CC0 do Openverse (e do Freesound, com a chave)."""

    def __init__(self, win, opener: Callable | None = None):
        super().__init__(win)
        self.setObjectName("janela_sons_cc0")
        self.setWindowTitle(_("Buscar sons livres (CC0)"))
        self.resize(760, 520)
        self.win = win
        self.opener = opener
        self.results: list[sons_cc0.Result] = []
        self.busy = False
        self.player = None
        self._audio_out = None
        self.cancel = threading.Event()
        self.bridge = _Bridge(self)
        self.bridge.found.connect(self._found)
        self.bridge.fetched.connect(self._fetched)
        self.bridge.failed.connect(self._failed)
        settings = getattr(win, "settings", None)
        self.key = freesound_key(settings) if settings is not None else ""

        lay = QVBoxLayout(self)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setObjectName("busca_sons")
        self.query.setPlaceholderText(_("O que procurar (em inglês acha mais: whoosh, rain, door…)"))
        self.query.returnPressed.connect(self.do_search)
        row.addWidget(self.query, 1)
        self.btn_search = QPushButton(_("Buscar"))
        self.btn_search.setObjectName("Primary")
        self.btn_search.clicked.connect(self.do_search)
        row.addWidget(self.btn_search)
        lay.addLayout(row)
        sources = _("Busca no Openverse e no Freesound.") if self.key else _(
            "Busca no Openverse. Com a chave da API do Freesound (Configurações › Sons livres), busca também lá.")
        self.where = QLabel(sources + " " + _("Só sons CC0 (domínio público)."))
        self.where.setObjectName("Muted")
        self.where.setWordWrap(True)
        lay.addWidget(self.where)
        self.list = QTreeWidget()
        self.list.setObjectName("resultados_sons")
        self.list.setHeaderLabels([_("Nome"), _("Autor"), _("Duração"), _("Origem")])
        self.list.setRootIsDecorated(False)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setColumnWidth(0, 300)
        self.list.setColumnWidth(1, 170)
        self.list.setColumnWidth(2, 70)
        self.list.itemSelectionChanged.connect(self._sync)
        self.list.itemDoubleClicked.connect(lambda *_a: self.do_listen())
        lay.addWidget(self.list, 1)
        folder = sons_cc0.target_dir(getattr(win, "project_path", None))
        if getattr(win, "project_path", None):
            dest = _("Os sons adicionados vão para {pasta}, ao lado do projeto.").format(pasta=folder)
        else:
            dest = _("O projeto ainda não foi salvo: os sons adicionados vão para {pasta} (a pasta do app).").format(
                pasta=folder)
        self.note = QLabel(dest + " " + _("Do Freesound vem a prévia de alta qualidade (MP3): o arquivo original "
                                          "pede login. O crédito fica no projeto e vai num .creditos.txt ao lado de "
                                          "cada exportação que usar o som."))
        self.note.setObjectName("Faint")
        self.note.setWordWrap(True)
        lay.addWidget(self.note)
        bottom = QHBoxLayout()
        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        self.btn_listen = QPushButton(_("Ouvir"))
        self.btn_listen.clicked.connect(self.do_listen)
        bottom.addWidget(self.btn_listen)
        self.btn_add = QPushButton(_("Adicionar à Mídia"))
        self.btn_add.setObjectName("Primary")
        self.btn_add.clicked.connect(self.do_add)
        bottom.addWidget(self.btn_add)
        btn_close = QPushButton(_("Fechar"))
        btn_close.clicked.connect(self.reject)
        bottom.addWidget(btn_close)
        lay.addLayout(bottom)
        self._sync()

    # -------------------------------------------------------- estado
    def current(self) -> sons_cc0.Result | None:
        items = self.list.selectedItems()
        if not items:
            return None
        i = items[0].data(0, Qt.ItemDataRole.UserRole)
        return self.results[i] if isinstance(i, int) and 0 <= i < len(self.results) else None

    def _sync(self) -> None:
        has = self.current() is not None
        self.btn_listen.setEnabled(has and not self.busy)
        self.btn_add.setEnabled(has and not self.busy)
        self.btn_search.setEnabled(not self.busy)

    def _start(self, text: str, fn: Callable[[], None]) -> None:
        self.busy = True
        self.status.setText(text)
        self._sync()
        threading.Thread(target=fn, daemon=True, name="sons-cc0").start()

    # -------------------------------------------------------- buscar
    def do_search(self) -> None:
        q = self.query.text().strip()
        if not q or self.busy:
            return
        key, opener = self.key, self.opener

        def run():
            try:
                found, errors = sons_cc0.search(q, key, opener)
            except Exception as exc:  # noqa: BLE001 (nada pode derrubar a thread sem avisar)
                found, errors = [], [str(exc)]
            self.bridge.found.emit(found, errors)

        self._start(_("Buscando “{busca}”…").format(busca=q), run)

    def _found(self, found: list, errors: list) -> None:
        self.busy = False
        self.results = list(found)
        self.list.clear()
        for i, r in enumerate(self.results):
            item = QTreeWidgetItem([r.titulo, r.autor, fmt_duration(r.duracao), r.origin_label])
            item.setData(0, Qt.ItemDataRole.UserRole, i)
            item.setToolTip(0, r.pagina)
            self.list.addTopLevelItem(item)
        if self.results:
            self.list.setCurrentItem(self.list.topLevelItem(0))
        msg = _("{n} sons CC0.").format(n=len(self.results)) if self.results else _("Nenhum som CC0 encontrado.")
        self.status.setText(" ".join([msg, *errors]))
        self._sync()

    # -------------------------------------------------------- ouvir e adicionar
    def _fetch(self, purpose: str, r: sons_cc0.Result) -> None:
        if purpose == "ouvir":
            url, dest, limit = r.previa, Path(tempfile.gettempdir()) / PREVIEW_DIR / sons_cc0.file_name(r), \
                sons_cc0.MAX_PREVIEW
        else:
            url, dest, limit = r.arquivo, sons_cc0.target_dir(getattr(self.win, "project_path", None)) / \
                sons_cc0.file_name(r), sons_cc0.MAX_DOWNLOAD
        opener, cancel = self.opener, self.cancel

        def run():
            try:
                path = sons_cc0.download(url, dest, opener, limit, cancel, r.origin_label)
            except Exception as exc:  # noqa: BLE001
                self.bridge.failed.emit(purpose, str(exc))
                return
            self.bridge.fetched.emit(purpose, path, r)

        text = _("Baixando a prévia de “{nome}”…") if purpose == "ouvir" else _("Baixando “{nome}”…")
        self._start(text.format(nome=r.titulo), run)

    def do_listen(self) -> None:
        r = self.current()
        if r is not None and not self.busy:
            self._fetch("ouvir", r)

    def do_add(self) -> None:
        r = self.current()
        if r is not None and not self.busy:
            self._fetch("adicionar", r)

    def _failed(self, purpose: str, text: str) -> None:
        self.busy = False
        self.status.setText(text)
        self._sync()

    def _fetched(self, purpose: str, path: str, r: sons_cc0.Result) -> None:
        self.busy = False
        self._sync()
        if purpose == "ouvir":
            self.status.setText(_("Tocando “{nome}”.").format(nome=r.titulo))
            self.play(path)
            return
        src = self.add_to_media(path, r)
        if src is None:
            self.status.setText(_("Não deu para abrir {arquivo}.").format(arquivo=path))
        else:
            self.status.setText(_("“{nome}” está na Mídia, com o crédito ({arquivo}).").format(nome=r.titulo,
                                                                                            arquivo=path))

    def add_to_media(self, path: str, r: sons_cc0.Result):
        """Abre o arquivo (ffprobe) e põe na Mídia com o crédito (também na fonte da montagem, se já estava lá)."""
        src = self.win._probe_source(path)
        if src is None:
            return None
        credit = sons_cc0.credit_of(r)
        src.credit = dict(credit)
        same = self.win.model.seq.sources.get(src.path)
        if same is not None:
            same.credit = dict(credit)
        return src

    def play(self, path: str) -> None:
        """Toca a prévia (QMediaPlayer; para o que estava tocando)."""
        from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
        if self.player is None:
            self.player = QMediaPlayer(self)
            self._audio_out = QAudioOutput(self)
            self.player.setAudioOutput(self._audio_out)
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(path))
        self.player.play()

    def done(self, result: int) -> None:  # noqa: D401 (fechar: para a prévia e os downloads)
        self.cancel.set()
        if self.player is not None:
            self.player.stop()
        super().done(result)


def open_dialog(win, opener: Callable | None = None) -> SearchDialog:
    """Abre a janela sem bloquear (a busca roda enquanto a pessoa monta)."""
    dlg = getattr(win, "_sons_cc0_dialog", None)
    if dlg is None:
        dlg = SearchDialog(win, opener)
        win._sons_cc0_dialog = dlg  # a mesma janela (com a última busca) volta ao abrir de novo
    elif not dlg.isVisible():
        dlg.cancel = threading.Event()
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg

"""Janela da fila de exportação com progresso, velocidade e tempo restante."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QDialog, QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ..export import ExportJob, ExportQueue
from . import icons, theme

STATUS = {"aguardando": "Na fila", "exportando": "Exportando", "concluido": "Concluído", "erro": "Erro",
          "cancelado": "Cancelado"}


def _dur(s: float) -> str:
    s = int(max(0, s))
    h, m, sec = s // 3600, s % 3600 // 60, s % 60
    return f"{h}h{m:02d}min" if h else f"{m}min{sec:02d}s" if m else f"{sec}s"


def open_folder(path: str) -> None:
    from .. import system
    system.reveal(path)


class JobRow(QFrame):
    def __init__(self, job: ExportJob, parent=None):
        super().__init__(parent)
        self.job = job
        self.setStyleSheet(f"JobRow {{ background: {theme.PANEL}; border: 1px solid {theme.BORDER}; border-radius: 10px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(6)
        top = QHBoxLayout()
        self.title = QLabel(job.name or Path(job.out_path).name)
        self.title.setStyleSheet("font-weight: 600;")
        top.addWidget(self.title, 1)
        self.state = QLabel()
        top.addWidget(self.state)
        lay.addLayout(top)
        self.path = QLabel(job.out_path)
        self.path.setObjectName("Faint")
        lay.addWidget(self.path)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFixedHeight(8)
        lay.addWidget(self.bar)
        bottom = QHBoxLayout()
        self.info = QLabel()
        self.info.setObjectName("Muted")
        self.info.setWordWrap(True)
        bottom.addWidget(self.info, 1)
        self.cancel = QPushButton("Cancelar")
        self.cancel.setObjectName("Danger")
        self.cancel.clicked.connect(job.cancel.set)
        bottom.addWidget(self.cancel)
        self.open = QPushButton("Abrir pasta")
        self.open.setIcon(icons.icon("folder", theme.TEXT, 16))
        self.open.clicked.connect(lambda: open_folder(job.out_path))
        bottom.addWidget(self.open)
        lay.addLayout(bottom)
        self.refresh()

    def refresh(self) -> None:
        j = self.job
        color = {"concluido": theme.OK, "erro": theme.DANGER, "exportando": theme.ACCENT_HI}.get(j.status, theme.MUTED)
        self.state.setText(STATUS.get(j.status, j.status))
        self.state.setStyleSheet(f"color: {color}; font-weight: 600;")
        self.bar.setValue(int(j.progress * 1000))
        active = j.status in ("aguardando", "exportando")
        self.cancel.setVisible(active)
        self.open.setVisible(j.status == "concluido")
        if j.status == "exportando":
            self.info.setText(f"{j.done} de {j.total} quadros • {j.progress * 100:.1f}% • {j.fps_rate:.1f} quadros/s"
                              f" • faltam {_dur(j.eta)}")
        elif j.status == "concluido":
            self.info.setText(f"{j.total} quadros em {_dur(j.finished - j.started)}")
        elif j.status == "erro":
            self.info.setText(j.error[-600:])
        elif j.status == "cancelado":
            self.info.setText("Exportação cancelada.")
        else:
            self.info.setText("Aguardando a exportação anterior terminar.")


class QueueDialog(QDialog):
    def __init__(self, parent, queue: ExportQueue):
        super().__init__(parent)
        self.queue = queue
        self.setWindowTitle("Fila de exportação")
        self.resize(640, 440)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        k = QLabel("FILA")
        k.setObjectName("Kicker")
        lay.addWidget(k)
        t = QLabel("Exportações")
        t.setObjectName("PanelTitle")
        t.setStyleSheet("font-size: 14pt;")
        lay.addWidget(t)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.inner = QWidget()
        self.vl = QVBoxLayout(self.inner)
        self.vl.setContentsMargins(0, 0, 4, 0)
        self.vl.setSpacing(8)
        self.vl.addStretch(1)
        self.scroll.setWidget(self.inner)
        lay.addWidget(self.scroll, 1)
        self.empty = QLabel("Nenhuma exportação ainda. Use o botão Exportar.")
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.empty)
        row = QHBoxLayout()
        clear = QPushButton("Limpar concluídos")
        clear.clicked.connect(self._clear)
        row.addWidget(clear)
        row.addStretch(1)
        close = QPushButton("Fechar")
        close.clicked.connect(self.close)
        row.addWidget(close)
        lay.addLayout(row)
        self.rows: dict[str, JobRow] = {}
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.refresh)
        self.timer.start()
        self.refresh()

    def _clear(self) -> None:
        self.queue.remove_finished()
        self.refresh()

    def refresh(self) -> None:
        ids = {j.id for j in self.queue.jobs}
        for jid in list(self.rows):
            if jid not in ids:
                self.rows.pop(jid).deleteLater()
        for j in self.queue.jobs:
            if j.id not in self.rows:
                row = JobRow(j)
                self.rows[j.id] = row
                self.vl.insertWidget(self.vl.count() - 1, row)
            self.rows[j.id].refresh()
        self.empty.setVisible(not self.queue.jobs)

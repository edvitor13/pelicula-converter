"""Som de película (1.8, módulo Beta "som_pelicula"; ARQUITETURA §45) na prévia: um ponto só de ligação com a janela.

O cartão "Som de película" é o da seção do look (sai do esquema); o módulo só o esconde (`module_tools`). Aqui fica o
som que a prévia toca: a janela pede um som por `MainWindow._set_audio(tipo, caminho)` (a mixagem da montagem ou o
arquivo aberto) e `route` troca pelo mesmo som já passado por `somfilme.process_wav`, o mesmo motor da exportação
(`export._film_sound`), a partir da amostra 0:

- montagem (modo Edição, ou montagem no modo Película): o WAV da mixagem da prévia, que continua sendo o de
  `audiomix.render_mix` (mudar um ajuste do som de película refaz só este processamento, não a mixagem);
- arquivo direto (modo Película): o som do arquivo decodificado uma vez (`audiomix.decode_wav`, guardado enquanto o
  arquivo é o mesmo) e processado. O medidor de som lê o WAV processado (o mesmo que toca), sem decodificar de novo.

Enquanto processa, a prévia toca o som de sempre; quando fica pronto, troca sem parar a reprodução. Os valores são os
do look em edição (o da sequência aberta, #67), nada no modo Edição sem película e nada com "Desligar todos os
efeitos" — como a imagem. Tudo em segundo plano; o resultado chega por sinal na thread principal.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading

from PySide6.QtCore import QObject, QTimer, Signal

from .. import audiomix, somfilme


class _Bridge(QObject):
    done = Signal(str, str)  # chave do processamento, WAV processado ("" = não deu)


class _Decode:
    """O som do arquivo num WAV (`audiomix.decode_wav`), uma vez: quem chega depois espera o mesmo resultado."""

    def __init__(self, path: str, wav: str):
        self.path, self.wav = path, wav
        self.lock = threading.Lock()
        self.ok: bool | None = None

    def result(self) -> bool:
        with self.lock:
            if self.ok is None:
                self.ok = audiomix.decode_wav(self.path, self.wav)
            return self.ok


class SomPeliculaUI:
    def __init__(self, win):
        self.win = win
        self.raw = ("", "")              # o som que a janela pediu (`_set_audio`)
        self.key = ""                    # chave do WAV processado pronto
        self.path = ""
        self.running: dict[str, str] = {}
        self.files: list[str] = []
        self.decoded: tuple = ((), "", None)  # som do arquivo: ((caminho, data), WAV, _Decode)
        self._token = 0
        self.bridge = _Bridge()
        self.bridge.done.connect(self._done)
        self.timer = QTimer(win)
        self.timer.setSingleShot(True)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.refresh)
        win.store.changed.connect(lambda _key: self.schedule())
        win.model.changed.connect(lambda kind: kind == "markers" or self.schedule())

    # ---------------------------------------------------------------- o que vale
    def values(self) -> dict | None:
        """Os valores do look que valem para o som da prévia (None = o som de sempre)."""
        win = self.win
        if win.mode == "edicao" and not win.edit_film:
            return None
        return somfilme.film_values(win.store.values, win.no_effects)

    def _key(self, kind: str, path: str) -> str:
        v = self.values()
        info = self.win.info
        if v is None or not path or info is None:
            return ""
        seq = self.win.model.seq if (kind == "seq" and self.win.src_seq is not None) else None
        try:
            stamp = os.path.getmtime(path)
        except OSError:
            return ""
        data = [kind, path, stamp, somfilme.sound_key(v), float(info.fps),
                somfilme.events_for(v, info.fps, info.frames, seq)]
        return hashlib.sha1(json.dumps(data).encode("utf-8")).hexdigest()

    # ---------------------------------------------------------------- a janela
    def route(self, kind: str, path: str) -> tuple[str, str]:
        """O som que a prévia toca no lugar de (`kind`, `path`): o WAV processado ("seq": um WAV pronto, que o medidor lê
        direto) ou, desligado ou enquanto processa, o próprio."""
        self.raw = (kind, path)
        key = self._key(kind, path)
        if not key:
            return kind, path
        if key == self.key and self.path and os.path.exists(self.path):
            return "seq", self.path
        self._start(key, kind, path)
        return kind, path

    def schedule(self) -> None:
        self.timer.start()

    def refresh(self) -> None:
        """Um ajuste, a montagem ou o modo mudou: a janela pede o mesmo som de novo e `route` decide."""
        if self.raw[1]:
            self.win._set_audio(*self.raw)

    def cleanup(self) -> None:
        """Janela fechando: apaga os WAVs (o player já soltou)."""
        self.key = self.path = ""
        self._clean(keep="")
        if self.decoded[1]:
            audiomix._remove(self.decoded[1])
            self.decoded = ((), "", None)

    # ---------------------------------------------------------------- em segundo plano
    def _start(self, key: str, kind: str, path: str) -> None:
        if key in self.running:
            return
        win = self.win
        v = dict(self.values())
        fps, frames = float(win.info.fps), int(win.info.frames)
        seq = win.model.seq if (kind == "seq" and win.src_seq is not None) else None
        events = somfilme.events_for(v, fps, frames, seq)
        self._token += 1
        tmp = tempfile.gettempdir()
        out = os.path.join(tmp, f"pelicula_somfilme_previa_{os.getpid()}_{self._token}.wav")
        self.files.append(out)
        self.running[key] = out
        src, job = path, None
        if kind != "seq":  # o som do arquivo, decodificado uma vez enquanto o arquivo é o mesmo
            stamp = (path, os.path.getmtime(path)) if os.path.exists(path) else (path, None)
            if self.decoded[0] != stamp:
                if self.decoded[1]:
                    audiomix._remove(self.decoded[1])
                wav = os.path.join(tmp, f"pelicula_somfilme_arquivo_{os.getpid()}_{self._token}.wav")
                self.decoded = (stamp, wav, _Decode(path, wav))
            src, job = self.decoded[1], self.decoded[2]

        def run():
            ok = False
            try:
                if job is None or job.result():
                    ok = somfilme.process_wav(src, out, v, fps, 0, events)
            except Exception:  # noqa: BLE001
                ok = False
            self.bridge.done.emit(key, out if ok else "")

        threading.Thread(target=run, daemon=True, name="som-pelicula").start()

    def _done(self, key: str, out: str) -> None:
        self.running.pop(key, None)
        if not out or key != self._key(*self.raw):
            if out:
                self._clean(keep=self.path)
            return  # um processamento mais novo está a caminho (ou o som mudou)
        self.key, self.path = key, out
        self.win._set_audio(*self.raw)
        self._clean(keep=out)

    def _clean(self, keep: str) -> None:
        running = set(self.running.values())
        for f in list(self.files):
            if f == keep or f in running:
                continue
            try:
                if os.path.exists(f):
                    os.remove(f)
                self.files.remove(f)
            except OSError:
                pass  # ainda aberto pelo player; tenta de novo depois


def install(win) -> SomPeliculaUI:
    return SomPeliculaUI(win)


def module_tools(win) -> dict[str, list]:
    """O cartão "Som de película" do look (módulo Beta "som_pelicula")."""
    cards = [c for c in win.cards if c.section.key == "som_pelicula"]
    return {"som_pelicula": cards}

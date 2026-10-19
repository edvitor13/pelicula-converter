"""Modelo da linha do tempo para a interface: a sequência atual, a seleção e desfazer/refazer.

Toda edição passa por aqui: o modelo chama `timeline.Sequence`, grava o instantâneo no
histórico e avisa a interface pelo sinal `changed` com o tipo da mudança:

- "structure": clipes ou faixas mudaram (posição, duração, mudo…);
- "values": só os ajustes de um clipe mudaram (cor, som, transição…);
- "settings": resolução, fps ou fundo da sequência;
- "*": a sequência inteira foi trocada (abrir projeto, desfazer, refazer).
"""

from __future__ import annotations

import copy
from typing import Any, Iterable

from PySide6.QtCore import QObject, QTimer, Signal

from .. import editparams, timeline
from ..timeline import AUDIO, VIDEO, Clip, Sequence, Source

TRACK_ATTRS = {"muted", "locked", "solo", "volume", "name"}


class TimelineModel(QObject):
    changed = Signal(str)
    selectionChanged = Signal()
    historyChanged = Signal()

    def __init__(self, seq: Sequence | None = None, parent=None):
        super().__init__(parent)
        self.seq: Sequence = seq if seq is not None else Sequence()
        self.history = timeline.History(self.seq)
        self.selection: list[str] = []
        self.clipboard: dict[str, Any] | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self.commit)

    # ------------------------------------------------------------ estado
    def set_sequence(self, seq: Sequence, reset_history: bool = True) -> None:
        self._timer.stop()
        self.seq = seq
        if reset_history:
            self.history.reset(seq)
        self._filter_selection()
        self.changed.emit("*")
        self.selectionChanged.emit()
        self.historyChanged.emit()

    def commit(self) -> None:
        """Grava o estado atual no histórico (se mudou)."""
        self._timer.stop()
        if self.history.push(self.seq):
            self.historyChanged.emit()

    def can_undo(self) -> bool:
        return self.history.can_undo() or self._timer.isActive()

    def can_redo(self) -> bool:
        return self.history.can_redo()

    def _restore(self, seq: Sequence | None) -> None:
        if seq is None:
            return
        self.seq = seq
        self._filter_selection()
        self.changed.emit("*")
        self.selectionChanged.emit()
        self.historyChanged.emit()

    def undo(self) -> None:
        self.commit()
        self._restore(self.history.undo())

    def redo(self) -> None:
        self.commit()
        self._restore(self.history.redo())

    def _done(self, kind: str = "structure") -> None:
        self._filter_selection(emit=True)
        self.commit()
        self.changed.emit(kind)

    # ------------------------------------------------------------ seleção
    def _filter_selection(self, emit: bool = False) -> None:
        ids = {c.id for c in self.seq.clips}
        new = [i for i in self.selection if i in ids]
        if new != self.selection:
            self.selection = new
            if emit:
                self.selectionChanged.emit()

    def select(self, ids: Iterable[str]) -> None:
        known = {c.id for c in self.seq.clips}
        new: list[str] = []
        for i in ids:
            if i in known and i not in new:
                new.append(i)
        if new != self.selection:
            self.commit()
            self.selection = new
            self.selectionChanged.emit()

    def select_group(self, cid: str, add: bool = False, toggle: bool = False) -> None:
        """Seleciona o clipe e os ligados a ele (o clicado vem primeiro)."""
        c = self.seq.find(cid)
        if c is None:
            return
        group = [cid] + [g.id for g in self.seq.group(c) if g.id != cid]
        if toggle and cid in self.selection:
            self.select([i for i in self.selection if i not in group])
        elif add or toggle:
            self.select(self.selection + [g for g in group if g not in self.selection])
        else:
            self.select(group)

    def selected_clips(self) -> list[Clip]:
        out = []
        for i in self.selection:
            c = self.seq.find(i)
            if c is not None:
                out.append(c)
        return out

    def primary(self) -> Clip | None:
        clips = self.selected_clips()
        return clips[0] if clips else None

    # ------------------------------------------------------------ edição
    def insert_media(self, src: Source, at: int | None = None, vtrack: int = 0, atrack: int = 0) -> list[Clip]:
        made = self.seq.insert_media(src, at, vtrack, atrack)
        if made:
            self.selection = [c.id for c in made]
            self.selectionChanged.emit()
        self._done("structure")
        return made

    def split_at(self, frame: int) -> list[str]:
        """Divide os clipes selecionados no quadro (ou todos sob o cursor, sem seleção)."""
        ids = list(self.selection) or None
        made = self.seq.split(int(frame), ids)
        if made:
            self._done("structure")
        return made

    def split_clip(self, cid: str, frame: int) -> list[str]:
        """Divide um clipe (e os ligados) no quadro — usado pela ferramenta Lâmina."""
        made = self.seq.split(int(frame), [cid])
        if made:
            self._done("structure")
        return made

    def delete_selected(self, ripple: bool = False) -> None:
        if not self.selection:
            return
        self.seq.delete(list(self.selection), ripple=ripple)
        self.selection = []
        self.selectionChanged.emit()
        self._done("structure")

    def delete_clips(self, ids: Iterable[str], ripple: bool = False) -> None:
        ids = list(ids)
        if not ids:
            return
        self.seq.delete(ids, ripple=ripple)
        self._done("structure")

    def move_clip(self, cid: str, start: int, track: int | None = None) -> int:
        c = self.seq.find(cid)
        if c is None:
            return 0
        before = (c.start, c.track)
        delta = self.seq.move(cid, int(start), track)
        if (c.start, c.track) != before or delta:
            self._done("structure")
        return delta

    def trim_start(self, cid: str, frame: int) -> int:
        delta = self.seq.trim_start(cid, int(frame))
        if delta:
            self._done("structure")
        return delta

    def trim_end(self, cid: str, frame: int) -> int:
        delta = self.seq.trim_end(cid, int(frame))
        if delta:
            self._done("structure")
        return delta

    def set_clip_values(self, cid: str, values: dict[str, Any], record: bool = True) -> None:
        """Troca os ajustes do clipe. `record=False` (arrastando um slider) agrupa o histórico em 400 ms."""
        c = self.seq.find(cid)
        if c is None:
            return
        before = (c.start, c.dur, c.speed)
        old = copy.deepcopy(c.values)
        self.seq.set_values(cid, values)
        if c.values == old and (c.start, c.dur, c.speed) == before:
            return
        kind = "structure" if (c.start, c.dur, c.speed) != before else "values"
        if record:
            self.commit()
        else:
            self._timer.start()
        self.changed.emit(kind)
        if not record:
            self.historyChanged.emit()

    def set_speed(self, cid: str, speed: float) -> None:
        self.seq.set_speed(cid, speed)
        self._done("structure")

    def apply_look(self, cid: str, look: dict[str, Any]) -> None:
        """Ajuste rápido: zera a cor e a luz do clipe e aplica os valores do look."""
        c = self.seq.find(cid)
        if c is None or c.kind != VIDEO:
            return
        defaults = editparams.VIDEO.defaults()
        vals = dict(c.values)
        for k in editparams.color_keys():
            vals[k] = copy.deepcopy(defaults[k])
        vals.update(look)
        self.set_clip_values(cid, vals)

    def reset_color(self, cid: str) -> None:
        self.apply_look(cid, {})

    def reset_values(self, cid: str) -> None:
        """Todos os ajustes do clipe de volta ao padrão (a velocidade também)."""
        c = self.seq.find(cid)
        if c is None:
            return
        self.set_clip_values(cid, editparams.SCHEMAS[c.kind].defaults())

    def unlink_selected(self) -> None:
        changed = False
        for c in self.selected_clips():
            if c.link:
                self.seq.unlink(c.id)
                changed = True
        if changed:
            self._done("structure")

    def link_selected(self) -> None:
        clips = self.selected_clips()
        if len(clips) >= 2:
            self.seq.link([c.id for c in clips])
            self._done("structure")

    def selection_linked(self) -> bool:
        return any(c.link for c in self.selected_clips())

    # ------------------------------------------------------------ faixas
    def add_track(self, kind: str) -> int:
        idx = self.seq.add_track(kind)
        self._done("structure")
        return idx

    def remove_track(self, kind: str, idx: int) -> None:
        if len(self.seq.kind_tracks(kind)) <= 1:
            return
        self.seq.remove_track(kind, idx)
        self._done("structure")

    def close_gaps(self, kind: str, idx: int) -> None:
        """Junta os clipes da faixa, sem espaços entre eles."""
        self.seq.close_gaps(kind, idx)
        self._done("structure")

    def set_track(self, kind: str, idx: int, **attrs) -> None:
        tr = self.seq.track(kind, idx)
        if tr is None:
            return
        changed = False
        for k, v in attrs.items():
            if k not in TRACK_ATTRS:
                raise KeyError(k)
            if k == "volume":
                v = min(max(float(v), -60.0), 12.0)
            if getattr(tr, k) != v:
                setattr(tr, k, v)
                changed = True
        if changed:
            self._done("structure")

    # ------------------------------------------------------------ sequência
    def set_settings(self, width: int, height: int, fps_str: str, background=None) -> None:
        """Resolução, fps e fundo. Ao mudar o fps, os clipes mantêm o tempo (em segundos)."""
        seq = self.seq
        old_fps = seq.fps
        fr = timeline.parse_fps(fps_str)
        seq.width = max(16, int(width))
        seq.height = max(16, int(height))
        seq.fps_str = f"{fr.numerator}/{fr.denominator}"
        if background is not None:
            seq.background = tuple(min(max(float(x), 0.0), 1.0) for x in list(background)[:3])
        new_fps = seq.fps
        if abs(new_fps - old_fps) > 1e-9:
            ratio = new_fps / old_fps
            for c in seq.clips:
                c.start = int(round(c.start * ratio))
                c.dur = max(1, int(round(c.dur * ratio)))
            for c in seq.clips:
                c.dur = max(1, min(c.dur, seq.max_dur(c)))
        self._done("settings")

    # ------------------------------------------------------------ copiar ajustes
    def copy_values(self, cid: str) -> bool:
        c = self.seq.find(cid)
        if c is None or c.kind != VIDEO:
            return False
        self.clipboard = {k: copy.deepcopy(c.values[k]) for k in editparams.color_keys()}
        return True

    def has_clipboard(self) -> bool:
        return bool(self.clipboard)

    def paste_values(self, ids: Iterable[str]) -> int:
        if not self.clipboard:
            return 0
        n = 0
        for cid in ids:
            c = self.seq.find(cid)
            if c is None or c.kind != VIDEO:
                continue
            vals = dict(c.values)
            vals.update(copy.deepcopy(self.clipboard))
            self.seq.set_values(cid, vals)
            n += 1
        if n:
            self._done("values")
        return n

    def apply_values_to_all(self, cid: str) -> int:
        """Copia a cor e a luz deste clipe para todos os outros clipes de vídeo."""
        if not self.copy_values(cid):
            return 0
        return self.paste_values([c.id for c in self.seq.clips if c.kind == VIDEO and c.id != cid])

    def kinds_selected(self) -> set[str]:
        return {c.kind for c in self.selected_clips()}


__all__ = ["TimelineModel", "VIDEO", "AUDIO"]

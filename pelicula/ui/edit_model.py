"""Modelo da linha do tempo para a interface: a sequência atual, a seleção e desfazer/refazer.

Toda edição passa por aqui: o modelo chama `timeline.Sequence`, grava o instantâneo no
histórico e avisa a interface pelo sinal `changed` com o tipo da mudança:

- "structure": clipes ou faixas mudaram (posição, duração, mudo…);
- "values": só os ajustes de um clipe mudaram (cor, som, transição…);
- "settings": resolução, fps, fundo, fades curtos nas emendas de som ou faixa principal magnética;
- "markers": só os marcadores mudaram (a imagem e o som não mudam: a prévia não recarrega),
  inclusive ao desfazer/refazer uma mudança só de marcadores;
- "*": a sequência inteira foi trocada (abrir projeto, desfazer, refazer).

A seleção de clipes (`selection`) e a de um marcador (`marker_sel`) não convivem: escolher um tira o
outro, e "Excluir" apaga o que estiver selecionado.

Toda edição que mexe na estrutura passa por `Sequence.keep_main()`: com a faixa principal magnética ligada,
a V1 fica sem buracos depois dela e o resto acompanha (`Sequence.settle_main`); sem ela, nada muda.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable

from PySide6.QtCore import QObject, QTimer, Signal

from .. import editparams, timeline, timemap
from ..timeline import AUDIO, VIDEO, Clip, Sequence, Source

FREEZE_SECONDS = 2.0  # duração padrão de "Congelar este quadro"

TRACK_ATTRS = {"muted", "locked", "solo", "volume", "name"}
AUDIO_TRANSITION_S = 1.0  # duração padrão da transição de som criada pelo menu do corte


def _without_markers(seq: Sequence) -> dict[str, Any]:
    d = seq.to_json()
    d.pop("marcadores", None)
    return d


class TimelineModel(QObject):
    changed = Signal(str)
    selectionChanged = Signal()
    historyChanged = Signal()

    def __init__(self, seq: Sequence | None = None, parent=None):
        super().__init__(parent)
        self.seq: Sequence = seq if seq is not None else Sequence()
        self.history = timeline.History(self.seq)
        self.selection: list[str] = []
        self.marker_sel: str | None = None   # marcador selecionado (id)
        self.clipboard: dict[str, Any] | None = None
        self.clipboard_keys: dict[str, list] = {}  # chaves da cor copiadas (tempo a partir do começo do clipe)
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
        only_markers = _without_markers(seq) == _without_markers(self.seq)
        self.seq = seq
        self._filter_selection()
        self.changed.emit("markers" if only_markers else "*")  # desfazer um marcador não recarrega a prévia
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
        marker = self.marker_sel if self.marker_sel and self.seq.marker(self.marker_sel) else None
        if new != self.selection or marker != self.marker_sel:
            self.selection = new
            self.marker_sel = marker
            if emit:
                self.selectionChanged.emit()

    def select(self, ids: Iterable[str]) -> None:
        known = {c.id for c in self.seq.clips}
        new: list[str] = []
        for i in ids:
            if i in known and i not in new:
                new.append(i)
        if new != self.selection or self.marker_sel is not None:
            self.commit()
            self.selection = new
            self.marker_sel = None
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
    def insert_media(self, src: Source, at: int | None = None, vtrack: int = 0, atrack: int = 0,
                     insert: bool = False) -> list[Clip]:
        """Põe o arquivo na montagem; `insert` (com um ponto `at`) empurra o resto em vez de sobrescrever."""
        with self.seq.keep_main():
            made = self.seq.insert_media(src, at, vtrack, atrack, insert=insert)
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

    def _delete(self, ids: list[str], ripple: bool) -> None:
        seq = self.seq
        if ripple and seq._magnet_owns(seq.expand(ids)):
            ripple = False  # V1 magnética: ela mesma fecha o espaço e o resto acompanha a imagem
        with seq.keep_main():
            seq.delete(ids, ripple=ripple)

    def delete_selected(self, ripple: bool = False) -> None:
        if self.marker_sel is not None:
            self.remove_marker(self.marker_sel)
            return
        if not self.selection:
            return
        self._delete(list(self.selection), ripple)
        self.selection = []
        self.selectionChanged.emit()
        self._done("structure")

    def delete_clips(self, ids: Iterable[str], ripple: bool = False) -> None:
        ids = list(ids)
        if not ids:
            return
        self._delete(ids, ripple)
        self._done("structure")

    def move_clip(self, cid: str, start: int, track: int | None = None, insert: bool = False) -> int:
        """Move o clipe (e os ligados); `insert` abre espaço no destino em vez de sobrescrever."""
        c = self.seq.find(cid)
        if c is None:
            return 0
        before = self.history._dump(self.seq) if self.seq.magnetic else (c.start, c.track)
        with self.seq.keep_main():
            delta = (self.seq.move_insert if insert else self.seq.move)(cid, int(start), track)
        after = self.history._dump(self.seq) if self.seq.magnetic else (c.start, c.track)
        if after != before or delta:
            self._done("structure")
        return delta

    def trim_start(self, cid: str, frame: int, solo: bool = False) -> int:
        """Apara o começo; `solo` (Alt) apara só este clipe, sem o ligado (corte J/L)."""
        seq = self.seq
        with seq.keep_main():
            if solo:
                delta = seq.trim_start_only(cid, int(frame))
            else:
                delta = seq.trim_start(cid, seq.room_for_start(cid, int(frame)))
        if delta:
            self._done("structure")
        return delta

    def trim_end(self, cid: str, frame: int, solo: bool = False) -> int:
        """Apara o fim; `solo` (Alt) apara só este clipe, sem o ligado (corte J/L)."""
        seq = self.seq
        with seq.keep_main():
            if solo:
                delta = seq.trim_end_only(cid, int(frame))
            else:
                seq.room_for_end(cid, int(frame))
                delta = seq.trim_end(cid, int(frame))
        if delta:
            self._done("structure")
        return delta

    def trim_to_playhead(self, frame: int, side: str) -> int:
        """Q (`side="start"`) / W (`"end"`): apara até o cursor o clipe sob ele — na faixa do clipe selecionado,
        senão na faixa destravada mais de cima — e fecha o espaço. Devolve os quadros tirados (0 = nada)."""
        prim = self.primary()
        target = self.seq.trim_target(int(frame), (prim.kind, prim.track) if prim is not None else None)
        if target is None:
            return 0
        with self.seq.keep_main():
            if side == "start":
                n = self.seq.ripple_trim_start(target.id, int(frame))
            else:
                n = self.seq.ripple_trim_end(target.id, int(frame))
        if n:
            self._done("structure")
        return n

    def split_edit(self, cid: str, left: bool, offset: int) -> int | None:
        """Corte J (`offset` < 0) / L (> 0) / alinhado (0) no corte do começo (`left`) ou do fim do par ligado
        de `cid`. Devolve o deslocamento que coube (None: ali não há um corte entre dois pares ligados)."""
        before = self.history._dump(self.seq)
        with self.seq.keep_main():
            got = self.seq.split_edit(cid, left, int(offset))
        if got is not None and self.history._dump(self.seq) != before:
            self._done("structure")
        return got

    def set_clip_values(self, cid: str, values: dict[str, Any], record: bool = True) -> None:
        """Troca os ajustes do clipe. `record=False` (arrastando um slider) agrupa o histórico em 400 ms."""
        c = self.seq.find(cid)
        if c is None:
            return
        before = (c.start, c.dur, c.speed)
        old = copy.deepcopy(c.values)
        speed = values.get("velocidade", c.speed) if isinstance(values, dict) else c.speed
        if self.seq.magnetic and abs(float(speed) - c.speed) > 1e-9:
            whole = self.history._dump(self.seq)
            with self.seq.keep_main():  # V1 magnética: mais lento empurra o resto, mais rápido puxa
                self.seq.room_for_speed(cid, float(speed))
                self.seq.set_values(cid, values)
            if self.history._dump(self.seq) != whole:
                before = None
        else:
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
        with self.seq.keep_main():
            self.seq.room_for_speed(cid, speed)
            self.seq.set_speed(cid, speed)
        self._done("structure")

    # ------------------------------------------------------------ tempo: rampa, reverso
    def set_ramp(self, cid: str, ramp) -> bool:
        """Troca a rampa de velocidade do clipe (e dos ligados do mesmo arquivo): um passo do desfazer."""
        return self._retime(cid, ramp=ramp)

    def apply_ramp_preset(self, cid: str, preset: str, amount: float = timemap.AMOUNT_DEFAULT,
                          ramp_s: float = timemap.RAMP_S_DEFAULT) -> bool:
        """Rampa pronta (`timemap.PRESETS`) no trecho do arquivo que o clipe mostra agora."""
        c = self.seq.find(cid)
        if c is None or self.seq._holds(c):
            return False
        lo, hi = self.seq.source_range(c)
        return self.set_ramp(cid, timemap.preset_anchors(preset, lo, hi, c.reverse, amount, ramp_s))

    def freeze_frame(self, cid: str | None, frame: int, seconds: float = FREEZE_SECONDS,
                     insert: bool = True) -> str | None:
        """"Congelar este quadro" (`Sequence.freeze_frame`): um passo do desfazer; o quadro parado fica escolhido."""
        with self.seq.keep_main():
            hold = self.seq.freeze_frame(cid, int(frame), self.seq.frames_for(max(0.04, float(seconds))), insert)
        if hold is None:
            return None
        self.selection = [hold.id]
        self.selectionChanged.emit()
        self._done("structure")
        return hold.id

    def set_reverse(self, cid: str, on: bool) -> bool:
        """Liga/desliga o reverso do clipe (e dos ligados do mesmo arquivo, o som junto): um passo do desfazer."""
        return self._retime(cid, reverse=bool(on))

    def _retime(self, cid: str, ramp=None, reverse=None) -> bool:
        before = self.history._dump(self.seq)
        with self.seq.keep_main():
            self.seq.room_for_retime(cid, ramp=ramp, reverse=reverse)
            self.seq.retime(cid, ramp=ramp, reverse=reverse)
        if self.history._dump(self.seq) == before:
            return False
        self._done("structure")
        return True

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
        self.seq.settle_main()  # a faixa que virou V1 também fica sem buracos (se ela for magnética)
        self._done("structure")

    def close_gaps(self, kind: str, idx: int) -> None:
        """Junta os clipes da faixa, sem espaços entre eles."""
        with self.seq.keep_main():
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
    def set_settings(self, width: int, height: int, fps_str: str, background=None,
                     micro_fade: bool | None = None, magnetic: bool | None = None) -> None:
        """Resolução, fps, fundo, fades curtos nas emendas de som e faixa principal magnética. Ao mudar o fps,
        os clipes mantêm o tempo (em segundos); ao ligar a faixa magnética, a V1 se fecha na hora."""
        seq = self.seq
        if micro_fade is not None:
            seq.micro_fade = bool(micro_fade)
        if magnetic is not None:
            seq.magnetic = bool(magnetic)
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
                c.rescale_keys(ratio)  # chaves de animação no tempo novo
            for c in seq.clips:
                c.dur = max(1, min(c.dur, seq.max_dur(c)))
            for mk in seq.markers:
                mk.frame = int(round(mk.frame * ratio))
        seq.settle_main()
        self._done("settings")

    # ------------------------------------------------------------ transição de som
    def set_audio_transition(self, cid: str, seconds: float) -> float:
        """Transição de som (potência constante) entre o clipe anterior da faixa e `cid`; 0 tira. Os fades
        dos dois clipes nesse corte são zerados (a transição toma o lugar deles), num passo só do
        desfazer. Devolve a duração que cabe com o arquivo que sobra além do corte (pode ser menor)."""
        c = self.seq.find(cid)
        if c is None or c.kind != AUDIO or self.seq.locked(c):
            return 0.0
        seconds = max(0.0, float(seconds))
        vals = dict(c.values)
        vals["transicao"] = seconds
        if seconds > 0:
            vals["fade_in"] = 0.0
            prev = self.seq.previous_on_track(c)
            if prev is not None and float(prev.values.get("fade_out", 0.0)) > 0:
                self.seq.set_values(prev.id, {**prev.values, "fade_out": 0.0})
        self.seq.set_values(cid, vals)
        self._done("values")
        _prev, before, after = self.seq.audio_crossfade(c)
        return before + after

    # ------------------------------------------------------------ marcadores
    def select_marker(self, mid: str | None) -> None:
        """Seleciona um marcador (tira a seleção de clipes); None tira a seleção do marcador."""
        mid = mid if mid and self.seq.marker(mid) is not None else None
        if mid == self.marker_sel and (mid is None or not self.selection):
            return
        self.commit()
        self.marker_sel = mid
        if mid is not None:
            self.selection = []
        self.selectionChanged.emit()

    def selected_marker(self):
        return self.seq.marker(self.marker_sel) if self.marker_sel else None

    def add_marker(self, frame: int, **fields):
        """Marcador no quadro (ou o que já existe ali), já selecionado."""
        n = len(self.seq.markers)
        mk = self.seq.add_marker(int(frame), **fields)
        self.select_marker(mk.id)
        if len(self.seq.markers) != n:
            self._done("markers")
        return mk

    def update_marker(self, mid: str, **fields) -> None:
        if self.seq.update_marker(mid, **fields):
            self._done("markers")

    def move_marker(self, mid: str, frame: int) -> None:
        self.update_marker(mid, frame=int(frame))

    def remove_marker(self, mid: str) -> None:
        if self.seq.remove_marker(mid):
            if self.marker_sel == mid:
                self.marker_sel = None
                self.selectionChanged.emit()
            self._done("markers")

    def clear_markers(self) -> None:
        if self.seq.markers:
            self.seq.markers = []
            self.marker_sel = None
            self.selectionChanged.emit()
            self._done("markers")

    # ------------------------------------------------------------ chaves de animação (keyframes.py)
    # Tempos em quadros da sequência; cada mudança é um passo do desfazer. A interface da linha do tempo
    # para as chaves fica para depois: estas funções são a API dela.
    def keys_of(self, cid: str, key: str) -> list[tuple[float, Any, str]]:
        """Chaves de um ajuste do clipe: [(quadro da sequência, valor, curva)]."""
        c = self.seq.find(cid)
        return self.seq.keys_of(c, key) if c is not None else []

    def value_at(self, cid: str, key: str, frame: float) -> Any:
        """O valor do ajuste no quadro (com as chaves; sem elas, o valor fixo do clipe)."""
        c = self.seq.find(cid)
        if c is None:
            raise KeyError(cid)
        return self.seq.values_at(c, frame)[key]

    def add_key(self, cid: str, key: str, frame: float, value: Any = None, easing: str = "linear",
                record: bool = True) -> bool:
        """Chave no quadro (`value` None = o valor que o ajuste tem ali). Mesmo quadro = troca a chave.
        `record=False` (a chave automática de um slider arrastado) agrupa o histórico em 400 ms."""
        if not self.seq.set_key(cid, key, frame, value, easing):
            return False
        if record:
            self._done("values")
        else:
            self._timer.start()
            self.changed.emit("values")
            self.historyChanged.emit()
        return True

    def move_key(self, cid: str, key: str, frame_from: float, frame_to: float) -> bool:
        if self.seq.move_key(cid, key, frame_from, frame_to):
            self._done("values")
            return True
        return False

    def remove_key(self, cid: str, key: str, frame: float) -> bool:
        if self.seq.remove_key(cid, key, frame):
            self._done("values")
            return True
        return False

    def move_keys(self, cid: str, moves: Iterable[tuple[str, float, float]]) -> bool:
        """Chaves de vários ajustes do clipe andando juntas ([(ajuste, de, para)]): um passo do desfazer."""
        by_key: dict[str, list[tuple[float, float]]] = {}
        for key, a, b in moves:
            by_key.setdefault(key, []).append((a, b))
        changed = False
        for key, pairs in by_key.items():
            changed = self.seq.move_keys(cid, key, pairs) or changed
        if changed:
            self._done("values")
        return changed

    def remove_keys(self, cid: str, items: Iterable[tuple[str, float]]) -> bool:
        """Apaga várias chaves do clipe ([(ajuste, quadro)]) num passo do desfazer."""
        changed = False
        for key, t in items:
            changed = self.seq.remove_key(cid, key, t) or changed
        if changed:
            self._done("values")
        return changed

    def clear_keys(self, cid: str, key: str | None = None) -> bool:
        """Tira a animação de um ajuste (ou de todos, com `key` None)."""
        if self.seq.clear_keys(cid, key):
            self._done("values")
            return True
        return False

    # ------------------------------------------------------------ copiar ajustes
    def copy_values(self, cid: str) -> bool:
        c = self.seq.find(cid)
        if c is None or c.kind != VIDEO:
            return False
        self.clipboard = {k: copy.deepcopy(c.values[k]) for k in editparams.color_keys()}
        # A animação da cor vai junto, presa ao começo do clipe (`Sequence.local_keys`).
        self.clipboard_keys = self.seq.local_keys(c, editparams.color_keys())
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
            self.seq.paste_keys(cid, self.clipboard_keys, editparams.color_keys())
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

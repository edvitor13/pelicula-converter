"""Editor de títulos (`pelicula/titles.py`), no alto do inspetor quando o clipe escolhido é um título.

Texto, estilo pronto, letra (fonte, peso, itálico, tamanho em px@1080, cor, alinhamento, entrelinha), contorno e
sombra, caixa, posição e animações de entrada e saída. Cada mudança vai para `TimelineModel.set_source_data`
(desfazer; digitar ou arrastar agrupa em 400 ms) e a prévia é o player de sempre: o que se vê é o que sai na
exportação. Os controles são os dos ajustes (`SectionCard` com um `params.Schema`); as chaves do estilo são as do
JSON de `textrender.TextStyle`. Avisa quando a fonte não tem algum caractere do texto (`titles.missing`).
"""

from __future__ import annotations

import copy

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QVBoxLayout, QWidget

from .. import params, textrender, titles
from ..i18n import N_, _
from ..textrender import TextStyle, color_hex, parse_color
from ..timeline import VIDEO
from . import generators_ui
from .edit_model import TimelineModel
from .store import ParamStore
from .widgets import SectionCard

WEIGHTS = [("400", N_("Normal")), ("700", N_("Negrito")), ("900", N_("Extranegrito"))]
ALIGN_LABELS = [("esquerda", N_("Esquerda")), ("centro", N_("Centro")), ("direita", N_("Direita"))]
BOX_MODES = [("linha", N_("Uma por linha")), ("bloco", N_("Uma para o texto todo"))]
STYLE_KEYS = ("fonte", "peso", "italico", "tamanho", "cor", "alinhamento", "entrelinha", "espacamento", "largura",
              "maiusculas", "contorno", "cor_contorno", "sombra", "cor_sombra", "sombra_desfoque", "caixa",
              "cor_caixa", "caixa_margem", "caixa_modo")
COLOR_KEYS = ("cor", "cor_contorno", "cor_sombra", "cor_caixa")
TITLE_KEYS = ("pos_x", "pos_y", "entrada", "dur_entrada", "saida", "dur_saida")

# O "Título…" do menu "Novo" da Mídia.
generators_ui.EXTRA_ITEMS.append((
    "titulo", N_("Título…"), N_("Um texto por cima do vídeo, com estilos prontos e animações de entrada e saída."),
    lambda seq: titles.new_source(seq)))


def _schema() -> params.Schema:
    P = params
    fonts = [(f.id, f.name) for f in textrender.FAMILIES]
    anims = [(a, label) for a, label in titles.ANIMATIONS]
    return P.Schema([
        P.Section("letra", N_("Letra"), None, [
            P.C("fonte", N_("Fonte"), textrender.DEFAULT_FAMILY, fonts,
                N_("Fontes que vêm com o app (licença livre): o título sai igual em qualquer computador.")),
            P.C("peso", N_("Peso"), "400", WEIGHTS, N_("Usa o mais perto que a fonte tem.")),
            P.B("italico", N_("Itálico"), False),
            P.F("tamanho", N_("Tamanho"), 54.0, 8.0, 600.0, 1.0, 0, " px",
                N_("Em pixels de um quadro de 1080 linhas (acompanha a resolução).")),
            P.COR("cor", N_("Cor do texto"), (1.0, 1.0, 1.0)),
            P.C("alinhamento", N_("Alinhamento"), "centro", ALIGN_LABELS),
            P.F("entrelinha", N_("Entrelinha"), 1.0, 0.5, 3.0, 0.05, 2, "×"),
            P.F("espacamento", N_("Espaço entre letras"), 0.0, -20.0, 100.0, 0.5, 1, " px"),
            P.F("largura", N_("Largura máxima"), 0.0, 0.0, 3840.0, 10.0, 0, " px",
                N_("Quebra as linhas nesta largura (px de um quadro de 1080 linhas). 0 = só onde há Enter.")),
            P.B("maiusculas", N_("Maiúsculas"), False),
        ]),
        P.Section("contorno", N_("Contorno e sombra"), None, [
            P.F("contorno", N_("Contorno"), 0.0, 0.0, 20.0, 0.5, 1, " px", N_("Espessura do contorno (0 = sem).")),
            P.COR("cor_contorno", N_("Cor do contorno"), (0.0, 0.0, 0.0)),
            P.F("sombra", N_("Sombra"), 0.0, 0.0, 1.0, percent=True, tip=N_("Opacidade da sombra (0 = sem).")),
            P.COR("cor_sombra", N_("Cor da sombra"), (0.0, 0.0, 0.0)),
            P.F("sombra_desfoque", N_("Desfoque da sombra"), 4.0, 0.0, 40.0, 0.5, 1, " px"),
        ]),
        P.Section("caixa", N_("Caixa"), None, [
            P.F("caixa", N_("Caixa"), 0.0, 0.0, 1.0, percent=True,
                tip=N_("Opacidade da caixa atrás do texto (0 = sem caixa).")),
            P.COR("cor_caixa", N_("Cor da caixa"), (0.0, 0.0, 0.0)),
            P.F("caixa_margem", N_("Margem da caixa"), 10.0, 0.0, 120.0, 1.0, 0, " px"),
            P.C("caixa_modo", N_("Caixas"), "linha", BOX_MODES),
        ]),
        P.Section("posicao", N_("Posição"), None, [
            P.F("pos_x", N_("Horizontal"), 0.5, 0.0, 1.0, percent=True,
                tip=N_("Onde fica a borda esquerda, o centro ou a borda direita do texto, conforme o alinhamento.")),
            P.F("pos_y", N_("Vertical"), 0.5, 0.0, 1.0, percent=True, tip=N_("Onde fica o meio do texto.")),
        ]),
        P.Section("animacao", N_("Animação"), None, [
            P.C("entrada", N_("Entrada"), "nenhuma", anims,
                N_("Como o título aparece no começo do clipe. \"Créditos rolando\" sobe o texto durante o clipe "
                   "inteiro.")),
            P.F("dur_entrada", N_("Duração da entrada"), 0.6, 0.0, 10.0, 0.05, 2, " s"),
            P.C("saida", N_("Saída"), "nenhuma", anims, N_("Como o título some no fim do clipe.")),
            P.F("dur_saida", N_("Duração da saída"), 0.6, 0.0, 10.0, 0.05, 2, " s"),
        ]),
    ])


def to_store(data: dict) -> dict:
    """`Source.data` do título → valores dos controles."""
    t = titles.title_of(data)
    st = t.style.to_json()
    out = {}
    for k in STYLE_KEYS:
        v = st.get(k)
        if k in COLOR_KEYS:
            v = list(parse_color(v))
        elif k == "peso":
            v = min(("400", "700", "900"), key=lambda w: abs(int(w) - int(v)))
        out[k] = v
    out.update(pos_x=t.pos_x, pos_y=t.pos_y, entrada=t.enter, dur_entrada=t.enter_s, saida=t.leave,
               dur_saida=t.leave_s)
    return out


def from_store(values: dict, data: dict) -> dict:
    """Valores dos controles → `Source.data` (o texto, o nome e o que o editor não mostra ficam como estavam)."""
    out = copy.deepcopy(dict(data))
    st = dict(TextStyle.from_json(out.get("estilo")).to_json())
    for k in STYLE_KEYS:
        if k not in values:
            continue
        v = values[k]
        if k in COLOR_KEYS:
            v = color_hex(parse_color(v))
        elif k == "peso":
            v = int(v)
        st[k] = v
    out["estilo"] = TextStyle.from_json(st).to_json()
    for k in TITLE_KEYS:
        if k in values:
            out[k] = values[k]
    return out


class TitleEditor(QWidget):
    """O título do clipe escolhido: texto, estilo pronto e os controles; escondido para os outros clipes."""

    def __init__(self, model: TimelineModel, parent=None):
        super().__init__(parent)
        self.model = model
        self.path: str | None = None
        self._loading = False
        self.allowed = True  # módulo "Títulos e geradores" ligado (`set_allowed`)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        k = QLabel(_("TÍTULO"))
        k.setObjectName("Kicker")
        lay.addWidget(k)
        self.text = QPlainTextEdit()
        self.text.setObjectName("titulo_texto")
        self.text.setPlaceholderText(_("Escreva o título (Enter quebra a linha)"))
        self.text.setFixedHeight(84)
        self.text.textChanged.connect(self._text_changed)
        lay.addWidget(self.text)
        self.warn = QLabel()
        self.warn.setObjectName("Faint")
        self.warn.setWordWrap(True)
        self.warn.setVisible(False)
        lay.addWidget(self.warn)
        row = QHBoxLayout()
        row.setSpacing(6)
        lab = QLabel(_("Estilo pronto"))
        lab.setObjectName("Muted")
        row.addWidget(lab)
        self.preset = QComboBox()
        self.preset.addItem(_("Escolher…"), "")
        for p in titles.PRESETS:
            self.preset.addItem(_(p.label), p.id)
        self.preset.setToolTip(_("Troca a letra, a posição e as animações (o texto fica)."))
        self.preset.activated.connect(self._preset_chosen)
        row.addWidget(self.preset, 1)
        lay.addLayout(row)
        self.store = ParamStore(None, schema=_schema())
        self.cards: list[SectionCard] = []
        for sec in self.store.schema.sections:
            card = SectionCard(sec, self.store, expanded=sec.key in ("letra", "animacao"))
            card.setObjectName(f"titulo_{sec.key}")
            self.cards.append(card)
            lay.addWidget(card)
        self.store.changed.connect(self._store_changed)
        self._text_timer = QTimer(self)
        self._text_timer.setSingleShot(True)
        self._text_timer.setInterval(120)
        self._text_timer.timeout.connect(self._push_text)
        model.selectionChanged.connect(self.sync)
        model.changed.connect(lambda _k: self.sync())
        self.sync()

    # -------------------------------------------------------- estado
    def _clip_source(self):
        c = self.model.primary()
        if c is None:
            return None
        if c.kind != VIDEO:
            c = next((g for g in self.model.seq.group(c) if g.kind == VIDEO), None)
        src = self.model.seq.sources.get(c.src) if c is not None else None
        return src if src is not None and src.kind == titles.KIND else None

    def sync(self) -> None:
        """Mostra o título do clipe escolhido (ou esconde o editor)."""
        src = self._clip_source()
        if src is None:
            self._text_timer.stop()
        elif self._text_timer.isActive() and src.path == self.path:
            return  # digitando: o texto ainda vai para o projeto
        self.path = src.path if src is not None else None
        self.setVisible(src is not None and self.allowed)
        if src is None or not self.allowed:
            return
        self._loading = True
        try:
            text = titles.title_of(src.data).text
            if self.text.toPlainText() != text:
                cur = self.text.textCursor().position()
                self.text.setPlainText(text)
                c = self.text.textCursor()
                c.setPosition(min(cur, len(text)))
                self.text.setTextCursor(c)
            vals = to_store(src.data)
            if any(self.store.values.get(k) != v for k, v in vals.items()):
                self.store.set_all({**self.store.values, **vals}, record=False)
        finally:
            self._loading = False
        self._update_warning(src.data)

    def set_allowed(self, on: bool) -> None:
        """Módulo "Títulos e geradores" desligado: o editor não aparece (o título continua igual na imagem)."""
        self.allowed = bool(on)
        self.sync()

    def _update_warning(self, data: dict) -> None:
        miss = titles.missing(data)
        if miss:
            fam = textrender.family(titles.title_of(data).style.family).name
            self.warn.setText(_("A fonte {fonte} não tem estes caracteres (aparecem como um retângulo no vídeo): "
                                "{caracteres}. Escolha outra fonte em Letra.").format(fonte=fam, caracteres=miss))
        self.warn.setVisible(bool(miss))

    # -------------------------------------------------------- edição
    def _data(self) -> dict | None:
        src = self.model.seq.sources.get(self.path) if self.path else None
        return dict(src.data) if src is not None else None

    def _apply(self, data: dict, record: bool) -> None:
        if self.path is None:
            return
        if not self.model.set_source_data(self.path, data, record=record):
            self._text_timer.stop()
            self.sync()  # faixa travada: volta ao que está no projeto

    def _text_changed(self) -> None:
        if not self._loading and self.path is not None:
            self._text_timer.start()

    def _push_text(self) -> None:
        data = self._data()
        if data is None:
            return
        self._apply(titles.with_text(data, self.text.toPlainText()), record=False)
        self._update_warning(titles.with_text(data, self.text.toPlainText()))

    def _store_changed(self, _key: str) -> None:
        if self._loading:
            return
        data = self._data()
        if data is not None:
            self._apply(from_store(self.store.values, data), record=False)

    def _preset_chosen(self, index: int) -> None:
        pid = self.preset.itemData(index)
        self.preset.setCurrentIndex(0)
        data = self._data()
        if not pid or data is None:
            return
        self._push_pending()
        data = self._data()
        new = {**data, **titles.preset_data(pid, titles.title_of(data).text)}
        self._apply(new, record=True)

    def _push_pending(self) -> None:
        if self._text_timer.isActive():
            self._text_timer.stop()
            self._push_text()

    def focus_text(self) -> None:
        """Título novo: o cursor no texto, tudo escolhido (para já digitar por cima)."""
        self.text.setFocus(Qt.FocusReason.OtherFocusReason)
        self.text.selectAll()

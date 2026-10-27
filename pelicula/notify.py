"""Notificações do sistema: tipos de evento, preferências e a decisão de avisar (sem Qt).

O app avisa por uma notificação do sistema (balão/toast no Windows, servidor de notificações no Linux)
quando algo termina em segundo plano: uma exportação, a fila inteira, o download de um componente ou
uma versão nova. Quem mostra é `ui/notifier.py` (Qt, thread principal); este arquivo só diz *o que*
avisar e *se* avisar, para ser testado sem janela:

    prefs = notify.load(settings)
    d = notify.decide(notify.EXPORT_DONE, module_on=True, focused=False, prefs=prefs)
    d.show, d.sound, d.flash   # notificação, som e piscar o ícone na barra de tarefas

Nada é enviado para fora do computador: a notificação é local.

Preferências (em `settings`, qualquer objeto com `value`/`setValue`: QSettings na janela, um
dicionário nos testes), todas com o prefixo `notificacoes/`:

- `notificacoes/<tipo>`: "1"/"0" para cada tipo de `KINDS` (padrão: ligado);
- `notificacoes/so_sem_foco`: só avisar quando a janela não está em foco (padrão: ligado);
- `notificacoes/som`: tocar um som (padrão: desligado);
- `notificacoes/piscar`: piscar o ícone na barra de tarefas (padrão: ligado).

Tipo novo de notificação: um `Kind` em `KINDS` (id ASCII sem acento, nunca renomear: vira chave das
preferências), uma função que monta o `Notice` aqui e a chamada em quem observa o evento
(`MainWindow`, `Notifier.watch_jobs`...). A página Configurações › Notificações mostra o tipo sozinha.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .i18n import N_, _

EXPORT_DONE = "exportacao_concluida"
EXPORT_FAILED = "exportacao_falhou"
QUEUE_DONE = "fila_concluida"
COMPONENT_DONE = "componente_baixado"
COMPONENT_FAILED = "componente_falhou"
UPDATE = "atualizacao_disponivel"


@dataclass(frozen=True)
class Kind:
    id: str           # ASCII sem acento, nunca renomear (chave das preferências)
    label: str        # PT-BR, traduzido com _() ao mostrar
    description: str


KINDS: tuple[Kind, ...] = (
    Kind(EXPORT_DONE, N_("Exportação concluída"), N_("Um vídeo, imagem ou sequência terminou de exportar.")),
    Kind(EXPORT_FAILED, N_("Exportação com erro"), N_("Uma exportação parou por causa de um erro.")),
    Kind(QUEUE_DONE, N_("Fila concluída"), N_("Todas as exportações da fila terminaram.")),
    Kind(COMPONENT_DONE, N_("Componente baixado"), N_("Um componente (como o ffmpeg) foi baixado e instalado.")),
    Kind(COMPONENT_FAILED, N_("Download com erro"), N_("O download de um componente não deu certo.")),
    Kind(UPDATE, N_("Atualização disponível"), N_("Há uma versão nova do PeliculaConverter.")),
)
KIND_IDS = tuple(k.id for k in KINDS)
_BY_ID = {k.id: k for k in KINDS}

PREFIX = "notificacoes/"
KEY_ONLY_UNFOCUSED = PREFIX + "so_sem_foco"
KEY_SOUND = PREFIX + "som"
KEY_FLASH = PREFIX + "piscar"
OPTION_DEFAULTS = {KEY_ONLY_UNFOCUSED: True, KEY_SOUND: False, KEY_FLASH: True}

# Sem o módulo ligado, a barra de tarefas pisca no fim de uma exportação, como antes das notificações.
LEGACY_FLASH = frozenset({EXPORT_DONE, EXPORT_FAILED, QUEUE_DONE})

# Destinos de um clique que não são arquivos: a janela resolve (`Notifier.actions`).
ACTION_QUEUE = "fila"
ACTION_COMPONENTS = "componentes"
ACTION_UPDATE = "atualizacao"


def get(kind_id: str) -> Kind:
    return _BY_ID[kind_id]


def kind_key(kind_id: str) -> str:
    return PREFIX + kind_id


def _truthy(value, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "sim", "yes", "on")


@dataclass(frozen=True)
class Prefs:
    kinds: frozenset[str] = frozenset(KIND_IDS)  # tipos ligados
    only_unfocused: bool = True
    sound: bool = False
    flash: bool = True

    def kind_on(self, kind_id: str) -> bool:
        return kind_id in self.kinds


def load(settings) -> Prefs:
    """Preferências gravadas (o que falta vale o padrão)."""
    def val(key, default):
        return _truthy(settings.value(key, None) if settings is not None else None, default)
    return Prefs(kinds=frozenset(k for k in KIND_IDS if val(kind_key(k), True)),
                 only_unfocused=val(KEY_ONLY_UNFOCUSED, True),
                 sound=val(KEY_SOUND, False),
                 flash=val(KEY_FLASH, True))


def set_kind(settings, kind_id: str, on: bool) -> None:
    get(kind_id)  # KeyError para tipo desconhecido
    settings.setValue(kind_key(kind_id), "1" if on else "0")


def set_option(settings, key: str, on: bool) -> None:
    if key not in OPTION_DEFAULTS:
        raise KeyError(key)
    settings.setValue(key, "1" if on else "0")


@dataclass(frozen=True)
class Decision:
    show: bool = False   # notificação do sistema
    sound: bool = False  # tocar um som
    flash: bool = False  # piscar o ícone na barra de tarefas (só faz efeito com a janela fora de foco)

    @property
    def anything(self) -> bool:
        return self.show or self.sound or self.flash


NOTHING = Decision()


def decide(kind_id: str, module_on: bool, focused: bool, prefs: Prefs, test: bool = False) -> Decision:
    """Se e como avisar um evento.

    - Módulo `notificacoes` desligado: nenhuma notificação nem som; nas exportações a barra de tarefas
      ainda pisca, como antes do módulo existir (`LEGACY_FLASH`).
    - Tipo desligado nas preferências: nada.
    - "Só quando a janela não está em foco" e a janela em foco: nada (a janela já mostra o resultado).
    - Senão: notificação, mais som e piscar conforme as preferências.

    `test`: o botão "Testar notificação" (ignora o tipo e o foco, já que a pessoa está na janela).
    """
    if not module_on:
        return Decision(flash=kind_id in LEGACY_FLASH and not test)
    if not test:
        if not prefs.kind_on(kind_id):
            return NOTHING
        if prefs.only_unfocused and focused:
            return NOTHING
    return Decision(show=True, sound=prefs.sound, flash=prefs.flash)


# ------------------------------------------------------------------ mensagens
@dataclass(frozen=True)
class Notice:
    kind: str
    title: str
    body: str
    target: str = ""   # arquivo (mostrado selecionado na pasta) ou pasta (aberta) ao clicar
    action: str = ""   # ou um destino da janela: ACTION_QUEUE, ACTION_COMPONENTS, ACTION_UPDATE


def export_done(name: str, path: str) -> Notice:
    """`path`: o que a exportação criou (arquivo ou, nas sequências, a pasta dos quadros)."""
    return Notice(EXPORT_DONE, _("Exportação concluída"),
                  _("{nome} está pronto. Clique para mostrar na pasta.").format(nome=name or Path(path).name),
                  target=path)


def export_failed(name: str, error: str = "") -> Notice:
    body = _("{nome} não foi exportado.").format(nome=name)
    first = (error or "").strip().splitlines()
    if first:
        body += " " + first[-1][:160]
    return Notice(EXPORT_FAILED, _("Exportação com erro"), body, action=ACTION_QUEUE)


def queue_done(ok: int, failed: int, folder: str = "") -> Notice:
    """Resumo da fila. Clicar abre a pasta (todas deram certo e foram para a mesma pasta) ou a fila."""
    title = _("Fila de exportação concluída")
    if failed:
        body = _("{ok} exportações concluídas e {erros} com erro.").format(ok=ok, erros=failed)
    else:
        body = _("{ok} exportações concluídas.").format(ok=ok)
    if folder and not failed:
        return Notice(QUEUE_DONE, title, body, target=folder)
    return Notice(QUEUE_DONE, title, body, action=ACTION_QUEUE)


def component_done(name: str) -> Notice:
    return Notice(COMPONENT_DONE, _("Componente instalado"),
                  _("{nome} foi baixado, conferido e está pronto para uso.").format(nome=name),
                  action=ACTION_COMPONENTS)


def component_failed(name: str, error: str = "") -> Notice:
    body = _("Não foi possível baixar {nome}.").format(nome=name)
    first = (error or "").strip().splitlines()
    if first:
        body += " " + first[-1][:160]
    return Notice(COMPONENT_FAILED, _("Download com erro"), body, action=ACTION_COMPONENTS)


def update_available(version: str) -> Notice:
    return Notice(UPDATE, _("Atualização disponível"),
                  _("O PeliculaConverter {versao} está disponível. Clique para ver as novidades.").format(
                      versao=version), action=ACTION_UPDATE)


TEST = "teste"  # o botão "Testar notificação" (não é um tipo das preferências)


def sample_notice() -> Notice:
    return Notice(TEST, "PeliculaConverter", _("As notificações estão funcionando."))


# ------------------------------------------------------------------ fila de exportação
@dataclass(frozen=True)
class Finished:
    """Uma exportação que acabou de terminar (status "concluido" ou "erro")."""
    status: str
    name: str
    target: str = ""
    error: str = ""


def queue_notices(new: list[Finished], batch: list[Finished], idle: bool, summary: bool = True) -> list[Notice]:
    """Avisos da fila de exportação num instante.

    `new`: exportações que terminaram agora; `batch`: todas as que terminaram desde que a fila começou a
    trabalhar (inclusive as de `new`); `idle`: nada mais esperando nem exportando. Cada exportação avisa
    por conta própria; quando a fila esvazia depois de duas ou mais, sai um aviso só, com o resumo da
    fila (no lugar do aviso da última). Canceladas não avisam nem contam. `summary` False (o tipo "Fila
    concluída" desligado nas preferências): sem resumo, a última avisa por conta própria.
    """
    ok = sum(1 for f in batch if f.status == "concluido")
    failed = sum(1 for f in batch if f.status == "erro")
    if summary and idle and ok + failed >= 2 and any(f.status in ("concluido", "erro") for f in new):
        folders = {str(Path(f.target).parent) for f in batch if f.status == "concluido" and f.target}
        return [queue_done(ok, failed, folders.pop() if len(folders) == 1 else "")]
    out = []
    for f in new:
        if f.status == "concluido":
            out.append(export_done(f.name, f.target))
        elif f.status == "erro":
            out.append(export_failed(f.name, f.error))
    return out

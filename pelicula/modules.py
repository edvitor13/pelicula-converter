"""Módulos: recursos que o usuário liga e desliga (Configurações › Recursos).

Desligar um módulo só esconde a ferramenta da interface. A renderização nunca consulta este
registro: um projeto ou preset que use um recurso desligado sai igual, e a janela avisa e
oferece religar (`used_by`). O núcleo (abrir, prévia, presets, ajustes básicos e exportar) não
é módulo e fica sempre ligado.

O estado fica nas preferências, em `modulos/<id>` ("1" ou "0"). Sem valor salvo vale o padrão:
recursos estáveis ligados (quem já usava o app não perde nada) e recursos em teste desligados.
Instalações novas escolhem um perfil na tela de boas-vindas (`apply_profile`).

Este arquivo não usa Qt: `settings` é qualquer objeto com `value(chave, padrão)` e
`setValue(chave, valor)` (QSettings na janela, um dicionário nos testes).
"""

from __future__ import annotations

from dataclasses import dataclass

from .i18n import N_

ESTAVEL = "estavel"
BETA = "beta"
EXPERIMENTAL = "experimental"
STATUS_LABELS = {ESTAVEL: N_("Estável"), BETA: N_("Beta"), EXPERIMENTAL: N_("Experimental")}

GROUPS = (
    ("edicao", N_("Edição")),
    ("pelicula", N_("Película")),
    ("cor", N_("Cor")),
    ("audio", N_("Som")),
    ("integracoes", N_("Integrações")),
    ("sistema", N_("Sistema")),
)


@dataclass(frozen=True)
class Module:
    id: str                         # chave sem acento, nunca renomear
    name: str                       # texto em PT-BR (traduzir com _() ao mostrar)
    description: str
    group: str
    status: str = ESTAVEL
    requires: tuple[str, ...] = ()  # componentes externos necessários (ids de ferramentas)


MODULES: tuple[Module, ...] = (
    Module("edicao", N_("Modo Edição"),
           N_("Linha do tempo com faixas de vídeo e de som, cortes e ajustes por clipe."), "edicao"),
    Module("laboratorio", N_("Laboratório"),
           N_("Emulação por densidade: negativo, luzes da copiadora, cópia e Technicolor."), "pelicula"),
    Module("defeitos", N_("Defeitos da película"),
           N_("Poeira, riscos, fio de cabelo, manchas, emendas, clarões e vazamento de luz."), "pelicula"),
    Module("scan", N_("Scan da película"),
           N_("Bordas, furos e textos da película escaneada."), "pelicula"),
    Module("luts", N_("LUTs externos"),
           N_("Aplicar LUTs .cube e usar os LUTs já instalados no computador."), "cor"),
    Module("exportar_lut", N_("Exportar LUT"),
           N_("Gerar LUTs .cube do look para usar em outros programas."), "cor"),
    Module("scopes", N_("Scopes"),
           N_("Histograma, forma de onda, parada RGB e vetorscópio."), "cor"),
    Module("curva", N_("Gráfico da curva"),
           N_("Curva de entrada e saída do look em vermelho, verde e azul."), "cor"),
    Module("recorte_ia", N_("Recorte por IA (CorridorKey)"),
           N_("Tira o fundo verde ou azul de um vídeo com o CorridorKey, da Corridor Digital, e grava o vídeo com "
              "transparência e a máscara. Precisa de uma placa NVIDIA RTX série 30 ou mais nova e de um download à "
              "parte em Componentes."), "edicao", BETA, requires=("corridorkey",)),
    Module("legendas_auto", N_("Legendas automáticas"),
           N_("Transcreve a fala dos vídeos neste computador, sem enviar nada para a internet, e cria as legendas "
              "com o tempo de cada palavra; com as palavras, dá para cortar trechos pelo texto. Precisa do "
              "whisper.cpp, de um modelo de fala e do Silero VAD, baixados à parte em Componentes."),
           "edicao", BETA, requires=("whisper_cpp", "silero_vad")),
    Module("medidor_som", N_("Medidor de som"),
           N_("Pico e volume (LUFS) do som durante a reprodução."), "audio"),
    Module("davinci", N_("Plugin do DaVinci Resolve"),
           N_("Instalar o plugin OpenFX, os DCTLs e os LUTs no DaVinci Resolve."), "integracoes"),
    Module("notificacoes", N_("Notificações do sistema"),
           N_("Avisa quando uma exportação termina e em outros eventos, mesmo com a janela em segundo plano."),
           "sistema"),
    Module("recuperacao", N_("Recuperação automática"),
           N_("Guarda cópias de segurança do projeto para recuperar o trabalho depois de um travamento."),
           "sistema"),
    Module("legendas", N_("Legendas"),
           N_("Painel e faixa de legendas: escrever e acertar o tempo, estilos prontos (YouTube, Reels e Cinema), "
              "importar e exportar .srt e .vtt e gravar as legendas no vídeo."), "edicao"),
    Module("silencios", N_("Remover silêncios"),
           N_("Acha os trechos sem fala no som da montagem e tira todos de uma vez, depois que você revisa a "
              "lista."), "edicao"),
)

_BY_ID = {m.id: m for m in MODULES}

_SIMPLES = frozenset({"edicao", "notificacoes", "recuperacao"})
_CRIADOR = _SIMPLES | {"defeitos", "luts", "scopes", "medidor_som", "legendas", "silencios"}
_CINEMA = _CRIADOR | {"laboratorio", "scan", "curva", "exportar_lut", "davinci"}

# (id, nome, descrição, módulos ligados). "Tudo" liga todo módulo estável; recursos em teste
# nunca são ligados por perfil, só um a um.
PROFILES: tuple[tuple[str, str, str, frozenset[str]], ...] = (
    ("simples", N_("Simples"), N_("O essencial: looks prontos, cortes simples e exportação."), _SIMPLES),
    ("criador", N_("Criador"), N_("Para vídeos de redes sociais e YouTube: defeitos, LUTs, scopes, medidor de som, "
                                  "legendas e remover silêncios."),
     _CRIADOR),
    ("cinema", N_("Cinema"), N_("Tudo do Criador mais o Laboratório, o scan, a curva, LUTs e o plugin do DaVinci."),
     _CINEMA),
    ("tudo", N_("Tudo"), N_("Todos os recursos estáveis."),
     frozenset(m.id for m in MODULES if m.status == ESTAVEL)),
)

KEY_PREFIX = "modulos/"
KEY_PROFILE = "modulos/perfil"
KEY_SHOW_TESTS = "modulos/mostrar_testes"


def get(module_id: str) -> Module:
    return _BY_ID[module_id]


def exists(module_id: str) -> bool:
    return module_id in _BY_ID


def _truthy(value) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "sim", "yes", "on")


def default_enabled(module_id: str) -> bool:
    return get(module_id).status == ESTAVEL


def is_enabled(settings, module_id: str) -> bool:
    """Se o módulo está ligado. Sem preferência salva vale o padrão (estável = ligado)."""
    if not exists(module_id):
        return False
    saved = _truthy(settings.value(KEY_PREFIX + module_id, None)) if settings is not None else None
    return default_enabled(module_id) if saved is None else saved


def set_enabled(settings, module_id: str, on: bool) -> None:
    get(module_id)  # KeyError para id desconhecido
    settings.setValue(KEY_PREFIX + module_id, "1" if on else "0")


def enabled_ids(settings) -> set[str]:
    return {m.id for m in MODULES if is_enabled(settings, m.id)}


def apply_profile(settings, profile_id: str) -> None:
    """Liga os módulos do perfil e desliga os outros (recursos em teste ficam como estão)."""
    chosen = next(p for p in PROFILES if p[0] == profile_id)[3]
    for m in MODULES:
        if m.status == ESTAVEL:
            set_enabled(settings, m.id, m.id in chosen)
    settings.setValue(KEY_PROFILE, profile_id)


def current_profile(settings) -> str | None:
    """O perfil que corresponde exatamente aos módulos estáveis ligados, ou None ("Personalizado").

    Dois perfis podem ligar os mesmos módulos (hoje Cinema e Tudo): vale o último escolhido e,
    sem escolha salva, "tudo".
    """
    on = {m.id for m in MODULES if m.status == ESTAVEL and is_enabled(settings, m.id)}
    matches = [pid for pid, _name, _desc, ids in PROFILES if on == set(ids)]
    saved = settings.value(KEY_PROFILE, None) if settings is not None else None
    if saved in matches:
        return saved
    if "tudo" in matches:
        return "tudo"
    return matches[0] if matches else None


def show_tests(settings) -> bool:
    """Se a página Recursos mostra os recursos Beta e Experimentais."""
    return bool(_truthy(settings.value(KEY_SHOW_TESTS, None))) if settings is not None else False


def visible(settings) -> list[Module]:
    """Módulos listados na página Recursos (os em teste só com "Mostrar recursos em teste")."""
    tests = show_tests(settings)
    return [m for m in MODULES if m.status == ESTAVEL or tests or is_enabled(settings, m.id)]


def used_by(values: dict | None = None, sequence=None, subtitles=None) -> set[str]:
    """Módulos que um look (valores), uma montagem ou as legendas do projeto (`subtitles.Subtitles`, também
    lidas de `sequence.subtitles`) usam de fato.

    Serve para avisar ao abrir um projeto ou aplicar um preset que depende de um módulo
    desligado. A renderização não muda: o aviso só oferece religar a ferramenta.
    """
    used: set[str] = set()
    v = values or {}
    for key, module_id in (("lab_on", "laboratorio"), ("desg_on", "defeitos"), ("scan_on", "scan")):
        if v.get(key):
            used.add(module_id)
    if v.get("lut_on") and v.get("lut_arquivo"):
        used.add("luts")
    # Montagem vazia ou só "o arquivo inteiro, sem mudanças" não é edição.
    trivial = getattr(sequence, "is_trivial", lambda: True)
    if sequence is not None and getattr(sequence, "clips", True) and not trivial():
        used.add("edicao")
    for subs in (subtitles, getattr(sequence, "subtitles", None)):
        if subs is not None and not subs.is_empty():
            used.add("legendas")
    return used

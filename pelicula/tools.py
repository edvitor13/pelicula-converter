"""Componentes externos: ferramentas que o app baixa e programas que ele encontra no computador.

O registro (`TOOLS`) diz, para cada componente, o que é, para que serve, a licença, a fonte oficial,
que módulos usam (`modules.MODULES`) e, para cada sistema, o arquivo a baixar (`Artifact`): versão,
URL, SHA-256 e tamanho **fixos no código** — nunca lidos do mesmo servidor na hora do download.

Tipos (`Tool.kind`):

- `BAIXADO`: o app baixa da fonte oficial — o binário do próprio autor quando ele publica checksums
  (`origin=OFICIAL`); senão, compilado no CI do PeliculaConverter a partir do código oficial e
  publicado na release do projeto com `SHA256SUMS.txt` (`origin=CI`). O SHA-256 é conferido
  **antes** de extrair; a instalação vai para `deps.app_data_dir()/ferramentas/<id>/<versão>/`,
  montada numa pasta temporária ao lado e trocada de uma vez (`rename`), com `pelicula-origem.json`
  (URL, SHA-256, data). Fica uma versão só, salvo `keep_old=True`.
- `SISTEMA`: programa instalado pelo usuário (DaVinci Resolve agora; Blender depois). O app só
  detecta (`DETECTORS`), sem download.

Receitas (`backend="receita"`, `Tool.recipe`): componentes de IA que não cabem num pacote só, como o
CorridorKey — código de um commit fixo conferido arquivo por arquivo (`SourceZip` + manifesto), um
ambiente Python próprio montado pelo uv (`PythonEnv` + `build_env()`: versão do Python, índice do
PyTorch e lista travada com hashes) e modelos com SHA-256 fixo (`Piece`, download retomável em
`fetch_file()`). `install_recipe()` monta tudo numa pasta temporária, roda o teste da receita e troca
de uma vez; o Python base fica em `ferramentas/<id>/python` e os downloads em `ferramentas/<id>/cache`
(retomáveis; a limpeza de pastas esquecidas não mexe). Programas externos rodam por `run_process()`
(cancelar encerra o processo e os filhos).

Exceção documentada: o **ffmpeg** (`backend="ffmpeg"`) mantém o fluxo de `deps.py` — o build mais
recente do gyan.dev (Windows) ou do BtbN (Linux), conferido com o arquivo de checksum publicado
pelo autor do build — e aparece aqui só para a página Componentes mostrar, atualizar e remover.

Sem Qt. A página `ui/pages/componentes.py` mostra o registro e baixa pela fila de tarefas
(`jobs.py`). Funções que gravam aceitam `root` (a pasta `ferramentas`) para os testes usarem uma
pasta temporária.
"""

from __future__ import annotations

import collections
import hashlib
import http.client
import json
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import APP_NAME, __version__, deps, system
from .i18n import N_, _, fmt_decimal

BAIXADO = "baixado"
SISTEMA = "sistema"
KINDS = (BAIXADO, SISTEMA)

OFICIAL = "oficial"  # binário oficial do autor, com checksum publicado por ele
CI = "ci"            # compilado no CI do PeliculaConverter a partir do código-fonte oficial
ORIGINS = (OFICIAL, CI)

ARCHIVES = ("zip", "tar.gz", "tar.xz", "arquivo")  # "arquivo" = um executável só, sem pacote
PLATFORMS = ("win32", "linux", "darwin")

# Estados (Status.state)
AUSENTE = "ausente"            # não instalado / não encontrado no computador
INSTALADO = "instalado"
DESATUALIZADO = "desatualizado"
INDISPONIVEL = "indisponivel"  # sem download para este sistema

MARKER = "pelicula-origem.json"
STAGING_PREFIX = ".novo-"
TRASH_PREFIX = ".removendo-"
STALE_SECONDS = 12 * 3600      # pastas temporárias esquecidas (app fechado no meio) somem depois disso
CHUNK = 1 << 20

Progress = Callable[[str, int, int], None]


class ToolError(RuntimeError):
    """Falha ao baixar, instalar ou remover um componente (mensagem pronta para o usuário)."""


Cancelled = deps.DownloadCancelled


@dataclass(frozen=True)
class Artifact:
    """O arquivo a baixar de uma ferramenta, num sistema. Tudo fixo no código."""
    platform: str                      # "win32", "linux" ou "darwin" (deps.platform_key())
    version: str                       # vira o nome da pasta: letras, números, ".", "_" e "-"
    url: str                           # https; para origin=CI, a release do PeliculaConverter
    sha256: str                        # 64 dígitos hexadecimais (minúsculos)
    size: int                          # bytes do arquivo baixado
    archive: str = "zip"               # um de ARCHIVES
    executables: tuple[str, ...] = ()  # caminhos dentro da pasta da versão, com "/"
    unpacked_size: int = 0             # bytes depois de extrair (0 = não se sabe)
    origin: str = OFICIAL


@dataclass(frozen=True)
class Tool:
    """Um componente externo. Textos em PT-BR (N_), traduzidos com _() ao mostrar."""
    id: str                            # chave ASCII sem acento, nunca renomear (é o nome da pasta)
    name: str
    description: str                   # para que serve, em uma ou duas frases
    icon: str                          # nome de um ícone de ui/icons.py
    homepage: str                      # site oficial (https)
    license: str                       # licença (SPDX ou nome curto)
    license_url: str                   # texto da licença (https)
    kind: str = BAIXADO
    modules: tuple[str, ...] = ()      # ids de modules.MODULES que usam
    core: bool = False                 # faz parte do núcleo (abrir, prévia, exportar)
    artifacts: tuple[Artifact, ...] = ()
    consent: str = ""                  # condições da licença que o usuário aceita antes de baixar
    backend: str = ""                  # "" = registro; "ffmpeg" = fluxo próprio de deps.py; "receita" = `recipe`
    source_url: str = ""               # código-fonte oficial (obrigatório quando um artefato é origin=CI)
    recipe: "Recipe | None" = None     # instalação composta (código + ambiente Python + modelos), backend="receita"
    notes: tuple[str, ...] = ()        # linhas fixas do cartão (créditos, condições de uso), em PT-BR (N_)
    licenses: tuple[tuple[str, str, str], ...] = ()  # licenças de terceiros: (o quê, licença, URL https)

    def artifact(self, platform: str | None = None) -> Artifact | None:
        """O arquivo deste sistema (ou do sistema dado), se houver."""
        key = platform or deps.platform_key()
        return next((a for a in self.artifacts if a.platform == key), None)


# ------------------------------------------------------------------ receitas (código + ambiente Python + modelos)
@dataclass(frozen=True)
class Piece:
    """Um arquivo (modelo, pesos) baixado da fonte oficial com SHA-256 e tamanho fixos no código."""
    url: str                           # https
    sha256: str                        # 64 dígitos hexadecimais minúsculos
    size: int                          # bytes
    dest: str                          # caminho dentro da instalação, com "/"


@dataclass(frozen=True)
class SourceZip:
    """Código de um commit fixo (zip do GitHub), conferido arquivo por arquivo contra um manifesto.

    O zip que o GitHub monta para um commit pode mudar de bytes com o tempo: por isso o SHA-256 vale
    para cada arquivo extraído (manifesto em `pelicula/data`, gerado por `tools/gerar_manifesto.py`),
    não para o zip. Arquivo fora do manifesto não é instalado (os `.bat`/`.sh` dos autores, por
    exemplo); arquivo que falta ou que não confere cancela a instalação.
    """
    url: str                           # https://codeload.github.com/<dono>/<repo>/zip/<commit>
    manifest: str                      # manifesto `<sha256>  <caminho>` (relativo a pelicula/data)
    dest: str = ""                     # pasta dentro da instalação (com package=True, o nome do pacote)
    package: bool = False              # True: instalado no ambiente Python (sem dependências), não copiado
    max_size: int = 64 << 20           # o zip não tem tamanho fixo: limite de segurança


@dataclass(frozen=True)
class PythonEnv:
    """Receita de um ambiente Python isolado, montado pelo uv (receita "Novo ambiente Python" no AGENTS.md).

    Cada componente tem o seu: versão exata do Python, índice do PyTorch e uma lista travada com
    hashes por sistema (`uv pip compile --generate-hashes`). Nada é compartilhado entre ambientes
    além do executável do uv (`UV`) quando a versão é a mesma.
    """
    python: str                                       # versão exata do Python ("3.12.15")
    requirements: dict[str, str] = field(default_factory=dict)  # sistema → lista travada (relativa a pelicula/data)
    torch: str = ""                                   # índice do PyTorch ("cu128", "cu126", "cpu"...; "" = sem)
    size: dict[str, int] = field(default_factory=dict)  # bytes das bibliotecas instaladas (barra de progresso)


@dataclass(frozen=True)
class Recipe:
    """Instalação composta de um componente: código de commits fixos + ambiente Python + modelos.

    Montada em `ferramentas/<id>/.novo-*` e trocada de uma vez para `ferramentas/<id>/<versão>`,
    como os pacotes comuns; o Python base fica em `ferramentas/<id>/python` (fora da pasta trocada,
    porque um ambiente Python aponta para ele por caminho absoluto) e os downloads grandes em
    `ferramentas/<id>/cache` (retomáveis; a limpeza de pastas esquecidas não mexe nele).
    """
    version: str                                      # nome da pasta da instalação
    env: PythonEnv
    code: tuple[SourceZip, ...] = ()
    files: tuple[Piece, ...] = ()
    workdir: str = ""                                 # pasta do código (cwd do teste e dos comandos)
    check: tuple[str, ...] = ()                       # teste final: argumentos para o Python do ambiente
    check_env: dict[str, str] = field(default_factory=dict)  # variáveis do teste
    check_timeout: float = 1800.0
    download_size: dict[str, int] = field(default_factory=dict)  # sistema → bytes a baixar (aproximado)
    disk_size: dict[str, int] = field(default_factory=dict)      # sistema → bytes no disco instalado (aproximado)

    def platforms(self) -> tuple[str, ...]:
        return tuple(self.env.requirements)


FFMPEG = Tool(
    id="ffmpeg", name="ffmpeg",
    description=N_("Lê e grava todos os formatos de vídeo e de som. Sem ele o app não abre nem exporta vídeos."),
    icon="video", homepage="https://ffmpeg.org", license="GPL-3.0", license_url="https://ffmpeg.org/legal.html",
    kind=BAIXADO, core=True, backend="ffmpeg")

DAVINCI_RESOLVE = Tool(
    id="davinci_resolve", name="DaVinci Resolve",
    description=N_("Editor e corretor de cor da Blackmagic Design. O app instala nele o plugin OpenFX, os DCTLs "
                   "e os LUTs do PeliculaConverter."),
    icon="davinci", homepage="https://www.blackmagicdesign.com/products/davinciresolve",
    license=N_("Proprietária (Blackmagic Design)"),
    license_url="https://www.blackmagicdesign.com/products/davinciresolve",
    kind=SISTEMA, modules=("davinci",))

# uv (Astral): monta os ambientes Python das receitas. Binário oficial com o .sha256 publicado pela
# Astral (conferido ao fixar). Reaproveitado por todo ambiente que pedir esta versão.
UV_VERSION = "0.13.5"
_UV_URL = f"https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/"
UV = Tool(
    id="uv", name="uv",
    description=N_("Instalador de Python da Astral. Monta numa pasta própria o Python e as bibliotecas dos "
                   "componentes de IA, sem mexer no Python do computador."),
    icon="box", homepage="https://github.com/astral-sh/uv", license="MIT / Apache-2.0",
    license_url=f"https://github.com/astral-sh/uv/blob/{UV_VERSION}/LICENSE-MIT",
    kind=BAIXADO, modules=("recorte_ia",),
    artifacts=(
        Artifact("win32", UV_VERSION, _UV_URL + "uv-x86_64-pc-windows-msvc.zip",
                 "a38b8d1902b7cfbc76b423ba1bb456f623f42064cdc72628b6075b89afd1019a", 15264056, "zip",
                 ("uv.exe",), unpacked_size=32591760),
        Artifact("linux", UV_VERSION, _UV_URL + "uv-x86_64-unknown-linux-gnu.tar.gz",
                 "f68d291c75783122dad58ab77def0e13f3233f358731db5d6d7e8715603b928f", 16682639, "tar.gz",
                 ("uv-x86_64-unknown-linux-gnu/uv",), unpacked_size=37927616),
    ))

# CorridorKey 2.0 (Corridor Digital): recorte de fundo verde/azul por IA. Tudo fixo: o código no commit
# 485f5e9 (15/10/2026), os pesos na revisão cf44a8d do Hugging Face e os três modelos de terceiros nas
# revisões do `scripts/download_weights.py` desse commit, nas mesmas pastas. SHA-256 dos arquivos LFS
# publicados pelo Hugging Face; os pequenos (.py/.json do C-RADIO) conferidos com o blob do git na
# revisão; o RVM conferido com o MD5 do script deles e fixado aqui em SHA-256. Licença: exceção
# registrada no AGENTS.md (baixado à parte das fontes oficiais, nunca redistribuído).
_CK_COMMIT = "485f5e9ab759ead6138cc990776184b59d6ea971"
_CK_REPO = "https://github.com/nikopueringer/CorridorKey2.0"
_HF = "https://huggingface.co"


def _hf(repo: str, rev: str, name: str, sha256: str, size: int, dest: str) -> Piece:
    return Piece(f"{_HF}/{repo}/resolve/{rev}/{name}", sha256, size, dest)


def _cradio(name: str, size: int, sha256: str) -> Piece:
    return _hf("nvidia/C-RADIOv4-SO400M", "c0457f5dc26ca145f954cd4fc5bb6114e5705ad8", name, sha256, size,
               f"codigo/vfms/cradio/C-RADIOv4-SO400M/{name}")


_CK_FILES = (
    _hf("nikopueringer/CorridorKey2.0", "cf44a8db3f024bb49fd59daa408848ccf05f7477", "corridorkey_v2.safetensors",
        "c43596de98cc8866d577c8a9f9ea239acdf3f7a130ff24e25db4375a50590436", 2661698720,
        "codigo/weights/corridorkey_v2.safetensors"),
    _hf("nikopueringer/CorridorKey2.0", "cf44a8db3f024bb49fd59daa408848ccf05f7477", "foundation_stats.safetensors",
        "924783ceddd293fd470126332ce328166faea6c4c8d2f36402d5b95187166af3", 18864,
        "codigo/weights/foundation_stats.safetensors"),
    # C-RADIOv4-SO400M (NVIDIA Open Model License): tudo, menos o *.pth.tar (duplica o model.safetensors)
    _cradio("model.safetensors", 1724986512, "23e0c117de49d4ce909150fe6658d470829e6639647c7a5b035ce82e0d5b763c"),
    _cradio(".gitattributes", 1519, "11ad7efa24975ee4b0c3c3a38ed18737f0658a5f75a0a96787b576a78a023361"),
    _cradio("README.md", 14000, "af7881b8207e7060b8df5b8df4df4e87e628faffc188b494836bbec086233b33"),
    _cradio("adaptor_attn.py", 1796, "baa112b58158d75077e9bba8baba51b2c75f6a6deed2d8046aa5e5f2d5cb669a"),
    _cradio("adaptor_base.py", 1693, "f9d285cc76e70f977f9c78e748f610765f0bd068a13f86d804c07c765cece577"),
    _cradio("adaptor_generic.py", 3747, "3d1b5a015ff3754a9eb64cd56b4d04cae01e537a1ffa606adaf904c55fff07a1"),
    _cradio("adaptor_mlp.py", 4025, "e75a9ed1f7f58c749dec5a510d699f36f32fdb7f3b61cd8a7e3ccd5afd2c9b77"),
    _cradio("adaptor_module_factory.py", 3278, "2beac17dc5824c7d9f925dc782cdd4b49bd15cf206bf1cbaa9108a8966e33316"),
    _cradio("adaptor_registry.py", 1371, "16963e07de300e5f3cbd5e343aed111d04e4e55a50e07f50ccc2ab930883ea1e"),
    _cradio("cls_token.py", 1787, "64ee35f128380c3bb9bc1a913e98ac328220be88964f2092686c637ef866fc79"),
    _cradio("common.py", 7160, "6cc79e1f7b61f4917602d2efc9e0a833fa74d60563f6aac74e4625de23723bab"),
    _cradio("config.json", 7571, "6e49e911ff6e980125c208b10ed4b51bb4a92061862cbb8947473f1b33f88fd4"),
    _cradio("dinov2_arch.py", 35529, "5433d08522c28f46a69e710da1a86fc1d76fc03562dbb9b2b49baf5db21195d3"),
    _cradio("dual_hybrid_vit.py", 7179, "86853ae2ed28c902529cd9b78201350e7dba1cf54ea9e57578241ecc0d88d867"),
    _cradio("enable_cpe_support.py", 6557, "3c1e3df656960f5c83b38ba5f632fc5b335edf1d6de67731396a865aaa5ce1ed"),
    _cradio("enable_damp.py", 1290, "7e2a0b6f8934ac6e4a4768e5ca84cb4ff09ba3726a470f1cf046bd5169b2e334"),
    _cradio("enable_spectral_reparam.py", 11004, "b8e703400604ee5f9cdfac0de9b857b7f5126aad8bba03604b04f52f7641d6cb"),
    _cradio("eradio_model.py", 58289, "bf76c60b991813eef45c76246cd7dcee3fefbf39bde3d2b6ac8576067012d05f"),
    _cradio("extra_models.py", 5763, "a938b96715266d2f65325e56d0d8e42465d23e944e905d2820023472785c55a9"),
    _cradio("extra_timm_models.py", 9892, "d7364d5abf5b617782366948f0e593d7a2df275b076094afa1ebc5276a9f7102"),
    _cradio("feature_normalizer.py", 4399, "a74401f5220c2e5960d39addce9ba40f481efca9ab44bb9d96535ed23e1ef62b"),
    _cradio("forward_intermediates.py", 5604, "eb5a562d11edc655876eeb95bc1c3b4c7484b963dae41a3f76f7acd2a6906b9e"),
    _cradio("hf_model.py", 7935, "d28c0a0238ca8854a9af5a9f003761332bfc9182601b3b7466d9242be91ee96f"),
    _cradio("input_conditioner.py", 1492, "72062d3b71877e1469e069cf090e5f35d6ad7abaeb451e56502f7f32dc6c1075"),
    _cradio("open_clip_adaptor.py", 1623, "c2eb9166de48f5eb5f90f8a750e8ebe67da93698e794dc0bbdab5f013bab8e66"),
    _cradio("preprocessor_config.json", 331, "6ca88d165592015b02a183d26a20fc96748e837d1cb21bde5f611141aca593cf"),
    _cradio("radio_model.py", 14018, "2be659f5cd5b9db9c49db70387b65253c74bc16b3eb86e976f0f693271d4b183"),
    _cradio("siglip2_adaptor.py", 3307, "1f40f7d77beefd69ad86aac61b12c82ed915b4012e6bea1628fc8abe80782851"),
    _cradio("utils.py", 1109, "3b83163ce2650ef04973538dd79716ab015d24344ea25d52cfb0c37b093ba4ba"),
    _cradio("vit_patch_generator.py", 11475, "092e9a0b8eca4fee162484ef3ef77b399f686e5e0ffc7be85fb2d69bc2f9ebd9"),
    _cradio("vitdet.py", 6318, "5b83b4c7b90b797d854a6da2fd4093ce9210a52533d3f7ba6bf505793b6c68c3"),
    # MoGe-2 ViT-B (Microsoft, MIT)
    _hf("Ruicheng/moge-2-vitb-normal", "ca5f0e07ff01d3e5a364c1d954ed12ee1814b368", "model.pt",
        "16b8110e86d5dc5a849db120ca96ef3a223fd30b0c9146d1d81db504073da5f6", 419110160, "codigo/vfms/moge/model.pt"),
    # RVM small (Google DeepMind, Apache-2.0 / CC-BY 4.0): MD5 ZJb6kj8+tasiJbVeplXu7Q== conferido ao fixar
    Piece("https://storage.googleapis.com/representations4d/checkpoints/pretrain_rvm_small16_256_204031069.npz",
          "8821ba9f5d983b9a3746bb5fe86b9c2ea834fe9985ab7b02438b917438bf2ede", 270086372,
          "codigo/vfms/rvm/pretrain_rvm_small16_256_204031069.npz"),
)
_CK_MODELS = sum(p.size for p in _CK_FILES)

CORRIDORKEY_RECIPE = Recipe(
    version="2.0-485f5e9",
    env=PythonEnv(python="3.12.15", torch="cu128",
                  requirements={"win32": "corridorkey/requirements-windows.txt",
                                "linux": "corridorkey/requirements-linux.txt"},
                  # cache do uv depois das bibliotecas (≈ o venv: o uv liga os arquivos do cache).
                  # Windows medido em 27/10/2026 (venv de 5.030.953.716 bytes); Linux estimado.
                  size={"win32": 5_100_000_000, "linux": 7_600_000_000}),
    code=(SourceZip(f"https://codeload.github.com/nikopueringer/CorridorKey2.0/zip/{_CK_COMMIT}",
                    "corridorkey/codigo-485f5e9.sha256", dest="codigo"),
          SourceZip("https://codeload.github.com/EasternJournalist/utils3d/zip/83bfa5bda008803f6521ce9547f94023b8afeddd",
                    "corridorkey/utils3d-83bfa5b.sha256", dest="utils3d", package=True)),
    files=_CK_FILES,
    workdir="codigo",
    check=("scripts/smoke_test_runtime.py", "--load_model"),
    check_env={"HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"},
    # bibliotecas (Windows 3,0 GB; Linux 4,2 GB com os pacotes nvidia-*) + modelos + Python, uv e código
    download_size={"win32": 3_004_591_508 + _CK_MODELS + 60_000_000,
                   "linux": 4_226_884_434 + _CK_MODELS + 60_000_000},
    # instalado no Windows (27/10/2026): versão 10.108.686.092 + Python base 130.726.865 bytes, 25 mil
    # arquivos; com folga para o cache durante a instalação. Linux estimado (não medido).
    disk_size={"win32": 10_700_000_000,
               "linux": 7_600_000_000 + _CK_MODELS + 400_000_000},
)

CORRIDORKEY = Tool(
    id="corridorkey", name="CorridorKey",
    description=N_("Recorte de fundo verde ou azul por IA, da Corridor Digital: gera a máscara (alfa) e a cor do "
                   "primeiro plano sem o verde."),
    icon="matte", homepage=_CK_REPO,
    license=N_("Corridor Key Licence (CC BY-NC-SA 4.0 com termos adicionais)"),
    license_url=f"{_CK_REPO}/blob/{_CK_COMMIT}/LICENSE",
    kind=BAIXADO, modules=("recorte_ia",), backend="receita", recipe=CORRIDORKEY_RECIPE,
    source_url=f"{_CK_REPO}/tree/{_CK_COMMIT}",
    consent=N_("O CorridorKey é da Corridor Digital e usa a Corridor Key Licence (CC BY-NC-SA 4.0 com termos "
               "adicionais, que valem primeiro).\n\n"
               "Resumo: você pode usar o CorridorKey em qualquer trabalho legal, inclusive comercial, e o que você "
               "recortar é seu. Não é permitido revender, redistribuir nem cobrar pelo acesso ao CorridorKey ou aos "
               "pesos, nem oferecer o recorte como serviço pago. Empresas com faturamento anual acima de US$ 20 "
               "milhões (somando o grupo) precisam comprar uma licença por pessoa em corridorkey.com.\n\n"
               "Tudo vem só das fontes oficiais, direto para este computador: o código do GitHub da Corridor, os "
               "pesos do Hugging Face e três modelos de terceiros, cada um com a sua licença."),
    notes=(N_("CorridorKey, da Corridor Digital. O que você recortar é seu e pode ser usado comercialmente."),
           N_("Empresas com faturamento anual acima de US$ 20 milhões precisam comprar uma licença por pessoa em "
              "corridorkey.com.")),
    licenses=(("C-RADIOv4 (NVIDIA)", "NVIDIA Open Model License",
               "https://developer.download.nvidia.com/licenses/nvidia-open-model-license-agreement-june-2024.pdf"),
              ("MoGe-2 (Microsoft)", "MIT", "https://github.com/microsoft/MoGe/blob/main/LICENSE"),
              ("RVM (Google DeepMind)", "Apache-2.0 / CC-BY 4.0",
               "https://github.com/google-deepmind/representations4d")),
)

# whisper.cpp (ggml-org, MIT): transcrição local para as legendas automáticas (módulo "legendas_auto").
# O autor não publica binários com checksum para Linux nem builds com Vulkan para os dois sistemas: o
# whisper-cli e as bibliotecas são compilados pelo nosso CI (.github/workflows/componentes.yml) a partir da
# tag oficial (commit conferido) e publicados na pre-release componente-whisper-cpp-<versão>; SHA-256 e
# tamanho daqui conferidos com o SHA256SUMS.txt dela. Variante "vulkan": CPU + Vulkan carregado na hora
# (sem driver Vulkan roda na CPU). Receita "Componente compilado no CI" no AGENTS.md.
WHISPER_CPP_VERSION = "1.9.5"
_WCPP_COMMIT = "d1be6fde11ac6e0407606b4e42fe72d34add8037"
_WCPP_REPO = "https://github.com/ggml-org/whisper.cpp"
_WCPP_URL = ("https://github.com/edvitor13/pelicula-converter/releases/download/"
             f"componente-whisper-cpp-{WHISPER_CPP_VERSION}/whisper-cpp-{WHISPER_CPP_VERSION}-")
WHISPER_CPP = Tool(
    id="whisper_cpp", name="whisper.cpp",
    description=N_("Transcreve a fala dos vídeos em texto, neste computador (nada é enviado): é o motor das "
                   "legendas automáticas. Usa a placa de vídeo (Vulkan) quando há; senão, o processador."),
    icon="captions", homepage=_WCPP_REPO, license="MIT", license_url=f"{_WCPP_REPO}/blob/{_WCPP_COMMIT}/LICENSE",
    kind=BAIXADO, modules=("legendas_auto",), source_url=f"{_WCPP_REPO}/tree/v{WHISPER_CPP_VERSION}",
    notes=(N_("Compilado pelo CI do PeliculaConverter a partir do código oficial, sem mudanças."),),
    artifacts=(
        Artifact("win32", WHISPER_CPP_VERSION, _WCPP_URL + "windows-x64-vulkan.zip",
                 "aaa472a7d948cee82d59d9dd076aac2169fbf27b95be21b7dbe9aaf2443e932d", 18108677, "zip",
                 ("whisper-cli.exe",), unpacked_size=58657906, origin=CI),
        Artifact("linux", WHISPER_CPP_VERSION, _WCPP_URL + "linux-x64-vulkan.tar.gz",
                 "184598fbfc348549acdd077dc96c003aa6fc345229386b178843dee410eafd8e", 21293425, "tar.gz",
                 ("whisper-cli",), unpacked_size=64733539, origin=CI),
    ))


def _hf_model(repo: str, rev: str, name: str, sha256: str, size: int, version: str) -> tuple[Artifact, ...]:
    """Um arquivo de modelo do Hugging Face (revisão fixa; SHA-256 do LFS), o mesmo nos dois sistemas."""
    url = f"{_HF}/{repo}/resolve/{rev}/{name}"
    return tuple(Artifact(p, version, url, sha256, size, "arquivo", (name,), unpacked_size=size)
                 for p in ("win32", "linux"))


# Modelos de fala do whisper.cpp (pesos do Whisper, da OpenAI, MIT, convertidos para ggml pelo autor do
# whisper.cpp), no repositório oficial ggerganov/whisper.cpp do Hugging Face, revisão fixa:
# small em q8_0 (quase igual ao f16, metade do tamanho) e large-v3-turbo em q5_0 (o mais preciso que
# ainda cabe em placas de 4 GB e roda na CPU; o q8_0 tem 874 MB e quase nenhum ganho de acerto).
_WM_REPO, _WM_REV = "ggerganov/whisper.cpp", "5359861c739e955e79d9a303bcbc70fb988958b1"
_WHISPER_LICENSE = "https://github.com/openai/whisper/blob/c0d2f624c09dc18e709e37c2ad90c039a4eb72a2/LICENSE"
WHISPER_SMALL = Tool(
    id="whisper_small", name=N_("Modelo de fala Rápido (small)"),
    description=N_("Modelo de transcrição leve e rápido, para muitos idiomas. Bom para a maioria dos vídeos."),
    icon="box", homepage=f"{_HF}/{_WM_REPO}", license="MIT", license_url=_WHISPER_LICENSE,
    kind=BAIXADO, modules=("legendas_auto",),
    notes=(N_("Pesos do Whisper (OpenAI), convertidos pelo autor do whisper.cpp."),),
    artifacts=_hf_model(_WM_REPO, _WM_REV, "ggml-small-q8_0.bin",
                        "49c8fb02b65e6049d5fa6c04f81f53b867b5ec9540406812c643f177317f779f", 264464607, "small-q8_0"))
WHISPER_TURBO = Tool(
    id="whisper_turbo", name=N_("Modelo de fala Preciso (turbo)"),
    description=N_("Modelo de transcrição mais preciso (large-v3-turbo), para muitos idiomas. Mais lento sem "
                   "placa de vídeo."),
    icon="box", homepage=f"{_HF}/{_WM_REPO}", license="MIT", license_url=_WHISPER_LICENSE,
    kind=BAIXADO, modules=("legendas_auto",),
    notes=(N_("Pesos do Whisper (OpenAI), convertidos pelo autor do whisper.cpp."),),
    artifacts=_hf_model(_WM_REPO, _WM_REV, "ggml-large-v3-turbo-q5_0.bin",
                        "394221709cd5ad1f40c46e6031ca61bce88931e6e088c188294c6d5a55ffa7e2", 574041195,
                        "large-v3-turbo-q5_0"))
# Silero VAD 6.2.0 (Silero, MIT) em ggml, do repositório oficial ggml-org/whisper-vad (o que o
# models/download-vad-model.sh do whisper.cpp usa), revisão fixa.
_SILERO = "https://github.com/snakers4/silero-vad"
SILERO_VAD = Tool(
    id="silero_vad", name="Silero VAD",
    description=N_("Detecta onde há fala no som: a transcrição pula os silêncios e não inventa texto neles."),
    icon="box", homepage=_SILERO, license="MIT", license_url=f"{_SILERO}/blob/v6.2/LICENSE",
    kind=BAIXADO, modules=("legendas_auto",),
    artifacts=_hf_model("ggml-org/whisper-vad", "9ffd54a1e1ee413ddf265af9913beaf518d1639b", "ggml-silero-v6.2.0.bin",
                        "2aa269b785eeb53a82983a20501ddf7c1d9c48e33ab63a41391ac6c9f7fb6987", 885098, "6.2.0"))

# Ordem da página Componentes: o ffmpeg primeiro. Ferramenta nova: veja a receita "Nova ferramenta
# externa" no AGENTS.md (fonte oficial, versão e SHA-256 fixos, licença, testes).
TOOLS: tuple[Tool, ...] = (FFMPEG, CORRIDORKEY, WHISPER_CPP, WHISPER_SMALL, WHISPER_TURBO, SILERO_VAD, UV,
                           DAVINCI_RESOLVE)


def all_tools() -> tuple[Tool, ...]:
    return TOOLS


def get(tool_id: str) -> Tool:
    for t in all_tools():
        if t.id == tool_id:
            return t
    raise KeyError(tool_id)


def used_by(tool: Tool) -> list[str]:
    """Módulos que usam a ferramenta: os de `tool.modules` e os que a pedem em `Module.requires`."""
    from . import modules
    ids = list(tool.modules)
    for m in modules.MODULES:
        if tool.id in m.requires and m.id not in ids:
            ids.append(m.id)
    return ids


# ------------------------------------------------------------------ pastas e tamanhos
def tools_dir() -> Path:
    """Pasta das ferramentas baixadas: <pasta do app>/ferramentas."""
    return deps.app_data_dir() / "ferramentas"


def tool_dir(tool: Tool, root: str | Path | None = None) -> Path:
    """Pasta de uma ferramenta: <ferramentas>/<id> (cada versão numa subpasta)."""
    return (Path(root) if root is not None else tools_dir()) / tool.id


def ffmpeg_home() -> Path:
    """Pasta do ffmpeg baixado pelo app (bin/ + ORIGEM.txt)."""
    return deps.ffmpeg_dir().parent


def dir_size(path: str | Path) -> int:
    """Bytes de todos os arquivos dentro da pasta (sem seguir links)."""
    total = 0
    stack = [Path(path)]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for e in it:
                    try:
                        if e.is_dir(follow_symlinks=False):
                            stack.append(Path(e.path))
                        elif e.is_file(follow_symlinks=False):
                            total += e.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def fmt_size(n: int) -> str:
    """Tamanho para o usuário: 980 KB, 9,8 MB, 120 MB, 1,2 GB (separador decimal do idioma)."""
    n = max(0, int(n))
    if n < 1024:
        return f"{n} B"
    value, unit = float(n), "B"
    for unit in ("KB", "MB", "GB", "TB"):
        value /= 1024.0
        if value < 1023.5 or unit == "TB":  # 1023,9 KB vira "1,0 MB", não "1024 KB"
            break
    return f"{fmt_decimal(value, 1 if value < 10 else 0)} {unit}"


def disk_usage(root: str | Path | None = None, include_ffmpeg: bool = True) -> int:
    """Espaço que os componentes baixados pelo app ocupam (ferramentas + ffmpeg)."""
    base = Path(root) if root is not None else tools_dir()
    recipes = {t.id: t for t in TOOLS if t.recipe is not None}
    total = 0
    try:
        entries = list(base.iterdir()) if base.is_dir() else []
    except OSError:
        entries = []
    for p in entries:
        try:
            if p.is_dir() and p.name in recipes:  # gigabytes em milhares de arquivos: tamanho guardado
                total += recipe_size(recipes[p.name], root)[0]
            elif p.is_dir():
                total += dir_size(p)
            else:
                total += p.stat().st_size
        except OSError:
            pass
    if include_ffmpeg and ffmpeg_home().is_dir():
        total += dir_size(ffmpeg_home())
    return total


# ------------------------------------------------------------------ o que está instalado
@dataclass
class Installed:
    version: str
    path: Path
    size: int
    sha256: str = ""
    url: str = ""
    installed_at: str = ""


def version_key(version: str) -> tuple:
    """Ordem de versões: números comparados como números (1.10 > 1.9)."""
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in re.split(r"[.\-_+]", version or "") if p)


def _read_marker(folder: Path) -> dict | None:
    try:
        data = json.loads((folder / MARKER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def installed(tool: Tool, root: str | Path | None = None) -> list[Installed]:
    """Versões instaladas pelo app (a mais nova primeiro). Pastas sem o marcador não contam."""
    if tool.backend == "ffmpeg" or tool.kind != BAIXADO:
        return []
    base = tool_dir(tool, root)
    out = []
    try:
        entries = sorted(p for p in base.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return []
    for d in entries:
        data = _read_marker(d)
        if not data or data.get("id") != tool.id:
            continue
        # Receitas (gigabytes, dezenas de milhares de arquivos): o tamanho vem de recipe_size(), com cache.
        size = 0 if tool.recipe is not None else dir_size(d)
        out.append(Installed(version=str(data.get("versao") or d.name), path=d, size=size,
                             sha256=str(data.get("sha256") or ""), url=str(data.get("url") or ""),
                             installed_at=str(data.get("instalado_em") or "")))
    out.sort(key=lambda i: version_key(i.version), reverse=True)
    return out


def _pick_current(tool: Tool, found: list[Installed]) -> Installed | None:
    if not found:
        return None
    art = tool.artifact()
    want = art.version if art is not None else (tool.recipe.version if tool.recipe is not None else None)
    if want is not None:
        for i in found:
            if i.version == want:
                return i
    return found[0]


def current(tool: Tool, root: str | Path | None = None) -> Installed | None:
    """A versão em uso: a fixada no código se estiver instalada; senão a mais nova instalada."""
    return _pick_current(tool, installed(tool, root))


def executable(tool: Tool, name: str | None = None, root: str | Path | None = None) -> Path | None:
    """Caminho de um executável da versão em uso (o primeiro de `executables`, ou o que termina em `name`).

    É o que os módulos chamam para usar a ferramenta: `tools.executable(tools.get("whisper"))`.
    """
    if tool.backend == "ffmpeg":
        from . import media
        try:
            return Path(media.ffmpeg() if name in (None, "ffmpeg") else media.ffprobe())
        except RuntimeError:
            return None
    inst = current(tool, root)
    if inst is None:
        return None
    if tool.recipe is not None:  # receita: o "executável" é o Python do ambiente da instalação
        py = env_python(inst.path / ENV_DIR)
        return py if py.is_file() else None
    key = deps.platform_key()
    art = next((a for a in tool.artifacts if a.version == inst.version and a.platform == key), None) or tool.artifact()
    rels = list(art.executables) if art else []
    if name:
        rels = [r for r in rels if r.rsplit("/", 1)[-1] in (name, name + ".exe")]
    for rel in rels:
        p = inst.path / rel
        if p.is_file():
            return p
    return None


# ------------------------------------------------------------------ programas do sistema
@dataclass
class Detected:
    found: bool
    version: str = ""
    path: str = ""                       # pasta do programa (para "Abrir pasta")
    notes: list[str] = field(default_factory=list)


def _win_uninstall_version(pattern: str) -> tuple[str, str]:
    """(versão, pasta) de um programa instalado no Windows, pelo nome na lista de desinstalação."""
    if sys.platform != "win32":
        return "", ""
    import winreg
    rx = re.compile(pattern)
    roots = [(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
             (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall")]
    for hive, path in roots:
        try:
            key = winreg.OpenKey(hive, path)
        except OSError:
            continue
        with key:
            i = 0
            while True:
                try:
                    sub = winreg.EnumKey(key, i)
                except OSError:
                    break
                i += 1
                try:
                    with winreg.OpenKey(key, sub) as k:
                        name = str(winreg.QueryValueEx(k, "DisplayName")[0])
                        if not rx.match(name):
                            continue
                        version = str(winreg.QueryValueEx(k, "DisplayVersion")[0])
                        try:
                            where = str(winreg.QueryValueEx(k, "InstallLocation")[0])
                        except OSError:
                            where = ""
                        return version, where
                except OSError:
                    continue
    return "", ""


def resolve_executables() -> list[Path]:
    """Onde o instalador oficial do DaVinci Resolve põe o programa em cada sistema."""
    if sys.platform == "win32":
        pf = os.environ.get("ProgramFiles") or r"C:\Program Files"
        return [Path(pf) / "Blackmagic Design" / "DaVinci Resolve" / "Resolve.exe"]
    if sys.platform == "darwin":
        return [Path("/Applications/DaVinci Resolve/DaVinci Resolve.app")]
    return [Path("/opt/resolve/bin/resolve")]


def detect_resolve() -> Detected:
    """DaVinci Resolve: o executável nas pastas padrão ou a pasta de LUTs que o instalador cria
    (`resolve.lut_dirs()`), mais o estado do plugin do PeliculaConverter (OpenFX e DCTLs/LUTs)."""
    from . import ofx, resolve
    exe = next((p for p in resolve_executables() if p.exists()), None)
    luts = [d for d in resolve.lut_dirs() if d.is_dir()]
    if exe is None and not luts:
        return Detected(False)
    version, where = _win_uninstall_version(r"^DaVinci Resolve( Studio)?$")
    folder = str(exe.parent) if exe is not None else (where or str(luts[0]))
    notes = []
    ofx_ver = ofx.installed_version()
    notes.append(_("Plugin OpenFX do PeliculaConverter: versão {versao}").format(versao=ofx_ver) if ofx_ver
                 else _("Plugin OpenFX do PeliculaConverter: não instalado"))
    dctl_ver = resolve.installed_version(resolve.default_install_dir()) if luts else None
    notes.append(_("DCTLs e LUTs do PeliculaConverter: versão {versao}").format(versao=dctl_ver) if dctl_ver
                 else _("DCTLs e LUTs do PeliculaConverter: não instalados"))
    return Detected(True, version, folder, notes)


# id da ferramenta → função que detecta (só leitura, nada é instalado)
DETECTORS: dict[str, Callable[[], Detected]] = {"davinci_resolve": detect_resolve}


def detect(tool: Tool) -> Detected:
    fn = DETECTORS.get(tool.id)
    if fn is None:
        return Detected(False)
    try:
        return fn()
    except Exception:  # noqa: BLE001 — detecção nunca derruba a página
        return Detected(False)


# ------------------------------------------------------------------ estado para a interface
@dataclass
class Status:
    tool: Tool
    state: str
    version: str = ""                  # versão em uso ou instalada ("" = nenhuma)
    available: str = ""                # versão para baixar (fixada no código; no ffmpeg, a mais nova publicada)
    update_available: bool = False
    downloadable: bool = False         # há download para este sistema
    path: str = ""                     # o que está em uso (executável ou pasta)
    folder: str = ""                   # pasta para "Abrir pasta"
    size: int = 0                      # bytes instalados pelo app (o que "Remover" libera)
    download_size: int = 0             # bytes a baixar (0 = não se sabe)
    managed: bool = False              # há uma cópia instalada pelo app (dá para remover)
    in_use_managed: bool = False       # a cópia em uso é a do app
    verified: bool = False             # a cópia do app foi conferida com SHA-256 ao instalar
    sha256: str = ""
    source_name: str = ""              # de onde vem o download
    source_url: str = ""
    origin: str = ""                   # OFICIAL ou CI (ferramentas do registro)
    where_note: str = ""               # ao lado do caminho: "(baixado pelo app)" ou "(do sistema)"
    notes: list[str] = field(default_factory=list)  # linhas extras (ex.: estado do plugin no Resolve)
    blocked: list[str] = field(default_factory=list)  # requisitos que faltam (não oferece o download)
    partial: int = 0                   # bytes de um download incompleto guardado (continua de onde parou)

    @property
    def installed(self) -> bool:
        return self.state in (INSTALADO, DESATUALIZADO)


def _is_sha(text: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", (text or "").lower()))


def _ffmpeg_origin() -> dict[str, str]:
    """Campos do ORIGEM.txt gravado por deps.download_ffmpeg (URL, fonte, SHA-256)."""
    out = {}
    try:
        for line in (ffmpeg_home() / "ORIGEM.txt").read_text(encoding="utf-8", errors="replace").splitlines():
            k, sep, v = line.partition(":")
            if sep:
                out[k.strip().lower()] = v.strip()
    except OSError:
        pass
    return out


def _has_files(folder: Path) -> bool:
    try:
        return folder.is_dir() and any(folder.iterdir())
    except OSError:
        return False


def _ffmpeg_status(tool: Tool, latest: str) -> Status:
    from . import media
    src = deps.SOURCES.get(deps.platform_key())
    st = Status(tool, AUSENTE, downloadable=deps.platform_supported() and src is not None,
                source_name=_(src["name"]) if src else "", source_url=src.get("page", "") if src else "")
    try:
        path = media.ffmpeg()
        media.ffprobe()
    except RuntimeError:
        path = ""
    home = ffmpeg_home()
    st.managed = _has_files(deps.ffmpeg_dir())
    if st.managed:
        st.size = dir_size(home)
        st.sha256 = _ffmpeg_origin().get("sha-256", "").lower()
        st.verified = _is_sha(st.sha256)
    st.available = latest
    if path:
        info = deps.inspect(path)
        newer = deps.parse_version(latest)
        st.path, st.folder = path, str(Path(path).parent)
        st.version = info.label if info else "?"
        outdated = bool(info and info.outdated)
        st.state = DESATUALIZADO if outdated else INSTALADO
        st.update_available = outdated or bool(info and info.version and newer and info.version < newer)
        try:
            st.in_use_managed = st.managed and Path(path).resolve().parent == deps.ffmpeg_dir().resolve()
        except OSError:
            st.in_use_managed = False
        st.where_note = _("(baixado pelo app)") if st.in_use_managed else _("(do sistema)")
    elif st.managed:
        st.folder = str(home)
    if not st.downloadable and not path:
        st.state = INDISPONIVEL
    return st


def status(tool: Tool, root: str | Path | None = None, latest: str = "") -> Status:
    """Estado de um componente para a página Componentes (só lê o disco; no ffmpeg roda `-version`).

    `latest`: versão mais nova publicada do ffmpeg, se já foi consultada (`deps.latest_version()`).
    """
    if tool.backend == "ffmpeg":
        return _ffmpeg_status(tool, latest)
    if tool.recipe is not None:
        return _recipe_status(tool, root)
    if tool.kind == SISTEMA:
        det = detect(tool)
        return Status(tool, INSTALADO if det.found else AUSENTE, version=det.version, path=det.path,
                      folder=det.path, notes=list(det.notes), source_name=_(tool.name), source_url=tool.homepage)
    art = tool.artifact()
    st = Status(tool, AUSENTE if art is not None else INDISPONIVEL, downloadable=art is not None)
    if art is not None:
        st.available, st.download_size, st.origin = art.version, art.size, art.origin
        st.source_url = tool.source_url if art.origin == CI and tool.source_url else tool.homepage
    found = installed(tool, root)
    inst = _pick_current(tool, found)
    if inst is not None:
        st.version, st.path, st.folder = inst.version, str(inst.path), str(inst.path)
        st.managed = st.in_use_managed = True
        st.size = sum(i.size for i in found)
        st.sha256 = inst.sha256
        st.verified = _is_sha(inst.sha256)
        st.update_available = art is not None and inst.version != art.version
        st.state = DESATUALIZADO if st.update_available else INSTALADO
    return st


def _recipe_status(tool: Tool, root: str | Path | None = None) -> Status:
    """Estado de um componente de receita: instalado, download parcial guardado ou requisitos que faltam."""
    rec = tool.recipe
    key = deps.platform_key()
    supported = key in rec.platforms() and deps.platform_supported()
    st = Status(tool, AUSENTE if supported else INDISPONIVEL, downloadable=supported, available=rec.version,
                download_size=rec.download_size.get(key, 0), origin=OFICIAL, source_url=tool.homepage)
    base = tool_dir(tool, root)
    inst = current(tool, root)
    total, cached = recipe_size(tool, root)
    if inst is not None:
        st.version, st.path, st.folder = inst.version, str(inst.path), str(inst.path)
        st.in_use_managed = True
        st.sha256 = inst.sha256
        st.verified = _is_sha(inst.sha256)
        st.update_available = inst.version != rec.version
        st.state = DESATUALIZADO if st.update_available else INSTALADO
    st.size = total
    st.managed = total > 0
    if st.managed and not st.folder:
        st.folder = str(base)
    if inst is None and cached:
        st.partial = cached
    if not st.installed and supported:
        st.blocked = requirement_problems(tool, root)
        st.downloadable = not st.blocked
    return st


# ------------------------------------------------------------------ download
_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(tool_id: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(tool_id, threading.Lock())


def check_url(url: str) -> None:
    """Só https (ou arquivo local / servidor local, usados nos testes). O SHA-256 fixo protege o conteúdo."""
    u = urllib.parse.urlparse(url)
    ok = u.scheme == "https" and bool(u.netloc)
    ok = ok or u.scheme == "file"
    ok = ok or (u.scheme == "http" and (u.hostname or "") in ("127.0.0.1", "localhost", "::1"))
    if not ok:
        raise ToolError(_("Endereço de download não permitido: {url}").format(url=url))


def _open(url: str, timeout: float = 60.0):
    req = urllib.request.Request(url, headers={**deps.UA, "Accept": "*/*"})
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 — esquema conferido em check_url


def _fetch(url: str, dest: Path, report: Progress, cancel: threading.Event, expected_size: int,
           stage: str) -> str:
    """Baixa para `dest` calculando o SHA-256; para no meio se passar do tamanho esperado."""
    h = hashlib.sha256()
    done = 0
    with _open(url) as r, open(dest, "wb") as fh:
        total = int(r.headers.get("Content-Length") or 0) or expected_size
        if expected_size and total != expected_size:
            raise ToolError(_("O arquivo baixado não tem o tamanho esperado. Nada foi instalado."))
        report(stage, 0, total)
        while True:
            if cancel.is_set():
                raise Cancelled()
            chunk = r.read(CHUNK)
            if not chunk:
                break
            done += len(chunk)
            if expected_size and done > expected_size:
                raise ToolError(_("O arquivo baixado não tem o tamanho esperado. Nada foi instalado."))
            fh.write(chunk)
            h.update(chunk)
            report(stage, done, total)
    if expected_size and done != expected_size:
        raise ToolError(_("O arquivo baixado não tem o tamanho esperado. Nada foi instalado."))
    return h.hexdigest()


def _clean_stale(base: Path, max_age: float = STALE_SECONDS) -> None:
    """Apaga pastas temporárias esquecidas: as de remoção sempre; as de instalação depois de `max_age`."""
    try:
        entries = list(base.iterdir())
    except OSError:
        return
    now = time.time()
    for p in entries:
        if p.name.startswith(TRASH_PREFIX):
            shutil.rmtree(p, ignore_errors=True)
        elif p.name.startswith(STAGING_PREFIX):
            try:
                old = now - p.stat().st_mtime > max_age
            except OSError:
                continue
            if old:
                shutil.rmtree(p, ignore_errors=True)


def _check_space(folder: Path, art: Artifact) -> None:
    need = art.size + (art.unpacked_size or art.size * 3) + (64 << 20)
    try:
        free = shutil.disk_usage(folder).free
    except OSError:
        return
    if free < need:
        raise ToolError(_("Espaço insuficiente em {pasta}: são precisos {precisa} e há {livre} livres.").format(
            pasta=folder, precisa=fmt_size(need), livre=fmt_size(free)))


def _move_aside(path: Path, parent: Path) -> Path:
    """Tira uma pasta do caminho com um `rename` (instantâneo); devolve onde ela ficou.

    No Windows, o antivírus segura por instantes os executáveis recém-instalados: tenta de novo por alguns
    segundos antes de desistir (um arquivo aberto de verdade continua impedindo e dá `PermissionError`).
    """
    trash = parent / f"{TRASH_PREFIX}{path.name}-{secrets.token_hex(4)}"
    system.replace_file(path, trash, wait=5.0)
    return trash


def download(tool: Tool, progress: Progress | None = None, cancel: threading.Event | None = None,
             root: str | Path | None = None, keep_old: bool = False) -> Installed:
    """Baixa, confere o SHA-256 fixo, extrai e instala de uma vez. Devolve a versão instalada.

    Nada é extraído antes de o SHA-256 conferir; qualquer falha (hash, tamanho, caminho suspeito no
    pacote, cancelamento) deixa a instalação anterior como estava e não deixa sobras. Levanta
    `ToolError` (mensagem para o usuário) ou `Cancelled`.
    """
    cancel = cancel or threading.Event()

    def report(stage: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress(stage, done, total)

    if tool.backend == "ffmpeg":
        dest = deps.download_ffmpeg(progress, cancel)
        origin = _ffmpeg_origin()
        info = deps.inspect(str(dest / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg")))
        return Installed(version=info.label if info else "", path=dest.parent, size=dir_size(dest.parent),
                         sha256=origin.get("sha-256", ""), url=origin.get("baixado de", ""))
    if tool.kind != BAIXADO:
        raise ToolError(_("{nome} é um programa do sistema: instale pelo site oficial.").format(nome=_(tool.name)))
    if tool.recipe is not None:
        return install_recipe(tool, progress, cancel, root, keep_old)
    art = tool.artifact()
    if art is None:
        raise ToolError(_("{nome} ainda não tem download para este sistema.").format(nome=_(tool.name)))
    check_url(art.url)
    base = tool_dir(tool, root)
    with _lock_for(tool.id):
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ToolError(_("Não foi possível instalar em {pasta}:\n{erro}").format(pasta=base, erro=exc)) from exc
        _clean_stale(base)
        _check_space(base, art)
        staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=base))
        try:
            name = art.url.rsplit("/", 1)[-1].split("?", 1)[0] or "download"
            archive = staging / ("pacote-" + re.sub(r"[^A-Za-z0-9._-]", "_", name))
            stage = _("Baixando {nome}…").format(nome=_(tool.name))
            try:
                digest = _fetch(art.url, archive, report, cancel, art.size, stage)
            except (ToolError, Cancelled):
                raise
            except OSError as exc:
                raise ToolError(_("Falha no download de {nome}: {erro}").format(nome=_(tool.name), erro=exc)) from exc
            report(_("Conferindo o SHA-256…"))
            if digest.lower() != art.sha256.lower():
                raise ToolError(_("O arquivo baixado não confere com o SHA-256 fixado no app. Nada foi instalado."))
            if cancel.is_set():
                raise Cancelled()
            report(_("Extraindo…"))
            content = staging / "conteudo"
            if art.archive == "arquivo":
                content.mkdir()
                rel = art.executables[0] if art.executables else name
                if not deps.safe_member(rel):
                    raise ToolError(_("Caminho suspeito dentro do arquivo: {caminho}").format(caminho=rel))
                (content / rel).parent.mkdir(parents=True, exist_ok=True)
                archive.replace(content / rel)
            else:
                try:
                    deps.extract_archive(archive, content, art.archive)
                except ToolError:
                    raise
                except Exception as exc:  # noqa: BLE001 — pacote ruim ou caminho suspeito
                    raise ToolError(str(exc)) from exc
                archive.unlink(missing_ok=True)
            for rel in art.executables:
                p = content / rel
                if not deps.safe_member(rel) or not p.is_file():
                    raise ToolError(_("{arquivo} não foi encontrado no pacote baixado.").format(arquivo=rel))
                if sys.platform != "win32":
                    p.chmod(p.stat().st_mode | 0o755)
            if cancel.is_set():
                raise Cancelled()
            report(_("Instalando…"))
            marker = {"id": tool.id, "versao": art.version, "plataforma": art.platform, "url": art.url,
                      "sha256": art.sha256.lower(), "tamanho": art.size, "origem": art.origin,
                      "instalado_em": time.strftime("%Y-%m-%dT%H:%M:%S"), "app": f"{APP_NAME} {__version__}"}
            (content / MARKER).write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
            final = base / art.version
            aside = None
            try:
                if final.exists():
                    aside = _move_aside(final, staging)  # a mesma versão de novo: a antiga sai inteira
                # O antivírus do Windows examina por instantes os programas recém-criados: a troca de
                # pasta tenta de novo por alguns segundos antes de desistir.
                system.replace_file(content, final, wait=30.0)
            except OSError as exc:
                if aside is not None and not final.exists():
                    try:
                        aside.rename(final)  # devolve a instalação anterior
                    except OSError:
                        pass
                raise ToolError(_("Não foi possível instalar em {pasta}: algum arquivo está em uso? Feche o que "
                                  "estiver usando {nome} e tente de novo.\n\n{erro}").format(
                    pasta=final, nome=_(tool.name), erro=exc)) from exc
            if not keep_old:
                for other in installed(tool, root):
                    if other.path != final:
                        try:
                            shutil.rmtree(_move_aside(other.path, base), ignore_errors=True)
                        except OSError:
                            pass  # em uso: fica para a próxima vez
            report(_("Pronto."), 1, 1)
            return Installed(version=art.version, path=final, size=dir_size(final), sha256=art.sha256.lower(),
                             url=art.url, installed_at=marker["instalado_em"])
        finally:
            shutil.rmtree(staging, ignore_errors=True)


# ------------------------------------------------------------------ remover
def remove(tool: Tool, root: str | Path | None = None, version: str | None = None) -> int:
    """Remove o que o app instalou (uma versão ou todas). Devolve os bytes liberados.

    A pasta sai do lugar com um `rename` (instantâneo) e só depois é apagada; se algum arquivo
    estiver em uso, nada muda e vem um `ToolError`.
    """
    if tool.backend == "ffmpeg":
        target, parent = ffmpeg_home(), deps.app_data_dir()
    elif tool.kind != BAIXADO:
        raise ToolError(_("{nome} é um programa do sistema: desinstale pelo próprio sistema.").format(
            nome=_(tool.name)))
    else:
        if version is not None and (not version or not deps.safe_member(version) or "/" in version
                                    or "\\" in version or version.startswith(".")):
            raise ValueError(f"versão inválida: {version!r}")
        base = tool_dir(tool, root)
        target, parent = (base / version if version else base), (base if version else base.parent)
    _clean_stale(parent)
    if not target.exists():
        return 0
    size = dir_size(target)
    try:
        trash = _move_aside(target, parent)
    except OSError as exc:
        raise ToolError(_("Não foi possível remover {nome}: algum arquivo está em uso. Feche o que estiver usando "
                          "e tente de novo.\n\n{erro}").format(nome=_(tool.name), erro=exc)) from exc
    shutil.rmtree(trash, ignore_errors=True)
    return size


# ------------------------------------------------------------------ processos (uv e o Python dos ambientes)
DATA_DIR = Path(__file__).resolve().parent / "data"  # listas travadas e manifestos (dentro do pacote)
PYTHON_DIR = "python"   # ferramentas/<id>/python: Python base dos ambientes (fora da pasta trocada no fim)
CACHE_DIR = "cache"     # ferramentas/<id>/cache: downloads retomáveis (a limpeza de 12 h não mexe aqui)
ENV_DIR = "venv"        # <versão>/venv: o ambiente Python da instalação
TAIL = 80               # linhas guardadas da saída de um processo (para a mensagem de erro)

# Variáveis do usuário que mudariam o uv ou o Python de um ambiente (índices, configuração, outro Python...).
_ENV_DROP = ("UV_", "PIP_", "PYTHON", "VIRTUAL_ENV", "CONDA_", "PYENV")
_SPLIT = re.compile(rb"[\r\n]+")


def data_path(rel: str | Path) -> Path:
    """Arquivo de dados do app (`pelicula/data`); caminho absoluto fica como está (testes)."""
    return DATA_DIR / rel


def env_python(venv: str | Path) -> Path:
    """O Python de um ambiente criado pelo uv (Scripts/python.exe no Windows, bin/python no Linux)."""
    v = Path(venv)
    return v / "Scripts" / "python.exe" if sys.platform == "win32" else v / "bin" / "python"


def clean_environ(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Variáveis de ambiente do sistema sem as que mudariam o uv ou o Python (PYTHONPATH, UV_INDEX...)."""
    env = {k: v for k, v in os.environ.items() if not k.upper().startswith(_ENV_DROP)}
    env.update(extra or {})
    return env


def runtime_environ(extra: dict[str, str] | None = None,
                    path_first: list[str] | tuple[str, ...] = ()) -> dict[str, str]:
    """Ambiente para rodar o Python de uma receita: saída sem buffer em UTF-8, sem pacotes do usuário,
    caches do PyTorch e do Hugging Face na pasta do app e, se pedido, pastas na frente do PATH."""
    cache = deps.app_data_dir() / "cache"
    env = clean_environ({"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "PYTHONNOUSERSITE": "1",
                         "HF_HOME": str(cache / "huggingface"), "TORCH_HOME": str(cache / "torch")})
    if path_first:
        env["PATH"] = os.pathsep.join([*map(str, path_first), env.get("PATH", "")])
    env.update(extra or {})
    return env


def popen_group_kwargs(perf=None) -> dict:
    """Processo num grupo próprio (cancelar encerra também os filhos), sem janela no Windows.

    `perf`: um `media.Perf` (prioridade do processo, regra 11 do AGENTS.md).
    """
    kw = dict(perf.popen_kwargs()) if perf is not None else {}
    if sys.platform == "win32":
        kw["creationflags"] = kw.get("creationflags", 0) | deps.NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    return kw


def kill_tree(proc: subprocess.Popen, timeout: float = 15.0) -> None:
    """Encerra um processo e todos os filhos dele (taskkill /T no Windows, o grupo no Linux)."""
    if proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=timeout,
                           creationflags=deps.NO_WINDOW)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        proc.kill()
    except OSError:
        pass
    try:
        proc.wait(timeout)
    except subprocess.TimeoutExpired:
        pass


@dataclass
class ProcessResult:
    returncode: int
    lines: list[str]

    def tail(self, n: int = 15) -> str:
        return "\n".join(self.lines[-n:])


def _pump(stream, sink: Callable[[str], None]) -> None:
    """Lê a saída do processo em linhas (também as que só terminam em \\r, das barras de progresso)."""
    buf = b""
    try:
        while True:
            chunk = stream.read1(65536)
            if not chunk:
                break
            buf += chunk
            *lines, buf = _SPLIT.split(buf)
            for raw in lines:
                text = raw.decode("utf-8", "replace").strip()
                if text:
                    sink(text)
    except (OSError, ValueError):
        pass
    text = buf.decode("utf-8", "replace").strip()
    if text:
        sink(text)


def run_process(cmd, *, cwd=None, env: dict[str, str] | None = None, cancel: threading.Event | None = None,
                on_line: Callable[[str], None] | None = None, timeout: float | None = None,
                perf=None) -> ProcessResult:
    """Roda um programa externo lendo a saída linha a linha; cancelar encerra o processo e os filhos.

    `on_line(linha)` roda na thread de leitura. Levanta `Cancelled` se `cancel` for ligado e
    `ToolError` se o programa não puder ser executado ou passar de `timeout` segundos.
    """
    cancel = cancel or threading.Event()
    if cancel.is_set():
        raise Cancelled()
    tail: collections.deque[str] = collections.deque(maxlen=TAIL)

    def sink(line: str) -> None:
        tail.append(line)
        if on_line is not None:
            try:
                on_line(line)
            except Exception:  # noqa: BLE001 — quem lê a saída nunca derruba o processo
                pass

    args = [str(c) for c in cmd]
    try:
        proc = subprocess.Popen(args, cwd=str(cwd) if cwd else None, env=env, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, **popen_group_kwargs(perf))
    except OSError as exc:
        raise ToolError(_("Não foi possível executar {programa}:\n{erro}").format(
            programa=Path(args[0]).name, erro=exc)) from exc
    reader = threading.Thread(target=_pump, args=(proc.stdout, sink), daemon=True, name="saida-processo")
    reader.start()
    deadline = None if timeout is None else time.monotonic() + timeout
    try:
        while proc.poll() is None:
            if cancel.wait(0.2):
                kill_tree(proc)
                raise Cancelled()
            if deadline is not None and time.monotonic() > deadline:
                kill_tree(proc)
                raise ToolError(_("{programa} demorou demais e foi encerrado.").format(programa=Path(args[0]).name))
    finally:
        if proc.poll() is None:
            kill_tree(proc)
        reader.join(10)
        try:
            proc.stdout.close()
        except (OSError, AttributeError):
            pass
    return ProcessResult(proc.returncode, list(tail))


# ------------------------------------------------------------------ download retomável
def _open_from(url: str, start: int = 0, timeout: float = 60.0):
    """Abre a URL pedindo os bytes a partir de `start` (cabeçalho Range) quando um download continua."""
    headers = {**deps.UA, "Accept": "*/*"}
    if start:
        headers["Range"] = f"bytes={start}-"
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout)  # noqa: S310


def fetch_file(url: str, dest: str | Path, sha256: str = "", size: int = 0, progress: Progress | None = None,
               cancel: threading.Event | None = None, stage: str = "", offset: int = 0, overall: int = 0,
               max_size: int = 0) -> Path:
    """Baixa `url` em `dest`, continuando de `dest.part` se um download anterior parou no meio.

    Com `sha256` e `size` (fixos no código) tudo é conferido antes de o arquivo ganhar o nome final:
    um arquivo com o nome final está sempre completo e conferido (e não é baixado de novo). O `.part`
    de um download interrompido (rede, cancelar, app fechado) fica para continuar depois; o que não
    confere é apagado. `offset`/`overall`: progresso de um conjunto de arquivos (bytes).
    """
    check_url(url)
    dest = Path(dest)
    cancel = cancel or threading.Event()

    def report(done: int, total: int) -> None:
        if progress:
            progress(stage, done, total)

    if dest.is_file() and (not size or dest.stat().st_size == size):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    have = part.stat().st_size if part.is_file() else 0
    if size and have > size:
        part.unlink()
        have = 0
    h = hashlib.sha256()
    if have:  # confere de novo o que já veio: o hash continua dali
        with open(part, "rb") as fh:
            for chunk in iter(lambda: fh.read(CHUNK * 8), b""):
                if cancel.is_set():
                    raise Cancelled()
                h.update(chunk)
    total = overall or size
    wrong_size = _("O arquivo baixado não tem o tamanho esperado. Nada foi instalado.")
    if not size or have < size:
        try:
            resp = _open_from(url, have)
        except urllib.error.HTTPError as exc:
            if exc.code != 416 or not have:
                raise ToolError(_("Falha no download: {erro}").format(erro=exc)) from exc
            part.unlink(missing_ok=True)  # o servidor não aceita continuar daqui: recomeça
            have, h = 0, hashlib.sha256()
            try:
                resp = _open_from(url, 0)
            except OSError as exc2:
                raise ToolError(_("Falha no download: {erro}").format(erro=exc2)) from exc2
        except OSError as exc:
            raise ToolError(_("Falha no download: {erro}").format(erro=exc)) from exc
        with resp as r:
            status = getattr(r, "status", None) or getattr(r, "code", None)
            content_range = str(r.headers.get("Content-Range") or "")
            if have and (status != 206 or not content_range.startswith(f"bytes {have}-")):
                have, h = 0, hashlib.sha256()  # veio o arquivo inteiro: recomeça do zero
            length = int(r.headers.get("Content-Length") or 0)
            if size and length and have + length != size:
                part.unlink(missing_ok=True)
                raise ToolError(wrong_size)
            done = have
            report(offset + done, total)
            try:
                with open(part, "ab" if have else "wb") as fh:
                    while True:
                        if cancel.is_set():
                            raise Cancelled()
                        chunk = r.read(CHUNK)
                        if not chunk:
                            break
                        done += len(chunk)
                        if (size and done > size) or (max_size and done > max_size):
                            raise ToolError(wrong_size)
                        fh.write(chunk)
                        h.update(chunk)
                        report(offset + done, total)
            except ToolError:
                part.unlink(missing_ok=True)
                raise
            except (OSError, http.client.HTTPException) as exc:  # a conexão caiu: o .part fica para continuar
                raise ToolError(_("O download parou no meio ({erro}). Tente de novo: ele continua de onde "
                                  "parou.").format(erro=exc)) from exc
    got = part.stat().st_size if part.is_file() else 0
    if size and got != size:
        raise ToolError(_("O download parou no meio. Tente de novo: ele continua de onde parou."))
    if sha256 and h.hexdigest() != sha256.lower():
        part.unlink(missing_ok=True)
        raise ToolError(_("O arquivo baixado não confere com o SHA-256 fixado no app. Nada foi instalado."))
    os.replace(part, dest)
    return dest


# ------------------------------------------------------------------ código conferido por manifesto
def read_manifest(rel: str | Path) -> dict[str, str]:
    """Manifesto `<sha256>  <caminho>` (linhas com # são comentários) → {caminho: sha256}."""
    out: dict[str, str] = {}
    for line in data_path(rel).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _sep, path = line.partition("  ")
        if not _is_sha(digest) or not path or not deps.safe_member(path):
            raise ToolError(_("Manifesto inválido: {arquivo}").format(arquivo=rel))
        out[path] = digest.lower()
    return out


def install_source(src: SourceZip, dest: Path, work: Path, progress: Progress | None = None,
                   cancel: threading.Event | None = None) -> Path:
    """Baixa o zip de um commit, confere cada arquivo contra o manifesto e grava só os do manifesto em `dest`."""
    manifest = read_manifest(src.manifest)
    work.mkdir(parents=True, exist_ok=True)
    archive = work / f"codigo-{secrets.token_hex(4)}.zip"
    fetch_file(src.url, archive, progress=progress, cancel=cancel, stage=_("Baixando o código…"),
               max_size=src.max_size)
    seen: set[str] = set()
    try:
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                if not deps.safe_member(info.filename):
                    raise ToolError(_("Caminho suspeito dentro do arquivo: {caminho}").format(caminho=info.filename))
                rel = info.filename.split("/", 1)[1] if "/" in info.filename else info.filename  # tira <repo>-<commit>/
                if rel not in manifest:
                    continue  # fora do manifesto: não é instalado (os .bat/.sh dos autores, por exemplo)
                data = zf.read(info)
                if hashlib.sha256(data).hexdigest() != manifest[rel]:
                    raise ToolError(_("O código baixado não confere com o SHA-256 fixado no app ({arquivo}). Nada "
                                      "foi instalado.").format(arquivo=rel))
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                seen.add(rel)
    except zipfile.BadZipFile as exc:
        raise ToolError(_("O código baixado está corrompido. Tente de novo.")) from exc
    finally:
        archive.unlink(missing_ok=True)
    missing = sorted(set(manifest) - seen)
    if missing:
        raise ToolError(_("Falta um arquivo no código baixado ({arquivo}). Nada foi instalado.").format(
            arquivo=missing[0]))
    return dest


# ------------------------------------------------------------------ ambiente Python com o uv (receita genérica)
def uv_command(progress: Progress | None = None, cancel: threading.Event | None = None,
               root: str | Path | None = None) -> list[str]:
    """O uv fixado (`UV_VERSION`), baixado do GitHub da Astral se faltar. Devolve a linha de comando.

    Outras versões instaladas ficam (`keep_old`): cada ambiente pede a versão com que foi testado.
    """
    if not any(i.version == UV_VERSION for i in installed(UV, root)):
        download(UV, progress, cancel, root=root, keep_old=True)
    exe = executable(UV, root=root)
    if exe is None or not exe.is_relative_to(tool_dir(UV, root) / UV_VERSION):
        raise ToolError(_("{arquivo} não foi encontrado no pacote baixado.").format(arquivo="uv"))
    return [str(exe)]


def uv_environ(cache: Path, python_dir: Path) -> dict[str, str]:
    """Variáveis do uv: cache e Python numa pasta própria, sem configuração do usuário nem barra de progresso."""
    return clean_environ({"UV_CACHE_DIR": str(cache / "uv"), "UV_PYTHON_INSTALL_DIR": str(python_dir),
                          "UV_NO_CONFIG": "1", "UV_NO_PROGRESS": "1", "UV_PYTHON_DOWNLOADS": "manual",
                          "UV_HTTP_TIMEOUT": "300", "NO_COLOR": "1"})


def _uv_failure(message: str, res: ProcessResult) -> ToolError:
    low = "\n".join(res.lines).lower()
    hints = []
    if "certificate" in low or "tls" in low or "ssl" in low:
        hints.append(_("A conexão segura (HTTPS) foi recusada. Se um antivírus examina as conexões HTTPS, "
                       "permita o uv nele e tente de novo."))
    elif any(k in low for k in ("failed to fetch", "connect", "timed out", "dns", "network")):
        hints.append(_("Confira a conexão com a internet e tente de novo: o que já foi baixado não se perde."))
    if "no space" in low or "os error 112" in low or "os error 28" in low:
        hints.append(_("O disco ficou sem espaço."))
    return ToolError("\n\n".join([message, *hints, res.tail(12)]).strip())


def _uv(cmd: list[str], env: dict[str, str], cwd: Path, cancel: threading.Event, failure: str) -> ProcessResult:
    res = run_process(cmd, cwd=cwd, env=env, cancel=cancel)
    if res.returncode != 0:
        raise _uv_failure(failure, res)
    return res


class _SizeWatch:
    """Relata o tamanho de uma pasta a cada 2 s (progresso do download das bibliotecas pelo uv)."""

    def __init__(self, folder: Path, report: Callable[[int], None], every: float = 2.0):
        self.folder, self.report, self.every = folder, report, every
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True, name="tamanho-cache")

    def _run(self) -> None:
        while not self.stop.wait(self.every):
            self.report(dir_size(self.folder))

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.stop.set()
        self.thread.join(5)


def build_env(spec: PythonEnv, venv: str | Path, *, python_dir: str | Path, cache: str | Path, uv: list[str],
              progress: Progress | None = None, cancel: threading.Event | None = None,
              packages: list[Path] | tuple[Path, ...] = ()) -> Path:
    """Monta um ambiente Python isolado com o uv e devolve o Python dele (receita genérica).

    1. `uv python install <versão>` em `python_dir` (o Python base; sem atalhos no PATH nem registro do
       Windows). Ele fica fora de `venv`: o ambiente aponta para ele por caminho absoluto, então `venv`
       pode ser montado numa pasta temporária e trocado de lugar depois (`--relocatable`).
    2. `uv venv <venv> --relocatable`.
    3. `uv pip install --require-hashes -r <lista travada>` (só wheels; PyTorch do índice `spec.torch`).
       Sempre `--system-certs` (o antigo `--native-tls`: certificados do sistema, que funcionam com
       antivírus que examinam HTTPS). O que já foi baixado fica no cache do uv em `cache/uv`.
    4. Pacotes locais (`packages`, já conferidos) sem dependências e sem rede.
    """
    key = deps.platform_key()
    rel = spec.requirements.get(key)
    if not rel:
        raise ToolError(_("Este componente ainda não tem download para este sistema."))
    req = data_path(rel)
    if not req.is_file():
        raise ToolError(_("A lista de bibliotecas do componente não foi encontrada: {arquivo}").format(arquivo=req))
    cancel = cancel or threading.Event()

    def report(stage: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress(stage, done, total)

    venv, python_dir, cache = Path(venv), Path(python_dir), Path(cache)
    python_dir.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    env = uv_environ(cache, python_dir)
    net = ["--system-certs"]

    report(_("Instalando o Python {versao}…").format(versao=spec.python))
    cmd = [*uv, "python", "install", spec.python, "--install-dir", str(python_dir), "--no-bin", *net]
    if sys.platform == "win32":
        cmd.append("--no-registry")
    failure = _("Não foi possível instalar o Python {versao}.").format(versao=spec.python)
    _uv(cmd, env, cache, cancel, failure)
    res = _uv([*uv, "python", "find", spec.python, "--managed-python", "--no-project"], env, cache, cancel, failure)
    base = Path(res.lines[-1].strip()) if res.lines else Path()
    try:
        inside = base.is_file() and base.resolve().is_relative_to(python_dir.resolve())
    except OSError:
        inside = False
    if not inside:
        raise ToolError(failure + "\n\n" + res.tail(5))
    if cancel.is_set():
        raise Cancelled()

    report(_("Criando o ambiente Python…"))
    _uv([*uv, "venv", str(venv), "--python", str(base), "--relocatable", "--no-project"], env, cache, cancel,
        _("Não foi possível criar o ambiente Python."))
    py = env_python(venv)

    stage = _("Baixando e instalando as bibliotecas…")
    total = spec.size.get(key, 0)
    report(stage, 0, total)
    cmd = [*uv, "pip", "install", "--python", str(py), "--require-hashes", "--only-binary", ":all:", "-r", str(req),
           *net]
    if spec.torch:
        cmd += ["--torch-backend", spec.torch]
    with _SizeWatch(cache / "uv", lambda n: report(stage, n, max(total, n))):
        _uv(cmd, env, cache, cancel, _("Não foi possível instalar as bibliotecas."))
    for pkg in packages:
        report(_("Instalando {pacote}…").format(pacote=Path(pkg).name))
        _uv([*uv, "pip", "install", "--python", str(py), "--no-deps", "--no-build-isolation", "--offline", str(pkg)],
            env, cache, cancel, _("Não foi possível instalar {pacote}.").format(pacote=Path(pkg).name))
    return py


# ------------------------------------------------------------------ requisitos e instalação de receitas
def _corridorkey_requirements() -> list[str]:
    from . import corridorkey
    return corridorkey.requirement_problems()


# id da ferramenta → função que diz o que falta no computador para baixá-la (lista vazia = tudo certo)
REQUIREMENTS: dict[str, Callable[[], list[str]]] = {"corridorkey": _corridorkey_requirements}

_sizes: dict[str, tuple[tuple, tuple[int, int]]] = {}  # pasta → (carimbo, (total, cache))
_sizes_lock = threading.Lock()


def _stamp(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return -1.0


def recipe_size(tool: Tool, root: str | Path | None = None) -> tuple[int, int]:
    """(bytes na pasta do componente, bytes de downloads guardados no cache). Guardado até a pasta mudar."""
    base = tool_dir(tool, root)
    if not base.is_dir():
        return 0, 0
    cache = base / CACHE_DIR
    try:
        marks = tuple(_stamp(p / MARKER) for p in sorted(base.iterdir()) if p.is_dir())
    except OSError:
        marks = ()
    stamp = (_stamp(base), _stamp(cache), _stamp(cache / "arquivos"), marks)
    with _sizes_lock:
        hit = _sizes.get(str(base))
        if hit is not None and hit[0] == stamp:
            return hit[1]
    found = (dir_size(base), dir_size(cache))
    with _sizes_lock:
        _sizes[str(base)] = (stamp, found)
    return found


def _need_space(rec: Recipe, cached: int) -> int:
    return max(0, rec.disk_size.get(deps.platform_key(), 0) - cached) + (1 << 30)


def _free_space(folder: Path) -> int | None:
    p = folder
    while not p.exists() and p.parent != p:
        p = p.parent
    try:
        return shutil.disk_usage(p).free
    except OSError:
        return None


def requirement_problems(tool: Tool, root: str | Path | None = None) -> list[str]:
    """O que impede baixar o componente neste computador (placa de vídeo, espaço livre...)."""
    out: list[str] = []
    fn = REQUIREMENTS.get(tool.id)
    if fn is not None:
        try:
            out += list(fn())
        except Exception:  # noqa: BLE001 — a checagem nunca derruba a página
            pass
    if tool.recipe is not None:
        base = tool_dir(tool, root)
        need = _need_space(tool.recipe, recipe_size(tool, root)[1])
        free = _free_space(base)
        if free is not None and free < need:
            out.append(_("Espaço insuficiente: são precisos cerca de {precisa} livres em {pasta} e há {livre}.").format(
                precisa=fmt_size(need), pasta=base.parent, livre=fmt_size(free)))
    return out


def _place(src: Path, dst: Path, moved: list[tuple[Path, Path]]) -> None:
    """Põe um arquivo do cache na instalação: link (instantâneo, o cache continua inteiro) ou, se o disco
    não aceitar links, movendo (e anotando para devolver ao cache se a instalação falhar)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        os.replace(src, dst)
        moved.append((src, dst))


def _same_path(a: str | Path, b: str | Path) -> bool:
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except (OSError, ValueError):
        return False


def _check_failure(tool: Tool, res: ProcessResult) -> ToolError:
    low = "\n".join(res.lines).lower()
    if "out of memory" in low:
        msg = _("O teste de {nome} ficou sem memória na placa de vídeo. Feche outros programas que usam a placa e "
                "tente de novo.").format(nome=_(tool.name))
    elif "cuda" in low and any(k in low for k in ("driver", "available", "requires cuda", "no cuda", "cudaerror")):
        msg = _("O teste de {nome} na placa de vídeo falhou. Atualize o driver da NVIDIA e tente de novo.").format(
            nome=_(tool.name))
    else:
        msg = _("O teste de {nome} falhou.").format(nome=_(tool.name))
    return ToolError(msg + "\n\n" + res.tail(12))


def run_check(tool: Tool, folder: str | Path, cancel: threading.Event | None = None,
              on_line: Callable[[str], None] | None = None) -> ProcessResult:
    """Roda o teste da receita (`Recipe.check`) com o Python da instalação em `folder`."""
    rec = tool.recipe
    if rec is None or not rec.check:
        return ProcessResult(0, [])
    folder = Path(folder)
    py = env_python(folder / ENV_DIR)
    if not py.is_file():
        raise ToolError(_("{nome} não está instalado.").format(nome=_(tool.name)))
    from . import media
    ffmpeg = media.tool_dir()
    env = runtime_environ(rec.check_env, [ffmpeg] if ffmpeg else ())
    res = run_process([py, *rec.check], cwd=folder / rec.workdir, env=env, cancel=cancel, on_line=on_line,
                      timeout=rec.check_timeout)
    if res.returncode != 0:
        raise _check_failure(tool, res)
    return res


def test_installed(tool: Tool, progress: Progress | None = None, cancel: threading.Event | None = None,
                   root: str | Path | None = None) -> str:
    """Botão "Testar" do cartão: roda o teste da receita na versão em uso. Devolve o fim da saída."""
    inst = current(tool, root)
    if inst is None:
        raise ToolError(_("{nome} não está instalado.").format(nome=_(tool.name)))
    if progress:
        progress(_("Testando {nome}…").format(nome=_(tool.name)), 0, 0)
    return run_check(tool, inst.path, cancel).tail(6)


OWNER = ".dono"  # dentro da pasta temporária de uma receita: o PID do processo do app que a montou


def _process_alive(pid: int) -> bool:
    """Se o processo `pid` ainda existe (na dúvida, sim: a pasta dele fica para a limpeza de 12 h)."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ctypes.get_last_error() == 5  # acesso negado: o processo existe
        try:
            code = ctypes.c_ulong()
            return not kernel.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259  # STILL_ACTIVE
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _clean_orphans(base: Path) -> None:
    """Apaga já as pastas temporárias de receitas cujo app não existe mais (fechado ou travado no meio).

    Uma receita deixa gigabytes numa pasta `.novo-*`; esperar as 12 h de `_clean_stale` ocuparia esse
    espaço à toa. Com a trava da ferramenta na mão, uma pasta deste mesmo processo também é sobra.
    """
    for p in base.glob(STAGING_PREFIX + "*"):
        try:
            pid = int((p / OWNER).read_text(encoding="ascii").strip())
        except (OSError, ValueError):
            continue  # sem dono conhecido: fica para a limpeza de 12 h
        if pid == os.getpid() or not _process_alive(pid):
            shutil.rmtree(p, ignore_errors=True)


def recipe_fingerprint(tool: Tool) -> str:
    """SHA-256 do que a receita fixa (listas travadas, manifestos, arquivos): o "selo" da instalação."""
    rec = tool.recipe
    h = hashlib.sha256()
    h.update(f"{tool.id} {rec.version} {rec.env.python} {rec.env.torch}\n".encode())
    for rel in sorted(rec.env.requirements.values()) + [z.manifest for z in rec.code]:
        try:
            h.update(hashlib.sha256(data_path(rel).read_bytes()).hexdigest().encode())
        except OSError:
            h.update(str(rel).encode())
    for p in rec.files:
        h.update(f"{p.sha256} {p.dest}\n".encode())
    return h.hexdigest()


def install_recipe(tool: Tool, progress: Progress | None = None, cancel: threading.Event | None = None,
                   root: str | Path | None = None, keep_old: bool = False) -> Installed:
    """Instala um componente de receita (código + ambiente Python + modelos) de uma vez.

    Ordem: requisitos e espaço → uv → código (conferido arquivo por arquivo) → Python e bibliotecas
    (`build_env`) → modelos (retomáveis, SHA-256) → teste da receita → troca para a pasta da versão →
    o Python ainda roda na pasta nova → `pelicula-origem.json`. Só com o marcador a instalação conta
    como instalada. Os downloads ficam em `cache/` até o fim: cancelar, falhar ou fechar o app não
    perde o que já veio; depois da instalação o cache é apagado (os modelos já estão na instalação).
    """
    rec = tool.recipe
    cancel = cancel or threading.Event()

    def report(stage: str, done: int = 0, total: int = 0) -> None:
        if progress:
            progress(stage, done, total)

    key = deps.platform_key()
    if key not in rec.platforms() or not deps.platform_supported():
        raise ToolError(_("{nome} ainda não tem download para este sistema.").format(nome=_(tool.name)))
    problems = requirement_problems(tool, root)
    if problems:
        raise ToolError("\n".join(problems))
    base = tool_dir(tool, root)
    with _lock_for(tool.id):
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise ToolError(_("Não foi possível instalar em {pasta}:\n{erro}").format(pasta=base, erro=exc)) from exc
        _clean_stale(base)
        _clean_orphans(base)
        uv = uv_command(progress, cancel, root)
        cache = base / CACHE_DIR
        staging = Path(tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=base))
        moved: list[tuple[Path, Path]] = []
        try:
            (staging / OWNER).write_text(str(os.getpid()), encoding="ascii")
            content = staging / "conteudo"
            content.mkdir()
            packages = []
            for src in rec.code:
                if cancel.is_set():
                    raise Cancelled()
                target = staging / "pacotes" / src.dest if src.package else content / src.dest
                install_source(src, target, staging / "zips", progress, cancel)
                if src.package:
                    packages.append(target)
            build_env(rec.env, content / ENV_DIR, python_dir=base / PYTHON_DIR, cache=cache, uv=uv,
                      progress=progress, cancel=cancel, packages=packages)
            total = sum(p.size for p in rec.files)
            done = 0
            for piece in rec.files:
                if cancel.is_set():
                    raise Cancelled()
                cached = fetch_file(piece.url, cache / "arquivos" / piece.sha256, piece.sha256, piece.size, progress,
                                    cancel, _("Baixando os modelos…"), offset=done, overall=total)
                done += piece.size
                _place(cached, content / piece.dest, moved)
            if cancel.is_set():
                raise Cancelled()
            report(_("Testando {nome}…").format(nome=_(tool.name)))
            run_check(tool, content, cancel)
            report(_("Instalando…"))
            final = base / rec.version
            aside = None
            try:
                if final.exists():
                    aside = _move_aside(final, staging)  # a mesma versão de novo: a antiga sai inteira
                # O antivírus do Windows examina por instantes os programas recém-criados: a troca de
                # pasta tenta de novo por alguns segundos antes de desistir.
                system.replace_file(content, final, wait=30.0)
            except OSError as exc:
                if aside is not None and not final.exists():
                    try:
                        aside.rename(final)
                    except OSError:
                        pass
                raise ToolError(_("Não foi possível instalar em {pasta}: algum arquivo está em uso? Feche o que "
                                  "estiver usando {nome} e tente de novo.\n\n{erro}").format(
                    pasta=final, nome=_(tool.name), erro=exc)) from exc
            moved.clear()  # o que foi movido do cache agora é da instalação
            # A pasta mudou de lugar: o Python do ambiente precisa continuar achando o Python base e a si mesmo.
            probe = run_process([env_python(final / ENV_DIR), "-c", "import sys; print(sys.prefix)"],
                                env=runtime_environ(), cancel=cancel, timeout=120)
            prefix = probe.lines[-1] if probe.lines else ""
            if probe.returncode != 0 or not _same_path(prefix, final / ENV_DIR):
                shutil.rmtree(_move_aside(final, base), ignore_errors=True)
                raise ToolError(_("O ambiente Python de {nome} não funcionou depois de instalado. Nada foi "
                                  "instalado.").format(nome=_(tool.name)) + "\n\n" + probe.tail(6))
            marker = {"id": tool.id, "versao": rec.version, "plataforma": key, "url": tool.source_url or tool.homepage,
                      "sha256": recipe_fingerprint(tool), "origem": OFICIAL, "python": rec.env.python,
                      "torch": rec.env.torch, "codigo": [z.url for z in rec.code],
                      "arquivos": [{"caminho": p.dest, "url": p.url, "sha256": p.sha256} for p in rec.files],
                      "instalado_em": time.strftime("%Y-%m-%dT%H:%M:%S"), "app": f"{APP_NAME} {__version__}"}
            tmp = final / (MARKER + ".tmp")
            tmp.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, final / MARKER)
            if not keep_old:
                for other in installed(tool, root):
                    if other.path != final:
                        try:
                            shutil.rmtree(_move_aside(other.path, base), ignore_errors=True)
                        except OSError:
                            pass
            shutil.rmtree(cache, ignore_errors=True)
            report(_("Pronto."), 1, 1)
            return Installed(version=rec.version, path=final, size=dir_size(final), sha256=marker["sha256"],
                             url=marker["url"], installed_at=marker["instalado_em"])
        except BaseException:
            for src_path, dst_path in moved:  # devolve ao cache o que foi movido (disco sem links)
                try:
                    os.replace(dst_path, src_path)
                except OSError:
                    pass
            raise
        finally:
            shutil.rmtree(staging, ignore_errors=True)

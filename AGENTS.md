# AGENTS.md — guia para quem mexe no código (pessoas e agentes de IA)

Este arquivo é a referência rápida para trabalhar no **PeliculaConverter**: o que é cada módulo,
quais regras não podem ser quebradas, como rodar e testar, e receitas para as mudanças mais comuns.
O mergulho técnico completo está em [docs/ARQUITETURA.md](docs/ARQUITETURA.md); o significado de
cada ajuste para o usuário, em [docs/EFEITOS.md](docs/EFEITOS.md).

## Em uma frase

App de desktop em Python (PySide6) que simula película cinematográfica em vídeos: o ffmpeg decodifica
os quadros, um pipeline de shaders OpenGL 3.3 (moderngl) aplica o look e o ffmpeg codifica o
resultado. Windows e Linux; macOS preparado e desativado. Interface 100% em português do Brasil.

## Mapa do código

```
PeliculaConverter.pyw        entrada sem console (pythonw); python -m pelicula também funciona
pelicula/
  __init__.py                __version__, __date__, APP_NAME
  __main__.py                python -m pelicula: sem comando abre a janela; com comando usa o modo terminal
  app.py                     main(): tema, idioma (1º acesso), checagem de bibliotecas, MainWindow, boas-vindas
  cli.py                     modo terminal (pelicula-cli): exportar, projeto, quadro, lut, presets, parametros…
  i18n.py                    _() / N_(), idiomas (pt_BR, en, es), separador decimal, idioma do sistema
  locales/                   catálogos en.json e es.json (texto em português → tradução)
  novidades/                 novidades em linguagem simples (pt_BR/en/es.md) e release_vX.Y.Z.md
  project.py                 projetos .plc (JSON): salvar, abrir, caminho relativo, miniatura
  updater.py                 atualização pelo GitHub Releases: checar, baixar, SHA-256, instalar ao fechar
  params.py                  ESQUEMA de todos os ajustes (Param, Section, SECTIONS, PARAMS, sanitize)
  look.py                    build_plan(): ajustes + nº do quadro → uniforms (tabelas de bitola, cópia, scan, gamut)
  shaders.py                 GLSL 330: COMMON, BASE, EXTRACT, BLUR, NOISE, FINAL, BAKE
  engine.py                  Engine: contexto moderngl, alvos, render(), bake_lut(), cache de LUT
  presets.py                 FILM_BASE, BUILTIN (33 presets), presets do usuário em JSON
  luts.py                    .cube (ler/gravar), LUTs instalados (Premiere/Resolve/Meus LUTs), instalar
  media.py                   ffmpeg/ffprobe: localizar, probe(), NamedPipe, FrameReader, Perf, encoders
  export.py                  CODECS, qualidades prontas, build_encoder_cmd(), ExportQueue, run_job(), measure_speed()
  deps.py                    versão do ffmpeg, download verificado (gyan.dev / BtbN), pip_install()
  system.py                  CPU, RAM, GPUs NVIDIA, abrir pasta/arquivo no sistema
  edgetext.py                máscara do texto de borda (QPainter → numpy)
  testimage.py               cena de teste
  ui/                        main_window, export_dialog, queue_dialog, deps_dialog, viewer, looks,
                             widgets, store (desfazer/refazer), theme, icons, prefs (QSettings),
                             welcome (boas-vindas e novidades), language_dialog, update_dialog
tests/                       pytest (conftest com fixtures gl_engine, ffmpeg_ok, qapp, make_info…)
assets/                      logo.svg, logo-256/512.png, logo.ico, banner.svg/png
docs/                        ARQUITETURA.md, EFEITOS.md, ASSINATURA.md, img/ (capturas de tela)
PeliculaConverter.spec       PyInstaller (onedir com PeliculaConverter + pelicula-cli, BUNDLE para macOS)
packaging/
  install_marker.py          grava pelicula-install.json {"kind", "version"} ao lado do executável
  pelicula_cli.py            entrada do executável de terminal pelicula-cli (chama pelicula.cli.main)
  discord_notify.py          avisos do CI no Discord (release, falha, teste); só biblioteca padrão
  windows/                   PeliculaConverter.wxs (WiX v5), build_msi.ps1, license_rtf.py,
                             assinar.ps1 (signtool opcional), verificar_msi.ps1 (teste no CI)
  linux/                     build_deb.sh, verificar_deb.sh, .desktop, tipo MIME (*.plc), debian/postinst|postrm
  macos/                     build_dmg.sh (macOS desativado)
.github/workflows/build.yml  CI: testes sempre; pacotes no main/master, tags v* e manual; release em tags
build.bat / build.sh         build local: executáveis + .zip/.msi (Windows) ou .tar.gz/.deb (Linux)
```

## Regras que não podem ser quebradas

1. **Prévia e exportação usam o mesmo caminho.** Todo efeito vive em `look.build_plan()` +
   `shaders.py`/`Engine.render()`. Nunca implemente um efeito só na interface, só na exportação ou
   só no "Salvar quadro". Prévia, miniaturas, salvar quadro, estimativa e exportação chamam as mesmas
   funções.
2. **Determinismo por quadro.** Tudo o que muda no tempo deriva do **número do quadro**, do fps e
   das **sementes** (`_hash`/`_vnoise` em `look.py`; `pcg`/`rnd`/`vnoise2` no GLSL). Proibido
   `random`, `np.random`, `time.time()` ou estado acumulado entre quadros no caminho de render. O
   quadro N da prévia tem que ser idêntico ao quadro N exportado (FFV1 16 bits é conferido bit a bit).
3. **Parâmetros independentes de resolução.** Distâncias no esquema são **px@1080**; converta com
   `scale = altura / 1080` em `build_plan` (ou use o espaço de 1080 linhas, como `damage()` faz no
   shader). Nunca use pixels absolutos.
4. **Coordenadas de imagem com y para baixo** nos shaders: linha 0 do array numpy = topo =
   `v_uv.y == 0`. Nada é invertido no caminho; não acrescente *flips*.
5. **Um contexto OpenGL por thread.** Um `Engine` só é usado na thread que o criou (a fila de
   exportação e a estimativa criam os seus). Nada de widgets Qt fora da thread principal; threads de
   trabalho falam com a interface por sinais, filas ou campos simples.
6. **Nunca distribuir LUTs proprietários.** LUTs da Adobe (Premiere/After Effects) e da Blackmagic
   (Resolve) são **apenas lidos** onde já estão instalados no computador do usuário. Não adicione
   arquivos `.cube` de terceiros ao repositório, ao executável, aos testes ou aos pacotes gerados (o
   `.gitignore` ignora `*.cube`, exceto fixtures próprias em `tests/`).
7. **Texto do usuário escrito em PT-BR e sempre traduzível.** Todo texto visível passa por `_()`
   (`from .i18n import _`) na hora de aparecer, com placeholders nomeados
   (`_("{n} quadros").format(n=...)`); tabelas montadas na importação usam `N_()` e são traduzidas
   ao exibir. Ao criar texto novo, rode `tools/i18n_extract.py --update` e preencha `en.json` e
   `es.json` (o teste `tests/test_i18n.py` falha se faltar tradução). Chaves de parâmetros e
   identificadores ficam em português sem acento (`grao_forca`, `scan_on`); docstrings e
   comentários em PT-BR.
8. **Nomes de filmes são aproximações artísticas.** Presets com nomes de marcas descrevem um estilo;
   não use dados, perfis ou LUTs dos fabricantes e mantenha o aviso legal (README e "Sobre").
9. **Compatibilidade de presets.** Presets são JSON com chaves de `params.PARAMS` e passam por
   `params.sanitize()`. Não renomeie nem remova chaves sem migração. Parâmetros novos precisam de um
   **padrão neutro** (que não mude o visual de presets antigos). IDs de presets prontos são gravados
   na sessão (`session_preset`): não renomeie.
10. **Dependências mínimas.** Em tempo de execução só PySide6, moderngl (+glcontext) e numpy; o resto
    é biblioteca padrão. Nada de Pillow, OpenCV, SciPy, requests. O ffmpeg é externo e só é baixado
    de fontes confiáveis com conferência de SHA-256 (`deps.py`).
11. **Multiplataforma.** Use `system.open_path()`/`system.reveal()` em vez de `os.startfile`/`explorer`,
    `Perf.popen_kwargs()` para prioridade de processos e `media.NO_WINDOW` só no Windows. Caminhos
    do Windows ficam atrás de `sys.platform == "win32"`. O macOS fica desativado
    (`deps.PLATFORM_ENABLED`, aviso em `app.py`, job do CI com `if: false`) até ser testado.
12. **Não sujar o ambiente do usuário.** Preferências só por `ui/prefs.settings()` (nunca
    `QSettings(APP_NAME, APP_NAME)` direto, que ignora redirecionamentos). Testes e automações
    definem `PELICULA_SETTINGS_DIR` (preferências num `.ini` temporário) e `APPDATA` (presets e
    LUTs) — a `conftest.py` já faz os dois — e encerram com `app.exit(0)`, nunca fechando a
    `MainWindow` (o `closeEvent` grava a sessão).
13. **Projetos `.plc` são um formato público.** Mantenha `project.FORMAT` e a leitura compatível com
    arquivos antigos; aumente `FORMAT` só com migração. Valores passam por `params.sanitize()`.
14. **Atualizações só com SHA-256.** `updater.download()` exige o `SHA256SUMS.txt` da release e
    recusa arquivo que não confere. Os nomes dos pacotes (`PATTERNS` em `updater.py`) precisam bater
    com os do CI, e cada pacote leva `pelicula-install.json` com o tipo de instalação.

## Rodar

```bash
# Windows
instalar.bat                      # cria .venv (py -3.15 → py -3) e instala requirements.txt
executar.bat [arquivo]            # .venv\Scripts\pythonw.exe PeliculaConverter.pyw

# Linux
bash instalar.sh
./executar.sh [arquivo]

# qualquer sistema
python -m pelicula [arquivo]
```

Requisitos: Python 3.12+ (recomendado **3.15**), GPU com **OpenGL 3.3**, ffmpeg + ffprobe (o app
oferece baixar). O `.venv` de referência usa Python 3.15.0, PySide6 6.12, moderngl 5.13, numpy 2.5 e
pytest.

Variáveis de ambiente úteis:

| Variável | Efeito |
|---|---|
| `PELICULA_SCREENSHOT=arquivo.png` | Abre o app, salva `win.grab()` depois de `PELICULA_SCREENSHOT_MS` (padrão 3500 ms) e sai. Atenção: sai com `app.quit()`, que fecha a janela e grava a sessão no `QSettings`. |
| `PELICULA_MACOS=1` | Ignora o bloqueio do macOS em `app.py` (só para desenvolvimento). |
| `QT_QPA_PLATFORM=offscreen` | Qt sem tela (CI, testes). Sem fontes reais no Windows: não use para capturas. |
| `APPDATA` | Base das pastas de presets e LUTs do usuário (os testes redirecionam). |

## Testar

```bash
.venv\Scripts\python -m pytest -q        # Windows
.venv/bin/python -m pytest -q            # Linux
```

- Configuração em `pytest.ini` (`testpaths = tests`, `pythonpath = .`, sem cache).
- `@pytest.mark.gpu` + fixture `gl_engine`: pulado sem OpenGL 3.3 (por exemplo no CI).
- `@pytest.mark.ffmpeg` + fixture `ffmpeg_ok`: pulado sem ffmpeg/ffprobe.
- `tests/test_look.py` confere que todo uniform gerado por `build_plan` existe nos shaders e que
  cada preset, perfil de entrada e espaço de LUT gera um plano válido. Rode depois de mexer em
  `params.py`, `look.py` ou `shaders.py`.
- No CI (`.github/workflows/build.yml`) os testes rodam com `QT_QPA_PLATFORM=offscreen` em Windows
  e Linux; "nenhum teste coletado" (código 5) não quebra o build.

Atenção: `Engine._run()` ignora em silêncio uniforms que não existem no programa (`prog.get(nome)`)
— um nome digitado errado não dá erro, só não faz nada. Os testes de `test_look.py` existem para
pegar isso.

## Receitas

### Adicionar um parâmetro

1. **`params.py`**: acrescente um `F(...)`, `I(...)`, `B(...)`, `C(...)` ou `COR(...)` na `Section`
   certa — chave em português sem acento, rótulo e dica em PT-BR, faixa, passo, unidade (`" px"`,
   `" EV"`, `"°"`, `"×"`) ou `percent=True`, e `advanced=True` se for ajuste fino. O padrão deve ser
   **neutro**. A interface aparece sozinha.
2. **`look.py` → `build_plan()`**: transforme o valor em uniform(s). Multiplique distâncias por
   `scale`; respeite a chave da seção (`v["grao_on"]` etc.); tudo que variar no tempo deve sair de
   `frame`/`t` + semente.
3. **`shaders.py`**: declare o `uniform` no shader certo (`COMMON` para cor — vale também para o
   `BAKE` —, `BASE` para geometria/entrada, `FINAL` para efeitos sobre a imagem) e use-o. Mantenha
   y para baixo.
4. Se o efeito é **só de cor**, coloque-o dentro de `colorPipe()` para que entre também nos LUTs
   exportados (`BAKE`). Efeitos espaciais ou temporais não cabem num LUT.
5. Se um preset precisar dele, ajuste `presets.FILM_BASE` ou o preset.
6. Documente em `docs/EFEITOS.md` (linha na tabela da seção) e no `CHANGELOG.md`; rode o `pytest`.

### Adicionar um preset pronto

1. Em `presets.BUILTIN`, acrescente `dict(id="snake_case_unico", nome="…", grupo="<um de GROUPS>",
   desc="Frase curta em PT-BR.", valores=dict(...))`. `valores` sobrescreve `FILM_BASE` e passa por
   `sanitize()`.
2. A miniatura, a busca e a lista do painel *Ajustes* são automáticas.
3. Atualize a tabela de presets e a contagem no `README.md`, e o `CHANGELOG.md`.
4. Nome com marca? É uma aproximação artística — sem dados do fabricante.

### Adicionar um codec de exportação

1. **`export.CODECS`**: `label` (PT-BR), `enc` (nome do codificador no ffmpeg), `exts`, `pix`
   (formatos de pixel oferecidos), `rc` (`crf`, `cq`, `gq`, `qp`, `qscale`, `jpgq`, `webpq`,
   `profile` ou `none`), `qrange`, `presets`, `profiles` e flags (`grain`, `gpu`, `image`).
2. **`build_encoder_cmd()`**: um ramo `elif s.codec == ...` com os argumentos específicos. Confira
   recipiente (`+faststart`, `hvc1`), tags de cor e `-threads`.
3. **`export_dialog.py`**: `PIX_NAMES`, `Q_LABELS`, `Q_DEFAULT`, `P_DEFAULT` se o codec tiver
   qualidade/velocidade novas; texto em `_describe()` se criar uma qualidade pronta.
4. **`quality_presets()`**: acrescente uma qualidade pronta se fizer sentido (protegida por
   `available()` quando o codificador pode não existir).
5. Áudio: confira a tabela de recipientes em `_audio_args()` (ao copiar áudio a partir do meio do
   arquivo, MKV/WebM/AVI recodificam para não deslocar o vídeo; MKV usa FLAC, sem perdas).
   Profundidade: `high_depth()` decide 8 ou 16 bits com `media.pix_depth()` (`nv12` é 8 bits,
   `p010le` 10, `rgb48le` 16). Dimensões pares: `output_size()`.
6. Codificadores de hardware: `available()` já testa NVENC/QSV/AMF de verdade via
   `media.encoder_works()`; mantenha esse padrão para qualquer codificador que "aparece mas não
   funciona".
7. Teste em `tests/test_export_cmd.py` (estrutura do comando) e documente no README.

### Adicionar um perfil de entrada (câmera)

`shaders.py` (`toLinear` e `lutEncode` com um novo id), `look.INPUT_IDS`, `look.INPUT_GAMUT` (e
`_PRIMARIES` se o gamut for novo), `params.ENTRADAS` e, se servir para LUTs, `params.LUT_ENTRADAS`
e `luts.guess_input()`. Documente em `docs/EFEITOS.md` e no README.

### Adicionar uma bitola

`look.GAUGES` (multiplicadores e proporção), `look.GAUGE_SCAN` (qual geometria de scan usar),
`params.BITOLAS`; se tiver geometria própria de scan, `look.SCAN_FORMATS` e a escolha em
`scan_formato`. Documente a tabela de bitolas.

### Mexer no ffmpeg / dependências

- Procura: `media.configure()` (pasta escolhida → `deps.ffmpeg_dir()` → `PATH` → pastas comuns).
  Depois de trocar o ffmpeg chame `media.configure()` (que limpa o cache de codificadores).
- Download: `deps.SOURCES` (URL do pacote + URL do hash). Toda fonte nova precisa de hash publicado e
  conferido antes de instalar; nada de executar instaladores, nada de pedir administrador.

## Empacotamento e release

### Pacotes

A pasta do PyInstaller (`dist/PeliculaConverter/`, com `PeliculaConverter[.exe]` e
`pelicula-cli[.exe]` dividindo `_internal/`) é a base de todos os pacotes:

| Pacote | Como é montado | Onde instala | `kind` |
|---|---|---|---|
| `PeliculaConverter-{tag}-windows-x64.msi` | `packaging/windows/build_msi.ps1` (WiX 5) | `%LOCALAPPDATA%\Programs\PeliculaConverter` (por usuário, sem administrador) | `msi` |
| `PeliculaConverter-{tag}-windows-x64.zip` | `Compress-Archive` | onde o usuário extrair | `zip` |
| `PeliculaConverter-{tag}-linux-x64.deb` | `packaging/linux/build_deb.sh` (`dpkg-deb`) | `/opt/pelicula-converter` + links em `/usr/bin` | `deb` |
| `PeliculaConverter-{tag}-linux-x64.tar.gz` | `tar` | onde o usuário extrair | `tar` |
| `PeliculaConverter-{tag}-macos.dmg` (desativado) | `packaging/macos/build_dmg.sh` (`hdiutil`) | `/Applications` | `dmg` |

- **Marcador de instalação**: cada pacote leva `pelicula-install.json` ao lado do executável
  (no macOS, em `PeliculaConverter.app/Contents/MacOS`), com `{"kind": ..., "version": "x.y.z"}`,
  gravado por `packaging/install_marker.py` na hora de montar **cada** pacote (o `.msi` e o `.zip`
  saem da mesma pasta: o marcador é regravado entre um e outro). O atualizador do app lê esse
  arquivo para escolher o pacote da release; os **nomes dos arquivos da release não podem mudar**.
- **`.msi`**: o `UpgradeCode` (`35055C18-5F06-43BC-85C7-C95E9E42F81B`) **nunca muda** — é ele que
  faz um `.msi` novo substituir o antigo no mesmo lugar (`MajorUpgrade`, inclusive na mesma
  versão). A pasta escolhida fica em `HKCU\Software\PeliculaConverter\InstallDir` e é reaproveitada
  nas atualizações. Recursos opcionais: `AtalhoDesktop`, `AssociacaoPlc` (ProgId
  `PeliculaConverter.Projeto`, `.plc` → `PeliculaConverter.exe "%1"`) e `PastaNoPath` (PATH do
  usuário). `ABRIR_APOS_INSTALAR=1` abre o app no fim de uma instalação silenciosa
  (`msiexec /i arquivo.msi /passive ABRIR_APOS_INSTALAR=1`). Versão do MSI: só `x.y.z`.
- **`.deb`**: `Depends` com as bibliotecas do Qt (xcb) e do OpenGL e `libc6 (>= …)` calculada a
  partir dos binários; `Recommends: ffmpeg`; `.desktop` com `MimeType=application/x-pelicula-project`
  e o tipo MIME em `/usr/share/mime/packages/pelicula-converter.xml`. Builds fora de tag usam a
  versão Debian `x.y.z~git<sha>`. Os pacotes do Linux são gerados no **`ubuntu-22.04`** de
  propósito (glibc 2.35; o PySide6 pede 2.34): assim o `.deb` e o `.tar.gz` servem ao Ubuntu
  22.04+ e ao Debian 12+ (o CI confere em contêineres). Gerado num Ubuntu mais novo, o mínimo sobe.
  O `.desktop` fica na especificação 1.4 (o `desktop-file-validate` do 22.04 não conhece a 1.5).
- **Testes de verdade no CI**: `verificar_msi.ps1` instala, confere, atualiza para uma versão maior
  (e numa pasta escolhida) e desinstala; `verificar_deb.sh` instala com o `apt`, confere e remove.
  Não rode esses dois no seu computador.
- **Assinatura**: opcional, só com os segredos `WINDOWS_CERT_PFX_BASE64` e `WINDOWS_CERT_PASSWORD`
  (ou `WINDOWS_CERT_SHA1` no build local); opções e custos em [docs/ASSINATURA.md](docs/ASSINATURA.md).
- **Build local**: `build.bat` (Windows; o `.msi` só se o WiX estiver instalado:
  `dotnet tool install --global wix --version 5.0.2`) ou `bash build.sh` (Linux; o `.deb` só com
  `dpkg-deb`).

### CI e Discord

- Todo push e PR: só o job `testes` (Windows e Linux).
- Push no `main`/`master`, tags `v*` e `workflow_dispatch`: o job `build` também gera, testa e
  envia os pacotes como artefatos. Para validar uma branch:
  `gh workflow run build.yml --ref <branch>`.
- Tags `v*`: release com os pacotes e o `SHA256SUMS.txt`. O texto da release vem de
  `pelicula/novidades/release_{tag}.md` (as primeiras linhas, até uma linha `---`, viram o resumo
  do aviso no Discord); sem o arquivo, o GitHub gera as notas. A tag precisa bater com
  `pelicula.__version__` (o build falha se não bater).
- Discord: segredo `DISCORD_WEBHOOK` (nunca imprima nem grave em arquivo). Aviso âmbar na release,
  vermelho quando um push no `main`/`master` falha;
  `gh workflow run build.yml -f testar_discord=true` manda só uma mensagem de teste.

### Versão e release

1. Atualize `pelicula/__init__.py` (`__version__`), `pyproject.toml` (`version`),
   `PeliculaConverter.spec` (`CFBundleShortVersionString`), o `CHANGELOG.md` e escreva
   `pelicula/novidades/release_vX.Y.Z.md`.
2. Crie a tag `vX.Y.Z` e envie. O workflow gera os pacotes, publica a Release e avisa no Discord.

## Estilo

- Python 3.12+, `from __future__ import annotations`, tipagem moderna (`X | None`), `dataclass`,
  linhas de até ~120 colunas.
- Mensagens ao usuário curtas, diretas e em PT-BR; números com vírgula decimal na interface.
- Sem mídia pessoal no repositório (vídeos, áudios e quadros de teste ficam fora; veja `.gitignore`).
  Capturas de tela da documentação usam só a cena de teste (`pelicula.testimage.make`).

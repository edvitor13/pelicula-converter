# AGENTS.md — guia para quem mexe no código (pessoas e agentes de IA)

Este arquivo é a referência rápida para trabalhar no **PeliculaConverter**: o que é cada módulo,
quais regras não podem ser quebradas, como rodar e testar, e receitas para as mudanças mais comuns.
O mergulho técnico completo está em [docs/ARQUITETURA.md](docs/ARQUITETURA.md); o significado de
cada ajuste para o usuário, em [docs/EFEITOS.md](docs/EFEITOS.md); o modo Edição para o usuário, em
[docs/EDICAO.md](docs/EDICAO.md); o plugin do DaVinci Resolve, em [docs/DAVINCI.md](docs/DAVINCI.md).

## Em uma frase

App de desktop em Python (PySide6) que simula película cinematográfica em vídeos: o ffmpeg decodifica
os quadros, um pipeline de shaders OpenGL 3.3 (moderngl) aplica o look e o ffmpeg codifica o
resultado. Windows e Linux; macOS preparado e desativado. Interface 100% em português do Brasil.

O app tem **dois modos** (seletor no topo da janela):

- **Película** — o modo de sempre: um arquivo (ou a montagem da edição) recebe o look de película.
- **Edição** — montagem em faixas de vídeo e de áudio (cortar, aparar, mover, velocidade,
  transições), cor e luz por clipe (rodas, curva, HSL, detalhe, enquadramento) e som por clipe
  (volume, fades, equalização, voz, ruído). A montagem é a entrada do look de película.

Junto vem um **plugin para o DaVinci Resolve** (DCTLs + LUTs) gerado a partir das mesmas tabelas e
da mesma matemática do app (`pelicula/resolve.py`).

## Mapa do código

```
PeliculaConverter.pyw        entrada sem console (pythonw); python -m pelicula também funciona
pelicula/
  __init__.py                __version__, __date__, APP_NAME
  __main__.py                python -m pelicula: sem comando abre a janela; com comando usa o modo terminal
  app.py                     main(): tema, idioma (1º acesso), checagem de bibliotecas, MainWindow, boas-vindas
  cli.py                     modo terminal (pelicula-cli): exportar, projeto, quadro, lut, presets, parametros…
  i18n.py                    _() / N_(), idiomas (pt_BR, en, es), separador decimal, idioma do sistema
  modules.py                 módulos que o usuário liga e desliga: MODULES, PROFILES, is_enabled(), used_by() (sem Qt)
  locales/                   catálogos en.json e es.json (texto em português → tradução)
  novidades/                 novidades em linguagem simples (pt_BR/en/es.md) e release_vX.Y.Z.md
  project.py                 projetos .plc (JSON): salvar, abrir, caminho relativo, miniatura
  updater.py                 atualização pelo GitHub Releases: checar, baixar, SHA-256, instalar ao fechar
  params.py                  ESQUEMA de todos os ajustes (Param, Section, SECTIONS, PARAMS, sanitize)
  look.py                    build_plan(): ajustes + nº do quadro → uniforms (tabelas de bitola, cópia, scan, gamut,
                             Laboratório: negativos, cópias, processos, calibração lab_paths, LabMods/LabPost)
  shaders.py                 GLSL 330: COMMON, BASE, EXTRACT, BLUR, NOISE, FINAL, BAKE
  engine.py                  Engine: contexto moderngl, alvos, render(), bake_lut(), cache de LUT
  presets.py                 FILM_BASE, BUILTIN (44 presets em 7 grupos), presets do usuário em JSON
  luts.py                    .cube (ler/gravar), LUTs instalados (Premiere/Resolve/Meus LUTs), instalar
  media.py                   ffmpeg/ffprobe: localizar, probe(), NamedPipe, FrameReader, Perf, encoders
  export.py                  CODECS, qualidades prontas, build_encoder_cmd(), ExportQueue, run_job(), measure_speed()
  deps.py                    versão do ffmpeg, download verificado (gyan.dev / BtbN), extract_archive(), pip_install()
  tools.py                   componentes externos (sem Qt): registro TOOLS (versão e SHA-256 fixos), download e
                             instalação atômica, remover, espaço em disco, detecção de programas do sistema
  jobs.py                    fila de tarefas em segundo plano (sem Qt): CPU/GPU/rede, progresso, cancelar, 1 de GPU
  system.py                  CPU, RAM, GPUs NVIDIA, abrir pasta/arquivo no sistema
  edgetext.py                máscara do texto de borda (QPainter → numpy)
  testimage.py               cena de teste
  timeline.py                modo Edição: Source, Clip, Track, Layer, Sequence (montagem, sem Qt), History
  editparams.py              esquemas dos ajustes por clipe (VIDEO e AUDIO), HSL_COLORS, QUICK_LOOKS
  compositor.py              ajustes do clipe + camada → uniforms do shader CLIP; auto_adjust() (cor automática)
  editshaders.py             GLSL do modo Edição: CLIP (uma camada sobre a tela) e a saída da tela
  sequence.py                camadas decodificadas: grab() (acesso aleatório), SequenceReader (sequencial),
                             canvas_size(), decode_size(), media_info() (MediaInfo "virtual" da montagem)
  audiomix.py                mixagem do som da montagem com o ffmpeg (prévia e exportação), forma de onda
  resolve.py                 plugin do DaVinci Resolve: gera os DCTLs (Cor, Textura, Projetor, presets) e LUTs;
                             dialetos dctl/glsl/cpp do mesmo kernel; atalhos ofx_* (instalar o plugin OpenFX)
  ofx.py                     plugin OpenFX: gera plugins/ofx/generated (dialeto cpp), parâmetros/presets, pacote e
                             instalação (pasta do OpenFX, com administrador)
  ui/                        main_window, export_dialog, queue_dialog, job_bridge (fila → sinais do Qt), viewer, looks,
                             widgets, store (desfazer/refazer), theme, icons, prefs (QSettings),
                             welcome (boas-vindas e novidades), language_dialog, update_dialog;
                             modo Edição: edit_model (TimelineModel: sequência + histórico + seleção),
                             timeline_view (TimelineEditor), edit_panels (MediaBin, ClipInspector),
                             scopes (histograma, forma de onda, parada RGB, vetorscópio),
                             sequence_dialog; resolve_dialog (plugin do DaVinci);
                             settings_dialog (Configurações) + pages/ (geral, recursos, componentes: ffmpeg,
                             ferramentas e programas do sistema, placa de vídeo e bibliotecas...);
                             profile_dialog (perfil de recursos no 1º acesso), module_notice (aviso de
                             recurso desligado em uso)
plugins/ofx/                 plugin OpenFX (C++, funciona no Resolve gratuito): openfx/ (OpenFX 1.4, BSD-3),
                             generated/ (gerado por ofx.py), src/ (pc_core, pc_ofx, pc_capi, pc_json), build.py,
                             build_windows.bat, build_linux.sh → dist/PeliculaConverter.ofx.bundle
tools/                       i18n_extract.py (textos), gerar_ofx.py (regenera plugins/ofx/generated)
tests/                       pytest (conftest com fixtures gl_engine, ffmpeg_ok, qapp, make_info…); ofxhost.py
                             (host OpenFX mínimo em ctypes para tests/test_ofx.py); uicases.py (roda arquivos
                             <nome>_ui_cases.py de widgets num subprocesso offscreen)
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
   funções. No modo Edição vale o mesmo: ajuste de clipe só em `compositor.py` + `editshaders.py` /
   `Engine.compose()`; qual quadro de qual arquivo aparece só em `timeline.Sequence.src_frame()` /
   `layers_at()`; som só em `audiomix.py` (a prévia toca a mesma mixagem que a exportação grava).
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
   na sessão (`session_preset`): não renomeie. O mesmo vale para os ajustes de clipe
   (`editparams.VIDEO`/`AUDIO`, gravados nos projetos): padrão neutro = clipe idêntico ao arquivo.
10. **Dependências mínimas.** Em tempo de execução só PySide6, moderngl (+glcontext) e numpy; o resto
    é biblioteca padrão. Nada de Pillow, OpenCV, SciPy, requests. O ffmpeg é externo e só é baixado
    de fontes confiáveis com conferência de SHA-256 (`deps.py`). Outras ferramentas externas (IA etc.)
    são **componentes baixados à parte**, nunca dentro do pacote, com versão e SHA-256 fixos no código
    (`tools.py`, receita "Nova ferramenta externa").
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
    Projetos com montagem do modo Edição gravam o bloco `"edicao"` (JSON de `timeline.Sequence`) e
    `"formato": 2`; projetos simples (só o arquivo inteiro, sem mudanças) continuam `"formato": 1`
    para abrir nas versões antigas.
14. **Atualizações só com SHA-256.** `updater.download()` exige o `SHA256SUMS.txt` da release e
    recusa arquivo que não confere. Os nomes dos pacotes (`PATTERNS` em `updater.py`) precisam bater
    com os do CI, e cada pacote leva `pelicula-install.json` com o tipo de instalação.
15. **O plugin do DaVinci acompanha o app.** Os DCTLs são gerados por `resolve.py` a partir das
    tabelas de `look.py`/`presets.py`; a cor (`colorPipe`, incluindo o Laboratório) é portada à mão e
    conferida contra `Engine.bake_lut` por `tests/test_resolve.py` (dialeto GLSL do mesmo código).
    Mudou a cor em `shaders.py`? Atualize o kernel em `resolve.py` e rode esse teste. Nada de
    instalar no Resolve do usuário em testes (use pastas temporárias). DCTL: sem *swizzles*, sem
    sobrecarga de funções (OpenCL), literais com `f`, até 64 controles por tipo e 5 seletores de cor.
    O plugin OpenFX usa o mesmo kernel (dialeto `cpp`): `plugins/ofx/generated` é gerado e tem que estar
    em dia (`tests/test_ofx.py`); nunca instale em `Common Files\OFX\Plugins` ou `/usr/OFX/Plugins` em
    testes nem copie código de exemplo da Blackmagic para o repositório.
16. **Recurso opcional é módulo.** Todo recurso que o usuário pode dispensar entra em
    `modules.MODULES` (id sem acento, nunca renomear; recurso novo em teste com `status` `beta` ou
    `experimental`, que começa desligado). Desligar um módulo **só esconde** a ferramenta na
    interface: a renderização (`look`, `compositor`, `engine`, `export`, CLI) nunca consulta
    `modules`, e um projeto ou preset que usa um módulo desligado sai igual — a janela avisa e
    oferece religar (`modules.used_by`). Preferências do usuário ficam em páginas de
    Configurações (`ui/settings_dialog.py`, uma classe `Page` por arquivo em `ui/pages/`).

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

Testes do modo Edição, do plugin e dos módulos:

| Arquivo | O que confere |
|---|---|
| `tests/test_modules.py` | registro de módulos sem Qt: padrões (estável ligado, em teste desligado), perfis, `used_by` |
| `tests/test_modules_ui.py` | casos de `modules_ui_cases.py`: página Recursos, perfil do 1º acesso e a janela (cada módulo esconde e devolve as ferramentas, Edição → Película sem mexer na montagem, aviso ao abrir projeto ou aplicar preset) |
| `tests/test_timeline.py` | montagem sem GPU: dividir, aparar, mover (sobrescreve), apagar com e sem fechar o espaço, ligar/desligar, velocidade, `layers_at` com transições, JSON e histórico |
| `tests/test_compositor.py` | uniforms do shader CLIP; na GPU: clipe neutro sai idêntico (8 e 16 bits), cada ajuste muda a imagem no sentido certo |
| `tests/test_sequence.py` | `grab` × `SequenceReader` iguais quadro a quadro; exportação de uma montagem com corte e som |
| `tests/test_audiomix.py` | comando do ffmpeg (filtros por clipe) e mixagem de verdade |
| `tests/test_lab.py` | Laboratório: cinza neutro em toda combinação negativo × cópia × processo, luzes da copiadora, revelação forçada |
| `tests/test_resolve.py` | DCTLs gerados (estrutura, limites de controles) e paridade de cor com o app na GPU |
| `tests/test_ofx.py` | plugin OpenFX: código gerado em dia, `.ofx` (pontos de entrada), paridade da cor e do quadro com o app, LUT rápido, `.json`, efeito num host de teste (`ofxhost.py`); compila na hora (pula sem compilador) |
| `tests/test_edit_ui.py` | widgets da edição em subprocesso *offscreen* (modelo, linha do tempo, inspetor, mídia, medidores) |
| `tests/test_main_window_edit.py` | janela inteira: abrir, trocar de modo, dividir, apagar, ajustar, exportar a montagem e salvar o projeto |

Componentes e fila de tarefas (sem rede: pacotes locais, `file://` e um servidor em 127.0.0.1; a pasta
do app vai para uma pasta temporária via `LOCALAPPDATA`/`XDG_DATA_HOME`):

| Arquivo | O que confere |
|---|---|
| `tests/test_tools.py` | registro consistente (ids, https, SHA-256, módulos), instalação atômica e relatada, SHA-256 ou tamanho errado não instala nada, caminhos suspeitos em zip/tar, cancelar, atualizar/manter versões, remover, espaço em disco, ffmpeg pelo fluxo de `deps.py`, detecção do Resolve |
| `tests/test_jobs.py` | fila: ordem dos eventos, erros, cancelar (na espera e rodando), um trabalho de GPU por vez, 200 trabalhos de 8 threads |
| `tests/test_componentes_ui.py` | página Componentes e ponte do Qt em subprocesso *offscreen*: baixar/remover pela fila, progresso e cancelar, erro de SHA-256, licença com aceite, `show_deps`, sinais na thread principal |

Widgets do Qt só rodam em teste dentro de um **subprocesso** com `QT_QPA_PLATFORM=offscreen` e
`QApplication` própria (a sessão do pytest já tem uma `QGuiApplication`).

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

### Adicionar um ajuste de clipe (modo Edição)

1. **`editparams.py`**: um `F`/`B`/`C`/`W` (roda) na seção certa de `VIDEO_SECTIONS` ou
   `AUDIO_SECTIONS`, com padrão neutro, chave sem acento e rótulo/dica em PT-BR. O inspetor aparece
   sozinho. Se for de cor, ele entra no "Copiar/Colar ajustes" (seções em `COLOR_SECTIONS`).
2. **Imagem**: `compositor.py` transforma o valor em uniform(s) e `editshaders.CLIP` usa; mantenha
   o atalho de "tudo neutro = cópia exata". **Som**: `audiomix.py` acrescenta o filtro do ffmpeg na
   cadeia do clipe.
3. Teste em `tests/test_compositor.py` (ou `test_audiomix.py`) e documente em `docs/EDICAO.md`.

### Mudar a montagem (timeline)

Toda regra de tempo fica em `timeline.Sequence` (sem Qt): `src_frame()` decide o quadro do arquivo,
`layers_at()` resolve camadas e transições, `audio_clips()` o que toca. A interface só chama os
métodos do `ui/edit_model.TimelineModel`, que grava o histórico (instantâneos JSON) e emite
`changed("structure" | "values" | "settings" | "*")`. A janela reage: `"values"` só remonta o quadro
atual; o resto recarrega a fonte da prévia. Teste novo em `tests/test_timeline.py`.

### Adicionar um negativo ou uma cópia do Laboratório

`look.py` (tabelas do Laboratório: curvas características, sensibilidade das camadas, diafonia dos
corantes; a calibração do cinza é automática), a escolha em `params.py` e, se quiser, um preset em
`presets.py`. Rode `tests/test_lab.py` (cinza neutro em toda combinação) e `tests/test_resolve.py`
(o plugin do DaVinci lê as mesmas tabelas). Nomes de filmes são aproximações artísticas (regra 8).

Como o Laboratório se organiza (`look.py`):

- `lab_paths(negativo, copia, processo, push, diafonia, chave, forca, mods, bypass_print)` (com
  `lru_cache`) devolve os caminhos A/B já calibrados. `LabMods` reúne o que muda as curvas e por
  isso entra na calibração (Hue Split, saturação do filme, bypass no negativo, curvas neutras, pé);
  `LabPost` reúne os passos depois da cópia (rolagens, saturação final, densidade por cor, pele),
  que por construção **não podem mexer no cinza** — mantenha assim ao acrescentar um passo.
- No shader, `u_lab_ops` liga só os passos usados (bits: 2 tons, 4 saturação, 8 densidade por cor,
  16 pele); com tudo no padrão nada extra roda.
- `ii_coefs` e `split_matrix` (Hue Split na densidade do negativo) são espelhados no kernel do DCTL
  em `resolve.py`; mudou um, mude o outro e rode `tests/test_resolve.py`.
- `look.lab_eval(v, lin)` é a referência em numpy (testes de paridade); o gráfico *Curva* da janela
  usa `Engine.bake_lut` (o eixo dos cinzas), então vale para qualquer ajuste.

### Atualizar o plugin do DaVinci Resolve

`resolve.py` gera tudo: rode `pelicula-cli resolve --pasta saida/` para ver o pacote. Mudou a cor
do app? Porte a mudança para o kernel do DCTL e rode `tests/test_resolve.py` (paridade com
`Engine.bake_lut` na GPU). Textura (grão, halação) e projetor são aproximações de passo único,
documentadas em `docs/DAVINCI.md`. São quatro tipos de nó (`COLOR_KINDS` e `NODE_LABELS`):
*Laboratorio* (entrada + laboratório inteiro + "Mostrar curva"), *Cor* (laboratório + cor
paramétrica + cópia), *Textura* e *Projetor*; cada um tem no máximo 64 controles de cada tipo.

### Plugin OFX (OpenFX, Resolve gratuito)

O plugin é C++ e reaproveita a matemática dos DCTLs:

1. Mudou a cor, um kernel de `resolve.py`, um parâmetro, um preset ou uma tabela de `look.py`? Rode
   `python tools/gerar_ofx.py` (regrava `plugins/ofx/generated/`) e commite os arquivos gerados;
   `tests/test_ofx.py::test_generated_files_are_up_to_date` falha se esquecer.
2. Mudou uma **passada** do `Engine.render()` (desfoque, mipmap, grão, ordem da composição em `FINAL`)?
   Mude também `plugins/ofx/src/pc_core.cpp` — é a única parte escrita à mão — e rode
   `tests/test_ofx.py` (paridade do quadro com `Engine.render`).
3. Compile: `plugins\ofx\build_windows.bat` (MSVC; acha o `vcvars64.bat` pelo vswhere) ou
   `bash plugins/ofx/build_linux.sh` (g++). Saída: `plugins/ofx/dist/PeliculaConverter.ofx.bundle`
   (`Contents/Win64` ou `Contents/Linux-x86-64`, `Contents/Resources/pelicula-ofx.txt` com a versão e a
   impressão digital das fontes). Ponto flutuante preciso: nada de `/fp:fast` ou `-ffast-math`.
4. Parâmetro novo do app aparece sozinho no plugin se estiver num dos nós Cor/Textura/Projetor de
   `resolve.py`; o nome do parâmetro no OFX é a chave do app — **não renomeie** (projetos do Resolve
   guardam os valores por esse nome). O identificador do plugin (`com.peliculaconverter.pelicula`) também
   não muda; a versão segue `__version__` (maior.menor).
5. O pacote do app leva o plugin pronto (spec: `_internal/ofx/`; CI com `PELICULA_EXIGIR_OFX=1`); o
   usuário só clica em *Instalar o plugin OpenFX* (`ofx.install()`, com UAC/pkexec). Testes instalam só em
   pastas temporárias. O OpenFX em `plugins/ofx/openfx` é a cópia oficial (BSD-3, `SOURCE.txt` com commit
   e SHA-256): não edite.

### Novo módulo (recurso opcional)

Todo recurso que dá para dispensar é um módulo (regra 16). Para criar um:

1. **`modules.py`**: um `Module("id_sem_acento", N_("Nome"), N_("Descrição curta."), "<grupo de GROUPS>",
   status)` em `MODULES`. Recurso novo em teste usa `BETA` ou `EXPERIMENTAL`: começa desligado e só
   aparece em Recursos com *Mostrar recursos em teste* (perfis nunca ligam recursos em teste). Recurso
   estável começa ligado para quem já usa o app; decida em que perfis ele entra (`_SIMPLES`,
   `_CRIADOR`, `_CINEMA`; *Tudo* pega todo estável). O id fica gravado em `modulos/<id>`: nunca renomeie.
2. **Esconder na janela**: acrescente as ferramentas (widgets ou `QAction`s) em
   `MainWindow._module_tools()`; casos especiais (atalhos, trocar de modo, gráfico que depende de outra
   chave) vão em `apply_modules()`. Desligar **só esconde**: `look`, `compositor`, `engine`, `export` e
   os comandos de renderização da CLI nunca consultam `modules`.
3. **Aviso de uso**: se um look ou uma montagem podem usar o recurso, ensine `modules.used_by()` a
   reconhecê-lo (chave de parâmetro ou propriedade da sequência). A janela avisa e oferece *Ligar* ao
   abrir um projeto, aplicar um preset ou soltar um LUT (`MainWindow._check_modules()`).
4. **Textos**: nome e descrição com `N_()` em PT-BR; rode `tools/i18n_extract.py --update` e traduza em
   `en.json` e `es.json`. A página Recursos, o perfil do 1º acesso e `pelicula-cli modulos` mostram o
   módulo sozinhos.
5. **Testes**: `tests/test_modules.py` (padrão, perfis, `used_by`) e um caso em
   `tests/modules_ui_cases.py` (as ferramentas somem e voltam; o aviso aparece e a renderização recebe
   os mesmos valores).

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
  conferido antes de instalar; nada de executar instaladores, nada de pedir administrador. A extração
  passa por `deps.extract_archive()` (recusa caminhos que saem da pasta).
- Interface: Configurações › Componentes (`ui/pages/componentes.py`, cartão do ffmpeg). O ffmpeg é a
  exceção do registro de componentes: baixa o build mais recente e confere com o checksum publicado pelo
  autor do build, sem versão fixa. `MainWindow.show_deps(reason, auto_download)` abre essa página com o
  aviso e, se pedido, já baixando.

### Nova ferramenta externa (componente)

Ferramentas externas (IA, conversores, modelos...) **nunca** vão dentro do pacote do app: são
downloads separados, com um cartão em Configurações › Componentes.

1. **Fonte oficial.** Use o binário publicado pelo próprio autor **só se ele publicar checksums**.
   Sem binário oficial verificável, compile a partir do código-fonte oficial **no CI do
   PeliculaConverter** (workflow próprio, versão da fonte fixa) e publique o pacote numa release do
   projeto com `SHA256SUMS.txt`; o `Artifact` aponta para essa release (`origin=tools.CI`) e o `Tool`
   leva o `source_url` do código.
2. **Tudo fixo no código** (`tools.TOOLS`): para cada sistema, um `tools.Artifact` com versão (vira o
   nome da pasta), URL `https`, SHA-256 (64 dígitos hexadecimais minúsculos), tamanho em bytes, tipo de
   pacote (`zip`, `tar.gz`, `tar.xz` ou `arquivo`) e caminhos dos executáveis. Confira o SHA-256 baixando
   e comparando com o publicado; nunca leia o hash do mesmo servidor na hora do download. Versão nova =
   mudança de código (versão + URL + SHA-256 + tamanho).
3. **Licença**: confira a do programa **e a dos pesos/modelos** — nada de licença não comercial
   (CC-BY-NC e afins) nem "só para pesquisa". Preencha `license`/`license_url`. Licença com condições
   (atribuição, avisos, uso aceitável) → texto em `consent` (PT-BR, `N_()`): a página pede o aceite do
   usuário antes de baixar.
4. **Pasta**: sempre `deps.app_data_dir()/ferramentas/<id>/<versão>/`, montada por `tools.download()`
   (SHA-256 conferido antes de extrair, troca atômica, `pelicula-origem.json`), só para o usuário, sem
   administrador e sem rodar instaladores. O `id` é ASCII sem acento e **nunca muda** (é o nome da pasta).
5. **Quem usa**: o id do módulo em `Tool.modules` e/ou o id da ferramenta em `Module.requires`. O módulo
   acha o executável com `tools.executable(tools.get("<id>"))` (`None` = não instalado: ofereça abrir
   `show_settings("componentes")`) e roda trabalhos longos pela fila de tarefas
   (`ui/job_bridge.bridge().submit(...)`; GPU no máximo um por vez, com `Engine` próprio).
6. **Ícone**: um desenho simples em `ui/icons.py` (sem logotipo de marca).
7. **Testes**: `tests/test_tools.py::test_registry_is_consistent` confere o registro sozinho. Teste o
   código que usa a ferramenta com uma instalação falsa em pasta temporária (`root=` ou
   `LOCALAPPDATA`/`XDG_DATA_HOME` temporários) — nunca a rede nem a pasta real do usuário.
8. Textos novos em PT-BR + `tools/i18n_extract.py --update` + en/es; README (componentes e
   privacidade) e `CHANGELOG.md`.

Programa do sistema (instalado pelo usuário, como o DaVinci Resolve): `kind=tools.SISTEMA`, sem
`artifacts`, e uma função em `tools.DETECTORS` que só lê (pastas padrão, lista de desinstalação do
Windows) — o app não instala nem baixa nada. O ffmpeg (`backend="ffmpeg"`) é a exceção documentada
ao modelo de versão fixa: não copie o fluxo dele para ferramentas novas.

### Trabalho em segundo plano (fila de tarefas)

Tudo que demora (downloads, análises, IA) vai para `jobs.py` pela ponte do Qt:
`bridge().submit(fn, título, kind=jobs.CPU|GPU|REDE, key="...", on_finished=f)`. A função recebe o job,
chama `job.report(etapa, feito, total)` e `job.check_cancel()` e devolve o resultado (`job.result`);
`f(job)` roda na thread principal (é ali que se mexe em widgets, preferências ou no projeto). A
interface acompanha pelos sinais `changed`/`finished` de `bridge()`, filtrando por `job.key`. Detalhes
em `docs/ARQUITETURA.md` (seção 18).

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
  `dpkg-deb`). Os dois compilam antes o plugin OpenFX quando há compilador C++ (sem ele, o pacote sai
  sem o plugin e a janela do Resolve explica como compilar).
- **Plugin OpenFX dentro dos pacotes**: o CI compila `plugins/ofx` (MSVC/g++) antes do PyInstaller, que
  o põe em `_internal/ofx/PeliculaConverter.ofx.bundle` (o `.msi` colhe a pasta inteira, o `.zip`, o
  `.deb` e o `.tar.gz` também). `PELICULA_EXIGIR_OFX=1` faz o PyInstaller falhar sem ele;
  `verificar_msi.ps1` e `verificar_deb.sh` conferem o arquivo e o `pelicula-cli resolve --ofx-pasta`.

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

1. Atualize `pelicula/__init__.py` (`__version__` e `__date__`; o `pyproject.toml` e o
   `PeliculaConverter.spec` leem a versão de lá), o `CHANGELOG.md` (a seção "Não lançado" vira
   `[X.Y.Z] - data`), as novidades em linguagem simples (`pelicula/novidades/pt_BR.md`, `en.md`,
   `es.md`) e escreva `pelicula/novidades/release_vX.Y.Z.md`.
2. Rode `python tools/gerar_ofx.py`: o código gerado do plugin OpenFX leva a versão do app
   (`tests/test_ofx.py` falha se esquecer).
3. Antes da tag, valide a branch com `gh workflow run build.yml --ref <branch>` (pacotes completos).
4. Crie a tag `vX.Y.Z` e envie. O workflow gera os pacotes, publica a Release e avisa no Discord.

## Estilo

- Python 3.12+, `from __future__ import annotations`, tipagem moderna (`X | None`), `dataclass`,
  linhas de até ~120 colunas.
- Mensagens ao usuário curtas, diretas e em PT-BR; números com vírgula decimal na interface.
- Sem mídia pessoal no repositório (vídeos, áudios e quadros de teste ficam fora; veja `.gitignore`).
  Capturas de tela da documentação usam só a cena de teste (`pelicula.testimage.make`).

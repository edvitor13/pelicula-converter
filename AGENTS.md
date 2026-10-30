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
  app.py                     main(): tema, idioma (1º acesso), checagem de bibliotecas, sessão da recuperação,
                             MainWindow, aviso de recuperação, boas-vindas
  cli.py                     modo terminal (pelicula-cli): exportar, projeto, quadro, lut, presets, parametros…
  i18n.py                    _() / N_(), idiomas (pt_BR, en, es), separador decimal, idioma do sistema
  modules.py                 módulos que o usuário liga e desliga: MODULES, PROFILES, is_enabled(), used_by() (sem Qt)
  locales/                   catálogos en.json e es.json (texto em português → tradução)
  novidades/                 novidades em linguagem simples (pt_BR/en/es.md) e release_vX.Y.Z.md
  project.py                 projetos .plc (JSON): salvar, abrir, caminho relativo, miniatura; formato mínimo
                             (needed_format, FEATURES_V3/V4/V5) e migração passo a passo (MIGRATIONS)
  updater.py                 atualização pelo GitHub Releases: checar, baixar, SHA-256, instalar ao fechar
  params.py                  ESQUEMA de todos os ajustes (Param, Section, SECTIONS, PARAMS, sanitize)
  look.py                    build_plan(): ajustes + nº do quadro → uniforms (tabelas de bitola, cópia, scan, gamut,
                             Laboratório: negativos, cópias, processos, calibração lab_paths, LabMods/LabPost)
  grao.py                    grão e textura da 1.6 (ARQUITETURA §30): modelos chamados por ganchos de build_plan
                             (maciez pelo grão, nitidez por camada, grão no negativo, halação física,
                             respiração por camada), constantes calibradas por datasheets
  grao_fisico.py             1.6, grão físico (ARQUITETURA §30.7; módulo Beta grao_fisico): modelo booleano no
                             negativo, gancho negative_grain (u_grain_on = 3, u_pg_*), GLSL e FINAL_PG (o FINAL
                             com physGrain, compilado só quando usado), referência exata (covariance, pixel_stats)
                             e, na fase 3 (§30.8), extras (tamanho do cristal, variação do tamanho: FINAL_PGV)
  grao_estrutura.py          1.6 (fase 3), estrutura pela densidade (ARQUITETURA §30.8): gancho structure (u_gs_*),
                             FINAL_GS (só quando usado), referência numpy (channel) e constantes do H-1-5207
  labx.py                    1.6, Laboratório (ARQUITETURA §32): scanner de luz branca, película vencida, pré-exposição;
                             variante FINAL_LX/BAKE_LX (só com u_lx_on) e o pc_lab_path_x do nó Laboratório/OFX
  shaders.py                 GLSL 330: COMMON, BASE, EXTRACT, BLUR, NOISE, FINAL, BAKE (BLUR3: um sigma por canal)
  engine.py                  Engine: contexto moderngl, alvos, render(), bake_lut(), cache de LUT
  frame.py                   receita única do quadro (Recipe): entrada → montagem (compose) → valores do look no
                             quadro → build_plan(legal=) → render/render_fit; usada pela prévia, "Salvar quadro",
                             exportação, prévia da exportação, medição de velocidade e linha de comando;
                             legendas gravadas (burn: "copia" antes do look, "digital" depois); 1.7, no_effects
                             (tudo desligado, ARQUITETURA §40)
  keyframes.py               chaves de animação (sem Qt): Key (tempo, valor, curva), as 4 curvas (EASINGS),
                             value_at, clean_keys/to_json (JSON "chaves"), look_values_at, ffmpeg_expr (volume)
  presets.py                 FILM_BASE, BUILTIN (48 presets em 7 grupos), presets do usuário em JSON
  luts.py                    .cube (ler/gravar), LUTs instalados (Premiere/Resolve/Meus LUTs), instalar
  media.py                   ffmpeg/ffprobe: localizar, probe(), NamedPipe, FrameReader, Perf, encoders;
                             transparência: has_alpha, decodes_alpha, leitura RGBA pré-multiplicada (_alpha_graph);
                             sequências de imagens: find_sequence, probe_sequence, sequence_input (image2);
                             1.6: log em float com os super-brancos (float_input), 16 bits exatos da faixa legal
                             (_legal16), perfil sugerido pelos metadados (suggest_input, SUGGEST_RULES, camera_tags,
                             sidecar_tags do XML da Sony)
  export.py                  CODECS, qualidades prontas, output_size() (lado menor), build_encoder_cmd(), ExportQueue,
                             run_job() (grava num parcial e troca no fim; volume alvo; duas passadas do tamanho
                             alvo), frame_pipeline()/preview_frame() (a receita de `frame.py` com os ajustes da
                             exportação; FramePipeline = frame.Recipe), measure_speed(), save_still();
                             saída com alfa: ALPHA_PIX, supports_alpha(), wants_alpha(), STILL_ALPHA_ARGS
  platforms.py               exportação por plataforma (sem Qt): PLATFORMS (YouTube, Instagram, TikTok, WhatsApp,
                             Discord… com fonte oficial), settings_for() → ExportSettings, limites, avisos, SAFE_AREAS
  fit.py                     encaixe num quadro de outra proporção (cortar, bordas, fundo desfocado): plan() → Fit
  loudnorm.py                volume alvo da exportação: loudnorm do ffmpeg em duas passadas (measure, filter_for)
  deps.py                    versão do ffmpeg, download verificado (gyan.dev / BtbN), extract_archive(), pip_install()
  tools.py                   componentes externos (sem Qt): registro TOOLS (versão e SHA-256 fixos), download e
                             instalação atômica, remover, espaço em disco, detecção de programas do sistema;
                             receitas de IA (Recipe: código por manifesto + ambiente Python pelo uv com lista
                             travada + modelos retomáveis), build_env(), fetch_file(), run_process()
  corridorkey.py             CorridorKey (módulo Beta recorte_ia, sem Qt): placa NVIDIA 8.0+ (nvidia-smi),
                             linha de comando e progresso do infer.py, run() num processo separado
  data/                      listas travadas com hash e manifestos de código das receitas (corridorkey/);
                             fontes/ (fontes SIL OFL do app, com OFL.txt e SOURCE.txt: origem e SHA-256);
                             datasheets/ (pontos lidos de datasheets públicos, com a fonte; regra 8)
  fontfile.py                leitor de TrueType (métricas, cmap, contornos da glyf) e cópia com nome único
  textrender.py              texto em RGBA igual em qualquer sistema: FAMILIES (fontes do app), TextStyle, layout(),
                             render() (contorno, sombra, caixa, destaque por palavra; 8/16 bits, alfa direto), paste()
  subtitles.py               legendas (sem Qt): Word, Cue, Subtitles (presas ao arquivo ou da sequência), map_cues()
                             pela montagem, cues_from_words(), SRT/WebVTT, STYLES, faixa na exportação, overlay()
  transcribe.py              transcrição local pelo whisper.cpp (módulo Beta legendas_auto, sem Qt): WAV 16 kHz,
                             whisper-cli com VAD e tempo por palavra, volta para a CPU, transcribe_file/_sequence,
                             make_job()
  silences.py                silêncios (RMS/pico por janela, limiar relativo, duração mínima, folga) e "Cortar pelo
                             texto" (palavras escolhidas → trechos do arquivo a remover), sem Qt
  subedit.py                 edição das legendas no tempo da montagem, guardadas no tempo do arquivo (sem Qt): items(),
                             Ref/Item/Mapping, set_times/move/split/merge/add/delete, busca e troca, import_cues,
                             remove_time (legendas da sequência num corte), words()
  subauto.py                 legendas automáticas da montagem (sem Qt): spans_for() (trechos de cada arquivo com som
                             que a montagem mostra), make_job() (vários trechos num trabalho da fila), apply()
  rangecut.py                tirar trechos de tempo de todas as faixas destravadas (sem Qt): remove_ranges(),
                             to_frames(), find_silences() no som mixado da montagem, text_ranges() (cortar pelo texto)
  jobs.py                    fila de tarefas em segundo plano (sem Qt): CPU/GPU/rede, progresso, cancelar, 1 de GPU
  notify.py                  notificações do sistema (sem Qt): tipos KINDS, preferências notificacoes/…, decide(),
                             textos (Notice), resumo da fila
  recovery.py                recuperação depois de um travamento (sem Qt): marcador da sessão (pid + início), cópias
                             automáticas com rodízio, fila de exportação guardada, scan() das sessões que travaram
  crashlog.py                relatórios de erro e de travamento em <pasta do app>/logs (faulthandler, excepthooks)
  system.py                  CPU, RAM, GPUs NVIDIA, abrir pasta/arquivo no sistema, gravação segura
                             (partial_path, replace_file, atomic_write)
  edgetext.py                máscara do texto de borda (QPainter → numpy)
  testimage.py               cena de teste
  timeline.py                modo Edição: Source, Clip, Track, Layer, Marker, Sequence (montagem, marcadores, emendas
                             de som: micro_fade, audio_crossfade; ferramentas de corte: open_space, ripple_trim_*,
                             split_edit, faixa magnética keep_main/settle_main; tempo: time_map, retime (rampa e
                             reverso), freeze_frame; sem Qt), History; Source.virtual
                             (clipe sem arquivo: kind/SOURCE_KINDS, data)
  timemap.py                 tempo de um clipe (sem Qt): TimeMap (velocidade, rampa por âncoras, reverso; forma
                             fechada e inversa exata, pieces() para o som), clean_ramp, PRESETS/preset_anchors
  chapters.py                capítulos dos marcadores: texto do YouTube (com as regras) e FFMETADATA da exportação
  loudness.py                loudness BS.1770-4 / EBU R128 em numpy (ponderação K, M/S/I, LRA, true peak)
  editparams.py              esquemas dos ajustes por clipe (VIDEO e AUDIO), HSL_COLORS, QUICK_LOOKS
  compositor.py              ajustes do clipe + camada → uniforms do shader CLIP; auto_adjust() (cor automática)
  editshaders.py             GLSL do modo Edição: CLIP (uma camada sobre a tela; u_tex_alpha = textura RGBA
                             pré-multiplicada, alfa na cobertura) e a saída da tela; CLIP_CS/CLIP_TR_CS (1.6: o
                             CLIP/CLIP_TR com a cor simples, só quando a camada traz u_cs_on), CAMERA (1.6: perfil
                             de câmera do clipe → entrada do look, passo antes do CLIP) e OUT_FLOAT (tela em float32)
  masks.py                   1.6, máscaras sem Qt nem GPU: pele em OkLab/OkLCh (skin_mask, conta-gotas skin_hue_of,
                             skin_even) e degradê linear/radial em px@1080 (gradient_mask); GLSL + referência numpy
  planes.py                  1.6, "Cor por planos" do look (módulo Beta cor_planos): uniforms u_cp_*, referência
                             numpy (apply), PRONTOS e BASE_CP (o BASE com imageLin passando por planes())
  colorsimple.py             1.6, cor simples do modo Edição (módulo cor_simples): uniforms u_cs_* e GLSL (cor
                             escolhida, degradê, pele natural), conta-gotas do balanço, "Automático" do clipe
                             inteiro, igualar a outro clipe/imagem, clicar numa cor (sem Qt)
  exposure.py                1.6, zebra e falsa cor da prévia em stops em relação ao cinza de 18% (sem Qt)
  tempo_camera.py            1.6, câmera de cinema (módulo Beta camera_cinema): obturador (pesos da janela aberta,
                             WindowReader/grab_window do arquivo, GLSL da mistura na luz da curva; Engine.temporal_blend)
                             e manivela por clipe (crank_factor, crank_offset); ARQUITETURA §33
  anamorfico.py              1.6, lente anamórfica (módulo Beta): desespremer, barril, bordas (u_anam no BASE,
                             shaders.filmLight) e o risco horizontal (cadeia "streak", Engine._streak)
  data_impressa.py           1.6, data de sete segmentos (módulo Beta): texto, layout em px@1080, u_date_* (BASE)
  scanformatos.py            1.6, formatos de foto no scan (135, meio quadro, 120): textos de borda e a variante do
                             BASE com a tira deitada (rotated, por substituição de texto; Engine._base_program)
  maquina.py                 1.6, máquina do tempo (módulo maquina_tempo): tabela época × lugar → valores do look
  montagem_filme.py          1.6, a montagem na película (módulo Beta montagem_pelicula): cortes secos da V1
                             (edit_info, via frame.Recipe.plan → build_plan(edit=)) e rolos de Super 8
  luz_plano.py               1.6, marcação de luz por plano: pontos da copiadora por clipe (luz_r/g/b, luz_densidade)
                             somados a lab_luz_* no plano da V1 (shot_lights, via frame.Recipe.plan; transição de dois
                             clipes interpolada), mostrador TAPE 25-25-25 (classic); ARQUITETURA §35
  fotometro.py               1.6, fotômetro da película (só tela): latitude do negativo escolhido (caminho A do
                             Laboratório) em stops do cinza, zonas sem detalhe/pé/reta/ombro/estourado, false_color,
                             leitura de um ponto (spot)
  transitions.py             transições de película (sem GPU nem Qt): tipos novos, ajustes por tipo, luz do look
                             (light_of), semente por clipe e apply() → uniforms u_tr_* do shader CLIP_TR
  camera.py                  perfil de câmera por clipe (1.6, sem GPU nem Qt): FOLLOW ("Igual ao do look"), Target
                             (a entrada do look), uses_profiles(), read_profile(), uniforms() do CAMERA, prefill()
                             (clipes novos pela sugestão dos metadados)
  alphashaders.py            GLSL da saída com transparência: PREMUL/CANVAS_OUT (tela RGBA de cor direta) e ALPHA
                             (alfa do look com a geometria do BASE, ALPHA_GEOMETRY)
  sequence.py                camadas decodificadas: grab() (acesso aleatório), SequenceReader (sequencial),
                             canvas_size(), decode_size(), media_info() (MediaInfo "virtual" da montagem);
                             RENDERERS[tipo] + render_source() (geradores dos clipes sem arquivo),
                             THUMBNAIL_FRAME + source_thumbnail()
  generators.py              geradores (sem Qt de interface): GENERATORS (cor, degrade, contagem) com Field (campos em
                             Source.data), desenho determinístico, o bipe da ponta (audiomix.TONES), needs_text()
  titles.py                  títulos (RENDERERS["texto"]): title_of(data), PRESETS, ANIMATIONS, motion(), draw()
                             (textrender → RGBA pré-multiplicado), missing()
  audiomix.py                mixagem do som da montagem com o ffmpeg (prévia e exportação): fades curtos nas
                             emendas, transição de potência constante; forma de onda; decode_wav/WavReader
                             (som do arquivo para o medidor); TONES/tones() (tons exatos à amostra, o bipe)
  resolve.py                 plugin do DaVinci Resolve: gera os DCTLs (Cor, Textura, Projetor, presets) e LUTs;
                             dialetos dctl/glsl/cpp do mesmo kernel; atalhos ofx_* (instalar o plugin OpenFX)
  ofx.py                     plugin OpenFX: gera plugins/ofx/generated (dialeto cpp), parâmetros/presets, pacote e
                             instalação (pasta do OpenFX, com administrador)
  ui/                        main_window, export_dialog, queue_dialog, job_bridge (fila → sinais do Qt), viewer, looks,
                             widgets, store (desfazer/refazer), theme, icons, prefs (QSettings),
                             welcome (boas-vindas e novidades), language_dialog, update_dialog;
                             modo Edição: edit_model (TimelineModel: sequência + histórico + seleção),
                             timeline_view (TimelineEditor), edit_panels (MediaBin, ClipInspector),
                             keyframes_ui (losangos das chaves: KeyRows, KeyStrip), tempo_ui (rampa, reverso,
                             congelar este quadro),
                             markers (MarkerDialog, ChaptersDialog), meter (AudioMeter, módulo medidor_som),
                             scopes (histograma, forma de onda, parada RGB, vetorscópio),
                             transitions_ui (transições de película: inspetor, menu "Transição" do corte,
                             desenho na linha do tempo, módulo),
                             sequence_dialog; resolve_dialog (plugin do DaVinci);
                             imageseq_dialog (imagens numeradas), alphaview (xadrez da transparência),
                             generators_ui (menu Novo da Mídia, GeneratorEditor), titles_panel (TitleEditor);
                             corridorkey_dialog (Recorte por IA, Beta);
                             legendas: subtitles_ui (SubtitleController, SubtitlesUI: botão, painel e faixa na
                             janela), subtitle_lane (faixa Legendas da linha do tempo), subtitles_panel (painel),
                             subtitle_style (StyleEditor), transcribe_dialog (Gerar legendas, Beta), text_cut
                             (Cortar pelo texto), silences_dialog (Remover silêncios);
                             settings_dialog (Configurações) + pages/ (geral, recursos, componentes: ffmpeg,
                             ferramentas e programas do sistema, placa de vídeo e bibliotecas...);
                             profile_dialog (perfil de recursos no 1º acesso), module_notice (aviso de
                             recurso desligado em uso), input_notice (1.6: perfil sugerido pelos metadados, com
                             um botão);
                             1.6, cor: cor_ui (ponto único de ligação com a janela), planes_ui (cartão da Cor
                             por planos), color_tools (barra "Cor simples" do inspetor), preview_tools (camadas
                             da tela: Context, PreviewTools), preview_bar (zebra, falsa cor, referência);
                             1.6, grao_fisico_ui (a linha "Modelo do grão no negativo" sob o módulo grao_fisico);
                             1.6, câmera e formato: filme_ui (ponto único de ligação: cartões dos módulos novos e o
                             botão da máquina do tempo), maquina_ui (janela da máquina do tempo)
                             1.6, luz e fotômetro: luz_fotometro_ui (ponto único de ligação), luz_plano_ui (cartão
                             "Luz da copiadora" do inspetor e os atalhos Alt+R/G/B/D), fotometro_ui (botão
                             Fotômetro da barra da prévia, camada de preview_tools e leitura de um ponto)
                             1.7, sem_efeitos_ui ("Desligar todos os efeitos": botão, Shift+D, pergunta ao exportar)
                             notificações e recuperação: notifier (Notifier + backends bandeja/D-Bus/nulo),
                             recovery_ui (Guard, cópias automáticas, aviso depois de um travamento),
                             crash_dialog (erro inesperado), pages/notificacoes e pages/recuperacao
plugins/ofx/                 plugin OpenFX (C++, funciona no Resolve gratuito): openfx/ (OpenFX 1.4, BSD-3),
                             generated/ (gerado por ofx.py), src/ (pc_core, pc_ofx, pc_capi, pc_json), build.py,
                             build_windows.bat, build_linux.sh → dist/PeliculaConverter.ofx.bundle
tools/                       i18n_extract.py (textos), gerar_ofx.py (regenera plugins/ofx/generated),
                             gerar_manifesto.py (manifesto SHA-256 do código de um commit, para receitas),
                             ajustar_grao.py (constantes de grao.py a partir de data/datasheets, offline)
                             ajustar_lab.py (filmes "(datasheet)" do Laboratório e matrizes de corante, offline)
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
.github/workflows/componentes.yml  componentes compilados no CI (whisper.cpp): manual, publica a pre-release
                             componente-<nome>-<versão> com SHA256SUMS.txt
build.bat / build.sh         build local: executáveis + .zip/.msi (Windows) ou .tar.gz/.deb (Linux)
```

## Regras que não podem ser quebradas

1. **Prévia e exportação usam o mesmo caminho.** Todo quadro mostrado ou gravado passa pela **receita
   única** `frame.Recipe` (entrada → `Engine.compose` → valores do look no quadro → `look.build_plan(...,
   legal=)` → `render`/`render_fit`): a prévia da janela, as miniaturas dos presets, "Salvar quadro", a
   prévia da exportação, a medição de velocidade, a exportação e `pelicula-cli quadro`/`exportar`. Quem
   chama só muda os campos (tamanho, profundidade, pontilhado); nunca monte o quadro à mão em outro lugar.
   Todo efeito vive em `look.build_plan()` + `shaders.py`/`Engine.render()`. Nunca implemente um efeito só
   na interface, só na exportação ou só no "Salvar quadro". No modo Edição vale o mesmo: ajuste de clipe só
   em `compositor.py` + `editshaders.py` / `Engine.compose()`; qual quadro de qual arquivo aparece só em
   `timeline.Sequence.src_frame()` / `layers_at()`; som só em `audiomix.py` (a prévia toca a mesma mixagem
   que a exportação grava). Chaves de animação viram valores num lugar só: `Sequence.values_at()` →
   `Layer.values` (imagem e volume do som) e `keyframes.look_values_at()` pela receita (look); nunca leia
   `clip.values` para desenhar um quadro. Imagem de camada com 4 canais é sempre RGBA **pré-multiplicado**
   (transparência: `media.FrameReader(alpha=)` e geradores de `sequence.RENDERERS`); com 3 canais, opaca.
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
8. **Dados de fabricantes só de publicações públicas.** Curvas e números de datasheets e publicações técnicas
   públicas (Kodak, Fujifilm, fórmulas de log das câmeras…) podem calibrar os modelos, com a fonte registrada
   junto dos dados (publicação, revisão, página e figura; decisão do autor em 23/10/2026). Não copie PDFs nem
   gráficos para o repositório, não inclua LUTs proprietários (Adobe, Blackmagic), não use perfis de terceiros
   sem licença e não apresente o resultado como oficial. Presets com nomes de marcas continuam sendo
   aproximações; mantenha o aviso legal (README e "Sobre": as marcas são dos donos e o app não é um produto
   oficial) e, quando um modelo for calibrado por datasheet, diga isso nele e no `docs/EFEITOS.md`.
9. **Compatibilidade de presets.** Presets são JSON com chaves de `params.PARAMS` e passam por
   `params.sanitize()`. Não renomeie nem remova chaves sem migração. Parâmetros novos precisam de um
   **padrão neutro** (que não mude o visual de presets antigos). IDs de presets prontos são gravados
   na sessão (`session_preset`): não renomeie. O mesmo vale para os ajustes de clipe
   (`editparams.VIDEO`/`AUDIO`, gravados nos projetos): padrão neutro = clipe idêntico ao arquivo.
10. **Dependências mínimas.** Em tempo de execução só PySide6, moderngl (+glcontext) e numpy; o resto
    é biblioteca padrão. Nada de Pillow, OpenCV, SciPy, requests. O ffmpeg é externo e só é baixado
    de fontes confiáveis com conferência de SHA-256 (`deps.py`). Outras ferramentas externas (IA etc.)
    são **componentes baixados à parte**, nunca dentro do pacote, com versão e SHA-256 fixos no código
    (`tools.py`, receita "Nova ferramenta externa"); as de Python (PyTorch etc.) rodam num ambiente
    próprio montado pelo uv e **sempre num processo separado**, nunca no processo do app (receita
    "Novo ambiente Python (uv)").
11. **Multiplataforma.** Use `system.open_path()`/`system.reveal()` em vez de `os.startfile`/`explorer`,
    `Perf.popen_kwargs()` para prioridade de processos e `media.NO_WINDOW` só no Windows. Caminhos
    do Windows ficam atrás de `sys.platform == "win32"`. O macOS fica desativado
    (`deps.PLATFORM_ENABLED`, aviso em `app.py`, job do CI com `if: false`) até ser testado.
12. **Não sujar o ambiente do usuário.** Preferências só por `ui/prefs.settings()` (nunca
    `QSettings(APP_NAME, APP_NAME)` direto, que ignora redirecionamentos). Testes e automações
    definem `PELICULA_SETTINGS_DIR` (preferências num `.ini` temporário) e `APPDATA` (presets e
    LUTs) — a `conftest.py` já faz os dois — e encerram com `app.exit(0)`, nunca fechando a
    `MainWindow` (o `closeEvent` grava a sessão).
13. **Projetos `.plc` são um formato público.** `project.FORMAT` (5) é o maior formato que o app lê; o
    gravador usa o **menor** que o projeto precisa (`project.needed_format`): 1 = só o arquivo inteiro, sem
    mudanças; 2 = com o bloco `"edicao"` (JSON de `timeline.Sequence`); 3 = usa algum recurso da 1.5; 4 = usa
    algo da 1.6; 5 = usa algo da 1.7 (listados em `"recursos"`). **Ajuste ou opção nova** (look ou clipe) não
    precisa de registro: o retrato do que a 1.6 lê (`pelicula/data/conhecidos_1_6.json`, `params.beyond_1_6`;
    nunca editar, nem o da 1.5) faz o projeto ir para o 5 quando o valor sai do padrão ou é uma opção nova.
    **Estrutura nova no JSON** (campo, bloco, tipo de fonte) que versões antigas não entenderiam: **uma linha** em
    `timeline.FEATURES_V5` (da montagem) ou `project.FEATURES_V5` (do projeto) — os da 1.6 ficam em
    `timeline.FEATURES_V4` e `project.FEATURES_V4`, os da 1.5 em `timeline.FEATURES` e `project.FEATURES_V3` — e o
    campo dele no JSON só quando usado. Assim um projeto que não usa nada novo continua abrindo nas versões
    antigas, e um que usa é recusado com aviso em vez de abrir sem o recurso. Formato antigo abre pelos passos
    puros de `project.MIGRATIONS` e `timeline.MIGRATIONS` (testados com os projetos gravados pela 1.4 e pela 1.6 em
    `tests/data/projetos_1_4/` e `tests/data/projetos_1_6/`);
    aumente um formato só com um passo novo. Valores passam por `params.sanitize()`.
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
16. **Curvas de câmera declaram o domínio; a faixa vem da fonte.** Toda curva de entrada está em
    `look.INPUT_DOMAIN` (`"cv"` = código de 10 bits da câmera, `"sinal"` = sinal de vídeo), com o documento
    do fabricante citado. Todo `build_plan` de uma imagem decodificada recebe `legal=` da fonte
    (`media.legal_range`, `sequence.legal_range`); LUTs ficam no domínio da curva. Veja *Adicionar um perfil
    de entrada* abaixo e `docs/ARQUITETURA.md` (seção 5.1).
17. **Recurso opcional é módulo.** Todo recurso que o usuário pode dispensar entra em
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
| `tests/test_timeline.py` | montagem sem GPU: dividir, aparar, mover (sobrescreve), apagar com e sem fechar o espaço, ligar/desligar, velocidade, `layers_at` com transições, JSON e histórico; ferramentas de corte: inserir, Q/W, cortes J/L (sobrevivem a mover/dividir/apagar/velocidade/desfazer) e as regras da faixa principal magnética |
| `tests/test_keyframes.py` | chaves de animação: curvas, limpeza e JSON, âncora em cada edição (mover, aparar, dividir, sobrescrever, velocidade, apagar, relocalizar, colar), uniforms, `decode_size`, grafo do som e envelope medido num tom com o ffmpeg, chaves do look (receita, projeto, fila, CLI) e quadros iguais aos de um clipe/look fixo na GPU |
| `tests/test_chaves_ui.py` | casos de `chaves_ui_cases.py`: losangos do inspetor (estados, chave no cursor, chave automática, arrastar = um passo do desfazer, setas, menu de curvas, apagar/limpar), do look, da linha do tempo (juntos, dica, clique vai até a chave, arrastar com ímã no cursor, Shift, Delete, desfazer), `KeyStrip` e a janela (faixas sob a barra e "Look" na Edição) |
| `tests/test_timemap.py` | mapa de tempo sem ffmpeg: linha reta sem rampa, monótono, inversa exata, forma fechada = integral, presets, JSON (projeto sem rampa igual), rampa presa à imagem em dividir/aparar/velocidade, V1 magnética, reverso = espelho exato (velocidade, dividir, aparar, J/L, com rampa), grafo do som em blocos |
| `tests/test_freeze.py` | "Congelar este quadro": inserir e sobrescrever (imagem parada, som em silêncio, sincronia depois), look e quadro daquele instante (rampa, reverso), JSON, recusas, V1 magnética, desfazer |
| `tests/test_tempo_media.py` | com o ffmpeg: quadros da rampa e do reverso = `src_frame` por `SequenceReader` e `grab` (blocos pequenos no reverso), som da rampa no quadro certo (estalos), som do reverso = arquivo ao contrário (varredura com emenda de blocos), quadro congelado = quadro do arquivo e, na GPU, igual ao quadro de antes |
| `tests/test_tempo_ui.py` | casos de `tempo_ui_cases.py`: seção da rampa no cartão Velocidade, aplicar/tirar com desfazer, menu do clipe, Reverso (caixa e menu), congelado sem rampa, "Congelar este quadro…" (duração, inserir/sobrescrever) e Shift+F na janela |
| `tests/test_fundacao_ui.py` | casos de `fundacao_ui_cases.py`: "Salvar quadro" = exportação (Película e Edição), API de chaves do `TimelineModel` e do `ParamStore` com desfazer, chaves do look e de clipes na janela, transparência |
| `tests/test_compositor.py` | uniforms do shader CLIP; na GPU: clipe neutro sai idêntico (8 e 16 bits), cada ajuste muda a imagem no sentido certo |
| `tests/test_sequence.py` | `grab` × `SequenceReader` iguais quadro a quadro; exportação de uma montagem com corte e som |
| `tests/test_virtual_sources.py` | clipes sem arquivo com um gerador de teste: JSON (`"tipo"`, `"dados"`) e formato 3, tempo do clipe, quem ignora a fonte (arquivos que faltam, relocalizar, entradas da exportação, `media_info`, `legal_range`, som, `"relativo"` do projeto), `grab` = `SequenceReader`, saída conferida/convertida, tipo sem gerador = transparente e, na GPU, o gerador sobre um arquivo com prévia = exportação |
| `tests/test_alpha.py` | transparência: detecção (ProRes 4444, PNG, WebM VP9 com `alpha_mode`, paleta), leitura RGBA pré-multiplicada em 8/16 bits, libvpx, e na GPU o fundo da V1 exato onde o alfa é 0, mistura no alfa parcial, opacidade, corte, mesclagens, transição, sem franja escura ao reduzir/girar/ampliar, `grab` = `SequenceReader` |
| `tests/test_image_sequences.py` | imagens numeradas: padrão `%0Nd`/`%d`, buracos, pasta, leitura a partir de um quadro, JSON `"sequencia"`, relocalizar, exportação |
| `tests/test_transparency_export.py` | fundo transparente: tela RGBA (8/16), cor do look igual à opaca, alfa com a geometria do look (Moldura, scan, tremor, força geral), encaixe, ida e volta em ProRes 4444, PNG 8/16, TIFF e VP9, "Salvar quadro", prévia da exportação = arquivo |
| `tests/test_generators.py` | cor, degradê e ponta em 8/16 bits, `grab` = `SequenceReader`, thread, miniatura e o bipe medido no som mixado (±1 amostra a 48 kHz em 24, 25 e 29,97 fps, com aparar) |
| `tests/test_titles.py` | títulos: dados conferidos, estilos prontos, pré-multiplicação, posição, animações em quadros fixos, tempo do clipe (aparar, velocidade, congelar), **hashes fixos** (iguais no Windows e no Linux), módulo e `used_by` |
| `tests/test_alfa_titulos_ui.py` | casos de `alfa_titulos_ui_cases.py`: imagens numeradas, Fundo transparente, janela Exportar com alfa, xadrez, menu Novo, campos do gerador e editor de títulos com desfazer, aviso de caractere, Sobre, módulo desligado |
| `tests/test_audiomix.py` | comando do ffmpeg (filtros por clipe) e mixagem de verdade |
| `tests/test_audio_fades.py` | emendas de som: projeto antigo gera o mesmo grafo da 1.3, fades curtos só nos cortes, tempo da transição e potência constante medida com o ffmpeg |
| `tests/test_loudness.py` | loudness (casos da EBU Tech 3341/3342, true peak, contra o `ebur128` do ffmpeg) e o WAV do medidor (`WavReader`, `decode_wav`) |
| `tests/test_chapters.py` | capítulos: tempos relativos ao trecho, regras do YouTube, FFMETADATA e o comando do codificador |
| `tests/test_edicao_som_ui.py` | casos de `edicao_som_ui_cases.py`: marcadores (teclas, mouse, menus, diálogo), capítulos, transição de som, medidor e a janela (M/Shift+M, medidor no relógio da prévia, módulo desligado) |
| `tests/test_corte_ui.py` | casos de `corte_ui_cases.py`: modelo (desfazer/refazer de inserir, Q/W, J/L, faixa magnética), botão Inserir e Ctrl, Alt ao aparar, menu Corte J/L, Mídia `,`/`.`, diálogo da sequência e a janela (J/K/L, K + J/L, Ctrl+L, Q/W, ajuda de atalhos) |
| `tests/test_transitions.py` | transições de película: escolhas só no fim, JSON enxuto (projeto antigo grava o mesmo JSON), formato 3, camadas e andamentos de cada tipo, uniforms do `CLIP_TR`; na GPU: pontas iguais aos clipes puros (8 e 16 bits), determinismo, cinza neutro em rec709/S-Log3/LogC3, fusão e exposição pelas fórmulas da curva, prévia = exportação e transições antigas iguais à BASE (`transicoes_base.py` + `data/transicoes_base.json`) |
| `tests/test_transicoes_ui.py` | casos de `transicoes_ui_cases.py`: inspetor (ícones, dicas, ajustes do tipo, módulo desligado), menu "Transição" do corte (alvo, desfazer num passo, última duração, faixa travada), desenho na linha do tempo e o módulo na janela |
| `tests/test_lab.py` | Laboratório: cinza neutro em toda combinação negativo × cópia × processo, luzes da copiadora, revelação forçada |
| `tests/test_lab_lad.py` | Laboratório conferido pelo LAD da Kodak (M9): cinza de 16%, pontos da copiadora, escala de cinza |
| `tests/test_lab_processos.py` | Laboratório da 1.6 (`labx.py`): scanner de luz branca, película vencida (véu sobe com os anos), pré-exposição, reversível e revelação cruzada; desligados não mudam nada; GPU (prévia e LUT) = numpy |
| `tests/test_lab_ui.py` | os controles novos do Laboratório da 1.6 no cartão da seção (casos em `lab_ui_cases.py`, subprocesso offscreen) |
| `tests/test_lab_datasheet.py` | filmes "(datasheet)" do Laboratório (M8): constantes = `tools/ajustar_lab.py`, fonte e tolerância nos JSONs, ids no fim, cinza e escala de cinza do par |
| `tests/test_luz_plano.py` | marcação de luz por plano: neutra no padrão, pontos do clipe da V1 nos quadros certos (cortes, transições interpoladas, V2 não muda o plano), 12 pontos = 1 stop da cópia, JSON esparso e formato 4, desfazer, prévia = exportação |
| `tests/test_presets_16.py` | presets da 1.6 (slide reversível, revelação cruzada, vencida, pré-exposição): no fim da lista, processo certo, efeito no eixo do cinza |
| `tests/test_fotometro.py` | fotômetro: latitude por negativo (Vision3 × Double-X), revelação, vencida e pré-exposição movem os limites como documentado, zonas da camada em stops conhecidos, leitura de um ponto, nada no caminho de render |
| `tests/test_luz_fotometro_ui.py` | casos de `luz_fotometro_ui_cases.py`: cartão "Luz da copiadora" (mostrador, aviso, ±1, zerar, copiar, desfazer), atalhos Alt+R/G/B/D, módulo "laboratorio"; botão Fotômetro (Beta desligado, camada só na tela, leitura de um ponto, some com o módulo) |
| `tests/test_resolve.py` | DCTLs gerados (estrutura, limites de controles) e paridade de cor com o app na GPU |
| `tests/test_grao.py` | grão e textura da 1.6: com os ajustes novos no padrão, planos, quadros (Película e Edição, 8/16 bits), LUTs, nós do plugin e OpenFX iguais à BASE bit a bit (`grao_base.py` + `data/grao_base.json`; GPU e compilador da gravação) |
| `tests/test_grao_efeitos.py` | o que cada ajuste da 1.6 faz ligado: modelo (constantes = `tools/ajustar_grao.py`, fonte dos datasheets), px@1080, resposta em frequência e brilho na GPU, grão moldado pela cópia, halação física (área lisa igual), respiração (estatística, sem estado preso), LUT igual, determinismo |
| `tests/test_grao_ui.py` | os controles de grão e textura da 1.6 nos cartões das seções (casos em `grao_ui_cases.py`, subprocesso offscreen) |
| `tests/test_grao_fisico.py` | grão físico (1.6): padrão "ruido" e módulo Beta, plano em px@1080, constantes = `tools/ajustar_grao.py`, referência numpy do modelo booleano (cobertura média, variância exata, pico no meio, sinal da assimetria, correlação ~ raio), sigma D na abertura = datasheet, cópia molda o grão, LUT igual, determinismo sem estado preso, prévia = exportação, independência da resolução |
| `tests/test_grao_estrutura.py` | estrutura pela densidade (1.6, fase 3): padrão neutro, constantes = `tools/ajustar_grao.py`, sigma D por densidade = pontos do H-1-5207, numpy = GLSL, assimetria/força/tamanho de cada camada no look, aglomeração, pesos por tom, brilho médio, grão no negativo, LUT igual, determinismo, prévia = exportação, resolução |
| `tests/test_grao_fisico_extras.py` | tamanho do cristal e variação do tamanho do grão físico (1.6, fase 3): padrão neutro, tabelas = ferramenta, E[ρ²] = 1, espalhamento do raio na GPU, variância = modelo exato com raios aleatórios, sigma D na abertura = datasheet, brilho/LUT iguais, determinismo, prévia = exportação, resolução |
| `tests/test_entrada.py` | perfis de entrada: domínio de cada curva (código × sinal), pontos de referência dos fabricantes, faixa legal × cheia, ida e volta com o LUT, HLG/PQ e detecção do HDR |
| `tests/test_entrada_base.py` | a entrada da 1.6 não muda os padrões: Película e Edição em 8/16 bits, LUT exportado e plugin iguais à BASE (`entrada_base.py` + `data/entrada_base.json`) |
| `tests/test_entrada_leitura.py` | leitura de log com super-brancos (códigos acima de 940 sobrevivem, em float32) e 16 bits exatos da faixa legal (preto, cinza e branco) com o ffmpeg |
| `tests/test_entrada_gamut.py` | "Proteger cores saturadas": a fórmula da ACES RGC em float64, a GPU contra ela, limites por gamut, continuidade varrendo a saturação, 0% = sem o ajuste (também no LUT) |
| `tests/test_entrada_camera.py` | perfil de câmera por clipe: chaves esparsas, JSON e formato 4, clipe Rec.709 num look log, luz acima de 1,0 na tela, transparência e dois vídeos log de verdade (S-Log3 + V-Log) numa montagem |
| `tests/test_entrada_sugestao.py` | perfil sugerido pelos metadados: tabela de dicionários do ffprobe, XML da Sony, etiquetas guardadas, preenchimento dos clipes novos |
| `tests/test_entrada_ui.py` | casos de `entrada_ui_cases.py`: cartão "Câmera" do inspetor, aviso da sugestão (um clique, nunca ao reabrir), clipes novos preenchidos num passo do desfazer |
| `tests/test_ofx.py` | plugin OpenFX: código gerado em dia, `.ofx` (pontos de entrada), paridade da cor e do quadro com o app, LUT rápido, `.json`, efeito num host de teste (`ofxhost.py`); compila na hora (pula sem compilador) |
| `tests/test_sem_efeitos.py` | `frame.Recipe.no_effects` e `ExportSettings.no_effects` sem GPU (receita, padrões, JSON antigo); na GPU: igual à montagem com os ajustes de imagem no padrão e o preset "original" (8 e 16 bits), a edição continua, campo desligado igual, arquivo direto, `grab` = `SequenceReader`, exportação |
| `tests/test_sem_efeitos_ui.py` | casos de `sem_efeitos_ui_cases.py`: botão, etiqueta e Shift+D nos dois modos; desligar e religar não muda valores, chaves, montagem, desfazer, alterações nem imagem; slider movido desligado, leitura de log e de perfil do clipe, obturador, miniaturas, abrir religa, `.plc` igual, a pergunta ao exportar, trabalho guarda o campo; seletores de modo e de comparação (rótulos, ícones, estilos, tecla C) |
| `tests/test_correcoes_17_ui.py` | casos de `correcoes_17_ui_cases.py`: botão, telas e `self.mode` iguais ao abrir projetos e Ctrl+Z no histórico certo (#50), a prévia toca o som do que ficou depois de apagar, mover, mudar volume e faixa (#51), âncora do zoom pelo marcador, pelo ponteiro e pelo centro (#53), Exportar com a fila ocupada e destino repetido (#59) |
| `tests/test_fila_exportacao.py` | fila de exportação sem GPU: trabalho novo não mexe no que está rodando, destino repetido (`queue_clash`), nome livre (`free_output`) |
| `tests/test_edit_ui.py` | widgets da edição em subprocesso *offscreen* (modelo, linha do tempo, inspetor, mídia, medidores) |
| `tests/test_main_window_edit.py` | janela inteira: abrir, trocar de modo, dividir, apagar, ajustar, exportar a montagem e salvar o projeto |

Componentes e fila de tarefas (sem rede: pacotes locais, `file://` e um servidor em 127.0.0.1; a pasta
do app vai para uma pasta temporária via `LOCALAPPDATA`/`XDG_DATA_HOME`):

| Arquivo | O que confere |
|---|---|
| `tests/test_tools.py` | registro consistente (ids, https, SHA-256, módulos), instalação atômica e relatada, SHA-256 ou tamanho errado não instala nada, caminhos suspeitos em zip/tar, cancelar, atualizar/manter versões, remover, espaço em disco, ffmpeg pelo fluxo de `deps.py`, detecção do Resolve |
| `tests/test_jobs.py` | fila: ordem dos eventos, erros, cancelar (na espera e rodando), um trabalho de GPU por vez, 200 trabalhos de 8 threads |
| `tests/test_componentes_ui.py` | página Componentes e ponte do Qt em subprocesso *offscreen*: baixar/remover pela fila, progresso e cancelar, erro de SHA-256, licença com aceite, `show_deps`, sinais na thread principal; receitas: requisitos, download incompleto, Testar, créditos e licenças do CorridorKey |
| `tests/test_ambiente.py` | receita de ambiente Python com o uv falso (`tests/uv_falso.py`): dois ambientes que não se tocam, retomada depois de cair, download com `Range`, SHA-256 errado, cancelar, código conferido por manifesto, instalação inteira e troca de pasta |
| `tests/test_corridorkey.py` / `test_corridorkey_ui.py` | requisitos pelo `nvidia-smi` falso, instalação falsa no formato do CorridorKey, recorte com `infer.py` falso num processo de verdade (PATH, pasta parcial, cancelar, erros), janela do recorte |
| `tests/test_corridorkey_real.py` | **manual**: `PELICULA_TESTE_CORRIDORKEY=1` (e `PELICULA_TEST_TIMEOUT=0`) baixa ~7,6 GB das fontes oficiais em `PELICULA_TESTE_CORRIDORKEY_DIR` e recorta um clipe 1080p na placa NVIDIA |
| `tests/test_transcribe.py` | transcrição com o `whisper-cli` falso (`tests/whisper_falso.py`): comando, progresso, JSON → palavras, volta para o processador quando a placa falha, cancelar, erros em PT-BR, componentes faltando, fila; **manual**: `PELICULA_TESTE_WHISPER=1` + `PELICULA_TESTE_WHISPER_ARQUIVO=<vídeo com fala>` baixa o whisper.cpp, o modelo small e o VAD numa pasta temporária e transcreve |

Texto, legendas e silêncios:

| Arquivo | O que confere |
|---|---|
| `tests/test_textrender.py` | fontes do app (SHA-256 do `SOURCE.txt`, licença ao lado, catálogo), leitor de TrueType, estilo em JSON, quebra de linha, acentos, e **hashes fixos das imagens** (iguais no Windows e no Linux: mudou o desenho de propósito, atualize os hashes e explique no commit) |
| `tests/test_subtitles.py` | SRT/WebVTT (ler e gravar), agrupar palavras, tempo pela montagem (cortes, velocidade, congelado), estilos, JSON, faixa na exportação com o ffmpeg de verdade (MP4, MOV, MKV, WebM), desenho no quadro |
| `tests/test_silences.py` | silêncios em som sintético (limiar relativo, duração mínima, folga, estalo), leitura pelo ffmpeg, cancelar, "Cortar pelo texto" |
| `tests/test_legendas_projeto.py` | bloco `"legendas"` da montagem, recurso do formato 3, projetos antigos iguais, desfazer, JSON estável no vaivém |
| `tests/test_subedit.py` | itens = `timeline_cues`, edições pelo `Mapping` (velocidade, aparo), âncora, dividir/juntar, busca e troca, importação, `map_cues` depois de edições e cortes |
| `tests/test_legendas_gravadas.py` | `Burn`, composição pré-multiplicada, escolhas da exportação e arquivo ao lado; na GPU, "cópia" passa pelo look e "digital" = look + legenda; exportação = prévia = `pelicula-cli quadro`; faixa vista pelo ffprobe e `--legendas srt` |
| `tests/test_subauto.py` | o que ouvir na montagem (cortes, velocidade, seleção, faixas mudas) e a fila com o `whisper-cli` falso (vários trechos, volta para o processador, cancelar, componentes faltando) |
| `tests/test_rangecut.py` | tirar trechos de todas as faixas (sincronia, faixa travada, chaves, marcadores, legendas, corte J/L), cortar pelo texto, silêncios de verdade na mixagem (tom, silêncio, tom) |
| `tests/test_legendas_ui.py` | casos de `legendas_ui_cases.py`: faixa Legendas, painel, estilos, janela de exportação, janela principal, Gerar legendas (fila, um passo de desfazer, erros), Remover silêncios e Cortar pelo texto |

Notificações e recuperação (a pasta do app vai para uma pasta temporária; nenhuma notificação de verdade
aparece: a `MainWindow` nasce com o backend nulo e os casos usam backends falsos):

| Arquivo | O que confere |
|---|---|
| `tests/test_notify.py` | tipos e preferências, `decide()` (foco, tipo, módulo desligado só pisca nas exportações, botão de teste), textos e traduções, resumo da fila |
| `tests/test_notify_ui.py` | casos de `notify_ui_cases.py`: notificador (som, piscar, clique abre arquivo, pasta ou janela), backend com defeito, D-Bus com a chamada tipada (servidor falso), bandeja, downloads de componentes pela fila de tarefas, página Notificações |
| `tests/test_recovery.py` | marcador da sessão, rodízio das cópias, pid vivo ou reaproveitado, `scan()`, fila guardada, `ExportJob.to_dict/from_dict`, travamentos de verdade em subprocessos (`os._exit`, `faulthandler._sigsegv`) |
| `tests/test_crashlog.py` | relatório legível, `sys.excepthook`/`threading.excepthook`, limites da pasta, `faulthandler` num subprocesso |
| `tests/test_recovery_ui.py` | casos de `recovery_ui_cases.py`: cópias só com mudanças não salvas (e nenhuma depois de salvar), recuperar (Película e Edição) marcado como modificado, fila de volta, parciais, aviso, erro inesperado, página Recuperação (a janela se pula sem OpenGL 3.3) |
| `tests/test_recovery_app.py` | o `app.main()` inteiro depois de um travamento simulado: pergunta antes das boas-vindas, recupera e fecha sem deixar nada |

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
   y para baixo. Um uniform do FINAL que o plano só grava com o efeito ligado (para os planos de
   sempre não mudarem) precisa do valor neutro em `Engine.FINAL_NEUTRAL`, senão o valor de um quadro
   anterior fica no programa.
4. Se o efeito é **só de cor**, coloque-o dentro de `colorPipe()` para que entre também nos LUTs
   exportados (`BAKE`). Efeitos espaciais ou temporais não cabem num LUT.
5. Se um preset precisar dele, ajuste `presets.FILM_BASE` ou o preset.
6. Documente em `docs/EFEITOS.md` (linha na tabela da seção) e no `CHANGELOG.md`; rode o `pytest`.

### Adicionar um ajuste de clipe (modo Edição)

1. **`editparams.py`**: um `F`/`B`/`C`/`W` (roda) na seção certa de `VIDEO_SECTIONS` ou
   `AUDIO_SECTIONS`, com padrão neutro, chave sem acento e rótulo/dica em PT-BR. O inspetor aparece
   sozinho. Se for de cor, ele entra no "Copiar/Colar ajustes" (seções em `COLOR_SECTIONS`). Ponha a
   chave em `editparams.SPARSE_KEYS`: no padrão ela não vai para o JSON e um projeto antigo grava igual.
2. **Imagem**: `compositor.py` transforma o valor em uniform(s) e `editshaders.CLIP` usa; mantenha
   o atalho de "tudo neutro = cópia exata". **Som**: `audiomix.py` acrescenta o filtro do ffmpeg na
   cadeia do clipe.
3. Teste em `tests/test_compositor.py` (ou `test_audiomix.py`) e documente em `docs/EDICAO.md`.
4. Se ele deve aceitar chaves de animação, veja *Tornar um ajuste animável*.

### Adicionar um tipo de transição (modo Edição)

1. **`editparams.py`**: o tipo **no fim** das escolhas de `entrada_tipo`/`saida_tipo` (nunca renomeie nem
   reordene) e em `EXTRA_IN`/`EXTRA_OUT` (e `EXTRA_TWO_CLIP` se mostra o clipe anterior por baixo); ajustes
   novos na seção "Transições", com padrão neutro e em `SPARSE_KEYS`.
2. **`transitions.py`**: número em `KIND_IDS`, ajustes em `PARAMS`, geometria (se mexe no quadro) em
   `apply()`; **`editshaders.py`**: um ramo no `main` do `CLIP_TR`, misturando com `lightMix`/`lightGain`/
   `lightAffine` (pontas exatas, cinza neutro) e ruído só com `u_tr_seed` e `u_tr_index`.
3. **`ui/transitions_ui.py`**: dica em `TIPS`, nome curto em `SHORT` e o desenho em `draw_glyph`.
4. Testes: o tipo entra sozinho nos laços de `tests/test_transitions.py` (pontas, determinismo, prévia =
   exportação); acrescente o caso no teste do cinza neutro se ele não tinge de propósito. Documente em
   `docs/EDICAO.md` e na seção 26 de `docs/ARQUITETURA.md`.

### Tornar um ajuste animável

As chaves (`keyframes.py`, `docs/ARQUITETURA.md` seção 22.3) valem para ajustes marcados com
`Param.animatable`. Antes de marcar, confira que o ajuste é **contínuo** (número, cor ou roda; escolhas e
liga/desliga só mudam de degrau e quase nunca fazem sentido animados) e que o valor é lido **por quadro**:

1. **Marque** no esquema: clipe de vídeo em `editparams.ANIMATABLE_VIDEO` (as seções de cor já entram todas),
   som em `editparams.ANIMATABLE_AUDIO`, look em `params.ANIMATABLE_KINDS` (todo `float`/cor já anima; um
   `int` ou uma escolha precisaria entrar à mão). Nunca desmarque um ajuste que já anima: projetos gravados
   têm chaves dele (a leitura descartaria a animação).
2. **Leia o valor avaliado**: na imagem, use `Layer.values` (`compositor.clip_uniforms` já faz — nunca
   `clip.values` direto); no look, `build_plan` recebe os valores do quadro pela receita. Se o ajuste muda o
   **tamanho** da decodificação (como `escala`), use o maior valor das chaves (`keyframes.max_value`, como
   `sequence.decode_size`). No som, o filtro precisa avaliar por bloco: siga `audiomix.volume_envelope`
   (`keyframes.ffmpeg_expr` + `eval=frame`) — um filtro do ffmpeg sem expressão por tempo não anima.
3. **Edições**: nada a fazer; as operações da montagem já mantêm a âncora. Uma operação **nova** que muda o
   começo do clipe com a imagem parada chama `clip.shift_head(delta)`; uma que estica o tempo do clipe,
   `clip.rescale_keys(razão)`.
4. **Teste** em `tests/test_keyframes.py`: o quadro com a chave no meio é bit a bit o de um clipe (ou look)
   fixo com o valor interpolado, e sem chaves nada muda.

### Mudar a montagem (timeline)

Toda regra de tempo fica em `timeline.Sequence` (sem Qt): `src_frame()` decide o quadro do arquivo,
`layers_at()` resolve camadas e transições, `audio_clips()` o que toca. A interface só chama os
métodos do `ui/edit_model.TimelineModel`, que grava o histórico (instantâneos JSON) e emite
`changed("structure" | "values" | "settings" | "*")`. A janela reage: `"values"` só remonta o quadro
atual; o resto recarrega a fonte da prévia. Teste novo em `tests/test_timeline.py`. Uma operação nova que
muda `start`, `src_in` ou a velocidade de um clipe precisa manter as chaves de animação no lugar
(`Clip.shift_head`/`rescale_keys`, receita *Tornar um ajuste animável*) e ganhar um teste de âncora em
`tests/test_keyframes.py`.
Operação nova que mexe na estrutura: no modelo, rode-a dentro de `with self.seq.keep_main():` para a faixa
principal magnética valer (sem ela não faz nada) e monte-a com as primitivas (`_cut`, `split`, `trim_*`,
`move`, `delete`, `_clear_range`, `open_space`); regras em `docs/ARQUITETURA.md`, seção 13.8.

### Legendas (editar, gravar, entregar, tirar tempo)

- Edição de legenda pela interface: uma função em `subedit.py` (sem Qt, no tempo do arquivo pelo `Mapping`) +
  `SubtitleController.apply` (que chama `TimelineModel.edit_subtitles`, um passo de desfazer). Números do JSON
  das legendas sempre `float`, senão o desfazer perde o refazer.
- Desenho no vídeo só por `frame.Recipe.burn` (`subtitles.Burn`): nunca componha legenda fora da receita; a
  prévia, o "Salvar quadro", a exportação e o terminal precisam dar o mesmo quadro
  (`tests/test_legendas_gravadas.py`).
- Nova forma de entregar: acrescente em `subtitles.DELIVERY`, `delivery_fields`, o rótulo de
  `export_dialog.SUBTITLE_LABELS` e o `choices` de `--legendas` do `cli.py`; campo novo do `ExportJob` só vai
  para o JSON quando usado.
- Tirar tempo da montagem (silêncios, texto ou algo novo): `TimelineModel.remove_ranges(quadros)`; os trechos em
  segundos passam por `rangecut.to_frames` (arredonda para dentro). Detalhes em `docs/ARQUITETURA.md`, seção 27.

### Novo tipo de clipe sem arquivo

Título, cor sólida, degradê, contagem regressiva, legenda… (detalhes em `docs/ARQUITETURA.md`, seção 22.5):

1. **Tipo**: use um id reservado de `timeline.SOURCE_KINDS` (`"cor"`, `"gerador"`, `"texto"`, `"legenda"`,
   `"ajuste"`) ou acrescente um no fim (nunca renomeie). Parâmetros do gerador vão em `Source.data` (chaves
   sem acento, só valores de JSON; `"nome"` é o nome mostrado). Ajustes que o usuário mexe no clipe
   (posição, escala, opacidade, cor) continuam em `editparams.py` — o gerador não os aplica.
2. **Gerador**: `sequence.RENDERERS[tipo] = fn(seq, clip, quadro_da_fonte, w, h, profundidade)` → h × w × 4
   RGBA pré-multiplicado (uint8 em 8 bits, uint16 em 16). Puro e determinístico (regra 2), sem OpenGL e sem
   widgets (roda na thread de quem lê, às vezes em duas); `QImage`/`QPainter` serve. Registre onde o recurso
   é importado; se for opcional, o recurso é um módulo (regra dos módulos), mas o gerador fica registrado
   mesmo desligado — a renderização nunca consulta `modules` e um projeto salvo sai igual.
3. **Criar e inserir**: `src = timeline.Source.virtual(tipo, seq.width, seq.height, seq.fps_str, data={…})`;
   na janela, `MainWindow.adopt_source(src)` (Mídia) e `model.insert_media(src, at=…, vtrack=…)` (ou arrastar
   da Mídia). Nada mais muda: arquivos que faltam, relocalizar, som, forma de onda e o `.plc` já ignoram a
   fonte sem arquivo, e o projeto vai para o formato 3 (recurso `"gerador"`).
4. **Teste**: como `tests/test_virtual_sources.py` — `grab` = `SequenceReader` quadro a quadro, a saída em 8 e
   16 bits e, na GPU, o clipe gerado sobre um arquivo igual na prévia e na exportação.

Os geradores e títulos do app (`docs/ARQUITETURA.md`, seção 25) mostram o resto do caminho:

- **Gerador com campos**: um `Generator` em `generators.GENERATORS` (id ASCII, `Field`s com padrão neutro) já
  ganha o item do menu **Novo** da Mídia (`ui/generators_ui.MENU_ORDER`) e os controles no inspetor
  (`GeneratorEditor`). Outro tipo (como o título) entra em `generators_ui.EXTRA_ITEMS` e tem o seu editor,
  posto com `ClipInspector.add_source_editor(widget)`.
- **Mudar o gerador** é sempre `TimelineModel.set_source_data(caminho, dados, record=False)` (desfazer;
  arrastar agrupa; faixa travada recusa); a janela atualiza nome e miniatura da Mídia sozinha.
- **Som**: `audiomix.TONES[tipo] = fn(seq, clip) -> [(quadro_da_fonte, n_quadros, Hz, dBFS)]` toca o tom nos
  quadros da sequência que mostram aquele quadro da fonte, exato à amostra, na prévia e na exportação.
- **Miniatura**: `sequence.THUMBNAIL_FRAME[tipo] = fn(src) -> quadro` (o padrão é o quadro 0).
- **Texto**: quem desenha com o `textrender` precisa da `QGuiApplication`; o terminal a cria quando
  `generators.needs_text(seq)` (acrescente o tipo novo lá).

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

Todo recurso que dá para dispensar é um módulo (regra 17). Para criar um:

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
   `p010le` 10, `rgb48le` 16). Tamanho: `output_size()` — a resolução (`"1080"`…) é o **lado menor**
   (vertical 1080 × 1920) e codecs de vídeo recebem dimensões pares; um codec que aceita tamanho ímpar
   entra na lista de exceções de lá.
6. Codificadores de hardware: `available()` já testa NVENC/QSV/AMF de verdade via
   `media.encoder_works()`; mantenha esse padrão para qualquer codificador que "aparece mas não
   funciona".
7. Teste em `tests/test_export_cmd.py` (estrutura do comando) e documente no README.
8. **Transparência**: se o formato guarda alfa, ponha o par opaco → com alfa em `export.ALPHA_PIX` (o com alfa
   entra no fim de `pix`; a janela o oferece só por "Manter a transparência"); o codificador recebe
   `rgba`/`rgba64le` quando `wants_alpha(s)`. Teste a ida e volta em `tests/test_transparency_export.py`.

### Nova plataforma de exportação

1. **`platforms.PLATFORMS`**: um `Platform(...)` no grupo certo (`GROUPS`), com **id ASCII novo** (nunca
   renomeie um id: ele fica nas preferências `export_platform` e nos scripts com `--plataforma`). Nome da
   marca como está; partes em português com `N_()`, e a `note` com `N_()`.
2. Valores da página oficial de envio da plataforma, com a URL e "conferido em AAAA-MM" num comentário logo
   acima. Sem especificação publicada: valores conservadores (H.264 + AAC em MP4, 30 quadros/s),
   `official=False` e a nota dizendo isso.
3. Quadro: `frame="1080x1920"` para formato fixo (vertical, 4:5, 1:1) ou `resolution="1080"` para manter a
   orientação do vídeo. Tamanhos pares; `upscale=True` só quando a plataforma dá mais qualidade a um envio
   maior. Limite de taxa: `maxrate` (Mb/s) com o CRF de sempre; limite de arquivo pequeno (mensageiros):
   `target_mb` (duas passadas).
4. Som: `audio` (chave de `export.AUDIO`), `loudness` (−14 redes/streaming, −16 podcast, −23 TV/festival) e
   `true_peak` (−1; −2 só se a plataforma pedir). `loudness=0` deixa o volume como está.
5. Vídeo vertical com interface por cima: uma `SafeArea` em `SAFE_AREAS` medida no modelo oficial
   (frações do quadro, y para baixo, `aspect=9 / 16`) e `safe=` na plataforma.
6. `tools/i18n_extract.py --update` e traduza em `locales/en.json` e `es.json`.
7. `tests/test_platforms.py` confere ids, tamanhos pares, limites e textos de toda a tabela; rode-o e o
   `tests/test_cli_platforms.py`. Nada no comando do codificador muda para quem não usa a plataforma.

A exportação por plataforma é núcleo, não módulo: exportar está sempre visível e a lista só preenche
opções que já existiam. Nenhuma plataforma envia arquivo (só grava no computador).

### Gravar arquivos do usuário

Nada é gravado direto no destino escolhido pela pessoa: grave num parcial ao lado e troque no fim, para
que cancelar, uma falha ou o app fechar no meio nunca deixem um arquivo quebrado com o nome final nem
apaguem o antigo antes da hora.

- Vídeo, imagem e sequência: `export.run_job()` já faz isso (`video.parcial-pelicula.mp4`, pasta
  `quadros.parcial-pelicula/`; a extensão real fica no fim para o ffmpeg escolher o mesmo formato). Não
  passe o destino final para `build_encoder_cmd()` fora desse caminho. A marca `parcial-pelicula`
  (`system.PARTIAL`) é reservada: o parcial que sobrou de uma exportação interrompida é apagado na
  próxima para o mesmo destino, e uma entrada com esse nome faz a exportação ser recusada
  (`export.partial_clash`).
- Um quadro: `export.save_still()`. Texto ou binário pequeno (LUT, preset): `with system.atomic_write(path)`.
- Teste o caminho de erro: o arquivo antigo continua igual e nenhum `*.parcial-pelicula*` sobra
  (`tests/test_export_e2e.py`, `tests/test_misc.py`).

### Adicionar um perfil de entrada (câmera)

`shaders.py` (`toLinear` e `lutEncode` com um novo id), `look.INPUT_IDS` (id novo depois do maior; nunca
renumere), `look.INPUT_GAMUT` (e `_PRIMARIES` se o gamut for novo), **`look.INPUT_DOMAIN`**, `params.ENTRADAS`
(no fim da lista) e, se servir para LUTs, `params.LUT_ENTRADAS` e `luts.guess_input()`. No plugin do Resolve:
a curva em `resolve.K_DECODE` (`pc_to_linear`), depois `python tools/gerar_ofx.py`. Pontos de referência do
fabricante em `tests/test_entrada.py`. Documente em `docs/EFEITOS.md` e no README.

O resto acompanha sozinho: o cartão "Câmera" dos clipes (`editparams` `camera_entrada` usa `params.ENTRADAS`),
os limites de "Proteger cores saturadas" (`look.gamut_limits` pelo gamut; no plugin, a tabela `PC_GCL`) e a
sugestão pelos metadados (`media.suggest_input` reconhece os nomes por `luts.guess_input`; acrescente lá o nome
da curva e um caso em `tests/test_entrada_sugestao.py`). Se a curva é log de câmera, a leitura em float com os
super-brancos vale para ela (`media.float_input`: todo perfil fora de `media.DISPLAY_PROFILES`).

**Toda curva declara o seu domínio** em `look.INPUT_DOMAIN`, com a fonte (documento do fabricante) num
comentário:

- `"cv"`: a fórmula usa o código de 10 bits normalizado, CV = código/1023, gravado pela câmera como está mesmo
  no arquivo marcado como faixa legal (Sony S-Log3, Panasonic V-Log, Nikon N-Log: o cinza 18% do S-Log3 é o
  código 420);
- `"sinal"`: a fórmula usa o próprio sinal de vídeo E′ (0 = preto, 1 = branco nominal), que a câmera grava com
  a quantização padrão (faixa legal 64 + 876·E′); o valor expandido pelo decodificador já é E′ (ARRI LogC3/LogC4,
  Blackmagic Gen 5, DaVinci Intermediate, RED Log3G10, Cineon, Apple Log, HLG, PQ, Rec.709, linear).

Como a faixa do arquivo chega à cor (nunca leia o código direto no shader sem passar por aqui):

- `media.legal_range(info)`: o `FrameReader` expandiu a faixa legal (vídeo YUV comum: v = (código − 64)/876)?
  Imagens RGB e vídeo de faixa cheia: não (v = código/1023).
- `look.build_plan(..., legal=...)` → `u_legal`; `u_input_cv` vem de `INPUT_DOMAIN` (e do ajuste
  `log_reescalado`, para log que a câmera já mandou reescalado pela saída HDMI "Limited"). O shader volta ao
  código, CV = (v·876 + 64)/1023, só quando os dois são 1 (`toLinear(..., cv)`).
- Quem chama passa a faixa da fonte: prévia, miniaturas, curva, "Salvar quadro" e exportação de arquivo
  (`media.legal_range`), montagem do modo Edição (`sequence.legal_range`: a faixa da maioria dos clipes de
  vídeo), terminal (`quadro`, `exportar`).
- LUTs ficam no domínio da própria curva (código de 10 bits nas curvas `"cv"`, a convenção dos LUTs "Full" dos
  fabricantes e das IDTs do ACES): o LUT externo (`lutEncode`) e os `.cube` exportados (`Engine.bake_lut`,
  padrão `legal=False`). O plugin do Resolve recebe o valor que o Resolve tem do clipe: controle *Faixa do
  vídeo* (padrão *Vídeo*, clipe em Data Levels Auto/Video = `bake_lut(legal=True)`; *Cheia* = `legal=False`).
- HLG e PQ são `"sinal"` (BT.2100). Presets não mudam o perfil nem `log_reescalado` (`presets.SOURCE_KEYS`);
  ao abrir um arquivo, `media.auto_profile` escolhe HLG/PQ pelos metadados (`color_transfer`), volta para
  Rec.709 num arquivo sem HDR e nunca troca um perfil log.

### Adicionar uma bitola

`look.GAUGES` (multiplicadores e proporção), `look.GAUGE_SCAN` (qual geometria de scan usar),
`params.BITOLAS`; se tiver geometria própria de scan, `look.SCAN_FORMATS` e a escolha em
`scan_formato`. Documente a tabela de bitolas. Se o grão deve seguir uma largura de quadro que não é a
largura da imagem no scan, `grao.FRAME_W_MM_EXTRA`. A bitola nova entra sozinha nas tabelas do plugin
(`resolve._gauge_tables`): regrave a chave `plugin` de `tests/data/cor_base.json` e rode `tests/test_resolve.py`.
Tira deitada no scan (foto): `scanformatos.ROTATED`.

### Mexer no ffmpeg / dependências

- Procura: `media.configure()` (pasta escolhida → `deps.ffmpeg_dir()` → `PATH` → pastas comuns).
  Depois de trocar o ffmpeg chame `media.configure()` (que limpa o cache de codificadores).
- Transparência: não troque os filtros de `media._alpha_graph` sem rodar `tests/test_alpha.py`. O swscale
  converte yuva420p de 8 bits errado para formatos com alfa (cores trocadas no VP9 com alfa); por isso a cor
  vai por `rgb24` e o alfa à parte (`alphaextract`/`alphamerge`). O VP8/VP9 com alfa precisa do `libvpx` antes
  do `-i` (`alpha_decoder`).
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
   usuário antes de baixar. Modelos de terceiros que o componente baixa vão em `Tool.licenses`
   (o quê, licença, link `https`).
   **Exceção aprovada (27/10/2026): o CorridorKey** (Corridor Key Licence, CC BY-NC-SA 4.0 com termos
   adicionais que permitem uso comercial). Ele é baixado **à parte, das fontes oficiais** (GitHub da
   Corridor e Hugging Face, commits e revisões fixos), **direto no computador do usuário** — nunca
   redistribuído nem espelhado (nada no repositório, no pacote ou numa release do projeto); o app
   continua gratuito e MIT; o que o usuário recorta é dele; o cartão e a janela mostram o nome
   "CorridorKey", os créditos da Corridor Digital e a regra das empresas acima de US$ 20 milhões. Outra
   exceção precisa de decisão do dono do projeto.
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

Componente compilado no CI (sem binário oficial verificável): veja a receita seguinte.

### Componente compilado no CI (publicar ou atualizar)

Exemplo: o whisper.cpp (`.github/workflows/componentes.yml`, `tools.WHISPER_CPP`). Só o dono do projeto
autoriza publicar; a release é do próprio repositório e nunca é a "latest".

1. **Workflow**: um job por componente em `componentes.yml`, com a versão **e o commit** da fonte
   oficial como entradas (o job confere que a tag aponta para o commit), dependências de compilação
   baixadas com SHA-256 conferido, opções que não dependem da máquina do CI (nada de `-march=native`;
   runtime estático no Windows; `RPATH=$ORIGIN` e a glibc mais antiga suportada no Linux), um teste que
   roda o programa compilado, e o pacote com a licença do autor e um `ORIGEM.txt` (versão, commit,
   opções). Mudar o workflow num push compila tudo sem publicar: use isso para testar.
2. **Publicar**: `gh workflow run componentes.yml --ref <branch> -f componente=<nome> -f versao=<x.y.z>
   -f commit=<sha completo> -f publicar=true`. O job `publicar` gera o `SHA256SUMS.txt` e cria a release
   `componente-<nome>-<versão>` como **pre-release** e **não latest** (`--latest=false`). A tag **não**
   começa com `v`: o `build.yml` só reage a `v*` e o atualizador (`releases/latest`) nunca vê
   pre-releases. Release que já existe não é sobrescrita: versão nova = tag nova (para refazer a mesma
   versão, apague a release e a tag de propósito).
3. **Conferir**: `gh release download componente-<nome>-<versão>` numa pasta vazia, `sha256sum -c
   SHA256SUMS.txt`, e `gh api repos/edvitor13/pelicula-converter/releases/tags/componente-<nome>-<versão>`
   deve mostrar `"prerelease": true`. Rode o pacote no Windows e no Linux (com e sem placa de vídeo).
4. **Fixar no app**: em `tools.TOOLS`, um `Artifact(..., origin=tools.CI)` por sistema com a URL
   `https://github.com/edvitor13/pelicula-converter/releases/download/componente-<nome>-<versão>/<pacote>`,
   o SHA-256 e o tamanho **do arquivo baixado** (não do log do CI), o tamanho extraído e os executáveis;
   o `Tool` leva `source_url` (a árvore da tag oficial) e a licença do autor. `test_registry_is_consistent`
   exige o `source_url` e a URL nesta release.
5. Atualizar a versão = repetir 2–4 com a versão nova (a antiga continua publicada para quem ainda não
   atualizou o app) e mencionar no `CHANGELOG.md`.

Programa do sistema (instalado pelo usuário, como o DaVinci Resolve): `kind=tools.SISTEMA`, sem
`artifacts`, e uma função em `tools.DETECTORS` que só lê (pastas padrão, lista de desinstalação do
Windows) — o app não instala nem baixa nada. O ffmpeg (`backend="ffmpeg"`) é a exceção documentada
ao modelo de versão fixa: não copie o fluxo dele para ferramentas novas.

### Novo ambiente Python (uv)

Para ferramentas de IA em Python (PyTorch, CUDA, modelos), use uma **receita** em vez de um `Artifact`
(`Tool(backend="receita", recipe=tools.Recipe(...))`; exemplo completo: `tools.CORRIDORKEY_RECIPE`;
detalhes em `docs/ARQUITETURA.md`, seção 21):

1. **Lista travada com hash** em `pelicula/data/<id>/`: escreva `requirements.in` (versões exatas onde
   importa) e gere, para cada sistema, com o uv fixado (`tools.UV_VERSION`):
   `uv pip compile requirements.in --generate-hashes --torch-backend cu128 --python-version 3.12
   --python-platform x86_64-pc-windows-msvc|x86_64-manylinux_2_28 --system-certs --no-header -o
   requirements-<sistema>.txt` e ponha o comando no topo do arquivo. Só wheels (`--only-binary :all:` na
   instalação), nada de `git+` nem `http://`.
2. **`PythonEnv`**: versão exata do Python (uma que o uv fixado ofereça), índice do PyTorch (`cu128`,
   outro CUDA ou `cpu`), as listas por sistema e o tamanho baixado (`size`, para o progresso).
3. **Código**: zip do commit em `codeload.github.com` (`SourceZip`) + manifesto de
   `tools/gerar_manifesto.py <repo> <commit> pelicula/data/<id>/codigo-<commit>.sha256 --pular "*.bat"`
   (confere cada arquivo contra o blob do git). Pacote Python sem wheel: `SourceZip(package=True)`.
4. **Modelos**: `Piece(url com revisão fixa, sha256, tamanho, destino)` — o SHA-256 do LFS publicado pelo
   Hugging Face (ou conferido com o hash publicado pelo autor), nunca lido na hora do download.
5. **Teste da receita** (`check` + `check_env`): um script deles que carrega o modelo **sem rede**; ele
   roda antes de a instalação valer e no botão Testar.
6. **Requisitos** que não dependem de espaço (placa, sistema): uma função em `tools.REQUIREMENTS[id]`
   que devolve os motivos (PT-BR); o cartão os mostra no lugar do download.
7. **Rodar**: sempre `tools.run_process([python, script, ...], cwd=..., env=tools.runtime_environ(...),
   cancel=job.cancel_event, on_line=...)` num trabalho da fila (GPU) — nunca importe torch no app.
   Arquivos do usuário: pasta parcial e troca no fim ("Gravar arquivos do usuário"). Teste caminhos
   com acentos: no Windows o `cv2.imread` não abre (veja `corridorkey._ascii_copy`).
8. **Tamanhos** (`download_size`, `disk_size`, `env.size`): meça numa instalação de verdade.
9. **Testes** com o uv falso (`tests/uv_falso.py`) e uma receita falsa (`test_ambiente.fake_recipe`);
   um teste manual de ponta a ponta atrás de uma variável de ambiente (como `test_corridorkey_real.py`).

Pastas: `ferramentas/<id>/python` (Python base, fora da pasta trocada: o venv `--relocatable` aponta para
ele), `ferramentas/<id>/<versão>/venv` e `ferramentas/<id>/cache` (downloads retomáveis; a limpeza de
12 h não mexe; apagado depois da instalação).

### Trabalho em segundo plano (fila de tarefas)

Tudo que demora (downloads, análises, IA) vai para `jobs.py` pela ponte do Qt:
`bridge().submit(fn, título, kind=jobs.CPU|GPU|REDE, key="...", on_finished=f)`. A função recebe o job,
chama `job.report(etapa, feito, total)` e `job.check_cancel()` e devolve o resultado (`job.result`);
`f(job)` roda na thread principal (é ali que se mexe em widgets, preferências ou no projeto). A
interface acompanha pelos sinais `changed`/`finished` de `bridge()`, filtrando por `job.key`. Detalhes
em `docs/ARQUITETURA.md` (seção 18).

### Nova notificação

1. **`notify.py`**: um `Kind("id_sem_acento", N_("Rótulo"), N_("Quando avisa."))` em `KINDS` (o id vira
   `notificacoes/<id>` nas preferências: nunca renomeie) e uma função que monta o `Notice` (título, texto
   e o destino do clique: `target` = arquivo ou pasta, ou `action` = um `ACTION_*`). Destino novo na
   janela = uma constante `ACTION_*` e a entrada em `ui/notifier.for_window()`.
2. **Onde o evento é visto**, na thread principal: `window.notifier.notify(notify.meu_aviso(...))` — na
   `MainWindow`, num `on_finished` da fila de tarefas ou num ouvinte como `Notifier.watch_jobs`. Nunca
   chame o backend direto: `notify()` aplica o módulo, o tipo, o foco, o som e o piscar.
3. A página Configurações › Notificações mostra o tipo sozinha. Textos com `_()`/`N_()` +
   `tools/i18n_extract.py --update` + en/es; teste o texto e o destino em `tests/test_notify.py` e o
   gancho num caso de `tests/notify_ui_cases.py` (backend falso: nada aparece na tela).

### Recuperação automática

Tudo o que entra no `.plc` (`project.Project`) já entra na cópia automática. Estado da tela que vale a
pena voltar depois de um travamento e não vai no projeto entra em `recovery_ui.ui_state()` e
`restore_ui_state()`. As cópias ficam só em `recovery.recovery_dir()` (nunca no `.plc` da pessoa) e os
relatórios em `crashlog.logs_dir()`; nos testes, `LOCALAPPDATA`/`XDG_DATA_HOME` temporários. Um
`ExportJob` com campo novo que importa para refazer a exportação precisa dele em `to_dict()`/`from_dict()`.
Detalhes em `docs/ARQUITETURA.md` (seção 20).

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
- `componentes.yml`: compila componentes externos a partir do código oficial (hoje o whisper.cpp) e,
  quando pedido à mão com `publicar=true`, publica a pre-release `componente-<nome>-<versão>` (receita
  "Componente compilado no CI").
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

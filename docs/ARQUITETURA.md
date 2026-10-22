# Arquitetura do PeliculaConverter

Mergulho técnico no funcionamento interno: camadas, pipeline de GPU, gestão de cor, threads,
comunicação com o ffmpeg, exportação e persistência. Para regras de contribuição e receitas
rápidas, veja [AGENTS.md](../AGENTS.md); para o significado de cada ajuste, [EFEITOS.md](EFEITOS.md).

## Sumário

1. [Visão geral](#1-visão-geral)
2. [Mapa dos módulos](#2-mapa-dos-módulos)
3. [Dos ajustes aos uniforms](#3-dos-ajustes-aos-uniforms)
4. [Pipeline de GPU](#4-pipeline-de-gpu)
5. [Gestão de cor](#5-gestão-de-cor)
6. [Determinismo e independência de resolução](#6-determinismo-e-independência-de-resolução)
7. [Threads e processos](#7-threads-e-processos)
8. [Leitura de quadros com o ffmpeg](#8-leitura-de-quadros-com-o-ffmpeg)
9. [Exportação](#9-exportação)
10. [Dependências externas (deps.py)](#10-dependências-externas-depspy)
11. [Persistência e arquivos](#11-persistência-e-arquivos)
12. [Testes](#12-testes)
13. [Modo Edição](#13-modo-edição)
14. [Laboratório: emulação por densidade](#14-laboratório-emulação-por-densidade)
15. [Plugin do DaVinci Resolve (`resolve.py`)](#15-plugin-do-davinci-resolve-resolvepy)
16. [Módulos (recursos opcionais)](#16-módulos-recursos-opcionais)
17. [Componentes externos (`tools.py`)](#17-componentes-externos-toolspy)
18. [Fila de tarefas (`jobs.py`)](#18-fila-de-tarefas-jobspy)

---

## 1. Visão geral

```mermaid
flowchart TB
    subgraph UI["Interface (PySide6) — thread principal"]
        MW["MainWindow<br/>ui/main_window.py"]
        ST["ParamStore<br/>ui/store.py"]
        WG["SectionCard / sliders<br/>ui/widgets.py"]
        VW["Viewer · Looks · Histograma"]
        ED["ExportDialog · QueueDialog · Configurações"]
    end
    subgraph CORE["Núcleo (sem Qt de interface)"]
        PR["params.py<br/>esquema"]
        LK["look.py<br/>build_plan()"]
        EN["engine.py<br/>Engine (moderngl)"]
        SH["shaders.py<br/>GLSL 330"]
        PS["presets.py · luts.py"]
        MD["media.py<br/>ffprobe / FrameReader"]
        EX["export.py<br/>ExportQueue / run_job"]
        DP["deps.py · tools.py · jobs.py · system.py"]
    end
    FF[("ffmpeg / ffprobe")]
    GPU[("GPU — OpenGL 3.3")]

    PR --> WG
    WG --> ST
    ST --> MW
    MW --> LK
    LK --> EN
    EN --> SH
    EN --> GPU
    MW --> MD
    MD --> FF
    ED --> EX
    EX --> LK
    EX --> EN
    EX --> MD
    PS --> ST
    DP --> FF
```

Três ideias guiam o projeto:

1. **Um único caminho de renderização.** Prévia, miniaturas, "Salvar quadro", estimativa de tempo
   e exportação chamam as mesmas funções: `look.build_plan(values, w, h, frame, fps, lut_info,
   dither)` e `Engine.render(plan, depth)`.
2. **Esquema declarativo.** `params.SECTIONS` descreve todos os ajustes (tipo, faixa, padrão,
   rótulo, dica). A interface é gerada a partir dele e o motor lê os valores pelas chaves.
3. **O núcleo não depende da interface.** `look`, `engine`, `media`, `export`, `presets`, `luts`,
   `deps`, `tools` e `jobs` funcionam sem janela (são usados assim pelos testes). A exceção é `edgetext`, que usa
   `QPainter` sobre `QImage` e precisa de uma `QGuiApplication` existente (sem ela, o texto de
   borda simplesmente não é desenhado).

## 2. Mapa dos módulos

| Módulo | Responsabilidade |
|---|---|
| `PeliculaConverter.pyw` | Abre o app sem console (`pythonw`). |
| `pelicula/__main__.py` | `python -m pelicula`. |
| `pelicula/__init__.py` | `__version__` e `APP_NAME`. |
| `pelicula/app.py` | `main()`: `QApplication`, estilo Fusion, paleta e folha de estilo, ícone; bloqueio do macOS (desativado); oferta de `pip install` se faltar `moderngl`/`numpy`/`glcontext`; cria a `MainWindow`; arquivos da linha de comando; gancho `PELICULA_SCREENSHOT`. |
| `pelicula/params.py` | `Param`, `Section`, `Schema` (esquema genérico: padrões e limpeza), `SECTIONS`/`FILM`, `PARAMS`, `defaults()`, `sanitize()`. |
| `pelicula/look.py` | Tabelas de bitolas (`GAUGES`), cópias (`PRINTS`), scan (`SCAN_FORMATS`), filtros P&B, viragens, primárias e matrizes de gamut; Laboratório (negativos, cópias, processos, calibração `lab_paths`); `build_plan()` → `Plan`. |
| `pelicula/shaders.py` | GLSL: `VERT`, `COMMON` (curvas, transferências log, look, cópia, LUT), `BASE`, `EXTRACT`, `BLUR`, `NOISE`, `FINAL`, `BAKE`. |
| `pelicula/engine.py` | `Engine`: contexto moderngl, programas, alvos de render, textura de entrada, LUT 3D, texto da borda; `render()` e `bake_lut()`; cache de LUTs por `mtime`. |
| `pelicula/presets.py` | `FILM_BASE`, `BUILTIN` (44 presets), presets do usuário (JSON), importar/exportar. |
| `pelicula/luts.py` | Ler/gravar `.cube`, palpite do espaço de entrada, LUTs instalados (Premiere, Resolve, Meus LUTs), instalar LUTs. |
| `pelicula/media.py` | Localizar ffmpeg/ffprobe, `probe()` → `MediaInfo`, `NamedPipe` (Windows), `FrameReader`, `grab_frame()`, `Perf`, detecção de codificadores e hwaccels. |
| `pelicula/export.py` | `CODECS`, qualidades prontas, `ExportSettings`, `build_encoder_cmd()`, `ExportJob`, `ExportQueue`, `run_job()`, `measure_speed()`. |
| `pelicula/deps.py` | Versão do ffmpeg, download verificado (gyan.dev / BtbN), extração segura (`extract_archive`, `safe_member`), pasta do app, pacotes Python, `pip_install()`. |
| `pelicula/tools.py` | Componentes externos: registro `TOOLS` (versão, URL e SHA-256 fixos), `download()` com troca atômica, `remove()`, `status()`, `disk_usage()`, detecção de programas do sistema (seção 17). |
| `pelicula/jobs.py` | Fila de tarefas em segundo plano: `Job`, `JobQueue` (limite por tipo, GPU 1 por vez), `shared()` (seção 18). |
| `pelicula/system.py` | Processador, núcleos, RAM, GPUs NVIDIA (`nvidia-smi`), abrir pasta/arquivo no sistema. |
| `pelicula/edgetext.py` | Máscara do texto impresso na borda da película. |
| `pelicula/testimage.py` | Cena de teste (cartela de 24 cores, janela clara, lâmpadas, faixa de matiz, rampa de cinza). |
| `pelicula/timeline.py` | Modo Edição: `Source`, `Clip`, `Track`, `Layer`, `Sequence` (montagem, tempo, transições, JSON) e `History` (desfazer). Sem Qt. |
| `pelicula/editparams.py` | Esquemas dos ajustes por clipe (`VIDEO`, `AUDIO`), cores do HSL, ajustes rápidos. |
| `pelicula/compositor.py` | Ajustes do clipe → uniforms do `CLIP` (`clip_uniforms`), enquadramento (`fit_box`, `transform`), `auto_adjust`. |
| `pelicula/editshaders.py` | GLSL do modo Edição: `CLIP` (uma camada sobre a tela) e `OUT` (tela → 8/16 bits inteiros). |
| `pelicula/resolve.py` | Plugin do DaVinci Resolve: gera os DCTLs (Cor, Textura, Projetor e os de cada preset), os LUTs e o `LEIA-ME`; instala na pasta de LUTs do Resolve. |
| `pelicula/modules.py` | Módulos (recursos que o usuário liga e desliga): `MODULES`, `GROUPS`, `PROFILES`, `is_enabled()`, `apply_profile()`, `current_profile()`, `used_by()`. Sem Qt (veja a seção 16). |
| `pelicula/ui/settings_dialog.py` / `ui/pages/` | Janela de Configurações: páginas numa barra lateral (`Page(dialog)` por arquivo); `pages/recursos.py` liga e desliga os módulos. |
| `pelicula/ui/profile_dialog.py` / `module_notice.py` | Perfil de recursos do primeiro acesso (`ProfileDialog`, cartões `ProfileCard`); faixa de aviso "recursos desligados em uso" (`ModuleNotice`). |
| `pelicula/ui/edit_model.py` | `TimelineModel`: a sequência da edição, seleção, histórico e as edições que a interface pede (sinal `changed`). |
| `pelicula/ui/timeline_view.py` | `TimelineEditor`: barra de ferramentas, régua, cabeçalhos das faixas, clipes, forma de onda, arrastar/aparar/lâmina/ímã. |
| `pelicula/ui/edit_panels.py` | `MediaBin` (Mídia) e `ClipInspector` (ajustes do clipe gerados de `editparams`). |
| `pelicula/ui/scopes.py` | Medidores: histograma, forma de onda, parada RGB e vetorscópio. |
| `pelicula/ui/sequence_dialog.py` / `resolve_dialog.py` | Resolução e fps da sequência; instalação do plugin do DaVinci. |
| `pelicula/sequence.py` | Quadros da sequência: `grab` (acesso direto), `SequenceReader` (em ordem, com pré-abertura), `media_info`. |
| `pelicula/audiomix.py` | Mixagem do som da sequência com o ffmpeg (`render_mix`), chave da prévia (`mix_key`), forma de onda (`peaks`). |
| `pelicula/ui/main_window.py` | Janela principal, carregamento de quadros, reprodução, presets, LUTs, exportação, atalhos, checagem de dependências. |
| `pelicula/ui/store.py` | `ParamStore`: valores atuais, sinal `changed`, desfazer/refazer (agrupado por 400 ms, até 300 passos). |
| `pelicula/ui/widgets.py` | `FilmSlider`, `ToggleSwitch`, linhas de parâmetro, `LutRow`, `SectionCard`, `Segmented`, `Histogram`, `Timeline`, `timecode()`. |
| `pelicula/ui/viewer.py` | Visualizador: modos de comparação, zoom livre (10%–1600%) e pan, espiar o original, modo de tela cheia (sem borda, fundo preto, dica das teclas), arrastar e soltar. |
| `pelicula/ui/looks.py` | Painel de miniaturas dos presets com busca. |
| `pelicula/ui/export_dialog.py` | Janela de exportação, desempenho e estimativa. |
| `pelicula/ui/queue_dialog.py` | Janela da fila. |
| `pelicula/ui/settings_dialog.py` / `pages/` | Configurações em páginas; `pages/componentes.py` mostra os componentes (ffmpeg, ferramentas, programas do sistema), o espaço em disco e o sistema (placa de vídeo, bibliotecas). |
| `pelicula/ui/job_bridge.py` | `JobBridge`/`bridge()`: eventos da fila de tarefas como sinais do Qt na thread principal; `on_finished`. |
| `pelicula/ui/theme.py` / `icons.py` | Cores, fontes, folha de estilo; ícones vetoriais e ícone do app (usa `assets/logo-*.png` quando existem). |

## 3. Dos ajustes aos uniforms

```
params.SECTIONS ──► interface (SectionCard) ──► ParamStore.values (dict)
                                                     │
                     presets.builtin_values() ───────┤  (FILM_BASE + valores do preset, sanitize)
                                                     ▼
          look.build_plan(values, largura, altura, quadro, fps, lut_info, dither)
                                                     │
                                                     ▼
   Plan(uniforms, soft_sigma, chains[hal/bloom/mist], grain_size, grain_seed, lut_path, edge_text)
                                                     │
                                                     ▼
                                   Engine.render(plan, depth=8|16)
```

`build_plan()` é uma função pura: dado o mesmo dicionário de valores, o mesmo tamanho e o mesmo
número de quadro, devolve exatamente os mesmos uniforms. Ela:

- converte px@1080 para pixels reais (`scale = altura / 1080`);
- aplica os multiplicadores da bitola (`GAUGES`) e do ISO (`(ISO/250)^0,35` na força,
  `(ISO/250)^0,18` no tamanho do grão);
- soma exposição, temperatura, tonalidade, cintilação, clarões e cor instável num ganho em EV por
  canal (`u_gain`);
- calcula o tremor (`u_shift`, `u_rot`, `u_zoom`) e os eventos de defeitos com `_hash()`/`_vnoise()`
  sobre o número do quadro e as sementes;
- monta as **cadeias de brilho** (`Chain`): halação (só luminância, limiar `0,18·2^limiar`, raio ×
  fator da bitola, máscara alfa quando há scan), bloom (colorido) e névoa (sem limiar);
- decide maciez/nitidez (`soft_sigma` = √(maciez_bitola² + (raio·maciez·2)²)·scale);
- calcula o tamanho do grão em pixels (mínimo 1 px) e a semente (`semente·7919 + quadro` se
  animado);
- converte as tabelas de cópia, filtros P&B, viragens e a cor da base do scan;
- com LUT ligado e `lut_info` válido, preenche tamanho, domínio e a matriz de gamut inversa do
  espaço que o LUT espera;
- com scan ligado, escolhe o formato (`SCAN_FORMATS`), a janela de visão em mm e o texto da borda.

## 4. Pipeline de GPU

Todos os passos desenham um quadrilátero de tela cheia (`VERT`) num *framebuffer*. Alvos usados
(criados sob demanda e reaproveitados enquanto o tamanho não muda):

| Alvo | Formato | Tamanho | Conteúdo |
|---|---|---|---|
| `input_tex` | RGB `f1` (8 bits) ou `nu2` (16 bits normalizado) | quadro | Quadro vindo do ffmpeg |
| `lin` | RGBA `f2` (half float) | quadro | Luz linear após o passo base; alfa = máscara da imagem no scan |
| `tmp`, `soft` | RGBA `f2` | quadro | Desfoque separável da maciez |
| `hi` | RGBA `f2` com mipmaps | quadro | Luzes extraídas para uma cadeia de brilho |
| `<cadeia>_a`, `<cadeia>_b` | RGBA `f2` | reduzido (`w >> nível`) | Desfoque horizontal e vertical de halação, bloom e névoa |
| `noise` | RGBA `f2` | `w / tamanho_do_grão` | Quatro canais de ruído gaussiano |
| `out8` / `out16` | RGB `f1` / `nu2` | quadro | Resultado lido de volta para a CPU |
| `bake` | RGB `f4` | `n² × n` | Grade de um LUT sendo exportado |

### 4.1 Passo base (`BASE`)

1. **Tremor**: `weave()` aplica zoom, rotação e deslocamento em pixels.
2. **Lente**: `lens()` aplica a distorção radial normalizada (o canto continua no canto) e, com
   aberração cromática, amostra R, G e B com escalas `1 + ca`, `1` e `1 − ca`.
3. **Entrada**: `toLinear(código, perfil)` desfaz a curva (Rec.709 neutra, N-Log, S-Log3, LogC3,
   V-Log, Cineon, DaVinci Intermediate, Log3G10) e `u_gamut` converte o gamut para Rec.709.
4. **Exposição e balanço**: `× exp2(u_gain)` por canal.
5. **Vinheta** (bitola + lente) em EV.
6. **Scan** (se ligado): converte o pixel para milímetros na tira (`u_scan_view`), calcula em qual
   quadro (`k`) ele cai, a distância com sinal ao retângulo arredondado do quadro (com rugosidade
   `fbm2`), os furos (retângulos arredondados periódicos), a densidade da base, o texto da borda
   (textura `t_text`) e a área fora da película. O vídeo é encaixado no quadro (caber/preencher) e
   os vizinhos mostram o mesmo quadro (como num scan estático). Alfa = dentro da imagem.

### 4.2 Maciez (`BLUR` × 2)

Gaussiana separável em resolução cheia com `soft_sigma`. O passo final usa `lin + (lin − soft) ×
nitidez` sobre a mistura escolhida, o que implementa ao mesmo tempo a maciez e a "recuperação de
detalhe" (máscara de nitidez).

### 4.3 Halação, bloom e névoa (`EXTRACT` + mipmaps + `BLUR`)

Para cada cadeia:

1. `EXTRACT` separa as luzes com joelho suave (`smoothstep(0,5·limiar, 1,5·limiar, L)`), limita a
   energia (`e / (1 + e/limite)`, evita que um pixel de 50× domine), multiplica pelo alfa do scan
   quando pedido e, na halação, reduz a luminância.
2. `build_mipmaps()` gera as reduções.
3. Escolhe-se o nível `n` tal que `σ / 2ⁿ ≤ 6` (até 8 níveis); o desfoque horizontal lê o mipmap
   nesse nível com `textureLod` e grava num alvo reduzido; o vertical completa. Raios de 250 px
   em 4K custam o mesmo que raios pequenos. O núcleo tem raio `3σ`, limitado a 48 amostras.

### 4.4 Ruído do grão (`NOISE`)

Uma textura com `⌈w / tamanho⌉ × ⌈h / tamanho⌉` texels recebe quatro números gaussianos
independentes por texel (Box–Muller sobre o hash PCG de `(x, y, semente)`). O passo final amostra
essa textura com **interpolação bicúbica** em duas escalas (fina e ~2,3× maior, misturadas pela
aspereza), mistura um canal comum (monocromático) com três independentes (grão colorido) e aplica a
resposta por luminância (gaussianas em L = 0,10 / 0,45 / 0,88).

### 4.5 Passo final (`FINAL`)

Em ordem:

1. `lin` → maciez/nitidez (`t_soft`).
2. Névoa: `mix(lin, névoa, 0,3·força) + névoa·0,35·força`.
3. Bloom (`+ bloom·força·0,22`), halação (`+ halo·cor·força·0,32`) e vazamento de luz (duas
   gaussianas coloridas que passeiam pelas bordas).
4. `colorPipe(lin)`:
   - **Laboratório** (se ligado): `lin` passa por `labPipe` (negativo → copiadora → cópia, seção 14)
     e volta para luz linear pela curva neutra inversa; daí em diante o resto do caminho vale igual;
   - **neutro** = curva neutra de exibição;
   - **LUT no lugar do look** → `mix(neutro, LUT(codificado no espaço do LUT), força)`;
   - senão **filmLook** (P&B com pesos do filtro → stops → saturação em log → contraste e
     deslocamento por canal → curva por canal com ombro/pé suaves → densidade → matiz de verdes,
     azuis e pele → tons de sombra/luz com pivô → viragem), misturado por *Intensidade do look*;
   - **printStage**: volta de exibição para stops (curva neutra inversa), saturação, gama e
     deslocamento por canal e curva da cópia; misturado por *Força da cópia*;
   - **envelhecimento**: dessatura 40%, levanta o preto (`×0,82 + 0,075`) e puxa para o magenta;
   - **LUT depois do look**: reencoda para o espaço que o LUT espera (Rec.709 usa o valor de
     exibição direto) e mistura.
5. Grão (no valor de exibição, como numa cópia).
6. Defeitos (`damage()`), em coordenadas px@1080: manchas, fio de cabelo (curva amostrada em 40
   segmentos), marca de troca de rolo, emenda, poeira (células de 90 px, 3×3 vizinhas, partículas
   elípticas) e riscos (até 6).
7. **Força geral**: `mix(código_original, resultado, u_mix)`.
8. **Moldura**: distância com sinal a um retângulo arredondado na proporção pedida, com borda suave
   e irregular, cor das barras (desligada quando o scan está ligado).
9. **Pontilhado**: ruído triangular de ±1 LSB em 8 bits (só quando `dither=True`).
10. `clamp(0, 1)` e gravação em `out8`/`out16`, lido com `fbo.read()`.

### 4.6 Exportar LUT (`BAKE`)

`Engine.bake_lut(values, n)` desenha uma grade `n² × n` (R varia mais rápido, depois G, depois B —
a ordem do `.cube`) e roda só `toLinear → gamut → ganho → colorPipe`, com o projetor desligado e sem
pontilhado. O resultado vai para `luts.save_cube()` (domínio 0–1, valores limitados a 0–1).

### 4.7 Coordenadas

Os shaders usam **coordenadas de imagem com y para baixo**: a linha 0 do array numpy (topo da
imagem) é enviada como linha 0 da textura e lida de volta como linha 0 do framebuffer. Como nada é
invertido no caminho, `v_uv.y = 0` é o topo. Toda geometria escrita à mão (tremor, scan, defeitos,
vazamento, marca de rolo no canto superior direito) segue essa convenção.

## 5. Gestão de cor

- **Espaço de trabalho**: luz linear de cena com primárias Rec.709/D65; cinza médio = 0,18.
- **Gamut**: matrizes calculadas em `look.py` a partir das primárias xy (Rec.709, Rec.2020,
  S-Gamut3.Cine, ARRI Wide Gamut 3, V-Gamut, DaVinci Wide Gamut, REDWideGamutRGB), todas com
  branco D65; enviadas como `mat3` coluna-maior (`mat3_uniform`).
- **Curvas de câmera** em GLSL: N-Log, S-Log3, LogC3 (EI 800), V-Log, Cineon (685/300 com preto
  offset), DaVinci Intermediate e Log3G10 — decodificação e codificação (a codificação serve para
  alimentar LUTs que esperam log).
- **Curva neutra de exibição** (`D_SLOPE = 0,155` por stop, `D_MID = 0,45`, `D_P = 4`): uma
  sigmoide de *soft clip* em stops, **inversível**. Ela é usada para levar Rec.709 até a luz linear
  e de volta, então com todos os efeitos desligados o vídeo sai igual ao que entrou (a menos do
  pontilhado). `look.display_to_lin()` é a mesma inversa em Python (usada para a cor da base do
  scan).
- **Curva da película** (`curve()`): mesma família, com inclinação = `D_SLOPE × contraste`, tom
  médio, preto, branco e expoentes de ombro (`ps`) e pé (`pt`) controlados pela suavidade
  (`4 → 1,15`).
- **Saída**: valores de exibição BT.709. O codificador recebe RGB e o ffmpeg converte para YUV com
  matriz BT.709 em faixa limitada (BT.601 em faixa cheia para JPEG/WebP), gravando as tags
  `bt709` de primárias, transferência e matriz.

## 6. Determinismo e independência de resolução

- **Nada aleatório de verdade.** Em Python, `_hash(i, semente)` (hash inteiro de 32 bits) e
  `_vnoise(x, semente)` (ruído de valor suave) geram tremor, cintilação, clarões, emendas, fio de
  cabelo, manchas, cor instável e vazamento a partir de `t = quadro / fps`, do índice do quadro e
  das sementes. Em GLSL, `pcg()`/`rnd(uvec3)` geram grão, poeira, riscos e pontilhado a partir de
  coordenadas inteiras, quadro e semente.
- **Mesmo quadro, mesmo resultado.** A prévia chama `build_plan(..., self.frame_idx, info.fps)`; a
  exportação chama `build_plan(..., first_index + i, fps_saída)`. Com a mesma resolução, o
  resultado é idêntico — uma exportação FFV1 16 bits foi conferida bit a bit contra
  `Engine.render()`.
- **Troca de fps.** Quando a exportação muda os quadros por segundo, os índices passam a contar na
  nova taxa (o primeiro quadro é `round(início · fps_saída / fps_original)`) e `build_plan` recebe
  o fps de saída; os efeitos ligados ao tempo (`t`) continuam no mesmo ritmo.
- **px@1080.** Todas as distâncias do esquema são em pixels de um quadro de 1080 linhas e
  multiplicadas por `altura / 1080`; os defeitos são desenhados num sistema de coordenadas de
  1080 linhas de altura. O grão é a única textura cujo padrão exato depende da resolução (o
  tamanho estatístico é o mesmo); por isso a dica da prévia recomenda a resolução máxima para
  julgar o grão.

## 7. Threads e processos

```mermaid
flowchart LR
    subgraph T0["Thread principal (Qt)"]
        R["render_now()<br/>Engine principal"]
        TH["miniaturas<br/>thumb_engine (mesmo contexto)"]
        PT["play_timer<br/>escolhe o quadro pelo relógio"]
    end
    subgraph T1["FrameLoader"]
        FL["grab_frame()<br/>só o pedido mais recente"]
    end
    subgraph T2["Player"]
        PL["FrameReader contínuo<br/>fila de 8 quadros"]
    end
    subgraph T3["ExportQueue — thread 'exportacao'"]
        EG["Engine próprio<br/>(contexto OpenGL próprio)"]
        RD["leitura<br/>FrameReader → frames_q"]
        WR["gravação<br/>out_q → pipe"]
        DR["dreno do stderr<br/>-progress → quadros gravados"]
    end
    subgraph T4["Estimativa"]
        MS["measure_speed()<br/>Engine próprio + vigia de 15 s"]
    end
    subgraph T5["Dependências"]
        DC["_check_deps()<br/>versão do ffmpeg / última versão"]
    end
    subgraph T6["Fila de tarefas — threads 'tarefa-N-tipo'"]
        DL["tools.download() / remove()<br/>download_ffmpeg()"]
    end
    FF1[["ffmpeg (decodificar)"]]
    FF2[["ffmpeg (codificar)"]]

    FL -- sinal loaded --> R
    PL -- fila --> PT --> R
    FL --> FF1
    PL --> FF1
    RD --> FF1
    RD --> EG --> WR --> FF2
    FF2 --> DR
    MS --> FF1
    MS --> FF2
```

| Thread | Onde | O que faz | Como fala com a interface |
|---|---|---|---|
| Principal (Qt) | `MainWindow` | Recebe quadros, chama `build_plan` + `Engine.render` (8 bits) para a prévia, desenha o visualizador, o histograma e as miniaturas (com `thumb_engine`, que compartilha o contexto do `engine` principal). | — |
| `FrameLoader` | `main_window.FrameLoader` | Decodifica um único quadro com `media.grab_frame()`. Se chegarem vários pedidos (arrastando a linha do tempo), só o mais recente é atendido. | Sinais `loaded` / `failed` (fila do Qt). |
| `Player` | `main_window.Player` | Um `FrameReader` contínuo a partir do quadro atual; põe `(índice, imagem)` numa fila de 8. Repete o trecho se a repetição estiver ligada. | `play_timer` (timer preciso) lê a fila e mostra o quadro certo para o tempo decorrido, descartando quadros atrasados. |
| `exportacao` | `export.ExportQueue` | Executa os trabalhos um de cada vez. O `Engine` é criado **dentro** dessa thread (contexto OpenGL próprio, atual nela). | `QTimer` de 500 ms na janela e de 250 ms na fila leem o estado do `ExportJob`. |
| leitura / gravação / dreno | `export.run_job` | Leitura: `FrameReader` → `frames_q`. GPU: laço na thread `exportacao`. Gravação: `out_q` → pipe do codificador. Dreno: lê o `stderr` do ffmpeg, interpreta `frame=` do `-progress` e guarda as mensagens de erro. As filas têm o tamanho do *buffer* escolhido (mínimo 2). | Campos do `ExportJob` (`done`, `fps_rate`, `eta`, `status`, `error`). |
| estimativa | `export_dialog._start_estimate` | `measure_speed()` cria **outro** `Engine`, exporta até 60 quadros num arquivo temporário (sem áudio), descarta os 8 primeiros (aquecimento) e para sozinho depois de 15 s (thread vigia). | `_Bridge.done` (sinal). Uma nova mudança cancela a medição anterior (`threading.Event`). |
| dependências | `MainWindow._check_deps` | Confere o ffmpeg e a última versão publicada (guardada em `deps.cached_latest_version()`). | `_DepsBridge.result`. |
| fila de tarefas | `jobs.JobQueue` (`jobs.shared()`) | Um thread por trabalho rodando: downloads e remoções de componentes (página Componentes), depois análises e IA. No máximo 1 trabalho de GPU. | `ui/job_bridge.JobBridge`: sinais `added`/`changed`/`finished` e `on_finished` na thread principal. |

Regras que decorrem disso:

- **Um contexto OpenGL por thread.** Um `Engine` só é usado na thread que o criou. A exportação e
  a estimativa criam os seus; a interface nunca toca neles.
- **Nada de Qt de interface fora da thread principal.** As threads de trabalho só trocam dados por
  sinais, filas ou campos simples.
- **Cancelamento cooperativo.** `ExportJob.cancel` (`threading.Event`) é conferido na leitura, na
  GPU e na gravação; o processo do codificador é morto e o arquivo parcial é apagado (sequências de
  imagens ficam).

## 8. Leitura de quadros com o ffmpeg

`media.probe()` roda `ffprobe -print_format json -show_streams -show_format` e monta o
`MediaInfo`: resolução (trocada em vídeos girados 90°), fps (`r_frame_rate`, imagens = 24),
quadros (`nb_frames` ou duração × fps), formato de pixel e profundidade, codec e perfil, taxa de
bits, metadados de cor, áudio e se é imagem.

`media.FrameReader` monta:

```
ffmpeg -v error -nostdin [-hwaccel X] [-threads N] [-ss (quadro−0,45)/fps]
       -i arquivo -map 0:v:0 -an -sn -dn
       -vf [fps=F,]scale=L:A:flags=…:in_color_matrix=M:in_range=R:threads=N,format=rgb24|rgb48le
       [-filter_threads N] [-frames:v K] -f rawvideo -pix_fmt rgb24|rgb48le <pipe>
```

- A busca usa `-ss` antes do `-i` meio quadro antes do alvo (rápido e preciso).
- A matriz de entrada vem dos metadados (`bt709`, `bt601`, `bt2020`, `smpte240m`; sem metadado,
  BT.709 a partir de 720 linhas); a faixa vem de `color_range`/`yuvj`.
- Prévia: `bicubic+full_chroma_int`. Exportação e "Salvar quadro": `lanczos+accurate_rnd+full_chroma_int`.
- 8 bits → `rgb24`; 16 bits → `rgb48le` (textura `nu2`).
- **Windows**: `NamedPipe` cria `\\.\pipe\pelicula_<uuid>` com buffer de 1 MiB; o ffmpeg escreve
  nele como se fosse um arquivo. A conexão espera o ffmpeg abrir o pipe e destrava sozinha se ele
  morrer antes (timeout de 60 s). Isso é bem mais rápido que `stdout` para quadros 4K.
- **Linux/macOS**: `stdout`/`stdin` comuns.
- Prioridade: no Windows por `creationflags` (abaixo/acima do normal); no Linux, `os.nice(10)`
  para *Baixa*.

Codificadores e acelerações são descobertos com `ffmpeg -encoders` e `ffmpeg -hwaccels`
(em cache; `media.reset_cache()` limpa depois de trocar o ffmpeg). NVENC, QSV e AMF aparecem na
lista mesmo sem hardware compatível, então `encoder_works()` codifica 0,1 s de teste antes de
oferecê-los.

## 9. Exportação

### 9.1 Do diálogo à fila

`ExportDialog` monta um `ExportSettings` (codec, recipiente, formato de pixel, qualidade,
velocidade, perfil, taxa de bits, resolução, fps, áudio, *tune grain*, pontilhado e as opções de
desempenho) e um `ExportJob` com uma **cópia** dos valores atuais. A janela principal guarda a
pasta, a qualidade e o desempenho escolhidos e põe o trabalho na `ExportQueue`.

### 9.2 `run_job()`

1. Tamanho de saída (`output_size`, dimensões pares quando o codec exige), fps, profundidade
   (`high_depth`: 16 bits se o formato tiver 10/12/16 bits, `p010`, RGB 48 ou for ProRes/FFV1),
   trecho em quadros e total de quadros na taxa de saída.
2. Pipe nomeado de saída (Windows) e comando do codificador (`build_encoder_cmd`):
   - entrada 0: `rawvideo` RGB (8/16 bits) pelo pipe, com `-progress pipe:2`;
   - entrada 1 (se houver áudio e o formato aceitar): o arquivo original com `-ss`/`-t` do trecho,
     mapeando `1:a:0?`;
   - conversão para YUV com `scale=out_color_matrix=…:out_range=…:flags=accurate_rnd+full_chroma_int`
     (GIF usa `palettegen`/`paletteuse`);
   - argumentos do codec (CRF/CQ/QP/bitrate, preset, perfil, `-tune grain`, `-x265-params`,
     `-tag:v hvc1`, opções de NVENC/QSV/AMF, FFV1 nível 3 com GOP 1 e 16 *slices*, TIFF com
     *deflate* etc.);
   - tags de cor BT.709, `+faststart` em MP4/MOV, áudio conforme `_audio_args()`.
3. `FrameReader` em alta qualidade. Com troca de fps, o leitor aplica o filtro `fps=` desde o
   começo e pula os quadros antes do trecho.
4. Três etapas em paralelo (leitura → GPU → gravação) com filas do tamanho do *buffer*.
5. Progresso: quadros **gravados** pelo ffmpeg (`frame=` do `-progress`) ou, antes disso, quadros
   processados; velocidade e tempo restante a partir daí.
6. Fim: fecha o pipe, espera o ffmpeg, confere código de saída e erros de escrita; status
   `concluido`, `erro` (com o final do `stderr`) ou `cancelado`.

### 9.3 Qualidades prontas e codecs

`export.quality_presets(info)` devolve a lista conforme o arquivo (imagem ou vídeo) e o que o
ffmpeg instalado oferece (`available()`). *Original — mesmo formato* é derivado do arquivo:
ProRes → mesmo perfil; DNxHD → DNxHR HQ/HQX; VP9/WebM → VP9; H.265 ou >8 bits → x265 10 bits com
o mesmo croma; senão x264 com o mesmo croma.

### 9.4 Áudio

`_audio_args()` copia quando o codec do original cabe no recipiente (tabela por recipiente) e senão
converte: WebM → Opus, AVI → MP3, MOV → PCM 24 bits, demais → AAC 320. PCM em MP4 vira AAC. GIF,
imagens e sequências não têm áudio.

## 10. Dependências externas (`deps.py`)

| Item | Valor |
|---|---|
| Versão mínima recomendada | `MIN_VERSION = (7, 0)`; builds de desenvolvimento (`N-…-AAAAMMDD`) são "desatualizados" depois de 540 dias |
| Fonte Windows | `https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip` + `.sha256`; versão atual em `…/release-version` |
| Fonte Linux | `https://github.com/BtbN/FFmpeg-Builds/releases/latest/download/ffmpeg-master-latest-linux64-gpl.tar.xz` + `checksums.sha256` |
| Plataformas | `PLATFORM_ENABLED = {"win32": True, "linux": True, "darwin": False}` |
| Pasta do app | Windows `%LOCALAPPDATA%\PeliculaConverter`; Linux `$XDG_DATA_HOME/PeliculaConverter` (padrão `~/.local/share/…`); macOS `~/Library/Application Support/…` |
| Instalação | `ffmpeg/bin/` dentro da pasta do app, com `ORIGEM.txt` (URL, fonte, SHA-256) |

`download_ffmpeg()`:

1. baixa o arquivo de hash publicado e extrai o SHA-256 esperado (no Linux, a linha do arquivo
   certo dentro de `checksums.sha256`);
2. baixa o pacote para uma pasta temporária calculando o SHA-256 em *streaming* (cancelável);
3. se o hash não conferir, para sem instalar nada;
4. extrai (zip com checagem de caminhos suspeitos; tar com `filter="data"`), localiza `ffmpeg` e
   `ffprobe`, copia para `bin.novo`, marca como executável no Linux e troca a pasta `bin` de uma
   vez (`rename`);
5. apaga a pasta temporária.

`media.configure()` procura nesta ordem: pasta escolhida pelo usuário → pasta do app
(`deps.ffmpeg_dir()`) → `PATH` → pastas comuns do sistema.

`missing_python_modules()` e `pip_install()` só valem rodando pelo código-fonte; no executável do
PyInstaller as bibliotecas já estão embutidas (`sys.frozen`).

O ffmpeg é a **exceção** do registro de componentes (seção 17): como os builds mudam o tempo todo e
os antigos saem do ar, ele não tem versão nem SHA-256 fixos no código — vale sempre o build mais
recente, conferido com o checksum publicado pelo autor do build. A interface é o cartão do ffmpeg em
Configurações › Componentes; o download roda na fila de tarefas (seção 18). `latest_version()` guarda
a versão consultada (`cached_latest_version()`), e a página mostra essa versão sem consultar a rede de
novo.

## 11. Persistência e arquivos

| O quê | Onde |
|---|---|
| Sessão e preferências | `QSettings("PeliculaConverter", "PeliculaConverter")` — registro `HKCU\Software\PeliculaConverter\PeliculaConverter` no Windows, `~/.config/PeliculaConverter/PeliculaConverter.conf` no Linux. Chaves: `session_values` (JSON dos ajustes), `session_preset`, `geometry`, `splitter`, `compare`, `preview_quality`, `advanced`, `last_dir`, `export_dir`, `export_quality`, `export_perf`, `ffmpeg_dir`, `ffmpeg_skip`. A sessão é gravada no `closeEvent` da janela. |
| Módulos | Nas mesmas preferências: `modulos/<id>` (`"1"`/`"0"`; sem valor vale o padrão), `modulos/perfil` e `modulos/mostrar_testes` (seção 16). |
| Presets do usuário | `presets.user_dir()` = `$APPDATA/PeliculaConverter/presets` (sem `APPDATA`, a pasta pessoal) — um `.json` por preset, nome derivado do título. |
| Meus LUTs | `luts.user_dir()` = `$APPDATA/PeliculaConverter/luts`. |
| ffmpeg baixado | `deps.ffmpeg_dir()` (veja a seção 10). |
| Ferramentas baixadas | `tools.tools_dir()` = `<pasta do app>/ferramentas/<id>/<versão>/`, cada versão com `pelicula-origem.json` (URL, SHA-256, data). Pastas `.novo-*` (instalação em andamento) e `.removendo-*` (remoção) são temporárias. |
| Temporários | `pelicula_seta.png` (seta das listas), `pelicula_cena_de_teste.png` (cena de teste), `pelicula_medida_*` (estimativa, apagada no fim), `pelicula_ffmpeg_*` (download, apagada no fim). |

Formato do preset: `{"nome", "desc", "app": "PeliculaConverter", "versao": 1, "valores": {…}}`.
`params.sanitize()` completa as chaves que faltam com o padrão, descarta chaves desconhecidas,
limita números à faixa e recusa escolhas inválidas — presets antigos continuam abrindo quando
parâmetros novos surgem.

## 12. Testes

A suíte fica em `tests/` (configuração em `pytest.ini`, que já põe a raiz no `sys.path`):

- `@pytest.mark.gpu` usa a fixture `gl_engine` e é pulado sem OpenGL 3.3 (CI, máquinas virtuais);
- `@pytest.mark.ffmpeg` usa `ffmpeg_ok` e é pulado sem ffmpeg/ffprobe;
- `APPDATA` é redirecionado para uma pasta temporária em todos os testes, então presets e LUTs do
  usuário nunca são tocados;
- os testes de componentes (`test_tools.py`, `componentes_ui_cases.py`) redirecionam também
  `LOCALAPPDATA`/`XDG_DATA_HOME` (a pasta do app, onde ficam o ffmpeg e as ferramentas baixadas) e não
  usam a rede: pacotes locais, `file://` e um servidor HTTP em 127.0.0.1.

```bash
.venv\Scripts\python -m pytest -q      # Windows
.venv/bin/python -m pytest -q          # Linux
QT_QPA_PLATFORM=offscreen python -m pytest -q   # sem tela (como no CI)
```

## 13. Modo Edição

O modo Edição monta uma **sequência** (faixas de vídeo e de som com clipes) que vira a entrada do look
de película. A regra do caminho único continua: tudo que muda a imagem de um clipe vive em
`compositor.clip_uniforms()` + `editshaders.CLIP` / `Engine.compose()`; tudo que muda o tempo vive em
`timeline.Sequence` (`src_frame`, `layers_at`); tudo que muda o som vive em `audiomix.py`. Prévia, "Salvar
quadro", terminal e exportação chamam as mesmas funções.

```mermaid
flowchart LR
    SEQ["timeline.Sequence<br/>faixas, clipes, transições"]
    GR["sequence.grab()<br/>(arrastar, salvar quadro)"]
    RD["sequence.SequenceReader<br/>(reprodução, exportação)"]
    FL["FrameLayers<br/>imagens das camadas"]
    CO["Engine.compose()<br/>CLIP por camada · tela f4"]
    FI["build_plan + Engine.render()<br/>look de película"]
    MX["audiomix.render_mix()<br/>WAV 48 kHz"]
    EN[["ffmpeg (codificar)"]]
    SEQ --> GR --> FL
    SEQ --> RD --> FL
    FL --> CO --> FI --> EN
    SEQ --> MX --> EN
```

### 13.1 Modelo (`timeline.py`)

- **Tempo da sequência** em quadros inteiros no fps da sequência; **tempo do arquivo** em segundos
  (`Clip.src_in`), para misturar fps diferentes e arquivos só de som.
- `Sequence.src_frame(clip, t)` = `floor((src_in + (t − start)/fps · velocidade) · fps_do_arquivo + 1e-6)`,
  limitado ao arquivo; imagens e "congelar quadro" usam sempre o mesmo quadro. É a única regra de
  mapeamento: o leitor em ordem e a busca direta dão o mesmo quadro.
- Faixa 0 = V1/A1, a de baixo. Vídeo e som do mesmo arquivo nascem **ligados** (`Clip.link`): mover,
  aparar, dividir, mudar a velocidade e apagar valem para o grupo, com o deslocamento limitado pelo membro
  mais restrito (o grupo nunca sai de sincronia). Faixas travadas não mudam (arrastar um clipe travado
  não mexe em nada).
- Colocar um clipe sobre outro **sobrescreve** (`_clear_range`: apaga, encurta ou divide o que estava
  embaixo). `delete(ripple=True)` fecha o espaço; `close_gaps()` junta os clipes de uma faixa.
- Velocidade: `set_speed()` mantém o trecho do arquivo e muda a duração (sem invadir o clipe seguinte).
- `layers_at(t)` resolve as transições: surgir/sumir no preto ou branco (`Layer.fade`), "dissolver"
  (o clipe anterior da mesma faixa continua por baixo, além do fim — `Layer.extension`) e "sumir
  mostrando a faixa de baixo" (`Layer.alpha`).
- `is_trivial()`: a sequência é só "o arquivo inteiro, sem ajustes" → o modo Película lê o arquivo
  direto (exatamente o caminho de antes do modo Edição).
- `History`: desfazer/refazer por instantâneos JSON (até 200).

### 13.2 Decodificação (`sequence.py`)

- `decode_size()`: cada clipe é decodificado no tamanho da sua caixa na tela (encaixe × escala, sem passar
  da resolução do arquivo). Na prévia a tela é menor (`canvas_size(seq, altura)`), então a decodificação
  também é.
- `grab()` usa `media.grab_frame()` com um cache LRU de 16 imagens (arrastar a linha do tempo).
- `SequenceReader` mantém um `FrameReader` por clipe ativo, anda só para a frente (lê e descarta até o
  quadro pedido; reabre se o salto passar de 2 s), repete o último quadro em câmera lenta e **abre antes**
  (thread `seq-prefetch`) os leitores dos clipes que começam no próximo 1,5 s, para os cortes não
  engasgarem. Com `fps_out`, o quadro i da saída é `start + floor(i · fps_seq / fps_out)`.
- O leitor devolve só imagens (`FrameLayers`); a montagem é feita na thread da GPU.
- `media.probe_source()` abre vídeos, imagens e arquivos só de som (`media.AUDIO_EXT`).

### 13.3 Montagem na GPU (`compositor.py`, `editshaders.py`, `Engine.compose`)

| Passo | Como |
|---|---|
| Tela | Dois alvos RGBA f4 (`canvas_a`/`canvas_b`) alternados; começa com a cor de fundo da sequência. |
| Camada | `CLIP` lê o clipe (`t_clip`) e a tela anterior (`t_dst`), aplica detalhe → cor → vinheta/desbotar → fade e mistura (normal, tela, multiplicar, sobrepor, adicionar, clarear, escurecer) com a opacidade. |
| Enquadramento | `u_xf` (mat3) leva o pixel da tela ao uv do clipe: caixa do encaixe, escala, rotação (positivo = horário), posição (fração da tela, y para baixo) e espelhos. A borda do corte tem antisserrilhado analítico (distância em px). |
| Exatidão | Clipe neutro com o tamanho da tela usa `texelFetch` (`u_exact`) e a saída `OUT` arredonda para inteiros (`u1`/`u2`): o resultado é **bit a bit** o arquivo, em 8 e 16 bits. |
| Cor | Exposição e balanço de branco em luz (código^2,2); tons por canal (pontos preto/branco, realces/sombras, curva de 4 faixas, brilho, contraste em S); levantar/gama/ganho das rodas; saturação, vibração, matiz e HSL de 8 faixas. |
| Rodas | Ponto [x, y] no disco: matiz = `atan2(y, x)` em graus como no HSV (0° vermelho em +x, sentido anti-horário com y para cima: 60° amarelo, 120° verde, 180° ciano, 240° azul, 300° magenta); força = distância (≤ 1). O desvio de cor não muda a luminância. |
| Detalhe | Bilateral 5×5, desfoque por mipmap (12 amostras), nitidez (máscara de nitidez) e clareza (mipmap bem desfocado); passos proporcionais à altura do clipe. |

`neutral=True` mantém enquadramento, opacidade e transições mas desliga cor e detalhe: é a imagem
"original" da comparação no modo Edição. `auto_adjust()` (numpy) calcula exposição, balanço de branco e
níveis com a mesma matemática do shader; `editparams.apply_quick_look()` aplica um ajuste rápido.

### 13.4 Som (`audiomix.py`)

Um WAV de 48 kHz estéreo em 24 bits por trecho. Cada clipe de som vira uma entrada (`-ss`/`-t` no trecho
usado do arquivo) com a cadeia: `aresample` → `atempo` (encadeado fora de 0,5–2) → volume do clipe +
da faixa → realce de voz (`highpass` + `acompressor`) → `bass`/`equalizer`/`treble` → `afftdn` →
`loudnorm` → balanço (`pan`) → `afade` de entrada e saída (no tempo do clipe) → `atrim` no trecho →
`adelay` até a posição. Tudo é somado com `amix=normalize=0` sobre um `anullsrc` com a duração exata do
trecho. Grafos longos vão por `-filter_complex_script`. A prévia guarda o WAV da sequência inteira e só
o refaz quando `mix_key()` muda. `peaks()` decodifica o som em mono numa taxa baixa para desenhar a forma
de onda (com cache por arquivo).

### 13.5 Exportação e projetos

- `ExportJob.sequence`: `run_job()` mixa o som do trecho num WAV temporário (cancelável), passa-o como
  entrada de áudio **sem** `-ss` (`build_encoder_cmd(audio_path=…)`), lê com `SequenceReader` e chama
  `engine.compose()` antes de `build_plan`/`render`. O número do quadro do look é o quadro da sequência,
  como na prévia — a exportação FFV1 16 bits de uma edição é conferida bit a bit (`tests/test_sequence.py`).
- `sequence.media_info(seq)`: `MediaInfo` virtual (tamanho, fps, duração, som, formato do 1º vídeo) usado
  pela janela de exportação, pela estimativa (`measure_speed(..., sequence=seq)`) e pelo terminal.
- `.plc`: a sequência vai em `"edicao"` (cada fonte com caminho absoluto e `"relativo"`, reencontrada
  como a mídia principal) e o modo em `"modo"`. `"formato": 2` só quando há sequência; projetos simples
  continuam `1` e abrem nas versões antigas.
- Terminal: `exportar`/`quadro` de um `.plc` com edição renderizam a montagem (`cli.project_sequence`); o
  comando `resolve` (`davinci`) instala ou grava o plugin do DaVinci Resolve.

### 13.6 Na janela (`ui/main_window.py`)

- Seletor **Película | Edição** no topo (`set_mode`). Na Edição aparecem a Mídia (esquerda), a linha do
  tempo (embaixo da prévia) e o inspetor com medidores (direita); a barra da prévia ganha *Com
  película*, *Sequência* e desfazer/refazer da edição.
- `_refresh_source()` escolhe a fonte da prévia: na Edição, sempre a sequência; na Película, a
  sequência só quando ela não é trivial (senão o arquivo, pelo caminho antigo). A prévia trabalha com
  uma **cópia** da sequência (`src_seq`), entregue às threads de leitura; `TimelineModel.changed`
  com `"values"` só remonta o quadro atual na GPU (as camadas já decodificadas recebem os ajustes
  atuais), o resto recarrega a fonte.
- O `FrameLoader` e o `Player` aceitam arquivo ou sequência (`sequence.grab` / `SequenceReader`);
  a montagem (`Engine.compose`) acontece na thread principal, com o mesmo contexto da prévia.
- Som da prévia da sequência: `audiomix.render_mix` num WAV temporário em segundo plano (troca de nome
  a cada versão, porque o player segura o arquivo aberto), refeito quando `mix_key()` muda.
- O que a prévia mostra é o que sai: no modo Edição sem *Com película*, exportar e salvar quadro
  saem só com a montagem (look "Original").

## 14. Laboratório: emulação por densidade

Uma alternativa física à curva paramétrica do look, toda dentro de `colorPipe` (entra no LUT exportado
e no plugin do Resolve). Tabelas e calibração em `look.py`; GLSL em `shaders.COMMON` (`labSoftplus`,
`labCurve`, `labPath`, `labPipe`).

1. **Negativo**: `e = sens · lin` (sensibilidade das camadas, linhas somam 1) → `le = log10(e / 0,18)`
   → densidade `dn = ii · curva(le)`; a curva característica é um *softplus duplo*
   `g·w·(sp((x−pé)/w) − sp((x−ombro)/w))` (pé, trecho reto com gama `g`, ombro) e `ii` é a diafonia
   entre camadas (efeitos de interimagem) no espaço de densidade. A revelação forçada multiplica a gama
   (`1 + 0,12·push`) e sobe o pé (`+0,08·push`).
2. **Copiadora**: a exposição da cópia é `off − dn`, onde `off` = calibração + luzes da copiadora
   (`0,025 log E` por ponto, 12 pontos = 1 stop).
3. **Cópia**: `dl = curva_da_cópia(off − dn)`; densidade final `d = dye · dl + (key · dl)` (diafonia dos
   corantes e, no Technicolor, a chave preta; na retenção de prata, a prata somada às três cores).
   Exibição: `10^(−d / 2,6)`.
4. **Sem cópia** (negativo escaneado): inversão digital `(dn − meio) / (g · 0,30103)` em stops e a curva
   neutra de exibição.
5. **Processos**: o caminho A é o negativo + cópia escolhidos; Technicolor 3 tiras / 2 cores usam um
   caminho B (registros P&B, corantes puros, chave) misturado por *Força do processo*.

A **calibração** (`look.lab_paths`, com `lru_cache`) acha por Newton/mínimos quadrados o `off` que leva
o cinza 18% ao código 0,45 em todos os canais, para toda combinação negativo × cópia × processo × push ×
diafonia × chave (no Technicolor 2 cores, só duas camadas de corante: sobra um tom mínimo, < 0,006).
`look.lab_eval()` é a referência em numpy usada nos testes. Com `lab_on` desligado o plano só leva
`u_lab_on = 0` e a imagem não muda.

## 15. Plugin do DaVinci Resolve (`resolve.py`)

`build_package(pasta)` grava `PeliculaConverter/` com:

| Arquivo | Conteúdo |
|---|---|
| `PeliculaConverter Cor.dctl` | Perfil de entrada, exposição/balanço, Laboratório, look de película, pele, cópia, envelhecimento, força geral. Só cor (funciona também como LUT). |
| `PeliculaConverter Textura.dctl` | Grão animado (`TIMELINE_FRAME_INDEX`), halação, bloom, névoa, maciez, nitidez, aberração, distorção, vinheta. |
| `PeliculaConverter Projetor.dctl` | Tremor, cintilação, clarões, cor instável, emendas, vazamento, poeira, riscos, fio de cabelo, manchas, marcas de rolo, moldura. |
| `Presets/` | Os DCTLs de cada preset (Cor, Textura e, se o preset usa, Projetor) com os valores do preset como padrão. |
| `LUTs/` | Um `.cube` por preset (assado com `Engine.bake_lut` numa thread com contexto próprio) — Resolve gratuito, Premiere etc. |
| `LEIA-ME.txt`, `VERSAO.txt` | Guia (PT-BR e EN) e marcador de versão para a instalação. |

- **Um código, dois dialetos**: `source(kind, dialect)` gera o mesmo kernel em DCTL (para o Resolve) ou
  em GLSL (para os testes, com os controles como uniforms). `tests/test_resolve.py` roda o dialeto GLSL
  com o moderngl e compara com o app: a cor bate com `Engine.bake_lut` (≤ 8e-7 nos 44 presets e em todos os controles novos, < 1,3e-4
  na varredura das 180 combinações do Laboratório); textura e projetor ficam a 1/255 de
  `Engine.render`, exceto halação/bloom/névoa (aproximação de passo único por amostragem esparsa).
- **Laboratório no DCTL**: a calibração das luzes da copiadora é resolvida no próprio kernel, em forma
  fechada (a curva da cópia tem pé zero e se inverte exatamente; as densidades das camadas saem de um
  sistema 3×3), então qualquer push, diafonia, chave e força funciona sem tabelas enormes.
- **Restrições do DCTL** respeitadas pelo gerador: texto ASCII, sem *swizzles*, sem sobrecarga de
  funções (OpenCL), literais com `f`, até 64 controles por tipo e 5 seletores de cor, tabelas
  `__CONSTANT__`. Tudo vem das tabelas de `look.py`/`params.py`/`presets.py` — o plugin não deriva do app.
- `install()` grava numa pasta temporária e troca a antiga de uma vez; recusa uma pasta
  `PeliculaConverter` que não foi criada por ele. `lut_dirs()` procura a pasta de LUTs do Resolve no
  Windows, Linux e macOS.

## 16. Módulos (recursos opcionais)

Todo recurso que o usuário pode dispensar — inclusive os que já existiam — é um **módulo** que liga e
desliga em **Configurações › Recursos**. A regra de ouro: desligar um módulo **só esconde a ferramenta**
na janela. `look`, `compositor`, `engine`, `export` e os comandos de renderização da CLI nunca consultam
`modules`, então um projeto ou preset que usa um módulo desligado sai idêntico (prévia e exportação).

```mermaid
flowchart LR
    REG["modules.py<br/>MODULES · PROFILES"]
    PREF[("preferências<br/>modulos/id")]
    PG["Configurações › Recursos<br/>ui/pages/recursos.py"]
    FR["1º acesso<br/>ui/profile_dialog.py"]
    CLI["pelicula-cli modulos"]
    MW["MainWindow.apply_modules()"]
    AV["_check_modules() → ModuleNotice"]
    PG -->|set_enabled / apply_profile| PREF
    FR -->|apply_profile| PREF
    CLI --> PREF
    PG -->|"settings_changed('modulos')"| MW
    PREF --> MW
    MW --> AV
```

- **Registro** (`modules.py`, sem Qt): `Module(id, name, description, group, status, requires)`. O `id` é
  sem acento e nunca muda (fica gravado). `status` é `estavel`, `beta` ou `experimental`.
- **Estado**: `modulos/<id>` = `"1"`/`"0"` nas preferências (`ui/prefs.settings()`). Sem valor vale o
  padrão: estável ligado (quem atualiza não perde nada), em teste desligado. `modulos/mostrar_testes`
  faz a página listar os recursos Beta e Experimentais (um recurso em teste ligado aparece sempre, para
  poder desligá-lo).
- **Perfis** (`PROFILES`): Simples ⊂ Criador ⊂ Cinema ⊂ Tudo. `apply_profile()` grava só os módulos
  estáveis (recursos em teste nunca são ligados por perfil) e `modulos/perfil`; `current_profile()` acha
  o perfil que bate exatamente com os estáveis ligados (`None` = *Personalizado*).
- **Primeiro acesso**: `app.choose_profile()` mostra o `ProfileDialog` logo depois do idioma (quatro
  cartões, *Tudo* marcado). Quem já tinha idioma salvo nunca vê essa escolha.
- **Página Recursos** (`ui/pages/recursos.py`): cartões dos perfis (`ProfileCard`, os mesmos do primeiro
  acesso), a lista por grupo (`GROUPS`) com selo de estado e chave, e *Mostrar recursos em teste*. Toda
  mudança grava com `set_enabled`/`apply_profile` e emite `settings_changed("modulos")`, que chega em
  `MainWindow.apply_modules()`.

### 16.1 Na janela

`MainWindow.apply_modules()` roda na abertura e a cada mudança. As ferramentas de cada módulo estão
em `_module_tools()` (widgets e `QAction`s que recebem `setVisible`); os casos especiais ficam no próprio
`apply_modules()`:

| Módulo | O que some |
|---|---|
| `edicao` | O seletor Película/Edição e os atalhos `Ctrl+2` e `Ctrl+I`. Se a janela estava no modo Edição, volta para o Película **sem mexer na montagem** (que continua sendo a entrada do look); `set_mode("edicao")` e `import_paths` ficam no Película. |
| `laboratorio`, `defeitos`, `scan`, `luts` | As seções `lab`, `desgaste`, `scan` e `lut` do painel de ajustes (`params.SECTIONS`). |
| `exportar_lut` | *Exportar a cor como LUT .cube* (33 e 65 pontos) e *Exportar todos os presets como LUTs* no menu do preset. |
| `scopes` | Os medidores (histograma, forma de onda, parada RGB, vetorscópio) dos dois modos. |
| `curva` | A chave *Curva* e o gráfico (a preferência `show_curve` fica como estava). |
| `davinci` | *Plugin para o DaVinci Resolve…* no menu de Configurações. |
| `medidor_som`, `notificacoes`, `recuperacao` | Ainda sem ferramenta na janela: entram em `_module_tools()` quando ganharem uma. |

**Aviso de uso** (`_check_modules()`): depois de abrir um projeto, aplicar um preset, soltar um LUT ou
mudar os módulos, `modules.used_by(valores, montagem)` diz o que o trabalho usa de fato (`lab_on`,
`desg_on`, `scan_on`, `lut_on` com arquivo, montagem que não é só o arquivo inteiro). Se algum desses
módulos está desligado, a faixa `ModuleNotice` (abaixo da barra do topo) mostra os nomes, lembra que a
imagem e a exportação não mudam e oferece **Ligar** (religa e emite `settings_changed("modulos")`) ou
fechar. Fechado, o aviso só volta nesta sessão se aparecer um módulo novo na lista ou se o módulo for
religado e desligado de novo.

**Terminal**: `pelicula-cli modulos` lista os módulos (id, nome, estado, ligado) e aceita
`--perfil P`, `--ligar ID` e `--desligar ID` (repetíveis) e `--json`. Ele só grava as preferências da
janela; exportar pelo terminal nunca depende dos módulos.

**Testes**: `tests/test_modules.py` (registro sem Qt) e `tests/test_modules_ui.py` (casos de
`modules_ui_cases.py` num subprocesso offscreen com um `.ini` próprio: página, perfil do primeiro acesso
e a janela inteira, que se pula sem OpenGL 3.3).

## 17. Componentes externos (`tools.py`)

Registro dos programas externos que o app usa, mostrado em **Configurações › Componentes**
(`ui/pages/componentes.py`). Sem Qt.

| Tipo | O que o app faz | Exemplos |
|---|---|---|
| `BAIXADO` | baixa da fonte oficial, confere o SHA-256 fixo no código e instala na pasta do app | ffmpeg (exceção, veja abaixo); ferramentas de IA nas próximas versões |
| `SISTEMA` | só detecta (`DETECTORS`, leitura), nunca baixa nem instala | DaVinci Resolve (agora), Blender (depois) |

`Tool`: id ASCII (é o nome da pasta; nunca muda), nome, descrição, ícone de `ui/icons.py`, site
oficial, licença e URL da licença, módulos que usam (`modules.MODULES`), `core` (núcleo do app),
`consent` (condições da licença que o usuário aceita antes de baixar), `backend` e `source_url`.
`Artifact` (um por sistema): versão, URL `https`, SHA-256, tamanho, pacote (`zip`, `tar.gz`, `tar.xz`
ou `arquivo`), executáveis dentro da pasta, tamanho extraído e origem.

**De onde vêm os arquivos** (o teste `test_registry_is_consistent` confere o registro):

- versão, URL, SHA-256 e tamanho **fixos no código** — o hash nunca é lido do mesmo servidor na hora do
  download;
- binário oficial do autor quando ele publica checksums (`origin=OFICIAL`); sem isso, compilado no CI do
  PeliculaConverter a partir do código-fonte oficial (`source_url`) e publicado numa release do projeto
  com `SHA256SUMS.txt` (`origin=CI`);
- só `https`; nada de instaladores nem de administrador;
- licença com condições → `consent` (a página pede o aceite); pesos e modelos com licença não comercial
  não entram.

**Exceção: o ffmpeg** (`backend="ffmpeg"`) segue o fluxo de `deps.py` (seção 10). No registro ele
aparece para a página mostrar versão, local e espaço, atualizar, remover e escolher outra pasta.

`download(tool, progress, cancel, root=None, keep_old=False)`:

1. confere o esquema da URL (`https`; `file://` e `http://127.0.0.1` só servem aos testes) e o espaço
   livre;
2. cria `ferramentas/<id>/.novo-XXXX` (no mesmo disco do destino) e baixa calculando o SHA-256 em
   *streaming*, parando se passar do tamanho fixado ou se pedirem para cancelar;
3. confere o SHA-256 **antes** de extrair — não conferiu, nada é instalado;
4. extrai com `deps.extract_archive()` (recusa caminhos absolutos, `..`, letra de unidade e `:`; no tar,
   o filtro `data` barra links para fora), confere os executáveis e os marca como executáveis no Linux;
5. grava `pelicula-origem.json` e troca de uma vez: `rename` da pasta nova para
   `ferramentas/<id>/<versão>` (uma instalação anterior da mesma versão sai antes e volta se a troca
   falhar);
6. sem `keep_old`, remove as outras versões; apaga a pasta temporária em qualquer caso.

Uma trava por ferramenta impede dois downloads simultâneos da mesma ferramenta. Sobras `.removendo-*`
somem no próximo download ou remoção; `.novo-*`, só depois de 12 h (podem ser o download de outra
janela do app).

Outras funções: `installed()` (versões com marcador válido, a mais nova primeiro), `current()`,
`executable(tool, nome)` (o caminho que um módulo usa para rodar a ferramenta), `status()` (estado para
a página: `AUSENTE`, `INSTALADO`, `DESATUALIZADO` ou `INDISPONIVEL`, versão, espaço, selo `verified`,
fonte), `remove()` (`rename` para `.removendo-*` e depois apaga; com arquivo em uso, erro e nada muda),
`disk_usage()` (ferramentas + ffmpeg do app) e `used_by()` (módulos de `Tool.modules` e de
`Module.requires`).

**Página Componentes**: um cartão por componente — ícone, para que serve, versão, espaço em disco, local
com "Abrir pasta", site oficial, licença, fonte do download, selo "verificado (SHA-256)", módulos que usam
e os botões Baixar/Atualizar/Remover —, o espaço total e a seção Sistema (placa de vídeo e OpenGL,
processador, memória, bibliotecas Python). Downloads e remoções rodam na fila de tarefas (seção 18) com a
chave `componente:<id>`: continuam com a janela fechada e reaparecem com o progresso ao reabrir. O fim de
um download do ffmpeg (tirar a pasta escolhida das preferências e chamar `media.configure()`) roda em
`on_finished`, na thread principal, mesmo com a página fechada. A página nunca consulta a rede sozinha:
a versão mais nova do ffmpeg vem da checagem ao abrir o app ou do botão "Procurar versão nova".
`MainWindow.show_deps(reason, auto_download)` abre a página com o aviso e, se pedido, já baixando o
ffmpeg (ffmpeg ausente ou antigo ao abrir o app).

## 18. Fila de tarefas (`jobs.py`)

Base dos trabalhos longos em segundo plano: downloads de componentes agora; análises e IA nas próximas
versões. O núcleo não usa Qt; `ui/job_bridge.py` faz a ponte com a interface.

```python
def analisar(job):
    for i in range(total):
        job.check_cancel()                      # levanta jobs.Cancelled se pediram para cancelar
        job.report(_("Analisando…"), i, total)  # etapa e progresso (total 0 = sem porcentagem)
    return resultado                            # vira job.result

job = bridge().submit(analisar, _("Analisar cenas"), kind=jobs.GPU, key="analise:cenas",
                      on_finished=self._guardar_no_projeto)  # chamado na thread principal
```

| Peça | O que faz |
|---|---|
| `Job` | título, tipo (`CPU`, `GPU`, `REDE`), `key` (a interface acha o trabalho por ela), `data`, estado (`ESPERANDO`, `RODANDO`, `CONCLUIDO`, `ERRO`, `CANCELADO`), etapa, `done`/`total`, `progress`, `result`, `error`, `cancel_event` |
| `JobQueue` | limite de simultâneos por tipo (`CPU` 2, `REDE` 3, **`GPU` sempre 1**), ordem de chegada dentro de cada tipo, uma thread por trabalho rodando (`tarefa-N-tipo`), `cancel`/`cancel_all`, `find(key)`, `active()`, `wait_all()`, `shutdown()`; ouvintes recebem `ADDED`, `STARTED`, `PROGRESS` e `FINISHED` na thread do evento |
| `jobs.shared()` | a fila do app inteiro; ao fechar o Python (`atexit`) cancela o que estiver rodando e espera até 2 s para as pastas temporárias serem limpas |
| `ui/job_bridge.JobBridge`, `bridge()` | leva os eventos para a thread principal (sinais `added`, `changed` e `finished`; progresso no máximo a cada 50 ms por trabalho) e chama `on_finished(job)` lá |

- **Cancelamento cooperativo**: na espera, o trabalho sai da fila na hora; rodando, a função confere
  `job.check_cancel()` ou `job.cancelled`. Uma exceção depois do pedido de cancelar conta como
  `CANCELADO` (`deps.DownloadCancelled` é um `jobs.Cancelled`).
- **Erros** viram `ERRO`, com a mensagem em `job.error`; a fila continua.
- **GPU**: o trabalho cria o seu próprio `Engine` dentro da função (um contexto OpenGL por thread) e nunca
  usa o da janela; a fila garante um de cada vez.
- **Resultado no projeto** (análises e IA): quem pediu guarda `job.result` em `on_finished`, na thread
  principal. Nada da fila entra no caminho de renderização (determinismo por quadro).
- Ligue os sinais a métodos de widgets (o Qt desliga sozinho quando o widget some) e use `on_finished`
  para o que precisa acontecer mesmo com a janela fechada. Outros recursos (as notificações do sistema,
  por exemplo) podem ouvir `bridge().finished` para avisar quando um trabalho termina.

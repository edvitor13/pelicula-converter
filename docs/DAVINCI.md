# Plugin do PeliculaConverter para o DaVinci Resolve

O PeliculaConverter leva o look para o DaVinci Resolve de dois jeitos:

| | **Plugin OpenFX** | **DCTLs e LUTs** |
|---|---|---|
| DaVinci Resolve **gratuito** | **Sim** | só os LUTs (só a cor) |
| DaVinci Resolve Studio | Sim | Sim |
| Como aparece | um efeito, *PeliculaConverter* (páginas Color e Edit) | três nós DCTL em série, mais um `.cube` por preset |
| O que tem | o look inteiro: cor, laboratório, grão, halação, bloom, névoa, lente, MTF, tremor, defeitos, moldura | o mesmo, dividido em nós |
| Igual ao app? | cor < 0,0001; quadro inteiro ≈ 1 nível de 8 bits | cor < 0,002; halação/bloom aproximados |
| Onde calcula | CPU (todos os núcleos) | GPU |
| Instala em | pasta do OpenFX (pede administrador) | pasta de LUTs do Resolve |

## Plugin OpenFX (funciona no Resolve gratuito)

Efeitos **DCTL** só rodam no Resolve Studio, mas plugins **OpenFX** de terceiros funcionam também na
versão gratuita. O `PeliculaConverter.ofx.bundle` é um plugin OpenFX próprio do app, em C++, que já vem
**compilado dentro de todo pacote do app** (`.msi`, `.zip`, `.deb`, `.tar.gz`): ninguém precisa compilar.

### Instalar

**Pelo app:** *Configurações › Plugin para o DaVinci Resolve… › Instalar o plugin OpenFX.* O app copia o
pacote para a pasta padrão do OpenFX — `C:\Program Files\Common Files\OFX\Plugins` no Windows,
`/usr/OFX/Plugins` no Linux — e por isso o sistema pede **permissão de administrador** (UAC no Windows,
`pkexec` no Linux; sem `pkexec`, o app mostra o comando com `sudo`). Feche o Resolve antes (com ele aberto
o plugin fica em uso) e abra de novo depois. A janela mostra a
versão instalada e a que veio com o app; quando forem diferentes, o botão vira **Atualizar o plugin
OpenFX**.

**Pelo terminal:**

```bash
pelicula-cli resolve --listar           # versão que veio com o app e versão instalada
pelicula-cli resolve --ofx-instalar     # instala ou atualiza (pede administrador)
pelicula-cli resolve --ofx-pasta D      # só copia o PeliculaConverter.ofx.bundle para D
```

**À mão:** copie a pasta `PeliculaConverter.ofx.bundle` (em `_internal/ofx/` na pasta do app) para a pasta
do OpenFX. Para desinstalar, apague essa pasta.

### Usar

1. Página **Color**: abra **OpenFX** (botão *Effects*), procure **PeliculaConverter** (categoria
   *PeliculaConverter*) e arraste para um nó. Página **Edit**: *Effects › OpenFX › PeliculaConverter*
   sobre o clipe.
2. Grupo **Look**: escolha um **Preset** (os 48 do app; trocar o preset troca os ajustes do look, num
   passo só de desfazer — o *Perfil do vídeo* e a *Faixa do vídeo* são do clipe e ficam, como no app) ou
   **Carregar look do PeliculaConverter (.json)** — um preset exportado pelo app (menu ⋯ dos presets ›
   *Exportar preset (.json)…*) ou um projeto `.plc`. **Recarregar o look** lê o arquivo de novo.
3. **Perfil do vídeo** (grupo *Entrada e exposição*): a curva da câmera (S-Log3, LogC3, LogC4, V-Log,
   N-Log, Log3G10, Blackmagic Film Gen 5, Apple Log, DaVinci Intermediate, Cineon e, desde a 1.6, Canon Log 2
   e 3, F-Log, F-Log2, F-Log2 C, D-Log, S-Log2 e L-Log), **HLG** ou **PQ** para vídeo HDR (celulares gravam em
   HLG) ou *Rec.709* se a linha do tempo já está em Rec.709 / Gamma 2.4 (ou ponha um *Color Space Transform*
   antes). No LogC3, **EI do LogC3** escolhe a curva do EI do clipe (padrão 800). **Proteger cores saturadas**
   (1.6, padrão 0%) traz LED, neon e céu muito saturado para dentro do Rec.709 antes do look, como no app.
   **Faixa do vídeo** só muda
   S-Log3, V-Log, N-Log, F-Log, F-Log2 e D-Log, curvas que os fabricantes escrevem no código de 10 bits (o
   cinza do S-Log3 é o código 420): deixe **Vídeo (faixa
   legal)** com o clipe em *Data Levels* Auto/Video (o padrão do Resolve para arquivos de câmera, que ele
   expande de 64–940 para 0–1 — o plugin volta ao código da câmera) e escolha **Cheia** quando o valor já é o
   código: clipe em *Full* (Clip Attributes, como a Sony recomenda para S-Log) ou log que a câmera mandou
   reescalado pela saída HDMI *Limited* (Nikon).
4. Os outros grupos são as seções do app, com os mesmos nomes (com acentos): *Película*, *Entrada e
   exposição*, *Laboratório (negativo e cópia)* — Hue Split, densidades, bleach bypass, curvas neutras,
   luzes da copiadora, revelação —, *Cor da película*, *Grão*, *Halação*, *Bloom e difusão*, *Lente e
   nitidez* (com o MTF), *Projetor*, *Defeitos da película* e *Moldura e proporção*. *Força geral* fica em
   *Película*; em 0 o efeito devolve a imagem original sem calcular nada. **Mostrar curva** desenha as
   curvas R, G e B do look sobre a imagem (desligue antes de renderizar).
5. Percentuais vão de 0 a 100; distâncias são **px em 1080p** (convertidas para a resolução do quadro,
   como no app). O grão, o tremor e os defeitos seguem o **número do quadro** e os **quadros por segundo**
   do clipe, que o Resolve informa ao plugin (não há o que escolher).
6. **Cálculo da cor**: *Exato (igual ao app)* calcula o laboratório em cada pixel; *Rápido (prévia)* passa
   a cor por um LUT 65³ montado com a mesma conta — as células do LUT em que a interpolação erraria mais
   de 0,002 (cores no limite do gamut, luzes estouradas) continuam exatas. Grão, brilhos e defeitos não
   mudam.

### Desempenho

Medido num Intel Core i9-12900KF (8 núcleos P + 8 E, 24 threads), Windows 11, binário do CI (MSVC /O2),
cena de teste do app, por quadro:

| Resolução | Só a cor (exato / rápido) | Look completo (exato / rápido) |
|---|---|---|
| 1080p | 0,14–0,18 s / 0,08–0,12 s | 0,25–0,30 s / 0,18–0,25 s |
| 4K UHD | 0,57–0,68 s / 0,32–0,42 s | 0,9–1,0 s / 0,6–0,8 s |

"Look completo" = presets *Kodak Vision3 250D* e *Teal & orange (5201 → 2393, Hue Split)* com grão,
halação, bloom, maciez, vinheta, tremor e defeitos. É CPU: para tocar em tempo real, use o **Render Cache**
do Resolve (*Playback › Render Cache › Smart*, ou botão direito no nó › *Node Cache › On*) ou a resolução
de proxy, e *Rápido* enquanto ajusta. As threads do plugin pedem desempenho ao Windows (sem isso o Windows
11 pode mandá-las para os núcleos de eficiência quando o Resolve fica em segundo plano).

### Igual ao app?

- **Cor**: a mesma conta, gerada a partir do mesmo kernel dos DCTLs. Comparado com `Engine.bake_lut`
  (GPU): diferença < 0,0001 nos 48 presets e nos 14 perfis de entrada, nas duas opções de *Faixa do vídeo*
  (no PQ, que vai até 10000 cd/m², cores HDR muito saturadas chegam a 0,001); em todas as combinações de
  negativo × cópia × processo, mediana 0,000001 e máximo 0,0005 (nos ombros mais íngremes, onde a precisão
  do float da GPU pesa).
- **Quadro inteiro** (comparado com `Engine.render`, saída de 8 bits do app): 99% dos pixels a menos de
  1/255 e média < 0,5/255 para grão, vinheta, maciez, MTF, nitidez, lente, tremor, cintilação, poeira,
  riscos, fio de cabelo, manchas, marcas, emendas, clarões, vazamento de luz, moldura, halação, bloom,
  névoa e presets inteiros; pixels isolados chegam a 2/255 (4/255 na nitidez e na halação), porque o app
  guarda a luz linear em meio float e o plugin em float32.
- Diferente dos nós DCTL, o plugin faz os **desfoques separáveis de verdade e os mipmaps** do app (sem a
  espiral de uma passada) e aplica tudo **na ordem do app** (halação e bloom antes da cor).

### Limitações

- Só CPU por enquanto (sem GPU/CUDA): é mais lento que o app; use o Render Cache.
- Sem o **scan da película** (furos, texto da borda, quadros vizinhos) e sem o **LUT externo** (ponha o
  seu LUT num nó próprio). Sem pontilhado: a saída é float.
- Sem a **Cor por planos** do app (frente, fundo e pele, 1.6): ela depende do lugar e da cor de cada pixel e fica
  fora da cor do look. No Resolve, use uma janela (Power Window) ou um qualificador num nó próprio.
- Os rótulos estão em português (o OpenFX não informa o idioma do editor).
- Os mipmaps das cadeias de brilho são médias 2×2; o driver do OpenGL do app pode filtrar um pouco
  diferente em tamanhos ímpares.
- O alfa passa direto; a cor entra como no app (código do vídeo de 0 a 1, no perfil escolhido). O plugin
  não sabe a faixa do arquivo: confira a *Faixa do vídeo* nos clipes S-Log3, V-Log, N-Log, F-Log, F-Log2 e
  D-Log.
- Compilado para Windows x64 e Linux x64 (o macOS está desativado no app).
- Conferido com um host OpenFX de teste (`tests/ofxhost.py`: descrever, criar, trocar preset, carregar
  `.json`, identidade e render); a instalação de verdade no Resolve é feita pelo usuário, pelo app.

## DCTLs e LUTs (DaVinci Resolve Studio)

O PeliculaConverter também gera um pacote de **DCTLs** (o "plugin" de cor do Resolve Studio) e de **LUTs
.cube** com o mesmo look do app. A ideia é a mesma dos pacotes de emulação de película vendidos para o
Resolve: três nós em série, na ordem de um laboratório de cinema — **LOOK → LAB → PRINT** —, aqui chamados
de **Laboratorio (ou Cor) → Textura → Projetor**.

| Nó | O que faz | Igual ao app? |
|---|---|---|
| **PeliculaConverter Laboratorio** | Só o **Laboratório**, como um nó de emulação de filme: perfil do vídeo, exposição e balanço, negativo, cópia, revelação, separação de cores (Hue Split) e o eixo, luzes da copiadora, densidade da cópia e por cor, pé da cópia, rolagens, saturação do filme e final, pele, bleach bypass no negativo e na cópia, curvas neutras, processo (Technicolor, retenção de prata), chave, diafonia e força geral. **Mostrar curva** desenha por cima da imagem as curvas R, G e B do ajuste (eixo horizontal de −8 a +8 stops em volta do cinza médio; a linha cinza marca o 0,45). | **Sim.** É o app com *Laboratório* ligado, *Cor da película* desligada e *Cópia (print)* em *Nenhuma* (como nos presets do grupo *Laboratório*). Diferença < 0,000001 nos testes. |
| **PeliculaConverter Cor** | Perfil do vídeo (Rec.709, log das câmeras), exposição e balanço, **Laboratório** (negativo, revelação, luzes da copiadora, cópia, Technicolor 3 tiras / 2 cores, retenção de prata), look de película (curva, saturação, densidade, tons de sombra/luz, pele, P&B e viragens), cópia 2383/2393/3513, envelhecimento e força geral. | **Sim.** É a mesma conta de `colorPipe()` (diferença < 0,002 nos testes, normalmente 0,000001). |
| **PeliculaConverter Textura** | Grão (tamanho, aspereza, cor, resposta por tom, animado, maciez pelo grão, respiração por camada), halação (modelo brilho ou física), bloom, névoa (filtro difusor), maciez da bitola e da lente, **MTF da película** (close, plano médio, plano aberto, 16 mm, Super 8; diferença entre camadas), recuperar detalhe, aberração cromática, distorção e vinheta. | Grão, lente, maciez e vinheta: **sim** (< 1/255). Halação, bloom e névoa: **aproximação** numa passada (veja *Limitações*). |
| **PeliculaConverter Projetor** | Tremor do quadro, cintilação, clarões de fim de rolo, cor instável, emendas, vazamento de luz, poeira, riscos, fio de cabelo, manchas químicas, marcas de troca de rolo e moldura (proporção, cantos, borda irregular). | **Sim** (< 1/255), quadro a quadro, com as mesmas sementes. |

Além dos três nós "em branco" (que já abrem com o preset inicial do app, Kodak Vision3 250D), o pacote
traz:

- **Presets/** — para cada preset pronto do app, um nó *Cor* e um *Textura* com os valores do preset (mais um
  *Laboratorio* quando o preset usa o laboratório e um *Projetor* quando usa tremor, defeitos ou moldura).
  Ex.: `Kodak Vision3 500T - Cor.dctl`, `Technicolor (5297 5386 Hue Split) - Laboratorio.dctl`.
- **LUTs/** — um `.cube` de 33 pontos por preset (só a cor, entrada Rec.709). Funcionam no **Resolve
  gratuito**, no Premiere, no Final Cut, no CapCut, no OBS e em qualquer programa que aceite `.cube`.
- **LEIA-ME.txt** (português e inglês) e **VERSAO.txt** (versão do app que gerou o pacote).

### Instalar os DCTLs e LUTs

**Pelo app:** *Configurações › Plugin para o DaVinci Resolve… › Instalar no DaVinci Resolve.* O app
encontra a pasta de LUTs do Resolve e grava a pasta `PeliculaConverter` dentro dela (substituindo uma
instalação anterior). Se a pasta não aceitar gravação, use **Salvar o pacote numa pasta…** e copie a
pasta `PeliculaConverter` para a pasta de LUTs (no Resolve: *Project Settings › Color Management › Open
LUT Folder*).

**Pelo terminal:**

```bash
pelicula-cli resolve --listar                 # mostra as pastas de LUT do Resolve
pelicula-cli resolve --instalar               # instala (ou atualiza) na pasta encontrada
pelicula-cli resolve --instalar --destino D   # instala em outra pasta de LUTs
pelicula-cli resolve --pasta D                # só grava o pacote em D (para levar a outro computador)
```

Pastas de LUT procuradas:

| Sistema | Pasta |
|---|---|
| Windows | `%ProgramData%\Blackmagic Design\DaVinci Resolve\Support\LUT` |
| Linux | `~/.local/share/DaVinciResolve/LUT` e `/opt/resolve/LUT` |
| macOS (desativado no app) | `/Library/Application Support/Blackmagic Design/DaVinci Resolve/LUT` e a mesma pasta em `~/Library` |

Depois de instalar, no Resolve clique em **Refresh** na lista de LUTs (ou reabra o programa). Para
atualizar, instale de novo pela versão nova do app: a pasta inteira é trocada.

### Usar os nós DCTL

1. Página **Color**. Crie três nós em série (Alt+S).
2. Em cada nó, arraste **OpenFX › ResolveFX Color › DCTL** e, na lista *DCTL List*, escolha
   **PeliculaConverter Laboratorio** (ou **PeliculaConverter Cor**), **PeliculaConverter Textura** e
   **PeliculaConverter Projetor**, nessa ordem (ou os arquivos da pasta *Presets*). Use o *Laboratorio*
   **ou** o *Cor*, não os dois: o *Cor* já contém o laboratório inteiro (com a chave *Laboratorio negativo
   e copia*) mais o look paramétrico, a cópia 2383/2393/3513 e o envelhecimento.
3. **Gestão de cor.** No primeiro nó, escolha em **Perfil do video** a curva da câmera (S-Log3, LogC3,
   LogC4, V-Log, N-Log, Log3G10, Blackmagic Film Gen 5, Apple Log, DaVinci Intermediate, Cineon e, desde a
   1.6, Canon Log 2 e 3, F-Log, F-Log2, F-Log2 C, D-Log, S-Log2 e L-Log) ou HLG / PQ para vídeo HDR. Se a linha do tempo já está em Rec.709 / Gamma 2.4, deixe *Rec.709*. Outra opção é pôr um
   *Color Space Transform* antes do primeiro nó convertendo para Rec.709 / Gamma 2.4. A saída dos nós é
   Rec.709 (como no app). **Faixa do video**: *Video faixa legal* (padrão) para clipes em *Data Levels*
   Auto/Video; *Cheia* para clipes em *Full* ou log reescalado pela saída HDMI *Limited* (só muda S-Log3,
   V-Log, N-Log, F-Log, F-Log2 e D-Log; veja o plugin OpenFX acima). **EI do LogC3** e **Proteger cores
   saturadas** funcionam como no plugin OpenFX.
4. Na *Textura* e no *Projetor*, escolha a **mesma bitola** (ela muda o tamanho do grão, a maciez, o
   tremor e a vinheta). No *Projetor*, escolha os **quadros por segundo** da linha do tempo: o tremor, a
   cintilação e os defeitos seguem o tempo real.
5. Os controles têm os mesmos nomes do app (sem acentos, porque o DCTL só aceita ASCII). Percentuais vão
   de 0 a 100; distâncias são **px em 1080p** (convertidas para a resolução do projeto, como no app).

Dicas:

- **Mostrar curva** (nós *Laboratorio* e *Cor*) é só para ver o ajuste — por exemplo, o efeito do *Pé da
  copia*, das *Rolagens* ou de um negativo com cruzamento de cores. Desligue antes de renderizar.
- O fluxo dos plugins de emulação (perfil → negativo → print → Hue Split → saturação do filme → luzes →
  textura com MTF, grão e halação) está explicado em [EFEITOS.md](EFEITOS.md#laboratório-negativo-e-cópia).
- Para "ajustar a cor no laboratório", use as **luzes da copiadora** (12 pontos = 1 stop; mais vermelho =
  cópia mais ciano) e a **densidade da cópia**, junto com a *Exposição* — o mesmo fluxo de um
  laboratório de verdade.
- Os nós *Laboratorio* e *Cor* podem ser aplicados também como LUT (botão direito no nó › *DCTL*), com os
  valores padrão.
- A **Qualidade do brilho** (nó *Textura*) troca velocidade por suavidade da halação/bloom/névoa.
- **Lab - Grao no negativo** (nó *Laboratorio*): o nó ganhou os ajustes do grão que esse modo usa (ligar,
  intensidade, tamanho, aspereza, colorido, semente, bitola e ISO) e põe o grão na densidade das camadas, como
  no app. Ligado, **desligue o Grão do nó Textura** para não somar dois grãos. No DCTL esse grão fica **parado**
  (o nó de cor também funciona como LUT, sem o número do quadro); o plugin OpenFX o anima como o app. O nó *Cor*
  não tem esse modo.
- **Lab - Modelo do grao no negativo** (nó *Laboratorio*, com o *Grao no negativo* ligado): *Ruido* (o de sempre)
  ou *Fisico* (os grãos de prata do app, veja [EFEITOS.md](EFEITOS.md#laboratório-negativo-e-cópia)). Como o
  outro, parado no DCTL e animado no OpenFX. É mais pesado: no nó DCTL, uns 2× o tempo do nó com o *Ruido* em
  1080p e 4K; no OpenFX (CPU), uns 3×. O nó *Cor* não tem esse modo.
- **Lab - Tamanho do cristal** e **Lab - Variacao do tamanho** (nó *Laboratorio* e plugin OpenFX, 1.6, só com o
  modelo *Fisico*): grãos maiores ou menores com a mesma granularidade e cada grão com o seu tamanho, iguais ao
  app. A *Variação* deixa o nó mais pesado (até uns 2× o do *Fisico* com 100%).
- **Grao - Estrutura pela densidade** e **Grao - Aglomeracao** (nó *Textura*, e no *Laboratorio* para o grão no
  negativo *Ruido*; plugin OpenFX, 1.6): o grão muda de forma e de força com a densidade, como no app. No nó
  *Laboratorio* e no OpenFX a densidade é a de cada camada do negativo, igual ao app. No nó *Textura* a densidade
  sai da imagem que chega ao nó (lida como o código de vídeo do app, antes da cor), então ele é igual ao app só
  quando a cor da árvore é neutra; o plugin OpenFX vê a exposição da cena e segue o app. O nó *Cor* não tem esses
  controles. Com o *Fisico* a estrutura não muda nada (ele já a tem).
- **Lab - Tipo de scanner**, **Lab - Pelicula vencida anos** e **Lab - Pre-exposicao** (com os stops abaixo do
  cinza e a cor) (nó *Laboratorio* e plugin OpenFX, 1.6): o scanner de luz branca do *Sem cópia*, o véu e a
  perda de contraste da película vencida e o *flashing*, iguais ao app (diferença < 0,000003 nos testes). O nó
  *Cor* não tem esses controles (fica perto do limite de controles do DCTL): use o *Laboratorio*. Os processos
  novos (*Reversível* e as duas *Revelações cruzadas*) e os filmes "(datasheet)" aparecem nas listas dos dois
  nós. Os presets *Película vencida (18 anos)* e *Pré-exposição (baixo contraste)* existem nos dois pacotes, mas
  no nó *Cor* saem sem a vencida e sem a pré-exposição: para o efeito completo, use o nó *Laboratorio*; como as listas ganham itens no fim, nós salvos com versões antigas continuam com os mesmos filmes.
- **MTF - Camadas com copia** (nó *Textura*): o nó não vê a cópia escolhida nos nós *Cor* ou *Laboratorio*;
  ligue-o quando houver uma cópia (print) na sua árvore, para a *Diferença entre camadas* amaciar também o
  azul, como no app. Os nós gerados pelo app já vêm com ele certo; o plugin OpenFX vê a cópia sozinho.
- **Grao - Respiracao por camada** (nó *Textura*): o nó vem depois da cor, então a variação de cada camada
  multiplica a luz da saída: é igual ao app com a cor neutra; com uma cópia ou o Laboratório falta a curva deles
  (a variação fica um pouco diferente nos pretos e nas altas luzes). O plugin OpenFX a põe antes da cor, como o
  app.
- **Halacao - Modelo** (nó *Textura*): *Física (reflexo na base)* faz a halação física do app (sem limiar, raio
  pelo quadro da bitola, áreas lisas iguais). No DCTL ela é a mesma aproximação numa passada da halação de
  sempre; o plugin OpenFX segue o app de perto.

### Resolve Studio × gratuito

- O efeito **DCTL** (OpenFX › DCTL) é do **DaVinci Resolve Studio**. No Resolve gratuito use o **plugin
  OpenFX** (acima), que tem o look inteiro, ou os **LUTs** da pasta `LUTs` (só a cor; grão, halação e
  defeitos não cabem num LUT).
- O grão e os defeitos **mudam a cada quadro** a partir do **Resolve 19.1** (`TIMELINE_FRAME_INDEX`).
  Em versões anteriores eles ficam parados (o DCTL detecta a versão e não dá erro).

### Limitações dos DCTLs

- **Halação, bloom e névoa** são calculados numa única passada (o Resolve roda um DCTL por nó, sem os
  desfoques separáveis e os mipmaps que o app usa): o brilho é amostrado numa espiral com distribuição
  gaussiana e girado de pixel a pixel. O resultado médio é igual ao do app (diferença média < 2/255),
  mas há um ruído fino no brilho, que some sob o grão; *Qualidade › Alta* reduz esse ruído.
- No app, halação, bloom, vinheta e tremor acontecem **antes** da cor; no Resolve eles vêm **depois** do
  nó *Cor* e são feitos na luz linear da curva neutra do app (para a cor da halação e do bloom a diferença
  é pequena, mas não é idêntica).
- O **scan da película** (furos, texto da borda e quadros vizinhos) e o **LUT externo** existem só no app.
  No Resolve, ponha o seu LUT num nó próprio.
- A origem das coordenadas do Resolve é tratada como no app (linha 0 = topo); efeitos assimétricos (marca
  de troca de rolo no canto superior direito) seguem essa convenção.

## Como é feito (para quem mexe no código)

- `pelicula/resolve.py` gera tudo. Os kernels são escritos uma vez num dialeto comum (C do DCTL com
  macros: `PC_F/PC_I/PC_U` para conversões, `PC_RGB(x, y)` para ler a imagem, `PC_FRAME` para o quadro) e
  saem em dois sabores: `dctl` (o arquivo do Resolve) e `glsl` (para os testes).
- As **tabelas** (gamuts, cópias, bitolas, filtros P&B, viragens, negativos, cópias e processos do
  Laboratório) são geradas a partir de `look.py` e `params.py`: o plugin não tem números próprios.
- A **calibração do cinza** do Laboratório (a luz da copiadora que deixa o cinza médio neutro) é feita no
  kernel, em forma fechada: com pé 0 a curva da cópia se inverte exatamente
  (`x = w·ln((q − 1)/(1 − q·e^(−s/w)))`, `q = e^(D/(g·w))`) e as densidades das camadas saem de
  `M·D = alvo` (mínimos quadrados no Technicolor de duas cores). Por isso qualquer revelação, diafonia,
  chave, força, separação de cores, saturação do filme, bleach bypass, curva neutra ou pé funciona sem
  tabelas. A matriz do negativo é montada linha a linha: `S·(A·I + B·J)`, com `A`, `B` de
  `look.ii_coefs` (efeito entre camadas, saturação do filme, prata no negativo) e `S` a matriz da
  separação (`look.split_matrix`: eixos `u` e `v` a partir do matiz do eixo). O que vem depois da cópia
  (`look.LabPost`: rolagens, saturação final, densidade por cor, pele) é `pc_lab_post`.
- **Mostrar curva** roda o mesmo caminho de cor uma segunda vez, para um cinza que vai de −8 a +8 stops
  ao longo da largura (`p_X`), e desenha as três curvas com `p_Y` (linha 0 = topo).
- `tests/test_resolve.py` roda o dialeto GLSL na GPU e compara com `Engine.bake_lut` (nó *Cor*: todos os
  presets, todos os perfis de entrada e todas as combinações de negativo × cópia × processo; nós *Cor* e
  *Laboratorio*: cada controle novo do laboratório em seis pares negativo/cópia; nó *Laboratorio*: os
  presets do grupo *Laboratório*) e com `Engine.render` (Textura, com o MTF, e Projetor). Também confere as regras do DCTL: só ASCII, sufixo `f` nos
  números, sem swizzles nem sobrecarga de funções, assinatura exata do `transform`, até 64 controles por
  tipo e 5 seletores de cor, rótulos seguros e únicos.
- Mudou `colorPipe` (em `shaders.py`) ou uma tabela de `look.py`? Atualize o kernel em `resolve.py` e rode
  `pytest tests/test_resolve.py`. **Nunca** instale no Resolve de verdade nos testes (use pastas
  temporárias).

### Plugin OpenFX

```
plugins/ofx/
  openfx/        OpenFX 1.4 oficial (cabeçalhos + biblioteca de apoio C++), BSD-3: LICENSE e SOURCE.txt
                 (endereço, commit e SHA-256 de cada arquivo); só leitura
  generated/     pc_kernels.h (kernels + tabelas + etapas) e pc_params.h (parâmetros, grupos, 48 presets),
                 gerados por pelicula/ofx.py — não edite; rode python tools/gerar_ofx.py
  src/           pc_core.cpp (as passadas do Engine.render na CPU), pc_ofx.cpp (o efeito OpenFX),
                 pc_capi.cpp (interface C para os testes), pc_json.h (leitor dos looks .json/.plc)
  build.py       compila e monta dist/PeliculaConverter.ofx.bundle (MSVC /O2 /fp:precise /MT; g++ -O2)
  build_windows.bat, build_linux.sh
```

- **Uma conta só.** `resolve.py` tem um terceiro dialeto, `cpp`: as mesmas funções `pc_*` dos DCTLs, as
  mesmas tabelas e os mesmos trechos de corpo (`B_INPUT` perfil de entrada, `B_GAIN` exposição e ganhos
  por canal, `B_LAB` + `B_LOOK` o `colorPipe`, `B_FRAME` tremor/cintilação/eventos de `build_plan`) viram
  `pc_input`, `pc_gain`, `pc_colorpipe` e `pc_frame_params` em `pc_kernels.h`. Mudou a cor? Atualize o
  kernel em `resolve.py`, rode `python tools/gerar_ofx.py` e os testes — o DCTL e o OpenFX mudam juntos.
- **As passadas** (`pc_core.cpp`) seguem `Engine.render()`: BASE (tremor, lente e aberração, entrada,
  ganho, vinheta) → desfoque separável da maciez/MTF (raio `min(⌈3σ⌉, 48)`) → cadeias de brilho
  (EXTRACT, mipmaps até σ/2ⁿ ≤ 6, desfoque horizontal e vertical no nível, amostragem bilinear) → grade de
  ruído do grão (PCG + Box-Muller, B-spline cúbica) → FINAL (maciez/nitidez, névoa, bloom, halação,
  vazamento, cor, grão, defeitos, força geral, moldura). Distâncias em px@1080 (`scale = altura/1080`),
  quadro e sementes como no app (determinístico). Imagens com a linha 0 no topo; a cola OpenFX inverte as
  linhas (o OpenFX tem a origem embaixo).
- **Parâmetros**: os controles dos nós Cor + Textura + Projetor (sem *Qualidade*, *fps* e *Camadas com copia*,
  que o OpenFX não precisa), nas seções do app, com rótulos e dicas de `params.py`. O efeito novo abre com o preset padrão
  do app. Presets e looks `.json` viram o vetor de valores (`ofx.ui_values`); a leitura do `.json` em C++
  segue `params.sanitize` (chave ausente = padrão do app).
- **Testes** (`tests/test_ofx.py`, compila na hora ou usa `plugins/ofx/dist` se foi compilado das mesmas
  fontes; sem compilador, pula): arquivos gerados em dia, pontos de entrada do `.ofx`, paridade da cor com
  `Engine.bake_lut` (presets, perfis, varredura do laboratório), do quadro com `Engine.render`, LUT rápido ×
  exato, escala px@1080, determinismo, leitura de `.json`/`.plc`, e o efeito num host de teste
  (`tests/ofxhost.py`). Nada é instalado nas pastas do sistema.
- **Pacotes**: o CI compila o plugin (MSVC no Windows, g++ no Ubuntu 22.04) antes do PyInstaller, que o
  põe em `_internal/ofx/` (`PELICULA_EXIGIR_OFX=1` faz o build falhar sem ele); `verificar_msi.ps1` e
  `verificar_deb.sh` conferem o pacote instalado. O aviso da licença BSD do OpenFX vai junto
  (`Contents/Resources/OpenFX-LICENSE.txt`).

Os nomes de filmes são aproximações artísticas, sem relação com os fabricantes. O grão no negativo e a diferença de nitidez entre camadas usam números de datasheets públicos da Kodak.

## Câmera, formato e montagem da 1.6 no plugin

- **Formatos de foto** (Foto 35 mm 135, Foto meio quadro, Foto médio formato 120): entram na escolha *Bitola* dos
  nós e do OpenFX, com o mesmo grão, maciez, tremor, vinheta e halação do app (paridade conferida em
  `tests/test_resolve.py`). O scan da película continua fora do plugin.
- **Fora do plugin**, porque são tempo da linha do tempo do app ou geometria que o nó Textura não tem:
  - *Obturador de película* (mistura vários quadros do arquivo: no Resolve, use o Motion Blur do Resolve Studio ou
    exporte do app a partir do vídeo rápido);
  - *Manivela* (velocidade e oscilação por clipe: no Resolve, Retime/Speed Change);
  - *A montagem na película* (emendas nos cortes e rolos de Super 8: o plugin vê um quadro de cada vez, sem os
    cortes da timeline);
  - *Marcação de luz por plano* (os pontos da copiadora de cada clipe do modo Edição: é tempo da montagem do app;
    no Resolve, o nó **Laboratorio** já tem as luzes da copiadora, então use um nó por plano ou mude as luzes no
    nó de cada clipe);
  - *Lente anamórfica* (desespremer, barril, bordas e o risco horizontal longo: no Resolve, o desespremer fica
    nos atributos do clipe e o risco num efeito de brilho);
  - *Data impressa* (desenhada na luz da cena antes da película: use um texto no Fusion antes dos nós do
    Película Converter).

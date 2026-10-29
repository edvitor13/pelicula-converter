# Efeitos e ajustes

Guia de todos os ajustes do painel **Ajustes**, seção por seção, com os nomes exatamente como
aparecem no app. Os valores vêm do esquema em [`pelicula/params.py`](../pelicula/params.py); o
que cada um faz por dentro está em [`pelicula/look.py`](../pelicula/look.py) e
[`pelicula/shaders.py`](../pelicula/shaders.py).

> **Como ler as tabelas**
> - **Faixa** e **Padrão** são os limites e o valor inicial do controle (o padrão do *esquema*;
>   os presets mudam muitos deles).
> - **px** são "pixels medidos num quadro de 1080 linhas" (px@1080): o app converte para a
>   resolução real, então um raio de 14 px vale 14 px em 1080p, 28 px em 4K e 9,3 px numa prévia
>   de 720p. Assim a prévia e o vídeo final têm a mesma cara.
> - **EV** são *stops* de luz: +1 EV dobra a luz.
> - Os ajustes marcados como **avançado** só aparecem com a chave **Ajustes avançados** ligada.
> - Uma seção com chave no título só tem efeito quando está **ligada**. Desligada, ela fica
>   esmaecida e os valores ficam guardados.

Dicas de uso dos controles: clique no número para digitar (aceita vírgula, `%` e unidades),
**duplo clique** no slider volta ao padrão, **Shift + arrastar** faz ajuste fino, o botão ↺ do
título restaura a seção inteira e o dado (*Sortear*) troca as sementes aleatórias.

**Animar o look (chaves).** Os ajustes de número, cor e rodas têm um **losango** ao lado do nome: clique para
gravar uma chave no cursor; com o ajuste animado, mexer no controle grava a chave ali (chave automática); as
setas ◀ ▶ vão à chave anterior / seguinte e o botão direito escolhe a curva até a próxima chave, apaga a chave
ou limpa a animação. As chaves do look aparecem numa **faixa fina sob a barra da prévia** no modo Película e na
linha **Look**, no topo da linha do tempo, no modo Edição (com *Com película* ligado): clique leva o cursor
até a chave, arrastar move (gruda no cursor), Shift escolhe várias e Delete apaga. O tempo das chaves é o do
vídeo (no modo Película) ou o da montagem; a exportação usa as mesmas chaves, quadro a quadro.

## Ordem em que tudo acontece

```
vídeo → perfil de entrada → luz linear (gamut Rec.709) → exposição, temperatura, tonalidade
      → [cor por planos: frente, fundo e pele] → tremor do projetor / emendas → lente (distorção, aberração) → vinheta → [scan da película]
      → maciez (bitola, lente e MTF da película) / nitidez → névoa → bloom → halação → vazamento de luz
      → respiração por camada
      → [laboratório: negativo (separação de cores, saturação do filme) → copiadora → cópia
         → rolagens, saturação final, densidade por cor, pele]
      → cor da película (ou LUT "no lugar do look") → cópia → envelhecimento → LUT "depois"
      → grão → defeitos → força geral do efeito → moldura → pontilhado → saída
```

---

## Película

*Bitola, sensibilidade e cópia.* Sempre ativa (sem chave).

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Bitola** | Nenhuma (manual), 8 mm, Super 8, 16 mm, Super 16, 35 mm, 65 mm, IMAX 70 mm (15/70); 1.6: Foto 35 mm (135), Foto meio quadro, Foto médio formato (120) | 35 mm | Tamanho do quadro da película. Bitolas menores têm grão maior, menos nitidez e mais tremor. Multiplica grão, maciez, tremor, vinheta e halação e define a proporção usada por *Moldura → Da bitola escolhida* e o formato do *Scan → Da bitola escolhida*. |
| **Sensibilidade** | ISO 50, 100, 125, 200, 250, 400, 500, 800, 1600, 3200 | ISO 250 | Filmes mais sensíveis têm grão maior e mais visível: tamanho × (ISO/250)^0,18 e força × (ISO/250)^0,35. Também escolhe o código do texto de borda automático no scan. |
| **Cópia (print)** | Nenhuma (sem cópia), Kodak 2383 (cópia de cinema clássica), Kodak 2393 (mais contraste), Fuji 3513 (mais fria e neutra) | Nenhuma | Filme usado para copiar o negativo para a projeção. Aplica uma segunda curva de contraste, saturação e cor por canal por cima do negativo. |
| **Força da cópia** | 0–100% | 100% | Mistura entre o negativo e o resultado com a cópia. |
| **Desfoque da bitola** | liga/desliga | ligado | Maciez natural de cada bitola (desfoque gaussiano). Em 1080p: 8 mm 2,4 px, Super 8 1,9 px, 16 mm 1,1 px, Super 16 0,9 px, 35 mm 0,35 px, 65 mm e IMAX nenhum (em 4K, o dobro). Desligado, o vídeo mantém a nitidez original; *Lente e nitidez → Recuperar detalhe* devolve ainda mais detalhe. |
| **Intensidade do desfoque** | 0–100% | 100% | Quanto desse desfoque é aplicado (100% = o natural da bitola; 0% = nenhum). Chave `bitola_resolucao`. |
| **Vinheta da bitola** | 0–100% | 100% | Escurecimento natural das bordas em bitolas pequenas. Vale mesmo com a seção *Lente* desligada. |
| **MTF da película (maciez fina)** | Desligado, Close (rosto), Plano médio, Plano aberto, Textura 16 mm, Textura Super 8 | Desligado | A resposta de detalhe (MTF) de um filme: tira a nitidez "digital" demais (poros, serrilhado) e mantém o detalhe maior. Escolha pelo enquadramento — o close suaviza mais a pele, o plano aberto menos. É uma gaussiana fina somada em quadratura com o desfoque da bitola e a maciez da lente: σ em 1080p = 1,6 / 1,1 / 0,7 / 1,5 / 2,3 px × 2 × *Quantidade*. Chave `mtf`. |
| **Quantidade do MTF** | 0–100% | 50% | 50% = o valor do enquadramento escolhido; 100% = o dobro. Chave `mtf_forca`. |
| **Diferença de nitidez entre camadas** | 0–100% | 0% | Cada cor fica com a nitidez da sua camada na película. No negativo a camada do vermelho é a mais macia e a do azul a mais nítida; com uma cópia escolhida (a *Cópia de projeção* ou a do *Laboratório*), a cópia 2383 amacia o azul e o verde passa a ser o mais nítido. Dá franjas coloridas sutis nas bordas de alto contraste e quase nada nas áreas lisas. 50% = a diferença medida (veja *Modelos calibrados por datasheets*), convertida pelo tamanho do quadro da bitola: some no 35 mm e aparece mais no Super 8; 100% = o dobro. Soma-se em quadratura às outras maciezes. Chave `mtf_camadas`. |
| **Força geral do efeito** | 0–100% | 100% | Mistura o resultado com o vídeo original (antes da moldura). |

Valores por bitola (multiplicadores internos):

| Bitola | Tamanho do grão | Força do grão | Maciez (px) | Tremor | Vinheta | Halação | Proporção |
|---|---|---|---|---|---|---|---|
| Nenhuma | 1,00 | 1,00 | 0 | 1,0 | 0 | 1,00 | do vídeo |
| 8 mm | 3,00 | 1,55 | 2,4 | 2,8 | 0,45 | 1,60 | 1,33 |
| Super 8 | 2,60 | 1,45 | 1,9 | 2,4 | 0,38 | 1,50 | 1,36 |
| 16 mm | 1,80 | 1,25 | 1,1 | 1,6 | 0,20 | 1,25 | 1,33 |
| Super 16 | 1,60 | 1,18 | 0,9 | 1,5 | 0,16 | 1,20 | 1,66 |
| 35 mm | 1,00 | 1,00 | 0,35 | 1,0 | 0,06 | 1,00 | 1,85 |
| 65 mm | 0,60 | 0,72 | 0 | 0,7 | 0,03 | 0,85 | 2,20 |
| IMAX 70 mm | 0,45 | 0,55 | 0 | 0,55 | 0,02 | 0,75 | 1,43 |

As três cópias, resumidas:

| Cópia | Contraste | Preto / branco | Cor | Saturação |
|---|---|---|---|---|
| Kodak 2383 | 1,10× | 0,012 / 0,975 | puxa levemente para o quente (vermelho +, azul −) | 1,08 |
| Kodak 2393 | 1,20× | 0,004 / 0,985 (preto mais profundo) | quente bem leve | 1,10 |
| Fuji 3513 | 1,08× | 0,014 / 0,975 | desloca para o frio (vermelho −, verde e azul +) | 1,12 |

---

## Entrada e exposição

*Perfil de cor e balanço.* Sempre ativa.

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Perfil do vídeo** | veja abaixo | Rec.709 / sRGB (vídeo comum) | Como o vídeo foi gravado. O app desfaz a curva e o gamut da câmera para trabalhar em luz linear. Use o perfil log da câmera se gravou em log, ou HLG/PQ para vídeo HDR. Vídeo HDR é reconhecido sozinho ao abrir o arquivo (veja abaixo). **Trocar de preset não muda este ajuste.** |
| **Log reescalado (HDMI "Limited")** (avançado) | liga/desliga | desligado | Só S-Log3, V-Log, N-Log, F-Log, F-Log2 e D-Log. Ligue em gravações externas em que a câmera mandou o log já reescalado para a faixa legal (saída HDMI em *Limited*, comum na Nikon); o app deixa de voltar ao código da câmera. Presets não mudam. Chave `log_reescalado`. |
| **EI do ARRI LogC3** (avançado, 1.6) | EI 160 a EI 1600 | EI 800 | Só ARRI LogC3. A ALEXA grava uma curva para cada EI (está nos metadados do clipe): o cinza fica no mesmo lugar e muda a compressão das luzes e das sombras. Presets não mudam. Chave `logc3_ei`. |
| **Exposição** | −3 a +3 EV | 0 EV | Mais ou menos luz, antes de qualquer curva (como abrir ou fechar o diafragma). |
| **Temperatura** | −100 a +100 | 0 | Negativo esfria, positivo esquenta. Em +100: vermelho +0,28 EV e azul −0,38 EV. |
| **Tonalidade** | −100 a +100 | 0 | Negativo puxa para verde, positivo para magenta. Em +100: verde −0,22 EV, vermelho e azul +0,08 EV. |
| **Proteger cores saturadas** (1.6) | 0 a 100% | 0% | Traz com suavidade para dentro do Rec.709 as cores que a câmera grava além dele (LED, neon, céu muito saturado), logo depois da conversão do gamut e antes do look e do negativo. Sem isso, uma dessas cores chega com um canal "negativo", que vira zero: o tom muda de repente e o negativo do Laboratório vê um canal sem exposição. Com 100%, a cor mais saturada que o gamut da câmera guarda cai na borda do Rec.709; as cores comuns (até ~80% do caminho até a borda) não mudam. Abaixo de 100% é uma mistura: as cores mais extremas ainda podem passar da borda. É a compressão da *ACES Reference Gamut Compression*, no espaço do app. Presets não mudam. Chave `proteger_cores`. |

Perfis disponíveis:

| Perfil | Curva | Gamut convertido para Rec.709 | Quando usar |
|---|---|---|---|
| Rec.709 / sRGB (vídeo comum) | curva neutra de exibição do app (inversível) | Rec.709 | Celular, câmeras em modo normal, vídeos da internet. |
| Linear | nenhuma | Rec.709 | EXR e arquivos já lineares. |
| Nikon N-Log | N-Log | Rec.2020 | Nikon Z gravando em N-Log. |
| Sony S-Log3 (S-Gamut3.Cine) | S-Log3 | S-Gamut3.Cine | Sony em S-Log3 / S-Gamut3.Cine. |
| ARRI LogC3 (ARRI Wide Gamut 3) | LogC3 do EI escolhido em *EI do ARRI LogC3* (padrão 800) | ARRI Wide Gamut 3 | ARRI Alexa (LogC3). |
| Panasonic V-Log | V-Log | V-Gamut | Panasonic Lumix/Varicam em V-Log. |
| RED Log3G10 (RWG) — R3D, Nikon N-RAW e R3D NE | Log3G10 | REDWideGamutRGB | RED R3D e Nikon N-RAW convertidos no DaVinci Resolve. |
| DaVinci Intermediate (DaVinci Wide Gamut) | DaVinci Intermediate | DaVinci Wide Gamut | Arquivos exportados do Resolve em DWG/Intermediate. |
| Cineon / DPX log | Cineon (685/300) | Rec.709 | Scans de película em DPX/Cineon. |
| Blackmagic Film Gen 5 (Blackmagic Wide Gamut) | Blackmagic Film Gen 5 | Blackmagic Wide Gamut | Câmeras Blackmagic (BRAW e ProRes em *Film*, geração 5). |
| ARRI LogC4 (ARRI Wide Gamut 4) | LogC4 | ARRI Wide Gamut 4 | ARRI Alexa 35 (LogC4). |
| Apple Log (Rec.2020) — iPhone | Apple Log | Rec.2020 | iPhone 15 Pro e mais novos gravando em Apple Log. |
| HLG (HDR de celular, Rec.2100) | HLG (ITU-R BT.2100) | Rec.2020 | Vídeo HDR de celular (iPhone, Android) e de câmeras em HLG. |
| PQ / HDR10 (Rec.2100) | PQ (SMPTE ST 2084) | Rec.2020 | Vídeo HDR10 / PQ (algumas câmeras e celulares, masters HDR). |
| Canon Log 2 (Cinema Gamut) | Canon Log 2 | Cinema Gamut | Câmeras Canon em Canon Log 2 com Cinema Gamut. |
| Canon Log 3 (Cinema Gamut) | Canon Log 3 | Cinema Gamut | Canon em Canon Log 3 com Cinema Gamut. |
| Fujifilm F-Log (F-Gamut) | F-Log | Rec.2020 (F-Gamut) | Fujifilm X e GFX em F-Log. |
| Fujifilm F-Log2 (F-Gamut) | F-Log2 | Rec.2020 (F-Gamut) | Fujifilm em F-Log2. |
| Fujifilm F-Log2 C (F-Gamut C) | F-Log2 | F-Gamut C | Fujifilm em F-Log2 C (a curva do F-Log2 com o gamut mais largo). |
| DJI D-Log (D-Gamut) | D-Log | D-Gamut | Câmeras e drones DJI em D-Log (o D-Log M dos drones menores é outra curva). |
| Sony S-Log2 (S-Gamut) | S-Log2 | S-Gamut | Sony mais antigas em S-Log2. |
| Leica L-Log (Rec.2020) | L-Log | Rec.2020 | Leica SL2, SL2-S, SL3, SL3-S e Q3 em L-Log (a SL tipo 601 grava em Rec.709: o gamut fica um pouco mais saturado). |

Os perfis da 1.6 seguem as fórmulas publicadas pelos fabricantes (Canon, Fujifilm, DJI, Sony, Leica e ARRI);
o *Apple Log 2* ficou de fora porque a Apple não publicou a curva nem o gamut.

**Vídeo HDR (HLG e PQ).** O app leva o HDR para a luz da cena e deixa o cinza médio no mesmo lugar dos
outros perfis, seguindo os níveis de referência da ITU-R BT.2408:

- **HLG**: desfaz a OETF da BT.2100; o cartão cinza 18% (38% do sinal) vira o cinza médio do app (0,18) e o
  branco de referência (75%) fica em ≈ 0,99; o pico do sinal (100%) chega a ≈ 3,7 (4,4 stops acima do cinza).
- **PQ**: o sinal vira luz da tela em cd/m² e, como na conversão PQ → HLG da BT.2408 (pico nominal de
  1000 cd/m², gama 1,2 pela luminância), volta para luz da cena: 26 cd/m² ≈ cinza médio, 203 cd/m² ≈ branco de
  referência. Acima de 1000 cd/m² a luz continua subindo, sem corte (4000 cd/m² ≈ 6,0 stops acima do cinza;
  10000 cd/m² ≈ 7,1 stops); a curva da película comprime as altas luzes.
- **Detecção**: ao **abrir um vídeo** no modo Película (ou pôr o **primeiro clipe** numa montagem vazia do
  modo Edição), o app lê a transferência do arquivo (`color_transfer` do ffprobe): `arib-std-b67` → HLG,
  `smpte2084` → PQ (o vídeo HDR do iPhone, Dolby Vision 8.4, é marcado como HLG). Se o *Perfil do vídeo* está
  no padrão (Rec.709), ele passa para HLG/PQ e a barra de status avisa; se está em HLG/PQ e o arquivo novo não é
  HDR, volta para Rec.709. Um perfil log escolhido à mão nunca muda, e reabrir um projeto salvo não muda nada.
  A troca entra no desfazer (Ctrl+Z).

**Sugestão pelos metadados (1.6).** Ao abrir um arquivo (ou pôr o primeiro clipe numa montagem vazia), se os
metadados indicam outro perfil, uma faixa abaixo da barra do topo diz qual ("Pelos metadados, este arquivo
parece gravado em…") com o botão **Usar este perfil**; o *Perfil do vídeo* só muda com o clique (e entra no
desfazer). Fechar a faixa mantém o perfil; reabrir um projeto salvo nunca mostra a sugestão. O que é reconhecido:

- HDR marcado (HLG e PQ), também quando o perfil está num log escolhido à mão;
- EXR (e a transferência `linear`) → *Linear*;
- o nome da curva numa etiqueta de gamma/curva do arquivo (como as que câmeras ARRI em ProRes e gravadores
  externos podem gravar) e o XML que as câmeras da **Sony** gravam ao lado do vídeo (`C0001M01.XML`,
  *CaptureGammaEquation*: S-Log3, S-Log2, HLG);
- iPhone em **Apple Log**: marca Apple com primárias BT.2020 e sem transferência HDR (uma dedução: a Apple não
  marca a curva no arquivo).

Nunca sugere Rec.709 por uma etiqueta BT.709 (muitas câmeras marcam o log assim). Sony em MP4 sem o XML,
Panasonic, Canon, Fujifilm, Nikon e DJI não gravam a curva onde o ffprobe a mostra: escolha o perfil à mão.
No modo Edição, a sugestão preenche o cartão **Câmera** dos clipes novos (veja o guia da Edição).

**Faixa do vídeo e curvas em código de 10 bits.** Vídeo comum (YUV) usa a *faixa legal*: o preto é o código
64 e o branco o 940 (em 10 bits). O app expande essa faixa ao decodificar (64 → 0, 940 → 1), como o DaVinci
Resolve faz com um clipe em *Video levels*. A maioria das curvas é definida sobre esse sinal (LogC3, LogC4,
Blackmagic Gen 5, DaVinci Intermediate, Log3G10, Cineon, Apple Log, HLG, PQ, Rec.709, Canon Log 2 e 3, S-Log2 e
L-Log). Já a **Sony (S-Log3), a Panasonic (V-Log), a Nikon (N-Log), a Fujifilm (F-Log, F-Log2) e a DJI (D-Log)**
escrevem a curva no **código de 10 bits** e gravam esse código como está: o cinza 18% do S-Log3 é o código 420
(41% IRE) e o branco 90% é o 598 (61%). Nesses perfis o app volta ao código da câmera antes da curva,
CV = (v·876 + 64)/1023, sempre que o arquivo veio em faixa legal; imagens e vídeo de faixa cheia já trazem o
código (o L-Log da Leica em h.264/h.265 é gravado assim, em faixa cheia). Na montagem do modo Edição vale a faixa da maioria dos clipes de
vídeo. Exceção: gravações externas em que a câmera reescalou o log para a faixa legal (saída HDMI em
*Limited*, comum na Nikon) — ligue **Log reescalado**.

---

## Laboratório (negativo e cópia)

*Simula a película de verdade: negativo, revelação, luzes da copiadora e cópia.* Chave: liga o
modelo de densidade. Desligada (o padrão), nada muda.

Enquanto a seção **Cor da película** desenha um look com curvas e tons, o **Laboratório** refaz o
caminho físico que a imagem percorria num laboratório de cinema, em **densidade** (o quanto cada
camada de corante escurece o filme):

```
cena → cada camada do negativo vê uma faixa de cor (sensibilidade)
     → curva característica do negativo (pé, trecho reto com gama ~0,6 e ombro) → densidade
     → efeito entre camadas, separação de cores (Hue Split), saturação do filme, prata retida
     → copiadora: a luz atravessa o negativo; os pontos de vermelho, verde e azul decidem a exposição
     → curva característica da cópia (gama ~3, pé ajustável) → corantes ciano, magenta e amarelo
     → absorções indesejadas dos corantes (diafonia), prata retida na cópia → projeção (gama 2,6)
     → rolagens das sombras e das altas luzes, saturação final, densidade por cor, pele → tela
```

O cinza médio é **calibrado** para sair neutro (0,45) em qualquer combinação, como o "25-25-25"
de um laboratório bem ajustado; as **luzes da copiadora** que você escolhe são somadas depois.
Como no laboratório de verdade, **Exposição** (seção *Entrada e exposição*) e luzes da copiadora
trabalham juntas: um negativo superexposto fica mais denso e sai mais claro; para "copiar para
baixo", aumente a **Densidade da cópia**. Os nomes de filmes são **aproximações artísticas** do
comportamento de cada um: as curvas dos negativos e das cópias não vêm de dados dos fabricantes (só o
*Grão no negativo* usa a granularidade publicada, veja *Modelos calibrados por datasheets*).

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Negativo** | Kodak Vision3 50D, Vision3 250D, Vision3 200T, Vision3 500T, Fujifilm Eterna 250D, Eterna Vivid 500, Eastman EXR 5248 (anos 90), Eastman 5247 ECN-II (anos 70), Kodak Vision2 5201 50D, Eastman ECN-II 5297 250D, Kodak Vision 5246 250D, Kodak Vision 5263 500T, Kodak Vision2 Expression 5229 500T, Kodak Double-X 5222 (P&B) | Vision3 250D | Filme da câmera: latitude (onde ficam o pé e o ombro), contraste de cada camada, mistura de cores entre as camadas e efeito entre camadas (que satura os filmes modernos). Double-X é preto e branco pancromático. |
| **Revelação (puxar / forçar)** | −2 a +3 stops | 0 | Revelação forçada (+): mais contraste, sombras mais fechadas e grão maior (× 1,15 por stop). Puxada (−): o contrário. Cada stop muda o gama do negativo em 12%. |
| **Grão no negativo** | liga/desliga | desligado | Põe o grão da seção *Grão* (que precisa estar ligada) **dentro do negativo**: cada camada recebe o grão na sua densidade, antes da cópia, como na película de verdade. Quem molda o grão visível passa a ser a curva da cópia: ele some nos pretos profundos e nas altas luzes estouradas e aparece nos tons médios; o azul tem mais grão que o verde e o vermelho (a granularidade das camadas, veja *Modelos calibrados por datasheets*). *Intensidade*, *Tamanho*, *Aspereza*, *Grão colorido*, *Muda a cada quadro*, a bitola, o ISO e a revelação valem como sempre; a resposta por tom (*Nas sombras*, *Nos tons médios*, *Nas altas luzes*) deixa de valer. Não entra no LUT exportado. |
| **Modelo do grão no negativo** (Beta) | Ruído (campo procedural), Físico (grãos de prata) | Ruído | Só com o *Grão no negativo* ligado, e só aparece com o recurso *Grão físico* ligado em *Configurações › Recursos* (com *Mostrar recursos em teste*). *Físico* troca o campo de ruído por grãos de verdade: discos opacos espalhados ao acaso em cada camada, mais numerosos onde a camada é mais densa (a fração coberta dá a densidade). Um processo só, com os mesmos ajustes na imagem inteira: o aspecto (grãos soltos onde há pouca densidade, buracos soltos onde há muita, mais grão nos tons médios) sai da própria conta. O tamanho visível é o do *Ruído*; *Intensidade*, *Tamanho*, *Grão colorido* (quanto cada camada tem grãos próprios), *Muda a cada quadro*, a bitola, o ISO e a revelação valem; a *Aspereza* não. É mais pesado (uns 13 ms por quadro em 1080p numa RTX 3060, contra ~2 ms). Não entra no LUT exportado. Chave `lab_grao_modelo`. |
| **Cópia** | Kodak 2383, Kodak 2393 (mais contraste), Fuji 3513 (mais fria e neutra), Eastman EXR Print 5386, Eastman Color Print 5385, Kodak 2302 (cópia P&B), Sem cópia (negativo escaneado e invertido) | Kodak 2383 | Filme da projeção. A cópia dá o contraste final, a rolagem suave das altas luzes (o pé da cópia) e o preto (a densidade máxima). *Sem cópia* inverte o negativo digitalmente, como num scan: muita latitude e pouco contraste. |
| **Processo** | Normal (negativo + cópia), Technicolor 3 tiras (transferência de corante), Technicolor 2 cores (anos 20), Retenção de prata (bleach bypass) | Normal | Veja abaixo. Nos dois Technicolor a cópia escolhida não é usada (eles imprimem os próprios corantes). |
| **Força do processo** | 0–100% | 100% | Technicolor: mistura com o caminho normal (negativo + cópia). Retenção de prata: quanto de prata fica na cópia. |
| **Chave preta (Technicolor)** | 0–100% | 30% | Imagem preto e branco de baixo contraste (tirada do registro verde) somada aos corantes no Technicolor 3 tiras: pretos mais profundos e sombras mais densas. |
| **Luz vermelha da copiadora** | −12 a +12 pt | 0 | Pontos de luz vermelha (12 pontos = 0,3 log E ≈ 1 stop). Como no laboratório, **mais vermelho deixa a cópia mais ciano** (e menos, mais vermelha). |
| **Luz verde da copiadora** | −12 a +12 pt | 0 | Mais verde deixa a cópia mais magenta. |
| **Luz azul da copiadora** | −12 a +12 pt | 0 | Mais azul deixa a cópia mais amarela (quente). |
| **Densidade da cópia** | −12 a +12 pt | 0 | As três luzes juntas: mais pontos = cópia mais escura. Sem cópia, desloca a inversão do scan (12 pontos ≈ 1 stop). |
| **Separação de cores (Hue Split)** | 0–100% | 0% | Afasta as cores em volta de um eixo, como a separação das câmeras de três tiras: na densidade do negativo, o eixo laranja ↔ azul-esverdeado é esticado (× 1 + 0,60 × quantidade) e o perpendicular, verde ↔ magenta, comprimido (× 1 − 0,45 × quantidade). Pele mais quente, céu e sombras mais frios, verdes puxados para o amarelo ou o ciano. O cinza e a média das camadas não mudam e, por ser em densidade (log), o efeito é o mesmo em qualquer exposição. |
| Eixo da separação (**avançado**) | 0–360° | 35° | Matiz do polo quente do eixo (35° = laranja, o par *teal & orange*; 215° inverte os polos). |
| **Saturação do filme** | 0,00–2,00× | 1,00× | Saturação dentro do negativo, na densidade (a mistura s·I + (1 − s)/3 da matriz de camadas): muda a cor como o próprio filme, antes da cópia. O cinza não muda. |
| **Saturação final** | 0,00–2,00× | 1,00× | Saturação depois da cópia, em volta da luminância Rec.709 (0 = preto e branco). |
| **Densidade dos vermelhos / verdes / azuis** | 0,00–2,00× | 1,00× | Densidade a mais (acima de 1) ou a menos só nas cores daquele canal: o peso é o quanto o canal passa dos outros dois, então cinzas e as outras cores não mudam. Azuis acima de 1 dão o céu denso do *teal & orange*. |
| **Pé da cópia (preto)** | −1,00 a +1,00 | 0,00 | Densidade máxima da cópia × 2^(−0,6 × pé): positivo lava os pretos, negativo aprofunda. O cinza médio é recalibrado e não muda. |
| **Rolagem das sombras** | 0–100% | 0% | Entrada mais suave no preto (mesma rolagem da *Cor da película*), depois da cópia. |
| **Rolagem das altas luzes** | 0–100% | 0% | Chegada mais suave ao branco: as altas luzes estouram menos. |
| **Matiz da pele** | −30° a +30° | 0° | Negativo puxa a pele para o vermelho; positivo para o amarelo (só a faixa de matiz da pele). |
| **Saturação da pele** | −1,00 a +1,00 | 0,00 | Mais ou menos cor só nos tons de pele. |
| **Bleach bypass no negativo** | 0–100% | 0% | A prata fica no negativo e soma uma imagem neutra às camadas: contraste neutro × (1 + 0,5 × quantidade) e cor dos corantes × (1 − 0,3 × quantidade). Mais contraste, menos cor e altas luzes mais duras. |
| **Bleach bypass na cópia** | 0–100% | 0% | A prata fica na cópia (a chave neutra de 0,8 × quantidade do processo *Retenção de prata*, agora em qualquer processo): pretos mais profundos e cor mais contida. Sem efeito em *Sem cópia*. |
| Curva neutra do negativo (**avançado**) | 0–100% | 0% | Aproxima o gama, o pé e o ombro das três camadas do negativo da média delas: tira a virada de cor entre sombras e luzes do filme. |
| Curva neutra da cópia (**avançado**) | 0–100% | 0% | O mesmo para o gama e a densidade máxima das camadas da cópia. |
| Mistura entre camadas (**avançado**) | 0,00–2,00× | 1,00× | Multiplica as absorções indesejadas dos corantes da cópia: acima de 1 a cor fica mais suja e densa; abaixo, mais pura. |

**Processos.**

- **Technicolor 3 tiras** (1932–1955, *O Mágico de Oz*, *E o Vento Levou*): a câmera separava a
  cena em três negativos preto e branco por filtros estreitos; de cada um saía uma matriz que
  transferia um corante puro (ciano, magenta, amarelo) para a cópia, por cima de uma imagem preta
  de baixo contraste (a **chave**). O resultado são cores densas e saturadas, pretos profundos e
  pouca latitude nas altas luzes. Aqui: registros de pouca latitude, separação estreita (efeito
  entre camadas forte), corantes puros e chave preta.
- **Technicolor 2 cores** (anos 1920): só dois registros, vermelho-laranja e verde-azul, impressos
  em dois corantes. Pele e vermelhos ficam bons; azuis e verdes viram tons de verde-azulado e
  cinza-ciano. Com duas cores para três canais, o cinza pode guardar um tom muito leve.
- **Retenção de prata** (*bleach bypass*, *O Resgate do Soldado Ryan*): a prata não é retirada
  da cópia e soma uma imagem preto e branca aos corantes: menos cor, mais contraste, pretos
  profundos. Os controles *Bleach bypass no negativo* e *na cópia* fazem o mesmo em qualquer
  processo e em quantidade ajustável.

**Calibração.** Tudo o que muda as curvas (negativo, revelação, separação, saturação do filme,
bleach bypass, curvas neutras, pé, diafonia, chave) entra na calibração do cinza: o cinza médio
continua saindo neutro em 0,45. O que vem depois da cópia (rolagens, saturação final, densidade por
cor e pele) não mexe no cinza por construção.

**O fluxo dos plugins de emulação de película.** Os plugins de emulação vendidos para o Resolve (como
o do tutorial "Three-Strip Technicolor Look") seguem quase sempre a mesma receita, que aqui vira:

1. *Espaço de cor e gama da câmera* → **Perfil do vídeo** (seção *Entrada e exposição*).
2. *Negativo* e *Print* → **Negativo** e **Cópia** (por exemplo Eastman ECN-II 5297 → EXR Print
   5386, ou Vision2 5201 → 2393).
3. *Hue Split* perto de 0,7 → **Separação de cores** 69%; *saturação do filme* um pouco acima de 1 →
   **Saturação do filme** 1,3×.
4. *Exposição* um pouco abaixo e *printer lights* → **Exposição** e **Luzes da copiadora** /
   **Densidade da cópia**.
5. Ajustes finos → **Densidade dos azuis** (céu), **Pé da cópia**, **Rolagens**, **Pele**,
   **Bleach bypass** e **Curvas neutras**.
6. *Film texture*: *MTF* do enquadramento, grão e halação de 35 mm → **MTF da película**, **Grão** e
   **Halação** com **Bitola** 35 mm.

Os presets *Technicolor (5297 → 5386, Hue Split)* e *Teal & orange (5201 → 2393, Hue Split)* (grupo
*Laboratório*) já vêm assim. No DaVinci Resolve, o nó **PeliculaConverter Laboratorio** tem esses
mesmos controles (e *Mostrar curva*, que desenha as curvas R, G e B) e o nó **Textura** tem o MTF —
veja [DAVINCI.md](DAVINCI.md). Os nomes dos filmes continuam sendo aproximações artísticas.

Tudo isso fica dentro da parte de cor do app, então entra nos **LUTs exportados** (menu de
presets → *Exportar a cor como LUT*) e no plugin do DaVinci Resolve. Para o resultado mais fiel
use o Laboratório com **Cor da película** desligada e **Cópia (print)** em *Nenhuma* (é assim
nos presets do grupo *Laboratório*); se ligar a *Cor da película*, ela atua por cima do
resultado do laboratório.

---

## Cor da película

*Curva, cor e tons da emulsão.* Chave: liga a emulação de cor. (No esquema começa desligada; quase
todos os presets a ligam — as exceções são *Só textura*, *Original* e os do grupo *Laboratório*,
que usam o modelo de densidade no lugar.)

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Intensidade do look** | 0–100% | 100% | Mistura entre a imagem neutra e o look de película. |
| **Contraste** | 0,50–2,00 | 1,00 | Inclinação da curva do negativo (aplicada em stops, canal por canal). |
| **Tom médio** | 0,300–0,600 | 0,450 | Brilho do cinza médio na saída. |
| **Preto da película** | 0,000–0,150 | 0,000 | Película raramente chega ao preto absoluto: levanta o preto. |
| **Branco da película** | 0,700–1,000 | 1,000 | Teto das altas luzes. |
| **Suavidade das altas luzes** | 0–100% | 0% | "Ombro" da curva: quanto maior, mais suave a chegada ao branco (mais latitude nas luzes). |
| **Suavidade das sombras** | 0–100% | 0% | "Pé" da curva: transição suave para o preto. |
| **Saturação** | 0,00–2,00 | 1,00 | Saturação calculada em stops (log), como na película. |
| **Densidade de cor** | 0–100% | 0% | Cores saturadas ficam mais escuras e ricas, como em película. |
| **Cor das sombras** | 0–360° | 200° | Matiz que tinge as sombras (200° ≈ azul-petróleo). |
| **Força nas sombras** | 0–100% | 0% | Quanto da cor acima entra nas sombras. |
| **Cor das altas luzes** | 0–360° | 35° | Matiz que tinge as altas luzes (35° ≈ laranja). |
| **Força nas altas luzes** | 0–100% | 0% | Quanto da cor acima entra nas luzes. |
| **Equilíbrio sombras/luzes** | −1,00 a +1,00 | 0,00 | Move o ponto de divisão entre "sombra" e "luz" para baixo (−) ou para cima (+). |
| **Envelhecimento (desbotado)** | 0–100% | 0% | Imita cópias antigas: preto lavado, cor perdida e puxando para o magenta. |
| Contraste do vermelho · do verde · do azul (**avançado**) | 0,800–1,200 | 1,000 | Contraste por canal; desequilíbrios pequenos dão o "cruzamento" de cores típico de película. |
| Equilíbrio do vermelho · do verde · do azul (**avançado**) | −0,500 a +0,500 EV | 0 EV | Desloca cada canal em stops antes da curva. |
| Matiz dos verdes (**avançado**) | −40° a +40° | 0° | Gira só os verdes (folhagem mais amarela ou mais azulada). |
| Matiz dos azuis (**avançado**) | −40° a +40° | 0° | Gira só os azuis (céu mais ciano ou mais violeta). |
| Saturação da pele (**avançado**) | −1,00 a +1,00 | 0,00 | Satura ou dessatura só os tons de pele. |
| Matiz da pele (**avançado**) | −30° a +30° | 0° | Gira só os tons de pele: negativo puxa para o vermelho, positivo para o amarelo. |
| Luz da pele (**avançado**) | −1,00 a +1,00 | 0,00 | Muda só a luminância dos tons de pele (até ±25%): negativo deixa a pele mais densa e escura, positivo clareia. |
| **Preto e branco** | liga/desliga | desligado | Converte para P&B antes da curva, usando o filtro abaixo. |
| **Filtro do P&B** | Pancromático (neutro), Vermelho (céu escuro), Laranja, Amarelo, Verde, Azul (ortocromático) | Pancromático | Peso de cada cor na conversão, como um filtro na frente da lente. Vermelho escurece céus azuis; verde clareia folhagem; azul imita filmes ortocromáticos antigos. |
| **Viragem do P&B** | Nenhuma, Sépia, Selênio, Cianótipo, Ouro | Nenhuma | Banho químico que tinge o P&B (só vale com *Preto e branco* ligado). |
| **Força da viragem** | 0–100% | 50% | Intensidade da viragem. |

Pesos dos filtros (vermelho, verde, azul): Pancromático 0,25/0,65/0,10 · Vermelho 0,75/0,22/0,03 ·
Laranja 0,55/0,38/0,07 · Amarelo 0,40/0,52/0,08 · Verde 0,18/0,72/0,10 · Azul 0,08/0,37/0,55.

---

## LUT externo

*Use LUTs do Premiere, Resolve ou qualquer .cube.* Chave: liga o LUT.

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Arquivo .cube** | lista + *Procurar arquivo .cube…* | (nenhum) | LUTs encontrados no computador (Premiere Pro, DaVinci Resolve e *Meus LUTs*) ou qualquer arquivo. **Instalar LUTs…** copia `.cube` para a pasta do app; **Pasta** abre essa pasta. Escolher um LUT liga a seção e adivinha a entrada. |
| **O LUT espera** | Rec.709 (LUTs criativos, Premiere), Cineon log (LUTs de cópia do Resolve), ARRI LogC3, Sony S-Log3, Nikon N-Log, Panasonic V-Log, RED Log3G10 (RWG), DaVinci Intermediate (DWG), Blackmagic Film Gen 5, ARRI LogC4, Apple Log, Linear, HLG (Rec.2100), PQ / HDR10 (Rec.2100), Canon Log 2, Canon Log 3, Fujifilm F-Log, Fujifilm F-Log2, Fujifilm F-Log2 C, DJI D-Log, Sony S-Log2, Leica L-Log | Rec.709 | Em que espaço o LUT foi feito. O app converte a imagem para esse espaço (curva e gamut) antes de consultar o LUT. LUTs de cópia do Resolve (Kodak 2383 etc.) esperam Cineon; os do Premiere esperam Rec.709. Em S-Log3, V-Log, N-Log, F-Log, F-Log2 e D-Log o LUT recebe o **código de 10 bits** da câmera (a convenção dos LUTs dos fabricantes, "Full range"), qualquer que seja a faixa do arquivo. O ARRI LogC3 do LUT é sempre o do EI 800. |
| **Aplicar** | Depois do look de película, No lugar do look | Depois | *Depois*: o LUT entra sobre o resultado da cor da película e da cópia. *No lugar*: só o LUT (a cor da película e a cópia são ignoradas; o envelhecimento continua valendo se a *Cor da película* estiver ligada). |
| **Intensidade do LUT** | 0–100% | 100% | Mistura com a imagem sem o LUT. |

Só LUTs **3D** são aceitos; `DOMAIN_MIN`, `DOMAIN_MAX` e `LUT_3D_INPUT_RANGE` são respeitados. A
interpolação é trilinear na GPU.

---

## Grão

*Textura da emulsão.* Chave: liga o grão.

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Intensidade** | 0,00–3,00 | 1,00 | Força do grão (multiplicada pela bitola e pelo ISO). |
| **Tamanho** | 0,30–4,00× | 1,00× | Multiplica o tamanho natural da bitola e do ISO. O tamanho final é 0,8 × tamanho × bitola × ISO px@1080 (mínimo 1 px real). |
| **Aspereza** | 0–100% | 22% | Mistura grãos finos com aglomerados maiores (uma segunda camada ~2,3× maior). |
| **Grão colorido** | 0–100% | 30% | 0% é grão monocromático; 100% é grão independente em cada canal, como as três camadas da película colorida. |
| **Nas sombras** | 0,00–2,00 | 0,80 | Quanto grão aparece nas sombras. |
| **Nos tons médios** | 0,00–2,00 | 1,00 | Quanto grão aparece nos tons médios. |
| **Nas altas luzes** | 0,00–2,00 | 0,45 | Quanto grão aparece nas altas luzes. |
| **Grão muda a cada quadro** | liga/desliga | ligado | Desligado, o padrão do grão fica parado (útil para fotos ou efeitos especiais). |
| Semente (**avançado**) | 0–9999 | 7 | Muda o padrão aleatório do grão. |
| **Maciez pelo grão** | 0–100% | 0% | Amacia a imagem até a nitidez do próprio grão, para ele não parecer uma camada por cima de uma imagem mais nítida que ele (na película, a imagem nunca é mais nítida que o grão). 100% dá à imagem a maciez do grão: cresce com o *Tamanho*, a bitola e o ISO. Soma-se às outras maciezes (bitola, lente, MTF) e só vale com o grão ligado. |
| **Respiração por camada** | 0–100% | 0% | A cor e o brilho de cada quadro variam um pouco, cada camada por si (vermelho, verde e azul), como na película: a espessura da emulsão ao longo da fita, a revelação e a luz da copiadora nunca são iguais de um quadro para outro. Uma parte muda de quadro em quadro e outra devagar ao longo da fita (uns 24 quadros), sempre igual para o mesmo quadro e a mesma *Semente*. Entra como exposição **antes da cor**, então a cópia (ou o Laboratório) a esconde nos pretos e nas altas luzes estouradas. 100% ≈ um ponto de copiadora de desvio (0,015 de densidade do negativo), o de uma cópia revelada sem muito cuidado; vale com a seção *Grão* ligada, mesmo com a *Intensidade* em 0. Não entra no LUT exportado. Chave `grao_respiracao`. |

O grão é ruído gaussiano gerado na GPU numa grade do tamanho do grão e ampliado com interpolação
bicúbica, então tem forma arredondada (não é ruído de pixel). Ele é **procedural**: nasce dos ajustes
e de constantes publicadas, nunca de uma análise da sua imagem ou de um scan. Ele é aplicado depois da curva de
cor, com resposta por luminância (picos em 10%, 45% e 88% de brilho); com o **Grão no negativo** do
Laboratório ligado, ele vai para a densidade das camadas do negativo e quem dá a resposta por tom é a cópia. Em prévias reduzidas, grãos
menores que 1 pixel são levemente compensados; para ver o grão fiel, use a prévia *Máxima* com
zoom 100%.

---

## Halação

*Brilho avermelhado em volta das luzes.* Chave: liga a halação.

Na película, a luz forte atravessa a emulsão, reflete na base e volta, sensibilizando de novo a
camada vermelha: daí o halo alaranjado em volta de lâmpadas e reflexos.

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Intensidade** | 0,00–3,00 | 0,60 | Força do halo. |
| **Raio** | 1–100 px | 14 px | Medido num quadro de 1080 linhas (e multiplicado pela bitola: 1,6× em 8 mm, 0,75× em IMAX). |
| **Limiar** | 0–6 EV | 2,50 EV | A partir de quantos stops acima do cinza médio brilha (com transição suave). |
| **Cor** | cor | `#FF450D` (vermelho-alaranjado) | Cor do halo. Os presets de P&B usam branco. |
| **Modelo** | Brilho (acima do limiar), Física (reflexo na base) | Brilho | Veja abaixo. Chave `hal_modelo`. |

No modelo **Brilho** (o de sempre), o halo é calculado só pela luminância das luzes acima do *Limiar*,
tingido pela cor escolhida e somado por cima da imagem. Com o *Scan da película* ligado, só a área da
imagem emite halação (os furos iluminados não).

No modelo **Física**, o halo é a própria luz que volta da base do filme: nasce da exposição do vermelho
(a camada mais perto da base) em toda a imagem, na proporção da luz, e entra na exposição **antes da
cópia** (e do Laboratório, se ligado), como uma segunda exposição da camada. O *Limiar* não vale. Só o
desvio local do reflexo entra: a parte que uma área lisa receberia já está nas curvas medidas do filme,
então céus, paredes e rostos sem luz forte por perto ficam iguais (em qualquer cor), e o anel em volta
de uma lâmpada sai da própria lâmpada. A *Cor* diz quanto do reflexo chega a cada camada (no padrão,
quase só no vermelho e um pouco no verde). O *Raio* vale para o 35 mm e cresce na proporção do quadro
das bitolas menores (o anel tem o mesmo tamanho na película, uns 0,2 mm): 2,4× no 16 mm, 4,3× no
Super 8, 0,47× no 65 mm. Com a *Intensidade* padrão, uns 11% do vermelho voltam, o que é o caso de uma
película sem camada anti-halo; o halo em volta de uma luz estourada fica com a força do modelo Brilho.
Esse número não vem de datasheet: a camada anti-halo (o *remjet* da Vision3) tira quase todo o reflexo,
e o quanto sobra muda de filme para filme. A luz de um ponto estourado no arquivo é contida suavemente
(o valor dela é um palpite da entrada).

---

## Bloom e difusão

*Brilho suave nas luzes.* Chave: liga bloom e névoa.

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Bloom** | 0,00–2,00 | 0,25 | Brilho colorido e largo em volta das luzes acima do limiar. |
| **Raio do bloom** | 5–250 px | 45 px | Tamanho do brilho. |
| **Limiar do bloom** | 0–6 EV | 1,80 EV | A partir de quantos stops acima do cinza médio as luzes brilham. |
| **Névoa (filtro difusor)** | 0–100% | 0% | Imita filtros tipo Pro-Mist: luzes espalham e o contraste cai (a imagem inteira, sem limiar, é misturada e somada a uma versão bem desfocada). |
| **Raio da névoa** | 10–300 px | 70 px | Tamanho do espalhamento da névoa. |

Raios grandes são calculados em versões reduzidas da imagem (mipmaps), então continuam rápidos.

---

## Lente e nitidez

*Maciez, aberração e vinheta.* Chave: liga os ajustes de lente (a maciez e a vinheta da **bitola**
valem mesmo com ela desligada).

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Maciez** | 0–100% | 0% | Desfoque suave, somado ao da bitola. |
| **Raio da maciez** | 0,30–6,00 px | 1,20 px | Raio do desfoque da maciez (e da nitidez quando não há maciez). |
| **Recuperar detalhe** | 0,00–2,00 | 0,00 | Devolve parte do detalhe fino (efeito de nitidez, tipo máscara de nitidez). |
| **Aberração cromática** | 0,00–10,00 px | 0 px | Separa vermelho e azul nas bordas do quadro, como lentes antigas. |
| **Distorção da lente** | −0,300 a +0,300 | 0,000 | Negativo = almofada, positivo = barril. A imagem é reenquadrada para não aparecer borda vazia. |
| **Vinheta** | 0–100% | 0% | Escurecimento das bordas (até −2 EV; somado à vinheta da bitola). |
| **Raio da vinheta** | 0,20–1,60 | 0,85 | Onde a vinheta começa (1,0 ≈ canto do quadro). |
| **Suavidade da vinheta** | 0,05–1,50 | 0,80 | Largura da transição. |
| **Redondeza** | 0–100% | 50% | 0% acompanha o formato do quadro (oval); 100% é um círculo perfeito. |

---

## Projetor

*Tremor do quadro e cintilação.* Chave: liga o projetor.

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Tremor horizontal** | 0–12 px | 1,20 px | Deslocamento lateral do quadro (multiplicado pela bitola). |
| **Tremor vertical** | 0–12 px | 0,90 px | Deslocamento vertical (o "pulo" do quadro na janela). |
| **Tremor de rotação** | 0,000–0,600° | 0,040° | Pequena rotação do quadro. |
| **Velocidade do tremor** | 0,10–3,00× | 1,00× | Mais lento ou mais nervoso. |
| **Cintilação** | 0,000–0,400 EV | 0,050 EV | Variação de brilho entre quadros (obturador e lâmpada do projetor). |
| **Velocidade da cintilação** | 0,10–3,00× | 1,00× | Ritmo da cintilação. |

O movimento mistura 70% de ruído suave (deriva lenta) com 30% de variação quadro a quadro. A
imagem recebe um zoom mínimo automático para as bordas não aparecerem. Com o *Scan da película*,
a tira inteira (furos, bordas e quadros) treme junto.

---

## Defeitos da película

*Escolha quais aparecem; dá para combinar vários.* Chave geral: liga a seção; cada defeito tem a
sua própria chave.

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Poeira** | liga/desliga | ligado | Sujeira que passa pelo quadro, diferente a cada quadro. |
| Quantidade de poeira | 0–100% | 30% | Densidade de partículas. |
| Tamanho da poeira | 0,30–4,00× | 1,00× | Tamanho das partículas (algumas são alongadas, como fiapos). |
| Tipo de poeira | Escura (sujeira na cópia), Clara (sujeira no negativo), Mista | Escura | Sujeira na cópia aparece escura; no negativo, aparece clara. |
| **Riscos** | liga/desliga | ligado | Riscos verticais de película arrastada no projetor. |
| Quantidade de riscos | 0–100% | 15% | Até 6 riscos simultâneos, que mudam a cada ~14 quadros e oscilam de posição. |
| Largura dos riscos | 0,30–6,00 px | 1,50 px | Espessura. |
| **Fio de cabelo no quadro** | liga/desliga | desligado | Um fio preso na janela do projetor, tremendo na borda. |
| Frequência do fio | 0–100% | 50% | Chance de aparecer um fio em cada janela de 3 s (entra por uma borda sorteada). |
| Tamanho do fio | 0,30–3,00× | 1,00× | Comprimento e espessura. |
| **Manchas químicas** | liga/desliga | desligado | Manchas da revelação que aparecem por alguns quadros. |
| Frequência das manchas | 0–100% | 30% | Chance a cada grupo de 3 quadros. |
| **Clarões de fim de rolo** | liga/desliga | desligado | Quadros estourados de luz, como no começo e fim do rolo. |
| Frequência dos clarões | 0–100% | 25% | Chance de um clarão (quente, decaindo em ~0,1 s) a cada janela de 6 s. |
| **Marcas de troca de rolo** | liga/desliga | desligado | Os círculos no canto que avisam o projecionista. |
| Intervalo das marcas | 4–120 s | 20 s | A marca aparece por 4 quadros no canto superior direito a cada intervalo. |
| **Cor instável** | liga/desliga | desligado | A cor oscila levemente de um quadro para outro. |
| Intensidade da oscilação | 0–100% | 40% | Até ±0,12 EV por canal. |
| **Emendas** | liga/desliga | desligado | Linha de emenda e pulo do quadro onde a película foi colada. |
| Frequência das emendas | 0–100% | 30% | Chance de uma emenda a cada janela de 2,5 s. |
| **Vazamento de luz** | liga/desliga | ligado | Luz entrando pela lateral da câmera. |
| Intensidade do vazamento | 0–100% | 0% | Força (em 0% nada aparece, mesmo ligado). |
| Cor do vazamento | cor | `#FF6B1F` (laranja) | Cor da luz que vaza. |
| Velocidade do vazamento | 0,05–3,00× | 0,50× | Quão rápido as manchas de luz passeiam pela borda. |
| Semente (**avançado**) | 0–9999 | 11 | Muda onde e quando cada defeito aparece. |

Todos os defeitos são determinísticos: dependem só do número do quadro, do fps e da semente, então
aparecem igualzinho na prévia e na exportação.

---

## Moldura e proporção

*Barras e janela do projetor.* Chave: liga a moldura. Fica desligada automaticamente enquanto o
*Scan da película* estiver ligado (o scan já desenha o quadro).

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Proporção** | Original do vídeo, Da bitola escolhida, 1,33 (4:3), 1,37 (Academy), 1,43 (IMAX), 1,66 (europeu), 1,78 (16:9), 1,85 (widescreen), 1,90 (IMAX digital), 2,00 (Univisium), 2,20 (70 mm), 2,39 (Scope), 2,76 (Ultra Panavision) | Original do vídeo | Coloca barras (em cima/embaixo ou nas laterais) para chegar à proporção. O tamanho do arquivo não muda. |
| **Cantos arredondados** | 0,000–0,250 | 0,000 | Cantos da janela do projetor, típico de 8 e 16 mm. |
| **Suavidade da borda** | 0,0000–0,0500 | 0,0020 | Desfoque da borda (fração da altura). |
| **Borda irregular** | 0–100% | 0% | Borda tremida e irregular, como uma janela de projetor gasta. |
| **Cor das barras** | cor | preto | Cor fora da janela. |

---

## Scan da película

*Bordas, furos e quadros vizinhos, como num scan real.* Chave: liga o scan.

Em vez de mostrar só a imagem, o app desenha a **tira de película inteira** com as medidas reais em
milímetros (furos, linhas entre quadros, borda com texto) e coloca o vídeo dentro do quadro.

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Película** | Da bitola escolhida, 35 mm (4 furos por quadro), 16 mm (1 furo), Super 16, Super 8; 1.6: Foto 35 mm (135, 8 furos), Foto meio quadro (4 furos), Foto 120 6 × 6 e 6 × 4,5 (sem furos) | Da bitola escolhida | Medidas reais de cada película: furos, linhas entre quadros e bordas. *Da bitola*: 8 mm e Super 8 → Super 8; 16 mm → 16 mm; Super 16 → Super 16; 35 mm, 65 mm, IMAX e Nenhuma → 35 mm; 135 → 135; meio quadro → meio quadro; 120 → 120 6 × 6. |
| **Tipo de scan** | Cópia projetada (furos claros), Negativo invertido (furos escuros) | Cópia projetada | Numa cópia escaneada com luz por trás, os furos aparecem brancos; num negativo invertido, escuros. |
| **Enquadramento** | Mostrar o vídeo inteiro (barras no quadro), Preencher o quadro (corta as bordas) | Mostrar o vídeo inteiro | Como o vídeo cabe no quadro da película quando as proporções são diferentes. |
| **Aproximação** | 1,00–1,60× | 1,00× | Aproxima do quadro e esconde parte das bordas (centraliza no quadro conforme aproxima). |
| **Mostrar quadros vizinhos** | liga/desliga | ligado | Mostra pedaços do quadro de cima e de baixo. |
| **Texto da borda** | Automático (filme e ISO), Nenhum, KODAK VISION3, EASTMAN KODAK SAFETY FILM, FUJIFILM ETERNA, KODAK 2383 | Automático | Texto impresso na borda. O automático monta algo como `KODAK 5207 VISION3 250D  KJ 44 2731 0815 +12` a partir do ISO (5203 50D, 5213 200T, 5207 250D, 5219 500T; 5222 Double-X no P&B; 72xx em 16 mm). Super 8 e Super 16 não têm texto automático (a imagem do Super 16 ocupa a borda). |
| **Brilho dos furos** | 0,30–2,00× | 1,00× | Intensidade da luz que passa pelos furos (e do texto no negativo). |
| **Cor da base** | cor | `#090807` (quase preto) | Cor da película fora da imagem. |

Medidas usadas:

| Formato | Largura | Passo | Quadro (largura × altura) | Furos |
|---|---|---|---|---|
| 35 mm | 35 mm | 19,0 mm | 24,9 × 18,66 mm | 2,794 × 1,981 mm, dos dois lados, a cada 4,75 mm |
| 16 mm | 16 mm | 7,62 mm | 10,26 × 7,49 mm | 1,829 × 1,27 mm, um lado |
| Super 16 | 16 mm | 7,62 mm | 12,45 × 7,41 mm | 1,829 × 1,27 mm, um lado |
| Super 8 | 8 mm | 4,234 mm | 5,79 × 4,01 mm | 0,914 × 1,143 mm, um lado |

A borda da imagem tem uma leve irregularidade e a base tem variação de densidade, como num scan
de verdade. Com o scan ligado, a *Moldura* é ignorada, a halação só nasce dentro da imagem e o
tremor do projetor move a tira inteira.

---

## Modelos calibrados por datasheets

Alguns modelos de grão e textura da 1.6 usam números lidos de datasheets **públicos** da Kodak. Os pontos
lidos ficam em `pelicula/data/datasheets/` com a fonte (publicação, revisão, página, figura e o SHA-256 do PDF
lido); os gráficos e os PDFs não estão no app. A Kodak avisa que esses dados são representativos e não
especificações, e o resultado continua sendo uma **aproximação**: o app não é um produto oficial e as marcas
são dos donos.

| Modelo | Ajuste | O que foi medido | Fonte |
|---|---|---|---|
| Nitidez por camada do negativo | **Diferença de nitidez entre camadas** | Curvas de MTF de cada camada: o vermelho cai mais cedo que o verde, e o verde mais cedo que o azul | KODAK VISION3 250D 5207/7207, H-1-5207, revisão 3-26, p. 3, *Modulation-Transfer Function Curves* |
| Nitidez por camada da cópia | **Diferença de nitidez entre camadas** (com cópia) | Curvas de MTF da cópia: o azul é a camada mais macia, o verde a mais nítida | KODAK VISION Color Print Film 2383/3383, H-1-2383, revisão 3-22, p. 4, figura F010_0292AC |
| Grão de cada camada do negativo | **Grão no negativo** | Granularidade rms difusa (sigma D, abertura de 48 µm) de cada camada: azul 0,0126, verde 0,0071, vermelho 0,0061 (média pela exposição) | KODAK VISION3 250D 5207/7207, H-1-5207, revisão 3-26, p. 3, *Diffuse rms Granularity Curves* |

Como a conta é feita: cada camada ganha uma gaussiana (somada em quadratura) que leva a resposta da camada mais
nítida à dela nas frequências do meio, de 20 a 62 ciclos/mm (`tools/ajustar_grao.py`). Ficam 4,3 µm no
vermelho e 2,2 µm no verde do negativo e 2,3 µm no vermelho e 4,5 µm no azul da cópia, convertidos em pixels
pelo tamanho do quadro da bitola (um quadro de 1080 linhas cobre a largura da imagem da bitola). A gaussiana
fica a menos de 8% das razões publicadas no negativo e a menos de 18% na cópia; outros filmes usam os mesmos
valores.

No **Grão no negativo**, o sigma D de cada camada vale para o 35 mm com ISO 250 (o próprio 250D) e *Tamanho* 1:
o app calcula quanto grão por pixel dá esse sigma D medido numa abertura de 48 µm (a média do grão nessa
abertura é 0,432 vezes o grão de um pixel) e a bitola, o ISO, a revelação e a *Intensidade* multiplicam como no
grão de sempre. O grão continua **procedural**: nasce dos ajustes e dessas constantes, nunca de uma análise da
sua imagem. Com o modelo *Físico*, a mesma calibração: a fração de cada camada que os grãos cobrem é escolhida para
que o sigma D na abertura de 48 µm, no cinza médio do 250D, seja o do datasheet (a conta é a exata do modelo de
discos; medido no app a 2,5% do publicado).

A **respiração por camada** também não: 100% é um ponto de copiadora de desvio, escolhido a olho.
A **halação física** (*Halação › Modelo › Física*) não é calibrada por datasheet: o raio vem da geometria do
reflexo na base e o quanto volta é escolhido para igualar o modelo *Brilho* (veja *Halação*).

---

## Cor por planos

*Frente, fundo e pele com ajustes próprios.* Chave: liga a seção. **Recurso em teste (Beta)**: aparece quando o
módulo *Cor por planos* está ligado em Configurações › Recursos (com *Mostrar recursos em teste*). Desligar o
módulo só esconde o cartão: um projeto que usa a seção sai igual.

O quadro é dividido em **frente** e **fundo** por um degradê, e a **pele** é achada pela cor. Cada parte tem os
seus ajustes, aplicados na luz da cena logo depois da exposição e do balanço (antes da vinheta, do negativo e da
cor da película): dá para escurecer e esfriar o fundo para destacar o assunto, tirar contraste e cor do que está
longe (perspectiva aérea) ou cuidar só da pele.

**Separação (degradê)** — distâncias em pixels de um quadro de 1080 linhas, a partir do centro:

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Separação** | Degradê linear, Degradê radial | Linear | Linear: uma linha separa o fundo (do lado da *Direção*) da frente. Radial: a frente fica dentro do círculo e o fundo fora. |
| **Direção** | −180° a 180° | 0° | Para que lado fica o fundo no degradê linear: 0° = em cima (céu), 90° = à direita, 180° = embaixo. |
| **Centro horizontal / vertical** | ±1920 / ±1080 px | 0 | Desloca a linha ou o círculo. |
| **Raio** | 10–2000 px | 400 px | Tamanho do círculo do degradê radial. |
| **Suavidade** | 0–2000 px | 300 px | Largura da passagem entre frente e fundo (0 = borda seca). |
| **Trocar frente e fundo** | liga/desliga | desligado | Inverte os dois lados. |

**Frente** e **Fundo** — os mesmos cinco ajustes em cada um:

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Exposição** | ±3 EV | 0 | Mais ou menos luz só nesta parte. |
| **Temperatura** / **Tonalidade** | ±100 | 0 | Balanço só nesta parte (a mesma mistura da *Entrada e exposição*). |
| **Saturação** | ±100 % | 0 | −100 % deixa a parte em preto e branco. |
| **Contraste** | ±100 % | 0 | Em torno do cinza médio, em stops (100 % = 1,5× a inclinação). |

**Pele**:

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Proteger a pele** | liga/desliga | ligado | Os ajustes da frente e do fundo não mexem na pele. |
| **Matiz** | ±30° | 0 | Negativo puxa a pele para o vermelho; positivo para o amarelo. |
| **Saturação** | ±100 % | 0 | Mais ou menos cor na pele. |
| **Luz** | ±1,5 EV | 0 | Clareia ou escurece só a pele. |
| **Uniformizar** | 0–100 % | 0 | Deixa a cor da pele mais uniforme (o matiz se aproxima da cor da pele e as manchas muito saturadas perdem cor). Só a cor: a claridade e a textura não mudam — não é um filtro de alisar. |
| **Cor da pele** *(avançado)* | 0–360° | 64,5° | O matiz que a máscara procura. O **conta-gotas** do cartão acerta este valor clicando na pele da prévia. |
| **Largura da cor da pele** *(avançado)* | 5–60° | 21° | Quanto o matiz pode se afastar da cor da pele. Estreite se madeira ou areia entrarem. |

A máscara da pele olha a cor como ela aparece (matiz, saturação e claridade no espaço OkLab) e foi acertada
para pegar todos os tons da escala Monk Skin Tone, do mais claro ao mais escuro, e deixar de fora laranja forte,
madeiras avermelhadas, areia amarelada e cinzas. Uma máscara só de cor não separa a pele de uma madeira clara ou
de uma areia da mesma cor: use o conta-gotas e a largura.

- **Prontos**: *Destacar o assunto* (radial, fundo −0,5 EV, menos cor e mais frio), *Fundo frio, pele quente*,
  *Perspectiva aérea* (fundo em cima com menos contraste e cor, um pouco mais claro e frio) e *Pele natural*
  (uniformizar 50 %). Só preenchem os ajustes.
- **Ver planos**: pinta por cima da prévia a frente em laranja, o fundo em azul e o contorno da pele. Só na
  tela: nunca vai para a exportação nem para o "Salvar quadro".
- Não entra no **LUT exportado** nem no **plugin do DaVinci** (depende do lugar e da cor de cada pixel).

---

## Zebra, falsa cor e referência (na prévia)

Para acertar a exposição antes da película, a barra da prévia tem **Falsa cor** e **Zebra**, medidas em *stops*
em relação ao cinza médio de 18% da **luz da cena** — o vídeo lido pelo *Perfil do vídeo*, com a exposição, o
balanço, a lente e a vinheta (antes da Cor por planos, do negativo e da cor da película). Faixas da falsa cor:
roxo < −6, azul −6 a −4,5, verde ±0,25 (cinza médio), rosa +0,75 a +1,25 (pele clara), amarelo +4,5 a +6 e
vermelho > +6; o resto em cinza. A zebra marca o que passa de +2,5, +4,5 (padrão) ou +6 stops. A **Referência**
fixa um quadro ou abre uma imagem para comparar em Dividido ou Lado a lado. Só na tela; detalhes em
[EDICAO.md](EDICAO.md#zebra-falsa-cor-e-referência).

---

## O que vai para um LUT exportado

*⋯ → Exportar a cor como LUT .cube* grava **só a cor**: perfil de entrada, exposição, temperatura,
tonalidade, laboratório (negativo, revelação, luzes da copiadora, cópia e processo), cor da película,
cópia, envelhecimento e LUT externo. Não cabem num LUT (porque
dependem da posição do pixel, dos vizinhos ou do tempo): grão (também o grão no negativo), respiração por
camada, halação, bloom, névoa, maciez,
nitidez, lente, vinheta, projetor, defeitos, moldura, scan e cor por planos.

A entrada do LUT é o valor do vídeo no *Perfil do vídeo* escolhido. Em S-Log3, V-Log, N-Log, F-Log, F-Log2 e
D-Log ela é o **código de 10 bits** da câmera, como nos LUTs oficiais desses fabricantes ("Full range"): no
DaVinci Resolve, ponha esses clipes em *Data Levels → Full* (Clip Attributes), como os fabricantes recomendam.
Nos outros perfis a entrada é o próprio sinal (o clipe pode ficar em *Auto/Video*).

---

## Câmera, formato e montagem (1.6)

Recursos novos da 1.6. Os de teste (Beta) começam desligados em *Configurações › Recursos*; todos começam com
a chave desligada no look, e desligados a imagem é exatamente a de antes.

### Obturador de película (Beta, recurso "Câmera de cinema")

*O rastro de movimento de uma câmera de cinema, a partir de vídeo rápido.* Chave: liga o obturador.

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Ângulo do obturador** | 45°, 90°, 144°, 172,8°, 180°, 270°, 360° | 180° | Quanto de cada quadro o obturador fica aberto: 180° = metade (1/48 s a 24 qps). Os quadros do vídeo dentro da janela aberta são misturados na luz, como a película recebia a luz. |

Só funciona quando o vídeo tem **pelo menos o dobro** dos quadros por segundo da saída (50, 60 ou 120 qps
exportados a 24, 25 ou 30). No modo Película vale na **exportação com outra taxa** (a *prévia da exportação*
mostra; a prévia da janela fica na taxa do arquivo). No modo Edição vale em cada clipe rápido numa sequência mais
lenta (e num clipe acelerado). Fica mais lento: lê e mistura 2 a 6 quadros por quadro (60 → 24 qps: 2,5×).

### Lente anamórfica (Beta)

*Desespremer, risco de luz, barril e bordas.* Chave: liga a lente.

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Desespremer** | Não, 1,33×, 1,5×, 1,8×, 2× | Não | Para vídeo filmado com lente ou adaptador anamórfico (chega espremido na horizontal): a imagem é esticada na largura do quadro e fica numa caixa de letra. 16:9 × 1,33 = 2,37:1. Com o *Scan* ligado, o quadro do negativo mostra a imagem espremida, como um scan de verdade. |
| **Risco de luz** | 0–100% | 50% | A linha horizontal comprida das luzes fortes (só na horizontal). |
| **Limiar do risco** | 0–5 stops | 2 | Quanto acima do cinza médio a luz precisa estar para riscar. |
| **Comprimento do risco** | 40–1200 px | 420 | Em px de um quadro de 1080 linhas. |
| **Cor do risco** | cor | azul | A cor do risco (o azul clássico das anamórficas). |
| **Barril horizontal** | 0–100% | 30% | O centro estica um pouco na horizontal, mais na linha do meio. |
| **Bordas macias** | 0–100% | 40% | As laterais ficam mais macias que o centro (até 6 px@1080). |

### Data impressa (Beta)

*A data laranja das câmeras dos anos 80 e 90.* Chave: liga a data.

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Ano / Mês / Dia** | 1970–2099, 1–12, 1–31 | 1998, 10, 29 | A data mostrada (não usa o relógio do computador). |
| **Formato** | '98 10 29, 10 29 '98, 29 10 '98, 1998 10 29 | '98 10 29 | A ordem dos números. |
| **Canto** | embaixo/em cima, direita/esquerda | embaixo à direita | Onde a data fica. |
| **Cor** | cor | laranja | A cor do mostrador. |
| **Intensidade** | 0–100% | 60% | Quanto o mostrador expõe o negativo: forte, ele estoura e brilha em volta. |
| **Tamanho** | 12–120 px | 34 | Altura dos números num quadro de 1080 linhas (a mesma em qualquer resolução). |
| **Distância do canto** | 0–300 px | 60 | Avançado. |

A data é **luz exposta no negativo**, como nas câmeras com data: passa pela halação (o brilho em volta), pela cor
do negativo e da cópia, e o grão fica por cima dela.

### A montagem na película (Beta)

*Os cortes da montagem viram emendas, e os rolos de Super 8 acabam.* Chave: liga.

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Emendas visíveis** | 0–100% | 70% | Em quantos cortes secos da faixa V1 a fita da emenda aparece no primeiro quadro do clipe novo. |
| **Clarão no corte** | 0–100% | 40% | A luz que passa pela junta: o primeiro quadro depois do corte clareia (um pouco o segundo). |
| **Pulo no corte** | 0–100% | 50% | A emenda pula na janela do projetor por um ou dois quadros. |
| **Rolos de Super 8** | liga/desliga | desligado | Um rolo de 50 pés tem 3 600 quadros: 3 min 20 s a 18 qps, 2 min 30 s a 24. No fim de cada rolo a luz vela a película; o rolo seguinte começa velado e com um pulo. |
| **Cadência do rolo** | 18, 24 qps | 18 | O comprimento de cada rolo. |
| **Velamento no fim do rolo** | 0–100% | 70% | A força do velamento. |
| **Cor do velamento** | cor | laranja | A cor da luz que vela. |

As emendas precisam de uma montagem (modo Edição, ou a montagem como entrada do modo Película); só os cortes secos
contam (um corte com transição não é emenda). Os rolos contam o tempo do vídeo e valem nos dois modos.

### Máquina do tempo (painel de looks)

O botão **Máquina do tempo…** (modo Película, abaixo da busca de looks) pede um **ano** (1920 a 2020) e **onde o
filme passava** (cinema, televisão ou filme caseiro) e preenche, de uma vez, bitola, sensibilidade, preto e branco
(com o filtro e a virada), cor, saturação, contraste, envelhecimento, cópia, grão, projetor, desgaste, moldura e
halação como eram na época. A janela mostra o motivo histórico e a lista do que vai mudar antes de aplicar; depois,
tudo continua editável e **Ctrl+Z** desfaz a máquina inteira de uma vez. A cadência de manivela da época (16 ou
18 qps) aparece como sugestão para o modo Edição.

### Formatos de foto

Bitolas e formatos de scan novos: **Foto 35 mm (135, 36 × 24)**, **Foto meio quadro (18 × 24)** e **Foto médio
formato (120)**; no *Scan da película*, 135 (8 furos), meio quadro (4 furos), 120 6 × 6 e 120 6 × 4,5 (sem furos).
O 135, o meio quadro e o 6 × 6 aparecem com a tira deitada, como nos scans de foto. O grão segue o tamanho do
quadro (maior quadro, grão menor: 120 < 135 < 35 mm de cinema < meio quadro).

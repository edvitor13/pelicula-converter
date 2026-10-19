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

## Ordem em que tudo acontece

```
vídeo → perfil de entrada → luz linear (gamut Rec.709) → exposição, temperatura, tonalidade
      → tremor do projetor / emendas → lente (distorção, aberração) → vinheta → [scan da película]
      → maciez (bitola, lente e MTF da película) / nitidez → névoa → bloom → halação → vazamento de luz
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
| **Bitola** | Nenhuma (manual), 8 mm, Super 8, 16 mm, Super 16, 35 mm, 65 mm, IMAX 70 mm (15/70) | 35 mm | Tamanho do quadro da película. Bitolas menores têm grão maior, menos nitidez e mais tremor. Multiplica grão, maciez, tremor, vinheta e halação e define a proporção usada por *Moldura → Da bitola escolhida* e o formato do *Scan → Da bitola escolhida*. |
| **Sensibilidade** | ISO 50, 100, 125, 200, 250, 400, 500, 800, 1600, 3200 | ISO 250 | Filmes mais sensíveis têm grão maior e mais visível: tamanho × (ISO/250)^0,18 e força × (ISO/250)^0,35. Também escolhe o código do texto de borda automático no scan. |
| **Cópia (print)** | Nenhuma (sem cópia), Kodak 2383 (cópia de cinema clássica), Kodak 2393 (mais contraste), Fuji 3513 (mais fria e neutra) | Nenhuma | Filme usado para copiar o negativo para a projeção. Aplica uma segunda curva de contraste, saturação e cor por canal por cima do negativo. |
| **Força da cópia** | 0–100% | 100% | Mistura entre o negativo e o resultado com a cópia. |
| **Desfoque da bitola** | liga/desliga | ligado | Maciez natural de cada bitola (desfoque gaussiano). Em 1080p: 8 mm 2,4 px, Super 8 1,9 px, 16 mm 1,1 px, Super 16 0,9 px, 35 mm 0,35 px, 65 mm e IMAX nenhum (em 4K, o dobro). Desligado, o vídeo mantém a nitidez original; *Lente e nitidez → Recuperar detalhe* devolve ainda mais detalhe. |
| **Intensidade do desfoque** | 0–100% | 100% | Quanto desse desfoque é aplicado (100% = o natural da bitola; 0% = nenhum). Chave `bitola_resolucao`. |
| **Vinheta da bitola** | 0–100% | 100% | Escurecimento natural das bordas em bitolas pequenas. Vale mesmo com a seção *Lente* desligada. |
| **MTF da película (maciez fina)** | Desligado, Close (rosto), Plano médio, Plano aberto, Textura 16 mm, Textura Super 8 | Desligado | A resposta de detalhe (MTF) de um filme: tira a nitidez "digital" demais (poros, serrilhado) e mantém o detalhe maior. Escolha pelo enquadramento — o close suaviza mais a pele, o plano aberto menos. É uma gaussiana fina somada em quadratura com o desfoque da bitola e a maciez da lente: σ em 1080p = 1,6 / 1,1 / 0,7 / 1,5 / 2,3 px × 2 × *Quantidade*. Chave `mtf`. |
| **Quantidade do MTF** | 0–100% | 50% | 50% = o valor do enquadramento escolhido; 100% = o dobro. Chave `mtf_forca`. |
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
| **Perfil do vídeo** | veja abaixo | Rec.709 / sRGB (vídeo comum) | Como o vídeo foi gravado. O app desfaz a curva e o gamut da câmera para trabalhar em luz linear. Use o perfil log da câmera se gravou em log. |
| **Exposição** | −3 a +3 EV | 0 EV | Mais ou menos luz, antes de qualquer curva (como abrir ou fechar o diafragma). |
| **Temperatura** | −100 a +100 | 0 | Negativo esfria, positivo esquenta. Em +100: vermelho +0,28 EV e azul −0,38 EV. |
| **Tonalidade** | −100 a +100 | 0 | Negativo puxa para verde, positivo para magenta. Em +100: verde −0,22 EV, vermelho e azul +0,08 EV. |

Perfis disponíveis:

| Perfil | Curva | Gamut convertido para Rec.709 | Quando usar |
|---|---|---|---|
| Rec.709 / sRGB (vídeo comum) | curva neutra de exibição do app (inversível) | Rec.709 | Celular, câmeras em modo normal, vídeos da internet. |
| Linear | nenhuma | Rec.709 | EXR e arquivos já lineares. |
| Nikon N-Log | N-Log | Rec.2020 | Nikon Z gravando em N-Log. |
| Sony S-Log3 (S-Gamut3.Cine) | S-Log3 | S-Gamut3.Cine | Sony em S-Log3 / S-Gamut3.Cine. |
| ARRI LogC3 (EI 800) | LogC3 EI 800 | ARRI Wide Gamut 3 | ARRI Alexa (LogC3). |
| Panasonic V-Log | V-Log | V-Gamut | Panasonic Lumix/Varicam em V-Log. |
| RED Log3G10 (RWG) — R3D, Nikon N-RAW e R3D NE | Log3G10 | REDWideGamutRGB | RED R3D e Nikon N-RAW convertidos no DaVinci Resolve. |
| DaVinci Intermediate (DaVinci Wide Gamut) | DaVinci Intermediate | DaVinci Wide Gamut | Arquivos exportados do Resolve em DWG/Intermediate. |
| Cineon / DPX log | Cineon (685/300) | Rec.709 | Scans de película em DPX/Cineon. |
| Blackmagic Film Gen 5 (Blackmagic Wide Gamut) | Blackmagic Film Gen 5 | Blackmagic Wide Gamut | Câmeras Blackmagic (BRAW e ProRes em *Film*, geração 5). |
| ARRI LogC4 (ARRI Wide Gamut 4) | LogC4 | ARRI Wide Gamut 4 | ARRI Alexa 35 (LogC4). |
| Apple Log (Rec.2020) — iPhone | Apple Log | Rec.2020 | iPhone 15 Pro e mais novos gravando em Apple Log. |

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
comportamento de cada um, sem dados nem curvas dos fabricantes.

| Ajuste | Faixa | Padrão | O que faz |
|---|---|---|---|
| **Negativo** | Kodak Vision3 50D, Vision3 250D, Vision3 200T, Vision3 500T, Fujifilm Eterna 250D, Eterna Vivid 500, Eastman EXR 5248 (anos 90), Eastman 5247 ECN-II (anos 70), Kodak Vision2 5201 50D, Eastman ECN-II 5297 250D, Kodak Vision 5246 250D, Kodak Vision 5263 500T, Kodak Vision2 Expression 5229 500T, Kodak Double-X 5222 (P&B) | Vision3 250D | Filme da câmera: latitude (onde ficam o pé e o ombro), contraste de cada camada, mistura de cores entre as camadas e efeito entre camadas (que satura os filmes modernos). Double-X é preto e branco pancromático. |
| **Revelação (puxar / forçar)** | −2 a +3 stops | 0 | Revelação forçada (+): mais contraste, sombras mais fechadas e grão maior (× 1,15 por stop). Puxada (−): o contrário. Cada stop muda o gama do negativo em 12%. |
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
| **O LUT espera** | Rec.709 (LUTs criativos, Premiere), Cineon log (LUTs de cópia do Resolve), ARRI LogC3, Sony S-Log3, Nikon N-Log, Panasonic V-Log, RED Log3G10 (RWG), DaVinci Intermediate (DWG), Blackmagic Film Gen 5, ARRI LogC4, Apple Log, Linear | Rec.709 | Em que espaço o LUT foi feito. O app converte a imagem para esse espaço (curva e gamut) antes de consultar o LUT. LUTs de cópia do Resolve (Kodak 2383 etc.) esperam Cineon; os do Premiere esperam Rec.709. |
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

O grão é ruído gaussiano gerado na GPU numa grade do tamanho do grão e ampliado com interpolação
bicúbica, então tem forma arredondada (não é ruído de pixel). Ele é aplicado depois da curva de
cor, com resposta por luminância (picos em 10%, 45% e 88% de brilho). Em prévias reduzidas, grãos
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

O halo é calculado só pela luminância das luzes e tingido pela cor escolhida. Com o *Scan da
película* ligado, só a área da imagem emite halação (os furos iluminados não).

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
| **Película** | Da bitola escolhida, 35 mm (4 furos por quadro), 16 mm (1 furo), Super 16, Super 8 | Da bitola escolhida | Medidas reais de cada película: furos, linhas entre quadros e bordas. *Da bitola*: 8 mm e Super 8 → Super 8; 16 mm → 16 mm; Super 16 → Super 16; 35 mm, 65 mm, IMAX e Nenhuma → 35 mm. |
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

## O que vai para um LUT exportado

*⋯ → Exportar a cor como LUT .cube* grava **só a cor**: perfil de entrada, exposição, temperatura,
tonalidade, laboratório (negativo, revelação, luzes da copiadora, cópia e processo), cor da película,
cópia, envelhecimento e LUT externo. Não cabem num LUT (porque
dependem da posição do pixel, dos vizinhos ou do tempo): grão, halação, bloom, névoa, maciez,
nitidez, lente, vinheta, projetor, defeitos, moldura e scan.

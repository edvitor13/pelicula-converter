# Modo Edição — guia rápido

O PeliculaConverter tem dois modos, escolhidos no topo da janela:

| Modo | Para quê | Atalho |
|---|---|---|
| **Película** | Aplicar o look de película (cor do negativo e da cópia, grão, halação, bitola, scan…) | Ctrl+1 |
| **Edição** | Montar o vídeo: cortar, juntar clipes, ajustar cor, luz, enquadramento, velocidade e som | Ctrl+2 |

A ideia é simples: **primeiro você monta e corrige no modo Edição; depois o modo Película aplica o look
em cima da montagem**. A exportação usa a montagem inteira (ou o trecho marcado com entrada e saída).
Se você só abriu um arquivo e não mexeu em nada na edição, o modo Película trabalha direto com o arquivo,
exatamente como antes.

O modo Edição foi feito para o básico ser fácil — sem nós, sem páginas, sem dezenas de janelas.

---

## 1. A tela da edição

```
┌──────────┬─────────────────────────────────────────────┬───────────────┐
│  MÍDIA   │                 prévia                       │    CLIPE      │
│ (seus    │                                              │ (ajustes do   │
│ arquivos)│      ◀ ▶  ⏯   00:00:12:05                   │  clipe        │
│          ├─────────────────────────────────────────────┤  escolhido)   │
│          │  ferramentas da linha do tempo               │               │
│          │  V2 ▕▔▔▔▔▔▔▔▔▔▔▔▏                             │               │
│          │  V1 ▕▔▔▔▔▔▔▔▏▕▔▔▔▔▔▔▔▔▔▔▏                   │               │
│          │  A1 ▕∿∿∿∿∿∿∿▏▕∿∿∿∿∿∿∿∿∿∿▏                   │               │
└──────────┴─────────────────────────────────────────────┴───────────────┘
```

- **Mídia** (esquerda): os arquivos importados — vídeos, imagens e músicas (MP3, WAV, AAC, FLAC…).
- **Prévia** (centro): mostra a montagem no ponto do cursor. A opção **Com película / Sem película**
  liga ou desliga o look de película na prévia enquanto você edita.
- **Linha do tempo** (embaixo): as faixas de vídeo (V1, V2…) ficam em cima e as de áudio (A1, A2…)
  embaixo. A faixa **V2 aparece por cima da V1** na imagem.
- **Clipe** (direita): todos os ajustes do clipe selecionado.

## 2. Montar

1. Clique em **Importar…** (Ctrl+I): os arquivos entram na lista de mídia **e** vão para o fim da
   montagem (músicas começam no início, na primeira faixa de áudio livre). Arrastar arquivos para a
   lista de mídia só os guarda ali; arrastar direto para a linha do tempo põe no ponto e na faixa do mouse.
2. Arraste um item da lista para a linha do tempo, na faixa e no ponto que quiser — ou dê **dois cliques**
   nele (vai para o fim da montagem).
3. Vídeos com som entram como **dois clipes ligados** (imagem em V1 e som em A1): mover, cortar ou apagar
   um mexe no outro junto. Para separar, use **Desligar** na barra da linha do tempo.

Colocar um clipe por cima de outro na mesma faixa **substitui** a parte coberta (como em qualquer editor).
Para sobrepor sem apagar, use outra faixa (V2).

### Mexer nos clipes

| Ação | Como |
|---|---|
| Selecionar | Clique no clipe (Ctrl+clique soma ou tira; Shift+clique soma) |
| Mover | Arraste o meio do clipe (para os lados e para outra faixa do mesmo tipo) |
| Aparar o começo / o fim | Arraste a borda esquerda / direita do clipe |
| Cortar no cursor | **Dividir** (S): corta os selecionados — ou tudo sob o cursor, se nada estiver selecionado |
| Cortar onde clicar | Ferramenta **Lâmina** (B) e clique no clipe; volte com **Selecionar** (V) |
| Apagar | **Excluir** (Delete) deixa o espaço vazio |
| Apagar e juntar | **Excluir e fechar o espaço** (Shift+Delete) puxa o que vem depois |
| Juntar os clipes da faixa | Botão direito → **Remover espaços da faixa** |
| Ímã | Liga/desliga com **N**: os clipes grudam no cursor, nas bordas dos outros e na entrada/saída. Segure **Shift** enquanto arrasta para inverter o ímã naquele momento |
| Zoom | **+ / −**, Ctrl + roda do mouse, o controle de zoom ou **Ajustar** (sequência inteira) |
| Rolar | Roda do mouse (para os lados); Shift + roda (para cima e para baixo) |
| Ir para um ponto | Clique ou arraste na régua de tempo |

### Faixas

Cada faixa tem botões no cabeçalho:

- **olho** (vídeo): esconde a faixa;
- **alto-falante** (áudio): silencia a faixa;
- **fones** (áudio): *solo* — só as faixas em solo tocam;
- **cadeado**: trava a faixa (nada muda nela);
- **barrinha de volume** (áudio): arraste para mudar o volume da faixa; dois cliques voltam a 0 dB.

**+ Vídeo** e **+ Áudio** criam faixas novas. Arrastar um clipe de vídeo para cima da última faixa de
vídeo também cria uma faixa nova. Para apagar uma faixa: botão direito nela → **Remover esta faixa**.

## 3. Ajustar o clipe (painel "Clipe")

Selecione um clipe e use o painel da direita. Quando o vídeo tem som ligado, escolha **Imagem** ou **Som**
no topo do painel.

### Ajustes rápidos

Um clique resolve o mais comum:

- **Automático**: corrige exposição, contraste e balanço de branco olhando o quadro atual.
- **Mais vivo**, **Quente**, **Frio**, **Suave**, **Contraste**, **Preto e branco**, **Antigo**.
- **Restaurar cor**: volta a cor e a luz ao original (o enquadramento e a velocidade ficam).
- **Copiar ajustes / Colar / Aplicar a todos**: leva a cor e a luz de um clipe para outros — ótimo para
  deixar todas as cenas iguais.

### Imagem

| Seção | O que faz |
|---|---|
| **Luz** | Exposição (em EV, como o diafragma), contraste, realces, sombras, brancos, pretos e brilho dos tons médios |
| **Cor** | Temperatura e tonalidade (balanço de branco), vibração (satura as cores apagadas e protege a pele), saturação (−100% = preto e branco) e matiz |
| **Rodas de cor** | Três rodas — sombras, tons médios e altas luzes. Arraste o ponto na direção da cor; quanto mais longe do centro, mais forte. Dois cliques zeram; Shift + arrastar faz ajuste fino. Cada roda tem também um controle de luz |
| **Curva de tons** | Ajuste fino por faixa de brilho: realces, claros, escuros e sombras |
| **Cor por faixa (HSL)** | Mude uma cor sem mexer nas outras: escolha a bolinha (vermelhos, laranjas, amarelos, verdes, cianos, azuis, roxos, magentas) e ajuste matiz, saturação e luminância. Bolinhas com um pontinho já têm ajuste |
| **Detalhe** | Nitidez, clareza (contraste local: realça textura ou suaviza a pele), desfoque e redução de ruído |
| **Efeitos** | Vinheta (escurece ou clareia as bordas) e desbotar (pretos lavados, como foto antiga) |
| **Enquadrar e posicionar** | Encaixe no quadro (inteiro com barras, preencher ou esticar), escala, posição, rotação, espelhar, cortes nas bordas, opacidade e mesclagem com a faixa de baixo (tela, multiplicar, sobrepor…) |
| **Velocidade** | Câmera lenta (abaixo de 1×), acelerado (acima de 1×) e **congelar quadro**. A duração do clipe muda junto, e o som ligado acompanha |
| **Transições** | Entrada: corte seco, **dissolver com o clipe anterior**, surgir do preto ou do branco. Saída: corte, sumir no preto, no branco ou mostrar a faixa de baixo. Cada uma com a sua duração |

> **Dissolver** mistura o começo deste clipe com o fim do clipe anterior da mesma faixa (encostado nele).
> Para a mistura ficar bonita, o clipe anterior precisa ter um pouco de vídeo sobrando depois do corte.

### Som

| Seção | O que faz |
|---|---|
| **Som** | Volume (dB), mudo, balanço esquerda/direita, aumentar no início (fade in) e diminuir no fim (fade out) |
| **Equalizar e limpar** | Graves, médios e agudos; **Realçar voz** (fala mais clara); redução de ruído (chiado e zumbido); normalizar volume |
| **Velocidade** | Acompanha o vídeo ligado (o tom da voz é preservado) |

A forma de onda aparece dentro dos clipes de áudio e já mostra o volume e os fades.

## 4. Sequência

**Sequência…** abre o tamanho e o ritmo do vídeo montado:

- **Resolução**: 4K, 2K, Full HD, HD, **vertical 1080 × 1920** (Reels, TikTok, Shorts), quadrado, retrato 4:5,
  igual ao primeiro clipe ou personalizada;
- **Quadros por segundo**: 23,976 / 24 / 25 / 29,97 / 30 / 50 / 59,94 / 60 — mudar mantém o tempo dos cortes;
- **Cor do fundo**: o que aparece onde não há imagem (barras, clipes menores que o quadro).

## 5. Monitores

Acima dos ajustes há um monitor com quatro vistas:

- **Histograma**: quantos pixels há em cada nível de brilho;
- **Onda** (forma de onda): o brilho de cada coluna da imagem — 0% embaixo, 100% em cima. Ótimo para ver
  se os brancos estouraram ou os pretos amassaram;
- **RGB** (parada): a forma de onda do vermelho, do verde e do azul lado a lado — se as três estão na mesma
  altura num objeto branco ou cinza, o balanço de branco está certo;
- **Vetor** (vetorscópio): o ângulo é a cor e a distância do centro é a saturação. A linha tracejada é o
  **tom de pele**: rostos bem corrigidos ficam perto dela.

## 6. Depois da edição

- Vá para o modo **Película** (Ctrl+1) para escolher o look; a prévia já mostra a montagem.
- **Exportar** (Ctrl+E) grava a montagem inteira ou o trecho entre a entrada (I) e a saída (O), com o som
  mixado de todas as faixas. A resolução das qualidades (1080p, 720p, 4K…) vale para o lado menor: uma
  sequência vertical 1080 × 1920 exportada em *Redes sociais 1080p* continua 1080 × 1920.
- Em **Plataforma** (YouTube, Instagram, TikTok, WhatsApp…) a janela de exportação preenche o quadro, o som
  e os limites. Uma montagem de outra proporção entra no quadro da plataforma cortada, com bordas pretas
  ou sobre um fundo desfocado, sempre com o look desenhado no quadro final; o **volume alvo** mede e acerta
  o som mixado. A **área segura** (botão na barra da prévia) mostra onde a interface do TikTok, do Reels ou
  do Shorts cobre o vídeo vertical — só na tela, nunca no arquivo.
- **Projeto → Salvar** (Ctrl+S) guarda a edição no arquivo `.plc` junto com o look. Se um arquivo usado na
  edição mudar de lugar, o app pergunta onde ele está ao abrir o projeto.

## 7. Atalhos do modo Edição

| Tecla | Ação |
|---|---|
| Ctrl+1 / Ctrl+2 | Modo Película / modo Edição |
| Ctrl+I | Importar mídia |
| Espaço | Reproduzir / pausar |
| ← / → | Quadro anterior / próximo (Shift: 1 segundo) |
| I / O | Marcar entrada / saída |
| S | Dividir no cursor |
| B / V | Ferramenta Lâmina / Selecionar |
| Delete | Excluir os clipes selecionados |
| Shift+Delete | Excluir e fechar o espaço |
| N | Ímã liga/desliga (Shift ao arrastar inverte) |
| + / − | Aproximar / afastar a linha do tempo |
| Ctrl+A | Selecionar todos os clipes (com a linha do tempo em foco) |
| Esc | Tirar a seleção e voltar para Selecionar |
| Ctrl+Z / Ctrl+Y | Desfazer / refazer a edição |
| Ctrl+Alt+C / Ctrl+Alt+V | Copiar / colar os ajustes de cor |

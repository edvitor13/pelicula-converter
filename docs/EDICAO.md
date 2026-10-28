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

Colocar um clipe por cima de outro na mesma faixa **substitui** a parte coberta (como em qualquer editor) —
é o modo **sobrescrever**, o padrão. Para sobrepor sem apagar, use outra faixa (V2).

### Inserir em vez de sobrescrever

Com o botão **Inserir** ligado (na barra da linha do tempo, ao lado do ímã), soltar um arquivo ou mover um
clipe **empurra o que vem depois** em vez de cobrir. Segurar **Ctrl** ao soltar (ou ao terminar de arrastar)
faz o contrário do botão naquele momento; a linha do ponto de inserção ganha setas para a direita.

- O clipe que estiver no ponto é **dividido** ali (imagem e som juntos) e a parte da direita anda.
- Tudo o que começa no ponto ou depois anda, **em todas as faixas destravadas**, com os sons ligados — assim
  nada sai de sincronia. Os marcadores depois do ponto andam junto.
- O que **atravessa** o ponto em outra faixa (uma música de fundo, um título longo) continua inteiro.
- Faixas **travadas** não mudam (e, se algo travado ficou depois do ponto, os marcadores ficam onde estão).
- Mover inserindo deixa vazio o lugar de onde o clipe saiu (use **Excluir e fechar o espaço** ou a faixa
  magnética para fechar).

Na lista de **Mídia**, o botão direito num item (ou nos escolhidos) tem **Inserir no cursor** (tecla **,**)
e **Sobrescrever no cursor** (tecla **.**): o arquivo entra no cursor, na V1 e na A1, e o cursor vai para o
fim dele (para encaixar o próximo). As teclas valem com o modo Edição aberto, para os itens escolhidos na
Mídia.

### Faixa principal magnética

Em **Sequência… → Montagem**, a opção **Faixa principal magnética** (desligada por padrão, também em
projetos novos) deixa a **V1 sempre sem buracos**:

- apagar, aparar ou mover um clipe da V1 **fecha o espaço** (até sem "fechar o espaço");
- alongar um clipe da V1 (borda, velocidade mais lenta) e soltar algo no meio dela **empurram** o resto em
  vez de cobrir;
- o que está nas outras faixas (títulos, imagens, efeitos de som, músicas) **acompanha a imagem da V1 que
  estava embaixo do começo dele**: se você move um clipe da V1, o título em cima dele vai junto; se a imagem
  embaixo foi apagada, ele vai para o ponto do corte. O que você mesmo mexeu fica onde você deixou, e nada
  cobre nada (se o lugar estiver ocupado, o clipe anda para a direita até caber);
- os marcadores acompanham a imagem da V1 do mesmo jeito.

Um ímã aparece no cabeçalho da V1 enquanto ela é magnética. Com a V1 **travada**, a regra espera (nada se
fecha). Desligada, a linha do tempo volta a ser livre (nada muda de lugar ao desligar).

### Aparar até o cursor (Q / W)

**Q** tira o começo do clipe até o cursor e **W** tira o fim a partir do cursor, **fechando o espaço** (o que
vem depois anda para a esquerda). Vale o clipe sob o cursor **na faixa do clipe selecionado**; sem seleção,
o da faixa destravada mais de cima (V mais alta, V1, depois A1…). O som ligado vai junto. Com **Q**, o cursor
vai para o novo começo do clipe — o quadro que estava na tela continua na tela. Como em *Excluir e fechar o
espaço*, as outras faixas só andam se nada delas atravessa o trecho tirado.

### Cortes J e L (som antes ou depois da imagem)

Num corte entre dois clipes de vídeo com som ligado, o botão direito (perto do corte: metade esquerda do
clipe = corte do começo, metade direita = corte do fim) tem:

- **Corte J**: o som do clipe seguinte entra **1 s antes** da imagem dele;
- **Corte L**: o som do clipe anterior **continua 1 s** depois do corte da imagem;
- **Alinhar o som com o corte da imagem**: volta ao corte reto.

Só o corte do som anda (um som cresce e o vizinho encolhe); a imagem fica igual. Cabe só o que sobra do
arquivo além do corte — se faltar, o app avisa quanto coube. Para ajustar à mão, segure **Alt** enquanto
arrasta a borda de um clipe: só ele muda (só a imagem ou só o som), sem o ligado. Os pares com entrada ou
saída diferentes continuam ligados: mover, dividir, apagar e mudar a velocidade mantêm a imagem e o som em
sincronia (na velocidade, a diferença muda na proporção).

**Transparência**: vídeos e imagens com canal alfa — ProRes 4444 (como o recorte `_cutout.mov` do
CorridorKey), PNG com transparência (inclusive com paleta) e WebM VP8/VP9 com alfa — deixam ver o que está
nas faixas de baixo, ou a cor de fundo da sequência. A opacidade, o corte, as transições e os modos de
mesclagem respeitam o recorte, e a borda continua limpa ao reduzir, girar ou ampliar. Aberto direto no modo
Película, um arquivo assim sai sobre a cor de fundo da sequência (preto, se você não mudou). O vídeo
exportado não tem transparência (sai sempre com a cor por baixo), e sequências de imagens ainda não entram.

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

### Marcadores e capítulos

Marcadores são lembretes no tempo da montagem (não presos a um clipe), desenhados na régua com a sua cor.

| Ação | Como |
|---|---|
| Pôr um marcador no cursor | **M** (ou o botão **Marcador** na barra, ou botão direito na régua → **Adicionar marcador aqui**) |
| Ver o nome e a nota | Pare o mouse sobre o marcador |
| Editar | **Dois cliques** no marcador: nome, nota, cor (8 cores) e **Capítulo** |
| Mover | Arraste o marcador na régua (clique simples leva o cursor até ele) |
| Apagar | Clique no marcador e **Delete**, ou botão direito → **Remover marcador** |
| Ir para o próximo / anterior | **Shift+↓ / Shift+↑** (também no modo Película) |

Mover, aparar e dividir clipes não mexe nos marcadores. **Excluir e fechar o espaço** em todas as faixas
puxa os marcadores que vêm depois junto com os clipes (os que estavam no trecho apagado vão para o ponto
do corte). Mudar os quadros por segundo mantém o tempo deles. No modo Película, a barra de tempo mostra os
marcadores da montagem (clique num deles para ir até lá).

**Capítulos**: ligue **Capítulo** num marcador e ele vira um capítulo do vídeo (capítulo sem nome se
chama "Capítulo 1", "Capítulo 2"…).

- **Copiar capítulos para o YouTube…** (botão de marcadores e capítulos na barra ou botão direito na
  régua) mostra o texto `00:00 Abertura` para colar na descrição do vídeo e confere as regras do YouTube:
  o primeiro capítulo em 00:00, pelo menos 3 capítulos e cada um com 10 segundos ou mais. Se algo não
  bate, a janela diz o quê.
- Ao exportar em **MP4, MOV ou MKV**, a opção **Incluir capítulos** (ligada quando há capítulos) grava os
  capítulos no arquivo; os players mostram a lista de capítulos. Exportando só um trecho (entrada e saída),
  os tempos contam a partir da entrada.

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
| **Velocidade** | Câmera lenta (abaixo de 1×), acelerado (acima de 1×) e **congelar quadro**. A duração do clipe muda junto, e o som ligado acompanha. No fim do cartão: **Reverso** e **Rampa de velocidade** (veja *Tempo do clipe*, abaixo) |
| **Transições** | Entrada: corte seco, **dissolver com o clipe anterior**, surgir do preto ou do branco. Saída: corte, sumir no preto, no branco ou mostrar a faixa de baixo. Cada uma com a sua duração |

> **Dissolver** mistura o começo deste clipe com o fim do clipe anterior da mesma faixa (encostado nele).
> Para a mistura ficar bonita, o clipe anterior precisa ter um pouco de vídeo sobrando depois do corte.

### Animar com chaves (losangos)

Todo ajuste que pode mudar ao longo do clipe (luz, cor, rodas, enquadramento, opacidade, volume…) tem um
**losango** ao lado do nome:

- **Clique no losango** grava uma chave no cursor com o valor atual. O losango fica **cheio** quando há uma
  chave exatamente no cursor, **vazado** quando o ajuste está animado (com chaves em outro ponto) e **apagado**
  quando o ajuste é fixo. Fora do clipe (cursor antes ou depois dele) o losango fica desligado.
- Depois que um ajuste tem chaves, **mexer no controle grava uma chave no cursor** (chave automática, como no
  Resolve). Um arraste inteiro do slider é um passo só do desfazer.
- As **setas ◀ ▶** ao lado do losango levam o cursor à chave anterior / seguinte desse ajuste.
- **Botão direito no losango**: a **curva até a próxima chave** (linear, suavizar a entrada, suavizar a saída,
  suavizar as duas), apagar a chave do cursor ou **limpar a animação** (o ajuste volta a ser fixo).
- Os controles mostram o valor **no cursor** e acompanham a reprodução.

Na **linha do tempo**, as chaves do clipe escolhido aparecem como losangos no corpo dele (de todos os ajustes
juntos; parar o mouse em cima diz quais). **Clique** leva o cursor até a chave; **arrastar** move a chave no
tempo (gruda no cursor e fica dentro do clipe); **Shift** ou **Alt** escolhe várias; **Delete** apaga as
chaves escolhidas (antes dos clipes); **Esc** tira a escolha. Cada ação é um passo do desfazer.

As chaves andam com o clipe: mover, aparar, dividir e mudar a velocidade mantêm cada chave no mesmo ponto da
imagem. Ao pôr ou tirar uma rampa, ou ligar o reverso, as chaves ficam na mesma fração do tempo do clipe (um
aumento de luz no começo continua no começo).

### Tempo do clipe: rampa, reverso e congelar

**Rampa de velocidade** (cartão *Velocidade* do clipe, ou botão direito no clipe → *Rampa de velocidade*):
escolha a forma e clique em **Aplicar rampa**.

| Forma | O que faz |
|---|---|
| **Acelerar** | Normal na primeira metade, rápido na segunda |
| **Desacelerar** | Normal na primeira metade, câmera lenta na segunda |
| **Impacto (rápido–lento–rápido)** | Rápido, câmera lenta no meio, rápido de novo — o clássico do esporte |
| **Câmera lenta no meio** | Normal, câmera lenta no meio, normal |
| **Entrada em câmera lenta** | Começa em câmera lenta e volta ao normal |
| **Saída em câmera lenta** | Normal e termina em câmera lenta |

- **Intensidade**: quanto o trecho lento fica lento e o rápido fica rápido (50% = 2,5× e 0,4×; 100% = 4× e
  0,25×). **Transição**: quanto tempo (em segundos do vídeo) leva cada mudança de velocidade.
- A rampa vale para o trecho do vídeo que o clipe mostra: ele continua mostrando o mesmo começo e o mesmo
  fim, e a **duração muda** (sem cobrir o clipe seguinte nem passar do fim do arquivo; na faixa principal
  magnética, o resto anda). A *Velocidade* do clipe multiplica a rampa.
- A rampa fica **presa à imagem**: aparar, dividir, mover e mudar a velocidade mantêm o trecho lento no mesmo
  pedaço do vídeo. **Tirar a rampa** volta à velocidade constante (e à duração de antes).
- **O som acompanha** quadro a quadro, sem mudar o tom (o app troca a velocidade do som em pedaços curtos e
  cruza um no outro). Em trechos muito rápidos (4×) sons curtos podem ficar borrados, como em qualquer editor.
- Imagens paradas e clipes com *Congelar quadro* não têm rampa. O rótulo do clipe mostra *rampa*.

**Reverso** (cartão *Velocidade* ou botão direito no clipe): o clipe toca **do fim para o começo**, com o mesmo
trecho e a mesma duração. O som ligado do mesmo arquivo também toca ao contrário, junto com a imagem; uma
música ligada de outro arquivo continua como está. Combina com a velocidade e com a rampa — como a rampa fica
presa à imagem, uma *entrada em câmera lenta* vira uma saída lenta no reverso. Num corte J/L, o som que sobrava
depois da imagem passa a vir antes dela (sem cobrir o clipe de som anterior). O rótulo mostra *reverso*.

**Congelar este quadro** (botão direito no clipe → *Congelar este quadro…*, ou **Shift+F** com o cursor sobre
o clipe): divide o clipe no cursor e põe ali o **quadro do cursor parado** por 2 segundos (o menu pergunta a
duração e o Shift+F usa a última escolhida). O quadro parado leva a cor e o enquadramento daquele instante.

- Com o botão **Inserir** ligado, o resto do clipe (e tudo o que vem depois) anda para a direita.
- Com ele desligado (sobrescrever), o quadro parado cobre os próximos segundos do clipe e o resto fica onde
  estava.
- O som ligado fica em **silêncio** enquanto a imagem está parada e continua em sincronia depois.
- É um passo só do desfazer. A caixa **Congelar quadro** do cartão continua igual (congela o clipe inteiro no
  primeiro quadro).

### Som

| Seção | O que faz |
|---|---|
| **Som** | Volume (dB), mudo, balanço esquerda/direita, aumentar no início (fade in), diminuir no fim (fade out) e **transição com o anterior** |
| **Equalizar e limpar** | Graves, médios e agudos; **Realçar voz** (fala mais clara); redução de ruído (chiado e zumbido); normalizar volume |
| **Velocidade** | Acompanha o vídeo ligado (o tom da voz é preservado) |

A forma de onda aparece dentro dos clipes de áudio e já mostra o volume e os fades.

**Transição de som** (potência constante): botão direito perto do corte entre dois clipes de som colados
na mesma faixa → **Transição de som (potência constante)**. Ela nasce com 1 segundo, centrada no corte,
e a duração se ajusta em **Transição com o anterior** no clipe da direita (até 5 s). Um some enquanto o
outro aparece, nas curvas seno e cosseno, e o volume total não cai no meio (como cairia num fade comum).
Para isso ela usa o som do arquivo **além do corte** — o que sobra depois do fim do clipe da esquerda e
antes do começo do da direita. Sem sobra de um lado, ela fica toda do outro; sem sobra nenhuma, não cabe
(o app avisa: apare um dos clipes). A transição aparece como um X sobre o corte; desmarque no mesmo menu
para tirar. Os fades dos dois clipes nesse corte são zerados, porque a transição faz o papel deles.

**Fades curtos nas emendas**: onde um clipe de som começa ou termina no meio do arquivo, o app põe um fade
de 5 ms, que não se ouve como fade mas tira o estalo do corte. Não vale onde o clipe já tem um fade maior
ou uma transição, nem num corte que não foi mexido (o som continua igual). Liga e desliga em
**Sequência…**; projetos novos começam ligados e projetos das versões anteriores continuam como eram
(desligados), para soar exatamente igual.

## 4. Sequência

**Sequência…** abre o tamanho e o ritmo do vídeo montado:

- **Resolução**: 4K, 2K, Full HD, HD, **vertical 1080 × 1920** (Reels, TikTok, Shorts), quadrado, retrato 4:5,
  igual ao primeiro clipe ou personalizada;
- **Quadros por segundo**: 23,976 / 24 / 25 / 29,97 / 30 / 50 / 59,94 / 60 — mudar mantém o tempo dos cortes;
- **Cor do fundo**: o que aparece onde não há imagem (barras, clipes menores que o quadro);
- **Fades curtos nas emendas de som**: veja *Som*, acima;
- **Faixa principal magnética**: veja *Montar*, acima.

## 5. Monitores

Acima dos ajustes há um monitor com quatro vistas:

- **Histograma**: quantos pixels há em cada nível de brilho;
- **Onda** (forma de onda): o brilho de cada coluna da imagem — 0% embaixo, 100% em cima. Ótimo para ver
  se os brancos estouraram ou os pretos amassaram;
- **RGB** (parada): a forma de onda do vermelho, do verde e do azul lado a lado — se as três estão na mesma
  altura num objeto branco ou cinza, o balanço de branco está certo;
- **Vetor** (vetorscópio): o ângulo é a cor e a distância do centro é a saturação. A linha tracejada é o
  **tom de pele**: rostos bem corrigidos ficam perto dela.

### Medidor de som

Ao lado da prévia (nos dois modos) fica o medidor do som que está tocando:

- **Barras L e R**: o pico de cada canal em dBFS (de −60 a 0). O traço fica 1,5 s no maior pico, e a luz
  no topo acende se o som chegou a 0 dBFS (clique no medidor para apagar).
- **M**, **S** e **I**: o volume percebido (loudness EBU R128, em LUFS) — momentâneo (0,4 s), de curto
  prazo (3 s) e integrado desde o play. **TP**: o maior *true peak* (dBTP).
- Referências: cerca de **−14 LUFS** para YouTube e Spotify e **−23 LUFS** para TV, com picos abaixo de
  **−1 dBTP**.

A medição recomeça a cada play, ao pular para outro ponto e na volta do loop (ou com um clique no
medidor). No modo Película, o som do arquivo é preparado uma vez em segundo plano ("preparando…") antes
de o medidor andar. O medidor só mede a prévia: nada dele vai para a exportação. Para escondê-lo,
desligue **Medidor de som** em Configurações › Recursos.

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
- Com marcadores de capítulo, a exportação em MP4, MOV ou MKV grava os capítulos no arquivo
  (**Incluir capítulos**); para o YouTube, use **Copiar capítulos para o YouTube…**.

## 7. Atalhos do modo Edição

| Tecla | Ação |
|---|---|
| Ctrl+1 / Ctrl+2 | Modo Película / modo Edição |
| Ctrl+I | Importar mídia |
| Espaço | Reproduzir / pausar |
| J / K / L | Para trás / pausar / para a frente; de novo no mesmo sentido: 2×, 4×, 8× (também no modo Película) |
| K + J / K + L | Segurando o K: um quadro para trás / para a frente |
| ← / → | Quadro anterior / próximo (Shift: 1 segundo) |
| I / O | Marcar entrada / saída |
| Ctrl+L | Repetir liga/desliga (antes era o L) |
| S | Dividir no cursor |
| Q / W | Aparar o começo / o fim do clipe até o cursor e fechar o espaço |
| , / . | Inserir / sobrescrever no cursor (itens escolhidos na Mídia) |
| Ctrl ao soltar ou mover | Inverte o botão Inserir naquele momento |
| Alt ao aparar | Só a imagem ou só o som do par ligado (corte J/L à mão) |
| B / V | Ferramenta Lâmina / Selecionar |
| Delete | Excluir as chaves escolhidas na linha do tempo; sem elas, os clipes selecionados (ou o marcador selecionado) |
| Shift+F | Congelar o quadro do cursor (2 s; inserir / sobrescrever segue o botão Inserir) |
| Shift+Delete | Excluir e fechar o espaço |
| N | Ímã liga/desliga (Shift ao arrastar inverte) |
| M | Marcador no cursor (dois cliques nele: nome, nota, cor e capítulo) |
| Shift+↓ / Shift+↑ | Próximo / anterior marcador (também no modo Película) |
| Shift+M | Som da prévia liga/desliga (no modo Película, **M** também) |
| + / − | Aproximar / afastar a linha do tempo |
| Ctrl+A | Selecionar todos os clipes (com a linha do tempo em foco) |
| Esc | Tirar a seleção e voltar para Selecionar |
| Ctrl+Z / Ctrl+Y | Desfazer / refazer a edição |
| Ctrl+Alt+C / Ctrl+Alt+V | Copiar / colar os ajustes de cor |

**J / K / L** (como no Premiere e no Resolve): **L** reproduz para a frente e **J** para trás; apertar de
novo no mesmo sentido dobra a velocidade (1×, 2×, 4×, 8×) e o outro sentido volta a 1×. **K** (ou Espaço)
para. A velocidade aparece ao lado do tempo (por exemplo, *◀◀ 2×*). Para trás, cada quadro é buscado no
arquivo: pode ser mais lento e pular quadros, mas o quadro mostrado é sempre o certo e a janela não trava.
**Fora de 1× para a frente o som fica mudo** (e o medidor de som espera). O **Repetir** passou do L para o
**Ctrl+L**, porque o L agora é a reprodução para a frente.

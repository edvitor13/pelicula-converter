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
| Zoom | **+ / −**, Ctrl + roda do mouse, o controle de zoom ou **Ajustar** (sequência inteira). O zoom mantém o marcador de reprodução parado na tela; se ele estiver fora da vista, vem para o centro. Com **Zoom pelo marcador de reprodução** desmarcado (botão direito nos controles de zoom ou Configurações › Geral), Ctrl + roda aproxima pelo ponteiro e o resto, pelo centro da vista |
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

### Imagens numeradas (sequências de imagens)

Renders, animações e scans costumam vir como uma imagem por quadro: `plano_0001.png`, `plano_0002.png`…
Importe **uma delas** (ou arraste a pasta) e o app pergunta se é uma **sequência** — um clipe só, um quadro por
arquivo — ou só aquela imagem parada. A janela mostra quantos quadros achou, os **buracos** da numeração
(o clipe vai até o primeiro buraco) e a **velocidade** (padrão: a da montagem; 24, 25, 29,97…). Valem PNG,
TIFF, JPEG e, se o ffmpeg desta máquina lê, EXR e DPX. PNG e TIFF com transparência entram transparentes.
No modo Película, abrir uma imagem numerada (ou a pasta) também abre a sequência inteira. Se a pasta mudar de
lugar, ao abrir o projeto é só apontar um quadro da pasta nova.

### Novo: títulos, cor sólida, degradê e ponta

O botão **Novo** da Mídia cria clipes que não vêm de um arquivo. Eles entram **no cursor**, na faixa de vídeo
mais baixa que está livre ali (por cima do que já aparece), e ficam escolhidos para ajustar no painel da
direita — cada mudança se desfaz com Ctrl+Z e a Mídia acompanha o nome e a miniatura.

- **Cor sólida**: uma cor que preenche o quadro (fundo, cartela, fade para uma cor com a opacidade).
- **Degradê**: linear (com ângulo) ou radial, com 2 ou 3 cores (e o ponto da cor do meio).
- **Ponta com contagem**: a contagem regressiva do cinema, de 8 a 2, um número por segundo com o ponteiro
  girando; no **2** há um bipe de 1 kHz de um quadro (desligue em **Bipe no 2**) e depois preto. Tem 8 s; serve
  para conferir a sincronia do som numa cópia ou numa sala.
- **Título…**: veja abaixo.

Cor, degradê e título começam com 5 s e esticam como uma imagem. Para esconder o botão Novo e os painéis,
desligue **Títulos e geradores** em Configurações › Recursos (os clipes que já estão na montagem continuam
iguais na imagem e na exportação).

### Títulos

**Novo ▸ Título…** põe um título no cursor, com o texto já escolhido para você digitar por cima. No painel da
direita:

- **Texto**: Enter quebra a linha. Se a fonte não tiver algum caractere (um ideograma, por exemplo), o painel
  avisa quais são — eles apareceriam como um retângulo — e é só escolher outra fonte.
- **Estilo pronto**: *Título grande*, *Terço inferior* (nome e função, com caixa), *Cartela de cinema*,
  *Créditos* (rolando), *Legenda de filme* e *Máquina de escrever*. Trocar o estilo muda a letra, a posição e as
  animações; o texto fica.
- **Letra**: fonte (as que vêm com o app, de licença livre: o título sai igual em qualquer computador), peso,
  itálico, tamanho (em pixels de um quadro de 1080 linhas: acompanha a resolução), cor, alinhamento,
  entrelinha, espaço entre letras, largura máxima (quebra automática) e maiúsculas.
- **Contorno e sombra**, **Caixa** (uma por linha ou uma para o texto todo) e **Posição** (horizontal e
  vertical, em % do quadro).
- **Animação**: entrada e saída com a duração de cada uma — *Aparecer*, *Subir*, *Deslizar*, *Máquina de
  escrever*, *Letra por letra*, *Zoom suave*, *Revelar com máscara* e *Créditos rolando* (sobe o texto do pé ao
  alto do quadro durante o clipe inteiro). A entrada começa no primeiro quadro do clipe e a saída termina no
  último: aparar ou mudar a velocidade do clipe acompanha.

A prévia é a de sempre: o que se vê é o que sai na exportação, com o look de película por cima. Posição,
escala, opacidade e as chaves de animação do clipe (painel Imagem) continuam valendo sobre o título.

## 3. Ajustar o clipe (painel "Clipe")

Selecione um clipe e use o painel da direita. Quando o vídeo tem som ligado, escolha **Imagem** ou **Som**
no topo do painel.

### Ajustes rápidos

Um clique resolve o mais comum:

- **Automático**: corrige exposição, níveis e balanço de branco olhando **o clipe inteiro** (9 quadros
  espalhados por ele, sempre os mesmos). A setinha do botão tem **Só o quadro atual**, o jeito de antes. Os
  clipes que já foram ajustados ficam como estão: só muda o que você clicar de novo.
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
| **Pele natural** *(cor simples)* | A pele não acompanha as mudanças de cor do clipe e fica com a cor mais uniforme (veja *Cor simples*, abaixo) |
| **Cor escolhida** *(cor simples)* | Uma cor só (a que você clicou): matiz, saturação e luminância |
| **Degradê** *(cor simples)* | Céu ou chão com luz e cor próprias |
| **Enquadrar e posicionar** | Encaixe no quadro (inteiro com barras, preencher ou esticar), escala (também só na horizontal ou só na vertical: veja *Escala por eixo*, abaixo), posição, rotação, espelhar, cortes nas bordas, opacidade e mesclagem com a faixa de baixo (tela, multiplicar, sobrepor…) |
| **Velocidade** | Câmera lenta (abaixo de 1×), acelerado (acima de 1×) e **congelar quadro**. A duração do clipe muda junto, e o som ligado acompanha. No fim do cartão: **Reverso** e **Rampa de velocidade** (veja *Tempo do clipe*, abaixo) |
| **Transições** | Entrada: corte seco, **dissolver com o clipe anterior**, surgir do preto ou do branco. Saída: corte, sumir no preto, no branco ou mostrar a faixa de baixo. Cada uma com a sua duração |
| **Câmera** (1.6) | O **perfil do clipe**: como ele foi gravado (S-Log3, V-Log, Canon Log 3, HLG do celular, Rec.709…), para misturar câmeras diferentes numa montagem. O padrão, **Igual ao do look**, deixa o clipe como sempre. Avançado: *Log reescalado* e *EI do ARRI LogC3*, como no look (veja *Câmeras diferentes na mesma montagem*, abaixo) |

> **Dissolver** mistura o começo deste clipe com o fim do clipe anterior da mesma faixa (encostado nele).
> Para a mistura ficar bonita, o clipe anterior precisa ter um pouco de vídeo sobrando depois do corte.

#### Cor simples

Ferramentas de um clique sobre a cor do clipe (módulo **Cor simples**, ligado no perfil Criador; desligar só
esconde a barra e os cartões). Tudo o que elas fazem vira ajuste comum do clipe: dá para mexer depois e desfazer
com Ctrl+Z. A barra **Cor simples** fica embaixo dos ajustes rápidos:

- **Neutro** (conta-gotas do balanço de branco): clique em algo que deveria ser branco ou cinza na prévia (uma parede, uma camiseta,
  o céu nublado). A temperatura e a tonalidade do clipe ficam no ponto em que essa cor vira neutra. Esc cancela.
- **Cor** (conta-gotas): clique numa cor da prévia — o carro vermelho, o céu, a grama. Ela vira a **Cor
  escolhida** do clipe: no cartão *Cor escolhida*, mude o **Matiz** (gira para outra cor), a **Saturação** e a
  **Luminância** só dela; a **Largura** diz quanto das cores vizinhas entra. O cartão HSL também abre na faixa
  mais perto da cor clicada. Os cinzas nunca mudam.
- **Igualar**: deixa a cor e a luz deste clipe parecidas com as de **outro clipe** (o quadro do meio dele, já
  com os ajustes dele) ou de **uma imagem**. Mede a exposição, o balanço, a saturação e o contraste e escreve os
  valores nos ajustes do clipe. Com **Proteger a pele** (ligado), os tons de pele ficam fora das contas — um rosto
  não puxa o balanço — e a *Pele natural* do clipe vai a 50%.
- **Grupo**: selecione dois ou mais clipes e use **Agrupar os selecionados**. Daí em diante, mexer na cor ou na
  luz de um muda a dos outros do grupo (só os ajustes que você mexeu: o resto de cada clipe fica). O
  enquadramento, a velocidade, as transições e as chaves de animação continuam de cada clipe. **Selecionar o
  grupo** e **Tirar do grupo** estão no mesmo menu.

Os cartões da cor simples:

| Cartão | Ajuste | O que faz |
|---|---|---|
| **Pele natural** | Pele natural (0–100%) | Na pele (achada pela cor, do muito claro ao muito escuro), a cor volta à do arquivo, com a luz do clipe, e fica mais uniforme. Esfrie o clipe inteiro sem deixar o rosto azulado. Só a cor: a textura nunca é alisada |
| | Cor da pele *(avançado)* | O matiz que a máscara da pele procura |
| **Cor escolhida** | Cor, Largura | A cor que muda (matiz, 0–360°) e quanto as vizinhas entram |
| | Matiz, Saturação, Luminância | O que muda nela |
| **Degradê** | Forma | Linear (uma linha: céu ou chão) ou radial (dentro do círculo) |
| | Direção | Que lado muda no linear: 0° = em cima (céu), 90° = à direita, 180° = embaixo (chão) |
| | Centro, Raio, Suavidade, Inverter | Onde fica a linha ou o círculo (em pixels de um quadro de 1080 linhas do próprio clipe: o degradê acompanha o enquadramento) |
| | Exposição, Temperatura, Tonalidade, Saturação | O que muda no lado marcado |

#### Transições de película

Com o recurso **Transições de película** ligado (Configurações › Recursos; vem ligado nos perfis Criador,
Cinema e Tudo), a lista de **Entrada** ganha:

| Transição | Como fica | Ajustes |
|---|---|---|
| **Fusão ótica** | Como na copiadora ótica: as duas imagens se somam na luz, e as partes claras do plano novo aparecem primeiro | Duração |
| **Surgir do preto na exposição** | A luz sobe do preto como na copiadora; os tons seguem a curva da película, sem ficar "lavado" | Duração |
| **Queima da película** | A película queima no projetor: um furo com a borda branca e laranja borbulha e abre, mostrando o plano novo | Duração, centro, suavidade da borda |
| **Emenda com clarão** | Um corte com a emenda à vista: de 1 a 3 quadros estouram de luz, com a linha da emenda e um pulinho da imagem | Quadros do clarão, força do clarão |
| **Ponta entre os planos** | Alguns quadros de ponta (preta ou clara) com poeira, riscos e o furo de perfuração no quadro do meio | Duração, ponta preta ou clara |
| **Íris** | Um círculo abre do centro escolhido, como nos filmes mudos | Duração, centro, suavidade, anel preto |
| **Empurrar** | O clipe novo empurra o anterior para fora, com desfoque de movimento | Duração, direção |
| **Cortina** | Uma borda atravessa o quadro e troca um plano pelo outro | Duração, direção, suavidade da borda |
| **Zoom** | O plano anterior amplia até a troca e o novo chega ampliado e volta ao tamanho | Duração, centro, ampliação |

E a lista de **Saída** ganha **Escurecer na exposição**, **Queimar a película** (mostra a faixa de baixo)
e **Íris** (fecha o círculo). O painel só mostra os ajustes do tipo escolhido; centro e suavidade são
medidos no quadro, então ficam iguais em qualquer resolução da prévia ou da exportação.

**Pelo menu do corte**: botão direito num clipe de vídeo → **Transição** → escolha o tipo. Perto do começo
do clipe, vale para a entrada dele; perto do fim, para a entrada do clipe colado à direita (ou para a saída
deste, se não houver). A duração é 1 segundo na primeira vez e depois a última que você usou; **Desfazer**
volta tudo num passo só. Na linha do tempo, a transição aparece como uma faixa sobre o corte, com o ícone e
o nome.

As misturas são feitas na luz do perfil de entrada da película (o mesmo que o look usa: vídeo comum,
S-Log3, LogC…), por isso combinam com a emulação; a prévia e a exportação dão exatamente o mesmo quadro, e
cada clipe repete a mesma queima e a mesma poeira toda vez. O som não muda: para cruzar o som use a
**Transição de som** abaixo. Desligar o recurso só esconde os tipos novos e o menu; um projeto que já os
usa continua saindo igual (o app avisa e oferece religar). Projetos com transições de película pedem a 1.5
ou mais nova para abrir.

#### Câmeras diferentes na mesma montagem

O look de película lê a montagem inteira com um perfil só (Película › *Entrada e exposição* › **Perfil do
vídeo**). Se a montagem mistura câmeras — a principal em S-Log3, um drone em D-Log, o celular em HLG —, escolha
no look o perfil da câmera principal e, no cartão **Câmera** de cada clipe de outra câmera, o perfil dele. O
app converte esse clipe para o perfil do look antes dos ajustes de cor do clipe (curva e cores da câmera dele →
luz → curva e cores da câmera do look): a cor, as transições e o look veem todos os clipes como se viessem da
mesma câmera. Um clipe que fica em **Igual ao do look** não muda.

- Os clipes com perfil próprio em log são lidos com as luzes acima do branco do vídeo (os super-brancos), e a
  montagem passa ao look a luz inteira, sem cortar nem arredondar. Para isso valer também para um clipe da
  câmera principal, escolha o perfil dele no cartão (em vez de *Igual ao do look*).
- Sem película na prévia (o botão do filme desligado), os clipes com perfil próprio aparecem convertidos para
  vídeo comum (Rec.709), como saem na exportação *Sem película (só a edição)*; os que seguem o look aparecem como
  foram gravados (um log continua lavado).
- **Proteger cores saturadas** (no look) vale para a montagem inteira, no espaço do look.
- **Clipes novos já vêm com o perfil** quando os metadados do arquivo indicam um diferente do look (HDR marcado,
  o XML da Sony, Apple Log, etiquetas de curva; veja *Sugestão pelos metadados* no guia dos efeitos). O primeiro
  vídeo de uma montagem vazia não: ele mostra a sugestão para o próprio look, como no modo Película. Num look
  HLG/PQ, um vídeo marcado como comum (BT.709/sRGB) entra como Rec.709. Clipes que já estão na montagem e
  projetos reabertos nunca mudam.
- Um projeto com perfil de clipe pede a 1.6 ou mais nova para abrir.

### Escala por eixo

No cartão **Enquadrar e posicionar**, **Escala horizontal** e **Escala vertical** esticam o clipe só em um eixo, de
10% a 400%, com 100% de padrão. O tamanho final de cada lado é a **Escala** vezes a escala daquele eixo, sempre nos
eixos do próprio clipe: com rotação, primeiro a escala, depois o giro. Os dois aceitam chaves de animação, como a
Escala. Não há um cadeado "proporcional": a própria **Escala** já é esse controle.

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
- **Faixa principal magnética**: veja *Montar*, acima;
- **Fundo transparente**: onde nada cobre a tela, a montagem fica transparente em vez da cor do fundo. A
  prévia mostra um xadrez nesses lugares; para gravar a transparência, exporte em um formato com alfa (veja
  *Depois da edição*).

## 5. Monitores

Acima dos ajustes há um monitor com quatro vistas:

- **Histograma**: quantos pixels há em cada nível de brilho;
- **Onda** (forma de onda): o brilho de cada coluna da imagem — 0% embaixo, 100% em cima. Ótimo para ver
  se os brancos estouraram ou os pretos amassaram;
- **RGB** (parada): a forma de onda do vermelho, do verde e do azul lado a lado — se as três estão na mesma
  altura num objeto branco ou cinza, o balanço de branco está certo;
- **Vetor** (vetorscópio): o ângulo é a cor e a distância do centro é a saturação. A linha tracejada é o
  **tom de pele**: rostos bem corrigidos ficam perto dela.

### Zebra, falsa cor e referência

Na barra da prévia (nos dois modos, com o módulo **Scopes**):

- **Falsa cor**: pinta a prévia pela exposição, em *stops* em relação ao cinza médio de 18% da luz da cena (a
  mesma luz que o look lê do vídeo, pelo *Perfil do vídeo*, com a exposição e o balanço): **roxo** abaixo de −6
  (preto), **azul** de −6 a −4,5 (sombra profunda), **verde** ±0,25 (cinza médio), **rosa** de +0,75 a +1,25
  (pele clara, um stop acima do cinza), **amarelo** de +4,5 a +6 (quase estourado) e **vermelho** acima de +6
  (estourado). O resto fica em cinza, mais claro quanto mais luz.
- **Zebra**: listras pretas e brancas onde a exposição passa do limite; a setinha do botão escolhe +2,5, +4,5
  (padrão) ou +6 stops.
- **Referência**: **Fixar este quadro** guarda a prévia atual; **Abrir imagem…** usa uma foto ou um quadro de
  outro filme. Com a referência, **Dividido** e **Lado a lado** mostram a referência no lugar do original
  (**Comparar com a referência** liga e desliga; **Tirar a referência** volta ao original).

Tudo isso é só na tela: nada vai para a exportação nem para o "Salvar quadro". No modo Edição sem película, a luz
medida é a da montagem lida pelo *Perfil do vídeo* do look.

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
- **Exportar com transparência**: com **Fundo transparente** ligado na Sequência, escolha **Apple ProRes**
  (sai em ProRes 4444), **VP9 (WebM)**, **Sequência PNG** ou **Sequência TIFF** e deixe **Manter a transparência (canal alfa)**
  ligado. A cor sai igual à exportação normal; o alfa acompanha o que o look faz com a imagem (tremor, zoom,
  moldura com barras transparentes, a tira do scan opaca). Grão, halação e defeitos só mudam a cor. **Salvar
  quadro** em PNG ou TIFF também guarda a transparência.
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
| Alt+R / G / B / D | +1 ponto de luz vermelha / verde / azul / densidade da copiadora no plano (Shift: −1; seção 10) |
| Ctrl+Shift+L | Painel de legendas (também no modo Película) |
| Delete / Enter / Esc na faixa Legendas | Apagar / editar / tirar a seleção da legenda escolhida |

**J / K / L** (como no Premiere e no Resolve): **L** reproduz para a frente e **J** para trás; apertar de
novo no mesmo sentido dobra a velocidade (1×, 2×, 4×, 8×) e o outro sentido volta a 1×. **K** (ou Espaço)
para. A velocidade aparece ao lado do tempo (por exemplo, *◀◀ 2×*). Para trás, cada quadro é buscado no
arquivo: pode ser mais lento e pular quadros, mas o quadro mostrado é sempre o certo e a janela não trava.
**Fora de 1× para a frente o som fica mudo** (e o medidor de som espera). O **Repetir** passou do L para o
**Ctrl+L**, porque o L agora é a reprodução para a frente.

## 8. Legendas, transcrição e silêncios

### Legendas

O botão **Legendas** (no topo da janela, nos dois modos) abre o **painel de legendas** (Ctrl+Shift+L) e
importa ou exporta arquivos **.srt** e **.vtt**. Com legendas no projeto, a linha do tempo ganha a faixa
**Legendas**, embaixo das faixas de som:

- clique numa legenda para escolher e levar o cursor até ela; arraste para mover; arraste as bordas para
  acertar o começo e o fim (o ímã gruda nos cortes, no cursor e nas outras legendas; Shift inverte);
- dois cliques editam o texto; dois cliques num lugar vazio criam uma legenda ali; Delete apaga a escolhida;
- o botão direito tem **Nova legenda aqui**, **Dividir no cursor**, **Juntar com a próxima** e **Excluir**.

As legendas ficam **presas ao trecho do vídeo** que mostram: cortar, mover, aparar ou mudar a velocidade de um
clipe leva a fala junto (as escritas num lugar sem clipe ficam no tempo da sequência e aparecem tracejadas).

No painel: a lista com **Buscar** e **Substituir todas**, o texto (aplica ao sair do campo ou com Ctrl+Enter),
o começo e o fim, itálico e negrito, e o tempo de cada palavra quando a legenda veio da transcrição. Ctrl+Z
desfaz também no modo Película, com o painel em foco (ou pelos botões do painel).

**Estilo**: comece por **YouTube** (caixa escura embaixo), **Reels** (letras grandes no meio, três palavras
por vez, a palavra falada em amarelo) ou **Cinema** (letras claras com sombra) e mude fonte, peso, tamanho,
cores, contorno, caixa, sombra, posição, margem, largura e palavras por vez — a prévia mostra na hora. Se a
fonte não tiver alguma letra do texto, o painel avisa.

**Gravar no vídeo** e a exportação: em **Exportar**, a linha **Legendas** (só aparece com legendas no projeto)
escolhe como elas saem:

| Opção | O que faz |
|---|---|
| Sem legendas | nada |
| Faixa de legenda no arquivo | o player liga e desliga (MP4, MOV, MKV e WebM) |
| Gravada na cópia | entra **antes** do look: ganha grão, halação e tremor, como numa cópia de cinema legendada |
| Digital | entra **depois** do look, nítida, por cima do quadro final |
| Arquivo .srt / .vtt ao lado | um arquivo com o mesmo nome do vídeo, no tempo do trecho exportado |

O modo escolhido em **Gravar no vídeo** (no painel) vale para a prévia, o **Salvar quadro** e a exportação.
Sem gravar, **Ver na prévia** mostra as legendas por cima, como num player, só na tela. No terminal:
`pelicula-cli exportar projeto.plc --legendas copia` (ou `nao`, `faixa`, `digital`, `srt`, `vtt`; o padrão é o
que o projeto pede).

### Gerar legendas pela fala (Beta)

Ligue **Legendas automáticas** em Configurações › Recursos. **Gerar…** (no painel) ou **Legendas › Gerar
legendas pela fala…** transcreve a fala **neste computador**, sem enviar nada para a internet:

- **Ouvir**: o arquivo aberto (modo Película) ou a montagem inteira / os clipes escolhidos (modo Edição);
- **Idioma** (ou *Detectar o idioma*), **Modelo** — *Rápido (small)* serve para a maioria dos vídeos;
  *Preciso (turbo)* acerta mais, mas é mais lento sem placa de vídeo — e o tamanho de cada legenda
  (caracteres por linha e linhas; para vídeos verticais, uns 24 caracteres);
- na primeira vez, a janela avisa o que falta e abre **Configurações › Componentes** para baixar o
  whisper.cpp, o modelo e o Silero VAD; nada é baixado sem você pedir.

A transcrição roda na fila de tarefas (a janela pode ser fechada; dá para cancelar). No fim, as legendas
entram no projeto de uma vez — Ctrl+Z tira todas — trocando as que já existiam nos trechos ouvidos, e
ficam presas aos arquivos: cortes feitos depois levam a fala junto.

**Cortar pelo texto**: com as legendas geradas, a aba **Cortar pelo texto** do painel mostra a fala como
texto. Selecione palavras ("éé", uma frase repetida…) e clique em **Marcar** (de novo desmarca); clicar
numa palavra leva o cursor até ela. **Cortar os marcados** tira esses trechos da montagem de uma vez: o que
vem depois encosta em todas as faixas, com o som junto da imagem.

### Remover silêncios

O botão **Silêncios** na barra da linha do tempo acha os trechos sem fala no som da montagem (ou só nos
clipes escolhidos) e tira todos de uma vez:

- **Limiar**: quanto abaixo do volume típico do trecho conta como silêncio (−30 dB tira só o silêncio de
  verdade; perto de −15 dB tira também respiros e ruído baixo); **Duração mínima** (pausas mais curtas
  ficam); **Folga** (quanto do silêncio fica encostado na fala, para o corte não ficar seco);
- **Analisar** mostra a lista: desmarque o que deve ficar e clique num trecho para levar o cursor até ele;
- **Tirar os marcados** corta todas as faixas destravadas e encosta o resto (som e imagem continuam
  juntos; marcadores, animações e legendas acompanham). Ctrl+Z desfaz tudo de uma vez. Faixas travadas
  (o cadeado) não mudam — por exemplo, uma música de fundo.

## 9. Câmera de cinema e a montagem na película (1.6, Beta)

Ligue em *Configurações › Recursos* os recursos **Câmera de cinema** e **A montagem na película** (em teste,
começam desligados).

### Manivela (no inspetor do clipe, depois de Velocidade)

- **Cadência da manivela**: 16, 18, 20 ou 22 qps, como uma câmera de manivela projetada na velocidade da
  sequência. O clipe fica mais rápido e aos saltos (16 qps numa sequência de 24 = 1,5×): a duração e o **som**
  acompanham, como numa mudança de velocidade. Voltar a *Normal* devolve a velocidade de antes.
- **Oscilação da mão**: a mão não gira a manivela num ritmo perfeito; a imagem adianta e atrasa um pouco (no
  máximo 50 ms com 100%), sem atrasar o clipe. Só a imagem oscila; o som segue a velocidade média.
- **Semente** (avançado): outro jeito da mão.

### Obturador de película

Com o look de película na montagem (*Com película*) e o **Obturador de película** ligado no look, cada clipe com
pelo menos o dobro de quadros por segundo da sequência (60 qps numa sequência de 24, ou um clipe acelerado)
ganha o rastro de movimento de um obturador de cinema: os quadros do arquivo dentro da janela aberta (180° =
metade do quadro) são misturados na luz. A prévia, "Salvar quadro" e a exportação mostram o mesmo.

### A montagem na película

Com a seção **A montagem na película** ligada no look, cada **corte seco** da faixa V1 vira uma emenda: a fita
aparece no primeiro quadro do clipe novo, a junta deixa passar um clarão e o quadro pula na janela do projetor.
Cortes com transição (dissolver, queima, emenda com clarão…) não contam. **Rolos de Super 8** dividem o vídeo em
rolos de 50 pés (3 min 20 s a 18 qps, 2 min 30 s a 24): o fim de cada rolo vela e a troca dá um pulo. Tudo é igual
a cada reprodução (mesma semente, mesmos quadros).

## 10. Marcação de luz por plano (1.6)

No laboratório, o marcador de luz assiste ao filme montado e escolhe, **plano a plano**, as luzes vermelha, verde e
azul da copiadora: um plano mais escuro ganha menos pontos, uma cena com dominante verde ganha um pouco mais de
verde. O cartão **Luz da copiadora** do inspetor (logo depois de *Câmera*) faz isso com o **Laboratório** do look:
os pontos de cada clipe **somam** às luzes da copiadora do Laboratório (Película › *Laboratório*) nos quadros em que
o clipe é o plano da **V1**.

- **Só com o Laboratório ligado** (e com a película na prévia, o botão do filme, para ver na tela; a exportação com
  o look sempre usa). Sem ele o cartão avisa e as luzes não mudam nada.
- O **mostrador** mostra as luzes do plano como numa folha de marcação: o TAPE padrão **25-25-25** (as luzes no
  alvo do LAD da Kodak) mais as do look e as do clipe — por exemplo *27 · 24 · 25*. Embaixo, só o que é deste
  plano (*R +2 · G −1 · B 0*).
- **1 ponto = 0,025 log E**: 12 pontos = 1 stop da cópia; cerca de 7 pontos = 1 stop da câmera. Mais vermelho deixa a
  cópia mais **ciano**, mais verde mais **magenta**, mais azul mais **amarela** (como no laboratório: a luz é
  subtraída na cópia). **Densidade** soma nas três: mais pontos = plano mais escuro, sem mudar a cor.
- **+1 / −1** em cada cor e na densidade, **Zerar** (volta às luzes do look) e **Copiar luzes para os clipes
  selecionados** (selecione os outros clipes com Ctrl ou Shift na linha do tempo). Cada clique é um passo do
  desfazer.
- **Atalhos** (modo Edição): **Alt+R / G / B / D** somam 1 ponto de luz vermelha / verde / azul / densidade;
  com **Shift**, tiram 1 ponto. Valem para os clipes de vídeo selecionados ou, sem seleção, para o plano da V1 sob
  o cursor; a barra de status mostra as luzes do plano.
- **Clipes nas faixas de cima** (V2, V3… — títulos, sobreposições) não mudam o plano: vale a luz do clipe da V1.
- **Transições**: num *dissolver* ou numa transição de dois clipes (fusão ótica, queima, íris, empurrar, cortina,
  zoom) a luz vai de um plano ao outro junto com a mistura. No laboratório, uma fusão ótica copia os dois
  negativos, cada um com a sua luz; aqui o look tem uma luz por quadro, então ela caminha sem pulo e cada plano
  tem a luz dele nas pontas. Surgir do preto ou do branco troca a luz no corte.
- **Modo Película** com um arquivo só: não há planos. Para marcar a luz por plano, divida o vídeo nos cortes no
  modo Edição (S) e dê a luz a cada pedaço; a montagem passa a ser a entrada do look.
- O cartão some com o recurso **Laboratório** desligado (*Configurações › Recursos*). Um projeto com luz por plano
  pede a 1.6 ou mais nova para abrir. O plugin do DaVinci não tem a montagem: lá a luz da copiadora fica no nó
  Laboratorio (uma por nó; use um nó por plano).

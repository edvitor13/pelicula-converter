# Changelog

Todas as mudanças importantes deste projeto ficam registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto usa
[Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Planejado
- Suporte ao macOS (o código, o `PeliculaConverter.spec` e o job do CI já estão preparados, mas
  desativados).

## [1.7.0] - 2026-10-30

### Adicionado
- **Várias sequências no projeto** (#57): abas sobre a linha do tempo, cada uma com tamanho, quadros por segundo,
  proporção, faixas, marcadores e legendas próprios; a Mídia e as pastas são do projeto. **+** cria, dois cliques
  renomeiam, arrastar muda a ordem, **Ctrl+Tab** e **Ctrl+Shift+Tab** passam de aba. *Nova sequência a partir deste
  vídeo*, na Mídia, já vem com o formato dele. Trocar de aba não é mudança, e o **Ctrl+Z** é um só para o projeto.
- **Sequência dentro de sequência** (#57): uma sequência entra em outra como um clipe de imagem e som ligados, até 8
  níveis; mexer na de dentro muda o clipe. **Aninhar seleção** (**Ctrl+Shift+G**) leva os clipes para uma sequência nova
  sem mudar a imagem nem o som, e **Desaninhar** devolve. Dois cliques no clipe abrem a sequência no quadro certo.
  Quando a promessa não se sustenta, a ação recusa ou avisa; os limites estão em *Sequências dentro de sequências*
  (`docs/EDICAO.md`).
- **Exportar sequências** (#57): com duas ou mais, a janela escolhe qual sai e *Pôr várias sequências na fila* gera uma
  tarefa para cada. No terminal, `pelicula-cli exportar` e `quadro` aceitam `--sequencia NOME`, e `info` lista as
  sequências do projeto.
- **Proporção de cinema na sequência** (#55): 1,33 a 2,76 (com 2,39 Scope) ou personalizada, como quadro real ou como
  faixas pretas no quadro. Com faixas nasce a **janela útil**: encaixe, posição, títulos e legendas valem dentro dela, e
  as faixas ficam em preto exato, fora do look.
- **Desespremer o clipe** (#52): 1,33×, 1,5×, 1,55×, 1,8×, 2× ou taxa manual, antes de o clipe se encaixar no quadro,
  para vídeo de lente anamórfica no meio de uma montagem.
- **Escala horizontal e vertical** (#54) nos ajustes do clipe, de 10% a 400%, com chaves de animação.
- **Filtrar ajustes** (#56): um campo no alto dos painéis de ajustes, nos dois modos, procura em português, inglês e
  espanhol nos títulos, nos controles, nas dicas e nas opções. **Ctrl+F** ou **/** levam a ele, **Esc** limpa e devolve
  o painel como estava.
- **Pastas coloridas na Mídia** (#58): pastas e subpastas, oito cores ou uma personalizada, arrastar, ordenar por nome,
  tipo ou data, e soltar uma pasta do sistema para importá-la. Um arquivo guardado numa pasta volta com o projeto mesmo
  sem estar na linha do tempo.
- **Desligar todos os efeitos** (**Shift+D**): mostra a imagem sem o look e sem os ajustes de imagem dos clipes, para
  comparar. Religar devolve tudo, nada entra no projeto ou no desfazer, e a exportação pergunta antes de sair sem efeitos.
- **Seletores da prévia:** o modo e a comparação ganharam ícones e o estado escolhido mais claro, e o seletor de
  comparação agora é *Resultado / Dividido / Lado a lado / Original*.

### Mudou
- **Projetos:** um projeto que usa algo novo da 1.7 (mais de uma sequência, sequência como clipe, pastas, janela útil,
  escala por eixo ou desespremer) só abre na 1.7 ou mais nova. Os antigos abrem e saem iguais, e a proporção como quadro
  real continua abrindo nas versões anteriores.

### Corrigido
- **Ctrl+Z desfazendo o look na Edição:** abrir um projeto salvo no modo Película com a Edição na tela deixava o botão
  e o histórico na Película e as telas na Edição (#50).
- **Som do clipe apagado na prévia:** depois de apagar um clipe ou mudar a ordem deles, a prévia continuava tocando a
  mixagem antiga, e volume e faixa pareciam não fazer efeito. A exportação não tinha o problema (#51).
- **Zoom da linha do tempo pulando para longe:** todo zoom agora mantém o marcador de reprodução parado e o traz para
  o centro quando está fora da vista. A opção **Zoom pelo marcador de reprodução** (marcada por padrão, em
  Configurações › Geral e no botão direito dos controles de zoom) volta ao ponteiro e ao centro da vista (#53).
- **Exportar durante uma exportação:** o botão (e o Ctrl+E) agora mostra a fila, em vez de abrir outra exportação
  que recomeçava do zero ao terminar a primeira. Na fila há *Adicionar outra exportação…*, e um destino que já está
  na fila pede outro nome (#59).

## [1.6.0] - 2026-10-29

### Adicionado
- **Perfis de câmera novos**, pelas fórmulas que os fabricantes publicam: Canon Log 2 e Log 3, Fujifilm
  F-Log, F-Log2 e F-Log2 C, DJI D-Log, Sony S-Log2 e Leica L-Log, e o **EI do ARRI LogC3** (avançado).
  Também no plugin do DaVinci.
- **Proteger cores saturadas** (seção *Entrada*): comprime com suavidade as cores fora do gamut (LED,
  neon), a partir da ACES Reference Gamut Compression. Também no plugin.
- **Perfil de câmera por clipe** no modo Edição (cartão *Câmera*): câmeras diferentes na mesma montagem;
  cada clipe é convertido para a entrada do look, e a montagem leva ao look a luz acima do branco.
- **Sugestão do perfil pelos metadados**: ao abrir um arquivo, uma faixa oferece *Usar este perfil* (o look
  só muda com o clique); no modo Edição, clipes novos de outra câmera já entram com o perfil.
- **Grão e textura**: *Maciez pelo grão* e *Respiração por camada* (seção *Grão*), *Diferença de nitidez
  entre camadas* (seção *Película*, pelas curvas de MTF dos datasheets públicos da Kodak), **Grão no
  negativo** (seção *Laboratório*: o grão na densidade de cada camada, moldado pela curva da cópia, com a
  granularidade publicada; também no nó *Laboratorio* do plugin) e o modelo **Física** da halação (o
  reflexo na base volta à camada do vermelho antes da cópia).
- **Cor por planos** (Beta, desligado): frente, fundo e pele com ajustes próprios no look, separados por
  degradê, com conta-gotas da pele e *Ver planos*. Não vai para o LUT exportado nem para o plugin.
- **Cor simples** no modo Edição (módulo, ligado a partir do perfil *Criador*): conta-gotas do balanço de
  branco, *Automático* analisando o clipe inteiro, igualar a outro clipe ou a uma imagem protegendo a pele,
  clicar numa cor da prévia e mudar só ela, *Pele natural*, degradê e grupos de cor.
- **Zebra, falsa cor e referência na prévia** (módulo *Scopes*): exposição em stops em relação ao cinza de
  18% e um quadro fixado ou uma imagem para comparar (Dividido ou Lado a lado). Só na tela.
- **Processos novos no Laboratório**: *Reversível* (slide, sem negativo nem cópia: mais contraste, pretos
  densos, pouca latitude) e a **Revelação cruzada** nos dois sentidos (*slide no C-41*: sombras azuladas e
  altas luzes amareladas; *negativo no E-6*: pouco contraste, preto lavado e altas luzes quentes). Também no
  plugin.
- **Película vencida** (0 a 30 anos: menos sensibilidade e contraste e um véu nas sombras) e **Pré-exposição**
  (*flashing*: uma luz uniforme no negativo que abre e suaviza as sombras), no Laboratório. Também no plugin
  (nó *Laboratorio* e OpenFX).
- **Tipo de scanner** do *Sem cópia*: *Luz branca* (uma câmera fotografando o negativo na mesa de luz, com as
  camadas misturadas e as cores menos saturadas) além do *RGB estreito* de sempre. Também no plugin.
- **Filmes "(datasheet)"** no Laboratório: Vision3 250D, 500T e 200T e a cópia 2383, com as curvas ajustadas
  às publicadas pela Kodak (gama, pé, ombro, densidade máxima e diafonia dos corantes). Feitos para andar
  juntos: negativo e cópia "(datasheet)" dão a escala de cinza quase neutra. Os filmes de antes não mudam.
- **Conferência pelo LAD da Kodak** no Laboratório: o cinza de 16% sai na cópia com a densidade-alvo dos
  laboratórios, e cerca de 7 pontos de copiadora compensam 1 stop da câmera.
- **Obturador de película** (Beta, recurso *Câmera de cinema*): o rastro de movimento de 180° (ou 45° a 360°) a
  partir de vídeo de 50, 60 ou 120 qps exportado a 24, 25 ou 30. No modo Edição vale por clipe.
- **Manivela por clipe** no modo Edição (Beta, *Câmera de cinema*): 16 a 22 qps com a oscilação da mão, no
  inspetor do clipe depois de *Velocidade*.
- **Lente anamórfica** (Beta): desespremer (1,33× a 2×) com caixa de letra, risco de luz horizontal azul,
  barril e bordas macias. Não vai para o plugin.
- **Data impressa** (Beta): a data laranja de sete segmentos das câmeras dos anos 80 e 90, exposta no
  negativo (passa pela halação, pela cor e pelo grão). Não usa o relógio do computador.
- **Formatos de foto**: bitolas *Foto 35 mm (135)*, *Foto meio quadro* e *Foto médio formato (120)*, e no
  *Scan da película* o 135, o meio quadro e o 120 (6 x 6 e 6 x 4,5). Também no plugin.
- **A montagem na película** (Beta): os cortes secos da faixa V1 viram emendas (fita, clarão e pulo na
  janela) e rolos de Super 8 de 50 pés com o velamento no fim. Não vai para o plugin.
- **Máquina do tempo** (módulo, ligado): botão no painel de looks; escolha um ano (1920 a 2020) e onde o filme
  passava, e ele preenche bitola, filme, cor, grão, projeção, desgaste e moldura da época, com o motivo de
  cada escolha. Ctrl+Z desfaz tudo de uma vez.
- **Grão físico** (Beta, desligado, recurso *Grão físico*): novo *Modelo do grão no negativo* (*Físico*), com
  grãos de prata espalhados ao acaso, tantos quanto a densidade de cada camada pede, na granularidade do
  datasheet. Ajustes avançados *Tamanho do cristal* e *Variação do tamanho*. No plugin, no nó *Laboratorio*
  (parado no DCTL, animado no OpenFX).
- **Grão completo**: *Estrutura pela densidade* (grãos soltos nas sombras, buracos soltos nas altas luzes,
  seguindo a granularidade de cada camada) e *Aglomeração nas altas densidades*, na seção *Grão*. Também no
  plugin (nós *Textura* e *Laboratorio*).
- **Luz da copiadora por clipe** (modo Edição): cartão *Luz da copiadora* no inspetor, com o mostrador
  25 · 25 · 25, botões de vermelha, verde, azul e densidade, *Zerar* e *Copiar luzes para os clipes
  selecionados*; atalhos **Alt+R / G / B / D** (+1 ponto) e com **Shift** (−1). Vale para a faixa V1 e precisa
  do Laboratório ligado.
- **Fotômetro da película** (Beta, desligado, recurso *Fotômetro da película*): na prévia, pinta a imagem pela
  zona do negativo escolhido (sem detalhe, pé, trecho reto, ombro, estourado), mostra a latitude em stops e lê
  um ponto. Com um processo especial dominante (*Reversível*, revelações cruzadas, Technicolor) mede o filme do
  processo. Só na tela.
- **Quatro presets novos** (grupo *Laboratório*): *Slide reversível*, *Revelação cruzada: slide no C-41*,
  *Película vencida (18 anos)* e *Pré-exposição (baixo contraste)*. Também no plugin (os dois últimos, com o
  efeito completo, só no nó *Laboratorio*).

### Corrigido
- **Super-brancos em vídeo log de faixa legal**: o que passava do código 940 era cortado ao abrir o
  arquivo (no S-Log3, a partir de uns 6,7 stops acima do cinza). Agora chega ao look na prévia, na
  exportação, no *Salvar quadro* e no `pelicula-cli`. **Isso muda a saída desses arquivos**: as altas luzes
  acima do branco legal deixam de estourar duro. Vídeo Rec.709/sRGB e os demais casos saem iguais.
- **Saída de 16 bits de arquivo de faixa legal** ficava uns 0,4% escura (o branco saía 0,9962): o branco
  agora é 65535 exato, na exportação e no *Salvar quadro*.

### Alterado
- Projeto `.plc` no **formato 4** (bloco da montagem 3) quando usa algo da 1.6: a 1.5 recusa o projeto com
  aviso em vez de abri-lo sem os ajustes novos. Projetos sem nada da 1.6 continuam no formato de antes.
- Dados de fabricantes: números de publicações públicas podem calibrar modelos, com a fonte registrada
  (`pelicula/data/datasheets/`); o aviso legal do README explica o que é usado.

## [1.5.0] - 2026-10-28

### Adicionado
- **Transparência (canal alfa)** em todo o caminho do modo Edição: PNG, ProRes 4444, WebM (VP8/VP9) e
  sequências de imagens com alfa aparecem sobre as faixas de baixo, sem a franja escura na borda (o
  recorte do CorridorKey, `_cutout.mov`, deixa de ficar com fundo preto). **Fundo transparente** em
  *Configurar a sequência*, com xadrez na prévia e na Mídia, e **exportar com transparência** em ProRes
  4444, WebM VP9 ou sequência PNG/TIFF; *Salvar quadro* e `pelicula-cli quadro` em PNG/TIFF também
  guardam o alfa.
- **Sequências de imagens numeradas** (`plano_0001.png`…): ao importar, o app pergunta se entra como
  sequência, mostra os quadros e os buracos na numeração e deixa escolher a velocidade. PNG, TIFF e
  JPEG (EXR e DPX quando o ffmpeg lê).
- **Chaves de animação** (keyframes) em posição, escala, rotação, opacidade, cor, luz, rodas, volume e
  nos ajustes de película: losango ao lado de cada ajuste no inspetor e no painel do look (clique grava
  a chave no cursor; setas para a anterior e a próxima; quatro curvas prontas), losangos na linha do
  tempo (arrastar move, Delete apaga) e as chaves do look sob a prévia (Película) ou numa linha *Look*
  no topo da linha do tempo (Edição).
- **Tempo do clipe**: rampa de velocidade com seis formas prontas (Acelerar, Desacelerar, Impacto,
  Câmera lenta no meio, Entrada e Saída em câmera lenta) e o som acompanhando sem mudar o tom;
  **Reverso**, com o som ao contrário; **Congelar este quadro…** (Shift+F) põe o quadro do cursor parado
  pelo tempo escolhido.
- **Novo** na Mídia (módulo *Títulos e geradores*): cor sólida, degradê (linear ou radial), **ponta com
  contagem regressiva** (8 a 2, com o bipe de 1 kHz no 2) e **títulos** com 11 famílias de fontes livres
  (OFL) embutidas, que saem iguais no Windows e no Linux: seis estilos prontos e oito animações de
  entrada e saída (Aparecer, Subir, Deslizar, Máquina de escrever, Letra por letra, Zoom suave, Revelar
  com máscara e Créditos rolando).
- **Transições de película** (módulo *Transições de película*): fusão ótica e surgir/escurecer na
  exposição (misturam a luz, como numa copiadora), queima da película, emenda com clarão, ponta entre
  os planos e íris, mais empurrar, cortina e zoom. Botão direito num clipe: *Transição*.
- **Legendas** (módulo *Legendas*): painel (Ctrl+Shift+L) e faixa na linha do tempo, presas à fala do
  arquivo (cortar não tira de sincronia); estilos YouTube, Reels (palavra a palavra) e Cinema;
  importar e exportar `.srt` e `.vtt`; na exportação, faixa no arquivo, **gravada na cópia** (antes do
  look, com grão e halação), **digital** (depois do look) ou arquivo ao lado. Terminal: `exportar
  --legendas`.
- **Legendas pela fala** (módulo Beta *Legendas automáticas*): transcrição no próprio computador pelo
  whisper.cpp (placa de vídeo pela Vulkan ou processador), com os modelos *small* e *turbo* e a detecção
  de voz Silero, baixados à parte em *Componentes* com SHA-256 conferido; roda pela fila. Com o tempo de
  cada palavra, dá para **cortar pelo texto**.
- **Remover silêncios** (módulo *Remover silêncios*): analisa o som, mostra a lista para revisar e tira
  os trechos marcados num passo só do desfazer.
- **Ferramentas de corte**: inserir ou sobrescrever (botão *Inserir*; Ctrl ao soltar inverte; `,` e `.`
  no cursor), **faixa principal magnética** opcional, **Q/W** aparam até o cursor fechando o espaço,
  **cortes J e L** (Alt ao aparar; menu *Corte J*/*Corte L*) e **J/K/L** para reproduzir para trás,
  pausar e para a frente (2×, 4×, 8×; K segurado + J/L anda um quadro).
- Projetos `.plc` no **formato 3**, gravado só quando o projeto usa um recurso da 1.5 (a 1.4 recusa com
  aviso em vez de abrir errado); projetos antigos abrem, tocam e saem iguais e continuam gravando no
  formato de antes.

### Alterado
- **Repetir** passou do L para **Ctrl+L** (o L agora reproduz para a frente).
- Prévia, *Salvar quadro*, estimativa de tempo, exportação e terminal usam a mesma receita do quadro.
- As ferramentas novas da 1.5 seguem o perfil de recursos escolhido: no perfil Simples elas chegam
  desligadas; nos outros, ligadas.

### Corrigido
- No Windows, a prévia da janela de exportação às vezes ficava "Prévia indisponível" e a leitura de
  quadros pequenos falhava (o ffmpeg terminava antes de o app conectar ao pipe).
- Em espanhol, a dica do grupo *Proyector* trazia o nome em português.

## [1.4.0] - 2026-10-27

### Adicionado
- **Configurações** numa janela só, com barra lateral e páginas (Geral, Recursos, Componentes,
  Notificações e Recuperação).
- **Recursos**: ligue e desligue cada ferramenta do app (Edição, Laboratório, Defeitos, Scan, LUTs,
  Exportar LUT, medidores de cor, Curva, plugin do DaVinci e as novas desta versão), por perfil
  (*Simples*, *Criador*, *Cinema* ou *Tudo*) ou uma a uma. No primeiro acesso, depois do idioma, o app
  pergunta o perfil; instalações antigas continuam com tudo ligado. Os recursos em teste (Beta)
  começam desligados. Desligar só esconde a ferramenta: um projeto, preset ou LUT que usa um recurso
  desligado sai igual e mostra um aviso com o botão *Ligar*. Terminal: `pelicula-cli modulos`.
- **Componentes**: um cartão para cada programa externo (ffmpeg, CorridorKey, DaVinci Resolve) com
  para que serve, versão, espaço no disco, pasta, fonte oficial, licença, selo *verificado (SHA-256)*,
  os recursos que o usam e *Baixar*, *Atualizar* e *Remover* com progresso. Mostra também a placa de
  vídeo e o OpenGL. Os downloads conferem o SHA-256 antes de instalar e passam por uma fila de
  tarefas que dá para cancelar.
- Perfis de entrada **HLG** e **PQ / HDR10** (Rec.2100, cinza de referência da BT.2408 em 0,18), também
  no plugin do DaVinci. Ao abrir um vídeo HDR (o padrão do iPhone), o perfil é escolhido sozinho pelos
  metadados do arquivo, com aviso na barra de status; projetos reabertos e presets nunca mudam o perfil.
- Plugin do DaVinci: controle **Faixa do vídeo** (*Vídeo (faixa legal)*, o padrão, ou *Cheia*) nos nós
  Cor e Laboratório.
- Opção avançada **Log reescalado (HDMI Limited)** para gravações N-Log feitas pela saída HDMI em faixa
  limitada.
- Terminal: `pelicula-cli info` mostra a faixa, a transferência e o perfil HDR do arquivo;
  `--resolucao` aceita `1080` ou `1080p`.
- **Exportação por plataforma**: 27 destinos (YouTube, Shorts, Instagram Reels, Stories e Feed, TikTok,
  Kwai, WhatsApp, Discord, X, Facebook, LinkedIn, Vimeo, Spotify, Festival, Arquivo e outros). Cada um
  preenche quadro, codec, som e limites (tudo continua editável) e a janela mostra uma prévia do
  resultado. Nada é enviado: o app só grava o arquivo.
- Na exportação: **Quadro** e **Encaixe** (cortar, bordas pretas ou fundo desfocado, com o look já no
  quadro final), **Tamanho alvo** (duas passadas no H.264 e no H.265), **Volume alvo** em LUFS com
  **pico real**, **Grão para redes** e avisos de duração e tamanho acima do limite da plataforma (com
  *Exportar só os primeiros N s*). A fila mostra a etapa (medindo o volume, passada 1 de 2).
- **Área segura** na prévia (TikTok, Reels, Shorts, título e ação da TV): só na tela, nunca no arquivo.
- Terminal: comando `plataformas` e as opções `--plataforma`, `--quadro`, `--encaixe`, `--tamanho-alvo`,
  `--volume`, `--pico` e `--grao-redes`.
- **Marcadores** no modo Edição (8 cores, nome e nota; aparecem também na barra do modo Película) e
  **capítulos**: *Copiar capítulos para o YouTube…* confere as regras do YouTube, e as exportações em
  MP4, MOV e MKV ganham *Incluir capítulos*.
- **Medidor de som** ao lado da prévia (módulo *Medidor de som*): picos dos canais com retenção e as
  leituras momentânea, curta e integrada (LUFS, EBU R 128) e o pico real.
- **Transição de som** de potência constante entre clipes vizinhos (até 5 s) e **fades curtos** (5 ms)
  nas emendas de som, para não estalar. Os fades vêm ligados nas sequências novas; projetos antigos
  continuam saindo iguais.
- **Notificações do sistema** (módulo *Notificações do sistema*): exportação concluída ou com erro, fila
  concluída, download de componente e versão nova. Clicar abre a pasta do arquivo. A página em
  Configurações escolhe os tipos, se avisa só com a janela em segundo plano, o som e o piscar do ícone.
- **Recuperação automática** (módulo *Recuperação automática*): cópias de segurança do projeto aberto a
  cada minuto (as 5 últimas), separadas do seu `.plc`. Se o app fechar inesperadamente, ao abrir de
  novo ele oferece *Recuperar*, *Abrir o salvo* ou *Descartar*, e as exportações que estavam na fila
  podem voltar (recomeçam do início). Relatório de erro só no computador (nada é enviado), com *Copiar
  relatório* e *Abrir pasta*.
- **Recorte por IA (CorridorKey, Beta)**: tira o fundo verde ou azul de um vídeo com o
  [CorridorKey 2.0](https://github.com/nikopueringer/CorridorKey2.0), da Corridor Digital, e grava o
  recorte com transparência (ProRes 4444 com alfa) e a máscara, ou EXR. Começa desligado (ligue em
  **Recursos**). O CorridorKey é um **download à parte de cerca de 7,6 GB** (uns 10,7 GB no disco) em
  **Componentes**, direto das fontes oficiais, com versões e SHA-256 fixos, e precisa de placa **NVIDIA
  RTX série 30 ou mais nova**. Roda num processo separado, pela fila de tarefas. O que você recorta é seu
  e pode ser usado comercialmente; empresas com faturamento anual acima de US$ 20 milhões precisam de
  licença da Corridor (corridorkey.com).

### Alterado
- *Dependências e atualizações…* virou *Componentes…*, uma página das Configurações.
- Atalhos: no modo Edição, **M** agora põe um marcador, e o som da prévia passa para **Shift+M**, que vale
  nos dois modos. No modo Película, **M** continua ligando e desligando o som. **Shift+↑/↓** pulam entre
  os marcadores.

### Corrigido
- **S-Log3, V-Log e N-Log** eram lidos na escala errada em vídeos de faixa limitada (o normal das
  câmeras): o cinza saía até 0,15 stop escuro e as altas luzes até 0,36 stop claras. Agora cada curva
  usa o domínio da especificação do fabricante (código de 10 bits ou sinal), no app e no plugin.
- Vídeo **vertical** encolhia nas qualidades prontas (1080 × 1920 em *Redes sociais 1080p* saía
  608 × 1080): a resolução agora vale para o lado menor, e a janela mostra o tamanho que vai sair.
- **Exportação segura**: o arquivo é gravado num parcial (`nome.parcial-pelicula.mp4`) e só troca o
  destino no fim. Cancelar, um erro ou o app fechar no meio não deixam arquivo quebrado e não apagam o
  arquivo antigo. O mesmo vale para quadros salvos, LUTs, presets e sequências de imagens.
- Aplicar um preset não troca mais o perfil de entrada (ele descreve o vídeo, não o look).
- **Otimizar para grão** (*tune grain*) ficava sempre desligado nas exportações feitas pela janela;
  agora vale quando o codec tem essa opção.
- A janela de atualização fechava o app mesmo quando o fechamento era cancelado (projeto não salvo ou
  exportações em andamento). Agora nada é instalado e o app continua aberto.

## [1.3.0] - 2026-10-19

### Adicionado
- **Modo Edição** (seletor *Película | Edição* no topo, Ctrl+1 / Ctrl+2): montagem em faixas de
  vídeo e de áudio antes do look de película. Importar vídeos, imagens e músicas (Ctrl+I ou
  arrastar), dividir no cursor (S), aparar pelas bordas, mover entre faixas (sobrescreve o que
  estiver embaixo), apagar com ou sem fechar o espaço, ímã, zoom da linha do tempo, imagem e som
  ligados (dá para desligar), velocidade (câmera lenta e acelerado), congelar quadro e transições
  (dissolver, surgir do preto/branco, sumir). Desfazer/refazer de toda a edição.
- **Cor e luz por clipe**, simples de usar: exposição, contraste, realces, sombras, brancos, pretos,
  brilho, temperatura, tonalidade, vibração, saturação, matiz, rodas de cor (sombras, tons médios,
  altas luzes), curva de tons por faixa, cor por faixa (HSL de 8 cores), nitidez, clareza, desfoque,
  redução de ruído, vinheta, desbotado, enquadramento (escala, posição, rotação, espelhar, cortar,
  opacidade, mesclagem). Ajustes rápidos (Mais vivo, Quente, Frio, Suave, Contraste, P&B, Antigo),
  **cor automática**, copiar/colar ajustes e aplicar a todos os clipes.
- **Som por clipe**: volume, mudo, balanço, aumentar no início e diminuir no fim, graves, médios,
  agudos, realçar voz, redução de ruído e normalizar volume; faixas com mudo, solo, trava e volume;
  forma de onda na linha do tempo. A prévia toca a mesma mixagem que a exportação grava.
- **Medidores de cor**: histograma, forma de onda, parada RGB e vetorscópio.
- O modo Película aplica o look na montagem (exportação, salvar quadro, estimativa e fila
  incluídos). Projetos `.plc` guardam a montagem (`"formato": 2` só quando há edição).
- **Laboratório (negativo e cópia)**: emulação por densidade, como no laboratório de verdade —
  negativo (curva característica e sensibilidade de cada camada), revelação forçada (push/pull),
  luzes da copiadora em pontos (vermelho, verde, azul e densidade), película de cópia com diafonia
  dos corantes e processos **Technicolor 3 tiras** (com chave preta), **Technicolor 2 cores** e
  **retenção de prata**. O cinza médio sai neutro em qualquer combinação. Novos presets no grupo
  *Laboratório*.
- **Controle de pele** no look: matiz e luz da pele, além da saturação.
- Controles no estilo do tutorial de Technicolor da Cinesumer (SumerFade): **separação de cores
  (Hue Split)** com eixo ajustável, **densidade dos vermelhos/verdes/azuis**, **saturação do filme**
  e **saturação final**, **pé da cópia**, **rolagem das sombras e das altas luzes**, **pele** no
  Laboratório, **bleach bypass no negativo e na cópia** e **curva neutra** do negativo e da cópia.
- Negativos Vision2 5201 50D, Eastman ECN-II 5297 250D, Vision 5246 250D, Vision 5263 500T e
  Vision2 Expression 5229 500T; cópias Eastman EXR Print 5386 e Eastman Color Print 5385 (todos
  aproximações artísticas). Presets *Technicolor (5297 → 5386, Hue Split)* e *Teal & orange
  (5201 → 2393, Hue Split)*.
- Perfis de entrada **Blackmagic Film Gen 5** (Blackmagic Wide Gamut), **ARRI LogC4** (Wide Gamut 4)
  e **Apple Log** (iPhone), também para LUTs; o palpite do espaço do LUT reconhece os nomes.
- **MTF da película** (lente): suaviza a nitidez digital fina por enquadramento, com quantidade.
- **Curva** no painel *Ajustes*: mostra a curva do look em R, G e B (calculada na GPU com o mesmo
  caminho de cor da exportação).
- **Plugin OpenFX do PeliculaConverter — funciona no DaVinci Resolve gratuito** (o DCTL exige o
  Studio): um efeito nativo em C++ com o look inteiro (perfil da câmera, Laboratório, cor da película,
  grão, halação, bloom, lente e MTF, tremor, defeitos e moldura), 44 presets e carregar um look `.json`
  exportado pelo app. O código de cor é gerado das mesmas tabelas e da mesma matemática do app (cor a
  menos de 0,0001; quadro inteiro a ~1 nível de 8 bits). Compilado pelo GitHub Actions (Windows e Linux)
  e embutido em todos os pacotes; instale em *Configurações → Plugin para o DaVinci Resolve… → Instalar
  o plugin OpenFX* (pede administrador) ou com `pelicula-cli resolve --ofx-instalar`. Calcula na CPU.
- Plugin do DaVinci: nó **PeliculaConverter Laboratorio** com **Mostrar curva**, todos os controles
  novos nos nós Cor e Laboratorio e o MTF no nó Textura.
- **Plugin para o DaVinci Resolve** (*Configurações → Plugin para o DaVinci Resolve…* ou
  `pelicula-cli resolve --instalar`): DCTLs *PeliculaConverter Cor*, *Textura* e *Projetor* (a
  ordem dos nós é como LOOK → LAB → PRINT), um DCTL por preset e LUTs `.cube` de todos os presets
  para o Resolve gratuito e o Premiere. A cor do plugin é conferida contra o app nos testes.

### Corrigido
- Arrastar o cursor na linha do tempo não faz mais o cursor voltar para trás por um instante: quadros
  de posições anteriores que chegam atrasados aparecem na prévia, mas o cursor fica onde você deixou.
- Painéis laterais (looks, ajustes, mídia e clipe) redimensionam direito: não recolhem por inteiro ao
  arrastar o divisor e não cortam opções. As barras da prévia, do player, da linha do tempo e do
  topo encolhem em etapas (botões só com ícone, extras escondidos, quebra de linha), a linha do
  tempo do player sobe para uma linha própria quando falta espaço e os looks se reorganizam em
  duas, três ou mais colunas conforme a largura (o painel nunca fica mais estreito que duas
  miniaturas lado a lado).

## [1.2.2] - 2026-10-16

### Adicionado
- **Desfoque da bitola** (Película): chave para ligar e desligar a maciez natural da bitola (o que
  deixa o Super 8 e o 8 mm mais "embaçados"), com a dica mostrando quanto cada bitola desfoca. O
  controle de força virou *Intensidade do desfoque* (antes *Perda de nitidez da bitola*; a chave
  `bitola_resolucao` não muda). Projetos e presets antigos continuam iguais, com o desfoque ligado.

### Mudado
- **Tela cheia da prévia**: a resolução escolhida continua (antes passava sozinha para a original) e
  pode ser trocada na própria tela cheia; a barra da prévia (comparação, zoom, resolução) e o
  player (reproduzir, linha do tempo, entrada/saída, volume) continuam visíveis. Somem só a barra
  superior, os painéis de looks e de ajustes e a barra de status. A barrinha flutuante saiu, e o
  botão de tela cheia vira *Sair da tela cheia*.
- Atualização no Windows: o app reabre direto (sem passar pelo shell do Windows) depois de instalar.
  Com o shell, a primeira abertura do executável novo demorava ~25 s e criava uma segunda instância
  passageira.

## [1.2.1] - 2026-10-16

### Corrigido
- **Atualização automática no Windows**: o app baixava e conferia a versão nova, fechava, mas a
  instalação nunca começava e o app não reabria. O script de instalação era entregue a um
  PowerShell iniciado com `DETACHED_PROCESS`, e sem console (o app empacotado não tem console) o
  PowerShell encerrava antes de rodar o script, sem erro. Agora ele roda com um console próprio e
  invisível (`CREATE_NO_WINDOW`) e continua depois que o app fecha. O script também grava
  `atualizar.log` e o `msiexec` grava `instalar.log` na pasta do download, e caminhos com apóstrofo
  são escapados. Quem está na 1.1.0 ou 1.2.0 precisa instalar a próxima versão manualmente uma
  vez, porque o atualizador dessas versões é o que tem o defeito. (#26)

## [1.2.0] - 2026-10-16

### Adicionado
- **Prévia em tela cheia** (botão na barra da prévia ou `F11`): só o vídeo ocupa a tela, na
  resolução original, para ver detalhes. Barrinha flutuante com zoom e *Sair*, que some com o mouse
  parado, e dica das teclas ao entrar. `Esc` ou `F11` saem e a qualidade de prévia escolhida volta.
  `Shift+F11` mantém a tela cheia da janela inteira, que antes ficava no `F11`.
- **Zoom livre de 10% a 1600%**: lupas − e + na barra da prévia, teclas `+`/`−` e roda do mouse,
  em passos de 25%. O zoom pode ficar menor que o tamanho que cabe na janela, com a imagem
  centralizada. O zoom atual aparece sempre na barra.
- O botão **Abrir** (`Ctrl+O`) também mostra os projetos `.plc`, que abrem como em *Abrir projeto*.

### Corrigido
- O selo de versão do README e a versão do pacote no `pyproject.toml` tinham ficado em 1.0.0. O selo
  agora mostra a última release do GitHub, e o `pyproject.toml` lê a versão de
  `pelicula.__version__`, que passa a ser o único lugar onde ela é escrita. Um teste garante isso.

## [1.1.0] - 2026-10-16

### Adicionado
- Interface em **português do Brasil, inglês e espanhol** (#1): escolha do idioma no primeiro
  acesso (com o idioma do sistema selecionado, ou inglês), troca em Configurações > Idioma,
  catálogos em `pelicula/locales/`, separador decimal por idioma, ferramenta
  `tools/i18n_extract.py` e teste que exige tradução para todo texto visível.
- **Tela de boas-vindas** (#2) com banner, versão e data por extenso, projetos recentes com
  miniatura, atalhos (abrir vídeo, abrir projeto, cena de teste, novidades) e aviso de atualização.
- **Projetos `.plc`** (#3): salvam vídeo (caminho absoluto e relativo), look, todos os ajustes,
  entrada/saída, quadro atual, comparação, prévia e miniatura. Menu Projeto (novo, abrir,
  recentes, salvar, salvar como), "•" no título com mudanças pendentes, pergunta ao fechar,
  localizar o vídeo se ele sumir, abertura por arrastar ou pela linha de comando.
- **Novidades em linguagem simples** (#4) em `pelicula/novidades/` nos três idiomas, mostradas
  depois de cada atualização; `release_vX.Y.Z.md` vira o texto da release.
- **Atualização automática** pelo GitHub Releases (#5): verificação diária em segundo plano,
  download do pacote do mesmo tipo da instalação, conferência do SHA-256 com `SHA256SUMS.txt` e
  instalação depois que o app fecha, reabrindo sozinho.
- **Modo terminal `pelicula-cli`** (#10): `exportar`, `projeto`, `quadro`, `lut`, `presets`,
  `parametros`, `qualidades`, `info`, `ffmpeg`, `versao` (com apelidos em inglês), barra de
  progresso ou JSON, cancelamento com Ctrl+C.
- **Som na prévia** (#11), sincronizado com o quadro mostrado, com botão de mudo (tecla M) e volume.
- Atalhos novos: `Ctrl+N`, `Ctrl+Shift+O`, `Ctrl+S`/`Ctrl+Shift+S` para projetos; salvar preset
  passou para `Ctrl+Alt+S` e salvar quadro para `Ctrl+Shift+F`.
- **Instalador para Windows (`.msi`)** (#6): instalação por usuário, sem administrador, em
  `%LOCALAPPDATA%\Programs\PeliculaConverter`; atalho no Menu Iniciar e, opcionalmente, na Área de
  Trabalho; projetos `.plc` abrem com dois cliques; pasta do app no `PATH` do usuário (para o
  `pelicula-cli`); ícone e links em *Adicionar ou remover programas*; uma versão nova substitui a
  antiga no mesmo lugar e lembra a pasta escolhida. Telas em português com a licença MIT.
- **Pacote para Debian/Ubuntu (`.deb`)** (#6): app em `/opt/pelicula-converter`, comandos
  `pelicula-converter` e `pelicula-cli`, atalho no menu (português, inglês e espanhol), tipo de
  arquivo `application/x-pelicula-project` para os projetos `.plc`, ícones, dependências do
  sistema pelo `apt` e `ffmpeg` recomendado.
- Executável de terminal **`pelicula-cli`** junto com o app em todos os pacotes (mesma pasta,
  sem duplicar bibliotecas) e o comando `pelicula-cli` ao instalar pelo `pip`.
- `pelicula-install.json` ao lado do executável em cada pacote (`msi`, `zip`, `deb`, `tar` ou
  `dmg`, com a versão), para o atualizador saber como o app foi instalado.
- Release com `SHA256SUMS.txt` de todos os arquivos e texto vindo de
  `pelicula/novidades/release_<tag>.md`.
- Avisos no Discord (#8): nova versão publicada (com resumo e links dos pacotes) e build quebrado no
  `main`.
- Assinatura de código opcional no CI (#7; certificado em segredos do repositório) e o guia
  [docs/ASSINATURA.md](docs/ASSINATURA.md) com as opções e custos.
- `build.sh` para gerar o `.tar.gz` e o `.deb` no Linux; o `build.bat` também gera o `.msi`
  quando o WiX Toolset está instalado.
- `.dmg` para macOS preparado (o suporte ao macOS continua desativado).
- Opção **Procurar atualizações automaticamente** em Configurações, que desliga as consultas feitas
  ao abrir (versão nova do app no GitHub e do ffmpeg no gyan.dev).
- Seções **Política de assinatura de código** e **Privacidade** no README (requisitos da SignPath
  Foundation) e link para as duas no texto da release.
- Executáveis do Windows com nome, versão, descrição e direitos autorais do produto
  (*Propriedades → Detalhes*), lidos de `pelicula.__version__`.

### Mudado
- CI (#9): pushes em outras branches e pull requests rodam só os testes; os pacotes são gerados no
  `main`/`master`, em tags `v*` e na execução manual, e o `.msi` e o `.deb` são instalados e
  removidos de verdade no runner para conferir.
- Os executáveis do Linux passam a ser gerados no Ubuntu 22.04: o `.deb` e o `.tar.gz` funcionam
  no Ubuntu 22.04+ e no Debian 12+ (glibc 2.35).

### Corrigido
- Preferências do app não são mais gravadas no registro durante testes automatizados:
  `PELICULA_SETTINGS_DIR` leva tudo para um `.ini` (também serve para modo portátil) (#12).
- Modo terminal: o motor de GPU agora é criado na mesma thread que o usa.

## [1.0.0] - 2026-10-16

Primeira versão pública.

### Adicionado

#### Motor de película na GPU
- Pipeline OpenGL 3.3 (moderngl) em passos: base → maciez/nitidez → halação, bloom e névoa (com
  mipmaps) → ruído do grão → passo final com curva da película, cópia, LUT, grão, defeitos,
  mistura, moldura e pontilhado.
- Processamento em luz linear de cena com conversão de gamut para Rec.709.
- Prévia e exportação pelo mesmo caminho (`look.build_plan()` + `Engine.render()`), com todos os
  efeitos animados calculados a partir do número do quadro: o quadro N da prévia é o quadro N do
  arquivo final (exportação FFV1 16 bits idêntica, bit a bit, ao render do motor).
- Parâmetros de distância em "px@1080", independentes da resolução.
- Saída em 8 ou 16 bits por canal; pontilhado contra faixas em 8 bits.

#### Película, entrada e cor
- Bitolas 8 mm, Super 8, 16 mm, Super 16, 35 mm, 65 mm e IMAX 70 mm (15/70), cada uma com grão,
  maciez, tremor, vinheta, halação e proporção próprios.
- Sensibilidade de ISO 50 a ISO 3200.
- Cópias Kodak 2383, Kodak 2393 e Fuji 3513, com força ajustável.
- Perfis de entrada Rec.709/sRGB, Linear, Nikon N-Log, Sony S-Log3 (S-Gamut3.Cine), ARRI LogC3
  (EI 800), Panasonic V-Log, RED Log3G10 (RWG), DaVinci Intermediate (DWG) e Cineon/DPX log.
- Exposição, temperatura e tonalidade em luz linear.
- Curva da emulsão: contraste, tom médio, preto e branco da película, suavidade das altas luzes e
  das sombras, saturação, densidade de cor, cor e força das sombras e das altas luzes, equilíbrio
  e envelhecimento.
- Ajustes avançados: contraste e equilíbrio por canal, matiz dos verdes e dos azuis, saturação da
  pele.
- Preto e branco com filtros (pancromático, vermelho, laranja, amarelo, verde, azul) e viragens
  (sépia, selênio, cianótipo, ouro).

#### Luz, lente, projeção e defeitos
- Halação (força, raio, limiar em EV, cor), bloom e névoa de filtro difusor.
- Lente: maciez, recuperar detalhe, aberração cromática, distorção barril/almofada e vinheta
  (raio, suavidade, redondeza).
- Projetor: tremor horizontal, vertical e de rotação, com velocidade; cintilação.
- Defeitos da película, cada um com chave própria: poeira (escura, clara ou mista), riscos, fio de
  cabelo, manchas químicas, clarões de fim de rolo, marcas de troca de rolo, cor instável, emendas
  e vazamento de luz.
- Moldura e proporção (1,33 a 2,76), cantos arredondados, borda suave e irregular, cor das barras.
- Scan da película com geometria real de 35 mm, 16 mm, Super 16 e Super 8: furos, linhas entre
  quadros, quadros vizinhos, texto de borda automático (código Kodak conforme ISO), cópia
  projetada ou negativo invertido, enquadramento caber/preencher e aproximação.

#### Presets e LUTs
- 33 presets prontos em seis grupos: Cinema 35 mm, Bitolas e formatos (incluindo scans de 35 mm
  e de Super 8 com furos), Preto e branco, Fotografia, Processos e estilos e Básicos.
- Painel de looks com miniaturas ao vivo do quadro atual, busca sem acentos e descrições.
- Presets do usuário em JSON: salvar como, atualizar, excluir, voltar ao preset, importar e
  exportar; valores conferidos e limitados ao carregar.
- LUT externo `.cube` 3D com espaço de entrada escolhido (Rec.709, Cineon, LogC3, S-Log3, N-Log,
  V-Log, Log3G10, DWG, Linear), posição (depois do look ou no lugar dele) e intensidade.
- Busca dos LUTs já instalados pelo Adobe Premiere Pro e pelo DaVinci Resolve (só leitura, nunca
  redistribuídos) e pasta "Meus LUTs" com o botão *Instalar LUTs…*.
- Exportação da cor do look como LUT `.cube` de 33 ou 65 pontos e pacote de LUTs com todos os
  presets.

#### Interface
- Interface em português do Brasil, tema escuro com acento âmbar, gerada a partir do esquema de
  parâmetros.
- Visualizador com modos Película, Dividido, Lado a lado e Original; espiar o original com o botão
  direito; zoom 100%/200%, roda do mouse até 1600% e arrastar.
- Linha do tempo com reprodução em tempo real, quadro a quadro, entrada/saída e repetição.
- Qualidade da prévia (540p, 720p, 1080p, original), histograma RGB, desfazer/refazer (300 passos),
  atalhos de teclado, arrastar e soltar (vídeos, imagens, `.cube`, `.json`) e arquivos pela linha
  de comando.
- Cena de teste embutida (cartela de cores, rampa de cinza, faixa de matiz e luzes fortes).
- Salvar o quadro atual em PNG 16 bits, TIFF 16 bits ou JPEG na resolução original.
- Sessão lembrada entre aberturas (look, geometria, comparação, qualidade da prévia, exportação).

#### Exportação
- Codecs: H.264/H.265 (x264/x265), NVENC, Quick Sync e AMF (listados só se funcionarem de
  verdade), AV1 (SVT-AV1), VP9/WebM, Xvid AVI, GIF, ProRes (Proxy a 4444 XQ), DNxHR (LB a 444),
  FFV1 16 bits, sequências PNG/TIFF e imagens PNG/TIFF/JPEG/WebP.
- Qualidades prontas: Original — mesmo formato, MP4, MOV, MKV, YouTube 4K (H.265 10 bits e H.264),
  Full HD, redes sociais, leve 720p, WebM, AVI, GIF, masters ProRes 422 HQ, ProRes 4444 XQ e
  DNxHR HQX, FFV1 sem perdas, GPU (NVIDIA/Intel/AMD) e sequência PNG 16 bits.
- Áudio: copiar, AAC 320/192, MP3 320, Opus 192, PCM 24 bits ou sem áudio, com correção
  automática para o recipiente.
- Resolução (até 8K) e quadros por segundo de saída; trecho marcado ou vídeo inteiro.
- Opções de desempenho: núcleos, prioridade do processo, decodificação por hardware, placa NVENC e
  buffer de quadros com cálculo de memória.
- Tempo estimado medido exportando um trecho real com as opções escolhidas (ignora o aquecimento
  do codificador).
- Fila de exportação em segundo plano, com contexto de GPU próprio, leitura/GPU/gravação em
  paralelo, progresso pelo próprio ffmpeg, velocidade, tempo restante e cancelamento.
- Leitura e gravação por *named pipes* no Windows (mais rápido que stdin/stdout para 4K).

#### Dependências e plataformas
- Gerenciador de dependências (*Configurações → Dependências e atualizações…*): mostra ffmpeg,
  GPU/OpenGL, processador, memória e bibliotecas Python.
- Download automático do ffmpeg quando ausente, de fontes confiáveis e conferido por SHA-256:
  gyan.dev *release essentials* no Windows e build estático do BtbN no Linux, instalado só para o
  usuário (`%LOCALAPPDATA%\PeliculaConverter\ffmpeg` ou `~/.local/share/PeliculaConverter/ffmpeg`),
  sem administrador.
- Aviso de atualização quando o ffmpeg é mais antigo que 7.0 (ou build de desenvolvimento antigo).
- Rodando pelo código-fonte, oferta de instalar `moderngl`/`numpy` com o `pip` se faltarem.
- Suporte a Windows 10/11 e Linux; macOS preparado e desativado.

#### Projeto
- Logo, ícone `.ico` com vários tamanhos e banner.
- `pyproject.toml` (comando `pelicula-converter`), `requirements.txt` e receita do PyInstaller
  (pasta única, Windows e Linux).
- Scripts `instalar.bat`, `executar.bat` e `build.bat` (Windows) e `instalar.sh` e `executar.sh`
  (Linux).
- CI no GitHub Actions: testes e build em Windows e Linux, artefatos `.zip` e `.tar.gz` e Release
  automática em tags `v*`; job de macOS pronto e desativado.
- Testes com pytest (os de GPU e de ffmpeg se pulam sozinhos quando não há OpenGL 3.3 ou ffmpeg).
- Documentação: README, AGENTS.md/CLAUDE.md, `docs/ARQUITETURA.md` e `docs/EFEITOS.md`.

# Changelog

Todas as mudanças importantes deste projeto ficam registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto usa
[Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado
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

### Planejado
- Suporte ao macOS (o código, o `PeliculaConverter.spec` e o job do CI já estão preparados, mas
  desativados).

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

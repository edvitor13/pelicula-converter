# Changelog

Todas as mudanças importantes deste projeto ficam registradas aqui.

O formato segue o [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/) e o projeto usa
[Versionamento Semântico](https://semver.org/lang/pt-BR/).

## [Não lançado]

### Adicionado
- **Instalador para Windows (`.msi`)**: instalação por usuário, sem administrador, em
  `%LOCALAPPDATA%\Programs\PeliculaConverter`; atalho no Menu Iniciar e, opcionalmente, na Área de
  Trabalho; projetos `.plc` abrem com dois cliques; pasta do app no `PATH` do usuário (para o
  `pelicula-cli`); ícone e links em *Adicionar ou remover programas*; uma versão nova substitui a
  antiga no mesmo lugar e lembra a pasta escolhida. Telas em português com a licença MIT.
- **Pacote para Debian/Ubuntu (`.deb`)**: app em `/opt/pelicula-converter`, comandos
  `pelicula-converter` e `pelicula-cli`, atalho no menu (português, inglês e espanhol), tipo de
  arquivo `application/x-pelicula-project` para os projetos `.plc`, ícones, dependências do
  sistema pelo `apt` e `ffmpeg` recomendado.
- Executável de terminal **`pelicula-cli`** junto com o app em todos os pacotes (mesma pasta,
  sem duplicar bibliotecas) e o comando `pelicula-cli` ao instalar pelo `pip`.
- `pelicula-install.json` ao lado do executável em cada pacote (`msi`, `zip`, `deb`, `tar` ou
  `dmg`, com a versão), para o atualizador saber como o app foi instalado.
- Release com `SHA256SUMS.txt` de todos os arquivos e texto vindo de
  `pelicula/novidades/release_<tag>.md`.
- Avisos no Discord: nova versão publicada (com resumo e links dos pacotes) e build quebrado no
  `main`.
- Assinatura de código opcional no CI (certificado em segredos do repositório) e o guia
  [docs/ASSINATURA.md](docs/ASSINATURA.md) com as opções e custos.
- `build.sh` para gerar o `.tar.gz` e o `.deb` no Linux; o `build.bat` também gera o `.msi`
  quando o WiX Toolset está instalado.
- `.dmg` para macOS preparado (o suporte ao macOS continua desativado).

### Mudado
- CI: pushes em outras branches e pull requests rodam só os testes; os pacotes são gerados no
  `main`/`master`, em tags `v*` e na execução manual, e o `.msi` e o `.deb` são instalados e
  removidos de verdade no runner para conferir.
- Os executáveis do Linux passam a ser gerados no Ubuntu 22.04: o `.deb` e o `.tar.gz` funcionam
  no Ubuntu 22.04+ e no Debian 12+ (glibc 2.35).

### Planejado
- Suporte ao macOS (o código, o `PeliculaConverter.spec` e o job do CI já estão preparados, mas
  desativados).

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

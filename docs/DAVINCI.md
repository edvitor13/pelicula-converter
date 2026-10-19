# Plugin do PeliculaConverter para o DaVinci Resolve

O PeliculaConverter gera um pacote de **DCTLs** (o "plugin" de cor do Resolve) e de **LUTs .cube** com o
mesmo look do app. A ideia é a mesma dos pacotes de emulação de película vendidos para o Resolve: três
nós em série, na ordem de um laboratório de cinema — **LOOK → LAB → PRINT** —, aqui chamados de
**Cor → Textura → Projetor**.

| Nó | O que faz | Igual ao app? |
|---|---|---|
| **PeliculaConverter Cor** | Perfil do vídeo (Rec.709, log das câmeras), exposição e balanço, **Laboratório** (negativo, revelação, luzes da copiadora, cópia, Technicolor 3 tiras / 2 cores, retenção de prata), look de película (curva, saturação, densidade, tons de sombra/luz, pele, P&B e viragens), cópia 2383/2393/3513, envelhecimento e força geral. | **Sim.** É a mesma conta de `colorPipe()` (diferença < 0,002 nos testes, normalmente 0,000001). |
| **PeliculaConverter Textura** | Grão (tamanho, aspereza, cor, resposta por tom, animado), halação, bloom, névoa (filtro difusor), maciez da bitola e da lente, recuperar detalhe, aberração cromática, distorção e vinheta. | Grão, lente, maciez e vinheta: **sim** (< 1/255). Halação, bloom e névoa: **aproximação** numa passada (veja *Limitações*). |
| **PeliculaConverter Projetor** | Tremor do quadro, cintilação, clarões de fim de rolo, cor instável, emendas, vazamento de luz, poeira, riscos, fio de cabelo, manchas químicas, marcas de troca de rolo e moldura (proporção, cantos, borda irregular). | **Sim** (< 1/255), quadro a quadro, com as mesmas sementes. |

Além dos três nós "em branco" (que já abrem com o preset inicial do app, Kodak Vision3 250D), o pacote
traz:

- **Presets/** — para cada preset pronto do app, um nó *Cor* e um *Textura* com os valores do preset (e um
  *Projetor* quando o preset usa tremor, defeitos ou moldura). Ex.: `Kodak Vision3 500T - Cor.dctl`.
- **LUTs/** — um `.cube` de 33 pontos por preset (só a cor, entrada Rec.709). Funcionam no **Resolve
  gratuito**, no Premiere, no Final Cut, no CapCut, no OBS e em qualquer programa que aceite `.cube`.
- **LEIA-ME.txt** (português e inglês) e **VERSAO.txt** (versão do app que gerou o pacote).

## Instalar

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

## Usar no Resolve

1. Página **Color**. Crie três nós em série (Alt+S).
2. Em cada nó, arraste **OpenFX › ResolveFX Color › DCTL** e, na lista *DCTL List*, escolha
   **PeliculaConverter Cor**, **PeliculaConverter Textura** e **PeliculaConverter Projetor**, nessa ordem
   (ou os arquivos da pasta *Presets*).
3. **Gestão de cor.** No nó *Cor*, escolha em **Perfil do video** a curva da câmera (S-Log3, LogC3,
   V-Log, N-Log, Log3G10, DaVinci Intermediate, Cineon). Se a linha do tempo já está em Rec.709 /
   Gamma 2.4, deixe *Rec.709*. Outra opção é pôr um *Color Space Transform* antes do nó *Cor*
   convertendo para Rec.709 / Gamma 2.4. A saída dos três nós é Rec.709 (como no app).
4. Na *Textura* e no *Projetor*, escolha a **mesma bitola** (ela muda o tamanho do grão, a maciez, o
   tremor e a vinheta). No *Projetor*, escolha os **quadros por segundo** da linha do tempo: o tremor, a
   cintilação e os defeitos seguem o tempo real.
5. Os controles têm os mesmos nomes do app (sem acentos, porque o DCTL só aceita ASCII). Percentuais vão
   de 0 a 100; distâncias são **px em 1080p** (convertidas para a resolução do projeto, como no app).

Dicas:

- Para "ajustar a cor no laboratório", use as **luzes da copiadora** (12 pontos = 1 stop; mais vermelho =
  cópia mais ciano) e a **densidade da cópia**, junto com a *Exposição* — o mesmo fluxo de um
  laboratório de verdade.
- O nó *Cor* pode ser aplicado também como LUT (botão direito no nó › *DCTL*), com os valores padrão.
- A **Qualidade do brilho** (nó *Textura*) troca velocidade por suavidade da halação/bloom/névoa.

## Resolve Studio × gratuito

- O efeito **DCTL** (OpenFX › DCTL) é do **DaVinci Resolve Studio**. No Resolve gratuito use os **LUTs**
  da pasta `LUTs` (só a cor; grão, halação e defeitos não cabem num LUT).
- O grão e os defeitos **mudam a cada quadro** a partir do **Resolve 19.1** (`TIMELINE_FRAME_INDEX`).
  Em versões anteriores eles ficam parados (o DCTL detecta a versão e não dá erro).

## Limitações

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
  chave ou força funciona sem tabelas.
- `tests/test_resolve.py` roda o dialeto GLSL na GPU e compara com `Engine.bake_lut` (nó *Cor*: todos os
  presets, todos os perfis de entrada e todas as combinações de negativo × cópia × processo) e com
  `Engine.render` (Textura e Projetor). Também confere as regras do DCTL: só ASCII, sufixo `f` nos
  números, sem swizzles nem sobrecarga de funções, assinatura exata do `transform`, até 64 controles por
  tipo e 5 seletores de cor, rótulos seguros e únicos.
- Mudou `colorPipe` (em `shaders.py`) ou uma tabela de `look.py`? Atualize o kernel em `resolve.py` e rode
  `pytest tests/test_resolve.py`. **Nunca** instale no Resolve de verdade nos testes (use pastas
  temporárias).

Os nomes de filmes são aproximações artísticas, sem relação com os fabricantes.

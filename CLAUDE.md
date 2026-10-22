# CLAUDE.md

Leia **[AGENTS.md](AGENTS.md)** antes de mudar qualquer coisa: lá estão o mapa dos módulos, as regras
que não podem ser quebradas, como rodar e testar e as receitas (parâmetro, preset, codec, perfil de
entrada, bitola, ajuste de clipe, negativo do Laboratório, plugin do DaVinci). Detalhes técnicos em
[docs/ARQUITETURA.md](docs/ARQUITETURA.md); efeitos para o usuário em [docs/EFEITOS.md](docs/EFEITOS.md);
modo Edição em [docs/EDICAO.md](docs/EDICAO.md); plugin do DaVinci Resolve em [docs/DAVINCI.md](docs/DAVINCI.md).

## O essencial

- **Mesmo caminho para prévia e exportação**: efeitos só em `look.build_plan()` + `shaders.py` /
  `Engine.render()`. Modo Edição: clipe só em `compositor.py` + `editshaders.py` / `Engine.compose()`,
  tempo só em `timeline.Sequence` (`src_frame`, `layers_at`), som só em `audiomix.py`.
- **Dois modos**: Película (look) e Edição (montagem em faixas). A montagem é a entrada do look; se ela
  é só o arquivo inteiro sem mudanças (`Sequence.is_trivial()`), o modo Película lê o arquivo direto.
- **Determinismo por quadro**: nada de `random`/`time` no render; use número do quadro, fps e sementes.
- **px@1080**: distâncias do esquema são pixels de um quadro de 1080 linhas, convertidas com
  `scale = altura / 1080`.
- **Curvas de câmera declaram o domínio** (`look.INPUT_DOMAIN`: código de 10 bits ou sinal) e a faixa do
  arquivo chega ao shader por `build_plan(..., legal=media.legal_range(info))`; LUTs ficam no domínio da
  própria curva; o plugin do Resolve tem o controle *Faixa do vídeo*.
- **Shaders com y para baixo** (linha 0 = topo); sem inversões.
- **Um `Engine` (contexto OpenGL) por thread**; Qt de interface só na thread principal.
- **Nunca incluir LUTs proprietários** (Adobe, Blackmagic): só ler onde já estão instalados.
- **Todo texto para o usuário em PT-BR com acentos**; chaves de parâmetros sem acento.
- **Recurso opcional é módulo** (`modules.MODULES`; Beta/Experimental começa desligado): desligar só esconde a
  ferramenta, a renderização nunca consulta `modules` e um projeto salvo sai igual.
- **Parâmetros novos com padrão neutro**; não renomear chaves nem IDs de presets (vale para os ajustes de
  clipe de `editparams.py`).
- **Plugin do DaVinci acompanha a cor do app**: mudou `colorPipe` (shaders.py)? Atualize o kernel em
  `resolve.py` e rode `tests/test_resolve.py` (paridade na GPU). Nunca instale no Resolve real em testes.
- **Dependências**: só PySide6, moderngl e numpy em tempo de execução; ffmpeg externo, baixado só de
  fonte confiável com SHA-256.
- **Windows e Linux** (macOS desativado): use `system.open_path()`/`reveal()` e `Perf.popen_kwargs()`.
- **Não sobrescrever a sessão do usuário** (`QSettings`) em testes e automações; widgets do Qt em teste só
  num subprocesso *offscreen* com `QApplication` própria.

## Comandos

```bash
.venv\Scripts\python -m pytest -q          # testes (Windows); Linux: .venv/bin/python -m pytest -q
.venv\Scripts\pythonw PeliculaConverter.pyw # abrir o app (ou executar.bat / ./executar.sh)
build.bat                                   # executáveis + .zip e .msi (Windows; .msi se houver WiX)
bash build.sh                               # executáveis + .tar.gz e .deb (Linux; .deb se houver dpkg-deb)
```

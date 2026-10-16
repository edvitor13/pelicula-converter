# CLAUDE.md

Leia **[AGENTS.md](AGENTS.md)** antes de mudar qualquer coisa: lá estão o mapa dos módulos, as regras
que não podem ser quebradas, como rodar e testar e as receitas (parâmetro, preset, codec, perfil de
entrada, bitola). Detalhes técnicos em [docs/ARQUITETURA.md](docs/ARQUITETURA.md); efeitos para o
usuário em [docs/EFEITOS.md](docs/EFEITOS.md).

## O essencial

- **Mesmo caminho para prévia e exportação**: efeitos só em `look.build_plan()` + `shaders.py` /
  `Engine.render()`.
- **Determinismo por quadro**: nada de `random`/`time` no render; use número do quadro, fps e sementes.
- **px@1080**: distâncias do esquema são pixels de um quadro de 1080 linhas, convertidas com
  `scale = altura / 1080`.
- **Shaders com y para baixo** (linha 0 = topo); sem inversões.
- **Um `Engine` (contexto OpenGL) por thread**; Qt de interface só na thread principal.
- **Nunca incluir LUTs proprietários** (Adobe, Blackmagic): só ler onde já estão instalados.
- **Todo texto para o usuário em PT-BR com acentos**; chaves de parâmetros sem acento.
- **Parâmetros novos com padrão neutro**; não renomear chaves nem IDs de presets.
- **Dependências**: só PySide6, moderngl e numpy em tempo de execução; ffmpeg externo, baixado só de
  fonte confiável com SHA-256.
- **Windows e Linux** (macOS desativado): use `system.open_path()`/`reveal()` e `Perf.popen_kwargs()`.
- **Não sobrescrever a sessão do usuário** (`QSettings`) em testes e automações.

## Comandos

```bash
.venv\Scripts\python -m pytest -q          # testes (Windows); Linux: .venv/bin/python -m pytest -q
.venv\Scripts\pythonw PeliculaConverter.pyw # abrir o app (ou executar.bat / ./executar.sh)
build.bat                                   # executáveis + .zip e .msi (Windows; .msi se houver WiX)
bash build.sh                               # executáveis + .tar.gz e .deb (Linux; .deb se houver dpkg-deb)
```

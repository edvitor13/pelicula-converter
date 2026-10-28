"""whisper-cli falso para os testes da transcrição (tests/test_transcribe.py): nada de rede nem de modelo.

Aceita os argumentos que `transcribe.command()` monta, confere que o modelo, o VAD e o WAV existem, imprime
o progresso como o whisper-cli (`whisper_print_progress_callback: progress =  N%`) e grava `<-of>.json` no
formato do whisper-cli com `-ml 1 -sow` (um segmento por palavra), com as palavras de `PCTEST_WHISPER_FALA`
(padrão: "Olá, pessoal. Tudo bem?") a partir de 0,5 s, 0,4 s cada.

Controle pelos testes (variáveis de ambiente):
PCTEST_WHISPER_MODO: "ok" (padrão); "falha_gpu" (sai com erro se não tiver -ng, como um driver Vulkan com
    defeito); "sem_placa" (sem -ng, mas nenhuma placa: roda no processador, como sem driver Vulkan); "falha" (sempre erro); "memoria" (erro de memória); "lento" (demora, para cancelar); "mudo"
    (nenhuma fala reconhecida); "especiais" (marcadores como [BLANK_AUDIO] e pontuação solta);
PCTEST_WHISPER_LOG: arquivo onde cada chamada é anotada (uma linha JSON por chamada: os argumentos e o
    GGML_VK_VISIBLE_DEVICES que o processo recebeu).
"""

from __future__ import annotations

import json
import os
import sys
import time

args = sys.argv[1:]
log = os.environ.get("PCTEST_WHISPER_LOG")
if log:
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"args": args, "vk": os.environ.get("GGML_VK_VISIBLE_DEVICES")}, ensure_ascii=False)
                 + "\n")


def opt(name: str, default: str | None = None) -> str | None:
    return args[args.index(name) + 1] if name in args else default


mode = os.environ.get("PCTEST_WHISPER_MODO", "ok")
for flag in ("-m", "-f"):
    path = opt(flag)
    if not path or not os.path.isfile(path):
        print(f"error: file not found: {path}", file=sys.stderr)
        sys.exit(2)
if "--vad" in args and not os.path.isfile(opt("-vm") or ""):
    print("error: VAD model not found", file=sys.stderr)
    sys.exit(2)
print("whisper_init_with_params_no_state: use gpu    = " + ("0" if "-ng" in args else "1"), file=sys.stderr, flush=True)
if "-ng" in args or mode == "sem_placa":
    print("whisper_backend_init_gpu: no GPU found", file=sys.stderr, flush=True)
else:
    print("whisper_backend_init_gpu: using Vulkan0 backend", file=sys.stderr, flush=True)
if mode == "falha_gpu" and "-ng" not in args:
    print("ggml_vulkan: Device lost (VK_ERROR_DEVICE_LOST)", file=sys.stderr, flush=True)
    sys.exit(3)
if mode == "falha":
    print("whisper_full: failed to process audio", file=sys.stderr, flush=True)
    sys.exit(4)
if mode == "memoria":
    print("ggml_backend_cpu_buffer_type_alloc_buffer: failed to allocate buffer of size 999999999", file=sys.stderr,
          flush=True)
    sys.exit(5)
for pct in (0, 25, 50, 75, 100):
    print(f"whisper_print_progress_callback: progress = {pct:3d}%", file=sys.stderr, flush=True)
    if mode == "lento":
        time.sleep(1.0)

speech = os.environ.get("PCTEST_WHISPER_FALA", "Olá, pessoal. Tudo bem?")
words = [] if mode == "mudo" else speech.split()
segs = []
t = 500
if mode == "especiais":
    segs.append({"offsets": {"from": 0, "to": 400}, "text": " [BLANK_AUDIO]"})
for w in words:
    segs.append({"offsets": {"from": t, "to": t + 400}, "text": " " + w})
    t += 400
if mode == "especiais":
    segs.append({"offsets": {"from": t, "to": t + 50}, "text": "!"})
    segs.append({"offsets": {"from": t + 100, "to": t + 500}, "text": " ¿qué"})
    segs.append({"offsets": {"from": t + 500, "to": t + 900}, "text": " tal?"})
lang = opt("-l", "auto")
data = {"systeminfo": "falso", "model": {"type": "falso"},
        "params": {"model": opt("-m"), "language": lang, "translate": False},
        "result": {"language": "pt" if lang == "auto" else lang},
        "transcription": [{"timestamps": {}, "offsets": s["offsets"], "text": s["text"]} for s in segs]}
out = opt("-of", "saida") + ".json"
with open(out, "w", encoding="utf-8") as fh:
    json.dump(data, fh, ensure_ascii=False)
print(f"output_json: saving output to '{out}'", file=sys.stderr)

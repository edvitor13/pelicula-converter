"""Transcrição local (whisper.cpp): comando, progresso, leitura do resultado, volta para o processador,
cancelamento e erros — com um whisper-cli falso (tests/whisper_falso.py), sem rede nem modelo.

O teste com o whisper.cpp de verdade só roda com PELICULA_TESTE_WHISPER=1 (baixa o motor, o modelo small e
o VAD numa pasta temporária, ou em PELICULA_TESTE_WHISPER_DIR para reaproveitar entre execuções) e
PELICULA_TESTE_WHISPER_ARQUIVO=<vídeo ou som com fala>; PELICULA_TESTE_WHISPER_CPU=1 força o processador.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from pelicula import jobs, subtitles as sb, timeline as tl, tools, transcribe as tc
from pelicula.subtitles import Cue, Word

FAKE = Path(__file__).with_name("whisper_falso.py")


@pytest.fixture
def fake_engine(tmp_path, monkeypatch):
    """Motor falso + modelo e VAD de mentira; anota as chamadas em `chamadas.txt`."""
    model, vad = tmp_path / "modelo.bin", tmp_path / "vad.bin"
    model.write_bytes(b"modelo")
    vad.write_bytes(b"vad")
    log = tmp_path / "chamadas.txt"
    monkeypatch.setenv("PCTEST_WHISPER_LOG", str(log))
    monkeypatch.delenv("PCTEST_WHISPER_MODO", raising=False)
    monkeypatch.setattr(tc, "temp_dir", lambda: tmp_path / "cache")
    eng = tc.Engine((sys.executable, str(FAKE)), model, vad)
    object.__setattr__(eng, "log", log)          # só para os testes conferirem as chamadas
    return eng


def calls(eng) -> list[list[str]]:
    path = eng.log
    return [json.loads(line)["args"] for line in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []


def vk_env(eng) -> list:
    """O GGML_VK_VISIBLE_DEVICES que cada chamada recebeu."""
    return [json.loads(line)["vk"] for line in eng.log.read_text(encoding="utf-8").splitlines()]


def wav(tmp_path) -> Path:
    p = tmp_path / "som.wav"
    p.write_bytes(b"RIFF....WAVE")
    return p


# ------------------------------------------------------------------ peças puras
def test_command_line(fake_engine, tmp_path):
    opts = tc.Options(language="pt", threads=3)
    cmd = tc.command(fake_engine, tmp_path / "a.wav", tmp_path / "saida", opts, gpu=True)
    assert cmd[:2] == [sys.executable, str(FAKE)]
    for flag in ("-oj", "-sow", "-sns", "-pp", "--vad"):
        assert flag in cmd
    assert cmd[cmd.index("-ml") + 1] == "1" and cmd[cmd.index("-l") + 1] == "pt" and cmd[cmd.index("-t") + 1] == "3"
    assert cmd[cmd.index("-vm") + 1] == str(fake_engine.vad) and "-ng" not in cmd
    cpu = tc.command(fake_engine, tmp_path / "a.wav", tmp_path / "saida", tc.Options(language="xx; rm"), gpu=False)
    assert "-ng" in cpu and cpu[cpu.index("-l") + 1] == "auto"
    assert tc.threads_for(tc.Options(), gpu=True) == 4 and 1 <= tc.threads_for(tc.Options(), gpu=False) <= 8


def test_parse_progress():
    assert tc.parse_progress("whisper_print_progress_callback: progress =  45%") == 45
    assert tc.parse_progress("progress = 100%") == 100
    assert tc.parse_progress("whisper_model_load: n_vocab = 51865") is None


def test_parse_output_words_punctuation_and_markers():
    data = {"result": {"language": "es"}, "transcription": [
        {"offsets": {"from": 0, "to": 300}, "text": " [BLANK_AUDIO]"},
        {"offsets": {"from": 300, "to": 320}, "text": ""},
        {"offsets": {"from": 400, "to": 800}, "text": " Hola"},
        {"offsets": {"from": 800, "to": 850}, "text": ","},
        {"offsets": {"from": 900, "to": 950}, "text": " ¿"},
        {"offsets": {"from": 950, "to": 1300}, "text": "qué"},
        {"offsets": {"from": 1300, "to": 2300}, "text": " tal muchacho?"},
        {"offsets": {"from": "x", "to": 1}, "text": " ruim"},
    ]}
    words, lang = tc.parse_output(data, offset=10.0)
    assert lang == "es"
    assert [w.text for w in words] == ["Hola,", "¿qué", "tal", "muchacho?"]
    assert words[0].start == pytest.approx(10.4) and words[0].end == pytest.approx(10.85)
    assert words[2].start == pytest.approx(11.3) and words[3].end == pytest.approx(12.3)   # dividido pelo tamanho
    assert words[2].end == pytest.approx(11.3 + 1.0 * 3 / 12)                          # "tal" = 3 de 12 letras
    capped, _lang = tc.parse_output(data, offset=10.0, limit=11.0)
    assert max(w.end for w in capped) <= 11.0
    assert tc.parse_output({}, 0) == ([], "")


# ------------------------------------------------------------------ motor falso
def test_run_engine_gpu_ok_with_progress(fake_engine, tmp_path):
    seen = []
    words, lang, device = tc.run_engine(fake_engine, wav(tmp_path), tc.Options(), tmp_path, offset=2.0,
                                        progress=lambda s, d, t: seen.append((s, d, t)))
    assert device == "gpu" and lang == "pt"
    assert [w.text for w in words] == ["Olá,", "pessoal.", "Tudo", "bem?"]
    assert words[0].start == pytest.approx(2.5) and words[-1].end == pytest.approx(4.1)
    assert ("Transcrevendo…", 100, 100) in seen and ("Transcrevendo…", 50, 100) in seen
    assert len(calls(fake_engine)) == 1 and "-ng" not in calls(fake_engine)[0]


def test_vulkan_failure_retries_on_cpu(fake_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("PCTEST_WHISPER_MODO", "falha_gpu")
    stages = []
    words, _lang, device = tc.run_engine(fake_engine, wav(tmp_path), tc.Options(), tmp_path,
                                         progress=lambda s, d, t: stages.append(s))
    assert device == "cpu" and len(words) == 4
    made = calls(fake_engine)
    assert len(made) == 2 and "-ng" not in made[0] and "-ng" in made[1]
    assert vk_env(fake_engine)[1] == ""                             # no processador, nenhuma placa no Vulkan
    assert any("processador" in s for s in stages)
    # sem a placa pedida: vai direto no processador, uma vez só
    fake_engine.log.unlink()
    tc.run_engine(fake_engine, wav(tmp_path), tc.Options(gpu=False), tmp_path)
    assert len(calls(fake_engine)) == 1 and "-ng" in calls(fake_engine)[0]


@pytest.mark.parametrize("mode,text", [("falha", "A transcrição falhou (código 4)"), ("memoria", "Faltou memória")])
def test_errors_are_user_messages(fake_engine, tmp_path, monkeypatch, mode, text):
    monkeypatch.setenv("PCTEST_WHISPER_MODO", mode)
    with pytest.raises(tc.TranscribeError, match=text.replace("(", r"\(").replace(")", r"\)")):
        tc.run_engine(fake_engine, wav(tmp_path), tc.Options(), tmp_path)
    assert len(calls(fake_engine)) == 2   # placa e processador


def test_cancel_stops_the_process(fake_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("PCTEST_WHISPER_MODO", "lento")
    cancel = threading.Event()
    threading.Timer(0.8, cancel.set).start()
    t0 = time.monotonic()
    with pytest.raises(tools.Cancelled):
        tc.run_engine(fake_engine, wav(tmp_path), tc.Options(), tmp_path, cancel=cancel)
    assert time.monotonic() - t0 < 4.0


def test_without_a_gpu_reports_cpu(fake_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("PCTEST_WHISPER_MODO", "sem_placa")      # Vulkan sem placa: o próprio whisper usa a CPU
    words, _lang, device = tc.run_engine(fake_engine, wav(tmp_path), tc.Options(), tmp_path)
    assert device == "cpu" and len(words) == 4 and len(calls(fake_engine)) == 1


def test_no_speech_gives_empty_result(fake_engine, tmp_path, monkeypatch):
    monkeypatch.setenv("PCTEST_WHISPER_MODO", "mudo")
    words, _lang, _dev = tc.run_engine(fake_engine, wav(tmp_path), tc.Options(), tmp_path)
    assert words == []


def test_components_are_pinned_where_the_updater_never_looks():
    import re
    eng = tools.get("whisper_cpp")
    assert {a.platform for a in eng.artifacts} == {"win32", "linux"}
    for a in eng.artifacts:
        assert a.origin == tools.CI and "-vulkan." in a.url
        # tag componente-*: nunca v* (o build.yml e o atualizador do app só olham as releases v*/latest)
        assert "/releases/download/componente-whisper-cpp-" + tc.tools.WHISPER_CPP_VERSION + "/" in a.url
    for tool_id in ("whisper_small", "whisper_turbo", "silero_vad"):
        for a in tools.get(tool_id).artifacts:
            assert re.match(r"https://huggingface\.co/[\w.-]+/[\w.-]+/resolve/[0-9a-f]{40}/", a.url), a.url
            assert a.archive == "arquivo" and a.executables[0] == a.url.rsplit("/", 1)[1]
        assert tools.get(tool_id).license == "MIT"
    for tool_id in ("whisper_cpp", "silero_vad", "whisper_small", "whisper_turbo"):
        assert "legendas_auto" in tools.used_by(tools.get(tool_id))


def test_missing_components_message(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "WHISPER_CMD", None)
    lack = tc.missing("turbo", root=tmp_path)
    assert [t.id for t in lack] == ["whisper_cpp", "silero_vad", "whisper_turbo"]
    assert not tc.available(root=tmp_path)
    with pytest.raises(tc.TranscribeError, match="Componentes"):
        tc.engine("turbo", root=tmp_path)


def test_job_kind_follows_vulkan(monkeypatch):
    monkeypatch.setattr(tc, "vulkan_available", lambda: True)
    assert tc.job_kind(tc.Options()) == jobs.GPU and tc.job_kind(tc.Options(gpu=False)) == jobs.CPU
    monkeypatch.setattr(tc, "vulkan_available", lambda: False)
    assert tc.job_kind(tc.Options()) == jobs.CPU


def test_merge_replaces_the_transcribed_range():
    doc = sb.Subtitles(sources={"a.mp4": [Cue(0, 1, "antes"), Cue(5, 6, "velha"), Cue(20, 21, "depois")]},
                       cues=[Cue(1, 2, "da sequência")])
    new = [Cue(4, 5, "nova")]
    tc.merge(doc, tc.Result([], new, "pt", "cpu", "a.mp4", 3.0, 10.0))
    assert [c.text for c in doc.sources["a.mp4"]] == ["antes", "nova", "depois"] and doc.language == "pt"
    tc.merge(doc, tc.Result([], [Cue(1.5, 2.5, "trocada")], "en", "cpu", None, 0.0, 3.0))
    assert [c.text for c in doc.cues] == ["trocada"] and doc.language == "pt"


# ------------------------------------------------------------------ com ffmpeg (som de verdade, motor falso)
@pytest.fixture
def installed(fake_engine, monkeypatch):
    monkeypatch.setattr(tc, "engine", lambda model="small", root=None: fake_engine)
    return fake_engine


@pytest.mark.ffmpeg
def test_transcribe_file_anchors_to_source_time(installed, sample_video):
    stages = []
    res = tc.transcribe_file(sample_video, tc.Options(language="pt"), start=0.25, end=1.0,
                             progress=lambda s, d, t: stages.append(s))
    assert res.path == sample_video and res.start == 0.25 and res.language == "pt"
    assert [w.text for w in res.words][:2] == ["Olá,", "pessoal."]
    assert res.words[0].start == pytest.approx(0.75)               # 0,25 s do trecho + 0,5 s no WAV
    assert all(w.end <= 1.0 + 1e-9 for w in res.words)             # cortado no fim do trecho
    assert res.cues and res.cues[0].words[0] == res.words[0]
    assert stages[0] == "Lendo o som…"
    made = calls(installed)[0]
    wav_path = made[made.index("-f") + 1]
    assert not os.path.exists(wav_path)                            # a pasta temporária é apagada


@pytest.mark.ffmpeg
def test_transcribe_sequence_uses_the_mix(installed, sample_video):
    from pelicula import media
    info = media.probe(sample_video)
    seq = tl.Sequence(320, 180, "24/1")
    src = tl.Source.from_info(info)
    seq.insert_media(src, at=24)                                  # começa em 1 s
    res = tc.transcribe_sequence(seq, tc.Options(), progress=lambda *a: None)
    assert res.path is None and res.start == 0.0 and res.end == pytest.approx(2.0)
    assert res.words[0].start == pytest.approx(0.5)


@pytest.mark.ffmpeg
def test_file_without_audio(installed, ffmpeg_ok, tmp_path):
    import subprocess
    silent = tmp_path / "mudo.mp4"
    subprocess.run([ffmpeg_ok, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=size=64x64:rate=10:duration=1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(silent)], check=True, capture_output=True)
    with pytest.raises(tc.TranscribeError, match="não tem som"):
        tc.transcribe_file(str(silent), tc.Options())


def test_job_runs_in_the_queue(installed, tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "extract_audio", lambda path, out, *a, **k: Path(out).write_bytes(b"RIFF"))
    monkeypatch.setattr(tc, "vulkan_available", lambda: False)
    q = jobs.JobQueue()
    try:
        job = q.submit(tc.make_job(tc.Options(), "Transcrevendo teste", path=str(tmp_path / "x.mp4")))
        assert job.kind == jobs.CPU and job.key == tc.JOB_KEY
        assert job.wait(30)
        assert job.state == jobs.CONCLUIDO, job.error
        assert [c.text for c in job.result.cues] == ["Olá, pessoal. Tudo bem?"]   # frase curta não quebra
    finally:
        q.shutdown()


# ------------------------------------------------------------------ manual: whisper.cpp de verdade
@pytest.mark.skipif(os.environ.get("PELICULA_TESTE_WHISPER") != "1", reason="teste manual (PELICULA_TESTE_WHISPER=1)")
def test_real_whisper_transcribes(tmp_path, ffmpeg_ok, monkeypatch):
    path = os.environ.get("PELICULA_TESTE_WHISPER_ARQUIVO", "")
    assert path and os.path.isfile(path), "defina PELICULA_TESTE_WHISPER_ARQUIVO com um vídeo ou som com fala"
    monkeypatch.setattr(tc, "temp_dir", lambda: tmp_path / "cache")       # nunca a pasta do app do usuário
    root = Path(os.environ.get("PELICULA_TESTE_WHISPER_DIR") or tmp_path / "ferramentas")
    for tool_id in ("whisper_cpp", "silero_vad", "whisper_small"):
        if tools.executable(tools.get(tool_id), root=root) is None:
            tools.download(tools.get(tool_id), root=root)
    res = tc.transcribe_file(path, tc.Options(model="small", gpu=os.environ.get("PELICULA_TESTE_WHISPER_CPU") != "1"),
                             root=root,
                             progress=lambda s, d, t: print(f"\r{s} {d}/{t}", end="", flush=True))
    print()
    print(f"idioma: {res.language}, rodou na {res.device}, {len(res.words)} palavras, {len(res.cues)} legendas")
    print(sb.to_srt(res.cues[:10]))
    assert res.words and res.cues

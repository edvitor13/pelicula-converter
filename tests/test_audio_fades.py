"""Emendas de som: fades curtos automáticos e transição de potência constante (timeline + audiomix)."""

from __future__ import annotations

import math
import wave

import numpy as np
import pytest

from pelicula import audiomix
from pelicula import timeline as tl

_PRE = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"

# build_graph da 1.3 (antes dos fades nas emendas e da transição de som) para `old_project`: um projeto
# antigo tem de soar exatamente igual.
GOLDEN = {
    (0, -1): (
        "-f lavfi -t 4.25 -i anullsrc=r=48000:cl=stereo -ss 0 -t 2 -i <a> -ss 2 -t 1 -i <a> "
        "-ss 1.25 -t 1.875 -i <b> -ss 0.5 -t 0.833333 -i <b> -ss 7 -t 0.5 -i <a>",
        ";".join([
            f"[1:a:0]{_PRE},volume=-1.5dB,afade=t=in:st=0:d=0.5,atrim=start=0:duration=2,asetpts=PTS-STARTPTS[a0]",
            f"[2:a:0]{_PRE},volume=1.5dB,atrim=start=0:duration=1,asetpts=PTS-STARTPTS,adelay=2000|2000[a1]",
            f"[3:a:0]{_PRE},atempo=1.5,volume=1.5dB,afade=t=out:st=0.85:d=0.4,atrim=start=0:duration=1.25,"
            "asetpts=PTS-STARTPTS,adelay=3000|3000[a2]",
            f"[4:a:0]{_PRE},bass=g=2:f=110,pan=stereo|c0=1*c0|c1=0.75*c1,atrim=start=0:duration=0.833333,"
            "asetpts=PTS-STARTPTS,adelay=417|417[a3]",
            f"[5:a:0]{_PRE},atrim=start=0:duration=0.5,asetpts=PTS-STARTPTS,adelay=1250|1250[a4]",
            "[0:a][a0][a1][a2][a3][a4]amix=inputs=6:duration=first:dropout_transition=0:normalize=0,"
            "atrim=duration=4.25[out]",
        ])),
    (20, 80): (
        "-f lavfi -t 2.5 -i anullsrc=r=48000:cl=stereo -ss 0 -t 2 -i <a> -ss 2 -t 1 -i <a> "
        "-ss 1.25 -t 1.875 -i <b> -ss 0.5 -t 0.833333 -i <b> -ss 7 -t 0.5 -i <a>",
        ";".join([
            f"[1:a:0]{_PRE},volume=-1.5dB,afade=t=in:st=0:d=0.5,atrim=start=0.833333:duration=1.166667,"
            "asetpts=PTS-STARTPTS[a0]",
            f"[2:a:0]{_PRE},volume=1.5dB,atrim=start=0:duration=1,asetpts=PTS-STARTPTS,adelay=1167|1167[a1]",
            f"[3:a:0]{_PRE},atempo=1.5,volume=1.5dB,afade=t=out:st=0.85:d=0.4,atrim=start=0:duration=0.333333,"
            "asetpts=PTS-STARTPTS,adelay=2167|2167[a2]",
            f"[4:a:0]{_PRE},bass=g=2:f=110,pan=stereo|c0=1*c0|c1=0.75*c1,atrim=start=0.416667:duration=0.416667,"
            "asetpts=PTS-STARTPTS[a3]",
            f"[5:a:0]{_PRE},atrim=start=0:duration=0.5,asetpts=PTS-STARTPTS,adelay=417|417[a4]",
            "[0:a][a0][a1][a2][a3][a4]amix=inputs=6:duration=first:dropout_transition=0:normalize=0,"
            "atrim=duration=2.5[out]",
        ])),
    (50, 100): (
        "-f lavfi -t 2.083333 -i anullsrc=r=48000:cl=stereo -ss 2 -t 1 -i <a> -ss 1.25 -t 1.875 -i <b>",
        ";".join([
            f"[1:a:0]{_PRE},volume=1.5dB,atrim=start=0.083333:duration=0.916667,asetpts=PTS-STARTPTS[a0]",
            f"[2:a:0]{_PRE},atempo=1.5,volume=1.5dB,afade=t=out:st=0.85:d=0.4,atrim=start=0:duration=1.166667,"
            "asetpts=PTS-STARTPTS,adelay=917|917[a1]",
            "[0:a][a0][a1]amix=inputs=3:duration=first:dropout_transition=0:normalize=0,atrim=duration=2.083333[out]",
        ])),
}


def old_project(a: str, b: str) -> dict:
    """Montagem como a 1.3 gravava: sem "micro_fades" e sem "transicao" nos ajustes de som."""
    def src(path, frames, secs):
        return {"caminho": path, "largura": 640, "altura": 360, "fps": "24/1", "quadros": frames, "duracao": secs,
                "imagem": False, "tem_video": True, "tem_audio": True}

    def clip(cid, path, track, start, dur, src_in, **vals):
        return {"id": cid, "tipo": "audio", "fonte": path, "faixa": track, "inicio": start, "duracao": dur,
                "entrada": src_in, "ligacao": "", "nome": "", "valores": vals}

    return {
        "formato": 1, "largura": 640, "altura": 360, "fps": "24/1", "nome": "antiga", "fundo": [0, 0, 0],
        "faixas": [{"tipo": "video", "nome": "V1"},
                   {"tipo": "audio", "nome": "A1", "volume": 1.5},
                   {"tipo": "audio", "nome": "A2"}],
        "fontes": [src(a, 240, 10.0), src(b, 240, 10.0)],
        "clipes": [
            clip("c1", a, 0, 0, 48, 0.0, volume=-3.0, fade_in=0.5),
            clip("c2", a, 0, 48, 24, 2.0),                                  # corte não mexido
            clip("c3", b, 0, 72, 30, 1.25, fade_out=0.4, velocidade=1.5),   # aparado e acelerado
            clip("c4", b, 1, 10, 20, 0.5, balanco=-0.25, graves=2.0),
            clip("c5", a, 1, 30, 12, 7.0),                                  # colado no c4, outro arquivo
        ],
    }


def fake(tmp_path, *names) -> list[str]:
    out = []
    for n in names:
        p = tmp_path / n
        p.write_bytes(b"x")
        out.append(str(p))
    return out


def audio_seq(paths, secs=10.0, micro=False) -> tl.Sequence:
    """Sequência a 24 quadros/s com arquivos só de som (ainda sem clipes)."""
    seq = tl.Sequence(640, 360, "24/1", micro_fade=micro)
    for p in paths:
        seq.add_source(tl.Source(p, fps=24.0, frames=1, duration=secs, has_video=False, has_audio=True))
    return seq


def place(seq, path, start, dur, src_in, track=0, **vals) -> tl.Clip:
    c = tl.Clip(tl.new_id(), tl.AUDIO, path, track, start, dur, src_in, values=vals)
    seq.clips.append(c)
    return c


def seg_of(seq, clip, start=0, end=-1) -> dict | None:
    return next((s for s in audiomix.segments(seq, start, end) if s["clip"] is clip), None)


# ------------------------------------------------------------------ neutralidade
def test_old_project_mixes_exactly_as_before(tmp_path):
    a, b = fake(tmp_path, "a.mp4", "b.mp4")
    seq = tl.Sequence.from_json(old_project(a, b))
    assert not seq.micro_fade and "micro_fades" not in seq.to_json()
    for rng, (inputs, graph) in GOLDEN.items():
        got_inputs, got_graph = audiomix.build_graph(seq, *rng)
        assert " ".join(got_inputs).replace(a, "<a>").replace(b, "<b>") == inputs, rng
        assert got_graph == graph, rng
    again = tl.Sequence.from_json(seq.to_json())  # salvo de novo: continua igual
    assert not again.micro_fade and audiomix.build_graph(again) == audiomix.build_graph(seq)


def test_new_sequences_have_micro_fades_and_the_setting_round_trips(tmp_path):
    (a,) = fake(tmp_path, "a.mp4")
    seq = tl.Sequence.for_source(tl.Source(a, 640, 360, 24.0, "24/1", 240, 10.0, has_audio=True))
    assert seq.micro_fade and seq.to_json()["micro_fades"] is True
    assert tl.Sequence.from_json(seq.to_json()).micro_fade
    assert not tl.Sequence().micro_fade                              # padrão do código: desligado
    assert not tl.Sequence.from_json({"micro_fades": "sim"}).micro_fade
    assert "afade" not in audiomix.build_graph(seq)[1]               # o arquivo inteiro não tem emenda
    key = audiomix.mix_key(seq)
    seq.micro_fade = False
    assert audiomix.mix_key(seq) != key and "micro_fades" not in seq.to_json()


# ------------------------------------------------------------------ fades curtos nas emendas
def test_micro_fades_only_where_a_clip_cuts_the_file(tmp_path):
    a, b = fake(tmp_path, "a.wav", "b.wav")
    seq = audio_seq([a, b], micro=True)
    left = place(seq, a, 0, 240, 0.0)  # o arquivo inteiro: começo e fim naturais
    assert not any(seg_of(seq, left)[k] for k in ("micro_in", "micro_out"))
    (right_id,) = seq.split(48)
    right = seq.find(right_id)
    # corte não mexido: o som continua igual, sem fade dos dois lados
    assert seq.continues(left, right)
    assert not seg_of(seq, left)["micro_out"] and not seg_of(seq, right)["micro_in"]
    # afastado: virou emenda (o da esquerda corta o arquivo no fim; o da direita, no começo)
    seq.move(right.id, 60)
    assert not seq.continues(left, right)
    s_left, s_right = seg_of(seq, left), seg_of(seq, right)
    assert s_left["micro_out"] and not s_left["micro_in"]
    assert s_right["micro_in"] and not s_right["micro_out"]  # o da direita vai até o fim do arquivo
    graph = audiomix.build_graph(seq)[1]
    assert "afade=t=out:st=1.995:d=0.005" in graph and "afade=t=in:st=0:d=0.005" in graph
    # o fade do clipe já é maior: vale o dele
    seq.set_values(right.id, {**right.values, "fade_in": 0.5})
    assert not seg_of(seq, right)["micro_in"]
    seq.set_values(right.id, {**right.values, "fade_in": 0.0})
    # de volta ao lugar: sem emenda de novo; mas com o anterior mudo, o som começa no meio da onda
    seq.move(right.id, 48)
    assert not seg_of(seq, right)["micro_in"]
    seq.set_values(left.id, {**left.values, "mudo": True})
    assert seg_of(seq, right)["micro_in"]
    seq.set_values(left.id, {**left.values, "mudo": False})
    # outro arquivo colado e aparado dos dois lados
    other = place(seq, b, 240, 24, 3.0)
    assert seg_of(seq, other)["micro_in"] and seg_of(seq, other)["micro_out"]
    # desligado: nenhum
    seq.micro_fade = False
    assert "d=0.005" not in audiomix.build_graph(seq)[1]


# ------------------------------------------------------------------ transição de som
def test_crossfade_timing_uses_the_file_beyond_the_cut(tmp_path):
    a, b = fake(tmp_path, "a.wav", "b.wav")
    seq = audio_seq([a, b])
    A = place(seq, a, 0, 96, 1.0)   # 1 s → 5 s do arquivo: sobram 5 s depois da saída
    B = place(seq, b, 96, 96, 2.0)  # entra no 2 s: sobram 2 s antes
    assert seq.audio_crossfade(B) == (None, 0.0, 0.0)  # sem transição pedida
    B.values["transicao"] = 1.0
    prev, before, after = seq.audio_crossfade(B)
    assert prev is A and (before, after) == pytest.approx((0.5, 0.5))  # centrada no corte
    B.src_in = 0.0     # sem sobra antes da entrada: tudo depois do corte
    assert seq.audio_crossfade(B)[1:] == pytest.approx((0.0, 1.0))
    B.src_in = 0.3     # pouca sobra antes; nada depois: encolhe
    A.src_in = 6.0
    assert seq.audio_crossfade(B)[1:] == pytest.approx((0.3, 0.0))
    B.src_in = 0.0     # nenhuma sobra: não cabe
    assert seq.audio_crossfade(B)[1:] == (0.0, 0.0)
    A.src_in, B.src_in = 1.0, 2.0
    B.values["transicao"] = 5.0  # no máximo metade de cada clipe (2 s)
    assert seq.audio_crossfade(B)[1:] == pytest.approx((2.0, 2.0))
    A.values["velocidade"] = 2.0  # A a 2×: usa 1 → 9 s; sobra 1 s do arquivo = 0,5 s na sequência
    assert seq.audio_crossfade(B)[1:] == pytest.approx((2.0, 0.5))
    A.values["velocidade"] = 1.0
    B.start = 100  # descolou: sem transição
    assert seq.audio_crossfade(B) == (None, 0.0, 0.0)
    B.start = 96
    # dividir o clipe que entra: a transição fica no corte de entrada, a parte da direita nasce sem
    B.values["transicao"] = 1.0
    (right_id,) = seq.split(120, [B.id])
    assert B.values["transicao"] == 1.0 and seq.find(right_id).values["transicao"] == 0.0
    # vídeo não tem transição de som
    assert "transicao" not in tl.Clip("v", tl.VIDEO, a, 0, 0, 10).values


def test_crossfade_graph_extends_both_clips_with_sine_curves(tmp_path):
    a, b = fake(tmp_path, "a.wav", "b.wav")
    seq = audio_seq([a, b], micro=True)
    A = place(seq, a, 0, 96, 1.0, fade_out=0.3)
    B = place(seq, b, 96, 96, 2.0, fade_in=0.2, transicao=1.0)
    s_a, s_b = seg_of(seq, A), seg_of(seq, B)
    # A toca até 4,5 s (0,5 s além do corte) e B começa em 3,5 s (0,5 s antes)
    assert (s_a["src_in"], s_a["src_len"], s_a["pre"]) == pytest.approx((1.0, 4.5, 0.0))
    assert (s_b["src_in"], s_b["src_len"], s_b["pre"], s_b["delay"]) == pytest.approx((1.5, 4.5, 0.5, 3.5))
    assert s_a["xf_out"] == pytest.approx(1.0) and s_a["xf_out_st"] == pytest.approx(3.5)
    assert s_b["xf_in"] == pytest.approx(1.0)
    # nas pontas com transição não há fade curto; nas outras (cortes no meio do arquivo), há
    assert s_a["micro_in"] and not s_a["micro_out"] and not s_b["micro_in"] and s_b["micro_out"]
    inputs, graph = audiomix.build_graph(seq)
    joined = " ".join(inputs)
    assert f"-ss 1 -t 4.5 -i {a}" in joined and f"-ss 1.5 -t 4.5 -i {b}" in joined
    chain_a, chain_b = graph.split(";")[:2]
    assert "afade=t=out:st=3.5:d=1:curve=qsin" in chain_a and "atrim=start=0:duration=4.5" in chain_a
    assert "afade=t=in:st=0:d=1:curve=qsin" in chain_b and "adelay=3500|3500" in chain_b
    assert "afade=t=out:st=4.495:d=0.005" in chain_b  # fade curto no fim do B (0,5 s antes + 4 s − 5 ms)
    # os fades do usuário nesse corte dariam silêncio na sobra: a transição toma o lugar deles
    assert "d=0.3" not in chain_a and "d=0.2" not in chain_b
    # trechos (exportar de/até): a parte além do corte respeita o recorte
    first = audiomix.segments(seq, 0, 96)
    assert [s["clip"] for s in first] == [A, B]
    assert first[1]["trim_start"] == pytest.approx(0.0) and first[1]["trim_len"] == pytest.approx(0.5)
    assert first[0]["trim_len"] == pytest.approx(4.0)
    late = audiomix.segments(seq, 108, 192)
    assert [s["clip"] for s in late] == [B] and late[0]["trim_start"] == pytest.approx(1.0)
    mid = audiomix.segments(seq, 100, 104)
    assert [s["clip"] for s in mid] == [A, B]
    assert mid[0]["trim_start"] == pytest.approx(100 / 24) and mid[0]["trim_len"] == pytest.approx(4 / 24)


# ------------------------------------------------------------------ ffmpeg de verdade
def write_tone(path, freq, secs=8.0, amp=0.5, rate=48000) -> str:
    t = np.arange(int(secs * rate)) / rate
    x = np.round(amp * np.sin(2 * np.pi * freq * t) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.repeat(x[:, None], 2, axis=1).tobytes())
    return str(path)


def mixed(seq, tmp_path) -> np.ndarray:
    out = tmp_path / "mix.wav"
    assert audiomix.render_mix(seq, str(out))
    r = audiomix.WavReader(str(out))
    assert r.rate == 48000
    return r.read(0, r.frames)[:, 0].astype(np.float64)


@pytest.mark.ffmpeg
def test_crossfade_keeps_constant_power(ffmpeg_ok, tmp_path):
    a = write_tone(tmp_path / "a.wav", 440.0)
    b = write_tone(tmp_path / "b.wav", 1250.0)
    seq = audio_seq([a, b], secs=8.0)
    place(seq, a, 0, 96, 1.0)                    # 0–4 s
    place(seq, b, 96, 96, 2.0, transicao=2.0)    # 4–8 s, transição de 3 s a 5 s
    x = mixed(seq, tmp_path)
    rate, win = 48000, 2400                      # janelas de 50 ms
    ref = 0.5 / math.sqrt(2)
    levels = []
    for start in range(int(2.0 * rate), int(6.0 * rate), win):
        rms = math.sqrt(float(np.mean(x[start:start + win] ** 2)))
        levels.append(20 * math.log10(rms / ref))
    assert max(abs(v) for v in levels) < 0.3, levels  # um fade linear cairia 3 dB no meio
    # no meio da transição tocam os dois, cada um a −3 dB (cos 45° = sen 45°)
    mid = x[int(3.95 * rate):int(4.05 * rate)]
    spec = np.abs(np.fft.rfft(mid * np.hanning(len(mid)))) / (len(mid) / 4)
    freqs = np.fft.rfftfreq(len(mid), 1 / rate)
    amp = [spec[np.argmin(abs(freqs - f))] for f in (440.0, 1250.0)]
    assert amp == pytest.approx([0.5 * math.cos(math.pi / 4)] * 2, rel=0.12)


@pytest.mark.ffmpeg
def test_micro_fade_removes_the_click_at_a_cut(ffmpeg_ok, tmp_path):
    a = write_tone(tmp_path / "a.wav", 440.0)
    peak = 1.0 + 1 / 1760  # o seno de 440 Hz está no pico: começar aqui estala
    seq = audio_seq([a], secs=8.0, micro=True)
    place(seq, a, 0, 48, peak)
    x = mixed(seq, tmp_path)
    assert abs(x[0]) < 0.02 and np.abs(x[:24]).max() < 0.1   # sobe a partir de zero
    assert np.abs(x[240:480]).max() > 0.45                    # depois dos 5 ms, volume cheio
    assert np.abs(x[-6:]).max() < 0.05                        # e desce até zero no fim
    seq.micro_fade = False
    x = mixed(seq, tmp_path)
    assert abs(x[0]) > 0.45  # sem o fade, o som começa no pico

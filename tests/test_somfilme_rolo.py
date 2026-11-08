"""1.8, estalo na troca de rolo de Super 8 (ARQUITETURA §45.7).

O pulo da troca de rolo ("A montagem na película" → "Rolos de Super 8") e o estalo do som usam a mesma lista de
quadros (`montagem_filme.reel_frames`, a conta de `apply`): o estalo começa na amostra exata do quadro que pula, um
trecho com o contexto antes dá as mesmas amostras do som inteiro, sem rolos não há estalo, tudo determinístico, e a
prévia e a exportação pegam os eventos pela mesma `events_for`. Sem ffmpeg: os sons são gerados com numpy.
"""

from __future__ import annotations

import subprocess

import numpy as np
import pytest

from pelicula import audiomix, look, media, montagem_filme as mf, params, somfilme as S
from pelicula import timeline as tl

RATE = S.RATE


def _rolls(**kw):
    """Só os rolos (sem projetor, defeitos nem cortes): o único deslocamento do quadro é o pulo da troca."""
    return params.sanitize({"mfilme_on": True, "rolo_on": True, "mfilme_salto": 0.0, "mfilme_clarao": 0.0,
                            "proj_on": False, "desg_on": False, **kw})


def _quiet(**kw):
    """Som de película só com os estalos."""
    return _rolls(**{**dict(somf_on=True, somf_trilha_forca=0.0, somf_estalos=1.0, somf_poeira=0.0, somf_wow=0.0,
                            somf_projetor=0.0, somf_sala=0.0), **kw})


def _image_jumps(v, fps, frames):
    return [f for f in frames if look.build_plan(v, 64, 36, f, fps).uniforms["u_shift"][1] > 0]


def test_reel_frames_are_the_frames_where_the_image_jumps():
    for cad in ("18", "24"):
        for fps in (18.0, 23.976, 24.0, 25.0, 29.97, 30.0, 60.0):
            v = _rolls(rolo_cadencia=cad)
            L = mf.roll_length_s(v)
            near = sorted({f for k in range(4) for f in range(int(k * L * fps) - 4, int(k * L * fps) + 5) if f >= 0})
            image = _image_jumps(v, fps, near)
            end = int(3 * L * fps) + 5
            assert mf.reel_frames(v, fps, 0, end) == image, (cad, fps)
            assert len(image) <= 3 and 0 not in image
            for f in image:  # um quadro por troca: o primeiro do rolo novo
                roll, tr = mf.roll_at(v, f, fps)
                assert roll >= 1 and tr * fps < 0.5 and mf.roll_at(v, f - 1, fps)[0] == roll - 1


def test_reel_frames_window_and_off():
    v = _rolls(rolo_cadencia="24")
    assert mf.reel_frames(v, 24.0, 0, 20000) == [3600, 7200, 10800, 14400, 18000]
    assert mf.reel_frames(v, 24.0, 3601, 10801) == [7200, 10800]
    assert mf.reel_frames(v, 24.0, 0, 3600) == []
    assert mf.reel_frames({**v, "rolo_on": False}, 24.0, 0, 20000) == []
    assert mf.reel_frames({**v, "mfilme_on": False}, 24.0, 0, 20000) == []


def test_events_for_has_the_reel_change_also_without_a_montage():
    v = _quiet(rolo_cadencia="24")
    assert S.events_for(v, 24.0, 8000) == [3600, 7200]
    seq = tl.Sequence(width=64, height=36, fps_str="24/1")
    assert S.events_for(v, 24.0, 8000, seq) == [3600, 7200]
    assert S.events_for({**v, "rolo_on": False}, 24.0, 8000) == []
    assert S.events_for({**v, "mfilme_on": False}, 24.0, 8000) == []


def test_pop_starts_at_the_exact_sample_of_the_reel_change():
    for fps, cad in ((24.0, "24"), (29.97, "18"), (25.0, "18")):
        v = _quiet(rolo_cadencia=cad)
        L = mf.roll_length_s(v)
        f = mf.reel_frames(v, fps, 0, int(2 * L * fps))[0]
        at = round(f / fps * RATE)
        s0 = at - RATE // 2
        y = S.process(np.zeros((RATE, 2)), RATE, v, fps, s0, S.events_for(v, fps, int(2 * L * fps)))
        nz = np.flatnonzero(np.abs(y[:, 0]) > 0)
        assert len(nz) and int(nz[0]) == at - s0, (fps, cad)
        assert np.abs(y[at - s0]).max() > 0.2
    # sem rolos (ou sem a seção), nada
    for off in (dict(rolo_on=False), dict(mfilme_on=False), dict(somf_estalos=0.0)):
        v = _quiet(rolo_cadencia="24", **off)
        y = S.process(np.zeros((RATE, 2)), RATE, v, 24.0, 150 * RATE - RATE // 2, S.events_for(v, 24.0, 8000))
        assert not np.abs(y).any(), off


def test_range_with_context_is_the_slice_of_the_whole_and_deterministic():
    fps = 24.0
    v = _quiet(rolo_cadencia="24", somf_trilha_forca=1.0, somf_poeira=0.5, somf_wow=0.6, somf_sala=0.4)
    ev = S.events_for(v, fps, 4000)
    assert 3600 in ev
    at = round(3600 / fps * RATE)
    s0 = at - int(1.5 * RATE)
    t = (s0 + np.arange(3 * RATE)) / RATE
    x = np.stack([0.3 * np.sin(2 * np.pi * 440 * t), 0.3 * np.sin(2 * np.pi * 659 * t + 1.0)], 1)
    P = S.preroll_samples(RATE)
    whole = S.process(x, RATE, v, fps, s0, ev)
    assert np.array_equal(whole, S.process(x, RATE, v, fps, s0, list(ev)))
    for m in (int(1.4 * RATE), at - s0 + 100):  # o trecho começa antes do estalo e no meio dele
        part = S.process(x[m:], RATE, v, fps, s0 + m, ev, before=x[max(0, m - P):m])
        assert np.abs(part - whole[m:]).max() < 1e-6, m


def _make(ffmpeg, path, audio):
    cmd = [ffmpeg, "-v", "error", "-y", "-nostdin", "-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24:duration=2",
           "-f", "lavfi", "-i", audio, "-map", "0:v", "-map", "1:a", "-t", "2", "-c:v", "libx264", "-preset",
           "veryfast", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", str(path)]
    if subprocess.run(cmd, capture_output=True).returncode != 0:
        pytest.skip("não foi possível gerar o vídeo de teste")
    return str(path)


def _read(path):
    r = audiomix.WavReader(path)
    return r.read(0, r.frames).astype(np.float64)


@pytest.mark.ffmpeg
def test_preview_equals_export_with_a_reel_change(ffmpeg_ok, tmp_path, monkeypatch):
    """Rolos de 1 s (24 quadros na cadência de 24 qps) para caber num arquivo de 2 s: a troca cai no quadro 24. A
    prévia (o arquivo decodificado e processado do quadro 0 com `events_for`, como `ui/som_pelicula_ui`) e a
    exportação de um trecho (`export_sound`) dão as mesmas amostras, com o estalo no mesmo lugar."""
    monkeypatch.setattr(mf, "ROLL_FRAMES", 24)
    for audio, kw in (("anullsrc=r=48000:cl=stereo", {}),
                      ("anoisesrc=color=white:amplitude=0.05:sample_rate=48000:seed=3",
                       dict(somf_trilha_forca=1.0, somf_wow=0.6, somf_sala=0.4, somf_projetor=0.3))):
        path = _make(ffmpeg_ok, tmp_path / f"v{len(kw)}.mov", audio)
        info = media.probe(path)
        v = _quiet(rolo_cadencia="24", **kw)
        ev = S.events_for(v, info.fps, info.frames)
        assert ev == [24]
        dec = str(tmp_path / f"arquivo{len(kw)}.wav")
        assert audiomix.decode_wav(path, dec)
        pv = str(tmp_path / f"previa{len(kw)}.wav")
        assert S.process_wav(dec, pv, v, info.fps, 0, ev)
        prev = _read(pv)
        start, end = 10, 40
        out = S.export_sound(v, info, None, start, end, None)
        try:
            got = _read(out)
        finally:
            audiomix._remove(out)
        a = round(start / 24 * RATE)
        n = min(len(got), len(prev) - a)
        assert n > 0.5 * RATE
        assert np.abs(got[:n] - prev[a:a + n]).max() < 1e-4  # o arquivo da prévia é de 16 bits
        if not kw:  # mudo: o estalo é o primeiro som, na amostra do quadro 24
            assert int(np.flatnonzero(np.abs(got[:, 0]) > 0)[0]) == RATE - a
            assert int(np.flatnonzero(np.abs(prev[:, 0]) > 0)[0]) == RATE

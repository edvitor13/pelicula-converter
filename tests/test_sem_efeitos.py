"""1.7, "Desligar todos os efeitos" (`frame.Recipe.no_effects`, ARQUITETURA §40).

Com o campo ligado a receita é o caminho "sem película" (o preset "original", sem chaves nem LUT) e a montagem sai
neutra: o resultado é, bit a bit, o da mesma montagem com os ajustes de imagem dos clipes no padrão. A edição continua
(enquadramento, opacidade, mesclagem, transições). Com o campo desligado, nada muda. A janela está em
`sem_efeitos_ui_cases.py`.
"""

from __future__ import annotations

import numpy as np
import pytest

from helpers import read_all
from pelicula import camera, editparams, export, frame, media, presets, sequence
from pelicula import timeline as tl
from pelicula.export import ExportJob, ExportSettings

W, H = 320, 180
KEYS = {"grao_forca": [[0.0, 0.2, "linear"], [20.0, 2.0, "linear"]]}

# Tudo o que muda a cor da imagem de um clipe e sai com o interruptor
PICTURE = {
    "exposicao": 0.6, "temperatura": 30.0, "saturacao": -0.4, "contraste": 0.3, "vinheta": -0.5, "desbotar": 0.3,
    "roda_meios": [0.3, 0.2], "curva_escuros": 0.2, "hsl_vermelho_sat": 0.5,    # cor
    "nitidez": 0.8, "clareza": 0.4, "desfoque": 0.2, "reducao_ruido": 0.4,       # detalhe
    "camera_entrada": "slog3", "camera_ei": "800",                               # perfil de câmera do clipe
    "pele_natural": 0.8,                                                         # pele
    "alvo_matiz": 120.0, "alvo_desvio": 40.0, "alvo_sat": 0.5,                   # cor escolhida
    "degrade_exposicao": -1.0, "degrade_saturacao": 0.4,                         # degradê
    "luz_r": 6.0, "luz_densidade": 3.0,                                          # luz da copiadora
}


def _look() -> dict:
    v = presets.builtin_values("vision3_500t")  # grão, halação, bloom, cópia
    v.update(grao_forca=1.4, mold_on=True, entrada="slog3", obturador_on=True, obturador_angulo="180")
    return v


def _montage(sample_video, picture: bool, edit: bool = True) -> tl.Sequence:
    """Corte com dissolver, enquadramento e uma camada com opacidade e mesclagem; `picture`: com a imagem ajustada."""
    src = media.probe_source(sample_video)
    seq = tl.Sequence.for_source(src)
    seq.split(8)
    a, b = sorted((c for c in seq.clips if c.kind == tl.VIDEO), key=lambda c: c.start)
    if edit:
        seq.set_values(b.id, {**b.values, "escala": 0.8, "rotacao": 4.0, "entrada_tipo": "dissolver",
                              "entrada_dur": 0.2})
        over, = seq.insert_media(src, at=4, vtrack=1, with_audio=False)
        seq.set_values(over.id, {**over.values, "escala": 0.4, "pos_x": 0.2, "opacidade": 0.6, "mesclagem": "tela"})
    if picture:
        for c in [c for c in seq.clips if c.kind == tl.VIDEO]:
            seq.set_values(c.id, {**c.values, **PICTURE})
    return tl.Sequence.from_json(seq.to_json())


def _frame(engine, seq, values, f, depth, keys=None, no_effects=False):
    r = frame.Recipe.for_source(values, 24.0, depth, legal=sequence.legal_range(seq), seq=seq, size=(W, H),
                                keys=keys, no_effects=no_effects)
    return r.render(engine, sequence.grab(seq, f, W, H, depth, hq=True, shutter=r.shutter, no_effects=no_effects), f)


def _ffv1(**kw) -> ExportSettings:
    return ExportSettings(codec="ffv1", container="mkv", pix="rgb48le", audio="none", dither=False, **kw)


# ------------------------------------------------------------------ sem GPU
def test_recipe_is_the_no_film_path(tmp_path):
    cube = tmp_path / "x.cube"
    cube.write_text("LUT_3D_SIZE 2\n" + "0 0 0\n1 0 0\n0 1 0\n1 1 0\n0 0 1\n1 0 1\n0 1 1\n1 1 1\n", encoding="ascii")
    v = dict(_look(), lut_on=True, lut_arquivo=str(cube))
    base = frame.Recipe.for_source(v, 24.0, 8, legal=True, keys=KEYS)
    assert base.lut is not None and base.keys and base.shutter == 180.0 and base.profile == "slog3"
    r = frame.Recipe.for_source(v, 24.0, 8, legal=True, keys=KEYS, no_effects=True)
    assert r.values == presets.builtin_values("original") and r.keys == {} and r.lut is None
    assert r.shutter == 0.0 and r.profile == "rec709"
    assert r.values is not v and v["grao_forca"] == 1.4 and v["lut_on"]   # os ajustes de quem chamou ficam como estão
    assert r.with_(depth=16).values == r.values and r.with_(depth=16).no_effects
    # sem película (prévia do modo Edição): continua só a montagem
    none = frame.Recipe.for_source(None, 24.0, 8, legal=True, no_effects=True)
    assert none.values is None and none.shutter == 0.0
    assert base.with_(no_effects=True).values == r.values


def test_defaults_do_not_change(make_info):
    v = _look()
    r = frame.Recipe.for_source(v, 24.0, 8, legal=True, keys=KEYS)
    assert r.no_effects is False and r.values is v and r.keys
    assert frame.Recipe(v, 24.0).no_effects is False
    info = make_info(width=W, height=H, fps=24.0, fps_str="24/1")
    p = export.frame_pipeline(info, v, ExportSettings(), keys=KEYS)
    assert p.no_effects is False and p.values is v and p.keys
    p = export.frame_pipeline(info, v, ExportSettings(no_effects=True), keys=KEYS)
    assert p.no_effects and p.values == presets.builtin_values("original") and not p.keys and p.shutter == 0.0


def test_export_settings_round_trip_and_old_job(make_info):
    assert ExportSettings().no_effects is False
    assert ExportSettings.from_dict(ExportSettings(no_effects=True).to_dict()).no_effects is True
    info = make_info()
    job = ExportJob(info=info, values=_look(), settings=ExportSettings(no_effects=True), out_path="saida.mp4",
                    look_keys=KEYS)
    d = job.to_dict()
    assert d["config"]["no_effects"] is True
    assert d["valores"]["grao_forca"] == 1.4 and d["chaves"]      # o trabalho guarda o look como estava
    assert ExportJob.from_dict(d).settings.no_effects is True
    # um trabalho guardado antes da 1.7 não tem o campo
    del d["config"]["no_effects"]
    old = ExportJob.from_dict(d)
    assert old.settings.no_effects is False
    assert ExportSettings.from_dict({"codec": "x265"}).no_effects is False


def test_every_clip_picture_key_is_in_the_test():
    """Toda seção de imagem do clipe (cor, detalhe, perfil, pele, alvo, degradê) está coberta por `PICTURE`."""
    covered = {k: v for k, v in PICTURE.items() if k in editparams.VIDEO.params}
    assert covered == PICTURE
    sections = {s.key for s in editparams.VIDEO_SECTIONS for p in s.params if p.key in PICTURE}
    assert sections >= {"luz", "cor", "rodas", "curva", "hsl", "detalhe", "efeitos", "camera", "pele", "alvo",
                        "degrade", "luz_copiadora"}


# ------------------------------------------------------------------ na GPU
@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("depth", [8, 16])
def test_montage_equals_defaults_and_original_preset(gl_engine, sample_video, depth):
    adjusted = _montage(sample_video, True)
    plain = _montage(sample_video, False)
    assert camera.uses_profiles(adjusted) and not camera.uses_profiles(plain)
    original = presets.builtin_values("original")
    for f in (2, 6, 9, 14):                 # só a V1, com a camada por cima, na transição, depois dela
        got = _frame(gl_engine, adjusted, _look(), f, depth, keys=KEYS, no_effects=True)
        want = _frame(gl_engine, plain, original, f, depth)
        assert got.dtype == want.dtype and np.array_equal(got, want), f"quadro {f}, {depth} bits"
        assert not np.array_equal(got, _frame(gl_engine, adjusted, _look(), f, depth, keys=KEYS)), f"quadro {f}"
        # sem película na prévia: a mesma montagem
        np.testing.assert_array_equal(_frame(gl_engine, adjusted, None, f, depth, no_effects=True),
                                      _frame(gl_engine, plain, None, f, depth))


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_the_edit_still_applies(gl_engine, sample_video):
    """Enquadramento, opacidade, mesclagem e transições continuam com os efeitos desligados."""
    edited = _montage(sample_video, True)
    bare = _montage(sample_video, False, edit=False)
    original = presets.builtin_values("original")
    for f in (6, 9, 14):
        got = _frame(gl_engine, edited, _look(), f, 8, no_effects=True)
        assert not np.array_equal(got, _frame(gl_engine, bare, original, f, 8)), f"quadro {f}"
    # a transição: no meio do dissolver o quadro não é nenhuma das pontas
    a, b = (_frame(gl_engine, edited, None, f, 8, no_effects=True) for f in (7, 12))
    mid = _frame(gl_engine, edited, None, 9, 8, no_effects=True)
    assert not np.array_equal(mid, a) and not np.array_equal(mid, b)


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("depth", [8, 16])
def test_flag_off_is_the_recipe_without_the_field(gl_engine, sample_video, depth):
    seq = _montage(sample_video, True)
    look = _look()
    legal = sequence.legal_range(seq)
    for f in (2, 9):
        fl = sequence.grab(seq, f, W, H, depth, hq=True, shutter=180.0)
        a = frame.Recipe.for_source(look, 24.0, depth, legal=legal, seq=seq, size=(W, H), keys=KEYS).render(gl_engine, fl, f)
        b = frame.Recipe.for_source(look, 24.0, depth, legal=legal, seq=seq, size=(W, H), keys=KEYS,
                                    no_effects=False).render(gl_engine, fl, f)
        np.testing.assert_array_equal(a, b)


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("depth", [8, 16])
def test_file_equals_original_preset(gl_engine, sample_video, depth):
    info = media.probe(sample_video)
    legal = media.legal_range(info)
    r = frame.Recipe.for_source(_look(), 24.0, depth, legal=legal, keys=KEYS, no_effects=True)
    o = frame.Recipe.for_source(presets.builtin_values("original"), 24.0, depth, legal=legal)
    for f in (0, 11):
        # a leitura também: sem o perfil de log do look
        img = media.grab_frame(info, f, W, H, depth, hq=True, profile=r.profile)
        assert img.dtype != np.float32
        np.testing.assert_array_equal(r.render(gl_engine, img, f), o.render(gl_engine, img, f))


@pytest.mark.ffmpeg
def test_readers_skip_the_clip_profile(sample_video):
    seq = _montage(sample_video, True)
    fl = sequence.grab(seq, 2, W, H, 8, hq=True, no_effects=True)
    assert all(li.image.dtype == np.uint8 and li.stack is None for li in fl.layers)
    plain = sequence.grab(_montage(sample_video, False), 2, W, H, 8, hq=True)
    np.testing.assert_array_equal(fl.layers[0].image, plain.layers[0].image)
    if media.has_zscale():
        assert sequence.grab(seq, 2, W, H, 8, hq=True).layers[0].image.dtype == np.float32


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_grab_equals_sequence_reader(gl_engine, sample_video):
    seq = _montage(sample_video, True)
    rd = sequence.SequenceReader(seq, W, H, 16, hq=True, no_effects=True)
    try:
        frames = [rd.read() for _ in range(seq.duration)]
    finally:
        rd.close()
    r = frame.Recipe.for_source(_look(), 24.0, 16, legal=sequence.legal_range(seq), seq=seq, size=(W, H),
                                no_effects=True)
    for f, fl in enumerate(frames):
        got = r.render(gl_engine, fl, f)
        np.testing.assert_array_equal(got, _frame(gl_engine, seq, _look(), f, 16, no_effects=True), f"quadro {f}")


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_export_is_the_recipe(gl_engine, sample_video, tmp_path):
    """Uma exportação com o campo (montagem e arquivo) dá os mesmos quadros da receita e da montagem sem ajustes."""
    seq = _montage(sample_video, True)
    plain = _montage(sample_video, False)
    info = sequence.media_info(seq)
    out = tmp_path / "montagem.mkv"
    job = ExportJob(info=info, values=_look(), settings=_ffv1(no_effects=True), out_path=str(out), start_frame=2,
                    end_frame=10, sequence=seq, look_keys=KEYS)
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    o = media.probe(str(out))
    frames = read_all(media.FrameReader(o, o.width, o.height, 16))
    assert len(frames) == 9
    original = presets.builtin_values("original")
    for i, got in enumerate(frames):
        f = 2 + i
        np.testing.assert_array_equal(got, export.preview_frame(gl_engine, info, _look(), _ffv1(no_effects=True), f,
                                                                seq=seq, depth=16, keys=KEYS), f"quadro {f}")
        np.testing.assert_array_equal(got, export.preview_frame(gl_engine, info, original, _ffv1(), f, seq=plain,
                                                                depth=16), f"quadro {f}")
    # o arquivo direto (modo Película)
    src = media.probe(sample_video)
    out = tmp_path / "arquivo.mkv"
    job = ExportJob(info=src, values=_look(), settings=_ffv1(no_effects=True), out_path=str(out), start_frame=3,
                    end_frame=8, look_keys=KEYS)
    export.run_job(job, gl_engine)
    assert job.status == "concluido", job.error
    o = media.probe(str(out))
    frames = read_all(media.FrameReader(o, o.width, o.height, 16))
    assert len(frames) == 6
    for i, got in enumerate(frames):
        np.testing.assert_array_equal(got, export.preview_frame(gl_engine, src, original, _ffv1(), 3 + i, depth=16),
                                      f"quadro {3 + i}")

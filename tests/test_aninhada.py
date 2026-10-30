"""Sequência aninhada (#57): um clipe cuja fonte é outra sequência aparece e soa como a montagem de dentro.

O coração daqui é a montagem "gêmea": os mesmos clipes dentro de uma sequência interna, e a de fora só com o clipe dela,
sem nenhum ajuste, tem que dar os mesmos quadros (bit a bit) e o mesmo som que a montagem sem aninhar.
"""

from __future__ import annotations

import numpy as np
import pytest

from pelicula import audiomix, camera, export, media, modules, sequence
from pelicula import timeline as tl

W, H = 320, 180
KIND = "gerador"


def gen(seq, clip, frame, w, h, depth):
    """Gerador de teste: cor pela fonte, brilho pelo quadro da fonte, uma barra que anda (para ver o quadro e o tamanho)."""
    src = seq.sources[clip.src]
    r, g, b = src.data.get("cor", [1.0, 0.5, 0.0])
    k = 0.2 + 0.03 * (frame % 25)
    img = np.ones((h, w, 3), np.float64) * [r * k, g * k, b * k]
    img[:, (frame * 3) % w] = 1.0
    mx = 255 if depth == 8 else 65535
    return np.rint(img * mx).astype(np.uint8 if depth == 8 else np.uint16)


@pytest.fixture
def renderer(monkeypatch):
    monkeypatch.setitem(sequence.RENDERERS, KIND, gen)
    return gen


def vsrc(cor=(1.0, 0.5, 0.0), seconds=4.0, fps="24/1"):
    return tl.Source.virtual(KIND, W, H, fps, seconds=seconds, data={"nome": "Barra", "cor": list(cor)}, alpha=False)


def fsrc(path="C:/nao/existe.mp4", frames=240, **kw):
    kw.setdefault("has_audio", True)
    kw.setdefault("color_range", "tv")
    return tl.Source(path, W, H, 24.0, "24/1", frames, frames / 24.0, pix_fmt="yuv420p", **kw)


def inner_of(outer, cor=(0.2, 0.8, 0.4), seconds=4.0, fps="24/1", width=W, height=H):
    """Uma sequência nova no projeto de `outer`, com um clipe gerado."""
    inner = outer.ensure_set().create(width, height, fps)
    inner.insert_media(vsrc(cor, seconds, fps), at=0)
    return inner


def nested_src(outer, inner):
    outer.siblings.sync()
    return outer.sources[f"sequencia:{inner.id}"]


def put(outer, inner, at=0, vtrack=0):
    """Um clipe de `inner` em `outer`."""
    return outer.insert_media(nested_src(outer, inner), at=at, vtrack=vtrack)[0]


def pair(**kw):
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = inner_of(outer, **kw)
    return outer, inner, put(outer, inner)


def same_layers(a: sequence.FrameLayers, b: sequence.FrameLayers, where="") -> None:
    assert a.frame == b.frame, where
    assert len(a.layers) == len(b.layers), where
    for x, y in zip(a.layers, b.layers):
        assert x.layer.clip.id == y.layer.clip.id and x.layer.src_frame == y.layer.src_frame, where
        assert (x.nested is None) == (y.nested is None), where
        if x.nested is not None:
            assert x.nested.size == y.nested.size and x.nested.seq.id == y.nested.seq.id, where
            same_layers(x.nested.layers, y.nested.layers, f"{where} > {x.layer.clip.id}")
        else:
            assert np.array_equal(x.image, y.image), where


def agree(seq, frames=None, w=W, h=H, depth=8, **kw) -> None:
    """`SequenceReader` = `grab`, quadro a quadro."""
    n = seq.duration if frames is None else frames
    reader = sequence.SequenceReader(seq, w, h, depth, 0, n, **kw)
    try:
        for t in range(n):
            same_layers(sequence.grab(seq, t, w, h, depth, **kw), reader.read(), f"quadro {t}")
        assert reader.read() is None and reader.error == ""
    finally:
        reader.close()


def nested_frames(seq, frames) -> list[int]:
    """Quadros da sequência interna que o primeiro clipe de sequência mostra."""
    out = []
    for t in frames:
        li = next(x for x in sequence.grab(seq, t, W, H).layers if x.nested is not None)
        out.append(li.nested.layers.frame)
    return out


# ------------------------------------------------------------------ tempo e leitura
def test_grab_gives_the_inner_layers_at_the_inner_frame(renderer):
    outer, inner, clip = pair()
    fl = sequence.grab(outer, 7, W, H)
    assert len(fl.layers) == 1 and fl.layers[0].stack is None
    n = fl.layers[0].nested
    assert n.seq is inner and n.size == (W, H) and n.layers.frame == 7
    assert np.array_equal(n.layers.layers[0].image, gen(inner, inner.clips[0], 7, W, H, 8))
    assert fl.layers[0].image.shape == (2, 2, 3)  # sem imagem própria: quem amostra vê preto, ninguém quebra


def test_reader_agrees_with_grab_on_a_plain_nested_clip(renderer):
    outer, inner, clip = pair()
    agree(outer)
    agree(outer, depth=16)


def test_reader_agrees_at_every_speed_and_entrance(renderer):
    outer, inner, clip = pair()
    outer.set_speed(clip.id, 2.0)
    assert nested_frames(outer, [0, 1, 2]) == [0, 2, 4]
    agree(outer)
    outer, inner, clip = pair()
    outer.set_speed(clip.id, 0.4)
    assert nested_frames(outer, [0, 1, 2, 3, 4, 5]) == [0, 0, 0, 1, 1, 2]
    agree(outer)
    outer, inner, clip = pair()
    outer.trim_start(clip.id, 24)  # a entrada: o clipe começa 1 s depois na interna
    outer.move(clip.id, 6)
    assert clip.start == 6 and nested_frames(outer, [6, 7]) == [24, 25]
    agree(outer)


def test_reader_agrees_in_reverse_and_frozen(renderer):
    outer, inner, clip = pair()
    outer.retime(clip.id, reverse=True)
    assert nested_frames(outer, [0, 1]) == [95, 94]
    agree(outer)
    outer, inner, clip = pair()
    outer.freeze_frame(clip.id, 10, 12)
    agree(outer)


def test_reader_agrees_with_a_different_frame_rate(renderer):
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = inner_of(outer, fps="25/1")
    put(outer, inner)
    assert nested_frames(outer, [0, 24, 48]) == [0, 25, 50]
    agree(outer)
    outer = tl.Sequence(width=W, height=H, fps_str="30/1")
    inner = inner_of(outer, fps="24/1")
    put(outer, inner)
    agree(outer)


def test_reader_agrees_with_two_levels(renderer):
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    middle = inner_of(outer, (0.9, 0.1, 0.1))
    deep = inner_of(outer, (0.1, 0.1, 0.9), seconds=2.0)
    c = put(middle, deep, 0, vtrack=1)
    middle.set_speed(c.id, 0.5)
    put(outer, middle)
    li = sequence.grab(outer, 5, W, H).layers[0]
    below, top = li.nested.layers.layers
    assert below.nested is None and top.nested.seq is deep and top.nested.layers.frame == 2
    agree(outer)


def test_reader_agrees_with_two_nested_clips_at_once_and_the_same_one_twice(renderer):
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    a = inner_of(outer, (0.9, 0.1, 0.1), seconds=2.0)
    b = inner_of(outer, (0.1, 0.1, 0.9), seconds=2.0)
    put(outer, a)
    c = put(outer, b, 0, vtrack=1)
    outer.trim_end(c.id, 24)
    twice = put(outer, a, 0, vtrack=2)
    outer.set_speed(twice.id, 0.5)
    assert len(sequence.grab(outer, 10, W, H).layers) == 3
    agree(outer)


def test_reader_of_real_files_inside(renderer, sample_video, sample_image):
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = outer.ensure_set().create(W, H, "24/1")
    vid = inner.insert_media(media.probe_source(sample_video), at=0)[0]
    inner.trim_start(vid.id, 6)
    inner.move(vid.id, 0)
    pic = inner.insert_media(media.probe_source(sample_image), at=4, vtrack=1)[0]
    inner.trim_end(pic.id, 12)
    c = put(outer, inner)
    outer.set_speed(c.id, 1.5)
    agree(outer)
    c2 = put(outer, inner, 0, vtrack=1)
    outer.retime(c2.id, reverse=True)
    agree(outer)


def test_cut_and_gap_between_nested_clips_reopen_nothing_wrong(renderer):
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = inner_of(outer, seconds=3.0)
    a = put(outer, inner)
    outer.trim_end(a.id, 12)
    b = put(outer, inner, at=30)
    outer.trim_start(b.id, 60)  # salto para a frente: o leitor interno reabre
    agree(outer)
    # os mesmos quadros lendo a partir do meio
    reader = sequence.SequenceReader(outer, W, H, 8, 40, 5)
    try:
        for t in range(40, 45):
            same_layers(sequence.grab(outer, t, W, H), reader.read(), f"quadro {t}")
    finally:
        reader.close()


def test_slow_motion_returns_the_same_object_only_for_the_same_frame(renderer):
    outer, inner, clip = pair()
    outer.set_speed(clip.id, 0.5)
    reader = sequence.SequenceReader(outer, W, H, 8, 0, 6)
    try:
        got = [reader.read().layers[0].nested.layers for _t in range(6)]
    finally:
        reader.close()
    assert [f.frame for f in got] == [0, 0, 1, 1, 2, 2]
    assert got[0] is got[1] and got[2] is got[3] and got[1] is not got[2]


def test_empty_inner_sequence_and_empty_inner_frame(renderer):
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    empty = outer.ensure_set().create(W, H, "24/1")
    c = put(outer, empty)
    assert c.dur == 1
    assert sequence.grab(outer, 0, W, H).layers[0].nested.layers.layers == []
    agree(outer)
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = inner_of(outer, seconds=1.0)
    inner.move(inner.clips[0].id, 12)  # buraco nos 12 primeiros quadros
    put(outer, inner)
    assert sequence.grab(outer, 3, W, H).layers[0].nested.layers.layers == []
    agree(outer)


def test_close_closes_the_inner_reader_and_the_errors_go_up(renderer, monkeypatch):
    outer, inner, clip = pair()
    reader = sequence.SequenceReader(outer, W, H, 8, 0, 5)
    reader.read()
    stream = reader._streams[clip.id]
    assert isinstance(stream, sequence._NestedStream)
    closed = stream.reader
    reader.close()
    assert stream.reader is None and closed._closed and reader.read() is None

    def bad(*a):
        raise ValueError("gerador quebrado")

    outer, inner, clip = pair()
    reader = sequence.SequenceReader(outer, W, H, 8, 0, 3)
    monkeypatch.setitem(sequence.RENDERERS, KIND, bad)
    try:
        assert reader.read().layers[0].nested.layers.layers[0].image.shape == (H, W, 4)  # camada transparente
        assert "gerador quebrado" in reader.error
    finally:
        reader.close()


# ------------------------------------------------------------------ tamanhos
def test_inner_canvas_follows_the_decode_size():
    outer = tl.Sequence(width=1920, height=1080, fps_str="24/1")
    inner = outer.ensure_set().create(1920, 1080, "24/1")
    clip = outer.insert_media(nested_src(outer, inner), at=0)[0]
    size = lambda s=outer, cw=1920, ch=1080: sequence.nested_canvas(inner, *sequence.decode_size(s, clip, cw, ch))
    assert size() == (1920, 1080)
    assert size(cw=640, ch=360) == (640, 360)  # prévia reduzida: tela reduzida
    assert size(cw=3840, ch=2160) == (1920, 1080)  # nunca maior que a sequência
    outer.set_values(clip.id, {"escala": 0.5})
    assert size(cw=640, ch=360) == (640, 360)  # escala menor não reduz (decode_size só amplia)
    outer.set_values(clip.id, {"escala": 2.0})
    assert size(cw=640, ch=360) == (1280, 720)  # ampliado: mais resolução
    assert size(cw=1920, ch=1080) == (1920, 1080)  # até o tamanho dela
    outer.set_values(clip.id, {"escala": 1.0, "encaixe": "esticar"})
    tall = tl.Sequence(width=1080, height=1920, fps_str="24/1", sources=outer.sources)
    tall.clips, tall.siblings = [clip], outer.siblings
    assert sequence.decode_size(tall, clip, 1080, 1920) == (1080, 1080)
    # "Esticar": a proporção da interna, com a maior medida: estica a imagem, não reencaixa lá dentro
    assert sequence.nested_canvas(inner, 1080, 1080) == (1920, 1080)
    assert sequence.nested_canvas(inner, 641, 361) == (640, 360)  # lados pares
    assert sequence.nested_canvas(inner, 720, 404) == (720, 404)  # a tela de fora, a menos do arredondamento
    assert sequence.nested_canvas(inner, 1000, 200) == (1000, 562)  # outra proporção: a proporção dela
    assert sequence.nested_canvas(tl.Sequence(width=1921, height=1081), 5000, 5000) == (1921, 1081)  # o tamanho dela


def test_a_nested_clip_keeps_its_proportion_in_the_window_unlike_a_generated_one():
    from pelicula import compositor
    outer = tl.Sequence(width=1920, height=1080, fps_str="24/1", window=2.39)
    inner = outer.ensure_set().create(1920, 1080, "24/1")
    clip = outer.insert_media(nested_src(outer, inner), at=0)[0]
    _x, _y, aw, ah = outer.window_rect(1920, 1080)
    bw, bh = compositor.fit_box(outer, clip, 1920, 1080)
    assert (bw, bh) != (aw, ah) and bw / bh == pytest.approx(16 / 9) and bh == ah  # mostra inteira, dentro da janela
    gen_clip = outer.insert_media(vsrc(), at=0, vtrack=1)[0]
    assert compositor.fit_box(outer, gen_clip, 1920, 1080) == (aw, ah)
    w, h = sequence.decode_size(outer, clip, 1920, 1080)
    assert w / h == pytest.approx(16 / 9, abs=0.01)


# ------------------------------------------------------------------ quem olha a montagem inteira
def _flat_and_twin(sources):
    """(montagem sem aninhar, a gêmea de fora, a de dentro) com os mesmos arquivos."""
    flat = tl.Sequence(width=W, height=H, fps_str="24/1")
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = outer.ensure_set().create(W, H, "24/1")
    for s in (flat, inner):
        at = 0
        for src in sources:
            c = s.insert_media(src, at=at)[0]
            at = c.end
    put(outer, inner)
    return flat, outer, inner


def test_legal_range_counts_the_clips_inside_as_if_not_nested():
    legal = lambda p: fsrc(p, frames=48)
    full = lambda p: fsrc(p, frames=48, color_range="pc")
    for mix in ([full("a"), legal("b"), legal("c")], [legal("a"), full("b"), full("c")], [full("a"), legal("b")],
                [legal("a"), full("b")]):
        flat, outer, _inner = _flat_and_twin(mix)
        assert sequence.legal_range(outer) == sequence.legal_range(flat), mix
    # um clipe de vídeo de fora mais os de dentro: a maioria é contada por clipe, não por "um clipe de sequência"
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = outer.ensure_set().create(W, H, "24/1")
    at = 0
    for p in "ab":
        at = inner.insert_media(full(p), at=at)[0].end
    c = put(outer, inner)
    outer.insert_media(legal("c"), at=c.end)
    assert sequence.legal_range(outer) is False
    # o mesmo clipe de sequência duas vezes pesa duas vezes
    outer2 = tl.Sequence(width=W, height=H, fps_str="24/1")
    one = outer2.ensure_set().create(W, H, "24/1")
    one.insert_media(full("x"), at=0)
    a = put(outer2, one)
    b = put(outer2, one, at=a.end)
    outer2.insert_media(legal("y"), at=b.end)
    assert sequence.legal_range(outer2) is False


def test_helpers_see_inside_and_only_what_is_used():
    a, b, c = fsrc("C:/m/a.mp4"), fsrc("C:/m/b.mp4", bit_depth=10, codec="hevc"), fsrc("C:/m/solta.mp4")
    outer = tl.Sequence(width=W, height=H, fps_str="24/1", name="Filme")
    middle = outer.ensure_set().create(W, H, "24/1")
    deep = outer.siblings.create(W, H, "24/1")
    other = outer.siblings.create(W, H, "24/1")
    deep.insert_media(a, at=0)
    middle.insert_media(b, at=0, vtrack=1)
    put(middle, deep)
    put(outer, middle)
    other.insert_media(c, at=0)  # noutra sequência do projeto: esta montagem não lê
    assert sequence.first_video_source(outer).path == a.path  # o primeiro, de baixo para cima, em qualquer nível
    assert sorted(export.job_inputs(sequence.media_info(outer), outer)) == [a.path, b.path]
    assert sequence.missing_sources(outer) == [a.path, b.path]
    assert sequence.missing_sources(other) == [c.path]
    assert sorted(s.path for s in outer.deep_sources()) == [a.path, b.path]
    info = sequence.media_info(outer)
    assert info.has_audio and info.width == W and info.path.replace("\\", "/").endswith("m/Filme.mp4")
    unnamed = sequence.media_info(deep)
    assert unnamed.path.endswith(".mp4")


def test_media_info_of_a_nested_sequence_with_only_sound_and_of_generated_clips(renderer):
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = outer.ensure_set().create(W, H, "24/1")
    snd = tl.Source("C:/m/musica.wav", 0, 0, 24.0, "24/1", 1, 4.0, has_video=False, has_audio=True, audio_codec="pcm")
    inner.insert_media(snd, at=0)
    src = nested_src(outer, inner)
    assert not src.has_video and src.has_audio
    clips = outer.insert_media(src, at=0)
    assert [c.kind for c in clips] == [tl.AUDIO]
    assert sequence.media_info(outer).path.replace("\\", "/").startswith("C:/m/") and sequence.first_video_source(outer) is None
    assert export.job_inputs(sequence.media_info(outer), outer) == ["C:/m/musica.wav"]
    outer, inner, _c = pair()  # só clipes gerados dentro: como uma montagem de gerados
    assert sequence.first_video_source(outer) is None and sequence.legal_range(outer) is False
    assert sequence.missing_sources(outer) == []


def test_a_missing_file_inside_is_a_skipped_layer_and_a_notice(renderer):
    outer, inner, _c = pair()
    gone = fsrc()
    inner.insert_media(gone, at=0, vtrack=1)
    assert sequence.missing_sources(outer) == [gone.path]
    fl = sequence.grab(outer, 3, W, H)
    assert len(fl.layers[0].nested.layers.layers) == 1  # só o gerador; o arquivo que falta some, como fora
    agree(outer, frames=8)


def test_thumbnail_of_a_nested_source_is_empty_and_the_clip_is_not_generated(renderer):
    outer, inner, clip = pair()
    src = nested_src(outer, inner)
    assert sequence.source_thumbnail(src, 32, 18).shape == (18, 32, 3)
    assert sequence.source_thumbnail(src, 32, 18, rgba=True).shape == (18, 32, 4)
    assert not sequence.source_thumbnail(src, 32, 18).any()


def test_used_by_looks_at_the_whole_project():
    a = tl.Sequence(width=W, height=H, fps_str="24/1")
    a.insert_media(fsrc(), at=0)
    assert "titulos_geradores" not in modules.used_by(None, a)
    b = a.ensure_set().create(W, H, "24/1")
    b.insert_media(vsrc(), at=0)
    used = modules.used_by(None, a)
    assert "titulos_geradores" in used and "edicao" in used


def test_camera_profile_is_seen_inside_and_ignored_on_the_nested_clip_itself():
    outer, inner, clip = pair()
    assert not camera.uses_profiles(outer)
    clip.values["camera_entrada"] = "slog3"
    assert not camera.uses_profiles(outer)  # no próprio clipe de sequência não faz nada
    assert camera.uniforms(clip.values, outer.sources[clip.src], camera.Target()) is None
    inner.clips[0].values["camera_entrada"] = "slog3"
    assert camera.uses_profiles(outer) and camera.uses_profiles(inner)
    other = outer.siblings.create(W, H, "24/1")
    assert not camera.uses_profiles(other)


def test_nested_sequence_with_only_a_beep_says_it_has_sound(renderer):
    from pelicula import generators
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = outer.ensure_set().create(W, H, "24/1")
    assert not nested_src(outer, inner).has_audio
    inner.insert_media(generators.new_source(generators.LEADER, inner), at=0)
    assert not inner.has_audio and nested_src(outer, inner).has_audio
    assert [c.kind for c in outer.insert_media(nested_src(outer, inner), at=0)] == [tl.VIDEO, tl.AUDIO]
    assert audiomix.has_audio(inner)


# ------------------------------------------------------------------ na GPU: a montagem gêmea
LOOK = "vision3_500t"


@pytest.fixture(scope="module")
def clips_media(ffmpeg_ok, tmp_path_factory, sample_video):
    """(vídeo com som, outro vídeo com som, PNG com transparência parcial)."""
    import subprocess
    d = tmp_path_factory.mktemp("aninhada")
    longo, alfa = d / "longo.mp4", d / "alfa.png"
    subprocess.run([ffmpeg_ok, "-v", "error", "-y", "-nostdin", "-f", "lavfi", "-i", f"testsrc2=s={W}x{H}:r=24:d=4",
                    "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=4", "-c:v", "libx264", "-pix_fmt",
                    "yuv420p", "-c:a", "aac", "-shortest", str(longo)], check=True)
    pattern = "format=rgba,geq=r='255*X/320':g='128':b='255*Y/180':a='if(lt(X,80),0,if(lt(X,240),255*(X-80)/160,255))'"
    subprocess.run([ffmpeg_ok, "-v", "error", "-y", "-nostdin", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}", "-vf",
                    pattern, "-frames:v", "1", str(alfa)], check=True)
    return str(longo), sample_video, str(alfa)


def flat_montage(clips_media, qapp, background=(0.1, 0.2, 0.3)) -> tl.Sequence:
    """Cortes, buraco, transições (dissolver e de película), opacidade, geometria, PNG transparente e um título."""
    from pelicula import titles
    longo, curto, alfa = (media.probe_source(p) for p in clips_media)
    seq = tl.Sequence(width=W, height=H, fps_str="24/1", micro_fade=True, background=background)
    a = seq.insert_media(longo, at=0)[0]
    seq.trim_end(a.id, 18)
    b = seq.insert_media(curto, at=18)[0]
    seq.trim_end(b.id, 36)
    seq.set_values(b.id, {"entrada_tipo": "dissolver", "entrada_dur": 0.25, "saturacao": 0.4})
    c = seq.insert_media(longo, at=36)[0]
    seq.trim_end(c.id, 54)
    seq.set_values(c.id, {"entrada_tipo": "fusao", "entrada_dur": 0.25})
    d = seq.insert_media(longo, at=60, with_audio=False)[0]  # depois de um buraco: o fundo aparece
    seq.trim_end(d.id, 66)
    over = seq.insert_media(curto, at=6, vtrack=1, with_audio=False)[0]
    seq.trim_end(over.id, 26)
    seq.set_values(over.id, {"escala": 0.5, "rotacao": 15.0, "pos_x": 0.1, "pos_y": -0.1, "opacidade": 0.6})
    png = seq.insert_media(alfa, at=10, vtrack=2, with_audio=False)[0]
    seq.trim_end(png.id, 44)
    title = seq.insert_media(titles.new_source(seq), at=4, vtrack=3)[0]
    seq.trim_end(title.id, 50)
    seq.set_values(title.id, {"mesclagem": "tela"})
    return seq


def twin_of(flat: tl.Sequence, outer_background=(0.9, 0.0, 0.0)) -> tl.Sequence:
    """A mesma montagem dentro de uma sequência (os mesmos clipes, com os mesmos ids: a semente das transições vem deles)
    e, fora, um único clipe dela, sem ajuste nenhum. O fundo de fora é outro: não pode aparecer."""
    outer = tl.Sequence(width=flat.width, height=flat.height, fps_str=flat.fps_str, micro_fade=True,
                        background=outer_background)
    inner = tl.Sequence._from_block(flat._block_json(flat.block_format(), False))
    outer.ensure_set().add(inner)
    clips = outer.insert_media(nested_src(outer, inner), at=0)
    assert clips[0].dur == flat.duration and clips[0].src_in == 0.0
    return outer


def _look(look):
    from pelicula import presets
    return None if look is None else presets.builtin_values(look)


def _first_diff(a, b) -> str:
    d = np.abs(a.astype(np.float64) - b.astype(np.float64))
    return f"{int((d > 0).sum())} valores diferentes, máximo {d.max()}"


def exported_frames(engine, seq, values, depth, settings=None, scale=1.0):
    """Os quadros pelo caminho da exportação (`frame_pipeline` + `open_reader`)."""
    info = sequence.media_info(seq)
    s = settings or export.ExportSettings()
    frames = export.frame_pipeline(info, values, s, seq, scale, depth)
    reader, skip = export.open_reader(info, frames, 0, seq.duration, None, media.Perf(), seq)
    assert skip == 0
    try:
        for i in range(seq.duration):
            yield frames.render(engine, reader.read(), i)
        assert reader.error == ""
    finally:
        reader.close()


def assert_twin_frames(engine, flat, twin, values, depth, **kw) -> None:
    n = 0
    for t, (a, b) in enumerate(zip(exported_frames(engine, flat, values, depth, **kw),
                                   exported_frames(engine, twin, values, depth, **kw))):
        assert a.dtype == b.dtype and a.shape == b.shape
        assert np.array_equal(a, b), f"quadro {t}: {_first_diff(a, b)}"
        n += 1
    assert n == flat.duration


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("depth", [8, 16])
@pytest.mark.parametrize("look", [None, LOOK])
def test_golden_twin_export_is_bit_identical(gl_engine, clips_media, qapp, depth, look):
    flat = flat_montage(clips_media, qapp)
    twin = twin_of(flat)
    assert sequence.legal_range(twin) == sequence.legal_range(flat)
    assert_twin_frames(gl_engine, flat, twin, _look(look), depth)


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("depth", [8, 16])
def test_golden_twin_without_effects_is_bit_identical(gl_engine, clips_media, qapp, depth):
    flat = flat_montage(clips_media, qapp)
    assert_twin_frames(gl_engine, flat, twin_of(flat), _look(LOOK), depth, settings=export.ExportSettings(no_effects=True))


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("look", [None, LOOK])
def test_golden_twin_preview_is_bit_identical(gl_engine, clips_media, qapp, look):
    """A prévia: tamanho reduzido, 8 bits, pontilhado, leitura por `grab`; e o "Salvar quadro": 16 bits, tamanho cheio."""
    from pelicula.frame import Recipe
    flat = flat_montage(clips_media, qapp)
    twin = twin_of(flat)
    values = _look(look)
    for t in range(flat.duration):
        got = []
        for s in (flat, twin):
            size = sequence.canvas_size(s, 90)
            r = Recipe.for_source(values, 24.0, 8, legal=sequence.legal_range(s), seq=s, dither=True, size=size)
            got.append(r.render(gl_engine, sequence.grab(s, t, *size, 8, shutter=r.shutter), t))
        assert np.array_equal(got[0], got[1]), f"quadro {t}: {_first_diff(*got)}"
    for t in (8, 20, 40):
        got = []
        for s in (flat, twin):
            r = Recipe.for_source(values, 24.0, 16, legal=sequence.legal_range(s), seq=s, size=(W, H))
            got.append(r.render(gl_engine, sequence.grab(s, t, W, H, 16, hq=True, shutter=r.shutter), t))
        assert np.array_equal(got[0], got[1]), f"quadro {t}: {_first_diff(*got)}"


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_golden_twin_in_two_levels_and_other_output_sizes(gl_engine, clips_media, qapp):
    flat = flat_montage(clips_media, qapp)
    twin = twin_of(flat)
    top = tl.Sequence(width=W, height=H, fps_str="24/1", background=(0.0, 0.9, 0.0))
    twin.siblings.add(top)  # mais um nível por fora
    top.insert_media(nested_src(top, twin), at=0)
    assert_twin_frames(gl_engine, flat, top, _look(LOOK), 8)
    assert_twin_frames(gl_engine, flat, top, None, 16, scale=0.5)
    for fit in ("cortar", "bordas", "desfocado"):
        s = export.ExportSettings(frame="160x160", fit=fit)
        assert_twin_frames(gl_engine, flat, twin, _look(LOOK), 8, settings=s)

def _measure(a, b) -> float:
    return float(np.abs(a.astype(np.float64) - b.astype(np.float64)).max())


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_golden_twin_on_a_rounded_preview_canvas(gl_engine, clips_media, qapp):
    """Numa tela cujos lados pares mudam um pouco a proporção, cada clipe de dentro faz a mesma conta que fora."""
    from pelicula.frame import Recipe
    flat = flat_montage(clips_media, qapp)
    twin = twin_of(flat)
    size = sequence.canvas_size(flat, 101)
    assert size == (180, 100)
    for t in (2, 12, 20, 40):
        got = []
        for s in (flat, twin):
            r = Recipe.for_source(None, 24.0, 8, legal=True, seq=s, size=size)
            got.append(r.render(gl_engine, sequence.grab(s, t, *size, 8), t))
        assert np.array_equal(got[0], got[1]), f"quadro {t}: {_first_diff(*got)}"


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_golden_twin_with_the_shutter_of_the_look(gl_engine, clips_media, qapp):
    """O obturador mistura os quadros da janela dos clipes rápidos em qualquer nível (`Recipe._blend_layers`)."""
    longo = media.probe_source(clips_media[0])
    flat = tl.Sequence(width=W, height=H, fps_str="24/1")
    c = flat.insert_media(longo, at=0)[0]
    flat.set_speed(c.id, 3.0)
    flat.trim_end(c.id, 20)
    twin = twin_of(flat)
    values = {**_look(LOOK), "obturador_on": True, "obturador_angulo": "180"}
    fl = sequence.grab(twin, 5, W, H, 8, shutter=180.0)
    assert fl.layers[0].stack is None and fl.layers[0].nested.layers.layers[0].stack is not None
    assert_twin_frames(gl_engine, flat, twin, values, 8)


# ------------------------------------------------------------------ fundo da sequência interna
def _over_v1(clips_media, transparent: bool):
    """(sem aninhar: V1 + PNG + clipe a 50%; aninhada: V1 + um clipe da sequência com o PNG e o clipe a 50%)."""
    longo, curto, alfa = (media.probe_source(p) for p in clips_media)

    def fill(seq):
        png = seq.insert_media(alfa, at=0, vtrack=1 if seq is flat else 0, with_audio=False)[0]
        seq.trim_end(png.id, 18)
        c = seq.insert_media(curto, at=0, vtrack=2 if seq is flat else 1, with_audio=False)[0]
        seq.trim_end(c.id, 18)
        seq.set_values(c.id, {"escala": 0.6, "pos_x": 0.2, "opacidade": 0.5})

    flat = tl.Sequence(width=W, height=H, fps_str="24/1", background=(0.1, 0.2, 0.3))
    fill(flat)
    v1 = flat.insert_media(longo, at=0, with_audio=False)[0]
    flat.trim_end(v1.id, 18)
    outer = tl.Sequence(width=W, height=H, fps_str="24/1", background=(0.1, 0.2, 0.3))
    inner = outer.ensure_set().create(W, H, "24/1")
    inner.background, inner.transparent = (0.7, 0.1, 0.1), transparent
    fill(inner)
    v1 = outer.insert_media(longo, at=0, with_audio=False)[0]
    outer.trim_end(v1.id, 18)
    put(outer, inner, 0, vtrack=1)
    return flat, outer, inner


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("depth, limit", [(8, 1), (16, 3)])
def test_transparent_inner_sequence_shows_what_is_below_like_the_clips_outside(gl_engine, clips_media, depth, limit):
    from pelicula.frame import Recipe
    flat, outer, inner = _over_v1(clips_media, True)
    assert nested_src(outer, inner).has_alpha
    worst = 0.0
    for t in (0, 5, 11, 17):
        a = Recipe(None, 24.0, depth, seq=flat, size=(W, H)).render(gl_engine, sequence.grab(flat, t, W, H, depth), t)
        b = Recipe(None, 24.0, depth, seq=outer, size=(W, H)).render(gl_engine, sequence.grab(outer, t, W, H, depth), t)
        worst = max(worst, _measure(a, b))
    assert worst <= limit, f"diferença máxima {worst}"


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_opaque_inner_sequence_covers_what_is_below_with_its_background(gl_engine, clips_media):
    from pelicula.frame import Recipe
    flat, outer, inner = _over_v1(clips_media, False)
    assert not nested_src(outer, inner).has_alpha
    fl = sequence.grab(outer, 5, W, H)
    img = Recipe(None, 24.0, 8, seq=outer, size=(W, H)).render(gl_engine, fl, 5)
    alone = Recipe(None, 24.0, 8, seq=inner, size=(W, H)).render(gl_engine, sequence.grab(inner, 5, W, H), 5)
    assert np.array_equal(img, alone)  # o V1 de fora não aparece; o fundo vermelho de dentro, sim
    assert tuple(int(x) for x in img[90, 2]) == (179, 26, 26)


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_transparent_output_of_a_transparent_twin(gl_engine, clips_media):
    """Fundo transparente na saída: o alfa da interna chega à tela de fora, com a mesma conta."""
    from pelicula.frame import Recipe
    flat, outer, inner = _over_v1(clips_media, True)
    flat.clips = [c for c in flat.clips if c.track != 0]
    outer.clips = [c for c in outer.clips if c.track != 0]
    flat.transparent = outer.transparent = True
    worst = 0.0
    for t in (0, 5, 11):
        a = Recipe(None, 24.0, 16, seq=flat, size=(W, H), alpha=True).render(gl_engine, sequence.grab(flat, t, W, H, 16), t)
        b = Recipe(None, 24.0, 16, seq=outer, size=(W, H), alpha=True).render(gl_engine, sequence.grab(outer, t, W, H, 16), t)
        assert a.shape == b.shape == (H, W, 4)
        worst = max(worst, _measure(a, b))
        assert a[..., 3].min() == 0  # há transparência de verdade
    # sem cobertura a cor é a dos vizinhos (`CANVAS_OUT`), que dá a diferença: 3 em 65535 é só o erro do ponto flutuante
    assert worst <= 3, f"diferença máxima {worst}"


# ------------------------------------------------------------------ ajustes no próprio clipe de sequência
def _as_file(outer_clip, image, values_of, background=(0.0, 0.0, 0.0)):
    """A imagem da sequência como se fosse um arquivo: um clipe comum com os mesmos ajustes e o mesmo id."""
    s = tl.Sequence(width=W, height=H, fps_str="24/1", background=background)
    c = s.insert_media(fsrc(frames=outer_clip.dur, has_audio=False), at=0)[0]
    c.id = outer_clip.id
    s.set_values(c.id, values_of)
    return s, c


@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("name, values, limit", [
    ("cor", {"saturacao": 0.5, "exposicao": 0.5, "contraste": 0.3}, 8),
    ("detalhe", {"nitidez": 0.5, "clareza": 0.4}, 12),
    ("geometria", {"escala": 0.6, "rotacao": 20.0, "pos_x": 0.1, "espelhar_h": True, "corte_esq": 0.1}, 8),
    ("opacidade", {"opacidade": 0.4}, 8),
    ("mesclagem", {"mesclagem": "multiplicar", "opacidade": 0.8}, 8),
    ("mesclagem2", {"mesclagem": "tela"}, 8),
    ("fade", {"entrada_tipo": "preto", "entrada_dur": 1.0}, 8),
    ("pelicula", {"entrada_tipo": "queima", "entrada_dur": 1.0}, 8),
])
def test_adjustments_of_the_nested_clip_act_on_the_inner_image(gl_engine, clips_media, qapp, name, values, limit):
    """O clipe de sequência com um ajuste = a imagem de dentro como um arquivo com o mesmo ajuste (em 16 bits: a única
    diferença é a imagem de dentro arredondada no arquivo)."""
    from pelicula.frame import Recipe
    flat = flat_montage(clips_media, qapp)
    twin = twin_of(flat)
    clip = twin.clips[0]
    twin.set_values(clip.id, values)
    t = 10
    inner_img = Recipe(None, 24.0, 16, seq=flat, size=(W, H)).render(gl_engine, sequence.grab(flat, t, W, H, 16), t)
    s, c = _as_file(clip, inner_img, values, twin.background)
    layer = s.layers_at(t)[0]
    file_img = gl_engine.compose(sequence.FrameLayers(t, [sequence.LayerImage(layer, inner_img)]), s, W, H, 16)
    nested_img = gl_engine.compose(sequence.grab(twin, t, W, H, 16), twin, W, H, 16)
    assert not np.array_equal(nested_img, inner_img), "o ajuste não fez nada"
    assert _measure(nested_img, file_img) <= limit, _first_diff(nested_img, file_img)


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_adjustments_in_two_levels(gl_engine, clips_media, qapp):
    """Sequência numa sequência, cada nível com a sua geometria: igual a fazer os dois passos como arquivo."""
    flat = flat_montage(clips_media, qapp)
    middle_outer = twin_of(flat)  # `middle_outer` tem o clipe de `inner`
    top = tl.Sequence(width=W, height=H, fps_str="24/1", background=(0.0, 0.0, 0.5))
    middle_outer.siblings.add(top)
    mid_clip = middle_outer.clips[0]
    va = {"escala": 0.7, "pos_x": 0.1}
    vb = {"escala": 0.8, "pos_y": -0.1, "saturacao": -0.3}
    middle_outer.set_values(mid_clip.id, va)
    top_clip = top.insert_media(nested_src(top, middle_outer), at=0)[0]
    top.set_values(top_clip.id, vb)
    t = 12
    got = gl_engine.compose(sequence.grab(top, t, W, H, 16), top, W, H, 16)
    a = gl_engine.compose(sequence.grab(flat, t, W, H, 16), flat, W, H, 16)
    s1, _c = _as_file(mid_clip, a, va, middle_outer.background)
    b = gl_engine.compose(sequence.FrameLayers(t, [sequence.LayerImage(s1.layers_at(t)[0], a)]), s1, W, H, 16)
    s2, _c = _as_file(top_clip, b, vb, top.background)
    want = gl_engine.compose(sequence.FrameLayers(t, [sequence.LayerImage(s2.layers_at(t)[0], b)]), s2, W, H, 16)
    assert _measure(got, want) <= 40, _first_diff(got, want)  # aqui as imagens intermediárias são reamostradas em 16 bits


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_two_nested_clips_and_the_same_one_twice_do_not_share_a_canvas(gl_engine, clips_media, qapp):
    """Dois clipes de sequência no mesmo quadro, com quadros diferentes da mesma sequência, cada um na sua tela."""
    longo = media.probe_source(clips_media[0])
    outer = tl.Sequence(width=W, height=H, fps_str="24/1")
    inner = outer.ensure_set().create(W, H, "24/1")
    c = inner.insert_media(longo, at=0)[0]
    a = put(outer, inner)
    b = put(outer, inner, 0, vtrack=1)
    outer.trim_start(b.id, 24)
    outer.move(b.id, 0)
    outer.set_values(a.id, {"escala": 0.5, "pos_x": -0.25})
    outer.set_values(b.id, {"escala": 0.5, "pos_x": 0.25})
    fl = sequence.grab(outer, 3, W, H)
    assert [li.nested.layers.frame for li in fl.layers] == [3, 27]
    got = gl_engine.compose(fl, outer, W, H)
    img3 = gl_engine.compose(sequence.grab(inner, 3, W, H), inner, W, H)
    img27 = gl_engine.compose(sequence.grab(inner, 27, W, H), inner, W, H)
    half = lambda img: (img[:-1:2, :-1:2].astype(np.float64) + img[1::2, 1::2]) / 2  # a tela pela metade
    left, right = got[45:135, 0:160].astype(np.float64), got[45:135, 160:].astype(np.float64)
    assert np.abs(left - half(img3)).mean() < np.abs(left - half(img27)).mean()  # cada um mostra o seu quadro
    assert np.abs(right - half(img27)).mean() < np.abs(right - half(img3)).mean()
    assert c.start == 0


# ------------------------------------------------------------------ janela útil
@pytest.mark.gpu
@pytest.mark.ffmpeg
@pytest.mark.parametrize("depth", [8, 16])
def test_window_of_the_inner_sequence_without_a_look_is_bit_identical(gl_engine, clips_media, qapp, depth):
    flat = flat_montage(clips_media, qapp)
    flat.window = 2.39
    assert_twin_frames(gl_engine, flat, twin_of(flat), None, depth)


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_window_of_the_inner_sequence_under_a_look_keeps_the_grain_on_its_bars(gl_engine, clips_media, qapp):
    """LIMITE conhecido: a receita só pinta de preto exato as faixas da sequência exportada. As da interna são imagem: o
    look passa por elas. Dentro da janela o quadro continua bit a bit."""
    flat = flat_montage(clips_media, qapp)
    flat.window = 2.39
    twin = twin_of(flat)
    x, y, w, h = flat.window_rect(W, H)
    for a, b in zip(exported_frames(gl_engine, flat, _look(LOOK), 8), exported_frames(gl_engine, twin, _look(LOOK), 8)):
        assert np.array_equal(a[y:y + h, x:x + w], b[y:y + h, x:x + w])
        assert a[:y].max() == 0 and b[:y].max() > 0
        break


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_window_of_the_outer_sequence_limits_the_nested_clip(gl_engine, clips_media, qapp):
    from pelicula.frame import Recipe
    flat = flat_montage(clips_media, qapp)
    twin = twin_of(flat)
    twin.window = 2.39
    x, y, w, h = twin.window_rect(W, H)
    assert y > 0
    r = Recipe(_look(LOOK), 24.0, 8, seq=twin, size=(W, H))
    img = r.render(gl_engine, sequence.grab(twin, 20, W, H), 20)
    assert img[:y].max() == 0 and img[y + h:].max() == 0 and img[y:y + h].max() > 0


# ------------------------------------------------------------------ perfil de câmera lá dentro
@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_log_clip_with_its_own_profile_inside_converts_to_the_input_of_the_look(gl_engine, ffmpeg_ok, tmp_path):
    """S-Log3 e V-Log dentro da sequência: tela em float32, com os super-brancos, bit a bit como fora; e o perfil no próprio
    clipe de sequência não faz nada."""
    from test_entrada_camera import _log_file, slog3_cv, vlog_cv
    from pelicula import presets
    from pelicula.frame import Recipe
    if not media.has_zscale():
        pytest.skip("ffmpeg sem zscale (a leitura do log em float precisa dele)")
    pa, pb = tmp_path / "sony.mkv", tmp_path / "panasonic.mkv"
    _log_file(pa, slog3_cv)
    _log_file(pb, vlog_cv)
    sa, sb = media.probe_source(str(pa)), media.probe_source(str(pb))
    flat = tl.Sequence(width=64, height=16, fps_str="24/1")
    ca = flat.insert_media(sa, at=0, with_audio=False)[0]
    cb = flat.insert_media(sb, at=ca.end, with_audio=False)[0]
    flat.set_values(ca.id, {"camera_entrada": "slog3"})
    flat.set_values(cb.id, {"camera_entrada": "vlog"})
    twin = twin_of(flat)
    assert camera.uses_profiles(twin) and sequence.legal_range(twin) == sequence.legal_range(flat)
    values = dict(presets.builtin_values(LOOK), entrada="slog3")
    fl = sequence.grab(twin, ca.start, 64, 16, 16, hq=True)
    inner_img = fl.layers[0].nested.layers.layers[0].image
    assert inner_img.dtype == np.float32 and inner_img.max() > 1.0
    for t in (ca.start, cb.start):
        got = []
        for s in (flat, twin):
            r = Recipe.for_source(values, 24.0, 16, legal=sequence.legal_range(s), seq=s, size=(64, 16))
            got.append(r.render(gl_engine, sequence.grab(s, t, 64, 16, 16, hq=True), t))
        assert np.array_equal(got[0], got[1]), _first_diff(*got)
    twin.set_values(twin.clips[0].id, {"camera_entrada": "vlog", "camera_ei": "800"})
    r = Recipe.for_source(values, 24.0, 16, legal=sequence.legal_range(twin), seq=twin, size=(64, 16))
    again = r.render(gl_engine, sequence.grab(twin, cb.start, 64, 16, 16, hq=True), cb.start)
    assert np.array_equal(again, got[1])


# ------------------------------------------------------------------ tamanho reduzido, determinismo e o cache do quadro
@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_reduced_preview_is_close_to_the_full_size(gl_engine, clips_media, qapp):
    flat = flat_montage(clips_media, qapp)
    twin = twin_of(flat)
    twin.set_values(twin.clips[0].id, {"escala": 0.8, "pos_x": 0.05, "saturacao": 0.2})
    for t in (5, 20, 40):
        full = gl_engine.compose(sequence.grab(twin, t, W, H), twin, W, H).astype(np.float64)
        small = gl_engine.compose(sequence.grab(twin, t, W // 2, H // 2), twin, W // 2, H // 2).astype(np.float64)
        box = (full[::2, ::2] + full[1::2, ::2] + full[::2, 1::2] + full[1::2, 1::2]) / 4
        assert np.abs(box - small).mean() < 5.0, t


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_export_larger_than_the_sequence_is_close_but_not_identical(gl_engine, clips_media, qapp):
    """LIMITE conhecido: a tela interna nunca passa do tamanho da sequência (a regra de um vídeo). Numa saída maior que ela, a
    tela é ampliada de uma vez, e os clipes fora de uma sequência seriam ampliados um a um: fica perto, não bit a bit."""
    flat = flat_montage(clips_media, qapp)
    twin = twin_of(flat)
    fl = sequence.grab(twin, 20, W * 2, H * 2)
    assert fl.layers[0].nested.size == (W, H)
    a = gl_engine.compose(sequence.grab(flat, 20, W * 2, H * 2), flat, W * 2, H * 2).astype(np.float64)
    b = gl_engine.compose(fl, twin, W * 2, H * 2).astype(np.float64)
    assert 0 < np.abs(a - b).mean() < 3.0


@pytest.mark.gpu
@pytest.mark.ffmpeg
def test_same_frame_same_bits(gl_engine, clips_media, qapp):
    flat = flat_montage(clips_media, qapp)
    twin = twin_of(flat)
    first = gl_engine.compose(sequence.grab(twin, 12, W, H), twin, W, H).copy()
    gl_engine.compose(sequence.grab(twin, 40, W, H), twin, W, H)
    gl_engine.compose(sequence.grab(flat, 3, W, H), flat, W, H)
    assert np.array_equal(gl_engine.compose(sequence.grab(twin, 12, W, H), twin, W, H), first)


def _count_inner(engine, monkeypatch) -> list:
    """Conta as telas de sequência interna montadas de verdade."""
    calls: list = []
    real = engine._canvas

    def spy(fl, seq, size, path, *a):
        if path:
            calls.append((path, fl.frame))
        return real(fl, seq, size, path, *a)

    monkeypatch.setattr(engine, "_canvas", spy)
    return calls


@pytest.mark.gpu
def test_slow_motion_reuses_the_canvas_and_never_shows_a_stale_frame(gl_engine, renderer, monkeypatch):
    outer, inner, clip = pair()
    outer.set_speed(clip.id, 0.25)
    calls = _count_inner(gl_engine, monkeypatch)
    reader = sequence.SequenceReader(outer, W, H, 8, 0, 12)
    try:
        read = [reader.read() for _t in range(12)]
    finally:
        reader.close()
    got = [gl_engine.compose(fl, outer, W, H).copy() for fl in read]
    assert [c[1] for c in calls] == [0, 1, 2]  # 3 quadros de dentro em 12 de fora
    for t in range(12):
        fresh = gl_engine.compose(sequence.grab(outer, t, W, H), outer, W, H)
        assert np.array_equal(got[t], fresh), t
    assert not np.array_equal(got[0], got[4]) and np.array_equal(got[0], got[3])


@pytest.mark.gpu
def test_the_frame_cache_depends_on_every_parameter(gl_engine, renderer, monkeypatch):
    from dataclasses import replace
    outer, inner, clip = pair()
    inner.set_values(inner.clips[0].id, {"saturacao": -1.0})
    fl = sequence.grab(outer, 5, W, H)
    calls = _count_inner(gl_engine, monkeypatch)
    plain = gl_engine.compose(fl, outer, W, H).copy()
    assert len(calls) == 1
    assert np.array_equal(gl_engine.compose(fl, outer, W, H), plain) and len(calls) == 1  # a mesma coisa: reaproveita
    neutral = gl_engine.compose(fl, outer, W, H, neutral=True).copy()
    assert len(calls) == 2 and not np.array_equal(neutral, plain)  # neutro: os clipes de dentro sem a cor
    assert np.array_equal(gl_engine.compose(fl, outer, W, H), plain) and len(calls) == 3
    gl_engine.compose(fl, outer, W, H, light=(3, True))
    assert len(calls) == 4
    gl_engine.compose(fl, outer, W, H, camera=camera.Target())
    assert len(calls) == 5
    gl_engine.compose(fl, outer, W, H, camera=camera.Target(3, True, "sgamut3cine"))
    assert len(calls) == 6
    assert np.array_equal(gl_engine.compose(fl, outer, W, H), plain) and len(calls) == 7
    other = sequence.grab(outer, 5, W, H)  # outro objeto com o mesmo quadro: monta de novo, é o caminho seguro
    gl_engine.compose(other, outer, W, H)
    assert len(calls) == 8
    # outra sequência com o mesmo objeto de camadas: não reaproveita
    edited = outer.copy()
    n = replace(other.layers[0].nested, seq=edited.nested(edited.clips[0]))
    swapped = sequence.FrameLayers(5, [replace(other.layers[0], nested=n)])
    gl_engine.compose(swapped, outer, W, H)
    assert len(calls) == 9
    # e uma tela do mesmo caminho noutro tamanho é outra tela
    small = sequence.grab(outer, 5, W // 2, H // 2)
    assert small.layers[0].nested.size == (W // 2, H // 2)
    assert gl_engine.compose(small, outer, W // 2, H // 2).shape == (H // 2, W // 2, 3)
    assert len(calls) == 10
    assert np.array_equal(gl_engine.compose(fl, outer, W, H), plain)

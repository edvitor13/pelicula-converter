"""Perfil sugerido pelos metadados (1.6, `media.suggest_input`), sem arquivos de câmera: dicionários do ffprobe
montados à mão passam pelo mesmo `media._info_from` do `probe`. Mais o XML da Sony ao lado do vídeo, as etiquetas
guardadas (só marca e curva) e o preenchimento dos clipes novos do modo Edição (`camera.prefill`)."""

from __future__ import annotations

import dataclasses

import pytest

from pelicula import camera, media, params


def probe_dict(transfer="", primaries="", space="", codec="prores", pix="yuv422p10le", fmt_tags=None,
               stream_tags=None, fmt="mov,mp4,m4a,3gp,3g2,mj2"):
    vs = {"codec_type": "video", "codec_name": codec, "width": 1920, "height": 1080, "pix_fmt": pix,
          "r_frame_rate": "24/1", "duration": "2.0", "nb_frames": "48", "color_range": "tv"}
    if transfer:
        vs["color_transfer"] = transfer
    if primaries:
        vs["color_primaries"] = primaries
    if space:
        vs["color_space"] = space
    if stream_tags:
        vs["tags"] = dict(stream_tags)
    return {"streams": [vs], "format": {"format_name": fmt, "duration": "2.0", "tags": dict(fmt_tags or {})}}


APPLE = {"com.apple.quicktime.make": "Apple", "com.apple.quicktime.model": "iPhone 15 Pro"}

# (nome, caminho, dicionário do ffprobe, perfil sugerido)
CASES = [
    ("iphone_hdr_hlg", "C:/v/IMG_0001.MOV", probe_dict("arib-std-b67", "bt2020", "bt2020nc", "hevc", "yuv420p10le",
                                                       APPLE), "hlg"),
    ("hdr10_pq", "C:/v/hdr10.mkv", probe_dict("smpte2084", "bt2020", "bt2020nc", "hevc", "yuv420p10le"), "pq"),
    ("iphone_apple_log", "C:/v/IMG_0002.MOV", probe_dict("", "bt2020", "bt2020nc", fmt_tags=APPLE), "applelog"),
    ("iphone_sdr", "C:/v/IMG_0003.MOV", probe_dict("bt709", "bt709", "bt709", "hevc", "yuv420p", APPLE), None),
    ("hdr_vence_a_marca", "C:/v/IMG_0004.MOV", probe_dict("arib-std-b67", "bt2020", fmt_tags=APPLE), "hlg"),
    ("bt709_nunca_sugere_rec709", "C:/v/a.mp4", probe_dict("bt709", "bt709", "bt709", "h264", "yuv420p"), None),
    ("sem_etiquetas", "C:/v/b.mov", probe_dict(), None),
    ("bt2020_sem_marca", "C:/v/c.mov", probe_dict("", "bt2020", "bt2020nc"), None),
    ("arri_logc3", "C:/v/A001C001.mov", probe_dict(fmt_tags={"com.arri.camera.ColorGammaSxS": "LOG-C"}), "logc3"),
    ("arri_logc4", "C:/v/A002C001.mov", probe_dict(fmt_tags={"com.arri.camera.ColorGammaSxS": "LogC4"}), "logc4"),
    ("gamma_no_fluxo", "C:/v/d.mov", probe_dict(stream_tags={"com.example.gamma": "V-Log"}), "vlog"),
    ("transfer_canon", "C:/v/e.mxf", probe_dict(fmt_tags={"transfer_characteristic": "Canon Log 3"}), "clog3"),
    ("curva_fujifilm", "C:/v/f.mov", probe_dict(fmt_tags={"com.example.curve": "F-Log2 C"}), "flog2c"),
    ("titulo_vlog_ignorado", "C:/v/g.mp4", probe_dict(fmt_tags={"title": "Meu vlog de viagem",
                                                                 "comment": "S-Log3"}), None),
    ("dlog_m_fora", "C:/v/h.mp4", probe_dict(fmt_tags={"com.example.gamma": "D-Log M"}), None),
    ("sdr_da_camera", "C:/v/i.mp4", probe_dict(fmt_tags={"com.example.gamma": "S-Cinetone"}), None),
    ("rec709_da_camera", "C:/v/j.mp4", probe_dict(fmt_tags={"com.example.gamma": "rec709-xvycc"}), None),
    ("exr", "C:/v/plano.0001.exr", probe_dict(codec="exr", pix="gbrpf32le", fmt="exr_pipe"), "linear"),
    ("transfer_linear", "C:/v/k.mov", probe_dict("linear"), "linear"),
]


@pytest.mark.parametrize("name,path,data,want", CASES, ids=[c[0] for c in CASES])
def test_suggest_input_from_probe_dicts(name, path, data, want):
    info = media._info_from(path, data)
    assert media.suggest_input(info) == want
    assert want is None or want in dict(params.ENTRADAS)


def test_suggest_input_never_gives_rec709_and_handles_none():
    assert media.suggest_input(None) is None
    seen = {media.suggest_input(media._info_from(p, d)) for _n, p, d, _w in CASES}
    assert "rec709" not in seen and "cineon" not in seen


def test_only_camera_tags_are_kept():
    """Só a marca e as etiquetas de curva ficam no MediaInfo (local, data, número de série e título, não)."""
    data = probe_dict(fmt_tags={**APPLE, "com.apple.quicktime.location.ISO6709": "-23.5+046.6/",
                                "creation_time": "2026-10-01T10:00:00Z", "title": "Praia",
                                "com.arri.camera.ColorGammaSxS": "LOG-C", "com.arri.camera.SerialNumber": "123"},
                      stream_tags={"handler_name": "Core Media Video", "encoder": "Apple ProRes 422 HQ"})
    info = media._info_from("C:/v/x.mov", data)
    assert info.tags == {"com.apple.quicktime.make": "Apple", "com.arri.camera.ColorGammaSxS": "LOG-C"}
    # o resto do MediaInfo é o de sempre: as etiquetas não entram na comparação
    assert info == dataclasses.replace(info, tags={})
    assert media._info_from("C:/v/x.mov", probe_dict()).tags == {}


SONY_XML = """<?xml version="1.0" encoding="UTF-8"?>
<NonRealTimeMeta xmlns="urn:schemas-professionalDisc:nonRealTimeMeta:ver.2.20" lastUpdate="2026-10-01T10:00:00Z">
  <Duration value="240"/>
  <Device manufacturer="Sony" modelName="ILME-FX3" serialNo="1234567"/>
  <AcquisitionRecord>
    <Group name="CameraUnitMetadataSet">
      <Item name="CaptureGammaEquation" value="{gamma}"/>
      <Item name="CaptureColorPrimaries" value="S-Gamut3Cine"/>
      <Item name="CodingEquations" value="rec709"/>
    </Group>
  </AcquisitionRecord>
</NonRealTimeMeta>
"""


@pytest.mark.parametrize("gamma,want", [("s-log3-cine", "slog3"), ("s-log3", "slog3"), ("s-log2", "slog2"),
                                        ("rec2100-hlg", "hlg"), ("s-cinetone", None), ("rec709", None)])
def test_sony_sidecar_xml(tmp_path, gamma, want):
    video = tmp_path / "C0001.MP4"
    (tmp_path / "C0001M01.XML").write_text(SONY_XML.format(gamma=gamma), encoding="utf-8")
    tags = media.sidecar_tags(str(video))
    assert tags == {"sony.CaptureGammaEquation": gamma, "manufacturer": "Sony"}       # sem o número de série
    info = media._info_from(str(video), probe_dict("bt709", "bt709", "bt709", "h264", "yuv420p10le",
                                                    fmt="mov,mp4,m4a,3gp,3g2,mj2"))
    assert media.suggest_input(info) == want


def test_sidecar_is_optional_and_safe(tmp_path):
    video = tmp_path / "C0002.MP4"
    assert media.sidecar_tags(str(video)) == {}                                        # sem XML
    (tmp_path / "C0002M01.XML").write_text("<NonRealTimeMeta><Item name=", encoding="utf-8")
    assert media.sidecar_tags(str(video)) == {}                                        # XML quebrado
    assert media.sidecar_tags(str(tmp_path / "plano_%04d.png")) == {}                  # sequência de imagens
    img = media._info_from(str(tmp_path / "C0002.png"), probe_dict(codec="png", pix="rgb24", fmt="png_pipe"))
    assert img.is_image and img.tags == {}


@pytest.mark.parametrize("sug,look_in,transfer,want", [
    ("slog3", "rec709", "", "slog3"),        # câmera de outro perfil: preenche
    ("slog3", "slog3", "", None),            # a mesma do look: fica em "Igual ao do look"
    ("hlg", "slog3", "arib-std-b67", "hlg"),
    (None, "hlg", "bt709", "rec709"),        # vídeo comum numa montagem HDR
    (None, "pq", "iec61966-2-1", "rec709"),
    (None, "hlg", "bt2020-10", None),        # câmeras marcam HLG assim: não preenche
    (None, "slog3", "bt709", None),          # muitas câmeras marcam o log como BT.709: não preenche
    (None, "rec709", "bt709", None),
])
def test_prefill_for_new_clips(sug, look_in, transfer, want):
    info = media._info_from("C:/v/a.mov", probe_dict(transfer))
    assert camera.prefill(sug, dict(params.defaults(), entrada=look_in), info) == want
    assert camera.prefill(sug, None, None) == (None if sug in (None, "rec709") else sug)


def test_probe_source_hands_back_the_info(ffmpeg_ok, sample_video):
    infos = {}
    src = media.probe_source(sample_video, infos)
    assert list(infos) == [src.path] and infos[src.path].width == src.width
    assert media.probe_source(sample_video).path == src.path                            # sem `infos`, como antes

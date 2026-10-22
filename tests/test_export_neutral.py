"""Exportação por plataforma (1.4) com os campos novos no padrão: tudo sai exatamente como antes.

`export_cmds_1_3.json` guarda a impressão digital (SHA-256 dos argumentos) do comando do codificador que a
versão 1.3.1 (`eba2d45`) montava para uma matriz de ajustes antigos (todas as qualidades prontas, todo codec,
recipiente e formato de cor, cada modo de áudio, trecho, tamanho, fps e som da mixagem). Os ajustes sem os campos
novos (um `to_dict()` antigo) e os ajustes com os campos novos no padrão neutro têm que dar o mesmo comando,
argumento por argumento. Para regenerar a referência a partir de outra versão do `export.py` (só se a mudança
for de propósito): `python tests/test_export_neutral.py caminho/do/export.py`.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pelicula import export, media  # noqa: E402
from pelicula.export import ExportSettings  # noqa: E402

GOLDEN = Path(__file__).with_name("export_cmds_1_3.json")
OLD_KEYS = ("codec", "container", "pix", "quality", "preset", "profile", "bitrate", "resolution", "fps", "audio",
            "tune_grain", "dither", "threads", "priority", "hwaccel", "gpu", "buffer")
NEW_KEYS = ("platform", "frame", "fit", "target_mb", "maxrate", "loudness", "true_peak", "net_grain")
SEP = chr(31)  # separador dos argumentos na impressão digital (nenhum argumento tem esse caractere)


def _info(**kw) -> media.MediaInfo:
    base = dict(path="C:/videos/entrada.mp4", width=1920, height=1080, fps=24.0, fps_str="24/1", frames=240,
                duration=10.0, pix_fmt="yuv420p", bit_depth=8, codec="h264", profile="High", bitrate=20_000_000,
                color_space="bt709", color_range="tv", color_transfer="bt709", color_primaries="bt709",
                has_audio=True, audio_codec="aac", container="mov,mp4,m4a,3gp,3g2,mj2", is_image=False)
    base.update(kw)
    return media.MediaInfo(**base)


INFOS = {
    "deitado": _info(),
    "vertical_pcm": _info(width=1080, height=1920, audio_codec="pcm_s16le"),
    "sem_som": _info(width=1280, height=720, has_audio=False, audio_codec=""),
    "prores": _info(codec="prores", profile="HQ", pix_fmt="yuv422p10le", bit_depth=10, audio_codec="pcm_s24le"),
    "imagem": _info(path="C:/fotos/foto.png", width=3000, height=2000, frames=1, duration=0.0, codec="png",
                    has_audio=False, audio_codec="", is_image=True),
}


def matrix(ex) -> list[tuple[str, str, dict, float, str | None]]:
    """(nome, info, ajustes antigos, início em s, som da mixagem) — só chaves que a 1.3.1 conhecia."""
    out = []
    for name in ("deitado", "prores", "imagem"):
        for key, _label, s in ex.quality_presets(INFOS[name]):
            d = {k: getattr(s, k) for k in OLD_KEYS}
            out.append((f"qualidade:{name}:{key}", name, d, 0.0, None))
    for codec, c in ex.CODECS.items():
        info = "imagem" if c.get("image") else "deitado"
        combos = {(ext, c["pix"][0]) for ext in c["exts"]} | {(c["exts"][0], pix) for pix in c["pix"]}
        for ext, pix in sorted(combos):
            d = dict(codec=codec, container=ext, pix=pix, quality=float(c.get("qrange", (0, 20))[1] // 2),
                     preset=(c.get("presets") or [""])[-1], profile=(c.get("profiles") or [("", "")])[-1][0],
                     audio="aac192", tune_grain=bool(c.get("grain")), threads=3)
            out.append((f"codec:{codec}:{ext}:{pix}", info, d, 0.0, None))
        if c.get("rc") in ("crf", "cq", "gq", "qp") and not c.get("image"):
            d = dict(codec=codec, container=c["exts"][0], pix=c["pix"][0], bitrate=12.5, audio="aac320", threads=0)
            out.append((f"taxa:{codec}", "deitado", d, 0.0, None))
    for audio in ("copy", "aac320", "aac192", "mp3", "opus", "pcm24", "none"):
        for container in ("mp4", "mov", "mkv"):
            for info, start in (("deitado", 0.0), ("deitado", 2.5), ("vertical_pcm", 2.5), ("sem_som", 0.0)):
                d = dict(codec="x264", container=container, pix="yuv420p", quality=18, preset="medium",
                         audio=audio, tune_grain=True)
                out.append((f"som:{audio}:{container}:{info}:{start}", info, d, start, None))
        d = dict(codec="x264", container="mp4", pix="yuv420p", quality=18, preset="medium", audio=audio)
        out.append((f"mixagem:{audio}", "deitado", d, 1.5, "C:/tmp/pelicula_som_1.wav"))
    for audio in ("copy", "opus"):
        d = dict(codec="vp9", container="webm", pix="yuv420p", quality=30, preset="2", audio=audio)
        out.append((f"webm:{audio}", "deitado", d, 2.5, None))
    for audio in ("copy", "aac192", "pcm24"):
        d = dict(codec="xvid", container="avi", pix="yuv420p", quality=3, audio=audio)
        out.append((f"avi:{audio}", "vertical_pcm", d, 2.5, None))
    for res in ("original", "2160", "720", "480"):
        for fps in ("original", "30000/1001", "12"):
            d = dict(codec="x265", container="mp4", pix="yuv420p10le", quality=20, preset="slow", resolution=res,
                     fps=fps, audio="aac192", tune_grain=True)
            out.append((f"tamanho:{res}:{fps}", "vertical_pcm", d, 0.0, None))
    return out


def command(ex, info_name: str, s, start: float, mix: str | None) -> list[str]:
    info = INFOS[info_name]
    w, h = ex.output_size(info, s)
    fps = info.fps_str if s.fps == "original" else s.fps
    depth = 16 if ex.high_depth(s) else 8
    cmd = ex.build_encoder_cmd(f"saida.{s.container}", info, s, w, h, fps, depth, start, 4.0, "pipe:0",
                               audio_path=mix)
    return ["ffmpeg"] + cmd[1:]


def digest(cmd: list[str]) -> str:
    return hashlib.sha256(SEP.join(cmd).encode("utf-8")).hexdigest()[:24]


@pytest.fixture
def fake_ffmpeg(monkeypatch):
    """Comando sem procurar o ffmpeg de verdade; todo codificador "existe" (as qualidades de GPU entram)."""
    monkeypatch.setattr(media, "ffmpeg", lambda: "ffmpeg")
    monkeypatch.setattr(export, "available", lambda key: True)
    return "ffmpeg"


def _golden() -> dict[str, str]:
    return json.loads(GOLDEN.read_text(encoding="utf-8"))


def test_reference_covers_the_whole_matrix(fake_ffmpeg):
    names = [name for name, *_rest in matrix(export)]
    assert len(names) == len(set(names)) > 150
    assert set(names) == set(_golden()), "a matriz mudou: regenere a referência (veja o começo do arquivo)"


def test_old_settings_build_the_same_command_as_1_3(fake_ffmpeg):
    golden = _golden()
    for name, info, d, start, mix in matrix(export):
        old = ExportSettings.from_dict(d)  # um to_dict() antigo: sem nenhuma chave nova
        cmd = command(export, info, old, start, mix)
        assert digest(cmd) == golden[name], f"{name}: {' '.join(cmd)}"


def test_new_fields_at_their_defaults_change_nothing(fake_ffmpeg):
    golden = _golden()
    neutral = {k: getattr(ExportSettings(), k) for k in NEW_KEYS}
    assert neutral == {"platform": "", "frame": "", "fit": "cortar", "target_mb": 0.0, "maxrate": 0.0,
                       "loudness": 0.0, "true_peak": -1.0, "net_grain": False}
    for name, info, d, start, mix in matrix(export):
        s = ExportSettings.from_dict({**d, **neutral})
        assert s == ExportSettings.from_dict(d)
        cmd = command(export, info, s, start, mix)
        assert digest(cmd) == golden[name], f"{name}: {' '.join(cmd)}"
        assert not export.uses_target(s) and not export.wants_loudness(s)


def test_old_dict_round_trip_keeps_new_fields_neutral():
    old = {k: v for k, v in ExportSettings(codec="x265", container="mkv", pix="yuv420p10le").to_dict().items()
           if k in OLD_KEYS}
    s = ExportSettings.from_dict(old)
    assert (s.platform, s.frame, s.target_mb, s.maxrate, s.loudness, s.net_grain) == ("", "", 0.0, 0.0, 0.0, False)
    assert ExportSettings.from_dict(s.to_dict()) == s
    full = ExportSettings(platform="discord", frame="1080x1920", fit="desfocado", target_mb=20, maxrate=8,
                          loudness=-14, true_peak=-2, net_grain=True)
    assert ExportSettings.from_dict(json.loads(json.dumps(full.to_dict()))) == full


def _write_reference(path: str) -> None:
    """Gera a referência com o `export.py` indicado (por exemplo o da 1.3.1, tirado com `git show`)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("pelicula._export_ref", path)
    ref = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ref)
    media.ffmpeg = lambda: "ffmpeg"
    ref.available = lambda key: True
    data = {name: digest(command(ref, info, ref.ExportSettings.from_dict(d), start, mix))
            for name, info, d, start, mix in matrix(ref)}
    GOLDEN.write_text(json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(data)} comandos em {GOLDEN}")


if __name__ == "__main__":
    _write_reference(sys.argv[1])

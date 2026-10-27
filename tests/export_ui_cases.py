"""Casos da janela de exportação por plataforma e da área segura da prévia (rodados por test_export_ui.py
num subprocesso offscreen, com preferências num .ini temporário herdado da conftest)."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

APP = QApplication.instance() or QApplication([])

from pelicula import export, i18n, media, platforms  # noqa: E402
from pelicula.ui import prefs  # noqa: E402

i18n.set_language("pt_BR")
export.measure_speed = lambda *a, **k: 0.0  # a medição de velocidade não interessa aqui

from pelicula.ui import export_dialog  # noqa: E402
from pelicula.ui.export_dialog import ExportDialog  # noqa: E402
from pelicula.ui.viewer import SafeAreaButton, Viewer  # noqa: E402


@pytest.fixture(autouse=True)
def _ffmpeg(ffmpeg_ok):  # a janela lista os codecs que o ffmpeg tem
    return ffmpeg_ok


def info(w=1920, h=1080, seconds=10.0, audio=True, audio_codec="aac", image=False):
    return media.MediaInfo(path=os.path.join(os.getcwd(), "entrada.png" if image else "entrada.mp4"), width=w,
                           height=h, fps=24.0, fps_str="24/1", frames=1 if image else int(seconds * 24),
                           duration=0.0 if image else seconds, pix_fmt="yuv420p", bit_depth=8,
                           codec="png" if image else "h264", profile="", bitrate=0, color_space="bt709",
                           color_range="tv", color_transfer="bt709", color_primaries="bt709", has_audio=audio,
                           audio_codec=audio_codec if audio else "", container="mov,mp4", is_image=image)


def dialog(src=None, quality="mp4", platform="", in_out=None, frame=0, values=None) -> ExportDialog:
    dlg = ExportDialog(None, src or info(), values or {}, "Teste", in_out, last_dir=os.getcwd(), last_quality=quality,
                       frame=frame, last_platform=platform)
    dlg._est_timer.stop()
    dlg._preview_timer.stop()
    return dlg


def choose(dlg: ExportDialog, pid: str) -> None:
    i = dlg.platform.findData(pid)
    assert i >= 0, pid
    dlg.platform.setCurrentIndex(i)


# ------------------------------------------------------------------ lista de plataformas
def test_platform_list_is_grouped_with_headers_that_cannot_be_chosen():
    dlg = dialog()
    combo, model = dlg.platform, dlg.platform.model()
    assert combo.itemData(0) == "" and dlg.platform_id() == ""
    headers = [i for i in range(combo.count()) if combo.itemData(i) is None]
    assert len(headers) == len(platforms.GROUPS)
    assert all(not model.item(i).isEnabled() for i in headers)
    ids = [combo.itemData(i) for i in range(combo.count()) if combo.itemData(i)]
    assert ids == [p.id for _g, _l, items in platforms.grouped() for p in items]
    assert dlg.plimits.isHidden() and dlg.warn.isHidden()


def test_choosing_a_platform_fills_the_settings():
    dlg = dialog()
    choose(dlg, "tiktok")
    s = dlg.settings()
    assert s.platform == "tiktok" and s.frame == "1080x1920" and s.codec == "x264"
    assert s.fit == "desfocado"            # 16:9 → 9:16: nada some (encaixe automático)
    assert s.loudness == -14.0 and s.true_peak == -1.0
    assert export.output_size(dlg.info, s) == (1080, 1920)
    assert dlg.quality.currentData() == "custom" and "TikTok" in dlg.qdesc.text()
    assert "1080 × 1920" in dlg.plimits.text() and not dlg.plimits.isHidden()
    assert not dlg.res.isEnabled() and dlg.fit_box.isEnabled()
    # tudo continua editável depois
    dlg.fit_box.setCurrentIndex(dlg.fit_box.findData("bordas"))
    assert dlg.settings().fit == "bordas" and dlg.platform_id() == "tiktok"


def test_quality_preset_resets_the_platform():
    dlg = dialog()
    choose(dlg, "instagram_reels")
    assert dlg.settings().maxrate == 25
    dlg.quality.setCurrentIndex(dlg.quality.findData("mp4"))
    s = dlg.settings()
    assert dlg.platform_id() == "" and s.frame == "" and s.loudness == 0 and s.maxrate == 0 and s.target_mb == 0
    assert dlg.res.isEnabled() and not dlg.fit_box.isEnabled()


def test_none_platform_in_custom_mode_clears_what_the_platform_set():
    dlg = dialog()
    choose(dlg, "discord")
    assert dlg.settings().target_mb == 20
    dlg.platform.setCurrentIndex(0)
    s = dlg.settings()
    assert s.platform == "" and s.target_mb == 0 and s.loudness == 0 and s.frame == ""


def test_default_dialog_settings_are_neutral():
    dlg = dialog(quality="mp4")
    s, preset = dlg.settings(), dict((k, v) for k, _l, v in export.quality_presets(dlg.info))["mp4"]
    for key in export_dialog.PLATFORM_KEYS + ("net_grain",):
        assert getattr(s, key) == getattr(preset, key), key


def test_last_platform_is_restored():
    dlg = dialog(platform="youtube_shorts")
    assert dlg.platform_id() == "youtube_shorts" and dlg.settings().frame == "1080x1920"
    assert dialog(platform="nao_existe").platform_id() == ""


# ------------------------------------------------------------------ avisos e trecho
def test_duration_over_the_limit_warns_and_offers_the_first_part():
    dlg = dialog(info(seconds=75))
    choose(dlg, "instagram_stories")
    assert not dlg.trim_max.isHidden() and "60 s" in dlg.trim_max.text()
    assert "75 s" in dlg.warn.text() and not dlg.warn.isHidden()
    assert dlg.job().end_frame == -1
    dlg.trim_max.setChecked(True)
    job = dlg.job()
    assert (job.start_frame, job.end_frame) == (0, 60 * 24 - 1)
    assert "75 s" not in dlg.warn.text()
    choose(dlg, "youtube_1080")
    assert dlg.trim_max.isHidden() and dlg.job().end_frame == -1


def test_trim_starts_at_the_marked_range():
    dlg = dialog(info(seconds=100), in_out=(240, 2000))
    dlg.r_sel.setChecked(True)
    choose(dlg, "instagram_stories")
    dlg.trim_max.setChecked(True)
    assert (dlg.job().start_frame, dlg.job().end_frame) == (240, 240 + 60 * 24 - 1)


def test_estimated_size_over_the_limit_warns():
    dlg = dialog(info(seconds=120))
    choose(dlg, "x")
    dlg._est_token = 7
    dlg._est_done(7, 50.0, 6e6)  # 6 MB/s de vídeo → ~720 MB em 2 min, acima de 512 MB
    assert "512 MB" in dlg.warn.text()


def test_target_size_warns_about_two_passes_and_doubles_the_time():
    dlg = dialog(info(seconds=30))
    choose(dlg, "whatsapp")
    s = dlg.settings()
    assert s.target_mb == 16 and export.uses_target(s)
    assert "dobro do tempo" in dlg.warn.text()
    assert not dlg.qval.isEnabled() and not dlg.bitrate.isEnabled()
    dlg._est_token = 3
    dlg._est_done(3, 72.0)  # 720 quadros a 72 quadros/s: 10 s por passada
    assert "duas passadas" in dlg.est_label.text() and "22 s" in dlg.est_label.text()


def test_target_size_too_small_warns():
    dlg = dialog(info(seconds=600))
    choose(dlg, "discord")
    dlg.target.setValue(1)
    assert "é pouco para" in dlg.warn.text()


def test_copy_audio_is_reencoded_for_loudness_and_says_so():
    dlg = dialog(quality="original")
    assert dlg.settings().audio == "copy" and "recodificado" not in dlg.warn.text()
    dlg.loud.setCurrentIndex(dlg.loud.findData(-14.0))
    assert "recodificado" in dlg.warn.text() and dlg.peak.isEnabled()
    dlg.loud.setCurrentIndex(dlg.loud.findData(0.0))
    assert dlg.warn.isHidden() and not dlg.peak.isEnabled()


def test_loudness_rows_are_off_without_sound():
    dlg = dialog(info(audio=False))
    choose(dlg, "youtube_1080")
    assert not dlg.loud.isEnabled() and dlg.settings().loudness == 0


def test_target_row_only_for_x264_and_x265():
    dlg = dialog()
    assert dlg.form.isRowVisible(dlg.target)
    dlg.codec.setCurrentIndex(dlg.codec.findData("prores"))
    assert not dlg.form.isRowVisible(dlg.target) and dlg.settings().target_mb == 0


def test_manual_frame_uses_automatic_fit_and_net_grain_is_kept():
    dlg = dialog(info(1080, 1350))
    dlg.net_grain.setChecked(True)
    dlg.frame_box.setCurrentIndex(dlg.frame_box.findData("1080x1080"))
    assert dlg.settings().fit == "cortar"  # 4:5 → 1:1 é parecido: corta
    dlg.frame_box.setCurrentIndex(dlg.frame_box.findData("1920x1080"))
    assert dlg.settings().fit == "desfocado"
    choose(dlg, "instagram_feed_45")
    assert dlg.settings().net_grain and dlg.settings().frame == "1080x1350"


def test_images_have_no_platform_rows():
    dlg = dialog(info(3000, 4000, image=True), quality="img_png")
    assert dlg.platform_group.isHidden()
    for w in (dlg.frame_box, dlg.target, dlg.loud, dlg.net_grain):
        assert not dlg.form.isRowVisible(w)
    s = dlg.settings()
    assert (s.platform, s.frame, s.target_mb, s.loudness, s.net_grain) == ("", "", 0.0, 0.0, False)


def test_english_texts():
    i18n.set_language("en")
    try:
        dlg = dialog(info(seconds=75))
        choose(dlg, "instagram_stories")
        assert "up to 60 s" in dlg.plimits.text()
        assert "Export only the first 60 s" in dlg.trim_max.text()
    finally:
        i18n.set_language("pt_BR")


# ------------------------------------------------------------------ prévia do resultado
def test_preview_uses_the_export_path_or_says_unavailable():
    dlg = dialog(info(seconds=2))
    choose(dlg, "tiktok")
    args = dlg._preview_args()
    assert args[2].frame == "1080x1920" and args[5] == pytest.approx(400 / 1920)
    seen = []
    dlg._preview_worker.request = lambda token, a: seen.append((token, a))
    dlg._start_preview()
    dlg._start_preview()  # mesmas opções: não renderiza de novo
    assert len(seen) == 1
    dlg._preview_done(dlg._preview_token, None)
    assert dlg.preview.text() == "Prévia indisponível"
    import numpy as np
    dlg._preview_done(dlg._preview_token, np.zeros((400, 225, 3), np.uint8))
    assert not dlg.preview.pixmap().isNull() and "1080 × 1920" in dlg.preview_caption.text()


def test_preview_worker_renders_the_fitted_frame(sample_video):
    try:
        import moderngl
        moderngl.create_standalone_context(require=330).release()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"OpenGL 3.3 indisponível: {exc}")
    import time
    from pelicula import presets
    dlg = dialog(media.probe(sample_video), frame=5, values=presets.builtin_values("vision3_500t"))
    choose(dlg, "tiktok")
    dlg._preview_timer.stop()
    dlg._start_preview()
    t_end = time.time() + 30
    while dlg.preview.pixmap().isNull() and dlg.preview.text() != "Prévia indisponível" and time.time() < t_end:
        APP.processEvents()
        time.sleep(0.02)
    pm = dlg.preview.pixmap()
    assert not pm.isNull(), dlg.preview.text()
    assert abs(pm.width() / pm.height() - 9 / 16) < 0.02  # o quadro 1080 × 1920 com o vídeo deitado encaixado
    dlg.done(0)


# ------------------------------------------------------------------ área segura (só na tela)
def test_safe_area_button_starts_off_and_remembers():
    s = prefs.settings()
    s.remove("safe_area")
    b = SafeAreaButton(s)
    assert b.kind == "" and not b.isChecked()
    seen = []
    b.changed.connect(seen.append)
    b.actions_by_kind["tiktok"].trigger()
    assert b.kind == "tiktok" and b.isChecked() and seen == ["tiktok"] and s.value("safe_area") == "tiktok"
    assert SafeAreaButton(s).kind == "tiktok"
    b.set_kind("nao_existe")
    assert b.kind == "" and s.value("safe_area") == ""


def test_safe_area_geometry_follows_the_vertical_frame():
    v = Viewer()
    v.set_safe_area("shorts")
    f, rects = v.safe_geometry(QRectF(0, 0, 540, 960))     # 9:16 inteiro
    assert (f.width(), f.height()) == (540, 960)
    assert [tuple(round(x) for x in (r.x(), r.y(), r.width(), r.height())) for r in rects] == [(24, 144, 420, 480)]
    f, rects = v.safe_geometry(QRectF(0, 0, 1920, 1080))   # deitado: o recorte 9:16 do centro
    assert round(f.width()) == round(1080 * 9 / 16) and round(f.center().x()) == 960
    v.set_safe_area("titulo")
    f, rects = v.safe_geometry(QRectF(0, 0, 1920, 1080))   # título e ação: o quadro inteiro
    assert (f.width(), len(rects)) == (1920, 2)
    v.set_safe_area("nada")
    assert v.safe_area == "" and v.safe_geometry(QRectF(0, 0, 10, 10))[1] == []


def test_safe_area_is_drawn_only_on_screen():
    from PySide6.QtGui import QColor, QImage
    v = Viewer()
    v.resize(400, 400)
    img = QImage(90, 160, QImage.Format.Format_RGB888)
    img.fill(QColor(200, 200, 200))
    v.set_images(img, img)
    v.set_mode("proc")
    plain = v.grab().toImage()
    v.set_safe_area("tiktok")
    over = v.grab().toImage()
    assert plain != over                  # escurece onde a interface do TikTok fica
    assert img.pixelColor(0, 0) == QColor(200, 200, 200)  # a imagem (o que seria exportado) não muda

"""Legendas guardadas no projeto (1.5): o bloco "legendas" da montagem, o recurso do formato 3 e os
projetos antigos sem mudança. Sem Qt."""

from __future__ import annotations

import json

from pelicula import modules, project, subtitles as sb, timeline as tl
from pelicula.subtitles import Cue, Word


def src(path="C:/videos/a.mp4", frames=240) -> tl.Source:
    return tl.Source(path, 1920, 1080, 24.0, "24/1", frames, frames / 24.0, has_audio=True)


def seq_with(subs: sb.Subtitles | None = None) -> tl.Sequence:
    seq = tl.Sequence.for_source(src())
    seq.subtitles = subs
    return seq


def sample() -> sb.Subtitles:
    return sb.Subtitles(
        sources={"C:/videos/a.mp4": [Cue(0.5, 1.7, "Olá, pessoal.", (Word(0.5, 0.9, "Olá,"),
                                                                     Word(1.0, 1.7, "pessoal."))),
                                     Cue(2.0, 3.0, "Tudo bem?", italic=True)]},
        cues=[Cue(4.0, 5.0, "Fim", bold=True)], language="pt", style=sb.style("reels"), burn="digital")


def test_feature_is_registered_once_in_the_montage_registry():
    assert sb.FEATURE_ID in tl.FEATURES
    assert sb.FEATURE_ID not in project.FEATURES_V3
    assert sb.FEATURE_ID not in seq_with(None).features()
    assert sb.FEATURE_ID not in seq_with(sb.Subtitles()).features()
    assert sb.FEATURE_ID in seq_with(sample()).features()


def test_sequence_json_round_trip():
    seq = seq_with(sample())
    data = seq.to_json()
    assert data["formato"] == tl.FORMAT and data["legendas"] == sample().to_json()
    back = tl.Sequence.from_json(json.loads(json.dumps(data)))
    assert back.subtitles == sample()
    assert back.to_json() == data
    assert seq.copy().subtitles == sample()


def test_default_subtitles_are_not_written_and_the_json_is_the_old_one():
    seq = seq_with(None)
    old = seq.to_json()
    assert "legendas" not in old and old["formato"] == tl.FORMAT_BASE
    seq.subtitles = sb.Subtitles()
    assert seq.to_json() == old
    assert tl.Sequence.from_json(old).subtitles is None
    # Só o estilo ou o modo de gravar (sem legendas) ainda é guardado, sem pedir o formato novo.
    styled = seq_with(sb.Subtitles(style=sb.style("cinema"))).to_json()
    assert styled["legendas"]["estilo"]["id"] == "cinema" and styled["formato"] == tl.FORMAT_BASE


def test_project_format_3_lists_the_feature_and_round_trips(tmp_path):
    p = project.Project(media_path="C:/videos/a.mp4", sequence=seq_with(sample()).to_json())
    data = p.to_json()
    assert data["formato"] == project.FORMAT and sb.FEATURE_ID in data["recursos"]
    path = tmp_path / "legendas.plc"
    project.save(p, str(path))
    back = project.load(str(path))
    assert tl.Sequence.from_json(back.sequence).subtitles == sample()


def test_old_project_without_subtitles_keeps_its_format(tmp_path):
    p = project.Project(media_path="C:/videos/a.mp4", sequence=seq_with(None).to_json())
    assert p.to_json()["formato"] == project.FORMAT_EDIT and "recursos" not in p.to_json()


def test_relink_moves_the_cues_of_the_file():
    seq = seq_with(sample())
    seq.relink("C:/videos/a.mp4", "D:/novo/a.mp4")
    assert set(seq.subtitles.sources) == {"D:/novo/a.mp4"}
    assert [c.text for c in seq.subtitles.timeline_cues(seq)][:2] == ["Olá, pessoal.", "Tudo bem?"]


def test_history_snapshots_include_the_subtitles():
    seq = seq_with(None)
    h = tl.History(seq)
    seq.subtitles = sample()
    assert h.push(seq)
    seq.subtitles = None
    assert h.push(seq)
    assert h.undo().subtitles == sample()
    assert h.redo().subtitles is None


def test_json_is_stable_through_a_round_trip():
    """Números inteiros (tempos, margem do estilo pronto) saem como no JSON relido: desfazer e logo depois
    gravar o estado não cria um passo novo (que apagaria o refazer)."""
    subs = sb.Subtitles(sources={"C:/videos/a.mp4": [Cue(1, 2, "oi", (Word(1, 2, "oi"),))]}, cues=[Cue(3, 4, "x")])
    for style_id in sb.STYLES:
        subs.style = sb.STYLES[style_id]
        once = json.dumps(subs.to_json(), sort_keys=True)
        assert json.dumps(sb.Subtitles.from_json(json.loads(once)).to_json(), sort_keys=True) == once, style_id
    seq = seq_with(subs)
    h = tl.History(seq)
    assert not h.push(tl.Sequence.from_json(seq.to_json()))


def test_used_by_flags_the_subtitles_module():
    assert "legendas" in modules.used_by(None, seq_with(sample()))
    assert "legendas" in modules.used_by(None, None, subtitles=sample())
    assert "legendas" not in modules.used_by(None, seq_with(sb.Subtitles(style=sb.style("cinema"))))
    for mid in ("legendas", "silencios"):
        assert modules.exists(mid) and modules.default_enabled(mid)
    assert not modules.default_enabled("legendas_auto")

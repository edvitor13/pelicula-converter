"""Busca de sons CC0 (sons_cc0.py, 1.8, ARQUITETURA §47): as respostas do Openverse e do Freesound (só CC0), os
pedidos (endereço, User-Agent, tempo limite; nada de rede: o `urlopen` é falso), o download, a pasta de destino, o
crédito na fonte (JSON e formato 6) e o `.creditos.txt` da exportação (com e sem o som no trecho)."""

from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

from pelicula import __version__, project, sons_cc0
from pelicula import timeline as tl

OPENVERSE = {
    "result_count": 3, "page_count": 1, "page_size": 20, "page": 1,
    "results": [
        {"id": "a1b2", "title": "Whoosh  rápido", "creator": "Ana", "license": "cc0", "license_version": "1.0",
         "url": "https://cdn.example.org/whoosh.wav", "foreign_landing_url": "https://freesound.org/s/111/",
         "filetype": "wav", "duration": 1500, "provider": "freesound"},
        {"id": "c3d4", "title": "Porta", "creator": "Bia", "license": "by", "license_version": "4.0",
         "url": "https://cdn.example.org/porta.mp3", "foreign_landing_url": "https://example.org/porta",
         "duration": 3000},
        {"id": "e5f6", "title": "Chuva", "creator": None, "license": "cc0", "url": "https://cdn.example.org/chuva.ogg",
         "duration": None, "filetype": None},
        {"id": "x", "title": "Sem arquivo", "license": "cc0", "url": None},
    ],
}
FREESOUND = {
    "count": 3,
    "results": [
        {"id": 111, "name": "Whoosh rápido", "username": "Ana",
         "license": "http://creativecommons.org/publicdomain/zero/1.0/", "duration": 1.52,
         "url": "https://freesound.org/people/Ana/sounds/111/",
         "previews": {"preview-hq-mp3": "https://cdn.freesound.org/previews/0/111-hq.mp3",
                      "preview-lq-mp3": "https://cdn.freesound.org/previews/0/111-lq.mp3"}},
        {"id": 222, "name": "Sino", "username": "Caio", "license": "https://creativecommons.org/licenses/by/4.0/",
         "duration": 2.0, "url": "https://freesound.org/s/222/", "previews": {"preview-hq-mp3": "https://x/222.mp3"}},
        {"id": 333, "name": "Clique", "username": "Duda", "license": "Creative Commons 0", "duration": 0.2,
         "url": "https://freesound.org/s/333/", "previews": {"preview-lq-mp3": "https://cdn.freesound.org/333-lq.mp3"}},
    ],
}


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


class FakeNet:
    """`urlopen` falso: responde por prefixo do endereço e guarda os pedidos."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.requests = []

    def __call__(self, req, timeout=None):
        self.requests.append((req, timeout))
        url = req.full_url
        for prefix, answer in self.routes.items():
            if url.startswith(prefix):
                if isinstance(answer, BaseException):
                    raise answer
                body = answer if isinstance(answer, bytes) else json.dumps(answer).encode("utf-8")
                return FakeResponse(body)
        raise urllib.error.URLError("sem rota")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*_a, **_k):
        raise AssertionError("teste tentou usar a rede")
    monkeypatch.setattr(sons_cc0.urllib.request, "urlopen", refuse)


# ------------------------------------------------------------------ respostas
def test_openverse_keeps_only_cc0_with_a_file():
    got = sons_cc0.parse_openverse(OPENVERSE)
    assert [r.id for r in got] == ["a1b2", "e5f6"]
    w = got[0]
    assert (w.origem, w.titulo, w.autor, w.duracao, w.ext) == ("openverse", "Whoosh rápido", "Ana", 1.5, ".wav")
    assert w.pagina == "https://freesound.org/s/111/" and w.arquivo == w.previa == "https://cdn.example.org/whoosh.wav"
    rain = got[1]
    assert rain.autor == "Autor desconhecido" and rain.duracao == 0.0 and rain.ext == ".ogg"
    assert rain.pagina == rain.arquivo
    assert sons_cc0.parse_openverse({}) == [] and sons_cc0.parse_openverse([1, 2]) == []


def test_freesound_keeps_only_cc0_and_uses_the_hq_preview():
    got = sons_cc0.parse_freesound(FREESOUND)
    assert [r.id for r in got] == ["111", "333"]
    a = got[0]
    assert a.arquivo == a.previa == "https://cdn.freesound.org/previews/0/111-hq.mp3" and a.ext == ".mp3"
    assert a.pagina == "https://freesound.org/people/Ana/sounds/111/" and a.duracao == 1.52
    assert got[1].arquivo.endswith("333-lq.mp3")  # sem a de alta qualidade, a outra


def test_urls_and_request_headers():
    u = urllib.parse.urlparse(sons_cc0.openverse_url("porta rangendo"))
    q = urllib.parse.parse_qs(u.query)
    assert u.netloc == "api.openverse.org" and u.path == "/v1/audio/"
    assert q == {"q": ["porta rangendo"], "license": ["cc0"], "page_size": ["20"]}
    q = urllib.parse.parse_qs(urllib.parse.urlparse(sons_cc0.freesound_url(" chuva ", " KEY ")).query)
    assert q["query"] == ["chuva"] and q["token"] == ["KEY"]
    assert q["filter"] == ['license:"Creative Commons 0"']
    assert q["fields"] == ["id,name,username,license,previews,duration,url"]
    net = FakeNet({sons_cc0.OPENVERSE_URL: OPENVERSE})
    sons_cc0.search("whoosh", "", net)
    (req, timeout), = net.requests
    assert req.get_header("User-agent") == f"PeliculaConverter/{__version__}" and timeout == sons_cc0.TIMEOUT
    assert "@" not in req.get_header("User-agent")


def test_search_without_key_asks_only_openverse_and_merges_with_freesound():
    net = FakeNet({sons_cc0.OPENVERSE_URL: OPENVERSE, sons_cc0.FREESOUND_URL: FREESOUND})
    found, errors = sons_cc0.search("whoosh", "", net)
    assert errors == [] and [r.origem for r in found] == ["openverse", "openverse"]
    assert all("freesound.org/apiv2" not in r.full_url for r, _t in net.requests)
    found, errors = sons_cc0.search("whoosh", "KEY", net)
    # o mesmo som nas duas (título e autor): fica o do Freesound, que vem primeiro
    assert [(r.origem, r.id) for r in found] == [("freesound", "111"), ("freesound", "333"), ("openverse", "e5f6")]
    assert sons_cc0.search("   ", "KEY", net) == ([], [])


def test_errors_are_clear_and_one_source_failing_keeps_the_other():
    bad_key = urllib.error.HTTPError(sons_cc0.FREESOUND_URL, 401, "Unauthorized", {}, None)
    net = FakeNet({sons_cc0.OPENVERSE_URL: OPENVERSE, sons_cc0.FREESOUND_URL: bad_key})
    found, errors = sons_cc0.search("whoosh", "KEY", net)
    assert len(found) == 2 and len(errors) == 1 and "chave" in errors[0]
    net = FakeNet({sons_cc0.OPENVERSE_URL: urllib.error.URLError("offline")})
    found, errors = sons_cc0.search("whoosh", "", net)
    assert found == [] and "conexão" in errors[0]
    net = FakeNet({sons_cc0.OPENVERSE_URL: TimeoutError("timed out")})
    assert "não respondeu" in sons_cc0.search("x", "", net)[1][0]
    net = FakeNet({sons_cc0.OPENVERSE_URL: b"<html>erro</html>"})
    assert "não é uma lista" in sons_cc0.search("x", "", net)[1][0]


# ------------------------------------------------------------------ download e pastas
def test_download_writes_the_file_once_and_respects_the_size_limit(tmp_path):
    r = sons_cc0.parse_openverse(OPENVERSE)[0]
    net = FakeNet({"https://cdn.example.org/": b"RIFF" + b"\0" * 1000})
    dest = tmp_path / "sons" / sons_cc0.file_name(r)
    path = sons_cc0.download(r.arquivo, dest, net)
    assert Path(path).read_bytes()[:4] == b"RIFF" and len(net.requests) == 1
    assert sons_cc0.download(r.arquivo, dest, net) == path and len(net.requests) == 1  # já baixado
    with pytest.raises(sons_cc0.NetError, match="grande demais"):
        sons_cc0.download(r.arquivo, tmp_path / "grande.wav", net, max_bytes=100)
    assert not (tmp_path / "grande.wav").exists() and not list(tmp_path.glob("*.parte"))
    empty = FakeNet({"https://cdn.example.org/": b""})
    with pytest.raises(sons_cc0.NetError):
        sons_cc0.download(r.arquivo, tmp_path / "vazio.wav", empty)


def test_file_names_and_target_folders(tmp_path, tmp_appdata):
    r = sons_cc0.Result("freesound", "12/3", 'Porta: "rangendo"?', "Ana*", 1.0, "https://p", "https://a", "https://a",
                        ".mp3")
    name = sons_cc0.file_name(r)
    assert not set('<>:"/\\|?*') & set(name) and name.endswith(".mp3") and "freesound" in name
    assert sons_cc0.target_dir(str(tmp_path / "filme.plc")) == tmp_path / "filme_sons"
    unsaved = sons_cc0.target_dir(None)
    assert unsaved.name == "sons_cc0" and str(tmp_appdata) in str(unsaved)


# ------------------------------------------------------------------ crédito e exportação
def credited_seq():
    seq = tl.Sequence(320, 180, "24/1")
    seq.add_track(tl.AUDIO)
    music = tl.Source("C:/sons/whoosh.wav", fps=24.0, frames=1, duration=2.0, has_video=False, has_audio=True)
    music.credit = sons_cc0.credit_of(sons_cc0.parse_openverse(OPENVERSE)[0])
    seq.add_source(music)
    plain = tl.Source("C:/sons/outro.wav", fps=24.0, frames=1, duration=2.0, has_video=False, has_audio=True)
    seq.add_source(plain)
    seq.clips.append(tl.Clip(tl.new_id(), tl.AUDIO, music.path, 0, 48, 48, 0.0))
    seq.clips.append(tl.Clip(tl.new_id(), tl.AUDIO, plain.path, 1, 0, 200, 0.0))
    return seq, music


def test_credit_json_round_trip_and_format_6():
    seq, music = credited_seq()
    d = music.to_json()
    assert d["credito"] == {"titulo": "Whoosh rápido", "autor": "Ana", "licenca": "CC0 1.0",
                            "url": "https://freesound.org/s/111/", "origem": "Openverse"}
    back = tl.Sequence.from_json(json.loads(json.dumps(seq.to_json())))
    assert back.sources[music.path].credit == music.credit
    assert "credito" not in back.sources["C:/sons/outro.wav"].to_json()
    assert "credito_som" in seq.features() and seq.block_format() == tl.FORMAT_18
    data = project.Project(media_path="", sequence=seq.to_json(), mode="edicao").to_json()
    assert data["formato"] == project.FORMAT_18 == 6 and "credito_som" in data["recursos"]
    music.credit = {}
    assert "credito_som" not in seq.features()
    # crédito estranho no JSON: só as chaves conhecidas, como texto; sem título nem URL, nada
    s = tl.Source.from_json({"caminho": "a.wav", "credito": {"titulo": "X", "autor": 3, "extra": "y", "url": None}})
    assert s.credit == {"titulo": "X", "autor": "3"}
    assert tl.Source.from_json({"caminho": "a.wav", "credito": {"autor": "só"}}).credit == {}
    assert tl.Source.from_json({"caminho": "a.wav", "credito": "texto"}).credit == {}


def test_credits_file_only_when_the_range_uses_the_sound(tmp_path):
    seq, music = credited_seq()
    out = tmp_path / "filme.mp4"
    assert sons_cc0.write_credits(seq, 0, 48, str(out)) is None   # o som começa no quadro 48
    assert not list(tmp_path.glob("*.creditos.txt"))
    path = sons_cc0.write_credits(seq, 40, 60, str(out))
    assert path == str(tmp_path / "filme.creditos.txt")
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    assert lines[-1] == "Whoosh rápido — Ana — CC0 1.0 — https://freesound.org/s/111/"
    assert len([x for x in lines if " — " in x]) == 1
    seq.track(tl.AUDIO, 0).muted = True   # faixa muda: o som não toca
    assert sons_cc0.write_credits(seq, 40, 60, str(tmp_path / "b.mp4")) is None


def test_export_hook_sets_the_note_and_never_fails_the_job(tmp_path):
    seq, _m = credited_seq()

    class Job:
        sequence = seq
        out_path = str(tmp_path / "som.wav")
        note = ""

    job = Job()
    sons_cc0.export_credits(job, 0, -1)
    assert "som.creditos.txt" in job.note and (tmp_path / "som.creditos.txt").is_file()
    job2 = Job()
    job2.out_path = str(tmp_path / "nao_existe" / "x.mp4")
    sons_cc0.export_credits(job2, 0, -1)
    assert "Não foi possível" in job2.note
    job3 = Job()
    job3.sequence = None
    sons_cc0.export_credits(job3, 0, -1)
    assert job3.note == ""


def test_credits_inside_a_nested_sequence_and_for_the_project():
    outer = tl.Sequence(320, 180, "24/1")
    inner = outer.ensure_set().create(320, 180, "24/1")
    seq, music = credited_seq()
    inner.add_track(tl.AUDIO)
    for s in seq.sources.values():
        inner.add_source(s)
    inner.clips = [tl.Clip(c.id, c.kind, c.src, c.track, c.start, c.dur, c.src_in) for c in seq.clips]
    outer.siblings.sync()
    nested = outer.sources[f"sequencia:{inner.id}"]
    clip = outer.insert_media(nested, at=0)
    assert any(outer.nested(c) is inner for c in clip)
    assert sons_cc0.credits_for(outer, 0, 40) == []
    assert [c["titulo"] for c in sons_cc0.credits_for(outer, 40, 60)] == ["Whoosh rápido"]
    assert [c["titulo"] for c in sons_cc0.project_credits(outer)] == ["Whoosh rápido"]


# ------------------------------------------------------------------ exportação de verdade e o terminal
@pytest.fixture
def keep_language():
    from pelicula import i18n
    before = i18n.language()
    yield
    i18n.set_language(before)


def test_sound_export_and_cli_write_and_list_the_credits(ffmpeg_ok, tmp_path, capsys, keep_language):
    from pelicula import cli, export, sequence
    from test_somcache import write_wav
    wav = write_wav(tmp_path / "whoosh.wav", 330.0, secs=2.0)
    seq = tl.Sequence(320, 180, "24/1")
    seq.add_track(tl.AUDIO)
    src = tl.Source(wav, fps=24.0, frames=1, duration=2.0, has_video=False, has_audio=True)
    src.credit = sons_cc0.credit_of(sons_cc0.parse_openverse(OPENVERSE)[0])
    seq.add_source(src)
    seq.clips.append(tl.Clip(tl.new_id(), tl.AUDIO, wav, 0, 24, 24, 0.0))
    plain = write_wav(tmp_path / "base.wav", 220.0, secs=2.0)   # sem crédito, tocando o tempo todo
    seq.add_source(tl.Source(plain, fps=24.0, frames=1, duration=2.0, has_video=False, has_audio=True))
    seq.add_track(tl.AUDIO)
    seq.clips.append(tl.Clip(tl.new_id(), tl.AUDIO, plain, 1, 0, 48, 0.0))
    s = export.ExportSettings(sound_only="som", audio="pcm24")
    job = export.ExportJob(info=sequence.media_info(seq), values={}, settings=s, out_path=str(tmp_path / "a.wav"),
                           start_frame=0, end_frame=47, sequence=seq)
    export.run_job(job, None)
    assert job.status == "concluido", job.error
    assert (tmp_path / "a.creditos.txt").is_file() and "a.creditos.txt" in job.note
    job = export.ExportJob(info=sequence.media_info(seq), values={}, settings=s, out_path=str(tmp_path / "b.wav"),
                           start_frame=0, end_frame=10, sequence=seq)
    export.run_job(job, None)
    assert job.status == "concluido" and job.note == "" and not (tmp_path / "b.creditos.txt").exists()
    plc = tmp_path / "proj.plc"
    project.save(project.Project(values={}, preset_id="", sequence=seq.to_json()), str(plc))
    capsys.readouterr()
    assert cli.main(["info", str(plc), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["creditos"] == [src.credit]
    assert cli.main(["info", str(plc)]) == 0
    assert "Whoosh rápido — Ana — CC0 1.0 — https://freesound.org/s/111/" in capsys.readouterr().out
    out = tmp_path / "c.wav"
    assert cli.main(["exportar", str(plc), "-o", str(out), "--so-som", "-q"]) == 0
    assert (tmp_path / "c.creditos.txt").is_file()
